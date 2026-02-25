## Eisenhower Matrix + Daily Planner integrated. Calender control working
print("STEP 1: app.py import started")
from re import search
from warnings import filters
from flask import Flask, request, redirect, url_for, render_template_string, session,jsonify,render_template,abort
import os
from datetime import date, datetime, timedelta
import calendar
import json
from google.auth.transport.requests import Request   
from werkzeug.wrappers import response
from supabase_client import get, post, update
from logger import setup_logger
from utils.dates import safe_date 
from config import TOTAL_SLOTS,QUADRANT_MAP
from utils.calender_links import google_calendar_link
from services.planner_service import generate_weekly_insight, load_day, save_day, get_daily_summary, get_weekly_summary,compute_health_streak,is_health_day,ensure_daily_habits_row,group_slots_into_blocks
from services.planner_service import fetch_daily_slots
from services.login_service import login_required
from services.eisenhower_service import autosave_task
from config import MIN_HEALTH_HABITS
from services.recurring_service import materialize_recurring_slots
from services.gantt_service import build_gantt_tasks
from services.eisenhower_service import (
    copy_open_tasks_from_previous_day,  
    enable_travel_mode,
)
from services.task_service import (
    complete_task_occurrence,
    skip_task_occurrence,
    update_task_occurrence,
    compute_next_occurrence
)
from collections import OrderedDict
from services.untimed_service import remove_untimed_task  
from services.timeline_service import load_timeline_tasks
from templates.planner import PLANNER_TEMPLATE
from templates.todo import TODO_TEMPLATE
from templates.summary import SUMMARY_TEMPLATE
from templates.login import LOGIN_TEMPLATE
from utils.smartplanner import parse_smart_sentence
from config import (
    IST,
    STATUSES,
    DEFAULT_STATUS, 
    HABIT_ICONS,
    HABIT_LIST,
    PRIORITY_MAP,
    SORT_PRESETS,
)
from utils.planner_parser import parse_planner_input
from utils.slots import current_slot,slot_label
import traceback
from services.ai_service  import call_gemini
from flask import jsonify
import requests
from flask import request, jsonify
from bs4 import BeautifulSoup
from utils.dates import safe_date_from_string
import bleach
from flask import session, redirect, url_for, request, jsonify
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
print("STEP 2: imports completed")

app = Flask(__name__)
print("STEP 3: flask created")
logger = setup_logger()
@app.errorhandler(Exception)
def catch_all_errors(e):
    print("🔥 GLOBAL EXCEPTION CAUGHT 🔥")
    traceback.print_exc()   # <-- ALWAYS prints
    logger.exception("UNHANDLED EXCEPTION")
    return "Internal Server Error", 500

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "changeme")
# ==========================================================
# Log in codestarts here
# ==========================================================
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # REMOVE in production

SCOPES = ['https://www.googleapis.com/auth/calendar.events']

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["authenticated"] = True
            session["user_id"] = "VenghateshS" 
            return redirect(url_for("planner"))
        return render_template_string(LOGIN_TEMPLATE, error="Invalid password")

    return render_template_string(LOGIN_TEMPLATE)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))






# ==========================================================
# ROUTES – DAILY PLANNER
# ==========================================================
@app.route("/", methods=["GET", "POST"])
@login_required
def planner():
    user_id = session["user_id"]
    daily_slots = []
    if request.method == "HEAD":
        return "", 200
    today = datetime.now(IST).date()
    # ----------------------------------------------------------
# Auto-redirect root load to today (only if no date provided)
# ----------------------------------------------------------
    if request.method == "GET" and not request.args.get("day"):
        today = datetime.now(IST).date()
        return redirect(
            url_for(
                "planner",
                year=today.year,
                month=today.month,
                day=today.day,
            )
        )

    if request.method == "POST":
        year = int(request.form["year"])
        month = int(request.form["month"])
        day = int(request.form["day"])
    else:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        day = int(request.args.get("day", today.day))

    plan_date = safe_date(year, month, day)
    formatted_date = plan_date.strftime("%d %B %Y").lstrip("0")


    if request.method == "POST":
        logger.info(f"Saving planner for date={plan_date}")
        save_day(plan_date, request.form)
        return redirect(
            url_for("planner", year=plan_date.year, month=plan_date.month, day=plan_date.day, saved=1)
        )
    materialize_recurring_slots(plan_date, user_id)
    ensure_daily_habits_row(user_id, plan_date)
  
    plans, habits, reflection,untimed_tasks= load_day(plan_date)
 
    daily_slots = fetch_daily_slots(plan_date)
    blocks = group_slots_into_blocks(plans)



    days = [
        date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)
    ]

    reminder_links = {
        slot: google_calendar_link(plan_date, slot, plans[slot]["plan"])
        for slot in range(1, TOTAL_SLOTS + 1)
    }
   
    health_streak = compute_health_streak(user_id, plan_date)

    streak_active_today = is_health_day(set(habits))
    selected_date = date(year, month, day)
    today = date.today()
    # ✅ ADD THIS HERE
    timeline_days = [
        selected_date + timedelta(days=i)
        for i in range(-6, 7)
    ]

    # ✅ Month navigation helpers
    prev_month = (selected_date.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (selected_date.replace(day=28) + timedelta(days=4)).replace(day=1)
   # tasks = build_tasks_for_ui(plan_date)
   

    return render_template_string(
        PLANNER_TEMPLATE,
        year=year,
        month=month,
        days=days,
        selected_day=plan_date.day,
        today=today,
        plans=plans,
        statuses=STATUSES,
        slot_labels={i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)},
        reminder_links=reminder_links,
        now_slot=current_slot() if plan_date == today else None,
        saved=request.args.get("saved"),
        habits=habits,
        reflection=reflection,
        habit_list=HABIT_LIST,
        habit_icons=HABIT_ICONS,
        calendar=calendar,
        untimed_tasks=untimed_tasks,
        plan_date=plan_date,
        health_streak=health_streak,
        streak_active_today=streak_active_today,
        min_health_habits=MIN_HEALTH_HABITS,
        blocks=blocks,
        today_display=formatted_date,
        prev_month=prev_month,
        next_month=next_month,
        timeline_days=timeline_days,
        selected_date=selected_date,
       # tasks=tasks,
        daily_slots=daily_slots
        
    )

def empty_quadrant():
    return {"tasks": []}



def build_eisenhower_view(tasks, plan_date):
    """
    Build Eisenhower matrix ONLY from todo_matrix tasks.
    No inference. No due-date logic. No urgency computation.
    """

    todo = {
        "do": empty_quadrant(),
        "schedule": empty_quadrant(),
        "delegate": empty_quadrant(),
        "eliminate": empty_quadrant(),
    }

    for t in tasks:
        quadrant = t.get("quadrant")
        if quadrant not in todo:
            continue  # safety guard

        task = {
            "id": t["id"],
            "task_text": t["task_text"],
            "is_done": t.get("is_done", False),
            "project_id": t.get("project_id"),
            "project_name": t.get("project_name"),
            "source_task_id": t.get("source_task_id"),
        }

        # Each quadrant has a single bucket
        todo[quadrant]["tasks"].append(task)

    return todo

def parse_date(d):
    if isinstance(d, str):
        return datetime.fromisoformat(d).date()
    return d

def compute_quadrant_counts(todo):
    counts = {}

    for q, data in todo.items():
        tasks = data["tasks"]
        total = len(tasks)
        done = sum(1 for t in tasks if t.get("is_done"))

        counts[q] = {
            "total": total,
            "done": done
        }

    return counts



def compute_urgency(due_date, due_time):
    # 🚫 Missing date or time → no urgency
    if not due_date or not due_time:
        return None

    # Normalize due_time (Supabase may return HH:MM or HH:MM:SS)
    if isinstance(due_time, str):
        parsed = None
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                parsed = datetime.strptime(due_time, fmt).time()
                break
            except ValueError:
                continue
        due_time = parsed

    if not due_time:
        return None

    now = datetime.now()
    due_dt = datetime.combine(due_date, due_time)

    if due_dt < now:
        return "overdue"    # 🔴
    elif due_dt <= now + timedelta(hours=2):
        return "soon"       # 🟠
    return None


def normalize_task(t, project_name=None):
    return {
        "task_id": t["task_id"],
        "text": t.get("task_text") or t.get("text"),
        "status": t.get("status"),
        "done": t.get("status") == "done",
        "due_date": parse_date(t.get("due_date")),
        "due_time": t.get("due_time"),
        "delegated_to": t.get("delegated_to"),
        "elimination_reason": t.get("elimination_reason"),
        "project_id": t.get("project_id"),
        "project_name": project_name,
        "recurring": bool(t.get("recurrence")),
        "recurrence": t.get("recurrence"),
    }
def expire_old_eisenhower_tasks(user_id):
    today = date.today().isoformat()

    rows = get(
        "todo_matrix",
        params={
            "user_id": f"eq.{user_id}",
            "is_done": "eq.false",
            "plan_date": f"lt.{today}",
            "select": "id, source_task_id"
        }
    )

    for r in rows:
        # 1️⃣ Remove / expire Eisenhower entry
        update(
            "todo_matrix",
            params={"id": f"eq.{r['id']}"},
            json={"is_deleted": True}
        )

        # 2️⃣ Restore project task status (if linked)
        if r.get("source_task_id"):
            update(
                "project_tasks",
                params={"task_id": f"eq.{r['source_task_id']}"},
                json={
                    "status": "open"
                }
            )
