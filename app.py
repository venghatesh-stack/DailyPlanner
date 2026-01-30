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
    return defaultdict(lambda: defaultdict(list))


def build_eisenhower_view(project_tasks, plan_date,project_map):


    todo = {
        "do": empty_quadrant(),
        "schedule": empty_quadrant(),
        "delegate": empty_quadrant(),
        "eliminate": empty_quadrant(),
    }
  
    for t in project_tasks:
        urgency = None

        # 🔴🟠 Compute urgency ONLY for today AND only if not done
        if t.get("due_date") == plan_date and t.get("status") != "done":
            urgency = compute_urgency(
                t.get("due_date"),
                t.get("due_time")
            )

        print(
            t["text"],
            "due:", t.get("due_date"),
            t.get("due_time"),
            "urgency:", urgency
        )

        task = {
            "id": t["id"],
            "text": t["text"],           # ✅ FIX
            "status": t["status"],       # ✅ keep status
            "done": t["done"],           # ✅ already computed
            "project_id": t.get("project_id"),
            "project_name": t.get("project_name"),
            "recurring": t.get("recurring"),
            "recurrence": t.get("recurrence"),
            "delegated_to": t.get("delegated_to"),
            "elimination_reason": t.get("elimination_reason"),
            "due_date": t.get("due_date"),
            "due_time": t.get("due_time"),
            "urgency": urgency,
        }

          # 🗑 Eliminate
        if t.get("is_eliminated"):
            todo["eliminate"]["eliminated"]["tasks"].append(task)
            continue

        # 🤝 Delegate
        if t.get("delegated_to"):
            todo["delegate"]["delegated"]["tasks"].append(task)
            continue

        # 🔥 Do Now
        if t.get("due_date") and t["due_date"] == plan_date:
            todo["do"]["today"]["tasks"].append(task)
            continue

        # 📅 Schedule
        if t.get("due_date") and t["due_date"] > plan_date:

            todo["schedule"]["future"]["tasks"].append(task)

    return todo
def parse_date(d):
    if isinstance(d, str):
        return datetime.fromisoformat(d).date()
    return d

def compute_quadrant_counts(todo):
    counts = {}

    for q, categories in todo.items():
        total = 0
        done = 0

        for subs in categories.values():
            for tasks in subs.values():
                for t in tasks:
                    total += 1
                    if t.get("done"):
                        done += 1

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
        "id": t["id"],
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

