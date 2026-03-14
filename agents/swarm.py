"""
BursaSentinel — SequentialAgent Swarm (Hardened v2)
====================================================
Phase 3 additions:
  - pipeline_elapsed_ms per stage and total
  - WatchlistAgent as optional third stage
  - Structured JSONL logging
  - Batch mode: analyze_batch() feeds WatchlistAgent automatically
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from agents.infiltrator import InfiltratorAgent
from agents.strategist import StrategistAgent
from agents.watchlist_agent import WatchlistAgent
from agents._logger import get_swarm_logger
from tools.bursa_scraper import BursaScraperTool
from tools.news_scraper import NewsScraperTool


class BursaSentinelSwarm:
    """
    SequentialAgent Swarm:
      Stage 1 — Infiltrator    : Data collection via MCP tools
      Stage 2 — Strategist     : Threshold reasoning + Agentic Recovery
      Stage 3 — WatchlistAgent : Portfolio-level aggregation (batch mode)
    """

    def __init__(self):
        bursa_tool = BursaScraperTool()
        news_tool  = NewsScraperTool()
        self.infiltrator      = InfiltratorAgent(bursa_tool=bursa_tool, news_tool=news_tool)
        self.strategist       = StrategistAgent()
        self.watchlist_agent  = WatchlistAgent()
        self.log              = get_swarm_logger("Swarm")

    # ── Single ticker ───────────────────────────────────────────────────── #

    def analyze(self, ticker: str) -> dict[str, Any]:
        print(f"\n{'='*60}")
        print(f"  🛰️  BURSASENTINEL SWARM — MISSION: {ticker}")
        print(f"{'='*60}")

        pipeline_start = time.time()
        self.log.info("mission_start", extra={"ticker": ticker})

        # Stage 1
        s1_start = time.time()
        infiltrator_output = self.infiltrator.run(ticker)
        s1_ms = int((time.time() - s1_start) * 1000)

        # Stage 2
        s2_start = time.time()
        strategist_output = self.strategist.run(infiltrator_output)
        s2_ms = int((time.time() - s2_start) * 1000)

        total_ms = int((time.time() - pipeline_start) * 1000)

        report = self._assemble_report(
            ticker, infiltrator_output, strategist_output,
            s1_ms=s1_ms, s2_ms=s2_ms, total_ms=total_ms
        )

        self._print_summary(report)
        self.log.info("mission_complete", extra={
            "ticker": ticker,
            "recommendation": report["final_recommendation"]["recommendation"],
            "total_ms": total_ms,
        })
        return report

    # ── Batch mode (triggers WatchlistAgent) ────────────────────────────── #

    def analyze_batch(self, tickers: list[str]) -> dict[str, Any]:
        print(f"\n{'='*60}")
        print(f"  🛰️  BURSASENTINEL BATCH — {len(tickers)} tickers: {tickers}")
        print(f"{'='*60}")

        batch_start = time.time()
        individual_reports = [self.analyze(t) for t in tickers]
        strategist_outputs = [r["strategist_analysis"] for r in individual_reports]

        # Stage 3: WatchlistAgent
        watchlist_output = self.watchlist_agent.run(strategist_outputs)
        total_ms = int((time.time() - batch_start) * 1000)

        best = watchlist_output.get("portfolio_summary", {}).get("best_pick")
        print(f"\n{'='*60}")
        print(f"  📋 BATCH COMPLETE in {total_ms}ms | Best Pick: {best}")
        print(f"{'='*60}")

        return {
            "mission": "BursaSentinel Batch Analysis",
            "tickers": tickers,
            "total_elapsed_ms": total_ms,
            "individual_reports": individual_reports,
            "watchlist_analysis": watchlist_output,
        }

    # ── Report assembly ──────────────────────────────────────────────────── #

    @staticmethod
    def _assemble_report(
        ticker: str,
        infiltrator_output: dict,
        strategist_output: dict,
        s1_ms: int, s2_ms: int, total_ms: int,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "mission": "BursaSentinel Strategic Research Swarm",
            "ticker": ticker.upper(),
            "generated_at": now,
            "pipeline_elapsed_ms": total_ms,
            "pipeline_trace": [
                {
                    "stage": 1, "agent": "InfiltratorAgent", "status": "COMPLETE",
                    "elapsed_ms": s1_ms,
                    "attempts": infiltrator_output.get("_attempts", 1),
                    "data_gaps": infiltrator_output.get("data_gaps", []),
                    "thought_trace": infiltrator_output.get("thought_trace", ""),
                },
                {
                    "stage": 2, "agent": "StrategistAgent", "status": "COMPLETE",
                    "elapsed_ms": s2_ms,
                    "attempts": strategist_output.get("_attempts", 1),
                    "recovery_log": strategist_output.get("recovery_log", []),
                    "thought_trace": strategist_output.get("thought_trace", ""),
                },
            ],
            "infiltrator_data": infiltrator_output,
            "strategist_analysis": strategist_output,
            "final_recommendation": {
                "recommendation":  strategist_output.get("recommendation", "HOLD"),
                "confidence":      strategist_output.get("confidence", "LOW"),
                "classifications": strategist_output.get("classifications", []),
                "summary":         strategist_output.get("summary", ""),
                "sentiment_score": strategist_output.get("sentiment_score", 0.0),
                "risk_flags":      strategist_output.get("risk_flags", []),
                "threshold_results": strategist_output.get("threshold_results", {}),
            },
        }

    @staticmethod
    def _print_summary(report: dict) -> None:
        rec = report["final_recommendation"]
        print(f"\n{'='*60}")
        print(f"  🎯  MISSION COMPLETE: {report['ticker']}")
        print(f"  📊  RECOMMENDATION : {rec['recommendation']}")
        print(f"  🏷️   CLASSIFICATIONS: {rec['classifications']}")
        print(f"  🔒  CONFIDENCE     : {rec['confidence']}")
        print(f"  ⏱️   ELAPSED        : {report['pipeline_elapsed_ms']}ms")
        print(f"{'='*60}\n")

    # ── Save ─────────────────────────────────────────────────────────────── #

    @staticmethod
    def save_report(report: dict, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ticker = report.get("ticker", "UNKNOWN")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(output_dir, f"report_{ticker}_{ts}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"[Swarm] 💾 Report saved → {path}")
        return path


# ── CLI ──────────────────────────────────────────────────────────────────── #

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BursaSentinel Swarm")
    parser.add_argument("--ticker", default="MAYBANK")
    parser.add_argument("--tickers", nargs="+")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    swarm = BursaSentinelSwarm()

    if args.tickers and len(args.tickers) > 1:
        batch = swarm.analyze_batch(args.tickers)
        if args.save:
            swarm.save_report(batch, output_dir="reports")
        print(json.dumps(batch.get("watchlist_analysis", {}), indent=2))
    else:
        ticker = (args.tickers or [args.ticker])[0]
        report = swarm.analyze(ticker)
        if args.save:
            swarm.save_report(report)
        print(json.dumps(report.get("final_recommendation", {}), indent=2))
