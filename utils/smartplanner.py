import re
from datetime import datetime, timedelta, date
from config import SLOT_MINUTES,WEEKDAYS,IST


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
    pattern = re.compile(
        r"""
        (?P<title>.+?)
        from\s+(?P<start>\d{1,2}(:\d{2})?\s?(am|pm))
        \s+to\s+(?P<end>\d{1,2}(:\d{2})?\s?(am|pm))
        \s+(?P<date>today|tomorrow|this\s+\w+|next\s+\w+)
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    match = pattern.search(text)
    if not match:
        raise ValueError("Could not parse sentence")

    title = match.group("title").strip()
    start_minutes = parse_time(match.group("start"))
    end_minutes = parse_time(match.group("end"))

    if end_minutes <= start_minutes:
        raise ValueError("End time must be after start time")

    plan_date = resolve_date(match.group("date"), base_date)

    start_slot = start_minutes // SLOT_MINUTES + 1
    slot_count = (end_minutes - start_minutes) // SLOT_MINUTES

    return {
        "plan_date": plan_date,
        "start_slot": start_slot,
        "slot_count": slot_count,
        "text": title,
    }
