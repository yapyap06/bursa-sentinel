"""
BursaSentinel — pytest Test Suite (Phase 3, Task 3.6)
======================================================
Tests cover:
  - Strategist threshold logic
  - Confidence downgrade cascade
  - Infiltrator thought_trace validation
  - Swarm report assembly structure
  - WatchlistAgent input handling
  - JSON parse and retry helpers

Run with:  pytest tests/ -v
"""

import json
import pytest
from unittest.mock import MagicMock, patch


# ══════════════════════════════════════════════════════════════════════════ #
#  Helpers / fixtures                                                        #
# ══════════════════════════════════════════════════════════════════════════ #

def make_infiltrator_payload(
    ticker="MAYBANK",
    dy=6.24, pe=12.4, de=0.82, rg=7.3,
    mc=114_500_000_000.0, high=10.38, low=8.62,
    data_gaps=None,
):
    return {
        "ticker": ticker,
        "company_name": "Test Corp",
        "thought_trace": (
            "<thought_trace>\n"
            "SOURCE_1: BursaScraperTool → OK\n"
            "SOURCE_2: NewsScraperTool → OK\n"
            "DATA_FOUND: dividend_yield_pct, pe_ratio, debt_to_equity\n"
            "ANOMALIES: None\n"
            "CONFIDENCE: HIGH\n"
            "</thought_trace>"
        ),
        "financial_metrics": {
            "dividend_yield_pct": dy,
            "pe_ratio": pe,
            "debt_to_equity": de,
            "market_cap_myr": mc,
            "52_week_high": high,
            "52_week_low": low,
            "revenue_growth_yoy_pct": rg,
        },
        "news_headlines": [],
        "data_gaps": data_gaps or [],
    }


def make_strategist_result(rec="BUY", conf="HIGH", cls=None, gaps=None):
    return {
        "ticker": "TEST",
        "company_name": "Test Corp",
        "thought_trace": (
            "<thought_trace>\n"
            "THRESHOLDS_APPLIED: DY PASS, PE PASS, DE PASS\n"
            "RECOVERY_ACTIONS: NONE\n"
            "CLASSIFICATION: [Yield Fortress]\n"
            "SENTIMENT_SYNTHESIS: +0.5\n"
            "CONFIDENCE: HIGH\n"
            "</thought_trace>"
        ),
        "classifications": cls or ["Yield Fortress"],
        "threshold_results": {
            "dividend_yield_pass": True,
            "value_zone_pass": True,
            "balance_sheet_pass": True,
        },
        "recommendation": rec,
        "confidence": conf,
        "summary": "Test summary.",
        "recovery_log": [],
        "sentiment_score": 0.5,
        "risk_flags": [],
    }


# ══════════════════════════════════════════════════════════════════════════ #
#  Threshold logic tests (no Gemini call needed)                             #
# ══════════════════════════════════════════════════════════════════════════ #

class TestThresholds:
    """Direct unit tests for threshold evaluation logic."""

    THRESHOLDS = {"dividend_yield_pct": 4.0, "pe_ratio": 20.0, "debt_to_equity": 1.5}

    def _check(self, dy, pe, de):
        m = {"dividend_yield_pct": dy, "pe_ratio": pe, "debt_to_equity": de}
        return {
            "dy_pass": m["dividend_yield_pct"] is not None and m["dividend_yield_pct"] > self.THRESHOLDS["dividend_yield_pct"],
            "pe_pass": m["pe_ratio"] is not None and m["pe_ratio"] < self.THRESHOLDS["pe_ratio"],
            "de_pass": m["debt_to_equity"] is not None and m["debt_to_equity"] < self.THRESHOLDS["debt_to_equity"],
        }

    def test_maybank_all_pass(self):
        r = self._check(dy=6.24, pe=12.4, de=0.82)
        assert r["dy_pass"] is True
        assert r["pe_pass"] is True
        assert r["de_pass"] is True

    def test_tenaga_dividend_fail(self):
        r = self._check(dy=3.78, pe=14.9, de=1.22)
        assert r["dy_pass"] is False   # 3.78 < 4.0 → FAIL
        assert r["pe_pass"] is True
        assert r["de_pass"] is True

    def test_boundary_dividend_exactly_threshold(self):
        r = self._check(dy=4.0, pe=10.0, de=0.5)
        assert r["dy_pass"] is False   # must be STRICTLY greater than 4.0

    def test_high_pe_fails_value_zone(self):
        r = self._check(dy=5.0, pe=25.0, de=1.0)
        assert r["pe_pass"] is False

    def test_high_de_fails_balance_sheet(self):
        r = self._check(dy=5.0, pe=15.0, de=2.0)
        assert r["de_pass"] is False

    def test_null_metrics_fail_gracefully(self):
        r = self._check(dy=None, pe=None, de=None)
        assert r["dy_pass"] is False
        assert r["pe_pass"] is False
        assert r["de_pass"] is False


