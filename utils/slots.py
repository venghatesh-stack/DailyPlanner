from datetime import datetime, timedelta
from config import IST
def slot_label(slot):
    start = datetime.min + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return f"{start:%I:%M %p} – {end:%I:%M %p}"

def current_slot():
    now = datetime.now(IST)
    return (now.hour * 60 + now.minute) // 30 + 1
def slots_to_timerange(slots):
    slots = sorted(slots)
    start_min = (slots[0] - 1) * 30
    end_min = slots[-1] * 30

    start = datetime.min + timedelta(minutes=start_min)
    end = datetime.min + timedelta(minutes=end_min)

    return f"{start.strftime('%I:%M %p').lstrip('0')}–{end.strftime('%I:%M %p').lstrip('0')}"
def slot_start_end(plan_date: date, slot: int):
    start = datetime.combine(plan_date, datetime.min.time(), tzinfo=IST) + timedelta(
        minutes=(slot - 1) * 30
    )
    end = start + timedelta(minutes=30)
    return start, end