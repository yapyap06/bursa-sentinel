"""Test google-genai SDK with env var approach (AI Studio endpoint)."""
import os
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Load .env first
from dotenv import load_dotenv
load_dotenv('.env')
key = os.environ.get("GOOGLE_API_KEY", "")
print(f"Key starts with: {key[:12]}")

# Try google-genai with env var
os.environ["GOOGLE_API_KEY"] = key  # ensure it's set
from google import genai

# When using google.generativeai is deprecated, google-genai SDK
# can be configured with env var directly
client = genai.Client()   # reads from GOOGLE_API_KEY env var automatically

resp = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="Return this JSON: {\"test\": \"ok\"}",
)
print("candidates:", len(resp.candidates) if resp.candidates else 0)
if resp.candidates:
    parts = resp.candidates[0].content.parts
    text = "".join(p.text for p in parts if hasattr(p, 'text'))
    print("TEXT:", text[:200])
