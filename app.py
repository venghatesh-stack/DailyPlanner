## Eisenhower Matrix + Daily Planner integrated. Calender control working
from flask import Flask, request, redirect, url_for, render_template_string, session
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
from services.planner_service import load_day, save_day, get_daily_summary, get_weekly_summary
from services.login_service import login_required
from services.eisenhower_service import (
    load_todo,
    save_todo,
    copy_open_tasks_from_previous_day,  
    enable_travel_mode,
)
from services.recurring_service import materialize_recurring_tasks
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
app = Flask(__name__)
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
    if request.method == "HEAD":
        return "", 200
    today = datetime.now(IST).date()

    if request.method == "POST":
        year = int(request.form["year"])
        month = int(request.form["month"])
        day = int(request.form["day"])
    else:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        day = int(request.args.get("day", today.day))

    plan_date = safe_date(year, month, day)

    if request.method == "POST":
        logger.info(f"Saving planner for date={plan_date}")
        save_day(plan_date, request.form)
        return redirect(
            url_for("planner", year=plan_date.year, month=plan_date.month, day=plan_date.day, saved=1)
        )

    plans, habits, reflection,untimed_tasks = load_day(plan_date)

    days = [
        date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)
    ]

    reminder_links = {
        slot: google_calendar_link(plan_date, slot, plans[slot]["plan"])
        for slot in range(1, TOTAL_SLOTS + 1)
    }

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
    )


# ==========================================================
# ROUTES – EISENHOWER MATRIX
# ==========================================================
@app.route("/todo", methods=["GET", "POST"])
@login_required
def todo():
    if request.method == "HEAD":
        return "", 200
    today = datetime.now(IST).date()

    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    day = int(request.args.get("day", today.day))
    plan_date = safe_date(year, month, day)

    if request.method == "POST":
        save_todo(plan_date, request.form)
        return redirect(url_for("todo", year=plan_date.year, month=plan_date.month, day=plan_date.day, saved=1))

    materialize_recurring_tasks(plan_date)
    todo = load_todo(plan_date)

    days = [
        date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)
    ]
    quote = MOTIVATIONAL_QUOTES[plan_date.day % len(MOTIVATIONAL_QUOTES)]
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
    today = datetime.now(IST).date()
    view = request.args.get("view", "daily")

    if view == "weekly":
        start = today - timedelta(days=6)
        data = get_weekly_summary(start, today)
        return render_template_string(
            SUMMARY_TEMPLATE,
            view="weekly",
            data=data,
            start=start,
            end=today,
        )

    # Default: daily
    data = get_daily_summary(today)
    return render_template_string(
        SUMMARY_TEMPLATE,
        view="daily",
        data=data,
        date=today,
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

@app.route("/favicon.ico")
def favicon():
    return "", 204


# ==========================================================
# ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    logger.info("Starting Daily Planner – stable + Eisenhower")
    app.run(debug=True)