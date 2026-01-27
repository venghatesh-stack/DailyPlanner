import re
from datetime import datetime, timedelta, date
from config import SLOT_MINUTES,WEEKDAYS,IST
HOUR_RANGE_RE = re.compile(
    r"\b(?P<start>\d{1,2})(?:[:\.](?P<sm>\d{2}))?\s*-\s*(?P<end>\d{1,2})(?:[:\.](?P<em>\d{2}))?\b"
)
def parse_24h_range(text: str):
    """
    Parses:
      7-9
      9.30-10.30
      14-15
    Returns (start_minutes, end_minutes, cleaned_text)
    """
    m = HOUR_RANGE_RE.search(text)
    if not m:
        return None

    sh = int(m.group("start"))
    sm = int(m.group("sm") or 0)
    eh = int(m.group("end"))
    em = int(m.group("em") or 0)

    # validation
    if not (0 <= sh <= 23 and 0 <= eh <= 23):
        raise ValueError("Hour must be between 0 and 23")

    start_minutes = sh * 60 + sm
    end_minutes = eh * 60 + em

    if end_minutes <= start_minutes:
        raise ValueError("End time must be after start time")

    cleaned = HOUR_RANGE_RE.sub("", text).strip()

    return start_minutes, end_minutes, cleaned


def parse_time(t: str) -> int:
    """
    Converts '9 am', '10:30 pm' → minutes since midnight
    """
    t = t.strip().lower()
    dt = datetime.strptime(t, "%I %p") if ":" not in t else datetime.strptime(t, "%I:%M %p")
    return dt.hour * 60 + dt.minute


def resolve_date(date_phrase: str, base_date: date | None = None) -> date:
    """
    Resolves today / tomorrow / this Tuesday / next Tuesday
    """
    base_date = base_date or datetime.now(IST).date()
    phrase = date_phrase.lower().strip()

    if phrase == "today":
        return base_date

    if phrase == "tomorrow":
        return base_date + timedelta(days=1)

    m = re.match(r"(this|next)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", phrase)
    if m:
        which, day = m.groups()
        target = WEEKDAYS[day]
        delta = (target - base_date.weekday()) % 7
        if which == "next" or delta == 0:
            delta += 7
        return base_date + timedelta(days=delta)

    raise ValueError(f"Unsupported date phrase: {date_phrase}")


def parse_smart_sentence(text: str, base_date: date | None = None) -> dict:
    """
    Main parser: converts natural sentence → planner structure
    """
        base_date = base_date or datetime.now(IST).date()

    # 1️⃣ Try 24h numeric range FIRST (7-9, 9.30-10.30)
    parsed = parse_24h_range(text)
    if parsed:
        start_minutes, end_minutes, title = parsed

        start_slot = start_minutes // SLOT_MINUTES + 1
        slot_count = (end_minutes - start_minutes) // SLOT_MINUTES

        return {
            "plan_date": base_date,
            "start_slot": start_slot,
            "slot_count": slot_count,
            "text": title,
        }
