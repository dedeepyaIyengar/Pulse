"""Pulse — Code Detective: Streamlit UI.

Every number on screen comes from analyzer.analyze(); nothing is hardcoded.
"""
from __future__ import annotations

import html
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from analyzer import (DISCLAIMER, SCORING_NOTE, SEVERITIES, analyze,
                      line_stats, report_to_json)

ROOT = Path(__file__).parent
SEV_ICON = {"High": "▲", "Medium": "◆", "Low": "●"}   # shape + text, not color alone
SEV_COLOR = {"High": "#fb7185", "Medium": "#fbbf24", "Low": "#60a5fa"}

SAMPLE_CODE = r'''import os
import sys
import json

GREETING = "This deliberately long line is here to show the style check in action, it keeps going and going"


def load_config(path):
    # TODO: validate the schema before returning
    try:
        with open(path) as handle:
            return json.load(handle)
    except:
        return {}


def run_expression(user_input):
    """Evaluate an expression typed by a user."""
    return eval(user_input)


def classify(score, bonus, mode, retries, strict, verbose):
    label = "none"
    if score > 90 and bonus:
        label = "elite"
    elif score > 75 or bonus:
        label = "great"
    elif score > 50:
        label = "ok"
    for attempt in range(retries):
        if attempt > 3 and strict:
            label = "retry-heavy"
        elif mode == "fast" or mode == "turbo":
            label = "quick"
        if verbose and attempt % 2 == 0:
            print("attempt", attempt, "label", label)
    while strict and retries > 0:
        retries -= 1
    return label
'''


def esc(text) -> str:
    """HTML-escape user-derived text (and '$', which Streamlit may read as math)."""
    return html.escape(str(text)).replace("$", "&#36;")


# ------------------------------ state & callbacks ------------------------------ #
def run_analysis() -> None:
    code = st.session_state.code
    if not code.strip():
        st.session_state.result, st.session_state.analyzed_code = None, None
        st.session_state.notice = "The editor is empty. Paste some Python code, then press Analyze Code."
    else:
        st.session_state.result = analyze(code)
        st.session_state.analyzed_code = code
        st.session_state.notice = ""


def load_sample() -> None:
    st.session_state.code = SAMPLE_CODE
    run_analysis()


def clear_all() -> None:
    st.session_state.code = ""
    st.session_state.result = st.session_state.analyzed_code = None
    st.session_state.notice = ""


# ------------------------------ HTML builders ------------------------------ #
def metric(label, value, hot=False) -> str:
    return f'<div class="metric{" hot" if hot else ""}"><span class="m-val">{value}</span><span class="m-label">{label}</span></div>'


def score_card(res) -> str:
    score = res["score"]
    tone = "" if score >= 75 else "mid" if score >= 50 else "bad"
    note = ("A syntax error stopped structural checks, so the score is capped."
            if res["status"] == "syntax_error"
            else "Based on the findings below. Fewer and less severe findings raise the score.")
    return (f'<div class="card score-card"><div class="ring {tone}" style="--target:{score}">'
            f'<div class="ring-in"><b>{score}</b><small>/ 100</small></div></div>'
            f'<div><h3>{esc(res["rating"])}</h3><p>{note}</p></div></div>')


def metrics_grid(res) -> str:
    m, c = res["metrics"], res["severity_counts"]
    broken = res["status"] == "syntax_error"
    return ('<div class="grid">'
            + metric("Total findings", sum(c.values()))
            + metric("High priority", c["High"], hot=c["High"] > 0)
            + metric("Functions", "—" if broken else m["functions"])
            + metric("Classes", "—" if broken else m["classes"])
            + metric("Total lines", m["total_lines"])
            + metric("Code lines", m["code_lines"]) + "</div>")


def finding_card(f) -> str:
    sev = f["severity"]
    where = f'Line {f["line"]}' if f["line"] else "Whole file"
    return (f'<article class="finding sev-{sev.lower()}"><div class="finding-head">'
            f'<span class="sev-pill sev-{sev.lower()}">{SEV_ICON[sev]} {sev}</span>'
            f'<span class="tag">{esc(f["category"])}</span><span class="tag mono">{where}</span></div>'
            f'<h4>{esc(f["title"])}</h4><p>{esc(f["explanation"])}</p>'
            f'<p class="fix"><b>How to fix:</b> {esc(f["recommendation"])}</p></article>')


def severity_chart(counts) -> go.Figure:
    peak = max(counts.values())
    fig = go.Figure(go.Bar(
        x=list(SEVERITIES), y=[counts[s] for s in SEVERITIES],
        marker_color=[SEV_COLOR[s] for s in SEVERITIES],
        text=[counts[s] for s in SEVERITIES], textposition="outside",
        hovertemplate="%{x}: %{y} finding(s)<extra></extra>"))
    fig.update_layout(
        height=300, margin=dict(l=10, r=10, t=20, b=10), bargap=0.5,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Manrope, sans-serif", color="#c7ccf0"),
        xaxis=dict(showgrid=False),
        yaxis=dict(range=[0, peak + 1], gridcolor="rgba(148,163,255,.12)",
                   dtick=1 if peak <= 8 else None, title="Findings"))
    return fig