# ==========================================================
# ROUTES – EISENHOWER MATRIX
# ==========================================================
@app.route("/todo", methods=["GET"])
@login_required
def todo():
    expire_old_eisenhower_tasks(session["user_id"])

    # 📅 Selected day (default = today)
    year = int(request.args.get("year", date.today().year))
    month = int(request.args.get("month", date.today().month))
    day = int(request.args.get("day", date.today().day))

    plan_date = date(year, month, day)

    # 1️⃣ Fetch ONLY Eisenhower tasks for this date
    raw_tasks = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{plan_date.isoformat()}",
            "is_deleted": "eq.false"
        }
    )

    # 2️⃣ Fetch projects (for labels / linking only)
    projects = get("projects")
    project_map = {
        p["project_id"]: p["name"]
        for p in projects
    }

    # 3️⃣ Normalize Eisenhower tasks
    tasks = []
    for t in raw_tasks:
        tasks.append({
            "id": t["id"],
            "task_text": t["task_text"],
            "quadrant": t["quadrant"],          # already explicit
            "is_done": t.get("is_done", False),
            "project_id": t.get("project_id"),
            "project_name": project_map.get(t.get("project_id")),
            "source_task_id": t.get("source_task_id"),
        })

    # 4️⃣ Build Eisenhower view (NO due-date logic here)
    todo = build_eisenhower_view(tasks, plan_date)
    quadrant_counts = compute_quadrant_counts(todo)

    # 5️⃣ Render
    days = calendar.monthrange(year, month)[1]

    return render_template_string(
        TODO_TEMPLATE,
        todo=todo,
        plan_date=plan_date,
        year=year,
        month=month,
        days=days,
        calendar=calendar,
        toast=session.pop("toast", None),
        quadrant_counts=quadrant_counts,
    )


@app.route("/todo/toggle-done", methods=["POST"])
@login_required
def toggle_todo_done():
    data = request.get_json()

    task_id = data.get("id")
    is_done = bool(data.get("is_done"))

    if not task_id:
        return jsonify({"error": "Missing task id"}), 400

    status = "done" if is_done else "open"

    # 1️⃣ Update Eisenhower task
    update(
        "todo_matrix",
        params={"id": f"eq.{task_id}"},
        json={
            "is_done": is_done,
            "status": status,
        },
    )

    # 2️⃣ Optional: sync back to project task
    if is_done:
        rows = get(
            "todo_matrix",
            params={
                "id": f"eq.{task_id}",
                "select": "source_task_id",
            },
        )

        if rows and rows[0].get("source_task_id"):
            update(
                "project_tasks",
                params={"task_id": f"eq.{rows[0]['source_task_id']}"},
                json={"status": "done"},
            )

    return jsonify({"status": "ok"})


@app.route("/todo/copy-prev", methods=["POST"])
@login_required
def copy_prev_todo():
    today = datetime.now(IST).date()

    year = int(request.form.get("year", today.year))
    month = int(request.form.get("month", today.month))
    day = int(request.form.get("day", today.day))
    plan_date = date(year, month, day)

    copied = copy_open_tasks_from_previous_day(plan_date)
    logger.info(f"Copied {copied} Eisenhower tasks from previous day")

    return redirect(url_for("todo", year=plan_date.year, month=plan_date.month, day=plan_date.day, copied=1))


@app.route("/set_recurrence", methods=["POST"])
@login_required
def set_recurrence():
    data = request.get_json()
    task_id = data["task_id"]
    recurrence = data.get("recurrence")

    # Safety: block unsaved tasks
    if task_id.startswith("new_"):
        return ("", 204)

    # Load the task instance
    task = get("todo_matrix", params={"id": f"eq.{task_id}"})[0]

    # ----------------------------
    # FIX 3: prevent duplicate rules
    # ----------------------------
    existing = get(
        "recurring_tasks",
        params={
            "task_text": f"eq.{task['task_text']}",
            "quadrant": f"eq.{task['quadrant']}",
            "start_date": f"eq.{task['plan_date']}",
            "is_active": "eq.true",
        },
    )

    if existing:
        # Rule already exists → do nothing (idempotent)
        return ("", 204)

    # ----------------------------
    # Create recurring rule
    # ----------------------------
    rule=post(
        "recurring_tasks",
        {
            "quadrant": task["quadrant"],
            "task_text": task["task_text"],
            "recurrence": recurrence,
            "start_date": task["plan_date"],
            "is_active": True,
            "category": task.get("category") or "General",
            "subcategory": task.get("subcategory") or "General",
            "day_of_month": (
            date.fromisoformat(task["plan_date"]).day
            if recurrence == "monthly"
            else None
            ),
            "days_of_week": (
                [date.fromisoformat(task["plan_date"]).weekday()]
                if recurrence == "weekly"
                else None
            ),
         },
    )
    update(
    "todo_matrix",
    params={"id": f"eq.{task_id}"},
    json={"recurring_id": rule[0]["id"]},
    )

    return ("", 204)


@app.route("/delete_recurring", methods=["POST"])
@login_required
def delete_recurring():
    data = request.get_json()
    task_id = data["task_id"]

    # Load the task instance for TODAY
    task = get(
        "todo_matrix",
        params={"id": f"eq.{task_id}"},
    )[0]

    recurring_id = task.get("recurring_id")
    if not recurring_id:
        return ("", 204)

    # Stop recurrence from yesterday onwards
    end_date = date.fromisoformat(task["plan_date"]) - timedelta(days=1)

    update(
        "recurring_tasks",
        params={"id": f"eq.{recurring_id}"},
        json={"end_date": str(end_date)},
    )

    # Also remove TODAY's instance
    update("todo_matrix", params={"id": f"eq.{task_id}"}, json={"is_deleted": True})

    return ("", 204)


### Travel mode Code Changes ###


@app.route("/todo/travel-mode", methods=["POST"])
@login_required
def travel_mode():
    year = int(request.form["year"])
    month = int(request.form["month"])
    day = int(request.form["day"])
    plan_date = date(year, month, day)

    added = enable_travel_mode(plan_date)
    logger.info(f"Travel Mode enabled: {added} tasks added")

    return redirect(url_for("todo", year=plan_date.year, month=plan_date.month, day=plan_date.day, travel=1))





@app.route("/summary")
@login_required
def summary():
    view = request.args.get("view", "daily")

    # -------------------------
    # DAILY DATE PARAM
    # -------------------------
    date_str = request.args.get("date")
    if date_str:
        plan_date = date.fromisoformat(date_str)
    else:
        plan_date = datetime.now(IST).date()

    # =========================
    # WEEKLY VIEW
    # =========================
    if view == "weekly":

        week_str = request.args.get("week")  # format: 2026-W07

        if week_str:
            try:
                year, week = week_str.split("-W")
                start = date.fromisocalendar(int(year), int(week), 1)
            except ValueError:
                start = plan_date - timedelta(days=plan_date.weekday())
        else:
            # fallback — current week
            start = plan_date - timedelta(days=plan_date.weekday())

        end = start + timedelta(days=6)

        data = get_weekly_summary(start, end)
        insights = generate_weekly_insight(data)

        return render_template_string(
            SUMMARY_TEMPLATE,
            view="weekly",
            data=data,
            start=start,
            end=end,  # ✅ FIXED (was plan_date)
            insights=insights,
            selected_week=start.strftime("%G-W%V"),  # for picker value
        )

    # =========================
    # DAILY VIEW
    # =========================
    data = get_daily_summary(plan_date)

    return render_template_string(
        SUMMARY_TEMPLATE,
        view="daily",
        data=data,
        date=plan_date,
    )

@app.route("/untimed/promote", methods=["POST"])
@login_required
def promoteuntimed():
    data = request.get_json()

    user_id = "VenghateshS"
    plan_date = date.fromisoformat(data["plan_date"])
    plan_date_str = plan_date.isoformat()
    task_id = data["id"]

    # -------------------------------------------------
    # Load untimed tasks from daily_meta
    # -------------------------------------------------
    rows = get(
        "daily_meta",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date_str}",
            "select": "untimed_tasks",
        },
    )

    if not rows:
        return ("Untimed task not found", 404)

    untimed = rows[0].get("untimed_tasks") or []

    task = next(
        (t for t in untimed if isinstance(t, dict) and t.get("id") == task_id),
        None
    )
    if not task:
        return ("Untimed task not found", 404)

    text = task["text"]

    # -------------------------------------------------
    # Quadrant validation
    # -------------------------------------------------
    raw_q = data["quadrant"].upper()
    if raw_q not in QUADRANT_MAP:
        return ("Invalid quadrant", 400)

    quadrant = QUADRANT_MAP[raw_q]

    # -------------------------------------------------
    # Compute next position
    # -------------------------------------------------
    max_pos = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{plan_date_str}",
            "quadrant": f"eq.{quadrant}",
            "is_deleted": "eq.false",
            "select": "position",
            "order": "position.desc",
            "limit": 1,
        },
    )

    existing = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{plan_date_str}",
            "quadrant": f"eq.{quadrant}",
            "task_text": f"eq.{text}",
            "is_deleted": "eq.false",
        },
    )

    if existing:
        return ("Task already exists in the selected quadrant", 400)

    next_pos = max_pos[0]["position"] + 1 if max_pos else 0

    # -------------------------------------------------
    # Insert into Eisenhower matrix
    # -------------------------------------------------
    post(
        "todo_matrix",
        {
            "plan_date": plan_date_str,
            "quadrant": quadrant,
            "task_text": text,
            "is_done": False,
            "is_deleted": False,
            "position": next_pos,
            "category": "General",
            "subcategory": "General",
        },
    )

    # -------------------------------------------------
    # Remove from untimed list
    # -------------------------------------------------
    remove_untimed_task(user_id, plan_date, task_id)

    return ("", 204)
def get_plans_for_date(plan_date):
    return [
        p for p in session.get("plans", [])
        if p["plan_date"] == plan_date
    ]

def get_plan_for_slot(plan_date, slot):
    plans = get_plans_for_date(plan_date)  # DB / cache / session

    for plan in plans:
        if plan["start_slot"] <= slot < plan["start_slot"] + plan["slot_count"]:
            return plan["text"]

    return None

@app.route("/smart/add", methods=["POST"])
@login_required
def smart_add():
    data = request.get_json(force=True)

    text = data["text"]
    plan_date = date.fromisoformat(data["plan_date"])

    # 🔥 ALWAYS delegate to save_day
    # This ensures:
    # - smart parsing
    # - generate_half_hour_slots
    # - start_time / end_time persistence
    # - recurrence handling
    save_day(plan_date, {"smart_plan": text})

    return jsonify({"status": "ok"})

