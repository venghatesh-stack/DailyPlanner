
import requests
import logging
SUPABASE_URL = "https://gidpxopleslvmrrycood.supabase.co"
SUPABASE_KEY = "sb_publishable_jv6-xI--WU4Tsm2Sq8wRYg_9Vf85OOi"
print("SUPABASE_URL =", SUPABASE_URL)
print("SUPABASE_KEY present =", bool(SUPABASE_KEY))

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Supabase env vars not set")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}
logger = logging.getLogger("daily_plan")



def get(path, params=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"

    # 🔍 Log intent
    logger.debug("SUPABASE GET → %s | params=%s", url, params)

    r = requests.get(
        url,
        headers=HEADERS,
        params=params,
    )

    # 🔑 Log final URL (THIS IS WHAT SUPABASE SEES)
    logger.debug("SUPABASE FINAL URL → %s", r.url)

    if not r.ok:
        # 🔥 Log full error context
        logger.error("SUPABASE ERROR %s", r.status_code)
        logger.error("SUPABASE URL → %s", r.url)
        logger.error("SUPABASE RESPONSE → %s", r.text)

        r.raise_for_status()

    return r.json()

def post(path, data, prefer=None):
    headers = HEADERS.copy()
    if prefer:
        headers["Prefer"] = prefer
    logger.debug("SUPABASE Post → %s | params=%s", path, data)
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
def update(table, params, json):
    """
    Update rows in a Supabase table.
    params example: {"id": "eq.123"}
    json example: {"is_done": True}
    """
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    # 🔍 Log intent
    logger.debug("SUPABASE UPDATE → %s | params=%s", url, params)
    response = requests.patch(
        url,
        headers=HEADERS,
        params=params,
        json=json,
        timeout=10
    )
    # 🔑 Log final URL (THIS IS WHAT SUPABASE SEES)
    logger.debug("SUPABASE FINAL URL → %s", response.url)
    if not response.ok:
        logger.error("SUPABASE RESPONSE → %s", response.text)
        raise Exception(
            f"UPDATE failed {response.status_code}: {response.text}",
        )

    return response.json() if response.text else None