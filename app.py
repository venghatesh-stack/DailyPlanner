## Eisenhower Matrix + Daily Planner integrated. Calender control working
from flask import Flask, request, redirect, url_for, render_template_string, session,jsonify,render_template
import os
from datetime import date, datetime, timedelta
import calendar
import json
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

from collections import defaultdict,OrderedDict
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

from utils.slots import current_slot,slot_label
import traceback



app = Flask(__name__)
@app.errorhandler(Exception)
def catch_all_errors(e):
    print("🔥 GLOBAL EXCEPTION CAUGHT 🔥")
    traceback.print_exc()   # <-- ALWAYS prints
    logger.exception("UNHANDLED EXCEPTION")
    return "Internal Server Error", 500
logger = setup_logger()
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "changeme")
# ==========================================================
# Log in codestarts here
# ==========================================================

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

    date_str = request.args.get("date")
    if date_str:
        plan_date = date.fromisoformat(date_str)
    else:
        plan_date = datetime.now(IST).date()

    if view == "weekly":
       # Monday → Sunday
        start = plan_date - timedelta(days=plan_date.weekday())
        end = start + timedelta(days=6)

        data = get_weekly_summary(start, end)
        insights = generate_weekly_insight(data)
        return render_template_string(
            SUMMARY_TEMPLATE,
            view="weekly",
            data=data,
            start=start,
            end=plan_date,
            insights=insights,
        )

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
    rows = get(
        "projects",
        params={"project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}"},
    )
    if not rows:
        return "Project not found", 404

    project = rows[0]
    sort = request.args.get("sort") or project.get("default_sort", "smart")
    order = SORT_PRESETS.get(sort, SORT_PRESETS["smart"])
    raw_tasks = get(
        "project_tasks",
        params={
            "project_id": f"eq.{project_id}",
            "order": order,
        },
    )

    tasks = [
        {
            "task_id": t["task_id"],
            "task_text": t["task_text"],
            "status": t.get("status"),
            "done": t.get("status") == "done",
            "start_date": t.get("start_date"),
            "duration_days": t.get("duration_days"),
            "due_date": t.get("due_date"),
            "due_time": t.get("due_time"),
            "delegated_to": t.get("delegated_to"),
            "elimination_reason": t.get("elimination_reason"),
            "project_name": project["name"],
            "urgency": None,
            "priority_rank": PRIORITY_MAP.get(t.get("priority"), 2),
            "is_pinned": t.get("is_pinned", False), # default to False
        }
        for t in raw_tasks
    ]

    grouped_tasks = group_tasks_smart(tasks)

    return render_template(
        "project_tasks.html",
        project=project,
        grouped_tasks=grouped_tasks,
        today=date.today().isoformat(),
        sort=sort,
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

    update(
        "project_tasks",
        params={"task_id": f"eq.{data['task_id']}"},
        json={"status": data["status"]},
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
@app.route("/tasks/timeline")
@login_required
def task_timeline():
    user_id = session["user_id"]

    today_tasks, future_tasks = load_timeline_tasks(user_id)

    return render_template(
        "task_timeline.html",
        today_tasks=today_tasks,
        future_tasks=future_tasks,
        today=date.today()
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
def get_latest_scribble(user_id):
    rows = get(
        "scribbles",
        params={
            "user_id": f"eq.{user_id}",
            "order": "updated_at.desc",
            "limit": 1
        }
    )
    return rows[0] if rows else None

@app.route("/notes/scribble", methods=["GET"])
@login_required
def scribble():
    user_id=session["user_id"]
    note = get_latest_scribble(user_id)
    return render_template("notes/scribble.html", note=note)


@app.route("/notes/scribble/save", methods=["POST"])
@login_required
def save_scribble():
    data = request.get_json()
    user_id=session["user_id"]
    post(
        "scribbles",
        json={
            "user_id": f".eq.{user_id}",
            "title": data.get("title"),
            "content": data.get("content")
        }
    )

    return jsonify({"status": "ok"})

=====================================================
# ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    logger.info("Starting Daily Planner – stable + Eisenhower")
    app.run(debug=True)
