import os
import requests

SUPABASE_URL = "https://gidpxopleslvmrrycood.supabase.co"
SUPABASE_KEY = "sb_publishable_jv6-xI--WU4Tsm2Sq8wRYg_9Vf85OOi"

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Supabase env vars not set")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

def get(table, params=None):
    url = f"{BASE_URL}/{table}"

    if params is None:
        params = {}

    # REQUIRED for Supabase/PostgREST
    params["select"] = "*"

    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    return r.json()

def post(path, data, prefer=None):
    headers = HEADERS.copy()
    if prefer:
        headers["Prefer"] = prefer

    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers=headers,
        json=data,
    )
    r.raise_for_status()
    return r.json() if r.text else None

def delete(path, params):
    r = requests.delete(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers=HEADERS,
        params=params,
    )
    r.raise_for_status()

