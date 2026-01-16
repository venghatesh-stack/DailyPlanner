import re
from datetime import datetime

def parse_time_token(token, plan_date):
    token = token.lower().strip()
    match = re.search(r"\b(\d{1,2})(?:[:\.](\d{2}))?\s*(am|pm)\b", token)

    if not match:
        raise ValueError(f"Invalid time token: {token}")

    h, m, ap = match.groups()
    m = m or "00"

    return datetime.strptime(
        f"{plan_date} {h}:{m}{ap}", "%Y-%m-%d %I:%M%p"
    )
