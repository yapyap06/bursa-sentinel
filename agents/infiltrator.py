"""
BursaSentinel — Infiltrator Agent (Hardened v3)
================================================
Phase 3 hardening:
  - thought_trace schema validator (5 required fields)
  - Retry loop (up to 3x) with corrective reprompt on JSON / trace failure
  - Structured logging to logs/swarm_{date}.jsonl
Phase 5 fix:
  - Reverted to google-generativeai (AI Studio endpoint)
  - stdout forced to utf-8 to avoid Windows cp1252 emoji crash
"""

import json
import os
import sys
import time
from typing import Any

# Force UTF-8 output on Windows to avoid emoji UnicodeEncodeError
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
import google.generativeai as genai

from agents._logger import get_swarm_logger

load_dotenv()
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

# -- Required fields in <thought_trace> ----------------------------------------
TRACE_REQUIRED_FIELDS = ["SOURCE_1", "DATA_FOUND", "ANOMALIES", "CONFIDENCE"]
MAX_RETRIES = 3

# -- System prompt --------------------------------------------------------------
INFILTRATOR_SYSTEM_PROMPT = """
You are the INFILTRATOR, a covert data-gathering operative in the BursaSentinel
Strategic Research Swarm. Your ONLY job is to collect raw intelligence about
Bursa Malaysia listed companies. Do NOT perform analysis.

MANDATORY: Every response MUST include a <thought_trace> block with ALL of:
  SOURCE_1:   [source name] -> [status: OK | MISSING | ERROR]
  SOURCE_2:   [source name] -> [status: OK | MISSING | ERROR]
  DATA_FOUND: [comma-separated list of collected fields]
  ANOMALIES:  [any suspicious data points, or "None"]
  CONFIDENCE: [HIGH | MEDIUM | LOW]

Return a JSON object with this exact schema:
{
  "ticker": "<STOCK_CODE>",
  "company_name": "<NAME>",
  "thought_trace": "<full thought_trace string>",
  "financial_metrics": {
    "dividend_yield_pct": <float | null>,
    "pe_ratio": <float | null>,
    "debt_to_equity": <float | null>,
    "market_cap_myr": <float | null>,
    "52_week_high": <float | null>,
    "52_week_low": <float | null>,
    "revenue_growth_yoy_pct": <float | null>
  },
  "news_headlines": [
    {"headline": "<text>", "source": "<source>", "sentiment_hint": "<positive|neutral|negative>"}
  ],
  "data_gaps": ["<field names that are null>"]
}
""".strip()

RETRY_CORRECTION_PROMPT = """
Your previous response was invalid. Problems found: {problems}

You MUST fix ALL of the above issues and return a valid JSON object exactly
matching the schema in your system prompt. Do not add any prose outside the JSON.
Previous response for reference:
{previous}
"""


