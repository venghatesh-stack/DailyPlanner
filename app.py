## Eisenhower Matrix + Daily Planner integrated. Calender control working
from flask import Flask, request, redirect, url_for, render_template_string, session
from functools import wraps
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import calendar
import urllib.parse
import json
import re
from supabase_client import get, post, delete, update
from logger import setup_logger

# ==========================================================
# APP SETUP
# ==========================================================
IST = ZoneInfo("Asia/Kolkata")
app = Flask(__name__)
logger = setup_logger()
# ==========================================================
# Log in codestarts here
# ==========================================================

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "changeme")


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


# ==========================================================
# Log in code ends here
# ==========================================================

# ==========================================================
# CONSTANTS
# ==========================================================
TOTAL_SLOTS = 48
META_SLOT = 0
DEFAULT_STATUS = "Nothing Planned"

STATUSES = ["Nothing Planned", "Yet to Start", "In Progress", "Closed", "Deferred"]

HABIT_LIST = [
    "Walking",
    "Water",
    "No Shopping",
    "No TimeWastage",
    "8 hrs sleep",
    "Daily prayers",
]

HABIT_ICONS = {
    "Walking": "🚶",
    "Water": "💧",
    "No Shopping": "🛑🛍️",
    "No TimeWastage": "⏳",
    "8 hrs sleep": "😴",
    "Daily prayers": "🙏",
}
MOTIVATIONAL_QUOTES = [
    {"icon": "🎯", "text": "Focus on what matters, not what screams loudest."},
    {"icon": "⏳", "text": "Urgent is not always important."},
    {"icon": "🧠", "text": "Clarity comes from prioritization."},
    {"icon": "📌", "text": "Do the right thing, not everything."},
    {"icon": "📅", "text": "What you schedule gets done."},
    {"icon": "🌱", "text": "Small progress each day adds up."},
    {"icon": "✂️", "text": "Decide what not to do."},
    {"icon": "🧭", "text": "Your priorities shape your future."},
    {"icon": "⚡", "text": "Action beats intention."},
    {"icon": "☀️", "text": "Important tasks deserve calm attention."},
]

### Travel mode Code Changes ###
TASK_CATEGORIES = {
    "Office": "🏢",
    "Personal": "👤",
    "Family": "👨‍👩‍👧",
    "Travel": "✈️",
    "Health": "🩺",
    "Finance": "💰",
    "General": "📁",
}


STATIC_TRAVEL_SUBGROUPS = {
    "Utilities": "⚙️",
    "Security": "🔐",
    "Vehicle": "🚗",
    "Documents": "📄",
    "Gadgets": "🔌",
    "Personal": "🧳",
}

### Travel mode Code Changes ###
### Category, Sub Category Changes start here ###

TRAVEL_MODE_TASKS = [
    # =========================
    # Utilities (Home shutdown)
    # =========================
    ("do", "Geyser switched off", "Utilities"),
    ("do", "Toilet valves closed", "Utilities"),
    ("do", "Fridge switched off", "Utilities"),
    ("do", "No food left inside fridge", "Utilities"),
    ("do", "Fridge door kept open", "Utilities"),
    ("do", "Washing machine switched off", "Utilities"),
    ("do", "Dishwasher switched off", "Utilities"),
    ("do", "Iron box switched off", "Utilities"),
    ("do", "AquaGuard valve closed & switched off", "Utilities"),
    ("do", "Router switched off", "Utilities"),
    ("do", "Inverter switched off", "Utilities"),
    ("do", "Main power switched off (Bengaluru)", "Utilities"),
    ("do", "All lights switched off", "Utilities"),
    ("do", "All vessels washed", "Utilities"),
    # =========================
    # Security & Housekeeping
    # =========================
    ("do", "Blankets and pillows kept inside", "Security"),
    ("do", "All doors closed", "Security"),
    ("do", "Door locked", "Security"),
    ("do", "Pooja room check", "Security"),
    ("do", "Bengaluru and Chennai house keys taken", "Security"),
    # =========================
    # Vehicle
    # =========================
    ("do", "Petrol and tyre air pressure checked", "Vehicle"),
    ("do", "Car wiper checked", "Vehicle"),
    # =========================
    # Gadgets & Electronics
    # =========================
    ("do", "Mobile phones (2)", "Gadgets"),
    ("do", "Watches (2)", "Gadgets"),
    ("do", "Power bank", "Gadgets"),
    ("do", "AirPods (2)", "Gadgets"),
    ("do", "Galaxy tablet", "Gadgets"),
    ("do", "iPad", "Gadgets"),
    ("do", "HP laptop", "Gadgets"),
    ("do", "Office laptop", "Gadgets"),
    ("do", "Laptop charger", "Gadgets"),
    ("do", "Floor robo cleaner packed", "Gadgets"),
    # =========================
    # Documents & Essentials
    # =========================
    ("do", "Purse", "Documents"),
    ("do", "Travel pouch", "Documents"),
    ("do", "Tickets (if applicable)", "Documents"),
    ("do", "ID card", "Documents"),
    # =========================
    # Personal & Misc
    # =========================
    ("do", "Clothes packed", "Personal"),
    ("do", "Homeopathy tablets", "Personal"),
    ("do", "Any vessels, groceries, or vegetables to be taken", "Personal"),
]

# ============================
# PLANNER PARSING CONFIG
# ============================

PRIORITY_RANK = {
    "Critical": 1,
    "High": 2,
    "Medium": 3,
    "Low": 4,
}

DEFAULT_PRIORITY = "Medium"
DEFAULT_CATEGORY = "Office"
QUADRANT_MAP = {
    "Q1": "do",
    "Q2": "schedule",
    "Q3": "delegate",
    "Q4": "eliminate",
}
WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
### Category, Subcategory code ends here ###


# ==========================================================
# HELPERS
# ==========================================================
def slot_label(slot: int) -> str:
    start = datetime.min + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return f"{start.strftime('%I:%M %p')} – {end.strftime('%I:%M %p')}"


def slot_start_end(plan_date: date, slot: int):
    start = datetime.combine(plan_date, datetime.min.time(), tzinfo=IST) + timedelta(
        minutes=(slot - 1) * 30
    )
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
        "trp": "false",
    }
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(
        params
    )
    


def slots_to_timerange(slots):
    slots = sorted(slots)
    start_min = (slots[0] - 1) * 30
    end_min = slots[-1] * 30

    start = datetime.min + timedelta(minutes=start_min)
    end = datetime.min + timedelta(minutes=end_min)

    return f"{start.strftime('%I:%M %p').lstrip('0')}–{end.strftime('%I:%M %p').lstrip('0')}"



def get_daily_summary(plan_date):
    rows = get(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date}",
            "slot": f"neq.{META_SLOT}",
            "select": "slot,plan,priority,tags",
        },
    ) or []

    # Phase 1: group slots by task + tags
    grouped = defaultdict(lambda: {
        "slots": [],
        "priority": "Medium",
        "tags": []
    })

    for r in rows:
        if not r.get("plan"):
            continue

        tags = r.get("tags") or ["untagged"]
        key = (r["plan"], tuple(sorted(tags)))

        grouped[key]["slots"].append(r["slot"])
        grouped[key]["priority"] = r.get("priority") or "Medium"
        grouped[key]["tags"] = tags

    # Phase 2: build summary (sorted by start time)
    summary = defaultdict(lambda: defaultdict(list))

    for (task, _), data in sorted(
        grouped.items(),
        key=lambda x: min(x[1]["slots"])
    ):
        time_range = slots_to_timerange(data["slots"])
        label = f"{task}@{time_range}"

        for tag in data["tags"]:
            summary[tag][data["priority"]].append(label)

    return summary
# NOTE:
# Weekly summary is intentionally compact (day → tasks with time).
# Tag and priority aggregation is handled only in daily summary to avoid noise.

def get_weekly_summary(start_date, end_date):
    rows = get(
        "daily_slots",
        params={
            "plan_date": f"gte.{start_date}&lte.{end_date}",
            "slot": f"neq.{META_SLOT}",
            "select": "plan_date,slot,plan,priority,tags",
        },
    ) or []

    grouped = defaultdict(lambda: defaultdict(lambda: {"slots": [], "priority": "Medium"}))

    for r in rows:
        if not r.get("plan"):
            continue

        day = r["plan_date"]
        key = (r["plan"], tuple(sorted(r.get("tags") or ["untagged"])))

        grouped[day][key]["slots"].append(r["slot"])
        grouped[day][key]["priority"] = r.get("priority") or "Medium"

    summary = defaultdict(list)

    # ✅ FIXED indentation + sorted by time
    for day in sorted(grouped.keys()):
        tasks = grouped[day]
        for (task, _), data in sorted(
            tasks.items(),
            key=lambda x: min(x[1]["slots"])
        ):
            time_range = slots_to_timerange(data["slots"])
            summary[day].append(f"{task}@{time_range}")

    return dict(summary)