# ==========================================================
# ROUTES – EISENHOWER MATRIX
# ==========================================================
@app.route("/todo", methods=["GET"])
@login_required
def todo():
    from datetime import date
    import calendar
    
    year = int(request.args.get("year", date.today().year))
    month = int(request.args.get("month", date.today().month))
    day = int(request.args.get("day", date.today().day))

    plan_date = date(year, month, day)

    # 1. Fetch tasks
    projects = get("projects")

    project_map = {
        p["id"]: p["name"]
        for p in projects
    }
    raw_tasks = get("project_tasks")

    tasks = [
        normalize_task(t, project_name=project_map.get(t.get("project_id")))
        for t in raw_tasks
    ]


    for t in tasks:
        t["due_date"] = parse_date(t["due_date"])

        tasks = [
            t for t in tasks
            if t.get("due_date")
            and t["due_date"].year == year
            and t["due_date"].month == month
        ]

   
    # 2. Build Eisenhower (urgency is computed there)
    todo = build_eisenhower_view(tasks, plan_date,project_map)
    quadrant_counts = compute_quadrant_counts(todo)
    # 3. Render
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
    
    # --------------------------------------------------
    # STEP 1: Update Eisenhower task (always)
    # --------------------------------------------------
    update(
        "todo_matrix",
        params={"id": f"eq.{task_id}"},
        json={"is_done": is_done},
    )
     # --------------------------------------------------
    # STEP 2 (OPTIONAL): Sync back to project task
    # --------------------------------------------------
    if is_done:
        rows = get(
            "todo_matrix",
            params={
                "id": f"eq.{task_id}",
                "select": "source_task_id, recurring_instance_id",
            },
        )

        if rows:
            source_id = rows[0].get("source_task_id")
            recurring_instance_id = rows[0].get("recurring_instance_id")

            if source_id and not recurring_instance_id:
                update(
                    "project_tasks",
                    params={"id": f"eq.{source_id}"},
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

    task_id = data["id"]

    # 🔹 METADATA-ONLY SAVE (project change, etc.)
    if "quadrant" not in data:
        if "project_id" in data:
            update(
                "todo_matrix",
                params={"id": f"eq.{task_id}"},
                json={"project_id": data["project_id"]},
            )
        return jsonify({"id": task_id})

    # 🔹 FULL TASK AUTOSAVE
    result = autosave_task(
        plan_date=data["plan_date"],
        task_id=task_id,
        quadrant=data["quadrant"],
        text=data.get("task_text"),
        is_done=data.get("is_done", False),
    )

    # 🔒 Never lose project_id
    if "project_id" in data:
        update(
            "todo_matrix",
            params={"id": f"eq.{task_id}"},
            json={"project_id": data["project_id"]},
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
@app.route("/projects/<project_id>/tasks")
@login_required
def project_tasks(project_id):
    user_id = session["user_id"]

    rows = get(
        "projects",
        params={"id": f"eq.{project_id}", "user_id": f"eq.{user_id}"},
    )
    if not rows:
        return "Project not found", 404

    project = rows[0]

    raw_tasks = get(
        "project_tasks",
        params={
            "project_id": f"eq.{project_id}",
            "order": "created_at.asc",
        },
    )

    # ✅ NORMALIZE FOR SHARED UI
    tasks = [
        {
            "id": t["id"],
            "text": t["task_text"],
            "status": t.get("status"),
            "done": t.get("status") == "done",

            # 🔑 ADD THESE
            "start_date": t.get("start_date"),
            "duration_days": t.get("duration_days"),

            "due_date": t.get("due_date"),
            "due_time": t.get("due_time"),
            "delegated_to": t.get("delegated_to"),
            "elimination_reason": t.get("elimination_reason"),
            "project_name": project["name"],
            "urgency": None,
        }
        for t in raw_tasks
    ]

    grouped_tasks = group_tasks_smart(tasks)
    return render_template(
        "project_tasks.html",
        project=project,
        grouped_tasks=grouped_tasks,
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

@app.route("/projects/<project_id>/tasks/add", methods=["POST"])
@login_required
def add_project_task(project_id):
    text = request.form["task_text"]

    post(
        "project_tasks",
        {
            "project_id": project_id,
            "task_text": text,
            "status": "backlog",
        },
    )
  
    return redirect(url_for("project_tasks", project_id=project_id))

@app.route("/projects/tasks/send", methods=["POST"])
@login_required
def send_task_to_eisenhower():
    data = request.get_json() or {}

    task_id   = data.get("task_id")
    quadrant  = data.get("quadrant")
    plan_date = data.get("plan_date")

    if not task_id or not plan_date or not quadrant:
        return jsonify({"error": "Missing required fields"}), 400

    user_id = session["user_id"]

    # --------------------------------------------------
    # STEP 1: Prevent duplicate sends (IDEMPOTENT)
    # --------------------------------------------------
    existing = get(
        "todo_matrix",
        params={
            "source_task_id": f"eq.{task_id}",
            "plan_date": f"eq.{plan_date}",
            "is_deleted": "eq.false",
            "select": "id",
        },
    ) or []

    if existing:
        return jsonify({"status": "already-sent"})

    # --------------------------------------------------
    # STEP 2: Fetch project task text (source of truth)
    # --------------------------------------------------
    rows = get(
        "project_tasks",
        params={
            "id": f"eq.{task_id}",
            "user_id": f"eq.{user_id}",
            "select": "task_text",
        },
    )

    if not rows:
        return jsonify({"error": "Project task not found"}), 404

    task_text = rows[0]["task_text"]

    # --------------------------------------------------
    # STEP 3: Insert into Eisenhower matrix
    # --------------------------------------------------
    post(
        "todo_matrix",
        [{
            "plan_date": plan_date,
            "quadrant": quadrant,
            "task_text": task_text,
            "is_done": False,
            "is_deleted": False,
            "position": 999,
            "source_task_id": task_id,   # 🔑 link back
        }],
    )

    return jsonify({"status": "ok"})

@app.route("/projects/tasks/status", methods=["POST"])
@login_required
def update_project_task_status():
    data = request.get_json(force=True)

    update(
        "project_tasks",
        params={"id": f"eq.{data['task_id']}"},
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
        params={"id": f"eq.{task_id}"},
        json={"due_date": due_date},
    )
    logger.info(f"👉 task_id={task_id}, new_date={due_date}")
    return jsonify({"status": "ok"})
@app.route("/projects/tasks/<task_id>/update", methods=["POST"])
def update_task(task_id):
    data = request.json

    update("tasks", {
        "title": data.get("title"),
        "start_time": data.get("start_time"),
        "end_time": data.get("end_time"),
        "project": data.get("project"),
        "notes": data.get("notes"),
        "completed": data.get("completed")
    }, {"id": task_id})

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
            "id": f"eq.{task_id}",
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
        params={"id": f"eq.{task_id}"},
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
        params={"id": f"eq.{data['id']}"},
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
        params={"id": f"eq.{task_id}"},
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
        params={"id": f"eq.{data['id']}"},
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
        params={"id": f"eq.{task_id}"},
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
        params={"id": f"eq.{data['task_id']}"},
        json={"planned_hours": data["planned_hours"]}
    )
    return "", 204


@app.route("/projects/tasks/update-actual", methods=["POST"])
@login_required
def update_actual():
    data = request.get_json()
    update(
        "project_tasks",
        params={"id": f"eq.{data['task_id']}"},
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


# ==========================================================
# ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    logger.info("Starting Daily Planner – stable + Eisenhower")
    app.run(debug=True)
