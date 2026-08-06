# /// script
# dependencies = [
#   "google-genai",
#   "httpx",
#   "beautifulsoup4",
# ]
# ///

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

from config_loader import load_config

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = {
    "target_url": "https://www.mujkaktus.cz/chces-pridat",
    "last_data_file": "last_content.txt",
    "gemini_model": "gemini-3.5-flash-lite",
    "email_to": REDACTED"",
    "email_from": REDACTED"",
    "email_subject": "The watched web page changed",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_username": REDACTED"",
    "smtp_password": "",
}
ENV_OVERRIDES = {
    "target_url": "TARGET_URL",
    "gemini_model": "GEMINI_MODEL",
    "email_to": "EMAIL_TO",
    "email_from": "EMAIL_FROM",
    "email_subject": "EMAIL_SUBJECT",
    "smtp_host": "SMTP_HOST",
    "smtp_port": "SMTP_PORT",
    "smtp_username": "SMTP_USERNAME",
    "smtp_password": "SMTP_PASSWORD",
}

# Support the production variable naming used by the deployment environment.
if os.getenv("GMAIL_PASSWORD"):
    ENV_OVERRIDES["smtp_password"] = "GMAIL_PASSWORD"

CONFIG = load_config(
    base_dir=BASE_DIR,
    defaults=DEFAULT_CONFIG,
    env_overrides=ENV_OVERRIDES,
)

# --- CONFIGURATION ---
TARGET_URL = CONFIG["target_url"]
LAST_DATA_FILE = str(BASE_DIR / CONFIG["last_data_file"])
MODEL_NAME = CONFIG["gemini_model"]

EMAIL_TO = CONFIG["email_to"]
EMAIL_FROM = CONFIG["email_from"]
EMAIL_SUBJECT = CONFIG["email_subject"]
SMTP_HOST = CONFIG["smtp_host"]
SMTP_PORT = CONFIG["smtp_port"]
SMTP_USERNAME = CONFIG["smtp_username"]
SMTP_PASSWORD = CONFIG["smtp_password"]

def get_web_content(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    response = httpx.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, 'html.parser')
    return soup.get_text(separator="\n", strip=True)

def analyze_with_ai(current_text, previous_text, client):
    prompt = f"""
    You are an automated web analysis agent. Compare the old content of a webpage with its newly updated content.
    Determine if anything significant has changed. Ignore minor formatting issues, ads, timestamps, or structural reloads.
    
    OLD CONTENT:
    {previous_text[:10000]}
    
    NEW CONTENT:
    {current_text[:10000]}
    
    Respond STRICTLY in the following format:
    CHANGED: [Yes or No]
    SUMMARY: [If Yes, provide a highly concise summary of what changed under 30 words. If No, leave blank]
    """

    # Configure maximum output tokens to cap completion length and lower total processing time
    config = types.GenerateContentConfig(
        max_output_tokens=300,
        temperature=0.2, # Lower temperature yields faster, more direct responses
    )
    
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=config,
        )
        return response.text
    except Exception as e:
        return f"CHANGED: Error\nSUMMARY: Failed to parse AI response: {str(e)}"

def send_notification(message):
    if not SMTP_PASSWORD:
        print("Email notification skipped: SMTP_PASSWORD not set.")
        return

    recipients = [address.strip() for address in EMAIL_TO.split(",") if address.strip()]
    if not recipients:
        print("Email notification skipped: EMAIL_TO is empty.")
        return

    msg = EmailMessage()
    msg["Subject"] = EMAIL_SUBJECT
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(recipients)
    msg.set_content(message)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"Email notification sent to {msg['To']}")
    except Exception as e:
        print(f"Failed to send email notification: {e}")

def main():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: Missing GEMINI_API_KEY environment variable.")
        return

    # Initialize Google GenAI client
    client = genai.Client(api_key=api_key)

    print("Fetching webpage...")
    current_content = get_web_content(TARGET_URL)
    
    # Check baseline file existence
    if not os.path.exists(LAST_DATA_FILE):
        with open(LAST_DATA_FILE, "w", encoding="utf-8") as f:
            f.write(current_content)
        print("Initial run completed. Baseline content saved.")
        return

    with open(LAST_DATA_FILE, "r", encoding="utf-8") as f:
        previous_content = f.read()

    # Pre-check for raw text changes to avoid unnecessary AI API calls
    if current_content == previous_content:
        print("No raw text changes detected. Skipping AI analysis.")
        return

    print("Changes detected in raw text. Analyzing with Gemini...")
    ai_analysis = analyze_with_ai(current_content, previous_content, client)
    print("--- AI Analysis Result ---")
    print(ai_analysis)

    if "CHANGED: Yes" in ai_analysis:
        summary = ai_analysis.split("SUMMARY:")[-1].strip()
        alert_msg = f"Webpage Updated! 🚨\n{summary}"
        send_notification(alert_msg)
        
        # Save updated state
        with open(LAST_DATA_FILE, "w", encoding="utf-8") as f:
            f.write(current_content)
    else:
        print("No meaningful changes flagged by AI.")

if __name__ == "__main__":
    main()