# ==========================================================
# DATA ACCESS – DAILY PLANNER
# ==========================================================

def load_day(plan_date, tag=None):
    plans = {
        i: {"plan": "", "status": DEFAULT_STATUS} for i in range(1, TOTAL_SLOTS + 1)
    }
    habits = set()
    reflection = ""
    untimed_tasks = []  

    rows = (
        get(
            "daily_slots",
            params={
                "plan_date": f"eq.{plan_date}",
                "select": "slot,plan,status,tags",
            },
        )
        or []
    )

    for r in rows:
        if r["slot"] == META_SLOT:
            try:
                meta = json.loads(r.get("plan") or "{}")
                habits = set(meta.get("habits", []))
                reflection = meta.get("reflection", "")
                raw = meta.get("untimed_tasks", [])
                untimed_tasks = []

                for t in raw:
                    if isinstance(t, str):
                        untimed_tasks.append({
                            "id": f"legacy_{hash(t)}",
                            "text": t
                        })
                    else:
                        untimed_tasks.append(t)

            except Exception:
                pass
            continue

        row_tags = []
        if r.get("tags"):
          if isinstance(r["tags"], list):
              row_tags = r["tags"]
          elif isinstance(r["tags"], str):
              try:
                  row_tags = json.loads(r["tags"])
              except Exception:
                  row_tags = []


        if tag and tag not in row_tags:
            continue

        plans[r["slot"]] = {
            "plan": r.get("plan") or "",
            "status": r.get("status") or DEFAULT_STATUS,
        }

    return plans, habits, reflection,untimed_tasks





def save_day(plan_date, form):
    payload = []
    auto_untimed = []

    # Track slots already filled by smart parsing
    smart_block = form.get("smart_plan", "").strip()

    # -------------------------------------------------
    # SMART MULTI-LINE INPUT (GLOBAL)
    # -------------------------------------------------
    if smart_block:
        for line in smart_block.splitlines():
            line = line.strip()
            if not line:
                continue
            has_time = re.search(r"(@\s*\d|\bfrom\s+\d)", line, re.I)
            quadrant_match = re.search(r"\b(Q[1-4])\b", line, re.I)

            # -------------------------------------------------
            # CASE 1: No time BUT Q1–Q4 → Eisenhower-only
            # -------------------------------------------------
            if not has_time and quadrant_match:
                try:
                    # Reuse parser by injecting a dummy time
                    parsed = parse_planner_input(
                        line + " @12am",
                        plan_date
                    )

                    quadrant = parsed["quadrant"]

                    existing = get(
                        "todo_matrix",
                        params={
                            "plan_date": f"eq.{plan_date}",
                            "quadrant": f"eq.{quadrant}",
                            "task_text": f"eq.{parsed['title']}",
                            "is_deleted": "eq.false",
                        },
                    )

                    if not existing:
                        post(
                            "todo_matrix",
                            {
                                "plan_date": str(plan_date),
                                "quadrant": quadrant,
                                "task_text": parsed["title"],
                                "is_done": False,
                                "is_deleted": False,
                                "position": 0,
                                "category": parsed["category"],
                                "subcategory": "General",
                            },
                        )

                    logger.info(f"Eisenhower-only task added: {line}")
                    continue

                except Exception as e:
                    logger.error(f"Eisenhower-only parse failed: {line} → {e}")
                    continue

            # -------------------------------------------------
            # CASE 2: No time and no quadrant → skip
            # -------------------------------------------------
            # CASE 2: No time and no quadrant → append to untimed tasks
            if not has_time and not quadrant_match:
                auto_untimed.append({
                    "id": f"u_{int(datetime.now().timestamp() * 1000)}",
                    "text": line
                })

                logger.info(f"Smart planner → untimed task: {line}")
                continue
            
            try:
                parsed = parse_planner_input(line, plan_date)
                task_date = parsed["date"]
                # --------------------------------------------
                # AUTO-INSERT INTO EISENHOWER MATRIX (Q1–Q4)
                # --------------------------------------------
                if parsed.get("quadrant"):
                    quadrant = parsed["quadrant"]

                    task_time = parsed["start"].strftime("%H:%M")
                   
                    existing = get(
                        "todo_matrix",
                        params={
                            "plan_date": f"eq.{task_date}",
                            "quadrant": f"eq.{quadrant}",
                            "task_text": f"eq.{parsed['title']}",
                            "task_time": f"eq.{task_time}",  # 👈 prevent duplicates
                            "is_deleted": "eq.false",
                        },
                    )

                    if not existing:
                        post(
                            "todo_matrix",
                            {
                                "plan_date": str(task_date),
                                "quadrant": quadrant,
                                "task_text": parsed["title"],
                                "task_date": str(task_date),   # ✅ retain date
                                "task_time": task_time,        # ✅ retain time
                                "is_done": False,
                                "is_deleted": False,
                                "position": 0,
                                "category": parsed["category"],
                                "subcategory": "General",
                            },
                        )
              

                slots = generate_half_hour_slots(parsed)

                affected_slots = set()

                for s in slots:
                    start_h, start_m = map(int, s["time"].split(" - ")[0].split(":"))
                    target_slot = (start_h * 60 + start_m) // 30 + 1
                    if 1 <= target_slot <= TOTAL_SLOTS:
                        affected_slots.add(target_slot)

                # Clear existing tasks in affected slots
                if affected_slots:
                    delete(
                        "daily_slots",
                        params={
                            "plan_date": f"eq.{task_date}",
                            "slot": f"in.({','.join(str(s) for s in affected_slots if s != META_SLOT)})",
                        },
                    )

                # Re-insert smart slots
                for s in slots:
                    start_h, start_m = map(int, s["time"].split(" - ")[0].split(":"))
                    target_slot = (start_h * 60 + start_m) // 30 + 1
                    if 1 <= target_slot <= TOTAL_SLOTS:
                        payload.append(
                            {
                                "plan_date": str(task_date),
                                "slot": target_slot,
                                "plan": s["task"],
                                "status": DEFAULT_STATUS,
                                "priority": s["priority"],
                                "category": s["category"],
                                "tags": s["tags"],
                            }
                        )
            except Exception as e:
                logger.error(
                    f"Smart planner parse failed for line '{line}': {e}"
                )

    # -------------------------------------------------
    # MANUAL ENTRY (only if smart planner not used)
    # -------------------------------------------------
    if not smart_block:
        for slot in range(1, TOTAL_SLOTS + 1):
            plan = form.get(f"plan_{slot}", "").strip()
            status = form.get(f"status_{slot}", DEFAULT_STATUS)

            if not plan:
                continue

            payload.append(
                {
                    "plan_date": str(plan_date),
                    "slot": slot,
                    "plan": plan,
                    "status": status,
                }
            )

    # ---- SAVE META (habits + reflection) ----
    # ---- LOAD EXISTING META (for safe merge) ----
    existing_meta = {}
    existing_rows = get(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date}",
            "slot": f"eq.{META_SLOT}",
            "select": "plan",
        },
    )

    if existing_rows:
        try:
            existing_meta = json.loads(existing_rows[0].get("plan") or "{}")
        except Exception:
            existing_meta = {}

    untimed_raw = form.get("untimed_tasks", "")
    untimed_raw = untimed_raw.strip() if untimed_raw is not None else ""
    new_untimed = []

    if untimed_raw:
        new_untimed = [
            {
                "id": f"u_{int(datetime.now().timestamp() * 1000)}_{i}",
                "text": line.strip()
            }
            for i, line in enumerate(untimed_raw.splitlines())
            if line.strip()
        ]


    raw_existing = existing_meta.get("untimed_tasks", [])
    existing_untimed = []

    for t in raw_existing:
        if isinstance(t, str):
            existing_untimed.append({
                "id": f"legacy_{hash(t)}",
                "text": t
            })
        else:
            existing_untimed.append(t)

    merged = {}
    for t in existing_untimed + auto_untimed + new_untimed:
        merged[t["id"]] = t


    meta = {
        "habits": form.getlist("habits"),
        "reflection": form.get("reflection", "").strip(),
        "untimed_tasks": list(merged.values()),
    }

    meta_payload = {
      "plan_date": str(plan_date),
      "slot": META_SLOT,
      "plan": json.dumps(meta),
      "status": DEFAULT_STATUS,
    }

    # -------------------------------------------------
    # FINAL WRITE (REQUIRED)
    # -------------------------------------------------
    ALLOWED_DAILY_COLUMNS = {
        "plan_date",
        "slot",
        "plan",
        "status",
        "priority",
        "category",
        "tags",
    }

    clean_payload = [
        {k: v for k, v in row.items() if k in ALLOWED_DAILY_COLUMNS}
        for row in payload
        if row.get("slot") != META_SLOT   # ✅ EXCLUDE META
    ]

    if clean_payload:
        post(
            "daily_slots?on_conflict=plan_date,slot",
            clean_payload,
            prefer="resolution=merge-duplicates",
        )

    post(
        "daily_slots?on_conflict=plan_date,slot",
        meta_payload,
        prefer="resolution=merge-duplicates",
    )

