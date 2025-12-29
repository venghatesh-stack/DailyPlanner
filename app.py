from flask import Flask, request, redirect, url_for, render_template_string
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar
import urllib.parse

from supabase_client import get, post
from logger import setup_logger

IST = ZoneInfo("Asia/Kolkata")

app = Flask(__name__)
logger = setup_logger()

# ===============================
# CONSTANTS
# ===============================
TOTAL_SLOTS = 48
DEFAULT_STATUS = "Nothing Planned"

STATUSES = [
    "Nothing Planned",
    "Yet to Start",
    "In Progress",
    "Closed",
    "Deferred"
]

HABIT_LIST = [
    "Walking",
    "Water",
    "No Shopping",
    "No TimeWastage",
    "8 hrs sleep",
    "Daily prayers"
]

HABIT_ICONS = {
    "Walking": "🚶‍♂️",
    "Water": "💧",
    "No Shopping": "🛒🚫",
    "No TimeWastage": "⏳🚫",
    "8 hrs sleep": "😴",
    "Daily prayers": "🙏"
}

# ===============================
# HELPERS
# ===============================
def slot_label(slot: int) -> str:
    start = datetime.min + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return f"{start.strftime('%I:%M %p')} – {end.strftime('%I:%M %p')}"

def slot_start_end(plan_date: date, slot: int):
    start = datetime.combine(plan_date, datetime.min.time(), tzinfo=IST) + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return start, end

def current_slot() -> int:
    now = datetime.now(IST)
    return (now.hour * 60 + now.minute) // 30 + 1

def google_calendar_link(plan_date, slot, task):
    if not task:
        return "#"

    start_ist, end_ist = slot_start_end(plan_date, slot)
    start_utc = start_ist.astimezone(ZoneInfo("UTC"))
    end_utc = end_ist.astimezone(ZoneInfo("UTC"))

    params = {
        "action": "TEMPLATE",
        "text": task,
        "dates": f"{start_utc.strftime('%Y%m%dT%H%M%SZ')}/{end_utc.strftime('%Y%m%dT%H%M%SZ')}",
        "details": "Created from Daily Planner",
        "trp": "false"
    }

    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)

# ===============================
# DATA ACCESS
# ===============================
def load_day(plan_date):
    plans = {i: {"plan": "", "status": DEFAULT_STATUS} for i in range(1, TOTAL_SLOTS + 1)}
    reflection = ""
    habits = set()

    rows = get("daily_slots", params={
        "plan_date": f"eq.{plan_date}",
        "select": "slot,plan,status"
    })

    for r in rows:
        plans[r["slot"]] = {
            "plan": r.get("plan") or "",
            "status": r.get("status") or DEFAULT_STATUS
        }

    summary = get("daily_summary", params={
        "plan_date": f"eq.{plan_date}",
        "select": "reflection,habits"
    })

    if summary:
        reflection = summary[0].get("reflection") or ""
        if summary[0].get("habits"):
            habits = set(h.strip() for h in summary[0]["habits"].split(",") if h.strip())

    return plans, reflection, habits

def save_day(plan_date, form):
    payload = []

    for slot in range(1, TOTAL_SLOTS + 1):
        plan = form.get(f"plan_{slot}", "").strip()
        status = form.get(f"status_{slot}", DEFAULT_STATUS)
        if plan:
            payload.append({
                "plan_date": str(plan_date),
                "slot": slot,
                "plan": plan,
                "status": status
            })

    if payload:
        post(
            "daily_slots?on_conflict=plan_date,slot",
            payload,
            prefer="resolution=merge-d
