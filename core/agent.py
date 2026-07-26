"""
NL-to-SQL agent. Generate SQL, execute, retry on error.
Caps at 3 attempts. Appends errors rather than restarting.
"""

import logging
import os
import re
import time
from typing import Any, Optional

from google import genai
from google.genai import types
from dotenv import load_dotenv

from tools.execute import run_sql
from core.prompts import SYSTEM_PROMPT, build_initial_prompt, build_retry_prompt

load_dotenv()
logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


def _extract_sql(text):
    # try "SQL:" marker first
    match = re.search(r"SQL:\s*(.+)", text, re.DOTALL | re.IGNORECASE)
    if match:
        sql = match.group(1).strip()
        sql = re.sub(r"^```(?:sql)?\s*", "", sql)
        sql = re.sub(r"\s*```\s*$", "", sql)
        return sql.strip()

    # fenced code block
    match = re.search(r"```(?:sql)?\s*(.+?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # fallback: last contiguous block
    lines = text.strip().splitlines()
    sql_lines = []
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            sql_lines.insert(0, stripped)
        elif sql_lines:
            break
    return "\n".join(sql_lines) if sql_lines else text.strip()


def _extract_reasoning(text):
    match = re.search(r"REASONING:\s*(.+?)(?=SQL:|$)", text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


class NL2SQLAgent:
    def __init__(self, api_key=None, model=None):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        if not self._api_key:
            raise ValueError("No Gemini API key. Set GEMINI_API_KEY in .env.")
        self._model = model or os.getenv("MODEL_NAME", "gemini-3.5-flash-lite")
        self._client = genai.Client(api_key=self._api_key)

    def answer(self, con, question, schema_text):
        system = SYSTEM_PROMPT.format(schema=schema_text)
        messages = build_initial_prompt(schema_text, question)
        trace = []
        sql = ""
        t0 = time.time()

        for attempt in range(1, MAX_ATTEMPTS + 1):
            contents = []
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg["content"])],
                ))

            # retry with backoff on rate limits
            raw_text = None
            for _api_try in range(4):
                try:
                    response = self._client.models.generate_content(
                        model=self._model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=system,
                            temperature=0.3,
                        ),
                    )
                    raw_text = response.text
                    break
                except Exception as exc:
                    exc_str = str(exc)
                    if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
                        wait = 15 * (_api_try + 1)
                        logger.warning("Rate limited, waiting %ds...", wait)
                        time.sleep(wait)
                    else:
                        logger.error("Gemini API error: %s", exc)
                        trace.append({"attempt": attempt, "reasoning": "", "sql": "", "error": f"API error: {exc}"})
                        break

            if raw_text is None:
                continue

            sql = _extract_sql(raw_text)
            reasoning = _extract_reasoning(raw_text)
            result, err = run_sql(con, sql)

            trace.append({"attempt": attempt, "reasoning": reasoning, "sql": sql, "error": err})

            if err is None:
                return {"sql": sql, "result": result, "attempts": attempt, "trace": trace,
                        "latency_s": round(time.time() - t0, 2), "model": self._model}

            messages.extend(build_retry_prompt(sql, err))

        return {"sql": sql, "result": None, "attempts": MAX_ATTEMPTS, "trace": trace,
                "latency_s": round(time.time() - t0, 2), "model": self._model}
