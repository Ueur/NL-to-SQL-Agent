"""
Evaluation Harness

Runs questions against the agent and scores on RESULT MATCH,
not SQL string comparison. Many correct queries exist for one question. Comparing text would measure the wrong thing.

Usage:
    python eval/run_eval.py

Writes eval/results.csv with per-question outcomes and a summary to stdout.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
import time

from pathlib import Path

import yaml
from dotenv import load_dotenv

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from tools.schema import describe_schema
from tools.execute import run_sql
from core.agent import NL2SQLAgent

DB_PATH = PROJECT_ROOT / "data" / "warehouse.db"
QUESTIONS_PATH = Path(__file__).parent / "questions.yaml"
RESULTS_PATH = Path(__file__).parent / "results.csv"



# Result comparison


def normalize_result(res: dict | None) -> list[tuple] | None:
    """Normalize a result dict for comparison.

    Rounds floats to 2 decimal places and converts all values to comparable types.
    """
    if res is None:
        return None
    rows: list[tuple] = []
    for row in res["rows"]:
        normalized = []
        for val in row:
            if isinstance(val, float):
                normalized.append(round(val, 2))
            elif val is None:
                normalized.append(None)
            else:
                normalized.append(str(val))
        rows.append(tuple(normalized))
    return rows


def results_match(
    predicted: dict | None,
    gold: dict | None,
    order_matters: bool = False,
) -> bool:
    """Compare predicted and optimal results.

    If order_matters is False, both are sorted before comparison.
    We compare values only (not column names) since column aliases differ.
    """
    pred_rows = normalize_result(predicted)
    gold_rows = normalize_result(gold)

    if pred_rows is None or gold_rows is None:
        return pred_rows is None and gold_rows is None

    if not order_matters:
        pred_rows = sorted(pred_rows)
        gold_rows = sorted(gold_rows)

    return pred_rows == gold_rows



# Baseline: keyword rules (deliberately dumb, for comparison)


def baseline_answer(question: str) -> str:
    """Extremely naive keyword-to-SQL baseline. Exists to give the LLM
    score something to sit against — 'LLM got 73% vs baseline 18%' is
    a real claim. 'LLM got 73%' alone is not."""
    q = question.lower()

    if "how many" in q and "customer" in q:
        return "SELECT COUNT(*) FROM customers"
    if "how many" in q and "order" in q:
        return "SELECT COUNT(*) FROM orders"
    if "how many" in q and "seller" in q:
        return "SELECT COUNT(*) FROM sellers"
    if "how many" in q and "product" in q:
        return "SELECT COUNT(*) FROM products"
    if "average review" in q:
        return "SELECT ROUND(AVG(review_score), 4) FROM order_reviews"
    if "order status" in q or "distinct" in q and "status" in q:
        return "SELECT DISTINCT order_status FROM orders ORDER BY order_status"
    if "payment type" in q and ("common" in q or "most" in q):
        return "SELECT payment_type FROM order_payments GROUP BY payment_type ORDER BY COUNT(*) DESC LIMIT 1"

    # Catch-all
    return "SELECT 'no baseline rule matched' AS result"



# Main eval loop


def run_eval():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}. Run data/build_db.py first.")
        sys.exit(1)

    con = sqlite3.connect(str(DB_PATH))
    schema_text = describe_schema(con)

    with open(QUESTIONS_PATH) as f:
        questions = yaml.safe_load(f)

    print(f"Loaded {len(questions)} questions from {QUESTIONS_PATH}")
    print(f"Model: {os.getenv('MODEL_NAME', 'gemini-2.5-flash-preview-05-20')}")
    print("=" * 72)

    agent = NL2SQLAgent()

    rows: list[dict] = []
    correct_llm = 0
    correct_baseline = 0

    for qi, q in enumerate(questions):
        if qi > 0:
            time.sleep(13)  # Free tier: 5 RPM. Pace to stay under limit.
        qid = q["id"]
        question = q["question"]
        gold_sql = q["gold_sql"].strip()
        difficulty = q["difficulty"]
        tags = q.get("tags", [])
        order_matters = q.get("order_matters", False)

        print(f"\n[Q{qid}] ({difficulty}) {question}")

        # Run gold SQL
        gold_result, gold_err = run_sql(con, gold_sql)
        if gold_err:
            print(f"  ⚠️  GOLD SQL ERROR: {gold_err}")
            print(f"  SQL: {gold_sql}")
            continue

        # --- LLM Agent ---
        agent_out = agent.answer(con, question, schema_text)
        llm_match = results_match(agent_out["result"], gold_result, order_matters)
        if llm_match:
            correct_llm += 1

        print(f"  LLM:      {'✓' if llm_match else '✗'}  (attempts: {agent_out['attempts']}, {agent_out['latency_s']}s)")
        if not llm_match and agent_out["result"]:
            pred_preview = str(agent_out["result"]["rows"][:3])[:120]
            gold_preview = str(gold_result["rows"][:3])[:120]
            print(f"    pred: {pred_preview}")
            print(f"    gold: {gold_preview}")
        if agent_out["result"] is None:
            last_err = agent_out["trace"][-1]["error"] if agent_out["trace"] else "?"
            print(f"    error: {last_err}")

        # --- Baseline ---
        baseline_sql = baseline_answer(question)
        baseline_result, _ = run_sql(con, baseline_sql)
        baseline_match = results_match(baseline_result, gold_result, order_matters)
        if baseline_match:
            correct_baseline += 1

        print(f"  Baseline: {'✓' if baseline_match else '✗'}")

        rows.append({
            "id": qid,
            "question": question,
            "difficulty": difficulty,
            "tags": "|".join(tags),
            "llm_correct": llm_match,
            "llm_attempts": agent_out["attempts"],
            "llm_latency_s": agent_out["latency_s"],
            "llm_sql": agent_out["sql"],
            "baseline_correct": baseline_match,
            "baseline_sql": baseline_sql,
            "gold_sql": gold_sql,
        })

    con.close()

    # Write results CSV
    with open(RESULTS_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    total = len(rows)
    print("\n" + "=" * 72)
    print("RESULTS SUMMARY")
    print("=" * 72)
    print(f"Total questions: {total}")
    print(f"LLM accuracy:      {correct_llm}/{total} ({100*correct_llm/total:.1f}%)")
    print(f"Baseline accuracy:  {correct_baseline}/{total} ({100*correct_baseline/total:.1f}%)")

    # By difficulty
    for diff in ["easy", "medium", "hard"]:
        subset = [r for r in rows if r["difficulty"] == diff]
        if subset:
            llm_c = sum(1 for r in subset if r["llm_correct"])
            bl_c = sum(1 for r in subset if r["baseline_correct"])
            print(f"  {diff:8s}: LLM {llm_c}/{len(subset)} ({100*llm_c/len(subset):.0f}%)  |  Baseline {bl_c}/{len(subset)} ({100*bl_c/len(subset):.0f}%)")

    # Attempt distribution
    attempt_counts = {}
    for r in rows:
        a = r["llm_attempts"]
        attempt_counts[a] = attempt_counts.get(a, 0) + 1
    print(f"\nAttempt distribution: {dict(sorted(attempt_counts.items()))}")

    avg_latency = sum(r["llm_latency_s"] for r in rows) / total
    print(f"Average latency: {avg_latency:.2f}s per question")
    print(f"\nResults written to {RESULTS_PATH}")


if __name__ == "__main__":
    run_eval()
