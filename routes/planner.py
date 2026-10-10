import calendar
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import re
from flask import Blueprint, jsonify, redirect, render_template, render_template_string, request, session, url_for
from supabase_client import post
import pytz

from config import DEFAULT_STATUS, IST,  QUADRANT_MAP, STATUSES, TASK_CATEGORIES, TOTAL_SLOTS
from utils.user_tz import user_now, user_today
from logger import setup_logger
from services.login_service import login_required
from services.planner_service import  fetch_daily_slots, generate_weekly_insight, get_daily_summary, get_morning_dashboard, get_weekly_summary, group_slots_into_blocks, is_health_day, load_day, load_slots_cached, save_day
from services.recurring_service import materialize_recurring_slots
from services.untimed_service import remove_untimed_task
from supabase_client import get, update
from templates.planner import PLANNER_TEMPLATE
from utils.calender_links import google_calendar_link
from utils.dates import safe_date
from utils.slots import current_slot, slot_label
from utils.smartplanner import parse_smart_sentence

planner_bp = Blueprint("planner", __name__)
logger = setup_logger()
@planner_bp.route("/")
@login_required
def planner():
    # Default landing page = Tasks Bucket. Quick-capture inbox is the
    # first thing the user wants on opening the app — drop a thought,
    # pick when, get back to it. Today's Plan still lives at
    # /summary?view=daily; Eisenhower matrix at /todo.
    return redirect(url_for("quick_bucket.quick_bucket_page"))


@planner_bp.route("/calendar")
@login_required
def planner_calendar():
    """Google Calendar-style planner view (previously the homepage)."""
    return render_template("planner_v2.html")


@planner_bp.route("/planner-legacy", methods=["GET", "POST"])
@login_required
def planner_legacy():
    """Legacy V1 slot-based planner — kept for backward compatibility."""
    user_id = session["user_id"]
    daily_slots = []
    if request.method == "HEAD":
        return "", 200
    today = user_today()
    # ----------------------------------------------------------
# Auto-redirect root load to today (only if no date provided)
# ----------------------------------------------------------
    if request.method == "GET" and not request.args.get("day"):
        today = user_today()
        return redirect(
            url_for(
                "planner.planner",
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
            url_for("planner.planner", year=plan_date.year, month=plan_date.month, day=plan_date.day, saved=1)
        )
    materialize_recurring_slots(plan_date, user_id)
    # ensure_daily_habits_row(user_id, plan_date)
  
    #plans, habits, reflection,untimed_tasks= load_day(plan_date)
    #plans= load_day(plan_date)
    
    #daily_slots = fetch_daily_slots(plan_date)
    #blocks = group_slots_into_blocks(plans)
    daily_slots = fetch_daily_slots(plan_date)
    plans = {
        i: {"plan": "", "status": None}
        for i in range(1, TOTAL_SLOTS + 1)
    }

    for row in daily_slots:
        plans[row["slot"]] = {
            "plan": row.get("plan") or "",
            "status": row.get("status")
        }
    blocks = group_slots_into_blocks(plans)
   # daily_slots = slots
   
    days = [
        date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)
    ]

    reminder_links = {
        slot: google_calendar_link(plan_date, slot, plans[slot]["plan"])
        for slot in range(1, TOTAL_SLOTS + 1)
    }
   
   # health_streak = compute_health_streak(user_id, plan_date)

   # streak_active_today = is_health_day(set(habits))
    selected_date = date(year, month, day)
    today = user_today()
    #✅ ADD THIS HERE
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
     #   habits=habits,
      #  reflection=reflection,
       # habit_list=HABIT_LIST,
        #habit_icons=HABIT_ICONS,
        calendar=calendar,
        #untimed_tasks=untimed_tasks,
        plan_date=plan_date,
        #health_streak=health_streak,
        #streak_active_today=streak_active_today,
        #min_health_habits=MIN_HEALTH_HABITS,
        blocks=blocks,
        today_display=formatted_date,
        prev_month=prev_month,
        next_month=next_month,
        timeline_days=timeline_days,
        selected_date=selected_date,
       # tasks=tasks,
        daily_slots=daily_slots
        
    )
    

