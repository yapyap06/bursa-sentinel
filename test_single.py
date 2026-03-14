"""Single-shot Gemini test with model from .env"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dotenv import load_dotenv
load_dotenv('.env')
import google.generativeai as genai
genai.configure(api_key=os.environ['GOOGLE_API_KEY'])
model_name = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
print(f'Key: {os.environ["GOOGLE_API_KEY"][:12]}...')
print(f'Model: {model_name}')
model = genai.GenerativeModel(model_name)
resp = model.generate_content('Return only this JSON with no extra text: {"status":"ok"}')
print('SUCCESS:', resp.text[:300])
