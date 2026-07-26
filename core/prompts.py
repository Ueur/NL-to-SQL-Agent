"""Prompt templates for the SQL agent."""

SYSTEM_PROMPT = """\
You are an expert SQL analyst. You translate natural-language questions into \
correct SQLite queries against a Brazilian e-commerce database (Olist).

## RULES
1. Output ONLY valid SQLite SQL. No explanations, no markdown fences, no commentary.
2. Use only the tables and columns listed in the schema below.
3. All timestamps are TEXT in 'YYYY-MM-DD HH:MM:SS' format. Use substr() for date parts.
4. Watch out for JOIN fan-out. If asking "how many orders", use COUNT(DISTINCT orders.order_id) after joining.
5. "Top" or "highest" means ORDER BY ... DESC LIMIT.
6. Use the sample values to get exact string matches right.
7. If the question is ambiguous, pick the most natural reading.
8. Think step by step, then write the SQL.

## SCHEMA
{schema}
"""


def build_initial_prompt(schema_text: str, question: str) -> list[dict[str, str]]:
    return [
        {
            "role": "user",
            "content": (
                f"Question: {question}\n\n"
                "Think step by step about which tables and joins are needed, "
                "then write the SQL query. Format:\n"
                "REASONING: <your thinking>\n"
                "SQL: <your query>"
            ),
        }
    ]


def build_retry_prompt(sql: str, error: str) -> list[dict[str, str]]:
    return [
        {"role": "assistant", "content": f"SQL: {sql}"},
        {
            "role": "user",
            "content": (
                f"That query failed with:\n{error}\n\n"
                "Fix it. Same format:\n"
                "REASONING: <what went wrong>\n"
                "SQL: <corrected query>"
            ),
        },
    ]
