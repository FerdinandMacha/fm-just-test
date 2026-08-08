# /// script
# dependencies = [
#   "google-genai",
#   "httpx",
#   "beautifulsoup4",
# ]
# ///

import sys
import traceback
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover - allows tests to run without the package
    genai = None
    types = None

from zoneinfo import ZoneInfo
from config_loader import load_config

BASE_DIR = Path(__file__).resolve().parent

DEFAULT_CONFIG = {
    "target_url": "https://www.mujkaktus.cz/chces-pridat",
    "gemini_model": "gemini-3.5-flash-lite",
    "gemini_api_key": "",
    "email_to": "",
    "email_from": "",
    "email_subject": "Event status update",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_username": "",
    "smtp_password": "",
}

ENV_OVERRIDES = {
    "target_url": "TARGET_URL",
    "gemini_model": "GEMINI_MODEL",
    "gemini_api_key": "GEMINI_API_KEY",
    "email_to": "EMAIL_TO",
    "email_from": "EMAIL_FROM",
    "email_subject": "EMAIL_SUBJECT",
    "smtp_host": "SMTP_HOST",
    "smtp_port": "SMTP_PORT",
    "smtp_username": "SMTP_USERNAME",
    "smtp_password": "SMTP_PASSWORD",
}

# Support production environment variable aliases
if os.getenv("GMAIL_PASSWORD"):
    ENV_OVERRIDES["smtp_password"] = "GMAIL_PASSWORD"

if os.getenv("EMAIL"):
    ENV_OVERRIDES["email_to"] = "EMAIL"
    ENV_OVERRIDES["email_from"] = "EMAIL"
    ENV_OVERRIDES["smtp_username"] = "EMAIL"

CONFIG = load_config(
    base_dir=BASE_DIR,
    defaults=DEFAULT_CONFIG,
    env_overrides=ENV_OVERRIDES,
)

# --- CONFIGURATION ---
TARGET_URL = CONFIG["target_url"]
MODEL_NAME = CONFIG["gemini_model"]
GEMINI_API_KEY = CONFIG["gemini_api_key"]

EMAIL_TO = CONFIG["email_to"]
EMAIL_FROM = CONFIG["email_from"]
EMAIL_SUBJECT = CONFIG["email_subject"]
SMTP_HOST = CONFIG["smtp_host"]
SMTP_PORT = CONFIG["smtp_port"]
SMTP_USERNAME = CONFIG["smtp_username"]
SMTP_PASSWORD = CONFIG["smtp_password"]


def get_web_content(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8,en-US;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "max-age=0",
        "Sec-Ch-Ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }

    response = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    return soup.get_text(separator="\n", strip=True)


def build_prompt(page_text, current_datetime):
    return f"""
You are analyzing a mobile operator web page to detect actionable promotional events ("Dobíječka").

Goal: Identify if there is an actionable event on the page relative to the provided CURRENT_DATETIME.

CLASSIFICATION RULES:
1. Compare the page's event date and time window against CURRENT_DATETIME.
2. Return STATUS: ACTIVE if the event date matches CURRENT_DATETIME's date AND current time is WITHIN the start and end time.
3. Return STATUS: UPCOMING if the event date matches CURRENT_DATETIME's date AND current time is BEFORE the start time.
4. Return STATUS: INACTIVE for all other cases (event date does not match CURRENT_DATETIME's date, current time is after the end time, or no event listed).

OUTPUT FORMAT:
STATUS: ACTIVE | UPCOMING | INACTIVE
EVENT_DATE: <DD. MM. YYYY or blank>
EVENT_TIME: <HH:MM - HH:MM or blank>
REASON: <One short sentence explaining the status relative to CURRENT_DATETIME>

CURRENT_DATETIME: {current_datetime}
TIMEZONE: Europe/Prague

PAGE CONTENT:
{page_text[:12000]}
"""


def parse_analysis_response(text):
    values = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip().upper()] = value.strip()

    status = values.get("STATUS", "UNKNOWN")
    return {
        "status": status,
        "event_date": values.get("EVENT_DATE", ""),
        "event_time": values.get("EVENT_TIME", ""),
        "reason": values.get("REASON", ""),
    }


def analyze_with_ai(page_text, client):
    tz = ZoneInfo("Europe/Prague")
    current_datetime = datetime.now(tz).strftime("%d. %m. %Y, %H:%M")
    prompt = build_prompt(page_text, current_datetime)

    if types is None or genai is None:
        return {
            "status": "UNKNOWN",
            "event_date": "",
            "event_time": "",
            "reason": "Google client is not available",
        }

    config = types.GenerateContentConfig(
        max_output_tokens=300,
        temperature=0.2,
    )

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=config,
        )
        return parse_analysis_response(response.text)
    except Exception as e:
        return {
            "status": "UNKNOWN",
            "event_date": "",
            "event_time": "",
            "reason": f"Failed to parse AI response: {str(e)}",
        }


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
    try:
        # Local variables pull consistently from CONFIG now
        local_gemini_api_key = GEMINI_API_KEY
        local_email_to = EMAIL_TO
        local_email_from = EMAIL_FROM
        local_smtp_username = SMTP_USERNAME

        # --- SET BREAKPOINT ON THE LINE BELOW ---
        missing = [
            name
            for name, val in {
                "GEMINI_API_KEY": local_gemini_api_key,
                "EMAIL_TO": local_email_to,
                "EMAIL_FROM": local_email_from,
                "SMTP_USERNAME": local_smtp_username,
            }.items()
            if not val
        ]

        if missing:
            print(f"Error: Missing required config: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)

        client = genai.Client(api_key=local_gemini_api_key)

        print("Fetching webpage...")
        current_content = get_web_content(TARGET_URL)

        print("Analyzing event status with Gemini...")
        ai_analysis = analyze_with_ai(current_content, client)
        print("--- AI Analysis Result ---")
        print(ai_analysis)

        if ai_analysis["status"] == "UNKNOWN":
            print(f"Error: AI analysis failed - {ai_analysis['reason']}", file=sys.stderr)
            sys.exit(1)

        if ai_analysis["status"] in {"ACTIVE", "UPCOMING"}:
            summary = ai_analysis.get("reason", "Event status updated")
            alert_msg = f"Event status: {ai_analysis['status']}\n{summary}"
            send_notification(alert_msg)
        else:
            print("No actionable event status detected.")

    except Exception:
        print("Unhandled error in main():", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()