"""
Eval harness. Runs 30 questions against three setups:
  1. Keyword baseline (no AI)
  2. Raw LLM (question + table names only, no schema details, no retry)
  3. Full agent (schema with sample values + retry loop)

The gap between 1->2 shows what the LLM adds.
The gap between 2->3 shows what the engineering adds on top of the LLM.
"""

from __future__ import annotations

import csv
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from google import genai
from google.genai import types

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from tools.schema import describe_schema
from tools.execute import run_sql
from core.agent import NL2SQLAgent, _extract_sql

DB_PATH = PROJECT_ROOT / "data" / "warehouse.db"
QUESTIONS_PATH = Path(__file__).parent / "questions.yaml"
RESULTS_PATH = Path(__file__).parent / "results.csv"


# --- Result comparison ---

def normalize_result(res):
    if res is None:
        return None
    rows = []
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


def results_match(predicted, gold, order_matters=False):
    pred_rows = normalize_result(predicted)
    gold_rows = normalize_result(gold)
    if pred_rows is None or gold_rows is None:
        return pred_rows is None and gold_rows is None
    if not order_matters:
        pred_rows = sorted(pred_rows)
        gold_rows = sorted(gold_rows)
    return pred_rows == gold_rows


# --- Keyword baseline (deliberately dumb) ---

def baseline_keyword(question):
    q = question.lower()
    if "how many" in q and "customer" in q:
        return "SELECT COUNT(*) FROM customers"
    if "how many" in q and "order" in q:
        return "SELECT COUNT(*) FROM orders"
    if "how many" in q and "seller" in q:
        return "SELECT COUNT(*) FROM sellers"
    if "average review" in q:
        return "SELECT ROUND(AVG(review_score), 4) FROM order_reviews"
    if "order status" in q or ("distinct" in q and "status" in q):
        return "SELECT DISTINCT order_status FROM orders ORDER BY order_status"
    if "payment type" in q and ("common" in q or "most" in q):
        return "SELECT payment_type FROM order_payments GROUP BY payment_type ORDER BY COUNT(*) DESC LIMIT 1"
    return "SELECT 'no rule matched' AS result"


# --- Raw LLM baseline (no schema details, no retry) ---

def baseline_raw_llm(client, model, con, question):
    """Send question to LLM with only table names. No columns, no samples, no retry."""
    prompt = (
        "Write a SQLite query to answer this question. Return ONLY the SQL, nothing else.\n\n"
        "The database has these tables: customers, orders, order_items, order_payments, "
        "order_reviews, products, sellers, category_translation, geolocation.\n\n"
        f"Question: {question}"
    )
    try:
        response = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
            config=types.GenerateContentConfig(temperature=0.3),
        )
        sql = _extract_sql(response.text)
        result, err = run_sql(con, sql)
        return result, sql, err
    except Exception as exc:
        return None, "", str(exc)


# --- Main ---

