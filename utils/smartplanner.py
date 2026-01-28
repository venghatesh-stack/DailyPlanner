import re
from datetime import datetime, timedelta, date
from config import SLOT_MINUTES,WEEKDAYS,IST
HOUR_RANGE_RE = re.compile(
    r"\b(?P<start>\d{1,2})(?:[:\.](?P<sm>\d{2}))?\s*-\s*(?P<end>\d{1,2})(?:[:\.](?P<em>\d{2}))?\b"
)
def parse_24h_range(text: str, base_date: date | None = None) -> dict | None:
    m = re.match(
        r"""
        (?P<sh>\d{1,2})
        (?:[.:](?P<sm>\d{2}))?
        \s*-\s*
        (?P<eh>\d{1,2})
        (?:[.:](?P<em>\d{2}))?
        \s+(?P<title>.+)
        """,
        text.strip(),
        re.VERBOSE,
    )

    if not m:
        return None

    sh = int(m.group("sh"))
    sm = int(m.group("sm") or 0)
    eh = int(m.group("eh"))
    em = int(m.group("em") or 0)

    if sh > 23 or eh > 23 or sm > 59 or em > 59:
        raise ValueError("Invalid time")

    start_minutes = sh * 60 + sm
    end_minutes = eh * 60 + em

    if end_minutes <= start_minutes:
        raise ValueError("End time must be after start time")

    base_date = base_date or datetime.now(IST).date()

    return {
        "plan_date": base_date,
        "start_slot": start_minutes // SLOT_MINUTES + 1,
        "slot_count": (end_minutes - start_minutes) // SLOT_MINUTES,
        "text": m.group("title").strip(),
    }



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
    base_date = base_date or datetime.now(IST).date()
    text = text.strip()

    # 1️⃣ Numeric range first: "9-12 balaji meet"
    parsed = parse_24h_range(text, base_date)
    if parsed:
        return parsed

    # 2️⃣ Natural language range: "meet from 9am to 12pm"
    pattern = re.compile(
        r"""
        (?P<title>.+?)
        from\s+(?P<start>\d{1,2}(:\d{2})?\s?(am|pm))
        \s+to\s+(?P<end>\d{1,2}(:\d{2})?\s?(am|pm))
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    match = pattern.search(text)
    if match:
        title = match.group("title").strip()
        start_minutes = parse_time(match.group("start"))
        end_minutes = parse_time(match.group("end"))

        if end_minutes <= start_minutes:
            raise ValueError("End time must be after start time")

        return {
            "plan_date": base_date,
            "start_slot": start_minutes // SLOT_MINUTES + 1,
            "slot_count": (end_minutes - start_minutes) // SLOT_MINUTES,
            "text": title,
        }

    # 3️⃣ 🔥 Single-time numeric task: "9 meeting with balaji"
    m = re.match(r"^(?P<h>\d{1,2})(?:[.:](?P<m>\d{2}))?\s+(?P<title>.+)", text)
    if m:
        h = int(m.group("h"))
        mnt = int(m.group("m") or 0)

        if h > 23 or mnt > 59:
            raise ValueError("Invalid time")

        start_minutes = h * 60 + mnt

        return {
            "plan_date": base_date,
            "start_slot": start_minutes // SLOT_MINUTES + 1,
            "slot_count": 1,
            "text": m.group("title").strip(),
        }

    # ❌ Nothing matched
    raise ValueError("Unsupported smart planner format")
