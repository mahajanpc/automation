#!/usr/bin/env python3
import os
import smtplib
import requests
from dotenv import load_dotenv

load_dotenv("/home/mahajan-ashok/automation/.env")

print("=" * 55)
print("       API & CREDENTIALS DIAGNOSTIC CHECK        ")
print("=" * 55)

# 1. Gemini AI
print("\n[1/4] Checking Google Gemini API...")
gemini_key = os.getenv("GEMINI_API_KEY", "")
if not gemini_key or gemini_key.startswith("your_"):
    print("  ❌ GEMINI_API_KEY is missing or placeholder.")
else:
    try:
        from google import genai
        client = genai.Client(api_key=gemini_key)
        resp = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents="Say 'healthy lifestyle' in Telugu in 3 words"
        )
        print(f"  ✅ SUCCESS: Gemini generated: '{resp.text.strip()}'")
    except Exception as e:
        print(f"  ❌ FAILED: {e}")

# 2. Pixabay Free Video API
print("\n[2/4] Checking Pixabay Video API...")
pix_key = os.getenv("PIXABAY_API_KEY", "")
if not pix_key or pix_key.startswith("your_"):
    print("  ❌ PIXABAY_API_KEY is missing or placeholder.")
else:
    try:
        r = requests.get(f"https://pixabay.com/api/videos/?key={pix_key}&q=healthy&per_page=3", timeout=10)
        if r.status_code == 200 and len(r.json().get("hits", [])) > 0:
            count = len(r.json()["hits"])
            print(f"  ✅ SUCCESS: Connected to Pixabay (found {count} video clips).")
        else:
            print(f"  ❌ FAILED: Status code {r.status_code}, response: {r.text[:80]}")
    except Exception as e:
        print(f"  ❌ FAILED: {e}")

# 3. Cloudinary Video Host
print("\n[3/4] Checking Cloudinary URL...")
c_url = os.getenv("CLOUDINARY_URL", "")
if not c_url or c_url.startswith("your_") or "your_api_key" in c_url or "@" not in c_url:
    print("  ⚠️  ATTENTION: CLOUDINARY_URL is incomplete or missing '@'.")
    print("     Format must be: cloudinary://<API_KEY>:<API_SECRET>@<CLOUD_NAME>")
    print("     (You already have the secret, just add your numeric API Key and @boe4lcof!)")
else:
    try:
        import cloudinary
        import cloudinary.api
        cloudinary.config(cloudinary_url=c_url)
        ping_res = cloudinary.api.ping()
        print(f"  ✅ SUCCESS: Cloudinary connected (Status: {ping_res.get('status', 'ok')}).")
    except Exception as e:
        print(f"  ❌ FAILED: {e}")

# 4. Email (Gmail SMTP)
print("\n[4/4] Checking Gmail Review Email (SMTP)...")
smtp_email = os.getenv("SMTP_EMAIL", "")
smtp_pass = os.getenv("SMTP_PASSWORD", "")
if not smtp_email or not smtp_pass or smtp_email.startswith("your_"):
    print("  ❌ SMTP_EMAIL or SMTP_PASSWORD missing.")
else:
    try:
        server_host = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        server_port = int(os.getenv("SMTP_PORT", "587"))
        with smtplib.SMTP(server_host, server_port, timeout=10) as s:
            s.starttls()
            s.login(smtp_email, smtp_pass)
            print("  ✅ SUCCESS: Gmail authenticated successfully! Ready to deliver reels.")
    except Exception as e:
        print(f"  ❌ FAILED: {e}")

print("\n" + "=" * 55)
print("Diagnostic Complete.")
print("=" * 55)