# ==========================================================
# DATA ACCESS – EISENHOWER
# ==========================================================
def load_todo(plan_date):
    # ----------------------------
    # Load today's todo items
    # ----------------------------
    rows = (
        get(
            "todo_matrix",
            params={
                "plan_date": f"eq.{plan_date}",
                "is_deleted": "eq.false",
                "select": (
                    "id,quadrant,task_text,is_done,position,"
                    "task_date,task_time,recurring_id,"
                    "category,subcategory"
                ),
            },
        )
        or []
    )

    # ----------------------------
    # Load recurrence metadata
    # ----------------------------
    recurring_rows = (
        get(
            "recurring_tasks",
            params={"is_active": "eq.true", "select": "id,recurrence"},
        )
        or []
    )

    recurring_map = {r["id"]: r.get("recurrence") for r in recurring_rows}

    # ----------------------------
    # Build quadrant buckets
    # ----------------------------
    data = {"do": [], "schedule": [], "delegate": [], "eliminate": []}

    for r in rows:
        data[r["quadrant"]].append(
            {
                "id": r["id"],
                "text": r["task_text"],
                "done": bool(r.get("is_done")),
                "task_date": r.get("task_date"),
                "task_time": r.get("task_time"),
                "recurring": bool(r.get("recurring_id")),
                "recurrence": recurring_map.get(r.get("recurring_id")),
                "category": r.get("category") or "General",
                "subcategory": r.get("subcategory") or "General",
            }
        )

    # ----------------------------
    # Sort within each quadrant
    # ----------------------------
    for q in data:
        data[q].sort(
        key=lambda t: (
                t["task_date"] is None,
                t["task_date"] or "",
                t["task_time"] is None,
                t["task_time"] or "",
            )
        )

    ### Category, Sub Category Changes start here ###

    grouped = {}

    for q in data:
        grouped[q] = {}
        for t in data[q]:
            cat = t["category"]
            sub = t["subcategory"]
            grouped[q].setdefault(cat, {}).setdefault(sub, []).append(t)

    return grouped


### Category, Subcategory code ends here ###


def save_todo(plan_date, form):
    logger.info("Saving Eisenhower matrix (batched)")

    # -----------------------------------
    # Load existing (non-deleted) IDs
    # -----------------------------------
    existing_rows = (
        get(
            "todo_matrix",
            params={
                "plan_date": f"eq.{plan_date}",
                "is_deleted": "eq.false",
                "select": "id, recurring_id",
            },
        )
        or []
    )

    existing_recurring_map = {
        str(r["id"]): r.get("recurring_id") for r in existing_rows
    }

    existing_ids = {str(r["id"]) for r in existing_rows}
    seen_ids = set()

    updates = []
    inserts = []

    # -----------------------------------
    # Process quadrants
    # -----------------------------------
    for quadrant in ["do", "schedule", "delegate", "eliminate"]:
        texts = form.getlist(f"{quadrant}[]")
        dates = form.getlist(f"{quadrant}_date[]")
        times = form.getlist(f"{quadrant}_time[]")
        ids = form.getlist(f"{quadrant}_id[]")
        deleted_flags = form.getlist(f"{quadrant}_deleted[]")


        # Build done_state
        done_state = {}
        prefix = f"{quadrant}_done_state["

        for key, values in form.to_dict(flat=False).items():
            if key.startswith(prefix) and key.endswith("]"):
                task_id = key[len(prefix) : -1]
                done_state[task_id] = values

        for idx, text in enumerate(texts):
            if idx < len(deleted_flags) and deleted_flags[idx] == "1":
              # Explicitly deleted by user → skip saving
              continue

            text = text.strip()
            if not text:
                continue

            if idx >= len(ids):
                continue

            task_id = str(ids[idx])

            task_date = dates[idx] if idx < len(dates) and dates[idx] else None
            task_time = times[idx] if idx < len(times) and times[idx] else None
            is_done = "1" in done_state.get(task_id, [])

            base_payload = {
                "quadrant": quadrant,
                "task_text": text,
                "task_date": task_date,
                "task_time": task_time,
                "is_done": is_done,
                "position": idx,
                "is_deleted": False,
            }
            ### Category, Sub Category Changes start here ###
            ### Category, Sub Category Changes start here ###
            ### Category, Sub Category Changes start here ###
            categories = form.getlist(f"{quadrant}_category[]")
            subcategories = form.getlist(f"{quadrant}_subcategory[]")
            ### Category, Subcategory code ends here ###

            base_payload.update(
                {
                    "category": categories[idx] if idx < len(categories) else "General",
                    "subcategory": subcategories[idx]
                    if idx < len(subcategories)
                    else "General",
                }
            )

            ### Category, Subcategory code ends here ###

            ### Category, Subcategory code ends here ###

            if task_id in existing_ids:
                payload = {
                    "id": task_id,
                    "plan_date": str(plan_date),
                    "recurring_id": existing_recurring_map.get(task_id),
                    **base_payload,
                }
                seen_ids.add(task_id)
                updates.append(payload)
            else:
                payload = {"plan_date": str(plan_date), **base_payload}

                inserts.append(payload)

    # -----------------------------------
    # BULK UPSERT existing rows
    # -----------------------------------
    if updates:
        post(
            "todo_matrix?on_conflict=id", updates, prefer="resolution=merge-duplicates"
        )

    # -----------------------------------
    # BULK INSERT new rows
    # -----------------------------------
    if inserts:
        post("todo_matrix", inserts)

    # -----------------------------------
    # BULK SOFT DELETE removed rows
    # -----------------------------------
    form_ids = {
        task_id
        for quadrant in ["do", "schedule", "delegate", "eliminate"]
        for task_id in form.getlist(f"{quadrant}_id[]")
    }

    existing = {r["id"]: r.get("recurring_id") for r in existing_rows}

    removed_ids = {
        tid
        for tid, rid in existing.items()
        if tid not in seen_ids and tid not in form_ids and rid is None  # 👈 IMPORTANT
    }

    if removed_ids:
        update(
            "todo_matrix",
            params={"id": f"in.({','.join(removed_ids)})"},
            json={"is_deleted": True},
        )

    logger.info(
        "Eisenhower save complete: %d updates, %d inserts, %d deletions",
        len(updates),
        len(inserts),
        len(removed_ids),
    )


def materialize_recurring_tasks(plan_date):
    """
    Create daily todo_matrix rows for recurring tasks
    (idempotent – safe to run multiple times)
    """

    rules = (
        get(
            "recurring_tasks",
            params={
                "is_active": "eq.true",
                "start_date": f"lte.{plan_date}",
                "select": "id,quadrant,task_text,category,subcategory,recurrence,days_of_week,day_of_month,end_date",
            },
        )
        or []
    )

    if not rules:
        return
    existing = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{plan_date}",
            "is_deleted": "eq.false",  # 👈 REQUIRED
            "select": "recurring_id",
        },
    )

    existing_recurring_ids = {
        r["recurring_id"] for r in existing if r.get("recurring_id")
    }
    max_row = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{plan_date}",
            "is_deleted": "eq.false",
            "select": "position",
            "order": "position.desc",
            "limit": 1,
        },
    )

    next_pos = (max_row[0]["position"] + 1) if max_row and len(max_row) > 0 else 0

    payload = []

    for r in rules:
        if r.get("end_date") and plan_date > date.fromisoformat(r["end_date"]):
            continue

        applies = False

        if r["recurrence"] == "daily":
            applies = True

        elif r["recurrence"] == "weekly":
            if r["days_of_week"] and plan_date.weekday() in r["days_of_week"]:
                applies = True

        elif r["recurrence"] == "monthly":
            last_day = calendar.monthrange(plan_date.year, plan_date.month)[1]

            if plan_date.day == r["day_of_month"]:
                applies = True
            elif r["day_of_month"] > last_day and plan_date.day == last_day:
                applies = True  

        if not applies:
            continue

        if r["id"] in existing_recurring_ids:
            continue

        payload.append(
            {
                "plan_date": str(plan_date),
                "quadrant": r["quadrant"],
                "task_text": r["task_text"],
                "category": r.get("category") or "General",
                "subcategory": r.get("subcategory") or "General",
                "is_done": False,
                "is_deleted": False,
                "position": next_pos,
                "recurring_id": r["id"],
            }
        )

    if payload:
        post("todo_matrix", payload)


