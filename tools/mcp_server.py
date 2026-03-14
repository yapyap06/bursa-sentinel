"""
BursaSentinel — MCP Server (Hardened v2)
=========================================
Phase 4 additions:
  - X-API-Key authentication on all POST endpoints
  - GET /health  — tool status + uptime + version
  - GET /tools   — full tool manifest (unchanged)
  - POST /       — tool invocation (unchanged interface + auth guard)
  - All 6 tools registered: bursa_scraper, news_scraper,
    bursa_announcements, financial_ratios, currency
"""

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from tools.bursa_scraper import BursaScraperTool
from tools.news_scraper import NewsScraperTool
from tools.bursa_announcements import BursaAnnouncementTool
from tools.financial_ratios import FinancialRatioTool
from tools.currency_tool import CurrencyTool

# ── Server meta ───────────────────────────────────────────────────────────── #
_VERSION = "2.0.0"
_START_TIME = time.time()

# ── API Key (loaded from env; None = auth disabled in dev mode) ────────────── #
_API_KEY = os.getenv("MCP_API_KEY")

# ── Tool registry ─────────────────────────────────────────────────────────── #
TOOLS = {
    "bursa_scraper":        BursaScraperTool(),
    "news_scraper":         NewsScraperTool(),
    "bursa_announcements":  BursaAnnouncementTool(),
    "financial_ratios":     FinancialRatioTool(),
    "currency":             CurrencyTool(),
}

TOOL_MANIFEST = {
    "version": _VERSION,
    "tools": [
        {
            "name": "bursa_scraper",
            "description": "Fetches financial metrics (DY, P/E, D/E, market cap, 52W range) for a Bursa ticker.",
            "parameters": {"type": "object", "properties": {
                "ticker": {"type": "string", "description": "Bursa stock code e.g. MAYBANK"}
            }, "required": ["ticker"]},
        },
        {
            "name": "news_scraper",
            "description": "Fetches recent financial news headlines for a Bursa ticker.",
            "parameters": {"type": "object", "properties": {
                "ticker": {"type": "string"}
            }, "required": ["ticker"]},
        },
        {
            "name": "bursa_announcements",
            "description": "Fetches recent corporate announcements (financial results, dividends, etc.) for a Bursa ticker.",
            "parameters": {"type": "object", "properties": {
                "ticker": {"type": "string"}
            }, "required": ["ticker"]},
        },
        {
            "name": "financial_ratios",
            "description": "Computes DY, P/E, D/E, and revenue growth from raw balance sheet inputs. Use when primary scraper returns null metrics.",
            "parameters": {"type": "object", "properties": {
                "ticker":               {"type": "string"},
                "dividend_per_share":   {"type": "number"},
                "share_price":          {"type": "number"},
                "earnings_per_share":   {"type": "number"},
                "total_debt":           {"type": "number"},
                "total_equity":         {"type": "number"},
                "net_profit":           {"type": "number"},
                "revenue":              {"type": "number"},
                "prev_revenue":         {"type": "number"},
            }, "required": ["ticker"]},
        },
        {
            "name": "currency",
            "description": "Fetches live exchange rate (default: USD/MYR). Cached for 15 min.",
            "parameters": {"type": "object", "properties": {
                "base":   {"type": "string", "default": "USD"},
                "target": {"type": "string", "default": "MYR"},
            }},
        },
    ],
}


# ── HTTP Handler ──────────────────────────────────────────────────────────── #

class MCPHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"  [MCPServer] {self.address_string()} — {fmt % args}")

    # ── Auth helper ────────────────────────────────────────────────────── #

    def _is_authorized(self) -> bool:
        """Return True if auth is disabled OR the correct key is provided."""
        if not _API_KEY:
            return True  # dev mode — no key configured
        provided = self.headers.get("X-API-Key", "")
        return provided == _API_KEY

    def _send_unauthorized(self) -> None:
        self._send_json(
            {"error": "Unauthorized — provide a valid X-API-Key header"},
            status=401
        )

    # ── GET ────────────────────────────────────────────────────────────── #

    def do_GET(self) -> None:
        if self.path in ("/", "/tools"):
            self._send_json(TOOL_MANIFEST)

        elif self.path == "/health":
            uptime_s = round(time.time() - _START_TIME, 1)
            self._send_json({
                "status": "ok",
                "version": _VERSION,
                "uptime_s": uptime_s,
                "tools": list(TOOLS.keys()),
                "auth_enabled": bool(_API_KEY),
            })

        else:
            self._send_json({"error": "Not found"}, status=404)

    # ── POST ───────────────────────────────────────────────────────────── #

    def do_POST(self) -> None:
        # Auth check
        if not self._is_authorized():
            self._send_unauthorized()
            return

        # Parse body
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            request = json.loads(body)
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON body"}, status=400)
            return

        tool_name = request.get("method") or request.get("tool", "")
        params = request.get("params", request.get("parameters", {}))
        req_id = request.get("id")

        if tool_name not in TOOLS:
            self._send_json({
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"},
                "id": req_id,
            })
            return

        try:
            tool = TOOLS[tool_name]
            # Route call according to tool's public method
            if tool_name == "financial_ratios":
                ticker = params.pop("ticker", "UNKNOWN")
                result_text = tool.compute(ticker, **{
                    k: v for k, v in params.items()
                    if k in [
                        "dividend_per_share", "share_price", "earnings_per_share",
                        "total_debt", "total_equity", "net_profit",
                        "revenue", "prev_revenue", "shares_outstanding", "market_cap",
                    ]
                })
            elif tool_name == "currency":
                result_text = tool.fetch(
                    base=params.get("base", "USD"),
                    target=params.get("target", "MYR"),
                )
            else:
                result_text = tool.fetch(params.get("ticker", ""))

            self._send_json({
                "jsonrpc": "2.0",
                "result": {"content": result_text},
                "id": req_id,
            })

        except Exception as exc:
            self._send_json({
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": str(exc)},
                "id": req_id,
            })

    # ── Helpers ────────────────────────────────────────────────────────── #

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Server lifecycle ──────────────────────────────────────────────────────── #

class MCPServer:
    def __init__(self, host: str = "localhost", port: int = 8080):
        self.host = host
        self.port = port
        self._server: HTTPServer | None = None

    def start(self) -> None:
        auth_note = f"Auth: X-API-Key required ({_API_KEY[:4]}…)" if _API_KEY else "Auth: DISABLED (dev mode)"
        self._server = HTTPServer((self.host, self.port), MCPHandler)
        print(f"[MCPServer] 🚀 BursaSentinel MCP v{_VERSION} → http://{self.host}:{self.port}")
        print(f"[MCPServer] Tools: {list(TOOLS.keys())}")
        print(f"[MCPServer] {auth_note}")
        print(f"[MCPServer] Health: http://{self.host}:{self.port}/health")
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            print("\n[MCPServer] Shutting down.")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()


# ── CLI ───────────────────────────────────────────────────────────────────── #

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BursaSentinel MCP Server v2")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    MCPServer(host=args.host, port=args.port).start()
