# =======================
# app.py (REGENERATED)
# =======================

from flask import Flask, request, redirect, url_for, render_template_string
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar
import urllib.parse
import json

from supabase_client import get, post, delete
from logger import setup_logger

# ==========================================================
# APP SETUP
# ==========================================================
IST = ZoneInfo("Asia/Kolkata")
app = Flask(__name__)
logger = setup_logger()

# ==========================================================
# CONSTANTS
# ==========================================================
TOTAL_SLOTS = 48
META_SLOT = 0
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
    "Walking": "🚶",
    "Water": "💧",
    "No Shopping": "🛑🛍️",
    "No TimeWastage": "⏳",
    "8 hrs sleep": "😴",
    "Daily prayers": "🙏"
}

# ==========================================================
# HELPERS
# ==========================================================
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

# ==========================================================
# DATA ACCESS – DAILY PLANNER (UNCHANGED)
# ==========================================================
def load_day(plan_date):
    plans = {i: {"plan": "", "status": DEFAULT_STATUS} for i in range(1, TOTAL_SLOTS + 1)}
    habits = set()
    reflection = ""

    rows = get(
        "daily_slots",
        params={"plan_date": f"eq.{plan_date}", "select": "slot,plan,status"}
    ) or []

    for r in rows:
        if r["slot"] == META_SLOT:
            try:
                meta = json.loads(r.get("plan") or "{}")
                habits = set(meta.get("habits", []))
                reflection = meta.get("reflection", "")
            except Exception:
                pass
        else:
            plans[r["slot"]] = {
                "plan": r.get("plan") or "",
                "status": r.get("status") or DEFAULT_STATUS
            }

    return plans, habits, reflection

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

    payload.append({
        "plan_date": str(plan_date),
        "slot": META_SLOT,
        "plan": json.dumps({
            "habits": form.getlist("habits"),
            "reflection": form.get("reflection", "").strip()
        }),
        "status": DEFAULT_STATUS
    })

    post("daily_slots?on_conflict=plan_date,slot", payload, prefer="resolution=merge-duplicates")

# ==========================================================
# DATA ACCESS – EISENHOWER (FIXED)
# ==========================================================
def load_todo(plan_date):
    rows = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{plan_date}",
            "select": "quadrant,task_text,is_done,position",
            "order": "position.asc"
        }
    ) or []

    data = {"do": [], "schedule": [], "delegate": [], "eliminate": []}
    for r in rows:
        data[r["quadrant"]].append({
            "text": r["task_text"],
            "done": bool(r.get("is_done"))
        })
    return data

def save_todo(plan_date, form):
    logger.info(f"Saving Eisenhower for {plan_date}")

    delete("todo_matrix", params={"plan_date": f"eq.{plan_date}"})

    payload = []
    for quadrant in ["do", "schedule", "delegate", "eliminate"]:
        texts = form.getlist(f"{quadrant}[]")
        checked = set(int(i) for i in form.getlist(f"{quadrant}_done[]"))

        for idx, text in enumerate(texts):
            text = text.strip()
            if not text:
                continue

            payload.append({
                "plan_date": str(plan_date),
                "quadrant": quadrant,
                "task_text": text,
                "is_done": idx in checked,
                "position": idx
            })

    if payload:
        post("todo_matrix", payload)

# ==========================================================
# ROUTES – DAILY PLANNER
# ==========================================================
@app.route("/", methods=["GET", "POST"])
def planner():
    today = datetime.now(IST).date()

    if request.method == "POST":
        year = int(request.form["year"])
        month = int(request.form["month"])
        day = int(request.form["day"])
    else:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        day = int(request.args.get("day", today.day))

    plan_date = date(year, month, day)

    if request.method == "POST":
        save_day(plan_date, request.form)
        return redirect(url_for("planner", year=year, month=month, day=day, saved=1))

    plans, habits, reflection = load_day(plan_date)

    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]

    reminder_links = {
        slot: google_calendar_link(plan_date, slot, plans[slot]["plan"])
        for slot in range(1, TOTAL_SLOTS + 1)
    }

    return render_template_string(
        PLANNER_TEMPLATE,
        year=year,
        month=month,
        days=days,
        selected_day=day,
        today=today,
        plans=plans,
        statuses=STATUSES,
        slot_labels={i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)},
        reminder_links=reminder_links,
        now_slot=current_slot() if plan_date == today else None,
        habits=habits,
        reflection=reflection,
        habit_list=HABIT_LIST,
        habit_icons=HABIT_ICONS,
        calendar=calendar
    )

# ==========================================================
# ROUTES – EISENHOWER
# ==========================================================
@app.route("/todo", methods=["GET", "POST"])
def todo():
    today = datetime.now(IST).date()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    day = int(request.args.get("day", today.day))
    plan_date = date(year, month, day)

    if request.method == "POST":
        save_todo(plan_date, request.form)
        return redirect(url_for("todo", year=year, month=month, day=day))

    return render_template_string(
        TODO_TEMPLATE,
        todo=load_todo(plan_date),
        plan_date=plan_date
    )

# ==========================================================
# ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    app.run(debug=True)
