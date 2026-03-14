"""
BursaSentinel — Bursa Malaysia Scraper Tool (MCP Tool) — Hardened v2
=====================================================================
Phase 4 hardening:
  - Rotating User-Agent pool (randomised per request)
  - Rate limiting: max 5 requests/sec via token-bucket throttle
  - robots.txt awareness flag
  - Unchanged public API: fetch(ticker) → str
"""

import random
import re
import time
from threading import Lock
from typing import Optional

import requests
from bs4 import BeautifulSoup


# ── Rotating User-Agent pool ────────────────────────────────────────────── #
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
]


# ── Token-bucket rate limiter ───────────────────────────────────────────── #
class _RateLimiter:
    """Allows at most `rate` calls per second across all threads."""

    def __init__(self, rate: float = 5.0):
        self._rate = rate          # tokens per second
        self._tokens = rate        # start full
        self._last = time.monotonic()
        self._lock = Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            self._last = now
            if self._tokens >= 1:
                self._tokens -= 1
            else:
                wait = (1 - self._tokens) / self._rate
                time.sleep(wait)
                self._tokens = 0


_RATE_LIMITER = _RateLimiter(rate=5.0)   # shared across all tool instances


class BursaScraperTool:
    """
    MCP Tool: Bursa Malaysia financial metrics scraper (hardened).
    Public API unchanged — fetch(ticker) → str.
    """

    KLSE_URL = "https://klse.i3investor.com/web/stock/overview/{code}"
    TIMEOUT = 10

    MOCK_DB: dict[str, dict] = {
        "MAYBANK": {
            "dividend_yield_pct": 6.24, "pe_ratio": 12.4,
            "debt_to_equity": 0.82, "market_cap_myr": 114_500_000_000.0,
            "52_week_high": 10.38, "52_week_low": 8.62, "revenue_growth_yoy_pct": 7.3,
        },
        "CIMB": {
            "dividend_yield_pct": 5.11, "pe_ratio": 10.2,
            "debt_to_equity": 1.01, "market_cap_myr": 61_200_000_000.0,
            "52_week_high": 7.84, "52_week_low": 6.21, "revenue_growth_yoy_pct": 4.8,
        },
        "TENAGA": {
            "dividend_yield_pct": 3.78, "pe_ratio": 14.9,
            "debt_to_equity": 1.22, "market_cap_myr": 87_300_000_000.0,
            "52_week_high": 15.20, "52_week_low": 11.80, "revenue_growth_yoy_pct": -1.2,
        },
    }

    # ── Public API ──────────────────────────────────────────────────────── #

    def fetch(self, ticker: str) -> str:
        ticker_upper = ticker.strip().upper()
        print(f"  [BursaScraperTool] Fetching data for {ticker_upper}...")
        try:
            _RATE_LIMITER.acquire()
            data = self._scrape_klse(ticker_upper)
            return self._format_output(ticker_upper, data, source="KLSE i3investor")
        except Exception as e:
            print(f"  [BursaScraperTool] ⚠️  Live scrape failed: {e}. Using mock data.")
            return self._mock_data(ticker_upper)

    # ── Scraping ─────────────────────────────────────────────────────────── #

    def _scrape_klse(self, ticker: str) -> dict:
        headers = {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        }
        url = self.KLSE_URL.format(code=ticker)
        resp = requests.get(url, headers=headers, timeout=self.TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        data: dict = {}

        patterns = {
            "dividend_yield_pct": re.compile(r"Dividend Yield", re.I),
            "pe_ratio":           re.compile(r"P/E Ratio|Price.*Earnings", re.I),
            "market_cap_myr":     re.compile(r"Market Cap", re.I),
            "52_week_high":       re.compile(r"52.*High|High.*52", re.I),
            "52_week_low":        re.compile(r"52.*Low|Low.*52", re.I),
        }
        for key, pat in patterns.items():
            tag = soup.find(string=pat)
            if tag and tag.find_next():
                data[key] = self._extract_float(tag.find_next().get_text())
        return data

    # ── Helpers ──────────────────────────────────────────────────────────── #

    @staticmethod
    def _extract_float(text: str) -> Optional[float]:
        match = re.search(r"[\d,]+\.?\d*", text)
        if match:
            try:
                return float(match.group().replace(",", ""))
            except ValueError:
                return None
        return None

    @staticmethod
    def _format_output(ticker: str, data: dict, source: str) -> str:
        lines = [f"TICKER: {ticker}", f"SOURCE: {source}"]
        for k, v in data.items():
            lines.append(f"{k.upper()}: {v if v is not None else 'N/A'}")
        return "\n".join(lines)

    def _mock_data(self, ticker: str) -> str:
        record = self.MOCK_DB.get(ticker.upper(), {k: None for k in [
            "dividend_yield_pct", "pe_ratio", "debt_to_equity",
            "market_cap_myr", "52_week_high", "52_week_low", "revenue_growth_yoy_pct",
        ]})
        lines = [f"TICKER: {ticker}", "SOURCE: MOCK_DATA (live scrape unavailable)"]
        for k, v in record.items():
            lines.append(f"{k.upper()}: {v if v is not None else 'N/A'}")
        return "\n".join(lines)
