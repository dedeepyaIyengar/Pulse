"""Pulse analysis engine.

Static analysis of Python *source text*. The code is parsed with ast.parse()
and tokenize only; it is never compiled, imported, or executed.
"""
from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

TOOL_NAME = "Pulse — Code Detective"
SEVERITIES = ("High", "Medium", "Low")

# Thresholds (kept as constants so they are easy to explain and tune).
MAX_LINE_LENGTH = 100
MAX_FUNCTION_LINES = 50
MAX_COMPLEXITY = 10

# Score heuristic: start at 100, subtract a penalty per finding.
PENALTY = {"High": 15, "Medium": 7, "Low": 2}
LOW_PENALTY_CAP = 20      # many small style nits cannot sink a score alone
SYNTAX_ERROR_CAP = 40     # unparseable code cannot be rated "healthy"

SCORING_NOTE = (
    "Score = 100 minus 15 per High, 7 per Medium and 2 per Low finding "
    "(Low findings cost at most 20 points in total). Code with a syntax error "
    "is capped at 40. This is a transparent heuristic for this project, "
    "not an industry-standard quality metric."
)
DISCLAIMER = (
    "Pulse performs heuristic static analysis on source text. It can miss real "
    "problems and can flag code that is actually fine (for example, an import "
    "used only via dynamic lookup). A high score does not prove code is secure, "
    "correct, or maintainable. Always review findings with human judgment."
)


@dataclass(frozen=True)
class Finding:
    severity: str
    category: str
    title: str
    explanation: str
    recommendation: str
    line: Optional[int] = None


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def line_stats(source: str) -> Dict[str, int]:
    """Cheap text-only statistics (safe to call on every UI rerun)."""
    lines = (source or "").splitlines()
    blank = sum(1 for ln in lines if not ln.strip())
    comments = sum(1 for ln in lines if ln.strip().startswith("#"))
    return {
        "total_lines": len(lines),
        "blank_lines": blank,
        "comment_lines": comments,
        "code_lines": len(lines) - blank - comments,
        "characters": len(source or ""),
    }


# --------------------------------------------------------------------------- #
# Individual checks. Each returns a list of Finding objects.
# --------------------------------------------------------------------------- #
def _syntax_finding(exc: Exception) -> Finding:
    line = getattr(exc, "lineno", None)
    msg = getattr(exc, "msg", None) or str(exc) or "Invalid syntax"
    return Finding(
        "High", "Syntax", "Python syntax error",
        f"The parser could not read this code: {msg}. "
        "AST-based checks were skipped because there is no valid syntax tree.",
        "Fix the syntax error at the reported line, then analyze again.", line,
    )


def _check_imports(tree: ast.AST) -> List[Finding]:
    imported = []  # (bound name, line, display text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported.append((a.asname or a.name.split(".")[0], node.lineno, a.name))
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            for a in node.names:
                if a.name != "*":
                    imported.append((a.asname or a.name, node.lineno,
                                     f"{node.module or '.'}.{a.name}"))
    used = {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Load, ast.Del))}
    # Names re-exported through __all__ count as used.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            used |= {c.value for c in ast.walk(node.value)
                     if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return [
        Finding("Low", "Imports", f"Potentially unused import: {shown}",
                f"'{name}' is imported but never referenced in this file.",
                "Remove the import if it is not needed, or use it. Keep it only "
                "if it is a deliberate re-export or used dynamically.", line)
        for name, line, shown in imported if name not in used
    ]


def _check_dangerous_calls(tree: ast.AST) -> List[Finding]:
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ("eval", "exec")):
            name = node.func.id
            out.append(Finding(
                "High", "Security", f"Use of {name}()",
                f"{name}() runs arbitrary code. If any part of its input can come "
                "from a user, file, or network, an attacker may run their own code.",
                "Use ast.literal_eval() for literals, json.loads() for data, or a "
                "dictionary of allowed functions instead.", node.lineno))
    return out


def _check_bare_except(tree: ast.AST) -> List[Finding]:
    return [
        Finding("Medium", "Error Handling", "Bare except clause",
                "A bare 'except:' also catches KeyboardInterrupt and SystemExit "
                "and hides the real cause of failures.",
                "Catch specific exceptions (for example 'except ValueError:') or "
                "at least 'except Exception:' and log the error.", node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and node.type is None
    ]


def _complexity(func: ast.AST) -> int:
    """Approximate cyclomatic complexity: 1 + number of decision points.
    Nested functions, classes and lambdas are counted separately."""
    score, stack = 1, list(ast.iter_child_nodes(func))
    branch = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
              ast.IfExp, ast.comprehension)
    match_case = getattr(ast, "match_case", ())  # Python 3.10+
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, branch) or (match_case and isinstance(node, match_case)):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
        stack.extend(ast.iter_child_nodes(node))
    return score