def copy_open_tasks_from_previous_day(plan_date):
    prev_date = plan_date - timedelta(days=1)

    prev_rows = (
        get(
            "todo_matrix",
            params={
                "plan_date": f"eq.{prev_date}",
                "is_deleted": "eq.false",
                "select": "quadrant,task_text,is_done,task_date,task_time,category,subcategory",
            },
        )
        or []
    )

    if not prev_rows:
        return 0

    today_rows = (
        get(
            "todo_matrix",
            params={
                "plan_date": f"eq.{plan_date}",
                "select": "quadrant,task_text,position",
                "is_deleted": "eq.false",
            },
        )
        or []
    )

    today_tasks = {
        (r["quadrant"], (r["task_text"] or "").strip().lower()) for r in today_rows
    }

    # Build max position per quadrant ONCE
    max_pos = {}
    for r in today_rows:
        q = r["quadrant"]
        max_pos[q] = max(max_pos.get(q, -1), r.get("position", -1))

    payload = []

    for r in prev_rows:
        if r.get("is_done"):
            continue

        key = (r["quadrant"], (r["task_text"] or "").strip().lower())
        if key in today_tasks:
            continue

        next_pos = max_pos.get(r["quadrant"], -1) + 1
        max_pos[r["quadrant"]] = next_pos

        payload.append(
            {
                "plan_date": str(plan_date),
                "quadrant": r["quadrant"],
                "task_text": r["task_text"],
                "is_done": False,
                "is_deleted": False,  # 👈 REQUIRED
                "task_date": r.get("task_date"),
                "task_time": r.get("task_time"),
                "position": next_pos,
                "category": r.get("category") or "General",
                "subcategory": r.get("subcategory") or "General",
            }
        )

    if payload:
        post("todo_matrix", payload)

    return len(payload)


### Travel mode Code Changes ###


def enable_travel_mode(plan_date):
    """
    Insert Travel Mode tasks for the day.
    Idempotent: inserts only missing tasks.
    """

    existing = (
        get(
            "todo_matrix",
            params={
                "plan_date": f"eq.{plan_date}",
                "is_deleted": "eq.false",
                "select": "quadrant,task_text",
            },
        )
        or []
    )

    existing_keys = {
        (r["quadrant"], (r["task_text"] or "").strip().lower()) for r in existing
    }

    payload = []
    max_rows = (
        get(
            "todo_matrix",
            params={
                "plan_date": f"eq.{plan_date}",
                "is_deleted": "eq.false",
                "select": "quadrant,position",
            },
        )
        or []
    )

    position_map = {}
    for r in max_rows:
        q = r["quadrant"]
        position_map[q] = max(position_map.get(q, -1), r.get("position", -1))

    for quadrant, text, subcat in TRAVEL_MODE_TASKS:
        key = (quadrant, text.lower())
        if key in existing_keys:
            continue

        pos = position_map.get(quadrant, -1) + 1
        position_map[quadrant] = pos

        ### Category, Sub Category Changes start here ###

        payload.append(
            {
                "plan_date": str(plan_date),
                "quadrant": quadrant,
                "task_text": text,
                "category": "Travel",
                "subcategory": subcat,
                "is_done": False,
                "is_deleted": False,
                "position": pos,
            }
        )

        ### Category, Subcategory code ends here ###

    if payload:
        post("todo_matrix", payload)

    return len(payload)
def safe_date(year: int, month: int, day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))

def extract_tags(text):
    return list(set(tag.lower() for tag in re.findall(r"#(\w+)", text)))

def parse_time_token(token, plan_date):
    token = token.lower().strip()

    # 🔒 Extract time safely FIRST (space-aware)
    match = re.search(
        r"\b(\d{1,2})(?:[:\.](\d{2}))?\s*(am|pm)\b",
        token
    )

    if not match:
        raise ValueError(f"Invalid time token: {token}")

    hour, minute, meridiem = match.groups()

    # Normalize
    minute = minute or "00"
    token = f"{hour}:{minute}{meridiem}"

    # Validate ranges
    if not (1 <= int(hour) <= 12):
        raise ValueError(f"Invalid hour in time: {token}")
    if not (0 <= int(minute) < 60):
        raise ValueError(f"Invalid minute in time: {token}")

    return datetime.strptime(
        f"{plan_date} {token}",
        "%Y-%m-%d %I:%M%p",
    )
def remove_untimed_task(plan_date, task_id):
    row = get(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date}",
            "slot": f"eq.{META_SLOT}",
            "select": "plan",
        },
    )[0]

    meta = json.loads(row.get("plan") or "{}")

    cleaned = []

    for t in meta.get("untimed_tasks", []):
        if isinstance(t, str):
            # Legacy string → skip only if text matches
            if f"legacy_{hash(t)}" != task_id:
                cleaned.append({
                    "id": f"legacy_{hash(t)}",
                    "text": t
                })
        else:
            if t.get("id") != task_id:
                cleaned.append(t)

    meta["untimed_tasks"] = cleaned


    update(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date}",
            "slot": f"eq.{META_SLOT}",
        },
        json={"plan": json.dumps(meta)},
    )

def extract_date(raw_text, default_date):
    """
    Resolves task date from natural language.

    Supported patterns (priority order):

    1. Explicit date (highest priority):
       - on 15Feb
       - on 15 Feb
       - on 15/02
       - on 15-02

    2. Relative date keywords:
       - tomorrow
       - next monday
       - next tuesday
       - next wednesday
       - next thursday
       - next friday
       - next saturday
       - next sunday

    3. Default behaviour:
       - If no date is specified, defaults to the planner UI date.

    Notes:
    - Explicit dates always override relative keywords.
    - Year defaults to the current planner year.
    - Invalid dates are safely clamped to month end
      (e.g., 31 Feb → 28/29 Feb).
    """
    text = raw_text.lower()

    # --------------------------------
    # 1️⃣ Explicit date: "on 15Feb", "on 15/02"
    # --------------------------------
    match = re.search(
        r"\bon\s+(\d{1,2})[\s\-\/]?([a-z]{3}|\d{1,2})",
        text,
        re.I,
    )

    if match:
        day = int(match.group(1))
        month_token = match.group(2)

        if month_token.isdigit():
            month = int(month_token)
        else:
            month = datetime.strptime(month_token[:3], "%b").month

        return safe_date(default_date.year, month, day)

    # --------------------------------
    # 2️⃣ Tomorrow
    # --------------------------------
    if re.search(r"\btomorrow\b", text):
        return default_date + timedelta(days=1)

    # --------------------------------
    # 3️⃣ Next weekday (e.g. "next monday")
    # --------------------------------
    weekday_match = re.search(
        r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        text,
    )

    if weekday_match:

        target = WEEKDAY_MAP[weekday_match.group(1)]
        today = default_date.weekday()

        delta = (target - today) % 7
        delta = 7 if delta == 0 else delta  # force NEXT, not today

        return default_date + timedelta(days=delta)

    # --------------------------------
    # 4️⃣ Default → planner UI date
    # --------------------------------
    return default_date

def parse_planner_input(raw_text, plan_date):
    # --------------------------------
    # QUADRANT PARSING
    # --------------------------------
    task_date = extract_date(raw_text, plan_date)

    quadrant_match = re.search(r"\b(Q[1-4])\b", raw_text, re.I)
    quadrant = (
        QUADRANT_MAP[quadrant_match.group(1).upper()]
        if quadrant_match
        else None
    )

    # --------------------------------
    # TIME PARSING (existing logic)
    # --------------------------------
 # --------------------------------
# TIME PARSING (expanded)
# --------------------------------

    range_match = re.search(
        r"(?:@|from)\s*([0-9:\.apm\s]+)\s+to\s+([0-9:\.apm\s]+)",
        raw_text,
        re.I,
    )

    single_match = re.search(
        r"@\s*([0-9:\.apm\s]+)",
        raw_text,
        re.I,
    )



    if range_match:
        start_raw, end_raw = range_match.groups()
        start_dt = parse_time_token(start_raw, task_date)
        end_dt = parse_time_token(end_raw, task_date)

    elif single_match:
        start_raw = single_match.group(1)
        start_dt = parse_time_token(start_raw, task_date)
        end_dt = start_dt + timedelta(minutes=30)

    else:
        raise ValueError("Time missing")

    if end_dt <= start_dt:
        raise ValueError("End time must be after start time")

    # --------------------------------
    # METADATA
    # --------------------------------
    priority_match = re.search(r"\$(critical|high|medium|low)", raw_text, re.I)
    category_match = re.search(
    r"%(" + "|".join(TASK_CATEGORIES.keys()) + r")",
    raw_text,
    re.I
    )


    priority = (
        priority_match.group(1).capitalize()
        if priority_match
        else DEFAULT_PRIORITY
    )

    category = (
        category_match.group(1).capitalize()
        if category_match
        else DEFAULT_CATEGORY
    )

    title = re.sub(r"\s(@|\$|%|#|Q[1-4]).*", "", raw_text).strip()
    tags = extract_tags(raw_text)

    return {
        "title": title,
        "start": start_dt,
        "end": end_dt,
        "date" : task_date,
        "priority": priority,
        "priority_rank": PRIORITY_RANK[priority],
        "category": category,
        "tags": tags,
        "quadrant": quadrant,  # ⭐ NEW
    }


