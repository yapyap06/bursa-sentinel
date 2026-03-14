"""
BursaSentinel — Watchlist Agent (Stage 3)
==========================================
Third stage in the SequentialAgent pipeline.

Receives a list of per-ticker Strategist reports and produces:
  - Portfolio-level risk flags
  - Sector concentration warnings
  - Best / Worst picks summary
  - Combined <thought_trace> for Demo Protocol

Phase 3 addition — fulfils Task 3.5.
"""

import json
import os
import time
from typing import Any

from dotenv import load_dotenv
import google.generativeai as genai

from agents._logger import get_swarm_logger

load_dotenv()
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

MAX_RETRIES = 3

WATCHLIST_SYSTEM_PROMPT = """
You are the WATCHLIST GUARDIAN, the third stage of the BursaSentinel swarm.
You receive multiple per-ticker Strategist reports and produce a portfolio-level
intelligence summary.

MANDATORY thought_trace fields:
  TICKERS_REVIEWED, BUY_COUNT, HOLD_COUNT, AVOID_COUNT,
  PORTFOLIO_RISK, CONCENTRATION_WARNING, CONFIDENCE

Return ONLY this JSON:
{
  "thought_trace": "<thought_trace string>",
  "portfolio_summary": {
    "tickers_reviewed": ["<TICKER>"],
    "buy_picks": ["<TICKER>"],
    "hold_picks": ["<TICKER>"],
    "avoid_picks": ["<TICKER>"],
    "best_pick": "<TICKER>",
    "worst_pick": "<TICKER>"
  },
  "portfolio_risk_flags": ["<flag>"],
  "concentration_warning": "<string | null>",
  "average_sentiment": <float>,
  "overall_confidence": "<HIGH|MEDIUM|LOW>",
  "watchlist_narrative": "<2-3 sentence plain English summary>"
}
""".strip()

RETRY_PROMPT = """
Your previous response was invalid. Problems: {problems}
Fix ALL issues. Return valid JSON only.
Previous response: {previous}
"""


class WatchlistAgent:
    """
    Portfolio-level aggregator — third SequentialAgent stage.
    """

    def __init__(self):
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=WATCHLIST_SYSTEM_PROMPT,
        )
        self.log = get_swarm_logger("WatchlistAgent")

    # ── Public API ─────────────────────────────────────────────────────── #

    def run(self, strategist_reports: list[dict[str, Any]]) -> dict[str, Any]:
        t0 = time.time()
        tickers = [r.get("ticker", "?") for r in strategist_reports]
        print(f"\n[WATCHLIST] 📋 Aggregating portfolio: {tickers}")
        self.log.info("run_start", extra={"tickers": tickers})

        prompt = self._build_prompt(strategist_reports)
        result, attempts = self._call_with_retry(prompt)

        elapsed_ms = int((time.time() - t0) * 1000)
        result["_elapsed_ms"] = elapsed_ms
        result["_attempts"] = attempts

        best = result.get("portfolio_summary", {}).get("best_pick", "N/A")
        print(f"  [WATCHLIST] ✅ Done in {elapsed_ms}ms. Best pick: {best}")
        self.log.info("run_complete", extra={"best_pick": best, "elapsed_ms": elapsed_ms})
        return result

    # ── Retry loop ─────────────────────────────────────────────────────── #

    def _call_with_retry(self, initial_prompt: str) -> tuple[dict, int]:
        prompt = initial_prompt
        last_raw = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.model.generate_content(prompt)
                last_raw = resp.text.strip()
                payload = self._parse_json(last_raw)
                problems = self._validate(payload)
                if not problems:
                    return payload, attempt
                print(f"  [WATCHLIST] ⚠️  Attempt {attempt} invalid: {problems}")
                self.log.warning("retry", extra={"attempt": attempt, "problems": problems})
                prompt = RETRY_PROMPT.format(problems="; ".join(problems),
                                             previous=last_raw[:600])
            except Exception as e:
                self.log.error("attempt_exception", extra={"attempt": attempt, "error": str(e)})
        return self._fallback(last_raw), MAX_RETRIES

    # ── Prompt builder ─────────────────────────────────────────────────── #

    @staticmethod
    def _build_prompt(reports: list[dict]) -> str:
        summaries = []
        for r in reports:
            ticker = r.get("ticker", "?")
            rec = r.get("recommendation", "?")
            conf = r.get("confidence", "?")
            cls_ = ", ".join(r.get("classifications", []))
            sent = r.get("sentiment_score", 0.0)
            flags = ", ".join(r.get("risk_flags", []))
            summaries.append(
                f"  {ticker}: {rec} ({conf}) | Classes: {cls_} | "
                f"Sentiment: {sent:+.2f} | Flags: {flags or 'None'}"
            )
        body = "\n".join(summaries)
        return (
            "You have received the following per-ticker Strategist reports:\n\n"
            f"{body}\n\n"
            "Produce the portfolio-level JSON summary. Identify concentration risk "
            "if >50% of holdings are in the same sector. Flag any tickers with AVOID."
        )

    # ── Validation ─────────────────────────────────────────────────────── #

    @staticmethod
    def _validate(payload: dict) -> list[str]:
        problems = []
        if not payload:
            return ["Empty payload"]
        for key in ["portfolio_summary", "portfolio_risk_flags",
                    "average_sentiment", "watchlist_narrative"]:
            if key not in payload:
                problems.append(f"Missing key: '{key}'")
        trace = payload.get("thought_trace", "")
        for field in ["TICKERS_REVIEWED", "PORTFOLIO_RISK", "CONFIDENCE"]:
            if field not in trace:
                problems.append(f"thought_trace missing: {field}")
        return problems

    # ── Helpers ─────────────────────────────────────────────────────────── #

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

    @staticmethod
    def _fallback(raw: str) -> dict:
        return {
            "thought_trace": (
                "<thought_trace>\n"
                "TICKERS_REVIEWED: N/A\nBUY_COUNT: N/A\nHOLD_COUNT: N/A\n"
                "AVOID_COUNT: N/A\nPORTFOLIO_RISK: UNKNOWN\n"
                "CONCENTRATION_WARNING: N/A\nCONFIDENCE: LOW\n"
                "</thought_trace>"
            ),
            "portfolio_summary": {"tickers_reviewed": [], "buy_picks": [],
                                   "hold_picks": [], "avoid_picks": [],
                                   "best_pick": None, "worst_pick": None},
            "portfolio_risk_flags": ["WATCHLIST_ANALYSIS_FAILURE"],
            "concentration_warning": None,
            "average_sentiment": 0.0,
            "overall_confidence": "LOW",
            "watchlist_narrative": "Watchlist analysis failed after max retries.",
            "_raw_response": raw,
        }