def section(title, sub="") -> None:
    st.markdown(f'<div class="sec"><h2>{title}</h2>{f"<p>{sub}</p>" if sub else ""}</div>', unsafe_allow_html=True)


# ------------------------------ page ------------------------------ #
st.set_page_config(page_title="Pulse — Code Detective", page_icon="🔎", layout="wide")
st.markdown(f"<style>{(ROOT / 'assets' / 'styles.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

if "code" not in st.session_state:                      # first visit: analyze the sample
    st.session_state.code = SAMPLE_CODE
    st.session_state.notice = ""
    run_analysis()

st.markdown(
    '<div class="hero"><h1>Pulse</h1><p class="tag-line">Read your Python the way a reviewer would.</p>'
    '<p class="desc">Paste a script and get a code health score, a list of risky patterns, and a concrete fix '
    'for each one. Your code is parsed as text and never run.</p>'
    '<div class="badges"><span class="badge">Python 3</span><span class="badge">ast module</span>'
    '<span class="badge">Streamlit</span><span class="badge">Plotly</span><span class="badge">pytest</span></div></div>',
    unsafe_allow_html=True)

left, right = st.columns([1.15, 1], gap="large")

with left:
    section("Source workspace", "Paste Python code, then analyze it.")
    st.text_area("Python source", key="code", height=460, label_visibility="collapsed",
                 placeholder="# Paste Python code here…")
    b1, b2, b3 = st.columns([1.4, 1, 1])
    b1.button("Analyze Code", type="primary", on_click=run_analysis, width="stretch")
    b2.button("Load Sample", on_click=load_sample, width="stretch")
    b3.button("Clear", on_click=clear_all, width="stretch")
    s = line_stats(st.session_state.code)
    st.markdown('<div class="chips">' + "".join(f'<span class="chip">{v:,} {k}</span>' for k, v in [
        ("lines", s["total_lines"]), ("code lines", s["code_lines"]),
        ("comments", s["comment_lines"]), ("characters", s["characters"])]) + "</div>", unsafe_allow_html=True)
    if st.session_state.notice:
        st.warning(st.session_state.notice)
    elif st.session_state.result and st.session_state.analyzed_code != st.session_state.code:
        st.markdown('<div class="stale">The editor changed since the last analysis. Press Analyze Code to refresh.</div>',
                    unsafe_allow_html=True)

result = st.session_state.result

with right:
    section("Analysis overview", "Results for the code you last analyzed.")
    if result is None:
        st.markdown('<div class="card empty"><b>No report yet</b>Paste code and press Analyze Code to see your score.</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(score_card(result) + metrics_grid(result), unsafe_allow_html=True)
        with st.expander("How is this score calculated?"):
            st.write(SCORING_NOTE)

if result is not None:
    section("Visual analytics", "How many findings sit at each severity level.")
    st.plotly_chart(severity_chart(result["severity_counts"]), width="stretch",
                    config={"displayModeBar": False})

section("Findings and recommendations", "Each card explains the issue and how to fix it.")
if result is None:
    st.markdown('<div class="card empty"><b>Nothing to show yet</b>Findings appear here after you analyze code.</div>',
                unsafe_allow_html=True)
else:
    counts = {"All Severities": len(result["findings"]), **result["severity_counts"]}
    choice = st.radio("Filter by severity", list(counts), horizontal=True, label_visibility="collapsed",
                      format_func=lambda k: f"{k} ({counts[k]})")
    shown = [f for f in result["findings"] if choice == "All Severities" or f["severity"] == choice]
    if not result["findings"]:
        st.markdown('<div class="card empty"><b>No findings detected</b>Pulse found none of the patterns it checks for. '
                    'That does not prove the code is correct or secure.</div>', unsafe_allow_html=True)
    elif not shown:
        st.markdown(f'<div class="card empty"><b>No {esc(choice)} findings</b>Choose another severity to see the rest.</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown("".join(finding_card(f) for f in shown), unsafe_allow_html=True)

section("Export", "Download the full report as JSON.")
st.download_button("Download JSON report",
                   data=report_to_json(result) if result else "{}",
                   file_name="pulse-report.json", mime="application/json", disabled=result is None)

st.markdown(f'<div class="foot"><b>Pulse — Code Detective</b> is a small static-analysis dashboard built on '
            f'Python’s <span class="mono">ast</span> module. {esc(DISCLAIMER)}</div>', unsafe_allow_html=True)
