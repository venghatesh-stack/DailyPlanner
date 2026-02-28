import json
import re
from datetime import datetime,date
from config import MONTHLY_RE,STARTING_RE,EVERY_DAY_RE,EVERY_WEEKDAY_RE,INTERVAL_RE,WEEKDAYS
from config import (
    TOTAL_SLOTS,
    DEFAULT_STATUS,
    HEALTH_HABITS,
    MIN_HEALTH_HABITS,
)
from utils.slots import generate_half_hour_slots
import logging
from supabase_client import get, post, update
from utils.planner_parser import parse_planner_input
from utils.slots import slot_label

logger = logging.getLogger(__name__)

def fetch_daily_slots(plan_date):


    # ensure correct format
    if hasattr(plan_date, "strftime"):
        plan_date = plan_date.strftime("%Y-%m-%d")

    rows = get(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date}",
            "select": "plan,start_time,end_time,slot",
            "order": "slot.asc",
        },
    )

    if not rows :
        return []

    return [
        {
            "text": r["plan"],
            "start_time": r["start_time"],
            "end_time": r["end_time"],
            "slot": r["slot"],
        }
        for r in rows
        if r.get("plan") and r.get("slot") is not None
    ]

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
    user_id ="VenghateshS"
    meta = get(
        "daily_meta",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date}",
            "select": "habits,reflection,untimed_tasks",
        },
    )

    if meta:
        row = meta[0]
        habits = set(row.get("habits") or [])
        reflection = row.get("reflection") or ""
        untimed_tasks = row.get("untimed_tasks") or []

    rows = (
        get(
            "daily_slots",
            params={
                "plan_date": f"eq.{plan_date}",
                "select": "slot,plan,status,priority,category,tags",
            },
        )
        or []
    )

    for r in rows:
        slot = r.get("slot")

        if not isinstance(slot, int) or not (1 <= slot <= TOTAL_SLOTS):
            logger.error("Invalid slot dropped %s", r)
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
            "priority": r.get("priority"),
            "category": r.get("category"),
            "tags": row_tags,
        }


    return plans, habits, reflection,untimed_tasks



