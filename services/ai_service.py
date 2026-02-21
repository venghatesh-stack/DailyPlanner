
import requests
import os

def call_gemini(prompt):
    API_KEY = os.getenv("GEMINI_API_KEY")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={API_KEY}"

    headers = {
        "Content-Type": "application/json"
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    response = requests.post(url, headers=headers, json=payload)

    print("Gemini status:", response.status_code)
    print("Gemini response:", response.text)

    response.raise_for_status()

    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]