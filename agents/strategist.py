"""
BursaSentinel -- Strategist Agent (Hardened v3)
================================================
Phase 3 hardening:
  - Retry loop (up to 3x) with corrective reprompting on JSON failure
  - Confidence downgrade cascade: any data_gaps -> cap at MEDIUM
  - pipeline_elapsed_ms tracking
  - Structured logging
Phase 5 fix:
  - Reverted to google-generativeai (AI Studio endpoint)
  - stdout forced to utf-8 to avoid Windows cp1252 emoji crash
  - Robust response.text extraction
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

# -- Thresholds ----------------------------------------------------------------
THRESHOLDS = {
    "dividend_yield_pct": float(os.getenv("DIVIDEND_YIELD_THRESHOLD", "4.0")),
    "pe_ratio":           float(os.getenv("PE_RATIO_MAX", "20.0")),
    "debt_to_equity":     float(os.getenv("DEBT_TO_EQUITY_MAX", "1.5")),
}

MAX_RETRIES = 3

# -- System prompt -------------------------------------------------------------
STRATEGIST_SYSTEM_PROMPT = f"""
You are the STRATEGIST, the analytical reasoning core of BursaSentinel.

THRESHOLDS (apply strictly):
  1. Dividend Yield  > {THRESHOLDS['dividend_yield_pct']}%  -> "Yield Fortress"
  2. P/E Ratio       < {THRESHOLDS['pe_ratio']}            -> "Value Zone"
  3. Debt/Equity     < {THRESHOLDS['debt_to_equity']}      -> "Balance Sheet Safe"

CONFIDENCE DOWNGRADE RULE (mandatory):
  If data_gaps is non-empty OR any recovery action was taken ->
  confidence MUST be MEDIUM or LOW. Never return HIGH if any field was missing.

AGENTIC RECOVERY PROTOCOL:
  For each null/missing metric: document "RECOVERY TRIGGERED: <field>",
  apply conservative default, reduce confidence, log the recovery step.

MANDATORY thought_trace fields:
  THRESHOLDS_APPLIED, RECOVERY_ACTIONS, CLASSIFICATION, SENTIMENT_SYNTHESIS, CONFIDENCE

Return ONLY this JSON schema:
{{
  "ticker": "<CODE>",
  "company_name": "<NAME>",
  "thought_trace": "<thought_trace string>",
  "classifications": ["<tag>"],
  "threshold_results": {{
    "dividend_yield_pass": <true|false|null>,
    "value_zone_pass": <true|false|null>,
    "balance_sheet_pass": <true|false|null>
  }},
  "recommendation": "<BUY|HOLD|AVOID>",
  "confidence": "<HIGH|MEDIUM|LOW>",
  "summary": "<2-3 sentence rationale>",
  "recovery_log": ["<step>"],
  "sentiment_score": <float -1.0 to 1.0>,
  "risk_flags": ["<flag>"]
}}
""".strip()

RETRY_CORRECTION_PROMPT = """
Your previous response was invalid. Problems: {problems}