def save_day(plan_date, form):
    user_id="VenghateshS"
    payload = []
    auto_untimed = []
    existing_meta = {}
    meta_rows = get(
        "daily_meta",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date}",
            "select": "habits,reflection,untimed_tasks",
        },
    )

    if meta_rows:   
        existing_meta = meta_rows[0]

    # Track slots already filled by smart parsing
    smart_block = form.get("smart_plan", "").strip()
    recurrence = parse_recurrence_block(smart_block, plan_date)

    # -------------------------------------------------
    # SMART MULTI-LINE INPUT (GLOBAL)
    # -------------------------------------------------
    if smart_block:
        for line in smart_block.splitlines():
            # -------------------------------------------------
            # Normalize leading time formats
            # -------------------------------------------------

            # Case 1: "9 task" → "task @9"
            m = re.match(r"^(\d{1,2})(?:\s+)(.+)$", line)
            if m:
                line = f"{m.group(2)} @{m.group(1)}"

            # Case 2: "9-10 task" → "task from 9 to 10"
            m = re.match(r"^(\d{1,2})\s*-\s*(\d{1,2})\s+(.+)$", line)
            if m:
                line = f"{m.group(3)} from {m.group(1)} to {m.group(2)}"

            # Case 3: "9.30-10.30 task" → "task from 9:30 to 10:30"
            m = re.match(r"^(\d{1,2})\.(\d{2})\s*-\s*(\d{1,2})\.(\d{2})\s+(.+)$", line)
            if m:
                start = f"{m.group(1)}:{m.group(2)}"
                end = f"{m.group(3)}:{m.group(4)}"
                line = f"{m.group(5)} from {start} to {end}"

            line = line.strip()
            if not line:
                continue
            has_time = re.search(
                r"""
                (
                    @\s*\d{1,2}(:\d{2})?\s*(am|pm)? |
                    \bfrom\s+\d{1,2} |
                    ^\d{1,2}(\.\d{2})?(\s*(am|pm))? |
                    ^\d{1,2}(\.\d{2})?\s*-\s*\d{1,2}(\.\d{2})?
                )
                """,
                line,
                re.I | re.X
                )

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

                        next_pos = max_pos[0]["position"] + 1 if max_pos else 0

                        post(
                            "todo_matrix",
                            {
                                "plan_date": str(plan_date),
                                "quadrant": quadrant,
                                "task_text": parsed["title"],
                                "is_done": False,
                                "is_deleted": False,
                                "position": next_pos,
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
                    "id": f"u_{int(datetime.now().timestamp() * 1000)}_{len(auto_untimed)}",
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
                      max_pos = get(
                            "todo_matrix",
                            params={
                                "plan_date": f"eq.{task_date}",
                                "quadrant": f"eq.{quadrant}",
                                "is_deleted": "eq.false",
                                "select": "position",
                                "order": "position.desc",
                                "limit": 1,
                            },
                        )

                      next_pos = max_pos[0]["position"] + 1 if max_pos else 0

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
                                "position": next_pos,
                                "category": parsed["category"],
                                "subcategory": "General",
                            },
                        )
              

                slots = generate_half_hour_slots(parsed)
               
                affected_slots = set()

                affected_slots = {
                    s["slot"]
                    for s in slots
                    if 1 <= s["slot"] <= TOTAL_SLOTS
                }

                # -------------------------------
                # Slot metadata for recurrence
                # -------------------------------
                if affected_slots:
                    first_slot = min(affected_slots)
                    slot_count = len(affected_slots)
                else:
                    first_slot = None
                    slot_count = 0
                if recurrence["type"] and affected_slots:
                    existing = get(
                        "recurring_slots",
                        params={
                            "title": f"eq.{parsed['title']}",
                            "start_slot": f"eq.{first_slot}",
                            "slot_count": f"eq.{slot_count}",
                            "start_date": f"eq.{recurrence['start_date']}",
                            "is_active": "eq.true",
                        },
                    )

                    if not existing:
                        post(
                            "recurring_slots",
                            {
                                "user_id": user_id,
                                "title": parsed["title"],
                                "start_slot": first_slot,
                                "slot_count": slot_count,
                                "recurrence_type": recurrence["type"],
                                "interval_value": recurrence["interval"],
                                "days_of_week": recurrence["days_of_week"],
                                "start_date": str(recurrence["start_date"]),
                                "is_active": True,
                            },
                        )

              

                # Re-insert smart slots
                for s in slots:
                    if 1 <= s["slot"] <= TOTAL_SLOTS:
                        payload.append(
                        {
                            "plan_date": str(task_date),
                            "slot": s["slot"],
                            "plan": s["task"],

                            # 🔥 ADD THESE TWO LINES
                            "start_time": s["start"].strftime("%H:%M"),
                            "end_time": s["end"].strftime("%H:%M"),

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

  

    untimed_raw = form.get("untimed_tasks", "")

    # 🔒 normalize untimed_raw to string
    if isinstance(untimed_raw, list):
        untimed_raw = "\n".join(untimed_raw)
    elif untimed_raw is None:
        untimed_raw = ""

    untimed_raw = untimed_raw.strip()

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

    merged = {}

    # Existing untimed tasks from DB
    existing_untimed = existing_meta.get("untimed_tasks", [])
    if isinstance(existing_untimed, list):
        for t in existing_untimed:
            merged[t["id"]] = t

    # Auto-detected untimed (smart planner)
    for t in auto_untimed:
        merged[t["id"]] = t

    # Manually entered untimed
    for t in new_untimed:
        merged[t["id"]] = t

    # 🔒 Support both request.form and dict inputs
    if hasattr(form, "getlist"):
        habits = form.getlist("habits")
    else:
        habits = form.get("habits", []) or []

    if habits is None:
        habits = existing_meta.get("habits", [])
   
    update(
    "daily_meta",
    params={
        "user_id": f"eq.{user_id}",
        "plan_date": f"eq.{plan_date}",
    },
    json={
        "habits": habits,
        "reflection": form.get("reflection", "").strip(),
        "untimed_tasks": list(merged.values()),
    },
)





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
         # 🔥 ADD THESE
        "start_time",
        "end_time",
    }

    clean_payload = [
        {k: v for k, v in row.items() if k in ALLOWED_DAILY_COLUMNS}
        for row in payload
    ]

    if clean_payload:
        post(
            "daily_slots?on_conflict=plan_date,slot",
            clean_payload,
            prefer="resolution=merge-duplicates",
        )



SLOT_LABELS = {i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)}