@app.route("/slot/toggle-status", methods=["POST"])
@login_required
def toggle_slot_status():
    data = request.get_json()

    update(
        "daily_slots",
        params={
            "plan_date": f"eq.{data['plan_date']}",
            "slot": f"eq.{data['slot']}",
        },
        json={"status": data["status"]},
    )

    return ("", 204)

@app.route("/smart/preview", methods=["POST"])
def smart_preview():
    data = request.get_json(force=True)

    text = data.get("text", "").strip()
    plan_date = data.get("plan_date")

    if not text or not plan_date:
        return jsonify({"conflicts": []})

    # Try parsing smart sentence
    try:
        parsed = parse_smart_sentence(text, date.fromisoformat(plan_date))
    except Exception:
        # If parsing fails → no conflicts, allow save
        return jsonify({"conflicts": []})

    start_slot = parsed["start_slot"]
    slot_count = parsed["slot_count"]

    # Fetch existing plans for those slots
    conflicts = []
    for i in range(slot_count):
        slot = start_slot + i
        existing = get_plan_for_slot(plan_date, slot)  # ← YOUR EXISTING helper
        if existing and existing.strip():
            conflicts.append({
                "time": f"Slot {slot}",
                "existing": existing,
                "incoming": parsed["text"]
            })

    return jsonify({"conflicts": conflicts})

@app.route("/untimed/schedule", methods=["POST"])
@login_required
def schedule_untimed():
    data = request.get_json()

    user_id = "VenghateshS"
    plan_date = date.fromisoformat(data["plan_date"])
    plan_date_str = plan_date.isoformat()

    if plan_date < datetime.now(IST).date():
        return ("Cannot schedule in the past", 400)

    task_id = data["id"]
    start_slot = int(data["start_slot"])
    slot_count = int(data["slot_count"])

    # -------------------------------------------------
    # Resolve untimed task from daily_meta (SOURCE OF TRUTH)
    # -------------------------------------------------
    rows = get(
        "daily_meta",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date_str}",
            "select": "untimed_tasks",
        },
    )

    if not rows:
        return ("Untimed task not found", 404)

    untimed = rows[0].get("untimed_tasks") or []

    task = next(
        (t for t in untimed if isinstance(t, dict) and t.get("id") == task_id),
        None
    )
    if not task:
        return ("Untimed task not found", 404)

    # Prefer confirmed text from client, fallback to stored text
    text = data.get("final_text") or task["text"]

    # -------------------------------------------------
    # Build slot payload
    # -------------------------------------------------
    payload = []
    for i in range(slot_count):
        slot = start_slot + i
        if 1 <= slot <= TOTAL_SLOTS:
            payload.append({
                "plan_date": plan_date_str,
                "slot": slot,
                "plan": text,
                "status": DEFAULT_STATUS,
            })

    if not payload:
        return ("Invalid slot range", 400)

    # -------------------------------------------------
    # Insert / update daily slots
    # -------------------------------------------------
    post(
        "daily_slots?on_conflict=plan_date,slot",
        payload,
        prefer="resolution=merge-duplicates",
    )

    # -------------------------------------------------
    # Remove from untimed list
    # -------------------------------------------------
    remove_untimed_task(user_id, plan_date, task_id)

    return ("", 204)

@app.route("/untimed/slot-preview", methods=["POST"])
@login_required
def untimed_slot_preview():
    data = request.get_json()

    plan_date = date.fromisoformat(data["plan_date"])
    start_slot = int(data["start_slot"])
    slot_count = int(data["slot_count"])

    preview = []

    for i in range(slot_count):
        slot = start_slot + i
        if not (1 <= slot <= TOTAL_SLOTS):
            continue

        row = get(
            "daily_slots",
            params={
                "plan_date":f"eq.{plan_date.isoformat()}",
                "slot": f"eq.{slot}",
                "select": "slot,plan",
            },
        )

        preview.append({
            "slot": slot,
            "existing": row[0]["plan"] if row and row[0].get("plan") else ""
        })

    return preview, 200
@app.route("/todo/autosave", methods=["POST"])
@login_required
def todo_autosave():
    data = request.get_json(force=True)
    logger.info("AUTOSAVE DATA: %s", data)

    # 🛑 HARD GUARD — ignore anything not from Eisenhower
    if "id" not in data or "plan_date" not in data or "quadrant" not in data:
        return jsonify({"ignored": True})

    task_id = data["id"]

    # 🔹 FULL EISENHOWER AUTOSAVE
    result = autosave_task(
        plan_date=data["plan_date"],
        task_id=task_id,
        quadrant=data["quadrant"],
        text=data.get("task_text"),
        is_done=data.get("is_done", False),
    )

    # 🔒 Preserve project_id if present
    if "project_id" in data:
        update(
            "todo_matrix",
            params={"id": f"eq.{task_id}"},
            json={"project_id": data["project_id"]},
        )

    # 🔁 Sync completion back to project task (if linked)
    if "is_done" in data:
        row = get(
            "todo_matrix",
            params={"id": f"eq.{task_id}"},
            single=True
        )

        if row and row.get("source_task_id"):
            update(
                "project_tasks",
                params={"task_id": f"eq.{row['source_task_id']}"},
                json={
                    "status": "done" if data["is_done"] else "open"
                }
            )

    return jsonify(result)




@app.route("/favicon.ico")
def favicon():
    return "", 204

@app.route("/slot/get")
@login_required
def get_slot():
    plan_date = request.args["date"]
    slot = int(request.args["slot"])

    row = get(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date}",
            "slot": f"eq.{slot}",
            "select": "plan",
        },
    )
    return jsonify({"text": row[0]["plan"] if row else ""})

@app.route("/projects/tasks/send-to-eisenhower11", methods=["POST"])
@login_required
def send_project_task_to_eisenhower11():
    data = request.get_json() or {}

    task_id = data.get("task_id")
    plan_date = data.get("plan_date")
    quadrant = data.get("quadrant", "do")

    if not task_id or not plan_date:
        return jsonify({"error": "Missing data"}), 400

    # 1️⃣ Fetch project task
    rows = get(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"}
    )

    if not rows:
        return jsonify({"error": "Task not found"}), 404

    task = rows[0]
    existing = get(
    "todo_matrix",
    params={
        "source_task_id": f"eq.{task_id}",
        "plan_date": f"eq.{plan_date}"
    }
)

    if existing:
        return jsonify({"status": "already-sent"})
    # 2️⃣ CREATE todo_matrix row (via post)
    post(
        "todo_matrix",
        {
            "text": task["task_text"],
            "plan_date": plan_date,
            "quadrant": quadrant,
            "project_id": task["project_id"],
            "source_task_id": task_id,   # 🔑 back-reference
            "is_done": False
        }
    )

    return jsonify({"status": "ok"})


@app.route("/slot/update", methods=["POST"])
@login_required
def update_slot():
    data = request.get_json()
    plan_date = data["plan_date"]
    start = int(data["start_slot"])
    end = int(data["end_slot"])
    text = data["text"]

    for slot in range(start, end + 1):
        update(
            "daily_slots",
            params={
                "plan_date": f"eq.{plan_date}",
                "slot": f"eq.{slot}",
            },
            json={"plan": text},
        )

    return ("", 204)
@app.route("/subtask/add", methods=["POST"])
@login_required
def add_subtask():
    data = request.get_json()

    post(
        "project_subtasks",
        {
            "project_id": data["project_id"],
            "parent_task_id": data["task_id"],
            "title": data["title"],
        },
    )
    return ("", 204)

@app.route("/subtask/toggle", methods=["POST"])
@login_required
def toggle_subtask():
    data = request.get_json(force=True)

    update(
        "project_subtasks",
        params={"id": f"eq.{data['id']}"},
        json={"is_done": bool(data.get("is_done"))},
    )
    
    return ("", 204)
@app.route("/projects")
@login_required
def projects():
    user_id = session["user_id"]

    projects = get(
        "projects",
        params={
            "user_id": f"eq.{user_id}",
            "is_archived": "eq.false",
            "order": "created_at.asc",
        },
    )

    return render_template(
        "projects.html",
        projects=projects,
    )

@app.route("/todo/set-project", methods=["POST"])
@login_required
def todo_set_project():
    data = request.get_json(force=True)

    task_id = data.get("id")
    project_id = data.get("project_id")

    if not task_id:
        return jsonify({"error": "Missing task id"}), 400

    update(
        "todo_matrix",
        params={"id": f"eq.{task_id}"},
        json={"project_id": project_id},
    )

    return jsonify({"status": "ok"})
@app.route("/projects/<project_id>/set-sort", methods=["POST"])
@login_required
def set_project_sort(project_id):
    data = request.get_json() or {}
    sort = data.get("sort")

    if not sort:
        return jsonify({"error": "Missing sort"}), 400

    update(
        "projects",
        params={"project_id": f"eq.{project_id}"},
        json={"default_sort": sort}
    )

    return jsonify({"status": "ok"})

