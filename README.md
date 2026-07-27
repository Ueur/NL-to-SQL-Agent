# NL-to-SQL Agent

Translates plain English questions into SQL queries against a 9-table Brazilian e-commerce database (Olist, ~100K orders). Uses an LLM to generate SQL, executes it, and if it fails, feeds the error back for self-correction. Includes an eval harness with 30 hand-written queries scored against three baselines.

## Inspiration

This is inspired from my previous role in data analytics. I was supporting various credit card portfolio teams (since my company did credit cards for various retail partners), and I would answer their questions. With more AI tools coming around, I wanted to see if the process for writing SQL queries could be automated (and its implication for my role since SQL was one of my favorite tools). I had also taken Machine Learning at school Spring of 2026 and wanted to use what I learned from that class and my group project to use industry tools to create something I cared about.

## How it works

Type a question like "How many orders were placed in 2017?" and the agent generates a SQL query, runs it against the database, and returns the result. If the query errors out, it sends the error message back to the LLM and asks it to fix itself. Caps at 3 attempts.

The key thing that made this work well include injecting 3 sample values per column into the schema prompt. Without that, the model guesses at string casing (`delivered` vs `Delivered`) and date formats and gets it wrong constantly. Adding sample values fixed an entire class of errors.

## Architecture

```
nl2sql/
  data/         build_db.py loads Olist CSVs into SQLite
  tools/        schema.py (introspection + samples), execute.py (read-only runner)
  core/         agent.py (retry loop), prompts.py
  eval/         questions.yaml (30 gold queries), run_eval.py, results.csv
  ui/           app.py (Streamlit dashboard)
```

## Results

Evaluated on 30 questions (8 easy, 12 medium, 10 hard). Scored on result match, not SQL string comparison, because many correct queries exist for one question.

| Setup | Accuracy | What it tests |
|-------|----------|---------------|
| Keyword baseline (no AI) | 3/30 (10%) | Can you do this without an LLM at all? |
| Raw LLM (no schema/retry) | 19/30 (63%) | What does the LLM add by itself? |
| **Full agent** | **24/30 (80%)** | What does the engineering add on top? |

By difficulty:

| Difficulty | Full Agent | Raw LLM | Keyword |
|------------|-----------|---------|---------|
| Easy (8)   | 8/8 (100%) | 8/8 (100%) | 3/8 (38%) |
| Medium (12)| 10/12 (83%)| 7/12 (58%) | 0/12 (0%) |
| Hard (10)  | 6/10 (60%) | 4/10 (40%) | 0/10 (0%) |

Every question where the raw LLM failed but the agent succeeded required knowing specific column names, which table a column lives in, or that dates are stored as text strings needing julianday() instead of Postgres-style EXTRACT(). Those are the details the schema tool provides.

Every question passed on the first attempt (30/30). Average latency 2.01s per question.

## Where it breaks

Six questions still fail. They fall into two patterns.

**Rounding and formatting differences.** Q15, Q24, Q28 all return the right data but with different precision. The model returns `93.33333...` where the gold-standard expects `93.33`. Or it returns 4 columns (seller, total, five_star, percentage) where the gold expects 2 (seller, percentage). The underlying answer is correct. Tightening the comparison logic would fix these in later runs.

**Grain and ordering.** Q25 returns states in alphabetical order, gold expects them sorted by order value. Q27 includes January 2018 with NULL growth (no previous month), gold excludes it. Q20 returns just the category name without the weight. These reflect genuinely ambiguous readings of the question where the model and the gold SQL made different but reasonable choices.

The retry loop only catches execution errors (bad syntax, missing columns). A query that runs fine but answers the wrong question never errors out. 

## What would make this better

- Retrieve only relevant tables instead of dumping the full schema every time. Works for 9 tables, wouldn't scale to 50.
- Add few-shot examples from the eval set. Take the hardest questions the model gets right and include them as prompt examples.
- Run a second LLM pass that checks result shape before returning. "Does this have the right columns and sort order for this question?"
- Loosen the eval to round all floats to 2 decimal places and ignore extra columns. Would push accuracy to ~90% without changing the agent at all.

## Setup

**Prerequisites:** Python 3.10+, Gemini API key (free at [aistudio.google.com](https://aistudio.google.com)). Claude API also works, just that I didn't want to pay for usage credits.

```bash
cd nl2sql
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# download Olist CSVs into data/raw/ from
# https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
python data/build_db.py

cp .env.example .env
# edit .env, add GEMINI_API_KEY

# dashboard
streamlit run ui/app.py

# eval
python eval/run_eval.py
```
