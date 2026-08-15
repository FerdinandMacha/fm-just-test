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
import config_registry as cfg
from config_loader import load_config

BASE_DIR = Path(__file__).resolve().parent

cfg.register(
    "target_url", "https://www.mujkaktus.cz/chces-pridat", env_vars=("TARGET_URL",)
)
cfg.register("gemini_model", "gemini-3.5-flash-lite", env_vars=("GEMINI_MODEL",))
cfg.register(
    "gemini_api_key", "", secret=True, required=True, env_vars=("GEMINI_API_KEY",)
)
cfg.register("email_to", "", required=True, env_vars=("EMAIL", "EMAIL_TO"))
cfg.register("email_from", "", required=True, env_vars=("EMAIL", "EMAIL_FROM"))
cfg.register("email_subject", "Event status update", env_vars=("EMAIL_SUBJECT",))
cfg.register("smtp_host", "smtp.gmail.com", env_vars=("SMTP_HOST",))
cfg.register("smtp_port", 587, coerce=int, env_vars=("SMTP_PORT",))
cfg.register(
    "smtp_username",
    "",
    secret=True,
    required=True,
    env_vars=("EMAIL", "SMTP_USERNAME"),
)
cfg.register(
    "smtp_password",
    "",
    secret=True,
    env_vars=("GMAIL_PASSWORD", "SMTP_PASSWORD"),
)

try:
    CONFIG = load_config(base_dir=BASE_DIR)
except ValueError as exc:
    print(f"Error: {exc}", file=sys.stderr)
    sys.exit(1)

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
4. Return STATUS: INACTIVE for all other cases (e.g. current time is after the end time, or no event listed).

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
        client = genai.Client(api_key=GEMINI_API_KEY)

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