@app.route("/projects/<project_id>/tasks")
@login_required
def project_tasks(project_id):
    user_id = session["user_id"]

    # ---------------------------------
    # Load project
    # ---------------------------------
    rows = get(
        "projects",
        params={"project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}"},
    )
    if not rows:
        return "Project not found", 404

    project = rows[0]

    # ---------------------------------
    # Read filters from URL
    # ---------------------------------
    hide_completed = request.args.get("hide_completed", "0") == "1"
    overdue_only   = request.args.get("overdue_only", "0") == "1"

    sort = request.args.get("sort") or project.get("default_sort", "smart")
    order = SORT_PRESETS.get(sort, SORT_PRESETS["smart"])

    # ---------------------------------
    # Fetch tasks (no filtering in SQL)
    # ---------------------------------
    raw_tasks = get(
        "project_tasks",
        params={
            "project_id": f"eq.{project_id}",
            "is_eliminated": "eq.false",   # ✅ ADD THIS
            "order": order,
        },
    ) or []

    today = date.today()

    tasks = []
    for t in raw_tasks:
        status = t.get("status")
        due    = t.get("due_date")

        # ❌ Hide completed
        if hide_completed and status == "done":
            continue

        # ❌ Overdue only
        if overdue_only:
            if not due:
                continue
            due_date = date.fromisoformat(due)
            if due_date >= today or status == "done":
                continue

        tasks.append({
            "task_id": t["task_id"],
            "task_text": t["task_text"],
            "status": status,
            "done": status == "done",
            "start_date": t.get("start_date"),
            "duration_days": t.get("duration_days"),
            "due_date": due,
            "due_time": t.get("due_time"),
            "delegated_to": t.get("delegated_to"),
            "elimination_reason": t.get("elimination_reason"),
            "project_name": project["name"],
            "urgency": None,
            "priority_rank": PRIORITY_MAP.get(t.get("priority"), 2),
            "is_pinned": t.get("is_pinned", False),
             "planned_hours": t.get("planned_hours", 0),
             "actual_hours": t.get("actual_hours", 0),
               # 🔥 ADD THESE
            "is_recurring": t.get("is_recurring", False),
            "recurrence_type": t.get("recurrence_type", "none"),
            "recurrence_days": t.get("recurrence_days"),
            "recurrence_interval": t.get("recurrence_interval"),
            "recurrence_end": t.get("recurrence_end"),
            "auto_advance": t.get("auto_advance", True),
            "recurrence_badge": build_recurrence_badge(t),

        })

    grouped_tasks = group_tasks_smart(tasks)

    return render_template(
        "project_tasks.html",
        project=project,
        grouped_tasks=grouped_tasks,
        today=today.isoformat(),
        sort=sort,
        hide_completed=hide_completed,
        overdue_only=overdue_only,
    )



def compute_due_date(start_date, duration_days):
    return start_date + timedelta(days=duration_days)


def _sort_key(task):
    """
    Normalizes start_date / due_date for safe sorting.
    Handles:
    - datetime.date
    - ISO date strings
    - None
    """
    d = task.get("start_date") or task.get("due_date")

    if not d:
        return date.max

    if isinstance(d, str):
        return date.fromisoformat(d)

    return d
def get_max_order_index(project_id):
    rows = get(
        "project_tasks",
        params={
            "project_id": f"eq.{project_id}",
            "select": "order_index",
            "order": "order_index.desc",
            "limit": 1
        }
    )
    return rows[0]["order_index"] if rows else None

def build_recurrence_badge(t):
    if not t.get("is_recurring"):
        return None

    rtype = t.get("recurrence_type")

    if rtype == "daily":
        return "🔁 Daily"

    if rtype == "weekly":
        return "🔁 Weekly"

    if rtype == "monthly":
        return "🔁 Monthly"

    return "🔁"

@app.route("/projects/<project_id>/tasks/add", methods=["POST"])
@login_required
def add_project_task(project_id):
    text = request.form["task_text"].strip()

    if not text:
        return redirect(url_for("project_tasks", project_id=project_id))

    max_order = get_max_order_index(project_id)
    order_index = max_order + 1   # ✅ append to end

    post(
        "project_tasks",
        {
            "project_id": project_id,
            "task_text": text,
            "status": "backlog",
            "order_index": order_index,   # ✅ THIS LINE
        },
    )

    return redirect(url_for("project_tasks", project_id=project_id))


@app.route("/projects/tasks/send-to-eisenhower", methods=["POST"])
@login_required
def send_project_task_to_eisenhower():
    data = request.get_json() or {}

    task_id = data.get("task_id")
    plan_date = data.get("plan_date")
    quadrant = (data.get("quadrant") or "do").lower()

    if not task_id or not plan_date:
        return jsonify({"error": "Missing task_id or plan_date"}), 400

    rows = get(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"}
    )

    if not rows:
        return jsonify({"error": "Task not found"}), 404

    task = rows[0]
    existing = get(
    "todo_matrix",
    params={
        "source_task_id": f"eq.{task_id}",
        "plan_date": f"eq.{plan_date}",
    }
)

    if existing:
     return jsonify({"status": "already-sent"})

    post(
        "todo_matrix",
        {
            "task_text": task["task_text"],   # ✅ FIXED
            "plan_date": plan_date,           # ✅ REQUIRED
            "quadrant": quadrant,              # ✅ CHECK constraint
            "project_id": task.get("project_id"),
            "user_id": session["user_id"],     # ✅ IMPORTANT
            "source_task_id": task_id,
            "is_done": False,
        }
    )

    return jsonify({"status": "ok"})




@app.route("/projects/tasks/status", methods=["POST"])
@login_required
def update_project_task_status():
    data = request.get_json(force=True)

    task_id   = data["task_id"]
    status    = data["status"]
    task_date = data.get("date")
    user_id   = session["user_id"]

    # Load base task (rule)
    rows = get(
        "project_tasks",
        params={
            "task_id": f"eq.{task_id}",
            "user_id": f"eq.{user_id}"
        }
    )

    if not rows:
        return jsonify({"error": "Task not found"}), 404

    task = rows[0]

    # ------------------------------------------------
    # CASE 1: recurring + per-day completion
    # ------------------------------------------------
    if task_date and task.get("is_recurring"):
        if status == "done":
            complete_task_occurrence(
                user_id=user_id,
                task_id=task_id,
                task_date=task_date
            )

            # 🔁 AUTO-ADVANCE (if enabled)
            if task.get("auto_advance", True):
                next_date = compute_next_occurrence(
                    task,
                    date.fromisoformat(task_date)
                )

                if next_date:
                    update(
                        "project_tasks",
                        params={"task_id": f"eq.{task_id}"},
                        json={
                            "start_date": next_date.isoformat(),
                            "due_date": next_date.isoformat(),  # ✅ FIX
                            "status": "open"
                        }
                    )

        return jsonify({"status": "ok"})

    # ------------------------------------------------
    # CASE 2: normal (non-recurring) task
    # ------------------------------------------------
    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"},
        json={"status": status}
    )

    return jsonify({"status": "ok"})

@app.route("/projects/tasks/unsend", methods=["POST"])
@login_required
def unsend_task_from_eisenhower():
    data = request.get_json() or {}

    task_id = data.get("task_id")
    scope = data.get("scope", "today_future")  # optional

    if not task_id:
        return jsonify({"error": "Missing task_id"}), 400

    today = date.today().isoformat()

    # ---------------------------------------------
    # Remove Eisenhower entries linked to this task
    # ---------------------------------------------
    params = {
        "source_task_id": f"eq.{task_id}",
        "is_deleted": "eq.false",
    }

    # Optional safety: only today & future
    if scope == "today_future":
        params["plan_date"] = f"gte.{today}"

    update(
        "todo_matrix",
        params=params,
        json={"is_deleted": True},
    )

    return jsonify({"status": "ok"})
def build_timeline_blocks(tasks, zoom="day"):
    blocks = {}

    for t in tasks:
        d = t.get("due_date") or t.get("start_date")
        if not d:
            continue

        if isinstance(d, str):
            d = date.fromisoformat(d)

        if zoom == "week":
            label = f"Week {d.isocalendar()[1]} — {d.strftime('%b %Y')}"
            key = f"{d.isocalendar()[0]}-{d.isocalendar()[1]}"
        else:
            label = d.strftime("%d %b %Y")
            key = d.isoformat()

        blocks.setdefault(key, {
            "label": label,
            "date": d.isoformat(),
            "tasks": []
        })["tasks"].append(t)

    return sorted(blocks.values(), key=lambda x: x["date"])

@app.route("/api/timeline/reschedule", methods=["POST"])
@login_required
def timeline_reschedule():
    data = request.get_json()

    task_id = data["task_id"]
    new_date = data["new_date"]

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"},
        json={"due_date": new_date}
    )

    return jsonify({"status": "ok"})

@app.route("/projects/timeline")
@login_required
def task_timeline():
    user_id = session["user_id"]

    zoom = request.args.get("zoom", "day")          # day | week
    project_id = request.args.get("project")        # optional filter

    tasks = load_timeline_tasks(user_id, project_id=project_id)

    timeline_blocks = build_timeline_blocks(tasks, zoom)

    projects = get(
        "projects",
        params={
            "user_id": f"eq.{user_id}",
            "is_archived": "eq.false"
        }
    )

    return render_template(
        "project_timeline.html",
        timeline_blocks=timeline_blocks,
        zoom=zoom,
        projects=projects,
    )
def load_slot_timeline(plan_date):
    return get(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date.isoformat()}",
            "select": "slot,plan,status",
            "order": "slot.asc"
        }
    ) or []


def build_slot_blocks(rows):
    slot_map = {r["slot"]: r for r in rows}
    blocks = []

    for slot in range(1, TOTAL_SLOTS + 1):
        r = slot_map.get(slot)

        blocks.append({
            "slot": slot,
            "label": slot_label(slot),
            "text": r["plan"] if r else "",
            "status": r["status"] if r else None
        })

    return blocks

@app.route("/timeline/day")
@login_required
def timeline_day():
    d = request.args.get("date")

    if d:
        plan_date = date.fromisoformat(d)
    else:
        plan_date = datetime.now(IST).date()

    rows = load_slot_timeline(plan_date)
    blocks = build_slot_blocks(rows)

    return render_template(
        "timeline_day.html",
        blocks=blocks,
        plan_date=plan_date
    )

@app.route("/projects/tasks/update-date", methods=["POST"])
@login_required
def update_project_task_date():
    data = request.get_json() or {}
    task_id = data.get("task_id")
    due_date = data.get("due_date")

    if not task_id:
        return jsonify({"error": "Missing task id"}), 400

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"},
        json={"due_date": due_date},
    )
    logger.info(f"👉 task_id={task_id}, new_date={due_date}")
    return jsonify({"status": "ok"})
