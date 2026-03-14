"""
BursaSentinel — Currency Tool (MCP Tool)
=========================================
Fetches the current USD/MYR exchange rate for international comparisons.
Falls back to a stored last-known rate when live fetch fails.
"""

import time
import requests


class CurrencyTool:
    """
    MCP Tool: USD/MYR (and other MYR pairs) exchange rate fetcher.
    Uses exchangerate-api.com (free tier, no key required for basic rates).
    """

    API_URL = "https://api.exchangerate-api.com/v4/latest/USD"
    FALLBACK_RATES = {
        "USD_MYR": 4.72,
        "SGD_MYR": 3.51,
        "EUR_MYR": 5.10,
        "GBP_MYR": 5.95,
    }
    HEADERS = {"User-Agent": "BursaSentinel/1.0"}
    TIMEOUT = 8
    _cache: dict = {}
    _cache_ts: float = 0.0
    CACHE_TTL = 900  # 15 minutes

    # ── Public API ──────────────────────────────────────────────────────── #

    def fetch(self, base: str = "USD", target: str = "MYR") -> str:
        """
        Fetch exchange rate for base → target.
        Returns plain-text summary string for agent consumption.
        """
        pair = f"{base}_{target}"
        print(f"  [CurrencyTool] Fetching {pair} rate...")

        # Check cache
        if self._cache and (time.time() - self._cache_ts) < self.CACHE_TTL:
            rate = self._cache.get(target)
            if rate:
                return self._format(base, target, rate, "cache")

        # Live fetch
        try:
            resp = requests.get(self.API_URL.replace("USD", base),
                                headers=self.HEADERS, timeout=self.TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            rates = data.get("rates", {})
            CurrencyTool._cache = rates
            CurrencyTool._cache_ts = time.time()
            rate = rates.get(target)
            if rate:
                return self._format(base, target, rate, "exchangerate-api.com")
        except Exception as e:
            print(f"  [CurrencyTool] ⚠️  Live fetch failed: {e}. Using fallback.")

        # Fallback
        rate = self.FALLBACK_RATES.get(pair, None)
        if rate:
            return self._format(base, target, rate, "FALLBACK (stored last-known rate)")
        return f"RATE {pair}: UNAVAILABLE"

    # ── Formatting ──────────────────────────────────────────────────────── #

    @staticmethod
    def _format(base: str, target: str, rate: float, source: str) -> str:
        return (
            f"PAIR: {base}/{target}\n"
            f"RATE: {rate:.4f}\n"
            f"SOURCE: {source}\n"
            f"NOTE: 1 {base} = {rate:.4f} {target}"
        )