# ══════════════════════════════════════════════════════════════════════════ #
#  Confidence downgrade cascade                                              #
# ══════════════════════════════════════════════════════════════════════════ #

class TestConfidenceCascade:
    """Tests for StrategistAgent._apply_confidence_cascade()."""

    def setup_method(self):
        # Import the static method directly, no Gemini needed
        from agents.strategist import StrategistAgent
        self.cascade = StrategistAgent._apply_confidence_cascade

    def test_high_confidence_downgraded_when_gaps(self):
        result = make_strategist_result(conf="HIGH")
        data_gaps = ["pe_ratio"]
        modified, downgraded = self.cascade(result, data_gaps)
        assert downgraded is True
        assert modified["confidence"] == "MEDIUM"

    def test_medium_confidence_not_changed(self):
        result = make_strategist_result(conf="MEDIUM")
        modified, downgraded = self.cascade(result, ["pe_ratio"])
        assert downgraded is False
        assert modified["confidence"] == "MEDIUM"

    def test_no_gaps_no_change(self):
        result = make_strategist_result(conf="HIGH")
        modified, downgraded = self.cascade(result, [])
        assert downgraded is False
        assert modified["confidence"] == "HIGH"

    def test_downgrade_adds_recovery_log_entry(self):
        result = make_strategist_result(conf="HIGH")
        result["recovery_log"] = []
        modified, _ = self.cascade(result, ["dividend_yield_pct"])
        assert any("CONFIDENCE DOWNGRADED" in entry for entry in modified["recovery_log"])

    def test_multiple_gaps_still_caps_at_medium(self):
        result = make_strategist_result(conf="HIGH")
        modified, downgraded = self.cascade(result, ["pe_ratio", "debt_to_equity", "market_cap_myr"])
        assert downgraded is True
        assert modified["confidence"] == "MEDIUM"


# ══════════════════════════════════════════════════════════════════════════ #
#  Infiltrator thought_trace validation                                      #
# ══════════════════════════════════════════════════════════════════════════ #

class TestInfiltratorValidation:
    """Tests for InfiltratorAgent._validate()."""

    def setup_method(self):
        from agents.infiltrator import InfiltratorAgent
        self.validate = InfiltratorAgent._validate

    def _make_payload(self, trace="", extra=None):
        p = {
            "ticker": "TEST",
            "thought_trace": trace,
            "financial_metrics": {},
            "data_gaps": [],
        }
        if extra:
            p.update(extra)
        return p

    def test_valid_payload_returns_no_problems(self):
        trace = (
            "SOURCE_1: BursaScraperTool → OK\n"
            "DATA_FOUND: dividend_yield_pct\n"
            "ANOMALIES: None\n"
            "CONFIDENCE: HIGH"
        )
        problems = self.validate(self._make_payload(trace=trace))
        assert problems == []

    def test_missing_source1_detected(self):
        trace = "DATA_FOUND: x\nANOMALIES: None\nCONFIDENCE: HIGH"
        problems = self.validate(self._make_payload(trace=trace))
        assert any("SOURCE_1" in p for p in problems)

    def test_missing_data_found_detected(self):
        trace = "SOURCE_1: BursaScraperTool → OK\nANOMALIES: None\nCONFIDENCE: HIGH"
        problems = self.validate(self._make_payload(trace=trace))
        assert any("DATA_FOUND" in p for p in problems)

    def test_missing_financial_metrics_key(self):
        trace = "SOURCE_1: ok\nDATA_FOUND: x\nANOMALIES: None\nCONFIDENCE: HIGH"
        payload = {"ticker": "X", "thought_trace": trace, "data_gaps": []}
        # No 'financial_metrics' key
        problems = self.validate(payload)
        assert any("financial_metrics" in p for p in problems)

    def test_missing_data_gaps_key(self):
        trace = "SOURCE_1: ok\nDATA_FOUND: x\nANOMALIES: None\nCONFIDENCE: HIGH"
        payload = {"ticker": "X", "thought_trace": trace, "financial_metrics": {}}
        problems = self.validate(payload)
        assert any("data_gaps" in p for p in problems)


# ══════════════════════════════════════════════════════════════════════════ #
#  Strategist validation                                                     #
# ══════════════════════════════════════════════════════════════════════════ #