@app.route("/projects/tasks/<task_id>/update", methods=["POST"])
def update_task(task_id):
    data = request.json or {}

    # Build update payload safely (PATCH semantics)
    updates = {}

    allowed_fields = [
        "task_text",
        "start_date",
        "due_date",
        "due_time",
        "notes",
        "status",
        "planned_hours",
        "actual_hours",
        "priority",
        "elimination_reason",
        "duration_days",
         # 🔥 ADD THESE
        "is_recurring",
        "recurrence_type",
        "recurrence_days",
        "recurrence_interval",
        "recurrence_end",
        "auto_advance",
    ]

    for field in allowed_fields:
        if field in data:
            updates[field] = data[field]

    # 🔒 Safety: never allow task_text to be null
    if "task_text" in updates and updates["task_text"] is None:
        return jsonify({
            "error": "task_text cannot be null"
        }), 400

    # 🛑 No-op protection
    if not updates:
        return jsonify({"status": "noop"})
    if "start_time" in updates and updates["start_time"] == "":
        updates["start_time"] = None

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"},
        json=updates
    )

    return jsonify({"status": "ok"})



@app.route("/projects/tasks/update-duration", methods=["POST"])
@login_required
def update_task_duration():
    data = request.get_json()

    task_id = data["task_id"]
    duration_days = int(data["duration_days"])

    # 1️⃣ Fetch start_date from DB (source of truth)
    rows = get(
        "project_tasks",
        params={
            "task_id": f"eq.{task_id}",
            "select": "start_date",
        },
    )

    if not rows or not rows[0].get("start_date"):
        return jsonify({"error": "Missing start date"}), 400

    start_date = date.fromisoformat(rows[0]["start_date"])

    # 2️⃣ ✅ Compute due date HERE
    due_date = compute_due_date(start_date, duration_days)

    # 3️⃣ Persist everything
    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"},
        json={
            "duration_days": duration_days,
            "due_date": due_date.isoformat(),
        },
    )

    return jsonify({
        "due_date": due_date.isoformat()
    })


@app.route("/projects/tasks/update-delegation", methods=["POST"])
@login_required
def update_delegation():
    data = request.get_json()

    update(
        "project_tasks",
        params={"task_id": f"eq.{data['id']}"},
        json={
            "delegated_to": data.get("delegated_to")
        }
    )

    return "", 204

@app.route("/projects/tasks/eliminate", methods=["POST"])
@login_required
def eliminate_task():
    data = request.get_json()

    task_id = data["id"]
    reason = data.get("reason")

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"},
        json={
            "is_eliminated": True,
            "elimination_reason": reason,
        }
    )

    return "", 204

@app.route("/projects/tasks/update-time", methods=["POST"])
@login_required
def update_due_time():
    data = request.get_json()

    update(
        "project_tasks",
        params={"task_id": f"eq.{data['id']}"},
        json={
            "due_time": data.get("due_time")
        }
    )

    return "", 204
@app.route("/projects/tasks/update-planning", methods=["POST"])
@login_required
def update_task_planning():
    data = request.get_json()

    task_id = data["task_id"]
    start   = date.fromisoformat(data["start_date"])
    days    = int(data.get("duration_days", 1))

    due_date = start + timedelta(days=days)

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"},
        json={
            "start_date": str(start),
            "duration_days": days,
            "due_date": str(due_date),
        }
    )

    return jsonify({
        "due_date": str(due_date)
    })
@app.route("/projects/<project_id>/gantt")
@login_required
def project_gantt(project_id):
    tasks = get(
        "project_tasks",
        params={"project_id": f"eq.{project_id}"}
    )

    gantt_tasks = build_gantt_tasks(tasks)

    return render_template(
        "project_gantt.html",
        project_id=project_id,
        gantt_tasks=json.dumps(gantt_tasks)
    )
@app.route("/projects/tasks/update-planned", methods=["POST"])
@login_required
def update_planned():
    data = request.get_json()
    update(
        "project_tasks",
        params={"task_id": f"eq.{data['task_id']}"},
        json={"planned_hours": data["planned_hours"]}
    )
    return "", 204


@app.route("/projects/tasks/update-actual", methods=["POST"])
@login_required
def update_actual():
    data = request.get_json()
    update(
        "project_tasks",
        params={"task_id": f"eq.{data['task_id']}"},
        json={"actual_hours": data["actual_hours"]}
    )
    return "", 204


def group_tasks_smart(tasks):
    today = date.today()
    tomorrow = today + timedelta(days=1)            

    # Week ends on Sunday
    end_of_week = today + timedelta(days=(6 - today.weekday()))

    # End of month
    next_month = today.replace(day=28) + timedelta(days=4)
    end_of_month = next_month.replace(day=1) - timedelta(days=1)

    groups = OrderedDict({
        "Today": [],
        "Tomorrow": [],
        "This Week": [],
        "This Month": [],
        "Later": []
    })

    for t in tasks:
        d = t.get("start_date") or t.get("due_date")

        if not d:
            groups["Later"].append(t)
            continue

        if isinstance(d, str):
            d = date.fromisoformat(d)

        if d == today:
            groups["Today"].append(t)
        elif d == tomorrow:
            groups["Tomorrow"].append(t)
        elif tomorrow < d <= end_of_week:
            groups["This Week"].append(t)
        elif d <= end_of_month:
            groups["This Month"].append(t)
        else:
            groups["Later"].append(t)

    # Optional: sort inside each group
    for key in groups:
        groups[key].sort(key=_sort_key)

    return groups
@app.route("/projects/tasks/update-priority", methods=["POST"])
@login_required
def update_priority():
    data = request.get_json()
    task_id = data["task_id"]
    priority = data["priority"]

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"},
        json={
            "priority": priority,
            "priority_rank": PRIORITY_MAP.get(priority, 2)
        }
    )

    return {"status": "ok"}


@app.route("/projects/new", methods=["GET", "POST"])
@login_required
def create_project():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            return "Project name is required", 400

        post(
            "projects",
            {
                "name": name,
                "description": description or None,
                "user_id": session.get("user_id")
            }
        )

        return redirect("/projects")

    return render_template("project_new.html")
def insert_many(table, rows, prefer="return=representation"):
    """
    Insert multiple rows into a Supabase table.
    rows: list[dict]
    """
    return post(table, rows, prefer=prefer)


@app.route("/projects/tasks/bulk-add", methods=["POST"])
def bulk_add_tasks():
    data = request.json or {}

    project_id = data.get("project_id")
    tasks = data.get("tasks", [])

    if not project_id:
        return jsonify({"error": "project_id missing"}), 400

    if not tasks:
        return jsonify({"error": "no tasks provided"}), 400

    today = date.today().isoformat()

    rows = []
    for idx,text in enumerate(tasks):
        if not text.strip():
            continue

        rows.append({
            "project_id": project_id,          # ✅ guaranteed non-empty
            "task_text": text.strip(),
            "start_date": today,
            "priority": "medium",
            "priority_rank": PRIORITY_MAP["medium"],
            "order_index": idx,          # ✅ THIS LINE
            "duration_days": 0,
            "status": "open",
            "user_id": session["user_id"]
        })

    if not rows:
        return jsonify({"error": "no valid tasks"}), 400

    insert_many("project_tasks", rows)

    return jsonify({
        "status": "ok",
        "count": len(rows)
    })
@app.route("/projects/tasks/pin", methods=["POST"])
@login_required
def toggle_pin():
    data = request.get_json() or {}

    task_id = data.get("task_id")
    is_pinned = data.get("is_pinned")

    if not task_id:
        return jsonify({"error": "Missing task_id"}), 400

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"},
        json={"is_pinned": bool(is_pinned)}
    )

    return jsonify({"status": "ok"})
@app.route("/projects/tasks/reorder", methods=["POST"])
@login_required
def reorder_tasks():
    data = request.get_json() or {}

    dragged = data.get("dragged_id")
    target = data.get("target_id")

    if not dragged or not target:
        return jsonify({"error": "Missing task ids"}), 400

    rows = get(
        "project_tasks",
        params={
            "task_id": f"in.({dragged},{target})",
            "select": "task_id,order_index,due_date,priority_rank,is_pinned"
        }
    )

    if len(rows) != 2:
        return jsonify({"error": "Tasks not found"}), 404

    a, b = rows
    if (
    a.get("due_date") != b.get("due_date")
    or a.get("priority_rank") != b.get("priority_rank")
    or a.get("is_pinned") != b.get("is_pinned")
    ):
        return jsonify({"error": "Tasks must have the same due date, priority, and pin status to reorder"}), 400
    # 🔄 swap order_index
    update(
        "project_tasks",
        params={"task_id": f"eq.{a['task_id']}"},
        json={"order_index": b["order_index"]}
    )
    update(
        "project_tasks",
        params={"task_id": f"eq.{b['task_id']}"},
        json={"order_index": a["order_index"]}
    )

    return jsonify({"status": "ok"})
@app.route("/todo/move", methods=["POST"])
@login_required
def move_eisenhower_task():
    data = request.get_json()
    task_id = data["id"]
    quadrant = data["quadrant"]
    

    update(
        "todo_matrix",
        params={"id": f"eq.{task_id}"},
        json={"quadrant": quadrant}
    )

    return jsonify({"status": "ok"})

def get_one(table, params=None):
    params = params or {}
    params = dict(params)
    params["limit"] = 1

    rows = get(table, params=params)
    return rows[0] if rows else None

def get_all(table, params=None, order=None):
    """
    Fetch multiple rows.
    Returns list (possibly empty).
    """
    params = params or {}

    if order:
        params = dict(params)  # avoid mutating caller dict
        params["order"] = order

    return get(table, params=params) or []
def get_latest_scribble(user_id):
    rows = get(
        "scribble_notes",
        params={
            "user_id": f"eq.{user_id}",
            "order": "updated_at.desc",
            "limit": 1
        }
    )
    return rows[0] if rows else None

