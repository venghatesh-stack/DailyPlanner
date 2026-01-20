from datetime import datetime, timedelta,date
from config import IST
def slot_label(slot: int) -> str:
    total_minutes = (slot - 1) * 30
    start_h, start_m = divmod(total_minutes, 60)
    end_minutes = total_minutes + 30
    end_h, end_m = divmod(end_minutes, 60)

    def fmt(h, m):
        h = h % 24
        suffix = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12:02d}:{m:02d} {suffix}"

    return f"{fmt(start_h, start_m)} – {fmt(end_h, end_m)}"

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