@planner_bp.route("/planner-v2")
@login_required
def planner_v2():
    """Alias — redirects to homepage which now serves V2."""
    return redirect(url_for("planner.planner"))

@planner_bp.route("/smart/add", methods=["POST"])
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


@planner_bp.route("/smart/preview", methods=["POST"])
@login_required
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


@planner_bp.route("/slot/toggle-status", methods=["POST"])
@login_required
def toggle_slot_status():
    data = request.get_json()
    user_id = session["user_id"]
    update(
        "daily_slots",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{data['plan_date']}",
            "slot": f"eq.{data['slot']}",
        },
        json={"status": data["status"]},
    )

    return ("", 204)

@planner_bp.route("/untimed/slot-preview", methods=["POST"])
@login_required
def untimed_slot_preview():
    data = request.get_json()

    plan_date = date.fromisoformat(data["plan_date"])
    start_slot = int(data["start_slot"])
    slot_count = int(data["slot_count"])

    preview = []
    user_id = session["user_id"]
    for i in range(slot_count):
        slot = start_slot + i
        if not (1 <= slot <= TOTAL_SLOTS):
            continue

        row = get(
            "daily_slots",
            params={
                "user_id": f"eq.{user_id}",
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
@planner_bp.route("/slot/get")
@login_required
def get_slot():

    plan_date = request.args["date"]
    slot = int(request.args["slot"])
    user_id = session["user_id"]

    row = get(
        "daily_slots",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date}",
            "slot": f"eq.{slot}",
            "select": "plan,start_time,end_time,priority,category"
        },
    )

    return jsonify(row[0] if row else {})
def slot_to_time(slot):

    base_minutes = (slot - 1) * 30

    hours = base_minutes // 60
    minutes = base_minutes % 60

    return f"{hours:02}:{minutes:02}"


def clean_plan_text(text: str) -> str:

    if not text:
        return ""

    text = text.strip()

    # Remove "from X to Y"
    text = re.sub(
        r"\s*from\s+\d{1,2}(:\d{2})?\s*(am|pm)?\s+to\s+\d{1,2}(:\d{2})?\s*(am|pm)?",
        "",
        text,
        flags=re.I,
    )

    # Remove "@9", "@9:30"
    text = re.sub(
        r"\s*@\s*\d{1,2}(:\d{2})?\s*(am|pm)?",
        "",
        text,
        flags=re.I,
    )

    # Remove trailing spaces
    return text.strip()
@planner_bp.route("/slot/update", methods=["POST"])
@login_required
def update_slot():

    data = request.get_json()
    print("UPDATE REQUEST:", data)
    plan_date = data["plan_date"]

    old_start = int(data["old_start"])
    old_end = int(data["old_end"])

    #new_start = int(data["start_slot"])

    text = clean_plan_text((data.get("text")))
    # remove any "from X to Y" or time pattern
    text = re.sub(r"\s*from.*$", "", text, flags=re.IGNORECASE).strip()
    priority = data.get("priority", "Medium")
    category = data.get("category", "Office")

    user_id = session["user_id"]

    # -----------------------------------------------------
    # 1️⃣ Calculate duration safely
    # -----------------------------------------------------
    new_start = int(data["start_slot"])
    new_end = int(data["end_slot"])

    # -----------------------------------------------------
    # 2️⃣ No-op protection
    # -----------------------------------------------------
    if old_start == new_start and old_end == new_end:
     return ("", 204)

    logger.debug(
        "DRAG MOVE user=%s old=%s-%s new=%s-%s",
        user_id, old_start, old_end, new_start, new_end
    )

    # -----------------------------------------------------
    # 3️⃣ Clear original slots
    # -----------------------------------------------------
    for slot in range(old_start, old_end + 1):

        update(
            "daily_slots",
            params={
                "user_id": f"eq.{user_id}",
                "plan_date": f"eq.{plan_date}",
                "slot": f"eq.{slot}",
            },
            json={
                "plan": None,
                "start_time": None,
                "end_time": None,
                "status": DEFAULT_STATUS,
            },
        )

    # -----------------------------------------------------
    # 4️⃣ Build new slots
    # -----------------------------------------------------
    rows = []

    for slot in range(new_start, new_end + 1):

        rows.append({
            "user_id": user_id,
            "plan_date": plan_date,
            "slot": slot,
            "plan": text,   # do NOT store time inside text
            "start_time": slot_to_time(slot),
            "end_time": slot_to_time(slot + 1),
            "priority": priority,
            "category": category,
            "status": DEFAULT_STATUS,
        })

    # -----------------------------------------------------
    # 5️⃣ Single UPSERT (atomic)
    # -----------------------------------------------------
    if rows:

        post(
            "daily_slots?on_conflict=user_id,plan_date,slot",
            rows,
            prefer="resolution=merge-duplicates"
        )

    return ("", 204)