def get_daily_summary(plan_date):
    # ----------------------------
    # Load day meta (habits + reflection)
    # ----------------------------
    meta_rows = get(
        "daily_meta",
        params={
            "plan_date": f"eq.{plan_date}",
            "select": "habits,reflection",
        },
    ) or []

    habits = []
    reflection = ""

    if meta_rows:
        row = meta_rows[0]
        habits = row.get("habits") or []
        reflection = row.get("reflection") or ""

    # ----------------------------
    # Load slot-based tasks
    # ----------------------------
    rows = get(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date}",
            "select": "slot,plan",
            "order": "slot.asc",
        },
    ) or []

    tasks = []
    current = None

    for r in rows:
        slot = r.get("slot")
        text = (r.get("plan") or "").strip()

        if not text:
            current = None
            continue

        if not isinstance(slot, int) or slot not in SLOT_LABELS:
            current = None
            continue

        # Start new block
        if (
            current is None
            or current["text"] != text
            or slot != current["end_slot"] + 1
        ):
            current = {
                "start_slot": slot,
                "end_slot": slot,
                "text": text,
            }
            tasks.append(current)
        else:
            # Extend existing block
            current["end_slot"] = slot

    # ----------------------------
    # Add labels
    # ----------------------------
    for t in tasks:
        start = t["start_slot"]
        end = t["end_slot"]

        start_label = SLOT_LABELS[start]
        end_label = SLOT_LABELS[end]

        # Extract ONLY the end time from the end slot label
        # "01:30 AM – 02:00 AM" → "02:00 AM"
        end_time = end_label.split("–")[-1].strip()

        t["time_label"] = f"{start_label.split('–')[0].strip()} – {end_time}"


    return {
        "tasks": tasks,
        "habits": habits,
        "reflection": reflection,
    }
def get_weekly_summary(start_date, end_date):
    slots = get(
        "daily_slots",
        params={
            "plan_date": f"gte.{start_date}",
            "and": f"(plan_date.lte.{end_date})",
            "select": "plan_date,slot,plan,status",
            "order": "plan_date.asc,slot.asc",
        },
    ) or []

    meta = get(
        "daily_meta",
        params={
            "plan_date": f"gte.{start_date}",
            "and": f"(plan_date.lte.{end_date})",
            "select": "plan_date,habits,reflection",
        },
    ) or []

    days = {}
    focused_slots = 0
    completed_slots = 0

    for r in slots:
        text = (r.get("plan") or "").strip()
        slot = r.get("slot")
        date = r.get("plan_date")

        if not text or slot not in SLOT_LABELS:
            continue

        days.setdefault(date, []).append({
            "slot": slot,
            "label": SLOT_LABELS[slot],
            "text": text,
            "done": r.get("status") == "done",
        })

        focused_slots += 1
        if r.get("status") == "done":
            completed_slots += 1

    habit_days = 0
    reflections = []

    for m in meta:
        if m.get("habits"):
            habit_days += 1
        if m.get("reflection"):
            reflections.append(m["reflection"])

    return {
        "days": days,
        "focused_hours": round(focused_slots * 0.5, 1),
        "completion_rate": round((completed_slots / focused_slots) * 100, 1)
                            if focused_slots else 0,
        "habit_days": habit_days,
        "reflections": reflections,
    }