@app.route("/notes/scribble", methods=["GET"])
@login_required
def scribble_list():
    q = (request.args.get("q") or "").strip()

    params = {
        "user_id": f"eq.{session['user_id']}",
        "order": "updated_at.desc",
    }

    if q:
        # search in title OR content (case-insensitive)
        params["or"] = f"(title.ilike.*{q}*,content.ilike.*{q}*)"

    notes = get("scribble_notes", params=params) or []

    return render_template(
        "scribble_list.html",
        notes=notes,
        q=q,
    )


@app.route("/notes/scribble/new")
def scribble_new():
    return render_template("scribble_edit.html", note=None)
@app.route("/notes/scribble/<note_id>")
def scribble_edit(note_id):
    note = get_one("scribble_notes", params={"id": f"eq.{note_id}"})
    
    if not note:
        abort(404)
    return render_template("scribble_edit.html", note=note)
    
   
@app.route("/notes/scribble/save", methods=["POST"])
@login_required
def save_scribble():
    data = request.get_json() or {}
    user_id = session["user_id"]

    note_id = data.get("id")
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()

    if note_id:
        # 🔁 UPDATE existing note
        update(
            "scribble_notes",
            params={
                "id": f"eq.{note_id}",
                "user_id": f"eq.{user_id}"
            },
            json={
                "title": title,
                "content": content
            }
        )
    else:
        # ➕ CREATE new note
        res = post(
            "scribble_notes",
            {
                "user_id": user_id,
                "title": title,
                "content": content
            }
        )
        note_id = res[0]["id"] if res else None

    return jsonify({
        "status": "ok",
        "id": note_id
    })
@app.route("/tasks/occurrence/update", methods=["POST"])
@login_required
def update_task_occurrence_route():
    data = request.get_json()

    update_task_occurrence(
        user_id=session["user_id"],
        task_id=data["task_id"],
        task_date=data["date"],
        title=data.get("title"),
        status=data.get("status")
    )

    return "", 204

def get_conflicts(user_id, plan_date, start_time, end_time, exclude_id=None):
    existing = get(
        "daily_events",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date}",
            "is_deleted": "eq.false"
        }
    ) or []

    conflicts = []

    for e in existing:
        if exclude_id and str(e["id"]) == str(exclude_id):
            continue

        if not (
            end_time <= e["start_time"] or
            start_time >= e["end_time"]
        ):
            conflicts.append({
                "start_time": str(e["start_time"]),
                "end_time": str(e["end_time"]),
                "title": e["title"]
            })

    return conflicts

@app.route("/planner-v2")
def planner_v2():
    return render_template("planner_v2.html")
@app.route("/api/v2/events")
def list_events():
    user_id = "VenghateshS"
    plan_date = request.args.get("date")

    events = get(
        "daily_events",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date}",
            "is_deleted": "eq.false",
            "order": "start_time.asc"
        }
    ) or []

    return jsonify(events)
@app.route("/api/v2/events", methods=["POST"])
@login_required
def create_event():
    from flask import jsonify

    user_id = session["user_id"]
    data = request.json
    force = data.get("force", False)

    if data["end_time"] <= data["start_time"]:
        return jsonify({"error": "Invalid time range"}), 400

    conflicts = get_conflicts(
        user_id,
        data["plan_date"],
        data["start_time"],
        data["end_time"]
    )

    if conflicts and not force:
        return jsonify({
            "conflict": True,
            "conflicting_events": conflicts
        }), 409

    response1 = post("daily_events", {
    "user_id": user_id,
    "plan_date": data["plan_date"],
    "start_time": data["start_time"],
    "end_time": data["end_time"],
    "title": data["title"],
    "description": data.get("description", ""),
    "priority": data.get("priority", "medium")
    })
    print("Created event:", response1)
    created_row = response1[0] if response1 else None
    print("Created row:", created_row )
# 🔥 AUTO SYNC TO GOOGLE
    if created_row:
        try:
            google_id = insert_google_event(created_row)

            if google_id:
                update(
                    "daily_events",
                    params={"id": f"eq.{created_row['id']}"},
                    json={"google_event_id": google_id}
                )
        except Exception as e:
            print("Google sync failed:", e)

    return jsonify({"success": True})


@app.route("/api/v2/events/<event_id>", methods=["PUT"])
def update_event(event_id):
    from flask import jsonify

    user_id = "VenghateshS"
    data = request.json
    force = data.get("force", False)

    conflicts = get_conflicts(
        user_id,
        data["plan_date"],
        data["start_time"],
        data["end_time"],
        exclude_id=event_id
    )

    if conflicts and not force:
        return jsonify({
            "conflict": True,
            "conflicting_events": conflicts
        }), 409

    update(
        "daily_events",
        params={"id": f"eq.{event_id}"},
        json={
            "start_time": data["start_time"],
            "end_time": data["end_time"],
            "title": data["title"],
            "description": data.get("description", "")
        }
    )
    # 🔥 SYNC GOOGLE UPDATE
    row = get(
        "daily_events",
        params={"id": f"eq.{event_id}"}
    )

    if row and row[0].get("google_event_id"):
        try:
            google_id = row[0]["google_event_id"]

            # 🔥 Load user Google credentials from DB
            user_id = "VenghateshS"

            rows = get(
                "user_google_tokens",
                {"user_id": f"eq.{user_id}"}
            )

            if rows:
                token_row = rows[0]

                credentials = Credentials(
                    token=token_row["access_token"],
                    refresh_token=token_row["refresh_token"],
                    token_uri=token_row["token_uri"],
                    client_id=token_row["client_id"],
                    client_secret=token_row["client_secret"],
                    scopes=token_row["scopes"].split(",")
                )

                if credentials.expired and credentials.refresh_token:
                    credentials.refresh(Request())

                    update(
                        "user_google_tokens",
                        params={"user_id": f"eq.{user_id}"},
                        json={"access_token": credentials.token}
                    )

                service = build("calendar", "v3", credentials=credentials)

                service.events().update(
                    calendarId="primary",
                    eventId=google_id,
                    body={
                        "summary": data["title"],
                        "description": data.get("description", ""),
                        "start": {
                            "dateTime": f"{data['plan_date']}T{data['start_time']}:00",
                            "timeZone": "Asia/Kolkata"
                        },
                        "end": {
                            "dateTime": f"{data['plan_date']}T{data['end_time']}:00",
                            "timeZone": "Asia/Kolkata"
                        }
                    }
                ).execute()

        except Exception as e:
            print("Google update failed:", e)
    return jsonify({"success": True})

@app.route("/api/v2/events/<event_id>", methods=["DELETE"])
def delete_event(event_id):
    update(
        "daily_events",
        params={"id": f"eq.{event_id}"},
        json={"is_deleted": True}
    )
    row = get(
    "daily_events",
    params={"id": f"eq.{event_id}"}
)

    if row and row[0].get("google_event_id"):
        try:
            google_id = row[0]["google_event_id"]

            user_id = "VenghateshS"

            rows = get(
                "user_google_tokens",
                {"user_id": f"eq.{user_id}"}
            )

            if rows:
                token_row = rows[0]

                credentials = Credentials(
                    token=token_row["access_token"],
                    refresh_token=token_row["refresh_token"],
                    token_uri=token_row["token_uri"],
                    client_id=token_row["client_id"],
                    client_secret=token_row["client_secret"],
                    scopes=token_row["scopes"].split(",")
                )

                service = build("calendar", "v3", credentials=credentials)

                service.events().delete(
                    calendarId="primary",
                    eventId=google_id
                ).execute()

        except Exception as e:
            print("Google delete failed:", e)
    return {"ok": True}
@app.route("/api/v2/project-tasks")
def get_project_tasks():
    user_id = "VenghateshS"
    date = request.args.get("date")

    if not date:
        return jsonify([])

    tasks = get(
        "project_tasks",
        params={
            "user_id": f"eq.{user_id}",
            "is_eliminated": "eq.false",
            "status": "neq.done",
            "or": f"(due_date.is.null,due_date.eq.{date},due_date.lt.{date})",
            "select": """
                task_id,
                task_text,
                priority,
                project_id,
                start_time,
                due_date,
                projects(name)
            """
        }
    )

    return jsonify(tasks)

@app.route("/api/v2/project-tasks/<task_id>/schedule", methods=["POST"])
def schedule_project_task(task_id):
    data = request.json

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"},
        json={
            "plan_date": data["due_date"],
            "start_time": data["start_time"],
            "end_time": data["end_time"]
        }
    )

    return {"ok": True}
@app.route("/api/v2/project-tasks/<task_id>", methods=["GET"])
def get_single_project_task(task_id):

    task = get(
        "project_tasks",
        params={
            "task_id": f"eq.{task_id}",
            "select": "*"
        }
    )

    return jsonify(task[0] if task else {})

@app.route("/api/v2/project-tasks/<task_id>", methods=["PUT"])
def update_project_task(task_id):
    data = request.json

    allowed_fields = {
    "task_text",
    "notes",
    "status",
    "priority",
    "planned_hours",
    "actual_hours",
    "duration_days",
    "due_date",
    "start_time",
    "notes",
    "recurrence",
    "recurrence_type",
    "recurrence_interval",
    "recurrence_end"
    }

    update_payload = {
        k: v for k, v in data.items()
        if k in allowed_fields
    }

    if "start_time" in update_payload and update_payload["start_time"] == "":
     update_payload["start_time"] = None

    update(
    "project_tasks",
    params={"task_id": f"eq.{task_id}"},
    json=update_payload
)


    return jsonify({"success": True})


@app.route("/api/v2/project-tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id):
    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"},
        json={"is_completed": True}
    )

    return {"ok": True}
@app.route("/api/v2/daily-health")
@login_required
def get_daily_health():
    user_id = session["user_id"]
    plan_date = request.args.get("date")

    if not plan_date:
        return jsonify({})

    # ---------------------
    # Load health
    # ---------------------
    health_rows = get(
        "daily_health",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date}"
        }
    )

    health = health_rows[0] if health_rows else {}

    # ---------------------
    # Load habits
    # ---------------------
    habit_rows = get(
        "daily_habits",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date}"
        }
    )

    habits = habit_rows[0]["habits"] if habit_rows else {}

    # ---------------------
    # Habit %
    # ---------------------
    total = len(HABIT_LIST)
    completed = sum(1 for h in HABIT_LIST if habits.get(h))
    habit_percent = round((completed / total) * 100) if total else 0

    # ---------------------
    # Streak
    # ---------------------
    streak = compute_health_streak(user_id, date.fromisoformat(plan_date))

    return jsonify({
        **health,
        "habits": habits,
        "habit_percent": habit_percent,
        "streak": streak
    })