def run_eval():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}. Run data/build_db.py first.")
        sys.exit(1)

    con = sqlite3.connect(str(DB_PATH))
    schema_text = describe_schema(con)

    with open(QUESTIONS_PATH) as f:
        questions = yaml.safe_load(f)

    model_name = os.getenv("MODEL_NAME", "gemini-3.5-flash-lite")
    api_key = os.getenv("GEMINI_API_KEY", "")

    print(f"Loaded {len(questions)} questions")
    print(f"Model: {model_name}")
    print("=" * 72)

    agent = NL2SQLAgent()

    # raw LLM baseline client
    raw_client = genai.Client(api_key=api_key) if api_key else None

    rows = []
    correct_agent = 0
    correct_raw = 0
    correct_keyword = 0

    for qi, q in enumerate(questions):
        if qi > 0:
            time.sleep(13)  # pace for free tier rate limits

        qid = q["id"]
        question = q["question"]
        gold_sql = q["gold_sql"].strip()
        difficulty = q["difficulty"]
        tags = q.get("tags", [])
        order_matters = q.get("order_matters", False)

        print(f"\n[Q{qid}] ({difficulty}) {question}")

        # run gold SQL
        gold_result, gold_err = run_sql(con, gold_sql)
        if gold_err:
            print(f"  GOLD SQL ERROR: {gold_err}")
            continue

        # --- Full agent ---
        agent_out = agent.answer(con, question, schema_text)
        agent_match = results_match(agent_out["result"], gold_result, order_matters)
        if agent_match:
            correct_agent += 1
        print(f"  Agent:    {'✓' if agent_match else '✗'}  (attempts: {agent_out['attempts']}, {agent_out['latency_s']}s)")
        if not agent_match and agent_out["result"]:
            print(f"    pred: {str(agent_out['result']['rows'][:3])[:120]}")
            print(f"    gold: {str(gold_result['rows'][:3])[:120]}")
        if agent_out["result"] is None:
            last_err = agent_out["trace"][-1]["error"] if agent_out["trace"] else "?"
            print(f"    error: {last_err}")

        # pace between agent and raw baseline
        time.sleep(5)

        # --- Raw LLM baseline ---
        raw_match = False
        raw_sql = ""
        if raw_client:
            for _raw_try in range(3):
                raw_result, raw_sql, raw_err = baseline_raw_llm(raw_client, model_name, con, question)
                if raw_err and ("429" in str(raw_err) or "RESOURCE_EXHAUSTED" in str(raw_err)):
                    time.sleep(15)
                    continue
                break
            raw_match = results_match(raw_result, gold_result, order_matters)
            if raw_match:
                correct_raw += 1
        print(f"  Raw LLM:  {'✓' if raw_match else '✗'}")

        # --- Keyword baseline ---
        kw_sql = baseline_keyword(question)
        kw_result, _ = run_sql(con, kw_sql)
        kw_match = results_match(kw_result, gold_result, order_matters)
        if kw_match:
            correct_keyword += 1
        print(f"  Keyword:  {'✓' if kw_match else '✗'}")

        rows.append({
            "id": qid,
            "question": question,
            "difficulty": difficulty,
            "tags": "|".join(tags),
            "agent_correct": agent_match,
            "agent_attempts": agent_out["attempts"],
            "agent_latency_s": agent_out["latency_s"],
            "agent_sql": agent_out["sql"],
            "raw_llm_correct": raw_match,
            "raw_llm_sql": raw_sql,
            "keyword_correct": kw_match,
            "keyword_sql": kw_sql,
            "gold_sql": gold_sql,
        })

    con.close()

    # write CSV
    with open(RESULTS_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    # summary
    total = len(rows)
    print("\n" + "=" * 72)
    print("RESULTS")
    print("=" * 72)
    print(f"Total: {total} questions\n")
    print(f"{'Setup':<30} {'Correct':<12} {'Accuracy'}")
    print(f"{'-'*30} {'-'*12} {'-'*10}")
    print(f"{'Keyword baseline (no AI)':<30} {correct_keyword}/{total:<10} {100*correct_keyword/total:.1f}%")
    print(f"{'Raw LLM (no schema/retry)':<30} {correct_raw}/{total:<10} {100*correct_raw/total:.1f}%")
    print(f"{'Full agent':<30} {correct_agent}/{total:<10} {100*correct_agent/total:.1f}%")

    print(f"\nBy difficulty:")
    for diff in ["easy", "medium", "hard"]:
        subset = [r for r in rows if r["difficulty"] == diff]
        if subset:
            a = sum(1 for r in subset if r["agent_correct"])
            r = sum(1 for r in subset if r["raw_llm_correct"])
            k = sum(1 for r in subset if r["keyword_correct"])
            print(f"  {diff:<8} Agent {a}/{len(subset)} ({100*a/len(subset):.0f}%)  "
                  f"Raw {r}/{len(subset)} ({100*r/len(subset):.0f}%)  "
                  f"Keyword {k}/{len(subset)} ({100*k/len(subset):.0f}%)")

    attempt_counts = {}
    for r in rows:
        a = r["agent_attempts"]
        attempt_counts[a] = attempt_counts.get(a, 0) + 1
    print(f"\nAttempt distribution: {dict(sorted(attempt_counts.items()))}")

    avg_latency = sum(r["agent_latency_s"] for r in rows) / total
    print(f"Average latency: {avg_latency:.2f}s per question")
    print(f"\nResults -> {RESULTS_PATH}")


if __name__ == "__main__":
    run_eval()
