
import time
import requests
import os

def call_gemini(prompt, retries=3):
    API_KEY = os.getenv("GOOGLE_API_KEY")
    model = "gemini-3-flash-preview"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={API_KEY}"

    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    for attempt in range(retries):
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 200:
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

        # If high demand or rate limit
        if response.status_code in [429, 503]:
            time.sleep(2 * (attempt + 1))
            continue

        print("Gemini error:", response.text)
        break

    return "AI service is busy. Please try again in a few seconds."