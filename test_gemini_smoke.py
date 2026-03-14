"""Direct smoke test of google-genai SDK in project directory."""
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
api_key = os.environ.get("GOOGLE_API_KEY", "")
print(f"KEY loaded: {api_key[:8]}...")

from google import genai
from google.genai import types as genai_types

client = genai.Client(api_key=api_key)

resp = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="Return exactly this JSON and nothing else: {\"test\": \"ok\", \"value\": 42}",
    config=genai_types.GenerateContentConfig(temperature=0.1),
)

print("candidates:", len(resp.candidates))
if resp.candidates:
    parts = resp.candidates[0].content.parts
    text = "".join(p.text for p in parts if hasattr(p, 'text'))
    print("TEXT:", repr(text[:400]))
else:
    print("No candidates!")
    print("Response:", resp)
