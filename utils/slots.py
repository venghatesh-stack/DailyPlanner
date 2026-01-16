from datetime import datetime, timedelta
from config import IST
def slot_label(slot):
    start = datetime.min + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return f"{start:%I:%M %p} – {end:%I:%M %p}"

def current_slot():
    now = datetime.now(IST)
    return (now.hour * 60 + now.minute) // 30 + 1