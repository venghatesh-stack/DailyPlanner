import re
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

def parse_time_token(token, plan_date):
    token = token.lower().strip()

    # ----------------------------------
    # 1️⃣ am / pm format (existing logic)
    # ----------------------------------
    match = re.search(
        r"\b(\d{1,2})(?:[:\.](\d{2}))?\s*(am|pm)\b",
        token
    )

    if match:
        hour, minute, meridiem = match.groups()
        minute = minute or "00"

        if not (1 <= int(hour) <= 12):
            raise ValueError(f"Invalid hour in time: {token}")
        if not (0 <= int(minute) < 60):
            raise ValueError(f"Invalid minute in time: {token}")

        naive = datetime.strptime(
            f"{plan_date} {hour}:{minute}{meridiem}",
            "%Y-%m-%d %I:%M%p",
        )

        return naive.replace(tzinfo=IST)

    # ----------------------------------
    # 2️⃣ Plain hour fallback: "9", "at 9", "9 meeting"
    # ----------------------------------
    match = re.search(r"\b(\d{1,2})\b", token)
    if match:
        hour = int(match.group(1))

        if 0 <= hour <= 23:
            naive = datetime.strptime(
                f"{plan_date} {hour}:00",
                "%Y-%m-%d %H:%M",
            )
            return naive.replace(tzinfo=IST)

    # ----------------------------------
    # ❌ Nothing matched
    # ----------------------------------
    raise ValueError(f"Invalid time token: {token}")
def parse_time_range(text, plan_date):
    text = text.lower().strip()

    # Matches:
    # 9-12
    # 9.30-12.30
    # 9:00-12
    # 9am-12pm
    match = re.search(
        r"\b(\d{1,2}(?:[:\.]\d{2})?\s*(?:am|pm)?)\s*-\s*(\d{1,2}(?:[:\.]\d{2})?\s*(?:am|pm)?)\b",
        text
    )

    if not match:
        return None

    start_token, end_token = match.groups()

    start_dt = parse_time_token(start_token, plan_date)
    end_dt   = parse_time_token(end_token, plan_date)

    # Safety: end must be after start
    if end_dt <= start_dt:
        raise ValueError("End time must be after start time")

    return start_dt, end_dt
