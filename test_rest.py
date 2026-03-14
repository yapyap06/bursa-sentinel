"""Direct REST API test - bypasses SDK quota tracking."""
import os, sys, json
import urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dotenv import load_dotenv
load_dotenv('.env')

api_key = os.environ['GOOGLE_API_KEY']
print(f'Key: {api_key[:12]}...')

url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
payload = json.dumps({"contents": [{"parts": [{"text": "Say hi"}]}]}).encode()
req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        text = data['candidates'][0]['content']['parts'][0]['text']
        print("SUCCESS:", text[:200])
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print("HTTP ERROR:", e.code, body[:500])