class TestStrategistValidation:
    def setup_method(self):
        from agents.strategist import StrategistAgent
        self.validate = StrategistAgent._validate

    def test_valid_result_no_problems(self):
        r = make_strategist_result()
        assert self.validate(r) == []

    def test_empty_payload_flagged(self):
        assert self.validate({}) != []

    def test_missing_recommendation_flagged(self):
        r = make_strategist_result()
        del r["recommendation"]
        problems = self.validate(r)
        assert any("recommendation" in p for p in problems)

    def test_invalid_confidence_value(self):
        r = make_strategist_result()
        r["confidence"] = "SUPER_HIGH"
        problems = self.validate(r)
        assert any("confidence" in p.lower() for p in problems)

    def test_invalid_recommendation_value(self):
        r = make_strategist_result()
        r["recommendation"] = "MAYBE"
        problems = self.validate(r)
        assert any("recommendation" in p.lower() for p in problems)

    def test_missing_thought_trace_fields(self):
        r = make_strategist_result()
        r["thought_trace"] = "incomplete trace"
        problems = self.validate(r)
        assert any("THRESHOLDS_APPLIED" in p for p in problems)


# ══════════════════════════════════════════════════════════════════════════ #
#  JSON parse helpers                                                        #
# ══════════════════════════════════════════════════════════════════════════ #

class TestJsonParse:
    def setup_method(self):
        from agents.infiltrator import InfiltratorAgent
        self.parse = InfiltratorAgent._parse_json

    def test_bare_json(self):
        raw = '{"ticker": "ABC", "data_gaps": []}'
        result = self.parse(raw)
        assert result["ticker"] == "ABC"

    def test_json_with_markdown_fence(self):
        raw = '```json\n{"ticker": "ABC"}\n```'
        result = self.parse(raw)
        assert result["ticker"] == "ABC"

    def test_json_in_code_fence_no_lang(self):
        raw = '```\n{"ticker": "XYZ"}\n```'
        result = self.parse(raw)
        assert result["ticker"] == "XYZ"

    def test_invalid_json_returns_empty(self):
        result = self.parse("This is not JSON at all.")
        assert result == {}

    def test_nested_json_parsed(self):
        raw = '{"a": {"b": [1, 2, 3]}}'
        result = self.parse(raw)
        assert result["a"]["b"] == [1, 2, 3]


# ══════════════════════════════════════════════════════════════════════════ #
#  Swarm report assembly (no Gemini)                                         #
# ══════════════════════════════════════════════════════════════════════════ #

class TestSwarmAssembly:
    def setup_method(self):
        from agents.swarm import BursaSentinelSwarm
        self.assemble = BursaSentinelSwarm._assemble_report

    def test_report_has_required_top_level_keys(self):
        inf = make_infiltrator_payload()
        strat = make_strategist_result()
        report = self.assemble("MAYBANK", inf, strat, s1_ms=100, s2_ms=200, total_ms=300)
        for key in ["ticker", "pipeline_elapsed_ms", "pipeline_trace",
                    "infiltrator_data", "strategist_analysis", "final_recommendation"]:
            assert key in report, f"Missing key: {key}"

    def test_pipeline_elapsed_ms_stored(self):
        inf, strat = make_infiltrator_payload(), make_strategist_result()
        report = self.assemble("TEST", inf, strat, s1_ms=50, s2_ms=75, total_ms=125)
        assert report["pipeline_elapsed_ms"] == 125

    def test_stage_elapsed_ms_in_trace(self):
        inf, strat = make_infiltrator_payload(), make_strategist_result()
        report = self.assemble("TEST", inf, strat, s1_ms=111, s2_ms=222, total_ms=333)
        stages = {s["stage"]: s for s in report["pipeline_trace"]}
        assert stages[1]["elapsed_ms"] == 111
        assert stages[2]["elapsed_ms"] == 222

    def test_final_recommendation_fields_present(self):
        inf, strat = make_infiltrator_payload(), make_strategist_result()
        report = self.assemble("TEST", inf, strat, s1_ms=10, s2_ms=20, total_ms=30)
        rec = report["final_recommendation"]
        for field in ["recommendation", "confidence", "classifications",
                      "summary", "sentiment_score", "risk_flags"]:
            assert field in rec, f"Missing field in final_recommendation: {field}"

    def test_ticker_uppercased(self):
        inf, strat = make_infiltrator_payload(), make_strategist_result()
        report = self.assemble("maybank", inf, strat, s1_ms=10, s2_ms=20, total_ms=30)
        assert report["ticker"] == "MAYBANK"


# ══════════════════════════════════════════════════════════════════════════ #
#  BursaScraperTool mock data                                                #
# ══════════════════════════════════════════════════════════════════════════ #