@planner_bp.route("/untimed/promote", methods=["POST"])
@login_required
def promoteuntimed():
    data = request.get_json()

    user_id = session["user_id"]
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
            "user_id": f"eq.{user_id}",
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
            "user_id": f"eq.{user_id}",
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

@planner_bp.route("/untimed/schedule", methods=["POST"])
@login_required
def schedule_untimed():
    data = request.get_json()

    user_id = session["user_id"]
    plan_date = date.fromisoformat(data["plan_date"])
    plan_date_str = plan_date.isoformat()

    if plan_date < user_today():
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
                "user_id": user_id,
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
        # Same conflict target as every other daily_slots upsert: the unique
        # key is (user_id, plan_date, slot), and naming only two of its
        # columns makes PostgREST reject the upsert outright.
        "daily_slots?on_conflict=user_id,plan_date,slot",
        payload,
        prefer="resolution=merge-duplicates",
    )

    # -------------------------------------------------
    # Remove from untimed list
    # -------------------------------------------------
    remove_untimed_task(user_id, plan_date, task_id)

    return ("", 204)

def _load_period_review(user_id: str, period_start) -> dict:
    """Load the structured review row for a given period start (week/month/year).
    The same `weekly_reviews` table backs all three — different date conventions
    (Monday for weekly, 1st of month for monthly, Jan 1 for annual) keep rows
    unique per period.
    """
    blank = {"went_well": "", "didnt_go": "", "one_change": ""}
    try:
        rows = get(
            "weekly_reviews",
            params={
                "user_id": f"eq.{user_id}",
                "week_start": f"eq.{period_start.isoformat()}",
                "select": "went_well,didnt_go,one_change",
            },
        ) or []
        if not rows:
            return blank
        return {
            "went_well":  rows[0].get("went_well")  or "",
            "didnt_go":   rows[0].get("didnt_go")   or "",
            "one_change": rows[0].get("one_change") or "",
        }
    except Exception:
        return blank


def _compute_trend_deltas(data: dict, prev_data: dict) -> dict:
    """Compute week-over-week deltas for the weekly KPI row.

    Returns a dict shape the template can splat into stat-cards:
      { focused_hours: {"diff": +3.0, "dir": "up"},
        completion_rate: {"diff": -8, "dir": "down"},
        habit_days: {"diff": 1, "dir": "up"},
        active_days: {"diff": 0, "dir": "flat"} }
    Each `diff` is rounded sensibly per metric.
    """
    def _delta(cur, prev):
        try:
            d = (cur or 0) - (prev or 0)
        except TypeError:
            return None
        direction = "up" if d > 0 else ("down" if d < 0 else "flat")
        return {"diff": d, "dir": direction}

    cur_active = len(data.get("days") or {})
    prev_active = len(prev_data.get("days") or {})

    out = {
        "focused_hours":   _delta(round(data.get("focused_hours", 0), 1),
                                   round(prev_data.get("focused_hours", 0), 1)),
        "completion_rate": _delta(round(data.get("completion_rate", 0)),
                                   round(prev_data.get("completion_rate", 0))),
        "habit_days":      _delta(data.get("habit_days", 0),
                                   prev_data.get("habit_days", 0)),
        "active_days":     _delta(cur_active, prev_active),
    }
    # Round the focused-hours diff to 1 decimal for clean display.
    if out["focused_hours"]:
        out["focused_hours"]["diff"] = round(out["focused_hours"]["diff"], 1)
    return out