@app.route("/api/v2/daily-health", methods=["POST"])
@login_required
def save_daily_health():
    user_id = session["user_id"]
    data = request.json
    plan_date = data.get("plan_date")

    if not plan_date:
        return jsonify({"error": "plan_date required"}), 400

    payload = {
        "user_id": user_id,
        "plan_date": plan_date,
        "weight": clean_number(data.get("weight")),
        "sleep_hours": clean_number(data.get("sleep_hours")),
        "mood": data.get("mood"),
        "energy_level": int(data.get("energy_level")) if data.get("energy_level") else None,
        "notes": data.get("notes")
    }

    # 🔥 UPSERT instead of check-then-update
    post(
        "daily_health",
        payload,
        prefer="resolution=merge-duplicates"
    )

    return jsonify({"success": True})

@app.route("/health")
@login_required
def health_dashboard():
    user_id = session["user_id"]
    plan_date = request.args.get("date")

    if plan_date:
        plan_date = date.fromisoformat(plan_date)
    else:
        plan_date = datetime.now(IST).date()

    plan_date_str = plan_date.isoformat()

    # -----------------------
    # Load daily health
    # -----------------------
    health_rows = get(
        "daily_health",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date_str}"
        }
    )

    health = health_rows[0] if health_rows else {}

    # -----------------------
    # Load daily habits
    # -----------------------
    habit_rows = get(
        "daily_habits",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date_str}"
        }
    )

    habits = habit_rows[0]["habits"] if habit_rows else {}

    # -----------------------
    # Habit completion %
    # -----------------------
    total = len(HABIT_LIST)
    completed = sum(1 for h in HABIT_LIST if habits.get(h))
    habit_percent = round((completed / total) * 100) if total else 0

    # -----------------------
    # Streak
    # -----------------------
    health_streak = compute_health_streak(user_id, plan_date)

    return render_template(
        "health_dashboard.html",
        plan_date=plan_date,
        health=health,
        habits=habits,
        habit_percent=habit_percent,
        health_streak=health_streak,
        habit_list=HABIT_LIST,
        habit_icons=HABIT_ICONS
    )


@app.route("/api/save-habit", methods=["POST"])
@login_required
def save_habit():
    data = request.json
    user_id = session["user_id"]

    habit_key = data.get("habit")
    completed = data.get("completed")
    plan_date = data.get("plan_date")

    if not habit_key or not plan_date:
        return jsonify({"error": "Missing data"}), 400

    # 1️⃣ Get existing row
    rows = get(
        "daily_habits",
        {
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date}"
        }
    )

    current_habits = rows[0].get("habits") if rows else {}
    current_habits = current_habits or {}

    # 2️⃣ Update only changed habit
    current_habits[habit_key] = completed

    # 3️⃣ Proper UPSERT
    post(
        "daily_habits?on_conflict=user_id,plan_date",
        {
            "user_id": user_id,
            "plan_date": plan_date,
            "habits": current_habits
        },
        prefer="resolution=merge-duplicates"
    )

    return jsonify({"success": True})

def clean_number(val):
    return float(val) if val not in ("", None) else None
def normalize_category(name):
    return name.strip().lower().replace("-", " ").title()

@app.route("/references/add", methods=["POST"])
@login_required
def add_reference():

    data = request.get_json()
    user_id = session["user_id"]

    raw_tags = data.get("tags", [])

    # ---------------------------------
    # Normalize Tags
    # ---------------------------------
    tags = []

    if isinstance(raw_tags, list):
        for t in raw_tags:
            if isinstance(t, dict) and t.get("value"):
                tags.append(t["value"].strip().lower())
            elif isinstance(t, str):
                tags.append(t.strip().lower())

    elif isinstance(raw_tags, str):
        tags = [t.strip().lower() for t in raw_tags.split(",") if t.strip()]

    # Remove duplicates
    tags = list(set(tags))

    # ---------------------------------
    # Auto-create missing tags
    # ---------------------------------
    for tag in tags:
        existing = get("tags", {
            "user_id": f"eq.{user_id}",
            "name": f"eq.{tag}"
        })

        if not existing:
            post("tags", {
                "user_id": user_id,
                "name": tag
            })

    # ---------------------------------
    # Category Handling
    # ---------------------------------
    category = data.get("category")

    if not category:

        # Fetch existing references
        existing_refs = get("reference_links", {
            "user_id": f"eq.{user_id}"
        })

        tag_category_scores = {}

        for ref in existing_refs:
            ref_category = ref.get("category")
            ref_tags = ref.get("tags", [])

            for tag in tags:
                if tag in ref_tags and ref_category:
                    tag_category_scores[ref_category] = (
                        tag_category_scores.get(ref_category, 0) + 1
                    )

        if tag_category_scores:
            # Pick highest scoring category
            category = max(tag_category_scores, key=tag_category_scores.get)

        elif tags:
            # 🔥 Create new category from strongest tag
            category = tags[0].capitalize()

        else:
            category = "Uncategorized"
    

    ALLOWED_TAGS = [
        "p", "br",
        "h1", "h2", "h3",
        "strong", "em",
        "ul", "ol", "li",
        "a"
    ]

    ALLOWED_ATTRIBUTES = {
        "a": ["href", "target", "rel"]
    }



    raw_description = data.get("description") or ""

    clean_description = bleach.clean(
        raw_description,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True
    )
    # ---------------------------------
    # Save Reference
    # ---------------------------------
    post("reference_links", {
        "user_id": user_id,
        "title": data.get("title"),
        "description": clean_description,
        "url": data.get("url"),
        "tags": tags,
        "category": category
    })

    return jsonify({"success": True})
@app.route("/references")
@login_required
def list_references():
    user_id = session["user_id"]
    tag = request.args.get("tag", "").strip().lower()
    category = request.args.get("category", "").strip()
    print("🔥 DEBUG /references")
    print("Query Params → tag:", tag)
    print("Query Params → category:", category)
    params = {
        "user_id": f"eq.{user_id}",
        "order": "created_at.desc"
    }

    if tag:
      params["tags"] = f"cs.{{{tag}}}"

    if category:
      params["category"] = f"eq.{category}"
    refs = get("reference_links", params=params)

    all_refs = get("reference_links", {
        "user_id": f"eq.{user_id}"
    })

    categories = sorted(
        list({r["category"] for r in all_refs if r.get("category")})
    )

    return render_template(
        "reference.html",
        references=refs,
        categories=categories
    )

@app.get("/search_references")
def search_references():
    user_id = session["user_id"]
    query = request.args.get("q", "").strip()

    if not query:
        return jsonify({"results": []})

    rows = get(
        "reference_links",
        {
            "user_id": f"eq.{user_id}",
            "tags": f"ilike.%{query}%"
        }
    )

    return jsonify({"results": rows})

def process_tags(user_id, tag_list):
    processed_tags = []

    for tag in tag_list:
        tag = tag.strip().lower()

        # check if exists
        existing = get("tags", {
            "user_id": f"eq.{user_id}",
            "name": f"eq.{tag}"
        })

        if existing:
            processed_tags.append(tag)
        else:
            post("tags", {
                "user_id": user_id,
                "name": tag
            })
            processed_tags.append(tag)

    return processed_tags

@app.route("/api/tags")
@login_required
def get_tags():
    user_id = session["user_id"]

    rows = get("tags", {
        "user_id": f"eq.{user_id}"
    })

    tag_list = [row["name"] for row in rows]

    return jsonify(tag_list)



@app.post("/ai/reflection-summary")
@login_required
def reflection_summary():
    reflection_text = request.json.get("reflection", "")

    prompt = f"""
    Summarize this daily reflection.
    Extract:
    - Key wins
    - Challenges
    - Lessons learned
    - Improvement suggestions

    Reflection:
    {reflection_text}
    """

    summary = call_gemini(prompt)

    return jsonify({"summary": summary})

@app.post("/ai/generate-day-plan")
@login_required
def generate_day_plan():
    user_id = session["user_id"]
    plan_date = request.json.get("date")

    # Get today's slots
    slots = get("daily_slots", {
        "plan_date": f"eq.{plan_date}",
        "select": "slot,plan,priority,category,tags",
        "order": "slot.asc"
    })

    prompt = f"""
    You are a productivity AI assistant.

    Here is today's schedule:
    {slots}

    Generate:
    1. A prioritized plan
    2. Suggested focus blocks
    3. Risk areas
    4. Time optimization suggestions

    Keep it structured and concise.
    """

    ai_output = call_gemini(prompt)

    return jsonify({"result": ai_output})

@app.post("/ai/assistant")
@login_required
def ai_assistant():
    message = request.json.get("message")

    prompt = f"""
    You are a productivity assistant for a Daily Planner app.
    Help the user improve time management.

    User says:
    {message}
    """

    response = call_gemini(prompt)

    return jsonify({"reply": response})

@app.post("/references/ai-generate")
@login_required
def ai_generate_reference():
    user_id = session["user_id"]
    query = request.json.get("query")

    prompt = f"""
    Generate ONE high-quality web reference for: "{query}"

    Return strictly in JSON format:

    {{
      "title": "",
      "url": "",
      "description": "",
      "category": "Learning",
      "tags": ["tag1","tag2"]
    }}

    Use a real public URL.
    No explanation. JSON only.
    """

    ai_text = call_gemini(prompt)

    data = json.loads(ai_text)

    return jsonify(data)


