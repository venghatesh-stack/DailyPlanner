import os
import requests

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"


def call_gemini(prompt: str) -> str:
    headers = {
        "Content-Type": "application/json"
    }

    params = {
        "key": GOOGLE_API_KEY
    }

    data = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }

    response = requests.post(GEMINI_URL, headers=headers, params=params, json=data)
    response.raise_for_status()

    result = response.json()
    return result["candidates"][0]["content"]["parts"][0]["text"]