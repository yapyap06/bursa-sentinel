"""Direct InfiltratorAgent test — runs from project root."""
import os
from dotenv import load_dotenv
load_dotenv('.env')   # load from project directory

from tools.bursa_scraper import BursaScraperTool
from tools.news_scraper import NewsScraperTool
from agents.infiltrator import InfiltratorAgent

print("API KEY:", os.environ.get("GOOGLE_API_KEY","(missing)")[:12], "...")
bursa = BursaScraperTool()
news  = NewsScraperTool()
agent = InfiltratorAgent(bursa_tool=bursa, news_tool=news)
result = agent.run("MAYBANK")
print("\n=== RESULT ===")
import json; print(json.dumps(result, indent=2)[:2000])