@planner_bp.route("/summary")
@login_required
def summary():
    view = request.args.get("view", "daily")

    # -------------------------
    # ✅ Planner Mode (NEW)
    # -------------------------
    planner_mode = request.args.get("mode", "v2")
    # options: "slots" | "v2" — default to v2

    # -------------------------
    # DAILY DATE PARAM
    # -------------------------
    date_str = request.args.get("date")
    if date_str:
        date_str = date_str.strip()   # ✅ ADD THIS
        plan_date = date.fromisoformat(date_str)
    else:
        plan_date = user_today()

    # =========================
    # MONTHLY VIEW
    # =========================
    if view == "monthly":
        month_str = request.args.get("month")  # YYYY-MM
        if month_str:
            try:
                yr, mo = month_str.split("-")
                start = date(int(yr), int(mo), 1)
            except (ValueError, TypeError):
                start = plan_date.replace(day=1)
        else:
            start = plan_date.replace(day=1)
        # Last day of month: bump to next month, subtract 1 day
        if start.month == 12:
            end = date(start.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(start.year, start.month + 1, 1) - timedelta(days=1)

        data = get_weekly_summary(start, end, planner_mode)
        insights = generate_weekly_insight(data)

        # Prev month for delta
        prev_start = (start - timedelta(days=1)).replace(day=1)
        if prev_start.month == 12:
            prev_end = date(prev_start.year + 1, 1, 1) - timedelta(days=1)
        else:
            prev_end = date(prev_start.year, prev_start.month + 1, 1) - timedelta(days=1)
        try:
            prev_data = get_weekly_summary(prev_start, prev_end, planner_mode)
        except Exception:
            prev_data = None
        deltas = _compute_trend_deltas(data, prev_data) if prev_data else {}

        # Nav helpers
        prev_month = prev_start.strftime("%Y-%m")
        if start.month == 12:
            next_month = f"{start.year + 1}-01"
        else:
            next_month = f"{start.year}-{start.month + 1:02d}"

        review = _load_period_review(session["user_id"], start)

        return render_template(
            "summary.html",
            view="monthly",
            data=data,
            start=start,
            end=end,
            insights=insights,
            deltas=deltas,
            review=review,
            selected_month=start.strftime("%Y-%m"),
            prev_month=prev_month,
            next_month=next_month,
        )

    # =========================
    # ANNUAL / YEAR-IN-REVIEW
    # =========================
    if view == "annual":
        year_str = request.args.get("year")
        try:
            year = int(year_str) if year_str else plan_date.year
        except (ValueError, TypeError):
            year = plan_date.year
        start = date(year, 1, 1)
        end = date(year, 12, 31)

        data = get_weekly_summary(start, end, planner_mode)
        insights = generate_weekly_insight(data)

        # Year-over-year delta
        prev_start = date(year - 1, 1, 1)
        prev_end = date(year - 1, 12, 31)
        try:
            prev_data = get_weekly_summary(prev_start, prev_end, planner_mode)
        except Exception:
            prev_data = None
        deltas = _compute_trend_deltas(data, prev_data) if prev_data else {}

        review = _load_period_review(session["user_id"], start)

        return render_template(
            "summary.html",
            view="annual",
            data=data,
            start=start,
            end=end,
            insights=insights,
            deltas=deltas,
            review=review,
            selected_year=year,
            prev_year=year - 1,
            next_year=year + 1,
        )

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

        # ✅ pass planner_mode
        data = get_weekly_summary(start, end, planner_mode)
        insights = generate_weekly_insight(data)

        # Trend deltas — fetch the previous 7-day window so the template
        # can show "+3h vs last week" beside each KPI. Failure to load
        # last week is non-fatal: the template just won't render deltas.
        prev_start = start - timedelta(days=7)
        prev_end = end - timedelta(days=7)
        try:
            prev_data = get_weekly_summary(prev_start, prev_end, planner_mode)
        except Exception:
            prev_data = None
        deltas = _compute_trend_deltas(data, prev_data) if prev_data else {}

        # Weekly structured review — degrade to empty if the migration
        # hasn't run yet (table missing).
        review = {"went_well": "", "didnt_go": "", "one_change": ""}
        try:
            rev_rows = get(
                "weekly_reviews",
                params={
                    "user_id": f"eq.{session['user_id']}",
                    "week_start": f"eq.{start.isoformat()}",
                    "select": "went_well,didnt_go,one_change",
                },
            ) or []
            if rev_rows:
                review = {
                    "went_well":  rev_rows[0].get("went_well")  or "",
                    "didnt_go":   rev_rows[0].get("didnt_go")   or "",
                    "one_change": rev_rows[0].get("one_change") or "",
                }
        except Exception:
            pass

        # Compute prev/next week for navigation
        prev_week = (start - timedelta(days=7)).strftime("%G-W%V")
        next_week = (start + timedelta(days=7)).strftime("%G-W%V")

        return render_template(
            "summary.html",
            view="weekly",
            data=data,
            start=start,
            end=end,
            insights=insights,
            deltas=deltas,
            review=review,
            selected_week=start.strftime("%G-W%V"),
            prev_week=prev_week,
            next_week=next_week,
        )

    # =========================
    # DAILY VIEW  — morning dashboard
    # =========================
    # THE TWO HALVES OF THIS PAGE DO NOT NEED EACH OTHER, so they do not
    # wait for each other either. The dashboard is a dozen Supabase round
    # trips (now fanned out inside build_dashboard) and the summary is
    # three more; run serially, this page paid for all of them end to
    # end. Reported 2026-08-30: "clicking todays plan is very slow."
    #
    # get_daily_summary stays on THIS thread on purpose: it reads
    # session["user_id"], and a worker thread has no request context.
    user_id = session["user_id"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        dash_future = pool.submit(get_morning_dashboard, plan_date, user_id)
        data = get_daily_summary(plan_date, planner_mode)
        dashboard = dash_future.result()

    # Today flag (used by template to show a "TODAY" pill)
    is_today = (plan_date == user_today())

    # Compute prev/next date for navigation
    prev_date = (plan_date - timedelta(days=1)).isoformat()
    next_date = (plan_date + timedelta(days=1)).isoformat()

    return render_template(
        "summary.html",
        view="daily",
        data=data,
        dashboard=dashboard,
        is_today=is_today,
        date=plan_date,
        prev_date=prev_date,
        next_date=next_date,
        task_categories=TASK_CATEGORIES,
    )
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

def load_slot_timeline(plan_date):
    user_id = session["user_id"]
    return get(
        "daily_slots",
        params={
            "user_id": f"eq.{user_id}",
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

def _to_minutes(t):
    """Convert "HH:MM" or "HH:MM:SS" to total minutes for reliable comparison."""
    parts = str(t).split(":")
    return int(parts[0]) * 60 + int(parts[1])


def get_conflicts(user_id, plan_date, start_time, end_time, exclude_id=None):
    existing = get(
        "daily_events",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date}",
            "is_deleted": "eq.false"
        }
    ) or []

    new_start = _to_minutes(start_time)
    new_end = _to_minutes(end_time)

    conflicts = []

    for e in existing:
        if exclude_id and str(e["id"]) == str(exclude_id):
            continue

        e_start = _to_minutes(e["start_time"])
        e_end = _to_minutes(e["end_time"])

        # Two events overlap only if one starts BEFORE the other ends (strict <)
        # Adjacent events (1:00-1:15 and 1:15-2:00) are NOT conflicts
        if new_start < e_end and new_end > e_start:
            conflicts.append({
                "start_time": str(e["start_time"]),
                "end_time": str(e["end_time"]),
                "title": e["title"]
            })

    return conflicts

def build_google_datetime(plan_date, time_str):
    tz = pytz.timezone("Asia/Kolkata")

    # 🔥 Support both HH:MM and HH:MM:SS
    try:
        dt = datetime.strptime(f"{plan_date} {time_str}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        dt = datetime.strptime(f"{plan_date} {time_str}", "%Y-%m-%d %H:%M")

    dt = tz.localize(dt)
    return dt.isoformat()


# ──────────────────────────────────────────────────────────────
# DAILY REFLECTION — write to daily_meta.reflection
# ──────────────────────────────────────────────────────────────
@planner_bp.route("/api/v2/weekly-review", methods=["POST"])
@login_required
def save_weekly_review():
    """Upsert a weekly review row.

    Body: { "week_start": "YYYY-MM-DD",
            "went_well": "...", "didnt_go": "...", "one_change": "..." }

    Any field omitted is preserved (partial save). Empty strings are
    stored as NULL so analytics distinguishes "skipped" from "answered".
    """
    user_id = session["user_id"]
    data = request.get_json() or {}
    week_start = (data.get("week_start") or "").strip()
    if not week_start:
        return jsonify({"error": "week_start required"}), 400
    try:
        date.fromisoformat(week_start)
    except ValueError:
        return jsonify({"error": "Invalid week_start"}), 400

    payload: dict = {}
    for k in ("went_well", "didnt_go", "one_change"):
        if k in data:
            v = (data.get(k) or "").strip()
            payload[k] = v if v else None

    if not payload:
        return jsonify({"success": True, "noop": True})

    # supabase_client.update sends raw JSON, so postgres functions like
    # NOW() can't be passed as strings — generate the timestamp here.
    payload["updated_at"] = datetime.utcnow().isoformat() + "Z"

    existing = get(
        "weekly_reviews",
        {"user_id": f"eq.{user_id}", "week_start": f"eq.{week_start}", "select": "user_id"},
    ) or []

    if existing:
        update(
            "weekly_reviews",
            params={"user_id": f"eq.{user_id}", "week_start": f"eq.{week_start}"},
            json=payload,
        )
    else:
        post(
            "weekly_reviews",
            {"user_id": user_id, "week_start": week_start, **payload},
            prefer="return=minimal",
        )
    return jsonify({"success": True})


@planner_bp.route("/api/v2/daily-gratitude", methods=["POST"])
@login_required
def save_daily_gratitude():
    """Upsert today's gratitude entry (separate from reflection).
    Body: { "plan_date": "YYYY-MM-DD", "gratitude": "..." }
    Empty string clears it."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    plan_date = (data.get("plan_date") or "").strip()
    gratitude = (data.get("gratitude") or "").strip() or None
    if not plan_date:
        return jsonify({"error": "plan_date required"}), 400
    try:
        date.fromisoformat(plan_date)
    except ValueError:
        return jsonify({"error": "Invalid plan_date"}), 400

    existing = get(
        "daily_meta",
        {"user_id": f"eq.{user_id}", "plan_date": f"eq.{plan_date}"},
    ) or []
    if existing:
        update(
            "daily_meta",
            params={"user_id": f"eq.{user_id}", "plan_date": f"eq.{plan_date}"},
            json={"gratitude": gratitude},
        )
    else:
        post(
            "daily_meta",
            {"user_id": user_id, "plan_date": plan_date, "gratitude": gratitude},
            prefer="return=minimal",
        )
    return jsonify({"success": True})


@planner_bp.route("/api/v2/daily-intent", methods=["POST"])
@login_required
def save_daily_intent():
    """Set or clear the user's "One Big Thing" for a date.

    Body: { "plan_date": "YYYY-MM-DD", "intent": "...", "done": false? }

    `intent` may be empty string to clear. `done` is optional — when
    omitted, existing done state is preserved (so a text edit doesn't
    accidentally re-open a completed intent).
    """
    user_id = session["user_id"]
    data = request.get_json() or {}
    plan_date = (data.get("plan_date") or "").strip()
    intent = (data.get("intent") or "").strip() or None

    if not plan_date:
        return jsonify({"error": "plan_date required"}), 400
    try:
        date.fromisoformat(plan_date)
    except ValueError:
        return jsonify({"error": "Invalid plan_date"}), 400

    payload = {"daily_intent": intent}
    if "done" in data:
        payload["daily_intent_done"] = bool(data.get("done"))
    elif intent is None:
        # Clearing the intent → reset done state too
        payload["daily_intent_done"] = False

    existing = get(
        "daily_meta",
        {"user_id": f"eq.{user_id}", "plan_date": f"eq.{plan_date}"},
    ) or []

    if existing:
        update(
            "daily_meta",
            params={"user_id": f"eq.{user_id}", "plan_date": f"eq.{plan_date}"},
            json=payload,
        )
    else:
        post(
            "daily_meta",
            {"user_id": user_id, "plan_date": plan_date, **payload},
            prefer="return=minimal",
        )

    return jsonify({"success": True})


@planner_bp.route("/api/v2/daily-intent/toggle", methods=["POST"])
@login_required
def toggle_daily_intent_done():
    """Flip the daily_intent_done flag for a date."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    plan_date = (data.get("plan_date") or "").strip()
    if not plan_date:
        return jsonify({"error": "plan_date required"}), 400

    rows = get(
        "daily_meta",
        {"user_id": f"eq.{user_id}", "plan_date": f"eq.{plan_date}",
         "select": "daily_intent_done"},
    ) or []
    cur = bool(rows[0].get("daily_intent_done")) if rows else False
    new_val = not cur

    if rows:
        update(
            "daily_meta",
            params={"user_id": f"eq.{user_id}", "plan_date": f"eq.{plan_date}"},
            json={"daily_intent_done": new_val},
        )
    else:
        post(
            "daily_meta",
            {"user_id": user_id, "plan_date": plan_date, "daily_intent_done": new_val},
            prefer="return=minimal",
        )

    return jsonify({"success": True, "done": new_val})


@planner_bp.route("/api/v2/daily-reflection", methods=["POST"])
@login_required
def save_daily_reflection():
    """Upsert the user's reflection for a given date.
    daily_meta has UNIQUE (user_id, plan_date); we check-then-update
    instead of relying on PostgREST's resolution=merge-duplicates
    (which needs an explicit on_conflict= query arg we don't pass)."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    plan_date = (data.get("plan_date") or "").strip()
    reflection = data.get("reflection") or ""

    if not plan_date:
        return jsonify({"error": "plan_date required"}), 400
    try:
        date.fromisoformat(plan_date)
    except ValueError:
        return jsonify({"error": "Invalid plan_date"}), 400

    existing = get(
        "daily_meta",
        {"user_id": f"eq.{user_id}", "plan_date": f"eq.{plan_date}"},
    ) or []

    if existing:
        update(
            "daily_meta",
            params={"user_id": f"eq.{user_id}", "plan_date": f"eq.{plan_date}"},
            json={"reflection": reflection},
        )
    else:
        post(
            "daily_meta",
            {"user_id": user_id, "plan_date": plan_date, "reflection": reflection},
            prefer="return=minimal",
        )

    return jsonify({"success": True})