class TestBursaScraperMock:
    def setup_method(self):
        from tools.bursa_scraper import BursaScraperTool
        self.tool = BursaScraperTool()

    def test_maybank_mock_returns_dividend_yield(self):
        result = self.tool._mock_data("MAYBANK")
        assert "DIVIDEND_YIELD_PCT" in result
        assert "6.24" in result

    def test_unknown_ticker_returns_null_fields(self):
        result = self.tool._mock_data("UNKNOWNXYZ")
        assert "N/A" in result

    def test_extract_float_basic(self):
        assert self.tool._extract_float("6.24%") == 6.24

    def test_extract_float_with_commas(self):
        assert self.tool._extract_float("1,234.56") == 1234.56

    def test_extract_float_none_on_no_number(self):
        assert self.tool._extract_float("No number here") is None


# ======================================================================== #
#  Phase 4 — New MCP Tools                                                   #
# ======================================================================== #

class TestFinancialRatioTool:
    def setup_method(self):
        from tools.financial_ratios import FinancialRatioTool
        self.tool = FinancialRatioTool()

    def test_dividend_yield_basic(self):
        dy = self.tool._dividend_yield(dps=0.32, price=10.0)
        assert abs(dy - 3.2) < 0.001

    def test_dividend_yield_none_when_price_zero(self):
        assert self.tool._dividend_yield(dps=0.32, price=0) is None

    def test_dividend_yield_none_when_dps_none(self):
        assert self.tool._dividend_yield(dps=None, price=10.0) is None

    def test_pe_from_price_and_eps(self):
        pe = self.tool._pe_ratio(price=10.0, eps=0.80,
                                 net_profit=None, shares=None, market_cap=None)
        assert abs(pe - 12.5) < 0.001

    def test_pe_from_market_cap_fallback(self):
        pe = self.tool._pe_ratio(price=None, eps=None,
                                 net_profit=8e9, shares=None, market_cap=100e9)
        assert abs(pe - 12.5) < 0.001

    def test_pe_none_when_all_missing(self):
        assert self.tool._pe_ratio(None, None, None, None, None) is None

    def test_debt_to_equity_basic(self):
        de = self.tool._debt_to_equity(total_debt=8e9, total_equity=10e9)
        assert abs(de - 0.8) < 0.001

    def test_debt_to_equity_none_when_equity_zero(self):
        assert self.tool._debt_to_equity(8e9, 0) is None

    def test_revenue_growth_positive(self):
        rg = self.tool._revenue_growth(revenue=110, prev_revenue=100)
        assert abs(rg - 10.0) < 0.001

    def test_revenue_growth_negative(self):
        rg = self.tool._revenue_growth(revenue=90, prev_revenue=100)
        assert abs(rg + 10.0) < 0.001

    def test_compute_output_contains_ticker(self):
        result = self.tool.compute("TESTCO", dividend_per_share=0.5, share_price=10.0)
        assert "TESTCO" in result
        assert "DIVIDEND_YIELD_PCT" in result


class TestBursaAnnouncementTool:
    def setup_method(self):
        from tools.bursa_announcements import BursaAnnouncementTool
        self.tool = BursaAnnouncementTool()

    def test_maybank_mock_returns_announcements(self):
        result = self.tool._mock("MAYBANK")
        assert "MAYBANK" in result
        assert "MOCK_DATA" in result

    def test_unknown_ticker_returns_no_results_note(self):
        result = self.tool._mock("XYZ999")
        assert "No recent announcements" in result

    def test_fetch_falls_back_to_mock_on_error(self):
        result = self.tool.fetch("MAYBANK")
        assert isinstance(result, str) and len(result) > 10


class TestCurrencyTool:
    def setup_method(self):
        from tools.currency_tool import CurrencyTool
        self.tool = CurrencyTool()

    def test_format_output_contains_pair(self):
        result = self.tool._format("USD", "MYR", 4.72, "test")
        assert "USD/MYR" in result and "4.720" in result

    def test_fallback_rates_positive(self):
        assert self.tool.FALLBACK_RATES["USD_MYR"] > 0

    def test_fetch_returns_string_with_myr(self):
        result = self.tool.fetch("USD", "MYR")
        assert isinstance(result, str) and "MYR" in result


class TestRateLimiter:
    def test_acquire_fast_when_permissive(self):
        from tools.bursa_scraper import _RateLimiter
        import time
        lim = _RateLimiter(rate=100.0)
        t0 = time.monotonic()
        for _ in range(5):
            lim.acquire()
        assert (time.monotonic() - t0) < 0.5

    def test_rate_limiter_slows_on_burst(self):
        from tools.bursa_scraper import _RateLimiter
        import time
        # At rate=1/s: token 0 is free, then each subsequent call waits ~1s
        # 3 calls = 2 waits of ~1s -> total >= 0.9s after thread overhead
        lim = _RateLimiter(rate=1.0)
        t0 = time.monotonic()
        for _ in range(3):
            lim.acquire()
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.9, f"Rate limiter didn't slow enough: {elapsed:.2f}s"
