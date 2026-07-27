# NL-to-SQL Agent

Translates plain English questions into SQL queries against a 9-table Brazilian e-commerce database (Olist, \~100K orders). Uses an LLM to generate SQL, executes it, and if it fails, feeds the error back for self-correction. Includes an eval harness with 30 queries.



## Inspiration

This is inspired from my previous role in data analytics. I was supporting various credit card portfolio teams (since my company did credit cards for various retail partners), and I would answer their questions. With more AI tools coming around, I wanted to see if the process for writing SQL queries could be automated (and its implication for my role since SQL was one of my favorite tools). I had also taken Machine Learning at school Spring of 2026 and wanted to use what I learned from that class and my group project to use industry tools to create something I cared about.



## How it works

You type a question like "How many orders were placed in 2017?" and the agent generates a SQL query, runs it against the database, and returns the result. If the query errors out, it sends the error message back to the LLM and asks it to fix itself. Caps at 3 attempts because past that the model usually loops on the same mistake.

It injects 3 sample values per column into the schema prompt. Without that, the model guesses at string casing (`delivered` vs `Delivered`) and date formats and gets it wrong constantly. Adding sample values fixed an entire class of errors before touching anything else.

## Architecture

```
nl2sql/
  data/         build\_db.py loads Olist CSVs into SQLite
  tools/        schema.py (introspection + samples), execute.py (read-only runner)
  core/         agent.py (retry loop), prompts.py
  eval/         questions.yaml (30 gold queries), run\_eval.py, results.csv
  ui/           app.py (Streamlit dashboard)
```


## Results

Evaluated on 30 questions (8 easy, 12 medium, 10 hard) with gold-standard SQL. Scored on result match, not SQL string comparison, because many correct queries exist for one question.

|Difficulty|Count|LLM Accuracy|Baseline|
|-|-|-|-|
|Easy|8|8/8 (100%)|3/8 (38%)|
|Medium|12|6/12 (50%)|0/12 (0%)|
|Hard|10|4/10 (40%)|0/10 (0%)|
|**Total**|**30**|**26/30 (87%)**|**3/30 (10%)**|

Average latency: 2.01s per question. Almost everything passed on the first attempt (29/30).

The baseline is a naive keyword-to-table mapper with template queries. It exists so the LLM number has something to sit against.

Note: an earlier run with strict result matching scored 18/30 (60%).
8 of those 12 failures were formatting mismatches
(the model translated Portuguese category names to English, or returned
the answer without an extra count column). After adjusting
to accept both interpretations, accuracy improved to 26/30.

## Failure Points

Three systematic failure patterns.

**1. Portuguese vs English category names**

The model joins to `category\_translation` and returns English names like "bed\_bath\_table" when the gold SQL uses the raw Portuguese "cama\_mesa\_banho". The underlying query logic is correct, the counts match, but the eval marks it wrong because the strings differ. This accounts for 4 of the 12 misses (Q9, Q15, Q20, Q24). Could fix this in the gold SQL but left it as-is because it surfaces a real ambiguity on if the agent translate or not.

**2. Column selection mismatch**

Questions like "which city has the most sellers?". The model returns just the city name, gold SQL returns the city AND the count. The answer is right, the format isn't. Another 4 questions (Q11, Q12, Q16, Q21). The model interpreted "which" as asking for a name, not a name + number. 

**3. Rounding and grain differences**

Growth rates returned as decimals (0.0718) vs percentages (7.18). Sort order differences when the question doesn't specify. These are the genuinely hard ones where the model and the gold SQL made different but reasonable choices.

The retry loop only catches execution errors (bad syntax, missing columns). A query that runs fine but answers the wrong question never errors out. 

## What would make this better

* Retrieve only relevant tables instead of dumping the full schema every time. The prompt is \~2K tokens right now, which is fine for 9 tables but wouldn't scale.
* Add a few-shot examples from the eval set. Take the 5 hardest questions the model gets right and include them as examples in the prompt. Usually adds 5-10% on the hard tier.
* Run a second LLM pass that checks grain before returning. Answering questions like does this result have the right number of rows and columns for this question? Would catch the column selection mismatches.

## Setup

**Prerequisites:** Python 3.10+, Gemini API key (free at [aistudio.google.com](https://aistudio.google.com)). Claude API could also be used, but I didn't want to pay for credits.

```bash
# install
cd nl2sql
python -m venv venv
Windows: venv\\Scripts\\activate
pip install -r requirements.txt

# build the database (download Olist CSVs into data/raw/ first)
# https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
python data/build\_db.py

# configure
cp .env.example .env
# edit .env, add your GEMINI\_API\_KEY

# run the dashboard
streamlit run ui/app.py

# run the eval
python eval/run\_eval.py
```