def generate_half_hour_slots(parsed):
    slots = []
    current = parsed["start"]

    while current < parsed["end"]:
        slot_end = min(current + timedelta(minutes=30), parsed["end"])

        slots.append({
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



### Travel mode Code Changes ###

# ==========================================================
# Log in codestarts here
# ==========================================================

LOGIN_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Login</title>
  <style>
    body {
      font-family: system-ui;
      background: #f6f7f9;
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100vh;
      margin: 0;
    }
    .login-box {
      background: #fff;
      padding: 24px;
      border-radius: 14px;
      width: 300px;
      box-shadow: 0 10px 25px rgba(0,0,0,.08);
    }
    h3 { margin-top: 0; }
    input {
      width: 100%;
      padding: 10px;
      margin-top: 10px;
      font-size: 15px;
    }
    button {
      width: 100%;
      padding: 12px;
      margin-top: 14px;
      font-size: 15px;
      font-weight: 600;
    }
    .error {
      color: #dc2626;
      font-size: 13px;
      margin-top: 10px;
    }
  </style>
</head>
<body>
  <form method="post" class="login-box">
    <h3>🔒 Login</h3>
    <input type="password" name="password" placeholder="Password" autofocus>
    <button type="submit">Continue</button>
    {% if error %}
      <div class="error">{{ error }}</div>
    {% endif %}
  </form>
</body>
</html>
"""


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
def promote_untimed():
    data = request.get_json()
    plan_date = date.fromisoformat(data["plan_date"])
    task_id = data["id"]
    text = data["text"]
    quadrant = data["quadrant"]

    # 1️⃣ Insert into Eisenhower
    post(
        "todo_matrix",
        {
            "plan_date": str(plan_date),
            "quadrant": quadrant,
            "task_text": text,
            "is_done": False,
            "is_deleted": False,
            "position": 0,
            "category": "General",
            "subcategory": "General",
        },
    )

    # 2️⃣ Remove from untimed
    remove_untimed_task(plan_date, task_id)

    return ("", 204)
@app.route("/untimed/schedule", methods=["POST"])
@login_required
def schedule_untimed():
    data = request.get_json()

    plan_date = date.fromisoformat(data["plan_date"])
    task_id = data["id"]
    text = data["text"]
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

### Travel mode Code Changes ###

# ==========================================================
# TEMPLATE – DAILY PLANNER (UNCHANGED, STABLE)
# ==========================================================
##PLANNER_TEMPLATE = """<-- SAME AS YOUR RESTORED VERSION, UNCHANGED -->"""

PLANNER_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>

body { font-family: system-ui; background:#f6f7f9; padding:12px; padding-bottom:220px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:16px; border-radius:14px; }

.header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
.header a { font-weight:600; text-decoration:none; }
.time { color:#2563eb; font-weight:700; }

.month-controls { display:flex; gap:8px; margin-bottom:12px; }
.day-strip { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }

.day-btn {
  width:36px; height:36px;
  border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  border:1px solid #ddd;
  text-decoration:none; color:#000;
}
.day-btn.selected { background:#2563eb; color:#fff; }

.slot { border-bottom:1px solid #eee; padding-bottom:12px; margin-bottom:12px; }
.current { background:#eef2ff; border-left:4px solid #2563eb; padding-left:8px; }

textarea { width:100%; min-height:90px; font-size:15px; }

.status-pill {
  display:inline-block;
  padding:6px 12px;
  border-radius:999px;
  font-weight:600;
  cursor:pointer;
}
.status-Nothing\\ Planned { background:#e5e7eb; }
.status-Yet\\ to\\ Start { background:#fde68a; }
.status-In\\ Progress { background:#bfdbfe; }
.status-Closed { background:#bbf7d0; }
.status-Deferred { background:#fecaca; }

.floating-bar {
  position:fixed;
  bottom:env(safe-area-inset-bottom,0);
  left:0; right:0;
  background:#fff;
  border-top:1px solid #ddd;
  padding:10px;
  display:flex;
  gap:10px;
}
.floating-bar button { flex:1; padding:14px; font-size:16px; }
</style>
</head>

<body>

<div class="container">

<div class="header">
  <div>{{ today }}</div>
  <div>
    <a href="/todo">📋 Eisenhower</a>
    &nbsp;&nbsp;
    <span class="time">🕒 <span id="clock"></span> IST</span>
  </div>
</div>

<form method="get" class="month-controls">
  <input type="hidden" name="day" value="{{ selected_day }}">
  <select name="month" onchange="this.form.submit()">
    {% for m in range(1,13) %}
      <option value="{{m}}" {% if m==month %}selected{% endif %}>
        {{ calendar.month_name[m] }}
      </option>
    {% endfor %}
  </select>
  <select name="year" onchange="this.form.submit()">
    {% for y in range(year-5, year+6) %}
      <option value="{{y}}" {% if y==year %}selected{% endif %}>{{y}}</option>
    {% endfor %}
  </select>
</form>

<div class="day-strip">
{% for d in days %}
<a href="/?year={{year}}&month={{month}}&day={{d.day}}"
   class="day-btn {% if d.day==selected_day %}selected{% endif %}">
  {{d.day}}
</a>
{% endfor %}
</div>

<form method="post" id="planner-form">
<input type="hidden" name="year" value="{{ year }}">
<input type="hidden" name="month" value="{{ month }}">
<input type="hidden" name="day" value="{{ selected_day }}">
<details style="
  background:#f8fafc;
  border-left:4px solid #2563eb;
  padding:10px 14px;
  margin-bottom:12px;
  border-radius:8px;
  font-size:14px;
">
  <summary style="
    font-weight:600;
    cursor:pointer;
    list-style:none;
    outline:none;
  ">
    🧠 How to write a smart task
  </summary>

  <div style="margin-top:10px;">
    <code>
      Task @time [to time] [tomorrow | next monday | on 15Feb] [Q1–Q4] [$Priority] [%Category] [#tags]
    </code>
    <div style="margin-top:8px;">
      <strong>Examples:</strong>
        <ul style="margin:6px 0 0 18px;">
          <li><code>Visit renga temple @10am</code></li>
          <li><code>Meeting @9am to 10am</code></li>
          <li><code>Workout @6am tomorrow</code></li>
          <li><code>Doctor visit @11am next friday</code></li>
          <li><code>Pay electricity bill @8pm on 15Feb</code></li>
          <li><code>Fix prod bug @10am Q1</code></li>
          <li><code>Plan quarterly goals @7am Q2</code></li>
          <li><code>Follow up vendor @3pm Q3</code></li>
          <li><code>Scroll social media @11pm Q4</code></li>
          <li><code>Submit tax docs @9pm $Critical</code></li>
          <li><code>Yoga @6am $High %Health</code></li>
          <li><code>Pack luggage @9pm %Travel</code></li>
          <li><code>Workout @6am #health #fitness</code></li>
          <li><code>Sprint planning @9am to 11am next monday Q2 $Critical %Office #agile</code></li>
        </ul>
    </div>

   <div style="margin-top:8px; color:#475569;">
      • <b>@</b> • @ Time is optional (tasks without time go to Untimed)(e.g. @9am or @9am to 10am)<br>
      • <b>on</b> Date (optional): tomorrow | next monday | on 15Feb<br>
      • <b>Q1–Q4</b> Eisenhower quadrant (optional)<br>
      • <b>$</b> Priority: Critical | High | Medium | Low<br>
      • <b>%</b> Category: Office | Personal | Family | Health | Travel | Finance | General<br>
      • <b>#</b> Tags (optional, multiple allowed)<br>
      • One task per line<br>
      • Time slots auto-fill in 30-minute blocks
    </div>

  </div>
</details>

<h3>🧠 Smart Planner Input</h3>
<textarea
  name="smart_plan"
  placeholder="
One task per line.
Example:
Meeting with Chitra @9am to 10am $Critical %Office #review
Workout @6am to 7am $High %Personal
"
  style="width:100%; min-height:120px; margin-bottom:16px;"
></textarea>
<h3>🗒 Tasks (No Time Yet)</h3>

<textarea
  name="untimed_tasks"
  placeholder="Tasks without a specific time"
  style="width:100%; min-height:120px; margin-bottom:12px;"
></textarea>

<div>
{% for t in untimed_tasks %}
  <div style="padding:8px 0;border-bottom:1px solid #eee;">
    <div>{{ t.text }}</div>
    <div style="margin-top:6px;">
      <button type="button"
              onclick="promoteUntimed('{{ t.id }}','{{ t.text }}')">
        📋 Promote
      </button>
      <button type="button"
              onclick="scheduleUntimed('{{ t.id }}','{{ t.text }}')">
        🕒 Schedule
      </button>
    </div>
  </div>
{% endfor %}
</div>


<div style="font-size:13px; color:#475569; margin-bottom:12px;">
  • These tasks are saved for the day<br>
  • They do not block calendar slots<br>
  • Rewrite them with time or Q1–Q4 when ready
</div>
<h3>🗓 Time-blocked Plans</h3>
{% for slot in plans %}
<div class="slot {% if now_slot==slot %}current{% endif %}">
  <strong>{{ slot_labels[slot] }}</strong>
  {% if plans[slot].plan %}
    <a href="{{ reminder_links[slot] }}" target="_blank">⏰</a>
  {% endif %}
  <textarea name="plan_{{slot}}">{{ plans[slot].plan }}</textarea>

  <div class="status-pill status-{{ plans[slot].status }}" onclick="cycleStatus(this)">
    {{ plans[slot].status }}
    <input type="hidden" name="status_{{slot}}" value="{{ plans[slot].status }}">
  </div>
</div>
{% endfor %}

<h3>🏃 Habits</h3>
{% for h in habit_list %}
<label>
  <input type="checkbox" name="habits" value="{{h}}" {% if h in habits %}checked{% endif %}>
  {{ habit_icons[h] }} {{h}}
</label><br>
{% endfor %}

<h3>📝 Reflection</h3>
<textarea name="reflection">{{ reflection }}</textarea>

</form>
</div>

<div class="floating-bar">
  <button type="submit" form="planner-form">💾 Save</button>
  <button type="button" onclick="window.location.reload()">❌ Cancel</button>
</div>
<script>
function updateClock(){
  const ist = new Date(new Date().toLocaleString("en-US",{timeZone:"Asia/Kolkata"}));
  document.getElementById("clock").textContent = ist.toLocaleTimeString();
}
setInterval(updateClock,1000); updateClock();

const STATUS_ORDER = {{ statuses|tojson }};
function cycleStatus(el){
  const input = el.querySelector("input");
  let idx = STATUS_ORDER.indexOf(input.value);
  idx = (idx + 1) % STATUS_ORDER.length;
  input.value = STATUS_ORDER[idx];
  el.childNodes[0].nodeValue = STATUS_ORDER[idx] + " ";
}
</script>
{% if saved %}
<div id="toast"
     style="
       position: fixed;
       bottom: 90px;
       left: 50%;
       transform: translateX(-50%);
       background: #16a34a;
       color: white;
       padding: 12px 20px;
       border-radius: 999px;
       font-weight: 600;
       box-shadow: 0 10px 25px rgba(0,0,0,.15);
       z-index: 9999;
     ">
  ✅ Saved successfully
</div>

<script>
  setTimeout(() => {
    const toast = document.getElementById("toast");
    if (toast) toast.remove();
  }, 2500);
</script>
{% endif %}
<script>
function promoteUntimed(id, text) {
  const q = prompt("Move to which quadrant? (Q1 / Q2 / Q3 / Q4)");
  if (!q) return;

  fetch("/untimed/promote", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: id,
      text: text,
      quadrant: q.toLowerCase(),
      plan_date: "{{ plan_date }}"
    })
  }).then(() => location.reload());
}

function scheduleUntimed(id, text) {
  const start = prompt("Start slot (1–48)");
  const slots = prompt("Number of 30-min slots");

  if (!start || !slots) return;

  fetch("/untimed/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: id,
      text: text,
      start_slot: start,
      slot_count: slots,
      plan_date: "{{ plan_date }}"
    })
  }).then(() => location.reload());
}
</script>

</body>
</html>
"""
# NOTE: Use the exact PLANNER_TEMPLATE you already validated as correct.
# (Intentionally not duplicated again to avoid accidental edits.)

# ==========================================================
# TEMPLATE – EISENHOWER MATRIX
# ==========================================================
TODO_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: system-ui; background:#f6f7f9; padding:16px;padding-bottom: calc(120px + env(safe-area-inset-bottom)); /* 👈 ADD THIS */ }
.container { max-width:1100px; margin:auto; background:#fff; padding:20px; border-radius:14px; /* 👇 ADD THIS */
  padding-bottom: 140px; }


.quad { border:1px solid #e5e7eb; border-radius:12px; padding:12px; }
.quad > div {
  margin-top: 8px;
}
.quad:last-child {
  margin-bottom: 40px;
}

.matrix {
   display: grid;
   grid-template-columns: 1fr 1fr;
   gap: 16px;
  padding-bottom: 160px;
}


summary {
  font-weight: 600;
  font-size: 16px;
  cursor: pointer;
  list-style: none;
}

summary::-webkit-details-marker {
  display: none;
}

.floating-bar {
  position: fixed;
  bottom: env(safe-area-inset-bottom, 0);
  left: 0;
  right: 0;
  background: #ffffff;
  border-top: 1px solid #e5e7eb;
  padding: 10px;
  display: flex;
  gap: 10px;
  z-index: 999;
}

.floating-bar button {
  flex: 1;
  padding: 14px;
  font-size: 16px;
  font-weight: 600;
  border-radius: 10px;
  border: none;
}

.floating-bar .save {
  background: #2563eb;
  color: white;
}

.floating-bar .cancel {
  background: #e5e7eb;
}
/* ===== Google Tasks–style Eisenhower ===== */

.task {
  padding: 12px 14px;
  border: 2px solid #cbd5e1;   /* 👈 THICK, visible border */
  border-radius: 12px;
  background: #ffffff;
  margin-bottom: 12px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04); /* Improves Scannability */
}

.task + .task {
  border-top: none;
}
.task:focus-within {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15);
}

/* Main row */
.task-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* Index */
.task-index {
  min-width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #f1f5f9;
  color: #475569;
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}


/* Checkbox */
.task-main input[type="checkbox"] {
  width: 18px;
  height: 18px;
}

/* Task text */
.task-main input[type="text"] {
  flex: 1;
  border: none;
  font-size: 16px;
  background: transparent;
  padding: 4px 0;
}

.task-main input[type="text"]:focus {
  outline: none;
  border-bottom: 2px solid #2563eb;
}

.task-delete {
  background: none;
  border: none;
  font-size: 20px;
  color: #dc2626;          /* 👈 visible red */
  cursor: pointer;
  padding: 8px;           /* 👈 touch target */
  border-radius: 8px;
  opacity: 0.85;
}

.task-delete:hover,
.task-delete:active {
  background: rgba(220, 38, 38, 0.12);
  opacity: 1;
}


/* Meta row */
.task-meta input {
  border: 1px solid #e5e7eb;
  background: #f9fafb;
  border-radius: 6px;
  padding: 2px 6px;
  font-size: 12px;
}

.task-meta {
  margin-left: 34px;
  margin-top: 6px;
  display: flex;
  gap: 10px;
}
.task-text {
  resize: none;
  overflow: hidden;
  line-height: 1.4;
}


/* Completed task */
.task.done {
  background: #f8fafc;
  border-color: #94a3b8;
}

.task.done textarea {
  text-decoration: line-through;
}
.task.removed {
 background: #fef2f2;
 border-color: #fca5a5;
}
/* Prevent mobile auto-zoom */
input,
textarea,
select {
  font-size: 16px !important;
}
####
/* ========================= This section handles Desktop */
####
@media (min-width: 768px) {

  .task {
    position: relative;
  }

  .task-main {
    align-items: center;
  }

  .task-meta {
    margin-left: auto;
    justify-content: flex-end;
    gap: 8px;
  }
}
/* =========================
   MOBILE (≤767px)
   ========================= */
@media (max-width: 767px) {

  /* Grid → single column */
  .matrix {
    grid-template-columns: 1fr;
    width: 100%;
    max-width: 100%;
  }

  .quad {
    width: 100%;
    min-width: 0;
  }

  .task {
    position: relative;
  }

  /* Task row layout */
  .task-main {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    width: 100%;
    min-width: 0;          /* 👈 critical */
    gap: 6px;
    box-sizing: border-box;
  }

  /* Checkbox */
  .task-main input[type="checkbox"] {
    transform: scale(1.25);
    margin: 0;
    margin-top: 2px;
  }

  /* Task text */
  .task-text {
    flex: 1 1 auto;
    min-width: 0;
    box-sizing: border-box;
  }

  /* Delete icon — NO auto margin */
  .task-delete {
    font-size: 20px;
    min-width: 36px;
    flex-shrink: 0;
    margin: 0;
    padding: 4px;
    background: #fee2e2;
    border-radius: 8px;
  }

  /* Repeat dropdown — close to delete */
  .task-repeat {
    margin-left: 4px;
  }

  /* Meta row (date/time goes next line naturally) */
  .task-meta {
    width: 100%;
    display: flex;
    justify-content: flex-start;
    gap: 8px;
    margin-top: 6px;
  }

  .motivation {
    padding: 12px 14px;
    font-size: 13px;
  }

  details.quad {
    overflow: visible;
  }
}


/* ===== Motivational Quote ===== */

.motivation {
  position: relative;   /* 👈 REQUIRED */
  margin: 20px 0 36px;
  padding: 16px 18px;
  border-radius: 14px;
  background: linear-gradient(135deg, #f8fafc, #eef2ff);
  border-left: 4px solid #6366f1;
  display: flex;
  gap: 14px;
}


.motivation-icon {
  font-size: 22px;
  line-height: 1;
}

.motivation-text {
  font-size: 17px;
  font-style: italic;
  font-weight: 500;     /* 👈 semi-bold, tasteful */
  line-height: 1.6;
  color: #1f2937;
  max-width: 640px;
}
.motivation::before {
  content: "Reflection";
  position: absolute;
  top: -12px;
  left: 16px;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6366f1;
  font-weight: 600;
  background: #fff;
  padding: 0 6px;
}

.motivation {
  animation: quoteFade 0.4s ease-out;
}

@keyframes quoteFade {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}


.task-main span[title] {
  margin-right: 4px;
}
.repeat-select {
  font-size: 12px;
  padding: 4px 6px;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
  background: #f9fafb;
  color: #374151;
}


</style>
</head>

<body>
<div class="container">
<a href="/">⬅ Back to Daily Planner</a>
<div class="page-header">
  <h2>📋 Eisenhower Matrix – {{ plan_date }}</h2>
 <form method="post"
      action="/todo/copy-prev"
      style="margin:16px 0;">

  <input type="hidden" name="year" value="{{ year }}">
  <input type="hidden" name="month" value="{{ month }}">
  <input type="hidden" name="day" value="{{ plan_date.day }}">

  <button type="submit">
    📥 Copy open tasks from previous day
  </button>

  </form>

</div>
<!-- Travel mode Code Changes  -->
<form method="post" action="/todo/travel-mode" style="margin:12px 0;">
  <input type="hidden" name="year" value="{{ year }}">
  <input type="hidden" name="month" value="{{ month }}">
  <input type="hidden" name="day" value="{{ plan_date.day }}">
  <button type="submit">✈️ Enable Travel Mode</button>
</form>
<!-- Travel mode Code Changes -->

<form method="get" style="margin:12px 0;">
  <input type="hidden" name="day" value="{{ plan_date.day }}">

  <select name="month" onchange="this.form.submit()">
    {% for m in range(1,13) %}
      <option value="{{m}}" {% if m==month %}selected{% endif %}>
        {{ calendar.month_name[m] }}
      </option>
    {% endfor %}
  </select>

  <select name="year" onchange="this.form.submit()">
    {% for y in range(year-5, year+6) %}
      <option value="{{y}}" {% if y==year %}selected{% endif %}>{{y}}</option>
    {% endfor %}
  </select>
</form>
<div class="floating-bar">
  <button type="submit"
          form="todo-form"
          class="save">
    💾 Save
  </button>

  <button type="button"
          class="cancel"
          onclick="window.location.reload()">
    ❌ Cancel
  </button>
</div>

<div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px;">
{% for d in days %}
  <a href="/todo?year={{year}}&month={{month}}&day={{d.day}}"
     style="
       width:36px;height:36px;
       display:flex;align-items:center;justify-content:center;
       border-radius:50%;
       text-decoration:none;
       border:1px solid #ddd;
       color:#000;
       {% if d.day == plan_date.day %}
         background:#2563eb;color:#fff;
       {% endif %}
     ">
    {{ d.day }}
  </a>
{% endfor %}
</div>
{% if quote %}
<div class="motivation">
  <span class="motivation-icon">{{ quote.icon }}</span>
  <span class="motivation-text">{{ quote.text }}</span>
</div>
{% endif %}
{% if request.args.get('travel') %}
<div style="
  margin:12px 0;
  padding:8px 12px;
  border-radius:999px;
  background:#eef2ff;
  color:#3730a3;
  font-weight:600;
  display:inline-block;
">
  ✈️ Travel Mode Active
</div>
{% endif %}

<form method="post" id="todo-form">

  <!-- ============================= -->
  <!-- MATRIX CONTAINER (GRID)       -->
  <!-- ============================= -->
  <div class="matrix">

    <!-- Hidden inputs -->
    <input type="hidden" name="year" value="{{ year }}">
    <input type="hidden" name="month" value="{{ month }}">
    <input type="hidden" name="day" value="{{ plan_date.day }}">

    <!-- ================================= -->
    <!-- START: QUADRANT LOOP (4 times)   -->
    <!-- ================================= -->
    {% for q, label in [
      ('do','🔥 Do Now'),
      ('schedule','📅 Schedule'),
      ('delegate','🤝 Delegate'),
      ('eliminate','🗑 Eliminate')
    ] %}

      <details class="quad" open>
        <summary>{{ label }}</summary>
        <div id="{{ q }}">

          <!-- =============================== -->
          <!-- CATEGORY / TASK RENDERING       -->
          <!-- =============================== -->
          {% for category, subs in todo[q].items() %}
            <details open>
              <summary>{{ TASK_CATEGORIES.get(category, "📁") }} {{ category }}</summary>

              {% if category == "Travel" %}
                {# -------- Travel: static subgroups -------- #}
                {% for sub, icon in STATIC_TRAVEL_SUBGROUPS.items() %}

                  <details open style="margin-left:12px;">
                    <summary>{{ icon }} {{ sub }}</summary>

                    {% for t in subs.get(sub, []) %}
                      <div class="task {% if t.done %}done{% endif %}">
                        <input type="hidden" name="{{ q }}_id[]" value="{{ t.id }}">
                        <!-- 👇 ADD THIS LINE -->
                        <input type="hidden" name="{{ q }}_deleted[]" value="0">
                        <div class="task-main">
                          <span class="task-index">{{ loop.index }}.</span>

                          <!-- Preserve category / subcategory -->
                          <input type="hidden" name="{{ q }}_category[]" value="{{ t.category }}">
                          <input type="hidden" name="{{ q }}_subcategory[]" value="{{ t.subcategory }}">
                          <input type="hidden"
                                 name="{{ q }}_done_state[{{ t.id }}]"
                                 value="0">

                          <textarea name="{{ q }}[]"
                                    class="task-text"
                                    rows="1"
                                    placeholder="Add a task"
                                    oninput="autoGrow(this)">{{ t.text }}</textarea>

                          <input type="checkbox"
                                 name="{{ q }}_done_state[{{ t.id }}]"
                                 value="1"
                                 {% if t.done %}checked{% endif %}
                                 onchange="toggleDone(this)">

                          {% if t.recurring %}
                            <button type="button"
                                    class="task-delete"
                                    title="Delete this and future occurrences"
                                    onclick="deleteRecurring('{{ t.id }}')">🗑</button>
                          {% else %}
                            <button type="button"
                                    class="task-delete"
                                    title="Removed after Save"
                                    onclick="
                                              const task = this.closest('.task');
                                              task.classList.add('removed');
                                              task.querySelector('input[name$=_deleted\\[\\]]').value = '1';
                                            ">🗑</button>
                          {% endif %}

                          {% if t.recurring %}
                            <span title="Repeats {{ t.recurrence }}" style="font-size:13px;color:#6366f1;">
                              🔁 {{ t.recurrence or "Recurring" }}
                            </span>
                          {% else %}
                            <select class="repeat-select"
                                    onchange="setRecurrence('{{ t.id }}', this.value)">
                              <option value="">Repeat…</option>
                              <option value="daily">Daily</option>
                              <option value="weekly">Weekly</option>
                              <option value="monthly">Monthly</option>
                            </select>
                          {% endif %}
                        </div>

                        <div class="task-meta">
                          <input type="date" name="{{ q }}_date[]" value="{{ t.task_date or '' }}">
                          <input type="time" name="{{ q }}_time[]" value="{{ t.task_time or '' }}">
                        </div>
                      </div>
                    {% endfor %}

                    {% if not subs.get(sub) %}
                      <div class="empty-group">No tasks</div>
                    {% endif %}
                  </details>
                {% endfor %}

              {% else %}
                {# -------- Non-Travel categories: flat list -------- #}
                {% for tasks in subs.values() %}
                  {% for t in tasks %}
                    <div class="task {% if t.done %}done{% endif %}">
                      <input type="hidden" name="{{ q }}_id[]" value="{{ t.id }}">
                      <!-- 👇 ADD THIS LINE -->
                      <input type="hidden" name="{{ q }}_deleted[]" value="0">
                      <div class="task-main">
                        <span class="task-index">{{ loop.index }}.</span>

                        <input type="hidden" name="{{ q }}_category[]" value="{{ t.category }}">
                        <input type="hidden" name="{{ q }}_subcategory[]" value="{{ t.subcategory }}">
                        <input type="hidden"
                               name="{{ q }}_done_state[{{ t.id }}]"
                               value="0">

                        <textarea name="{{ q }}[]"
                                  class="task-text"
                                  rows="1"
                                  placeholder="Add a task"
                                  oninput="autoGrow(this)">{{ t.text }}</textarea>

                        <input type="checkbox"
                               name="{{ q }}_done_state[{{ t.id }}]"
                               value="1"
                               {% if t.done %}checked{% endif %}
                               onchange="toggleDone(this)">

                        {% if t.recurring %}
                          <button type="button"
                                  class="task-delete"
                                  title="Delete this and future occurrences"
                                  onclick="deleteRecurring('{{ t.id }}')">🗑</button>
                        {% else %}
                          <button type="button"
                                  class="task-delete"
                                  title="Removed after Save"
                                  onclick="
                                        const task = this.closest('.task');
                                        task.classList.add('removed');
                                        task.querySelector('input[name$=_deleted\\[\\]]').value = '1';
                                      ">🗑</button>
                        {% endif %}

                        {% if t.recurring %}
                          <span title="Repeats {{ t.recurrence }}" style="font-size:13px;color:#6366f1;">
                            🔁 {{ t.recurrence or "Recurring" }}
                          </span>
                        {% else %}
                          <select class="repeat-select"
                                  onchange="setRecurrence('{{ t.id }}', this.value)">
                            <option value="">Repeat…</option>
                            <option value="daily">Daily</option>
                            <option value="weekly">Weekly</option>
                            <option value="monthly">Monthly</option>
                          </select>
                        {% endif %}
                      </div>

                      <div class="task-meta">
                        <input type="date" name="{{ q }}_date[]" value="{{ t.task_date or '' }}">
                        <input type="time" name="{{ q }}_time[]" value="{{ t.task_time or '' }}">
                      </div>
                    </div>
                  {% endfor %}
                {% endfor %}
              {% endif %}

            </details>
          {% endfor %}
        </div>

        <!-- Add button for this quadrant -->
        <button type="button" onclick="addTask('{{ q }}')">+ Add</button>

      </details>
      <br>

    {% endfor %}
    <!-- ================================= -->
    <!-- END: QUADRANT LOOP                -->
    <!-- ================================= -->

  </div>
</form>

</div>


<script>
function addTask(q, category = "General", subcategory = "General") {
  const container = document.getElementById(q);
  if (!container) return;

  const row = document.createElement("div");
  row.className = "task";

  const id = "new_" + Date.now();

  row.innerHTML = `
    <input type="hidden" name="${q}_id[]" value="${id}">
    <input type="hidden" name="${q}_deleted[]" value="0">
    <input type="hidden" name="${q}_category[]" value="${category}">
    <input type="hidden" name="${q}_subcategory[]" value="${subcategory}">
    <input type="hidden" name="${q}_done_state[${id}]" value="0">

    <div class="task-main">
      <span class="task-index">*</span>

      <textarea name="${q}[]"
                class="task-text"
                rows="1"
                placeholder="Add a task"
                oninput="autoGrow(this)"
                autofocus></textarea>

      <input type="checkbox"
             name="${q}_done_state[${id}]"
             value="1"
             onchange="toggleDone(this)">

      <button type="button"
              class="task-delete"
              title="Remove before save"
              onclick="this.closest('.task').remove()">🗑</button>
    </div>

    <div class="task-meta">
      <input type="date" name="${q}_date[]">
      <input type="time" name="${q}_time[]">
    </div>
  `;

  container.appendChild(row);

  // Auto-grow immediately
  const textarea = row.querySelector("textarea");
  if (textarea) autoGrow(textarea);
}
</script>
<script>

let autoSaveTimer = null;

function toggleDone(checkbox) {
  const task = checkbox.closest(".task");
  if (!task) return;

  // UI update (already correct)
  if (checkbox.checked) {
    task.classList.add("done");
  } else {
    task.classList.remove("done");
  }

  // Debounced auto-save (prevents rapid submits)
  if (autoSaveTimer) {
    clearTimeout(autoSaveTimer);
  }

  autoSaveTimer = setTimeout(() => {
  const form = document.getElementById("todo-form");
  const textarea = task.querySelector("textarea");
  if (textarea) autoGrow(textarea);
  if (form) {
    form.submit(); // IMPORTANT: use submit(), not requestSubmit()
  }
}, 500);

}
function autoGrow(textarea) {
  if (!textarea) return;

  // Reset height so shrink also works
  textarea.style.height = "auto";

  // Set height to scroll height
  textarea.style.height = textarea.scrollHeight + "px";
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("textarea.task-text").forEach(autoGrow);
});
function setRecurrence(taskId, recurrence) {
  if (taskId.startsWith("new_")) {
    alert("Please save the task before making it recurring.");
    return;
  }
  fetch("/set_recurrence", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task_id: taskId,
      recurrence: recurrence
    })
  }).then(() => location.reload());
}

