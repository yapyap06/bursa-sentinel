"""
BursaSentinel — Financial Ratio Tool (MCP Tool)
================================================
Computes DY, P/E, and D/E from raw balance sheet inputs when primary
sources (BursaScraperTool) fail or return null for those fields.

Acts as the Agentic Recovery computation layer.
"""


class FinancialRatioTool:
    """
    MCP Tool: Computes financial ratios from raw balance sheet data.

    Used by the Infiltrator Agent as a fallback when primary scrapers
    return null metrics — part of the Agentic Recovery pipeline.
    """

    # ── Public API ──────────────────────────────────────────────────────── #

    def compute(
        self,
        ticker: str,
        dividend_per_share: float | None = None,
        share_price: float | None = None,
        earnings_per_share: float | None = None,
        total_debt: float | None = None,
        total_equity: float | None = None,
        net_profit: float | None = None,
        revenue: float | None = None,
        prev_revenue: float | None = None,
        shares_outstanding: float | None = None,
        market_cap: float | None = None,
    ) -> str:
        """
        Compute all derivable ratios from the provided raw inputs.
        Returns a plain-text summary for the Infiltrator Agent.
        """
        print(f"  [FinancialRatioTool] Computing ratios for {ticker}...")
        results: dict[str, float | str] = {}

        # ── Dividend Yield ─────────────────────────────────────────────── #
        dy = self._dividend_yield(dividend_per_share, share_price)
        results["dividend_yield_pct"] = round(dy, 4) if dy is not None else "CANNOT_COMPUTE"

        # ── P/E Ratio ──────────────────────────────────────────────────── #
        pe = self._pe_ratio(share_price, earnings_per_share,
                            net_profit, shares_outstanding, market_cap)
        results["pe_ratio"] = round(pe, 4) if pe is not None else "CANNOT_COMPUTE"

        # ── Debt / Equity ──────────────────────────────────────────────── #
        de = self._debt_to_equity(total_debt, total_equity)
        results["debt_to_equity"] = round(de, 4) if de is not None else "CANNOT_COMPUTE"

        # ── Revenue Growth YoY ─────────────────────────────────────────── #
        rg = self._revenue_growth(revenue, prev_revenue)
        results["revenue_growth_yoy_pct"] = round(rg, 4) if rg is not None else "CANNOT_COMPUTE"

        return self._format(ticker, results)

    # ── Ratio computations ──────────────────────────────────────────────── #

    @staticmethod
    def _dividend_yield(
        dps: float | None, price: float | None
    ) -> float | None:
        """DY = (Dividend Per Share / Share Price) × 100"""
        if dps is not None and price and price > 0:
            return (dps / price) * 100
        return None

    @staticmethod
    def _pe_ratio(
        price: float | None,
        eps: float | None,
        net_profit: float | None,
        shares: float | None,
        market_cap: float | None,
    ) -> float | None:
        """P/E = Price / EPS  OR  Market Cap / Net Profit (fallback)"""
        if price is not None and eps and eps > 0:
            return price / eps
        if market_cap is not None and net_profit and net_profit > 0:
            return market_cap / net_profit
        if net_profit and shares and shares > 0 and price is not None:
            eps_computed = net_profit / shares
            if eps_computed > 0:
                return price / eps_computed
        return None

    @staticmethod
    def _debt_to_equity(
        total_debt: float | None, total_equity: float | None
    ) -> float | None:
        """D/E = Total Debt / Total Equity"""
        if total_debt is not None and total_equity and total_equity > 0:
            return total_debt / total_equity
        return None

    @staticmethod
    def _revenue_growth(
        revenue: float | None, prev_revenue: float | None
    ) -> float | None:
        """YoY Growth = ((Revenue - Prev) / Prev) × 100"""
        if revenue is not None and prev_revenue and prev_revenue > 0:
            return ((revenue - prev_revenue) / prev_revenue) * 100
        return None

    # ── Formatting ──────────────────────────────────────────────────────── #

    @staticmethod
    def _format(ticker: str, results: dict) -> str:
        lines = [
            f"TICKER: {ticker}",
            "SOURCE: FinancialRatioTool (computed from raw inputs)",
        ]
        for k, v in results.items():
            lines.append(f"{k.upper()}: {v}")
        return "\n".join(lines)
