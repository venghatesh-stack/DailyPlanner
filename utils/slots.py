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
def slots_to_timerange(slot_objs):
    start = min(s["time"].split(" - ")[0] for s in slot_objs)
    end = max(s["time"].split(" - ")[1] for s in slot_objs)
    return f"{start}–{end}"

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

        slot = (current.hour * 60 + current.minute) // 30 + 1

        slots.append({
            "slot": slot,  # ✅ SOURCE OF TRUTH
            "start": current,
            "end": slot_end,
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