function deleteRecurring(taskId) {
  if (!confirm("Delete this task from today onwards? Past entries will remain.")) {
    return;
  }

  fetch("/delete_recurring", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId })
  }).then(() => location.reload());
}


</script>
{% if request.args.get('saved') %}
<div id="toast"
     style="
       position: fixed;
       bottom: 90px;
       left: 50%;
       transform: translateX(-50%);
       background: #2563eb;
       color: white;
       padding: 12px 20px;
       border-radius: 999px;
       font-weight: 600;
       box-shadow: 0 10px 25px rgba(0,0,0,.15);
       z-index: 9999;
     ">
  ✅ Saved successfully
</div>

<script>
  setTimeout(() => {
    const toast = document.getElementById("toast");
    if (toast) toast.remove();
  }, 2500);
</script>
{% endif %}
{% if request.args.get('copied') %}
<div id="copied-toast"
     style="
       position: fixed;
       bottom: 140px;   /* 👈 slightly higher than Save toast */
       left: 50%;
       transform: translateX(-50%);
       background: #16a34a;
       color: white;
       padding: 12px 20px;
       border-radius: 999px;
       font-weight: 600;
       box-shadow: 0 10px 25px rgba(0,0,0,.15);
       z-index: 9999;
     ">
  📥 Open tasks copied
