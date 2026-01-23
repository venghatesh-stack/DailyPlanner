import re
from datetime import datetime, timedelta

from utils.dates import safe_date
from utils.time_parser import parse_time_token 
from config import (
    WEEKDAY_MAP,
    QUADRANT_MAP,
    TASK_CATEGORIES,
    DEFAULT_PRIORITY,
    DEFAULT_CATEGORY,
    PRIORITY_RANK,
)


META_SLOT = "__meta__"
   
def extract_tags(text):
    return list(set(tag.lower() for tag in re.findall(r"#(\w+)", text)))


def extract_date(raw_text, default_date):
    """
    Resolves task date from natural language.

    Supported patterns (priority order):

    1. Explicit date (highest priority):
       - on 15Feb
       - on 15 Feb
       - on 15/02
       - on 15-02

    2. Relative date keywords:
       - tomorrow
       - next monday
       - next tuesday
       - next wednesday
       - next thursday
       - next friday
       - next saturday
       - next sunday

    3. Default behaviour:
       - If no date is specified, defaults to the planner UI date.

    Notes:
    - Explicit dates always override relative keywords.
    - Year defaults to the current planner year.
    - Invalid dates are safely clamped to month end
      (e.g., 31 Feb → 28/29 Feb).
    """
    text = raw_text.lower()

    # --------------------------------
    # 1️⃣ Explicit date: "on 15Feb", "on 15/02"
    # --------------------------------
    match = re.search(
        r"\bon\s+(\d{1,2})[\s\-\/]?([a-z]{3}|\d{1,2})",
        text,
        re.I,
    )

    if match:
        day = int(match.group(1))
        month_token = match.group(2)

        if month_token.isdigit():
            month = int(month_token)
        else:
          try:
              month = datetime.strptime(month_token[:3], "%b").month
          except ValueError:
              return default_date


        return safe_date(default_date.year, month, day)

    # --------------------------------
    # 2️⃣ Tomorrow
    # --------------------------------
    if re.search(r"\btomorrow\b", text):
        return default_date + timedelta(days=1)

    # --------------------------------
    # 3️⃣ Next weekday (e.g. "next monday")
    # --------------------------------
    weekday_match = re.search(
        r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        text,
    )

    if weekday_match:

        target = WEEKDAY_MAP[weekday_match.group(1)]
        today = default_date.weekday()

        delta = (target - today) % 7
        delta = 7 if delta == 0 else delta  # force NEXT, not today

        return default_date + timedelta(days=delta)

    # --------------------------------
    # 4️⃣ Default → planner UI date
    # --------------------------------
    return default_date

def parse_planner_input(raw_text, plan_date):
    # --------------------------------
    # QUADRANT PARSING
    # --------------------------------
    raw_text =normalize_date_time_order(raw_text)
    raw_text = normalize_ordinal_dates(raw_text)
    task_date = extract_date(raw_text, plan_date)

    quadrant_match = re.search(r"\b(Q[1-4])\b", raw_text, re.I)
    quadrant = (
        QUADRANT_MAP[quadrant_match.group(1).upper()]
        if quadrant_match
        else None
    )

    # --------------------------------
    # TIME PARSING (existing logic)
    # --------------------------------
 # --------------------------------
# TIME PARSING (expanded)
# --------------------------------

    range_match = re.search(
        r"(?:@|from)\s*([0-9:\.apm\s]+)\s+to\s+([0-9:\.apm\s]+)",
        raw_text,
        re.I,
    )

    single_match = re.search(
        r"@\s*([0-9:\.apm\s]+)",
        raw_text,
        re.I,
    )



    if range_match:
        start_raw, end_raw = range_match.groups()
        start_dt = parse_time_token(start_raw, task_date)
        end_dt = parse_time_token(end_raw, task_date)

    elif single_match:
        start_raw = single_match.group(1)
        start_dt = parse_time_token(start_raw, task_date)
        end_dt = start_dt + timedelta(minutes=30)

    else:
        raise ValueError("Time missing")

    if end_dt <= start_dt:
        raise ValueError("End time must be after start time")

    # --------------------------------
    # METADATA
    # --------------------------------
    priority_match = re.search(r"\$(critical|high|medium|low)", raw_text, re.I)
    category_match = re.search(
    r"%(" + "|".join(TASK_CATEGORIES.keys()) + r")",
    raw_text,
    re.I
    )


    priority = (
        priority_match.group(1).capitalize()
        if priority_match
        else DEFAULT_PRIORITY
    )

    category = (
        category_match.group(1).capitalize()
        if category_match
        else DEFAULT_CATEGORY
    )

    title = re.sub(r"\s(@|\$|%|#|Q[1-4]).*", "", raw_text).strip()
    tags = extract_tags(raw_text)

    return {
        "title": title,
        "start": start_dt,
        "end": end_dt,
        "date" : task_date,
        "priority": priority,
        "priority_rank": PRIORITY_RANK[priority],
        "category": category,
        "tags": tags,
        "quadrant": quadrant,  # ⭐ NEW
    }


def generate_half_hour_slots(parsed):
    slots = []
    current = parsed["start"]

    while current < parsed["end"]:
        slot_end = min(current + timedelta(minutes=30), parsed["end"])

        slots.append({
            "task": parsed["title"],
            "time": f"{current.strftime('%H:%M')} - {slot_end.strftime('%H:%M')}",
            "priority": parsed["priority"],
            "priority_rank": parsed["priority_rank"],
            "category": parsed["category"],
            "tags": parsed["tags"],
            "status": "open",
        })

        current = slot_end

    return slots



ORDINAL_RE = re.compile(r'(\d+)(st|nd|rd|th)', re.I)

def normalize_ordinal_dates(text: str) -> str:
    """
    Converts 'Jan31st' -> 'Jan 31'
    Converts '31st Jan' -> '31 Jan'
    """
    return ORDINAL_RE.sub(r'\1', text)



ON_DATE_FROM_TIME_RE = re.compile(
    r"(on\s+[^,]+?)\s+(from\s+\d{1,2}(:\d{2})?\s*(am|pm)\s+to\s+\d{1,2}(:\d{2})?\s*(am|pm))",
    re.I,
)

def normalize_date_time_order(text: str) -> str:
    """
    Converts:
      'meet Renga on Feb 28 from 7 am to 8 am'
    into:
      'meet Renga from 7 am to 8 am on Feb 28'
    """
    return ON_DATE_FROM_TIME_RE.sub(r"\2 \1", text)