class InfiltratorAgent:
    """
    Gemini ADK Infiltrator Agent -- hardened with retry + trace validation.
    """

    def __init__(self, bursa_tool=None, news_tool=None):
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=INFILTRATOR_SYSTEM_PROMPT,
        )
        self.bursa_tool = bursa_tool
        self.news_tool = news_tool
        self.log = get_swarm_logger("InfiltratorAgent")

    # -- Public API ------------------------------------------------------------

    def run(self, ticker: str) -> dict[str, Any]:
        t0 = time.time()
        print(f"\n[INFILTRATOR] >> Recon on: {ticker}")
        self.log.info("run_start", extra={"ticker": ticker})

        financial_raw = self._gather_financial_data(ticker)
        news_raw = self._gather_news(ticker)
        user_prompt = self._build_prompt(ticker, financial_raw, news_raw)

        payload, attempts = self._call_with_retry(user_prompt)

        elapsed_ms = int((time.time() - t0) * 1000)
        payload["_elapsed_ms"] = elapsed_ms
        payload["_attempts"] = attempts

        gaps = payload.get("data_gaps", [])
        print(f"[INFILTRATOR] Done in {elapsed_ms}ms ({attempts} attempt(s)). Gaps: {gaps}")
        self.log.info("run_complete", extra={"ticker": ticker, "elapsed_ms": elapsed_ms,
                                             "attempts": attempts, "data_gaps": gaps})
        return payload

    # -- Retry loop ------------------------------------------------------------

    def _call_with_retry(self, initial_prompt: str) -> tuple[dict, int]:
        prompt = initial_prompt
        last_raw = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.model.generate_content(prompt)
                # Safely extract text - response.text raises ValueError if blocked
                try:
                    last_raw = response.text.strip()
                except (ValueError, AttributeError):
                    # Blocked or no content - try parts directly
                    last_raw = ""
                    if hasattr(response, 'candidates') and response.candidates:
                        for part in response.candidates[0].content.parts:
                            if hasattr(part, 'text'):
                                last_raw += part.text
                        last_raw = last_raw.strip()
                if not last_raw:
                    raise ValueError("Empty or blocked response from Gemini")
                payload = self._parse_json(last_raw)
                problems = self._validate(payload)
                if not problems:
                    return payload, attempt
                # Prepare corrective prompt for next round
                print(f"  [INFILTRATOR] WARN Attempt {attempt} invalid: {problems}")
                self.log.warning("retry", extra={"attempt": attempt, "problems": problems})
                prompt = RETRY_CORRECTION_PROMPT.format(
                    problems="; ".join(problems),
                    previous=last_raw[:800],
                )
            except Exception as e:
                err_str = str(e)
                # Exponential backoff for rate limit (429) errors
                if '429' in err_str or 'ResourceExhausted' in err_str or 'quota' in err_str.lower():
                    wait = [5, 15, 30][attempt - 1]
                    print(f"  [INFILTRATOR] RATE-LIMIT Attempt {attempt} — waiting {wait}s before retry...")
                    self.log.warning("rate_limit", extra={"attempt": attempt, "wait_s": wait})
                    time.sleep(wait)
                else:
                    print(f"  [INFILTRATOR] ERR Attempt {attempt} exception: {type(e).__name__}: {str(e)[:200]}")
                self.log.error("attempt_exception", extra={"attempt": attempt, "error": err_str})
        # Exhausted retries -- return a safe fallback
        return self._fallback_payload(last_raw), MAX_RETRIES

    # -- Validation ------------------------------------------------------------

    @staticmethod
    def _validate(payload: dict) -> list[str]:
        """Return a list of problems. Empty list = valid."""
        problems = []
        trace = payload.get("thought_trace", "")
        for field in TRACE_REQUIRED_FIELDS:
            if field not in trace:
                problems.append(f"<thought_trace> missing required field: {field}")
        if "financial_metrics" not in payload:
            problems.append("Missing 'financial_metrics' key")
        if "data_gaps" not in payload:
            problems.append("Missing 'data_gaps' key")
        return problems

    # -- Data gathering --------------------------------------------------------

    def _gather_financial_data(self, ticker: str) -> str:
        if self.bursa_tool:
            try:
                return self.bursa_tool.fetch(ticker)
            except Exception as e:
                self.log.warning("bursa_tool_error", extra={"error": str(e)})
                return f"[TOOL ERROR] BursaScraperTool: {e}"
        return "[TOOL UNAVAILABLE] BursaScraperTool not mounted."

    def _gather_news(self, ticker: str) -> str:
        if self.news_tool:
            try:
                return self.news_tool.fetch(ticker)
            except Exception as e:
                self.log.warning("news_tool_error", extra={"error": str(e)})
                return f"[TOOL ERROR] NewsScraperTool: {e}"
        return "[TOOL UNAVAILABLE] NewsScraperTool not mounted."

    # -- Prompt builder --------------------------------------------------------

    @staticmethod
    def _build_prompt(ticker: str, financial_raw: str, news_raw: str) -> str:
        return (
            f"Ticker: {ticker}\n\n"
            f"--- RAW FINANCIAL DATA (BursaScraperTool) ---\n{financial_raw}\n\n"
            f"--- RAW NEWS DATA (NewsScraperTool) ---\n{news_raw}\n\n"
            "Produce the complete JSON response. Use null for missing numerics. "
            "List missing field names in data_gaps. Include all thought_trace fields."
        )

    # -- JSON parser -----------------------------------------------------------

    @staticmethod
    def _parse_json(raw: str) -> dict:
        text = raw
        if "```" in text:
            for part in text.split("```"):
                stripped = part.strip().lstrip("json").strip()
                if stripped.startswith("{"):
                    text = stripped
                    break
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    # -- Fallback --------------------------------------------------------------

    @staticmethod
    def _fallback_payload(raw: str) -> dict:
        return {
            "ticker": "UNKNOWN",
            "company_name": "UNKNOWN",
            "thought_trace": (
                "<thought_trace>\n"
                "SOURCE_1: N/A -> ERROR\n"
                "SOURCE_2: N/A -> ERROR\n"
                "DATA_FOUND: none\n"
                "ANOMALIES: JSON parse failure after max retries\n"
                "CONFIDENCE: LOW\n"
                "</thought_trace>"
            ),
            "financial_metrics": {k: None for k in [
                "dividend_yield_pct", "pe_ratio", "debt_to_equity",
                "market_cap_myr", "52_week_high", "52_week_low", "revenue_growth_yoy_pct"
            ]},
            "news_headlines": [],
            "data_gaps": ["ALL -- max retries exhausted"],
            "_raw_response": raw,
        }