</div>

<script>
  setTimeout(() => {
    const toast = document.getElementById("copied-toast");
    if (toast) toast.remove();
  }, 2500);
</script>
{% endif %}

</body>
</html>
"""
SUMMARY_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: system-ui; background:#f6f7f9; padding:16px; }
.container { max-width:900px; margin:auto; background:#fff; padding:20px; border-radius:14px; }
h2 { margin-top:0; }
.tag { margin-top:16px; }
.priority { margin-left:16px; color:#475569; }
.task { margin-left:32px; }
.day { margin-top:18px; font-weight:600; }
</style>
</head>

<body>
<div class="container">
<a href="/">⬅ Back to Planner</a>

{% if view == "daily" %}
  <h2>📊 Daily Summary – {{ date }}</h2>

  {% for tag, priorities in data.items() %}
    <div class="tag">
      <strong>#{{ tag }}</strong>
      {% for p, tasks in priorities.items() %}
        <div class="priority">{{ p }}</div>
        {% for t in tasks %}
          <div class="task">• {{ t }}</div>
        {% endfor %}
      {% endfor %}
    </div>
  {% endfor %}

{% else %}
  <h2>📈 Weekly Summary ({{ start }} → {{ end }})</h2>

  {% for day, tasks in data.items() %}
    <div class="day">{{ day }}</div>
    {% for t in tasks %}
      <div class="task">• {{ t }}</div>
    {% endfor %}
  {% endfor %}
{% endif %}

</div>
</body>
</html>
"""

# ==========================================================
# ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    logger.info("Starting Daily Planner – stable + Eisenhower")
    app.run(debug=True)