def _check_functions(tree: ast.AST) -> List[Finding]:
    out = []
    func_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, func_types):
            continue
        length = (node.end_lineno or node.lineno) - node.lineno + 1
        if length > MAX_FUNCTION_LINES:
            out.append(Finding(
                "Medium", "Maintainability", f"Long function: {node.name}()",
                f"{node.name}() spans {length} lines (limit {MAX_FUNCTION_LINES}). "
                "Long functions are harder to read, test, and reuse.",
                "Split it into smaller helpers that each do one thing.", node.lineno))
        cx = _complexity(node)
        if cx > MAX_COMPLEXITY:
            sev = "High" if cx > 2 * MAX_COMPLEXITY else "Medium"
            out.append(Finding(
                sev, "Complexity", f"Many branching paths: {node.name}()",
                f"{node.name}() has an estimated complexity of {cx} "
                f"(limit {MAX_COMPLEXITY}) from if/loop/except/boolean branches.",
                "Extract conditions into helper functions, use early returns, or "
                "replace long if/elif chains with a lookup table.", node.lineno))
    # Public functions/methods that sit directly in a module or class body.
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.Module, ast.ClassDef)):
            for node in parent.body:
                if (isinstance(node, func_types) and not node.name.startswith("_")
                        and ast.get_docstring(node) is None):
                    out.append(Finding(
                        "Low", "Documentation", f"Missing docstring: {node.name}()",
                        f"Public function {node.name}() has no docstring, so its "
                        "purpose and parameters are undocumented.",
                        "Add a short docstring describing what it does, its "
                        "arguments and its return value.", node.lineno))
    return out


def _check_long_lines(lines: List[str]) -> List[Finding]:
    return [
        Finding("Low", "Style", "Unusually long line",
                f"This line is {len(ln.rstrip())} characters (limit {MAX_LINE_LENGTH}), "
                "which is hard to read side by side or in code review.",
                "Break the line using parentheses or intermediate variables.", i)
        for i, ln in enumerate(lines, 1) if len(ln.rstrip()) > MAX_LINE_LENGTH
    ]


_MARKER = re.compile(r"\b(TODO|FIXME)\b", re.IGNORECASE)


def _check_markers(source: str, lines: List[str]) -> List[Finding]:
    """Find TODO/FIXME inside real comments (tokenize ignores string contents)."""
    hits = []  # (line, marker)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                m = _MARKER.search(tok.string)
                if m:
                    hits.append((tok.start[0], m.group(1).upper()))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        # Broken code: fall back to a plain-text scan of '#' comments.
        hits = []
        for i, ln in enumerate(lines, 1):
            if "#" in ln:
                m = _MARKER.search(ln[ln.index("#"):])
                if m:
                    hits.append((i, m.group(1).upper()))
    return [
        Finding("Low", "Technical Debt", f"{mark} comment",
                f"A {mark} note marks unfinished or known-broken work.",
                "Resolve it, or convert it into a tracked issue and remove the "
                "comment.", line)
        for line, mark in hits
    ]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def _score(findings: List[Finding], syntax_error: bool) -> int:
    low = min(LOW_PENALTY_CAP, sum(PENALTY["Low"] for f in findings if f.severity == "Low"))
    rest = sum(PENALTY[f.severity] for f in findings if f.severity != "Low")
    score = max(0, 100 - rest - low)
    return min(score, SYNTAX_ERROR_CAP) if syntax_error else score


def _rating(score: int) -> str:
    return ("Excellent" if score >= 90 else "Good" if score >= 75
            else "Needs attention" if score >= 50 else "At risk")


def analyze(source: Optional[str]) -> dict:
    """Analyze Python source text and return a JSON-serializable result dict."""
    source = source or ""
    lines = source.splitlines()
    stats = line_stats(source)
    metrics = {**stats, "functions": 0, "classes": 0, "imports": 0}
    empty = {s: 0 for s in SEVERITIES}

    if not source.strip():
        return {"status": "empty", "score": None, "rating": "No code",
                "metrics": metrics, "findings": [], "severity_counts": empty}

    findings: List[Finding] = []
    status = "ok"
    try:
        tree = ast.parse(source)  # parse only: never compile/exec/import
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        status = "syntax_error"
        findings.append(_syntax_finding(exc))
        tree = None

    if tree is not None:
        nodes = list(ast.walk(tree))
        metrics["functions"] = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in nodes)
        metrics["classes"] = sum(isinstance(n, ast.ClassDef) for n in nodes)
        metrics["imports"] = sum(isinstance(n, (ast.Import, ast.ImportFrom)) for n in nodes)
        for check in (_check_imports, _check_dangerous_calls,
                      _check_bare_except, _check_functions):
            findings += check(tree)

    findings += _check_long_lines(lines)          # text checks also run on broken code
    findings += _check_markers(source, lines)

    unique = list(dict.fromkeys(findings))        # frozen dataclass -> hashable -> dedupe
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    unique.sort(key=lambda f: (rank[f.severity], f.line or 0, f.title))

    score = _score(unique, status == "syntax_error")
    counts = {s: sum(f.severity == s for f in unique) for s in SEVERITIES}
    return {"status": status, "score": score, "rating": _rating(score),
            "metrics": metrics, "findings": [asdict(f) for f in unique],
            "severity_counts": counts}


def build_report(result: dict) -> dict:
    """Wrap an analysis result in the exportable report structure."""
    return {
        "tool": TOOL_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": result["status"],
        "code_health_score": result["score"],
        "rating": result["rating"],
        "scoring_method": SCORING_NOTE,
        "metrics": result["metrics"],
        "severity_counts": result["severity_counts"],
        "findings": result["findings"],
        "disclaimer": DISCLAIMER,
    }


def report_to_json(result: dict) -> str:
    return json.dumps(build_report(result), indent=2, ensure_ascii=False)
