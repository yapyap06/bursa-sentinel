"""
BursaSentinel — News Scraper Tool (MCP Tool)
=============================================
Scrapes financial news headlines related to a given Bursa Malaysia
ticker from public news sources using BeautifulSoup.

Mounted as an MCP tool for the Infiltrator Agent.
"""

import re
from typing import Optional

import requests
from bs4 import BeautifulSoup


class NewsScraperTool:
    """
    MCP Tool: Financial news headline scraper.

    Targets The Star Business and i3investor news feeds.
    Falls back to clearly labelled mock headlines for demo use.
    """

    SOURCES = [
        {
            "name": "i3investor",
            "url": "https://klse.i3investor.com/web/blog/detail/{code}",
        },
        {
            "name": "The Star Business",
            "url": "https://www.thestar.com.my/search?q={code}&cat=business",
        },
    ]
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    TIMEOUT = 10
    MAX_HEADLINES = 5

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def fetch(self, ticker: str) -> str:
        """
        Fetch recent news headlines for a Bursa ticker.

        Returns a plain-text summary for the Infiltrator Agent.
        """
        ticker_upper = ticker.strip().upper()
        print(f"  [NewsScraperTool] Fetching news for {ticker_upper}...")

        headlines = []
        for source in self.SOURCES:
            try:
                fetched = self._scrape_source(ticker_upper, source)
                headlines.extend(fetched)
            except Exception as e:
                print(f"  [NewsScraperTool] ⚠️  Source '{source['name']}' failed: {e}")

        if not headlines:
            print("  [NewsScraperTool] No live headlines found. Using mock data.")
            return self._mock_news(ticker_upper)

        return self._format_output(ticker_upper, headlines[:self.MAX_HEADLINES])

    # ------------------------------------------------------------------ #
    #  Scraping logic                                                      #
    # ------------------------------------------------------------------ #

    def _scrape_source(self, ticker: str, source: dict) -> list[dict]:
        url = source["url"].format(code=ticker.lower())
        resp = requests.get(url, headers=self.HEADERS, timeout=self.TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        results = []
        # General strategy: look for <a> or <h2>/<h3> inside article-ish containers
        candidates = soup.find_all(["h2", "h3", "a"], limit=20)
        for tag in candidates:
            text = tag.get_text(strip=True)
            # Filter: must mention ticker or be substantive (>20 chars)
            if len(text) > 20 and (ticker.lower() in text.lower() or
                                    re.search(r"\b(dividend|earnings|profit|revenue|merger|acquire)\b",
                                              text, re.I)):
                results.append({
                    "headline": text[:200],
                    "source": source["name"],
                })
        return results

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _format_output(ticker: str, headlines: list[dict]) -> str:
        lines = [f"NEWS FOR: {ticker}"]
        for i, h in enumerate(headlines, 1):
            lines.append(f"{i}. [{h['source']}] {h['headline']}")
        return "\n".join(lines)

    @staticmethod
    def _mock_news(ticker: str) -> str:
        """Clearly-labelled mock news for demo / CI."""
        MOCK_NEWS_DB: dict[str, list[dict]] = {
            "MAYBANK": [
                {"headline": "Maybank declares 32 sen interim dividend, yield remains above 6%",
                 "source": "The Star Business (MOCK)", "sentiment": "positive"},
                {"headline": "Maybank Q3 net profit up 8.2% YoY driven by Islamic banking growth",
                 "source": "The Edge Markets (MOCK)", "sentiment": "positive"},
                {"headline": "Analysts warn of NIM compression risk for Maybank amid rate uncertainty",
                 "source": "Reuters Malaysia (MOCK)", "sentiment": "negative"},
            ],
            "CIMB": [
                {"headline": "CIMB Group posts record quarterly profit on regional expansion",
                 "source": "The Star Business (MOCK)", "sentiment": "positive"},
                {"headline": "CIMB dividend payout ratio raised to 55% for FY2025",
                 "source": "The Edge Markets (MOCK)", "sentiment": "positive"},
            ],
            "TENAGA": [
                {"headline": "Tenaga Nasional reports lower profits amid coal cost volatility",
                 "source": "The Star Business (MOCK)", "sentiment": "negative"},
                {"headline": "TNB announces RM500m green sukuk issuance for renewable projects",
                 "source": "Bernama (MOCK)", "sentiment": "positive"},
            ],
        }
        items = MOCK_NEWS_DB.get(ticker.upper(), [
            {"headline": f"No recent news found for {ticker}",
             "source": "MOCK", "sentiment": "neutral"},
        ])
        lines = [f"NEWS FOR: {ticker}", "SOURCE: MOCK_DATA (live scrape unavailable)"]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. [{item['source']}] {item['headline']} ({item['sentiment']})")
        return "\n".join(lines)
