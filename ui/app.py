"""
NL-to-SQL Agent — Streamlit Dashboard

Shows:
  - Question input
  - Generated SQL with attempt count
  - Result table
  - Full reasoning trace (including failed attempts)
  - Eval tab with accuracy breakdown

Launch:  streamlit run ui/app.py
"""

from __future__ import annotations

import csv
import sqlite3
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from tools.schema import describe_schema
from core.agent import NL2SQLAgent

DB_PATH = PROJECT_ROOT / "data" / "warehouse.db"
RESULTS_PATH = PROJECT_ROOT / "eval" / "results.csv"


# Page config

st.set_page_config(
    page_title="NL-to-SQL Agent",
    page_icon="🗃️",
    layout="wide",
)

st.markdown("""
<style>
    .sql-block {
        background: #1e1e2e;
        color: #cdd6f4;
        padding: 16px;
        border-radius: 8px;
        font-family: 'JetBrains Mono', 'Fira Code', monospace;
        font-size: 0.85em;
        white-space: pre-wrap;
        overflow-x: auto;
        border-left: 4px solid #89b4fa;
    }
    .error-block {
        background: #1e1e2e;
        color: #f38ba8;
        padding: 12px;
        border-radius: 6px;
        font-family: monospace;
        font-size: 0.82em;
        border-left: 4px solid #f38ba8;
    }
    .success-badge {
        color: #a6e3a1;
        font-weight: 600;
    }
    .attempt-badge {
        background: #313244;
        color: #cdd6f4;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.78em;
        font-weight: 500;
    }
    .trace-step {
        background: #181825;
        border: 1px solid #313244;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 10px;
    }
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# Session state

if "history" not in st.session_state:
    st.session_state.history = []



# Sidebar

with st.sidebar:
    st.markdown("## 🗃️ NL-to-SQL Agent")
    st.caption("Ask questions in plain English, get SQL + results.")

    st.markdown("---")
    st.markdown("### Example Questions")
    examples = [
        "How many orders were placed in 2017?",
        "What are the top 5 product categories by items sold?",
        "What is the average delivery time in days for delivered orders?",
        "Which seller has the highest average review score with at least 50 orders?",
        "What percentage of delivered orders were late?",
        "What is the monthly order count for 2018?",
    ]
    for ex in examples:
        if st.button(f"📝 {ex[:55]}...", key=f"ex_{hash(ex)}", use_container_width=True):
            st.session_state["prefill_question"] = ex
            st.rerun()

    st.markdown("---")
    st.markdown("### Query History")
    for i, entry in enumerate(reversed(st.session_state.history[-15:])):
        status = "✓" if entry["result"] is not None else "✗"
        st.caption(f"{status} {entry['question'][:50]}...")

    if st.session_state.history:
        if st.button("🗑️ Clear History", use_container_width=True):
            st.session_state.history = []
            st.rerun()



# Tabs
query_tab, eval_tab = st.tabs(["💬 Query Agent", "📊 Eval Results"])

# ═══════════════════════════════════════════════════════════════════════════
# QUERY TAB
# ═══════════════════════════════════════════════════════════════════════════
with query_tab:
    st.markdown("# Ask a question about the Olist e-commerce database")

    # Check database exists
    if not DB_PATH.exists():
        st.error(
            f"Database not found at `{DB_PATH}`.\n\n"
            "1. Download the Olist dataset from "
            "[Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)\n"
            "2. Unzip CSVs into `data/raw/`\n"
            "3. Run `python data/build_db.py`"
        )
        st.stop()

    # Check API key
    if not os.getenv("GEMINI_API_KEY"):
        st.error("Set `GEMINI_API_KEY` in your `.env` file to use the agent.")
        st.stop()

    # Question input
    prefill = st.session_state.pop("prefill_question", "")
    question = st.text_input(
        "Your question:",
        value=prefill,
        placeholder="e.g. Which product category has the highest revenue?",
    )

    col_run, col_model = st.columns([1, 2])
    with col_model:
        model_name = st.text_input(
            "Model",
            value=os.getenv("MODEL_NAME", "gemini-2.5-flash-preview-05-20"),
            label_visibility="collapsed",
        )

    if col_run.button("🚀 Run Query", type="primary", use_container_width=True) and question:
        con = sqlite3.connect(str(DB_PATH))
        schema_text = describe_schema(con)
        agent = NL2SQLAgent(model=model_name)

        with st.spinner("Generating SQL..."):
            result = agent.answer(con, question, schema_text)

        con.close()

        st.session_state.history.append({
            "question": question,
            **result,
        })
        st.rerun()

    # Display latest result
    if st.session_state.history:
        latest = st.session_state.history[-1]

        st.markdown("---")

        # Header with attempt badge
        header_col, badge_col = st.columns([4, 1])
        with header_col:
            st.markdown(f"**Q:** {latest['question']}")
        with badge_col:
            attempts = latest["attempts"]
            color = "#a6e3a1" if latest["result"] else "#f38ba8"
            st.markdown(
                f'<span class="attempt-badge">Attempt {attempts}/{3} · {latest["latency_s"]}s</span>',
                unsafe_allow_html=True,
            )

        # SQL output
        sql_col, result_col = st.columns([1, 1], gap="medium")

        with sql_col:
            st.markdown("#### Generated SQL")
            st.code(latest["sql"], language="sql")

        with result_col:
            st.markdown("#### Result")
            if latest["result"]:
                df = pd.DataFrame(
                    latest["result"]["rows"],
                    columns=latest["result"]["columns"],
                )
                st.dataframe(df, use_container_width=True, height=300)
            else:
                last_err = latest["trace"][-1]["error"] if latest["trace"] else "Unknown error"
                st.markdown(
                    f'<div class="error-block">❌ Query failed after {attempts} attempts\n\n{last_err}</div>',
                    unsafe_allow_html=True,
                )

        # Reasoning trace (shows failed attempts — this is deliberate)
        with st.expander(f"🔍 Full Reasoning Trace ({len(latest['trace'])} step{'s' if len(latest['trace']) != 1 else ''})"):
            for step in latest["trace"]:
                attempt_num = step["attempt"]
                is_error = step["error"] is not None

                st.markdown(f"**Attempt {attempt_num}**")

                if step["reasoning"]:
                    st.markdown(f"💭 *{step['reasoning']}*")

                st.code(step["sql"], language="sql")

                if is_error:
                    st.markdown(
                        f'<div class="error-block">⚠️ {step["error"]}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown('<span class="success-badge">✓ Executed successfully</span>', unsafe_allow_html=True)

                if attempt_num < len(latest["trace"]):
                    st.markdown("---")


# ═══════════════════════════════════════════════════════════════════════════
# EVAL TAB
# ═══════════════════════════════════════════════════════════════════════════
with eval_tab:
    st.markdown("# Evaluation Results")
    st.caption("Run `python eval/run_eval.py` to generate results, then refresh this page.")

    if RESULTS_PATH.exists():
        df = pd.read_csv(RESULTS_PATH)

        # Summary metrics
        total = len(df)
        llm_correct = df["llm_correct"].sum()
        baseline_correct = df["baseline_correct"].sum()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Questions", total)
        m2.metric("LLM Accuracy", f"{100 * llm_correct / total:.1f}%")
        m3.metric("Baseline Accuracy", f"{100 * baseline_correct / total:.1f}%")
        m4.metric("Avg Latency", f"{df['llm_latency_s'].mean():.1f}s")

        st.markdown("---")

        # By difficulty
        st.markdown("### Accuracy by Difficulty")
        diff_summary = []
        for diff in ["easy", "medium", "hard"]:
            subset = df[df["difficulty"] == diff]
            if len(subset) > 0:
                diff_summary.append({
                    "Difficulty": diff.capitalize(),
                    "Count": len(subset),
                    "LLM Correct": int(subset["llm_correct"].sum()),
                    "LLM %": f"{100 * subset['llm_correct'].mean():.0f}%",
                    "Baseline Correct": int(subset["baseline_correct"].sum()),
                    "Baseline %": f"{100 * subset['baseline_correct'].mean():.0f}%",
                })
        st.dataframe(pd.DataFrame(diff_summary), use_container_width=True, hide_index=True)

        # Attempt distribution
        st.markdown("### Attempt Distribution")
        attempt_dist = df["llm_attempts"].value_counts().sort_index()
        st.bar_chart(attempt_dist)

        # Full results table
        st.markdown("### Per-Question Results")
        display_cols = ["id", "difficulty", "question", "llm_correct", "llm_attempts", "llm_latency_s", "baseline_correct"]
        st.dataframe(
            df[display_cols].style.applymap(
                lambda v: "color: #a6e3a1" if v is True else ("color: #f38ba8" if v is False else ""),
                subset=["llm_correct", "baseline_correct"],
            ),
            use_container_width=True,
            height=500,
        )

        # Failures detail
        failures = df[df["llm_correct"] == False]
        if len(failures) > 0:
            st.markdown("### ❌ Failed Questions")
            for _, row in failures.iterrows():
                with st.expander(f"Q{int(row['id'])}: {row['question']}"):
                    st.markdown(f"**Difficulty:** {row['difficulty']}")
                    st.markdown(f"**Tags:** {row['tags']}")
                    st.markdown("**LLM SQL:**")
                    st.code(row["llm_sql"], language="sql")
                    st.markdown("**Gold SQL:**")
                    st.code(row["gold_sql"], language="sql")
    else:
        st.info(
            "No results file found. Run the eval harness first:\n\n"
            "```bash\npython eval/run_eval.py\n```"
        )
