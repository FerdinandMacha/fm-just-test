# /// script
# dependencies = [
#   "google-genai",
#   "httpx",
#   "beautifulsoup4",
# ]
# ///

import os
import httpx
from bs4 import BeautifulSoup
from google import genai

# --- CONFIGURATION ---
TARGET_URL = "https://www.mujkaktus.cz/chces-pridat"  # Change this to your target URL
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "my_private_web_scraper_2026")
LAST_DATA_FILE = "last_content.txt"
MODEL_NAME = "gemini-flash-latest"  # Future-proof alias pointing to the latest Flash model

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
    {previous_text[:3000]}
    
    NEW CONTENT:
    {current_text[:3000]}
    
    Respond STRICTLY in the following format:
    CHANGED: [Yes or No]
    SUMMARY: [If Yes, provide a highly concise summary of what changed under 30 words. If No, leave blank]
    """
    
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )
        return response.text
    except Exception as e:
        return f"CHANGED: Error\nSUMMARY: Failed to parse AI response: {str(e)}"

def send_notification(message):
    httpx.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode('utf-8'))

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