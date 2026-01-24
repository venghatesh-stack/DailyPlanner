## Eisenhower Matrix + Daily Planner integrated. Calender control working
from flask import Flask, request, redirect, url_for, render_template_string, session,jsonify
import os
from datetime import date, datetime, timedelta
import calendar
import json
from supabase_client import get, post, update
from logger import setup_logger
from utils.dates import safe_date 
from config import TOTAL_SLOTS,QUADRANT_MAP,TASK_CATEGORIES,STATIC_TRAVEL_SUBGROUPS
from utils.slots import current_slot,slot_label
from utils.calender_links import google_calendar_link
from services.planner_service import load_day, save_day, get_daily_summary, get_weekly_summary,compute_health_streak,is_health_day,ensure_daily_habits_row,group_slots_into_blocks
from services.login_service import login_required
from services.eisenhower_service import autosave_task
from config import MIN_HEALTH_HABITS
from services.recurring_service import materialize_recurring_slots,materialize_recurring_tasks

from services.eisenhower_service import (
    load_todo,
    save_todo,
    copy_open_tasks_from_previous_day,  
    enable_travel_mode,
)

from services.untimed_service import remove_untimed_task  
from templates.planner import PLANNER_TEMPLATE
from templates.todo import TODO_TEMPLATE
from templates.summary import SUMMARY_TEMPLATE
from templates.login import LOGIN_TEMPLATE
from config import (
    IST,
    STATUSES,
    DEFAULT_STATUS, 
    MOTIVATIONAL_QUOTES,
    HABIT_ICONS,
    HABIT_LIST,
)
from config import META_SLOT
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
# Log in code ends here
# ==========================================================
@app.route("/health", methods=["GET", "HEAD"])
def health():
    return "OK", 200


# ==========================================================
# ROUTES – DAILY PLANNER
# ==========================================================
@app.route("/", methods=["GET", "POST"])
@login_required
def planner():
    user_id = session["user_id"]
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
  
    plans, habits, reflection,untimed_tasks = load_day(plan_date)
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
    )


# ==========================================================
# ROUTES – EISENHOWER MATRIX
# ==========================================================
@app.route("/todo", methods=["GET", "POST"])
@login_required
def todo():
    user_id="VenghateshS"
    if request.method == "HEAD":
        return "", 200
    today = datetime.now(IST).date()

    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    day = int(request.args.get("day", today.day))
    plan_date = safe_date(year, month, day)
    logger.debug("Todo route: %s %s", request.method, plan_date)
    if request.method == "POST":
        save_todo(plan_date, request.form)
        logger.debug("Session toast after save: %s", session.get("toast"))
        if "toast" not in session:
            session["toast"] = {
            "type": "success",
            "message": "💾 Eisenhower Matrix saved"
            }
            logger.debug("Fallback save toast set")
        return redirect(url_for("todo", year=plan_date.year, month=plan_date.month, day=plan_date.day, saved=1))

    materialize_recurring_tasks(plan_date,user_id)
    todo = load_todo(plan_date)
    logger.debug("Rendering todo page, toast=%s", session.get("toast"))
    days = [
        date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)
    ]
    quote = MOTIVATIONAL_QUOTES[plan_date.day % len(MOTIVATIONAL_QUOTES)]
    projects = get(
    "projects",
    params={
        "user_id": f"eq.{user_id}",
        "is_archived": "eq.false",
        "order": "created_at.asc",
    },
)

    return render_template_string(
        TODO_TEMPLATE,
        todo=todo,
        plan_date=plan_date,
        year=year,
        month=month,
        days=days,
        calendar=calendar,
        quote=quote,
        TASK_CATEGORIES=TASK_CATEGORIES,
        STATIC_TRAVEL_SUBGROUPS=STATIC_TRAVEL_SUBGROUPS,
        toast = session.pop("toast", None),
        projects=projects,

    )


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
        start = plan_date - timedelta(days=6)
        data = get_weekly_summary(start, plan_date)
        return render_template_string(
            SUMMARY_TEMPLATE,
            view="weekly",
            data=data,
            start=start,
            end=plan_date,
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

    plan_date = date.fromisoformat(data["plan_date"])
    task_id = data["id"]
    # Resolve text from META instead of trusting client
    rows = get(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date}",
            "slot": f"eq.{META_SLOT}",
            "select": "plan",
        },
    )

    meta = json.loads(rows[0]["plan"]) if rows else {}
    task = next(t for t in meta.get("untimed_tasks", []) if t["id"] == task_id)
    text = task["text"]


    raw_q = data["quadrant"].upper()
    if raw_q not in QUADRANT_MAP:
        return ("Invalid quadrant", 400)

    quadrant = QUADRANT_MAP[raw_q]
    # 🔹 Compute next position in the quadrant
    max_pos = get(
    "todo_matrix",
    params={
        "plan_date": f"eq.{plan_date}",
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
        "plan_date": f"eq.{plan_date}",
        "quadrant": f"eq.{quadrant}",
        "task_text": f"eq.{text}",
        "is_deleted": "eq.false",
    },
    )
    if existing:
        return ("Task already exists in the selected quadrant", 400)
    else:
        next_pos = max_pos[0]["position"] + 1 if max_pos else 0
        post(
            "todo_matrix",
            {
                "plan_date": str(plan_date),
                "quadrant": quadrant,
                "task_text": text,
                "is_done": False,
                "is_deleted": False,
                "position": next_pos,
                "category": "General",
                "subcategory": "General",
            },
        )
        remove_untimed_task(plan_date, task_id)
        return ("", 204)

@app.route("/untimed/schedule", methods=["POST"])
@login_required
def schedule_untimed():
    data = request.get_json()

    plan_date = date.fromisoformat(data["plan_date"])
    if plan_date < datetime.now(IST).date():
      return ("Cannot schedule in the past", 400)
    task_id = data["id"]
    # Resolve text from META (never trust client)
    rows = get(
          "daily_slots",
          params={
              "plan_date": f"eq.{plan_date}",
              "slot": f"eq.{META_SLOT}",
              "select": "plan",
          },
      )

    meta = json.loads(rows[0]["plan"]) if rows else {}
    task = next(t for t in meta.get("untimed_tasks", []) if t["id"] == task_id)

    text = data.get("final_text") or task["text"]

    start_slot = int(data["start_slot"])
    slot_count = int(data["slot_count"])

    payload = []
    for i in range(slot_count):
        slot = start_slot + i
        if 1 <= slot <= TOTAL_SLOTS:
            payload.append({
                "plan_date": str(plan_date),
                "slot": slot,
                "plan": text,
                "status": DEFAULT_STATUS,
            })

    post(
        "daily_slots?on_conflict=plan_date,slot",
        payload,
        prefer="resolution=merge-duplicates",
    )

    remove_untimed_task(plan_date, task_id)

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
                "plan_date": f"eq.{plan_date}",
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

    result = autosave_task(
        plan_date=data["plan_date"],
        task_id=data["id"],
        quadrant=data["quadrant"],
        text=data["task_text"],
        is_done=data.get("is_done", False),
    )

    # 🔑 ALWAYS JSON
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


# ==========================================================
# ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    logger.info("Starting Daily Planner – stable + Eisenhower")
    app.run(debug=True)