Fix ALL issues and return valid JSON matching the schema exactly.
Previous (broken) response:
{previous}
"""


class StrategistAgent:
    """
    Gemini ADK Strategist Agent -- hardened with retry, confidence cascade,
    and structured logging.
    """

    def __init__(self):
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=STRATEGIST_SYSTEM_PROMPT,
        )
        self.log = get_swarm_logger("StrategistAgent")

    # -- Public API ------------------------------------------------------------

    def run(self, infiltrator_payload: dict[str, Any]) -> dict[str, Any]:
        t0 = time.time()
        ticker = infiltrator_payload.get("ticker", "UNKNOWN")
        data_gaps = infiltrator_payload.get("data_gaps", [])
        print(f"\n[STRATEGIST] >> Reasoning over: {ticker}")
        if data_gaps:
            print(f"  [STRATEGIST] WARN Gaps detected - Agentic Recovery will activate: {data_gaps}")
        self.log.info("run_start", extra={"ticker": ticker, "data_gaps": data_gaps})

        user_prompt = self._build_prompt(infiltrator_payload)
        result, attempts = self._call_with_retry(user_prompt)

        # -- CONFIDENCE DOWNGRADE CASCADE ----------------------------------------
        result, downgraded = self._apply_confidence_cascade(result, data_gaps)
        if downgraded:
            print(f"  [STRATEGIST] DOWN Confidence downgraded to MEDIUM (data_gaps present).")
            self.log.warning("confidence_downgraded", extra={"ticker": ticker,
                                                              "data_gaps": data_gaps})

        elapsed_ms = int((time.time() - t0) * 1000)
        result["_elapsed_ms"] = elapsed_ms
        result["_attempts"] = attempts

        rec = result.get("recommendation")
        conf = result.get("confidence")
        print(f"  [STRATEGIST] OK {rec} ({conf}) in {elapsed_ms}ms ({attempts} attempt(s))")
        self.log.info("run_complete", extra={"ticker": ticker, "recommendation": rec,
                                             "confidence": conf, "elapsed_ms": elapsed_ms,
                                             "attempts": attempts})
        return result

    # -- Confidence downgrade cascade ------------------------------------------

    @staticmethod
    def _apply_confidence_cascade(result: dict, data_gaps: list) -> tuple[dict, bool]:
        """
        If data_gaps is non-empty AND confidence is HIGH -> downgrade to MEDIUM.
        Returns (modified_result, was_downgraded).
        """
        if data_gaps and result.get("confidence") == "HIGH":
            result = dict(result)
            result["confidence"] = "MEDIUM"
            recovery = list(result.get("recovery_log", []))
            recovery.append(
                f"CONFIDENCE DOWNGRADED: data_gaps={data_gaps} -> confidence capped at MEDIUM"
            )
            result["recovery_log"] = recovery
            return result, True
        return result, False

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
                print(f"  [STRATEGIST] WARN Attempt {attempt} invalid: {problems}")
                self.log.warning("retry", extra={"attempt": attempt, "problems": problems})
                prompt = RETRY_CORRECTION_PROMPT.format(
                    problems="; ".join(problems),
                    previous=last_raw[:800],
                )
            except Exception as e:
                err_str = str(e)
                if '429' in err_str or 'ResourceExhausted' in err_str or 'quota' in err_str.lower():
                    wait = [5, 15, 30][attempt - 1]
                    print(f"  [STRATEGIST] RATE-LIMIT Attempt {attempt} — waiting {wait}s before retry...")
                    self.log.warning("rate_limit", extra={"attempt": attempt, "wait_s": wait})
                    time.sleep(wait)
                else:
                    print(f"  [STRATEGIST] ERR Attempt {attempt} exception: {type(e).__name__}: {str(e)[:200]}")
                self.log.error("attempt_exception", extra={"attempt": attempt, "error": err_str})
        return self._fallback_result(last_raw), MAX_RETRIES

    # -- Validation ------------------------------------------------------------

    @staticmethod
    def _validate(payload: dict) -> list[str]:
        problems = []
        if not payload:
            return ["Empty or unparseable JSON"]
        required_keys = ["recommendation", "confidence", "classifications",
                         "threshold_results", "recovery_log", "sentiment_score"]
        for k in required_keys:
            if k not in payload:
                problems.append(f"Missing key: '{k}'")
        if payload.get("confidence") not in ("HIGH", "MEDIUM", "LOW", None):
            problems.append(f"Invalid confidence: {payload.get('confidence')}")
        if payload.get("recommendation") not in ("BUY", "HOLD", "AVOID", None):
            problems.append(f"Invalid recommendation: {payload.get('recommendation')}")
        trace = payload.get("thought_trace", "")
        for field in ["THRESHOLDS_APPLIED", "RECOVERY_ACTIONS", "CONFIDENCE"]:
            if field not in trace:
                problems.append(f"thought_trace missing: {field}")
        return problems

    # -- Prompt builder --------------------------------------------------------

    @staticmethod
    def _build_prompt(payload: dict) -> str:
        m = payload.get("financial_metrics", {})
        news = payload.get("news_headlines", [])
        gaps = payload.get("data_gaps", [])
        news_text = "\n".join(
            f"  [{h.get('source','')}] {h.get('headline','')} ({h.get('sentiment_hint','')})"
            for h in news
        ) or "  No headlines."

        return (
            f"=== INFILTRATOR REPORT ===\n"
            f"Ticker: {payload.get('ticker','N/A')} | Company: {payload.get('company_name','N/A')}\n"
            f"Infiltrator Trace:\n{payload.get('thought_trace','')}\n\n"
            f"=== METRICS ===\n"
            f"Dividend Yield  : {m.get('dividend_yield_pct','MISSING')}%\n"
            f"P/E Ratio       : {m.get('pe_ratio','MISSING')}\n"
            f"Debt/Equity     : {m.get('debt_to_equity','MISSING')}\n"
            f"Market Cap MYR  : {m.get('market_cap_myr','MISSING')}\n"
            f"Revenue Growth  : {m.get('revenue_growth_yoy_pct','MISSING')}%\n\n"
            f"=== DATA GAPS (trigger Agentic Recovery) ===\n"
            f"{gaps if gaps else 'None.'}\n\n"
            f"=== NEWS ===\n{news_text}\n\n"
            "Apply thresholds. Trigger Agentic Recovery for MISSING fields. "
            "Return the complete JSON recommendation."
        )

    # -- Helpers ---------------------------------------------------------------

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
    def _fallback_result(raw: str) -> dict:
        return {
            "ticker": "UNKNOWN",
            "thought_trace": (
                "<thought_trace>\n"
                "THRESHOLDS_APPLIED: N/A -- parse failure\n"
                "RECOVERY_ACTIONS: CRITICAL -- exhausted retries\n"
                "CLASSIFICATION: UNKNOWN\n"
                "SENTIMENT_SYNTHESIS: N/A\n"
                "CONFIDENCE: LOW\n"
                "</thought_trace>"
            ),
            "classifications": [],
            "threshold_results": {"dividend_yield_pass": None,
                                   "value_zone_pass": None,
                                   "balance_sheet_pass": None},
            "recommendation": "HOLD",
            "confidence": "LOW",
            "summary": "Analysis failed after max retries. Manual review required.",
            "recovery_log": ["CRITICAL: Max retries exhausted -- returning safe HOLD."],
            "sentiment_score": 0.0,
            "risk_flags": ["ANALYSIS_FAILURE", "MAX_RETRIES_EXCEEDED"],
            "_raw_response": raw,
        }
