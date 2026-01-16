import re
from datetime import datetime
def parse_time_token(token, plan_date):
    token = token.lower().strip()

    # 🔒 Extract time safely FIRST (space-aware)
    match = re.search(
        r"\b(\d{1,2})(?:[:\.](\d{2}))?\s*(am|pm)\b",
        token
    )

    if not match:
        raise ValueError(f"Invalid time token: {token}")

    hour, minute, meridiem = match.groups()

    # Normalize
    minute = minute or "00"
    token = f"{hour}:{minute}{meridiem}"

    # Validate ranges
    if not (1 <= int(hour) <= 12):
        raise ValueError(f"Invalid hour in time: {token}")
    if not (0 <= int(minute) < 60):
        raise ValueError(f"Invalid minute in time: {token}")

    return datetime.strptime(
        f"{plan_date} {token}",
        "%Y-%m-%d %I:%M%p",
    )
    