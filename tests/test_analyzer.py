import json
import os

from analyzer import analyze, line_stats, report_to_json

CLEAN = '''"""Module docstring."""


def add(a, b):
    """Add two numbers."""
    return a + b
'''


def titles(result):
    return [f["title"] for f in result["findings"]]


def test_clean_code_has_no_findings():
    r = analyze(CLEAN)
    assert r["status"] == "ok" and r["findings"] == [] and r["score"] == 100


def test_syntax_error_reports_line_and_caps_score():
    r = analyze("x = 1\ndef broken(:\n    pass\n")
    assert r["status"] == "syntax_error"
    f = r["findings"][0]
    assert f["category"] == "Syntax" and f["severity"] == "High" and f["line"] == 2
    assert r["score"] <= 40


def test_unused_import_detected_and_used_import_ignored():
    r = analyze("import os\nimport sys\nprint(sys.argv)\n")
    unused = [t for t in titles(r) if "unused import" in t]
    assert unused == ["Potentially unused import: os"]


def test_import_used_via_attribute_is_not_flagged():
    assert not [t for t in titles(analyze("import os.path\nprint(os.path.sep)\n")) if "import" in t]


def test_eval_and_exec_are_high_severity_security_findings():
    r = analyze("eval('1+1')\nexec('x = 1')\n")
    sec = [f for f in r["findings"] if f["category"] == "Security"]
    assert len(sec) == 2 and all(f["severity"] == "High" for f in sec)
    assert [f["line"] for f in sec] == [1, 2]


def test_bare_except_detected_but_typed_except_is_fine():
    bad = analyze("try:\n    pass\nexcept:\n    pass\n")
    good = analyze("try:\n    pass\nexcept ValueError:\n    pass\n")
    assert "Bare except clause" in titles(bad)
    assert "Bare except clause" not in titles(good)


def test_todo_fixme_only_in_comments():
    r = analyze("# TODO: fix\nx = 'TODO in a string'\ny = 2  # fixme later\n")
    marks = [f for f in r["findings"] if f["category"] == "Technical Debt"]
    assert [f["line"] for f in marks] == [1, 3]


def test_empty_and_whitespace_and_none_input():
    for src in ("", "   \n\t\n", None):
        r = analyze(src)
        assert r["status"] == "empty" and r["score"] is None and r["findings"] == []


def test_long_line_long_function_complexity_and_docstring():
    body = "".join(f"    x{i} = {i}\n" for i in range(55))
    branches = "".join(f"    if a == {i}:\n        return {i}\n" for i in range(12))
    src = f"def big(a):\n{body}{branches}"
    src += "y = '" + "a" * 120 + "'\n"
    t = titles(analyze(src))
    assert "Long function: big()" in t
    assert "Many branching paths: big()" in t
    assert "Missing docstring: big()" in t
    assert "Unusually long line" in t


def test_private_functions_do_not_need_docstrings():
    assert "Missing docstring: _helper()" not in titles(analyze("def _helper():\n    return 1\n"))


def test_multiple_findings_sorted_deduped_and_counted():
    src = "import os\n# TODO: x\ntry:\n    eval('1')\nexcept:\n    pass\n"
    r = analyze(src)
    sevs = [f["severity"] for f in r["findings"]]
    assert sevs == sorted(sevs, key=["High", "Medium", "Low"].index)
    assert r["severity_counts"] == {"High": 1, "Medium": 1, "Low": 2}
    assert len(r["findings"]) == len({json.dumps(f, sort_keys=True) for f in r["findings"]})
    assert r["score"] == 100 - 15 - 7 - 4


def test_score_stays_within_bounds():
    assert analyze("eval('1')\n" * 30)["score"] == 0


def test_submitted_code_is_never_executed(tmp_path, monkeypatch):
    marker = tmp_path / "executed.txt"
    src = (f"import os\nos.environ['PULSE_RAN'] = '1'\n"
           f"open(r'{marker}', 'w').write('x')\nraise SystemExit(3)\n")
    monkeypatch.delenv("PULSE_RAN", raising=False)
    analyze(src)
    assert not marker.exists() and "PULSE_RAN" not in os.environ


def test_null_bytes_do_not_crash():
    assert analyze("x = 1\x00\n")["status"] in {"syntax_error", "ok"}


def test_json_report_is_valid_and_complete():
    data = json.loads(report_to_json(analyze("eval('1')\n")))
    for key in ("tool", "generated_at", "code_health_score", "metrics", "findings", "disclaimer"):
        assert key in data
    assert data["findings"][0]["recommendation"]


def test_line_stats():
    s = line_stats("a = 1\n\n# note\nb = 2\n")
    assert (s["total_lines"], s["blank_lines"], s["comment_lines"], s["code_lines"]) == (4, 1, 1, 2)
