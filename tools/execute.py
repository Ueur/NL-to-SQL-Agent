"""Read-only SQL execution. Returns errors as data instead of raising."""

import sqlite3
from typing import Any, Optional


def run_sql(con: sqlite3.Connection, sql: str, row_limit: int = 200):
    """Execute sql, return (result_dict, None) on success or (None, error_string) on failure."""
    stripped = sql.strip()
    lowered = stripped.lower()

    if not lowered.startswith(("select", "with")):
        return None, "Only SELECT / WITH statements are allowed."

    dangerous = {"insert ", "update ", "delete ", "drop ", "alter ", "create ", "attach "}
    if any(kw in lowered for kw in dangerous):
        return None, "Statement contains a disallowed keyword."

    try:
        cur = con.execute(stripped)
        rows = cur.fetchmany(row_limit)
        columns = [desc[0] for desc in cur.description]
        return {"columns": columns, "rows": rows}, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