@app.route("/references/metadata", methods=["POST"])
@login_required
def fetch_metadata():

    data = request.json
    url = data.get("url")
    use_ai = data.get("use_ai", True)

    if not url:
        return jsonify({"error": "URL required"}), 400

    try:
        # Always fetch page title
        page = requests.get(url, timeout=5)
        soup = BeautifulSoup(page.text, "html.parser")
        title = soup.title.string.strip() if soup.title else None

        # If AI disabled → return only title
        if not use_ai:
            return jsonify({
                "title": title,
                "tags": [],
                "category": None
            })

        # AI enabled
        prompt = f"""
        Analyze this webpage title:
        "{title}"

        Return JSON ONLY like this:
        {{
          "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
          "category": "Technology"
        }}

        Category must be one of:
        Technology, Health, Finance, Learning
        """

        ai_response = call_gemini(prompt)

        import json
        ai_data = json.loads(ai_response)

        return jsonify({
            "title": title,
            "tags": ai_data.get("tags", []),
            "category": ai_data.get("category")
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/references/tags")
@login_required
def get_tags_with_counts():

    user_id = session["user_id"]
    print("🔥 DEBUG /references/tags called")
    rows = get("reference_links", {
        "user_id": f"eq.{user_id}"
    })

    grouped_tags = {}

    for ref in rows:
        category = ref.get("category") or "Uncategorized"
        tags = ref.get("tags", [])

        if category not in grouped_tags:
            grouped_tags[category] = {}

        for tag in tags:
            grouped_tags[category][tag] = (
                grouped_tags[category].get(tag, 0) + 1
            )

    return jsonify(grouped_tags)

@app.route("/references/list")
@login_required
def list_references_api():

    user_id = session["user_id"]
    page = int(request.args.get("page", 1))
    tags = request.args.get("tags")
    search = request.args.get("search")
    sort = request.args.get("sort", "created_at_desc")
    category = request.args.get("category")
    limit = 10
    offset = (page - 1) * limit

    filters = {
        "user_id": f"eq.{user_id}",
        "limit": limit,
        "offset": offset
    }

    # Sorting
    if sort == "created_at_asc":
        filters["order"] = "created_at.asc"
    elif sort == "title_asc":
        filters["order"] = "title.asc"
    else:
        filters["order"] = "created_at.desc"

    and_conditions = []

    # 1️⃣ Multi-tag OR block
    if tags:
        tag_list = tags.split(",")

        tag_or = ",".join([
            f"tags.cs.{{{tag.strip()}}}"
            for tag in tag_list if tag.strip()
        ])

        if tag_or:
            and_conditions.append(f"or({tag_or})")

    # 2️⃣ Search OR block
    if search:
        search_or = f"title.ilike.%{search}%,description.ilike.%{search}%"
        and_conditions.append(f"or({search_or})")
    if category:
     and_conditions.append(f"category.eq.{category}")
    # 3️⃣ Attach combined AND logic
    if and_conditions:
        filters["and"] = f"({','.join(and_conditions)})"
    print("🔥 DEBUG /references/list")
    print("Incoming → tags:", tags)
    print("Incoming → search:", search)
    print("Incoming → sort:", sort)
    print("Final filters →", filters)
    rows = get("reference_links", filters)

    return jsonify({
    "items": rows,
    "has_more": len(rows) == limit
    })

@app.route("/references/ai-generate-groq", methods=["POST"])
@login_required
def ai_generate_groq():
    import os
    import requests
    import json
    import urllib.parse

    data = request.get_json()
    query = data.get("query")

    GROQ_API_KEY = os.getenv("GROQ_API_KEY")

    system_prompt = """
        You are a knowledge reference generator.

        Return ONLY valid JSON in this exact format:
        {
        "title": "short clear title",
        "description": "detailed 4-6 sentence explanation",
        "tags": ["tag1", "tag2"],
        "category": "Technology | Health | Finance | Learning",
        "url": "real public URL if known, otherwise null"
        }

        Rules:
        - No markdown
        - No explanation
        - Only raw JSON
        """

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            
        },
        json={
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            "temperature": 0.3
        }
    )

    if response.status_code != 200:
        return jsonify({"error": "Groq failed"}), 500

    result = response.json()
    content = result["choices"][0]["message"]["content"]

    try:
        structured = json.loads(content)
    except Exception:
        return jsonify({"error": "Invalid AI JSON format"}), 500

    # 🔥 Fallback: If no URL, generate Google search link
    if not structured.get("url"):
        search_url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
        structured["url"] = search_url

    # Safety defaults
    structured["title"] = structured.get("title") or query[:80]
    structured["description"] = structured.get("description") or "No description generated."
    structured["tags"] = structured.get("tags") or []
    structured["category"] = structured.get("category") or "Learning"

    return jsonify(structured)
def insert_event(user_id, data, force=False):
    if data["end_time"] <= data["start_time"]:
        return {"error": "Invalid time range"}, 400

    conflicts = get_conflicts(
        user_id,
        data["plan_date"],
        data["start_time"],
        data["end_time"]
    )

    if conflicts and not force:
        return {
            "conflict": True,
            "conflicting_events": conflicts
        }, 409

    response1 = post("daily_events", {
        "user_id": user_id,
        "plan_date": data["plan_date"],
        "start_time": data["start_time"],
        "end_time": data["end_time"],
        "title": data["title"],
        "description": data.get("description", "")
    })

    created_row = response1[0] if response1 else None

    # 🔥 GOOGLE AUTO SYNC HERE
    if created_row:
        try:
            google_id = insert_google_event(created_row)

            if google_id:
                update(
                    "daily_events",
                    params={"id": f"eq.{created_row['id']}"},
                    json={"google_event_id": google_id}
                )
        except Exception as e:
            print("Google sync failed:", e)

    return {"success": True}, 200

@app.post("/api/v2/smart-create")
def smart_create():
    data = request.json or {}

    text = data.get("text", "").strip()
    date = safe_date_from_string(data.get("date"))

    created = []
    failed = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        try:
            parsed = parse_planner_input(line, date)

            payload = {
                "plan_date": str(parsed["date"]),
                "start_time": parsed["start"].strftime("%H:%M"),
                "end_time": parsed["end"].strftime("%H:%M"),
                "title": parsed["title"],
            }
            user_id = session["user_id"]
            result, status = insert_event(user_id, payload)

            if status == 200:
                created.append(payload)
            else:
                failed.append({
                    "line": raw_line,
                    "error": result
                })

        except Exception as e:
            failed.append({
                "line": raw_line,
                "error": str(e)
            })

    return jsonify({
        "status": "ok",
        "created_count": len(created),
        "failed_count": len(failed),
        "failed": failed
    })

@app.route("/ping")
def ping():
    return "OK", 200
@app.route('/google-login')
def google_login():
    flow = Flow.from_client_config(
    {
        "web": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    },
    scopes=SCOPES,
    redirect_uri=url_for('oauth2callback', _external=True)
    )

    authorization_url, state = flow.authorization_url(
    access_type='offline',
    include_granted_scopes='true',
    prompt='consent'
    )

    session['state'] = state
    return redirect(authorization_url)

def credentials_to_dict(credentials):
    return {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes
    }
@app.route('/oauth2callback')
@login_required
def oauth2callback():

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=SCOPES,
        state=session["state"],
        redirect_uri=url_for("oauth2callback", _external=True)
    )

    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials

    creds_dict = credentials_to_dict(credentials)
    user_id = session["user_id"]

    # 🔥 MANUAL UPSERT (since you don't use supabase upsert)
    existing = get(
        "user_google_tokens",
        {"user_id": f"eq.{user_id}"}
    )

    if existing:
        update(
            "user_google_tokens",
            params={"user_id": f"eq.{user_id}"},
            json={
                "access_token": creds_dict["token"],
                "refresh_token": creds_dict["refresh_token"],
                "token_uri": creds_dict["token_uri"],
                "client_id": creds_dict["client_id"],
                "client_secret": creds_dict["client_secret"],
                "scopes": ",".join(creds_dict["scopes"])
            }
        )
    else:
        post(
            "user_google_tokens",
            {
                "user_id": user_id,
                "access_token": creds_dict["token"],
                "refresh_token": creds_dict["refresh_token"],
                "token_uri": creds_dict["token_uri"],
                "client_id": creds_dict["client_id"],
                "client_secret": creds_dict["client_secret"],
                "scopes": ",".join(creds_dict["scopes"])
            }
        )

    return redirect("/planner-v2")

def insert_google_event(event_row):
    print("🔥 GOOGLE INSERT FUNCTION CALLED")
    user_id = session.get("user_id")
    if not user_id:
      return None
    user_id = session["user_id"]  # session.get("user_id") or hardcoded for testing
    print("USER ID:", session.get("user_id"))
    rows = get(
        "user_google_tokens",
        {"user_id": f"eq.{user_id}"}
    )

    if not rows:
        return None

    row = rows[0]

    credentials = Credentials(
        token=row["access_token"],
        refresh_token=row["refresh_token"],
        token_uri=row["token_uri"],
        client_id=row["client_id"],
        client_secret=row["client_secret"],
        scopes=row["scopes"].split(",")
    )

    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

        update(
            "user_google_tokens",
            params={"user_id": f"eq.{user_id}"},
            json={
                "access_token": credentials.token,
                "updated_at": datetime.utcnow().isoformat()
            }
        )

    service = build("calendar", "v3", credentials=credentials)

    start_iso = f"{event_row['plan_date']}T{event_row['start_time']}:00"
    end_iso = f"{event_row['plan_date']}T{event_row['end_time']}:00"

    event_body = {
        "summary": event_row["title"],
        "description": event_row.get("description", ""),
        "start": {
            "dateTime": start_iso,
            "timeZone": "Asia/Kolkata"
        },
        "end": {
            "dateTime": end_iso,
            "timeZone": "Asia/Kolkata"
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 10}
            ]
        }
    }

    created = service.events().insert(
        calendarId="primary",
        body=event_body
    ).execute()

    return created.get("id")



# ENTR
# Y POINT
# ==========================================================
#if __name__ == "__main__":
 #   logger.info("Starting Daily Planner – stable + Eisenhower")
    #app.run(debug=True)