def generate_weekly_insight(data):
    insights = []

    if data["completion_rate"] >= 80:
        insights.append("🔥 Excellent execution this week.")
    elif data["completion_rate"] >= 50:
        insights.append("👍 Decent follow-through, room to tighten focus.")
    else:
        insights.append("⚠️ Planning exceeded execution — simplify next week.")

    if data["habit_days"] >= 5:
        insights.append("💪 Strong habit consistency.")
    elif data["habit_days"] >= 3:
        insights.append("🙂 Habits are forming — keep them visible.")
    else:
        insights.append("🧠 Habits slipped — reduce friction next week.")

    if data["focused_hours"] >= 25:
        insights.append("⏱ High focus output — watch for burnout.")
    elif data["focused_hours"] >= 15:
        insights.append("⏳ Solid focus foundation.")
    else:
        insights.append("⚡ Increase protected focus blocks.")

    return insights


def ensure_daily_habits_row(user_id, plan_date):
    existing = get(
        "daily_meta",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date}",
        },
    )

    if existing:
        return

    post(
        "daily_meta",
        {
            "user_id": user_id,
            "plan_date": str(plan_date),
            "habits": [],
            "reflection": "",
            "untimed_tasks": [],
        },
    )



def is_health_day(habits):
    return len(HEALTH_HABITS.intersection(habits)) >= MIN_HEALTH_HABITS
def compute_health_streak(user_id, plan_date):

    try:
        # Get active habits
        habit_defs = get(
            "habit_master",
            {
                "user_id": f"eq.{user_id}",
                "is_deleted": "is.false"
            }
        )

        total = len(habit_defs)
        if total == 0:
            return 0

        habit_map = {h["id"]: h for h in habit_defs}

        # Get entries for that day
        entries = get(
            "habit_entries",
            {
                "user_id": f"eq.{user_id}",
                "plan_date": f"eq.{plan_date}"
            }
        )

        completed = 0

        for e in entries:
            habit = habit_map.get(e["habit_id"])
            if not habit:
                continue

            goal = float(habit.get("goal") or 0)
            value = float(e.get("value") or 0)

            if goal > 0 and value >= goal:
                completed += 1

        return completed

    except Exception as e:
        logger.warning(f"Health streak query failed: {e}")
        return 0

def parse_recurrence_block(text, default_date):
    text = text.lower()

    recurrence = {
        "type": None,
        "interval": None,
        "days_of_week": None,
        "start_date": default_date,
    }

    if m := re.search(STARTING_RE, text, re.I):
        try:
            recurrence["start_date"] = date.fromisoformat(m.group(1))
        except Exception:
            recurrence["start_date"] = default_date


    if re.search(EVERY_DAY_RE, text, re.I):
        recurrence["type"] = "daily"

    elif m := re.search(EVERY_WEEKDAY_RE, text, re.I):
        recurrence["type"] = "weekly"
        recurrence["days_of_week"] = [WEEKDAYS[m.group(1)]]

    elif m := re.search(INTERVAL_RE, text, re.I):
        recurrence["type"] = "interval"
        recurrence["interval"] = int(m.group(1))

    elif re.search(MONTHLY_RE, text, re.I):
        recurrence["type"] = "monthly"

    return recurrence
def group_slots_into_blocks(plans):
    blocks = []
    current = None

    for slot in sorted(plans.keys()):
        plan = (plans[slot].get("plan") or "").strip()
        if not plan:
            current = None
            continue

        if (
            current
            and current["text"] == plan
            and slot == current["end_slot"] + 1
        ):
            current["end_slot"] = slot
        else:
            current = {
                "text": plan,
                "start_slot": slot,
                "end_slot": slot,
                "status": plans[slot].get("status"),
                "recurring_id": plans[slot].get("recurring_id"),
            }
            blocks.append(current)

    return blocks
