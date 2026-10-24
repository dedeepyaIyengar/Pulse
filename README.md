# Pulse — Code Detective

A lightweight static-analysis dashboard for Python. Paste code, press **Analyze Code**, and get a code health score, severity chart, and explained findings with fixes. Code is parsed with `ast` and **never executed**.

> Screenshots: add `docs/dashboard.png` and `docs/findings.png` here after your first run.

## Features
- Code workspace with sample loader, clear button and live line statistics
- Checks: syntax errors (with line), unused imports, `eval()`/`exec()`, bare `except`, long lines, TODO/FIXME comments, long functions, high branching complexity, missing docstrings on public functions
- Every finding has severity, category, line, explanation and recommendation
- Dashboard: score ring, findings count, high-priority count, functions, classes, lines, Plotly severity chart
- Severity filter and JSON report export (with disclaimer)

## Setup (Windows PowerShell)
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m streamlit run app.py
```
Opens at http://localhost:8501. Run tests with `python -m pytest`.

### Troubleshooting
- **Activation blocked** ("running scripts is disabled"): run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again.
- **`No module named streamlit/plotly/pytest`**: the venv is not active (prompt should start with `(.venv)`). Activate it, then `pip install -r requirements.txt`.
- **Port 8501 in use**: `python -m streamlit run app.py --server.port 8502`.

## Architecture
```
pulse-code-detective/
├── app.py              Streamlit UI and interaction logic
├── analyzer.py         Analysis engine: checks, metrics, scoring, report export
├── assets/styles.css   Dark glass theme, score ring animation, responsive rules
├── tests/test_analyzer.py
├── pytest.ini  requirements.txt  .gitignore  README.md
```
`analyzer.analyze(source)` returns one plain dict (`status`, `score`, `rating`, `metrics`, `findings`, `severity_counts`). The UI only renders that dict, so the score, chart, cards and JSON always agree.

## Score heuristic
`100 − 15 per High − 7 per Medium − 2 per Low` (Low penalties capped at 20; syntax errors cap the score at 40). It is a transparent, tunable heuristic — **not** an industry-standard metric.

## Limitations
Heuristic and file-local: no type checking, no data-flow or taint analysis, no cross-file imports. Unused-import detection can false-positive on dynamic use; complexity is an approximation of cyclomatic complexity. A clean report does not prove code is secure or correct.

## Future improvements
Upload `.py` files and folders · configurable thresholds · more rules (mutable defaults, `subprocess` with `shell=True`, hardcoded secrets) · inline line highlighting · score history · SARIF export · GitHub Action.

## Six-hour plan
1. **Setup (0:30)** venv, structure, requirements · 2. **Engine (1:45)** checks + tests · 3. **Dashboard (1:15)** state, metrics, chart, filter, export · 4. **Polish (1:00)** CSS, responsive, motion · 5. **Edge cases (0:45)** empty/invalid/huge input · 6. **Docs (0:45)** README, screenshots, push to GitHub.

## Resume description
**Pulse — Code Detective** (Python, Streamlit, Plotly): Built a static-analysis dashboard that parses Python with the `ast` module to detect security risks, unused imports, complexity and documentation gaps, produces a transparent 0–100 health score, and exports JSON reports. Wrote 16 pytest tests, including one proving submitted code is never executed.

## 2-minute demo script
1. "Pulse reviews Python the way a code reviewer would, without running it." Show the preloaded sample.
2. Point to the score and chart: "These come from the analyzer, not hardcoded values."
3. Filter to **High**: open the `eval()` finding and read its recommendation.
4. Edit the code (fix the bare `except`), press **Analyze Code**, show the score rise.
5. Break the syntax: show the line-numbered error and the capped score.
6. Download the JSON and mention the disclaimer. Close with the design choice: `ast` gives structure that regex cannot, and the analyzer is separate from the UI so it is testable.
