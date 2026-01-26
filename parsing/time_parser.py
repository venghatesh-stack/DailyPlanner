import re
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

def parse_time_token(token, plan_date):
    token = token.lower().strip()

    match = re.search(
        r"\b(\d{1,2})(?:[:\.](\d{2}))?\s*(am|pm)\b",
        token
    )

    if not match:
        raise ValueError(f"Invalid time token: {token}")

    hour, minute, meridiem = match.groups()
    minute = minute or "00"

    if not (1 <= int(hour) <= 12):
        raise ValueError(f"Invalid hour in time: {token}")
    if not (0 <= int(minute) < 60):
        raise ValueError(f"Invalid minute in time: {token}")

    # Parse as local IST time (NOT UTC)
    naive = datetime.strptime(
        f"{plan_date} {hour}:{minute}{meridiem}",
        "%Y-%m-%d %I:%M%p",
    )

    # 🔥 THIS LINE FIXES EVERYTHING
    return naive.replace(tzinfo=IST)
