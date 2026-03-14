"""
BursaSentinel — Bursa Announcement Tool (MCP Tool)
====================================================
Scrapes Bursa Malaysia corporate announcements for a given ticker.
Returns a list of recent announcement titles, dates, and document links.
Falls back to clearly-labelled mock data when live scraping fails.
"""

import re
import time
from typing import Optional
import requests
from bs4 import BeautifulSoup


class BursaAnnouncementTool:
    """
    MCP Tool: Bursa Malaysia corporate announcements scraper.
    Targets the Bursa Malaysia announcements portal.
    """

    ANNOUNCE_URL = (
        "https://www.bursamalaysia.com/market_information/announcements/company_announcement"
        "?stock_code={code}&page=1"
    )
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    TIMEOUT = 12
    MAX_RESULTS = 5

    MOCK_DB: dict[str, list[dict]] = {
        "MAYBANK": [
            {"title": "Quarterly Financial Report Q3 FY2025",
             "date": "2025-11-28", "category": "Financial Results", "url": "#"},
            {"title": "Notice of Interim Dividend — 32 sen per share",
             "date": "2025-11-15", "category": "Dividend", "url": "#"},
            {"title": "Change in Boardroom — Appointment of Independent Director",
             "date": "2025-10-02", "category": "Change in Boardroom", "url": "#"},
        ],
        "CIMB": [
            {"title": "CIMB Group Q3 2025 Financial Results",
             "date": "2025-11-30", "category": "Financial Results", "url": "#"},
            {"title": "CIMB Niaga Subsidiary Expansion Announcement",
             "date": "2025-10-18", "category": "General Announcement", "url": "#"},
        ],
        "TENAGA": [
            {"title": "RM500m Green Sukuk Issuance Completion",
             "date": "2025-12-01", "category": "Corporate Action", "url": "#"},
            {"title": "Quarterly Financial Report Q3 FY2025",
             "date": "2025-11-25", "category": "Financial Results", "url": "#"},
            {"title": "Unscheduled Trading Halt — Price Sensitive Announcement",
             "date": "2025-10-10", "category": "Trading Halt", "url": "#"},
        ],
    }

    # ── Public API ──────────────────────────────────────────────────────── #

    def fetch(self, ticker: str) -> str:
        """Fetch recent corporate announcements. Returns plain-text summary."""
        ticker_upper = ticker.strip().upper()
        print(f"  [BursaAnnouncementTool] Fetching announcements for {ticker_upper}...")
        try:
            items = self._scrape(ticker_upper)
            if items:
                return self._format(ticker_upper, items, source="Bursa Malaysia Portal")
        except Exception as e:
            print(f"  [BursaAnnouncementTool] ⚠️  Scrape failed: {e}. Using mock.")
        return self._mock(ticker_upper)

    # ── Scraping ────────────────────────────────────────────────────────── #

    def _scrape(self, ticker: str) -> list[dict]:
        url = self.ANNOUNCE_URL.format(code=ticker)
        resp = requests.get(url, headers=self.HEADERS, timeout=self.TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        items = []
        # Try common Bursa table row patterns
        rows = soup.select("table tr") or soup.select(".announcement-row")
        for row in rows:
            cols = row.find_all(["td", "th"])
            if len(cols) >= 2:
                title = cols[0].get_text(strip=True)
                date_text = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                link_tag = row.find("a", href=True)
                if title and len(title) > 10:
                    items.append({
                        "title": title[:200],
                        "date": date_text[:20],
                        "category": "Announcement",
                        "url": link_tag["href"] if link_tag else "#",
                    })
            if len(items) >= self.MAX_RESULTS:
                break
        return items

    # ── Formatting ──────────────────────────────────────────────────────── #

    @staticmethod
    def _format(ticker: str, items: list[dict], source: str) -> str:
        lines = [f"ANNOUNCEMENTS FOR: {ticker}", f"SOURCE: {source}"]
        for i, item in enumerate(items, 1):
            lines.append(
                f"{i}. [{item.get('date','?')}] [{item.get('category','?')}] "
                f"{item.get('title','?')}"
            )
        return "\n".join(lines)

    def _mock(self, ticker: str) -> str:
        items = self.MOCK_DB.get(ticker, [
            {"title": f"No recent announcements found for {ticker}",
             "date": "N/A", "category": "N/A", "url": "#"},
        ])
        return self._format(ticker, items, source="MOCK_DATA (live scrape unavailable)")
