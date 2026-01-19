import json
import re
from datetime import datetime,timedelta
from config import (
    META_SLOT,
    TOTAL_SLOTS,
    DEFAULT_STATUS,
)
from utils.slots import generate_half_hour_slots
import logging
from supabase_client import get, post, delete
from parsing.planner_parser import parse_planner_input


logger = logging.getLogger(__name__)
    
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
                "select": "slot,plan,status,priority,category,tags",
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
            "priority": r.get("priority"),
            "category": r.get("category"),
            "tags": row_tags,
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

    # Always preserve existing untimed tasks
    for t in existing_untimed:
        merged[t["id"]] = t

    # Add newly detected untimed tasks (smart planner)
    for t in auto_untimed:
        merged[t["id"]] = t

    # Add manually entered untimed tasks (if any)
    for t in new_untimed:
        merged[t["id"]] = t

    meta = {
        "habits": form.getlist("habits") or existing_meta.get("habits", []),
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
    
def build_slot_labels():
    labels = {}
    start = datetime.strptime("06:00", "%H:%M")
    for i in range(1, 49):
        end = start + timedelta(minutes=30)
        labels[i] = f"{start.strftime('%H:%M')} – {end.strftime('%H:%M')}"
        start = end
    return labels

SLOT_LABELS = build_slot_labels()
def get_daily_summary(plan_date):
    rows = get(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date}",
            "select": "slot,plan",
             "order": "slot.asc",
           
        },
    ) or []

    tasks = []
    habits = []
    reflection = ""

    for r in rows:
        slot = r.get("slot")
        plan = (r.get("plan") or "").strip()

        if slot == META_SLOT:
            try:
                meta = json.loads(plan or "{}")
                habits = meta.get("habits", [])
                reflection = meta.get("reflection", "")
            except Exception:
                pass
        else:
            if plan:
                tasks.append({
                    "slot": slot,
                    "label": SLOT_LABELS.get(slot),
                    "text": plan,
                })

    return {
        "tasks": tasks,
        "habits": habits,
        "reflection": reflection,
    }


# NOTE:
# Weekly summary is intentionally compact (day → tasks with time).
# Tag and priority aggregation is handled only in daily summary to avoid noise.
def get_weekly_summary(start_date, end_date):
    rows = get(
        "daily_slots",
        params={
            "plan_date": f"gte.{start_date}",
            "plan_date": f"lte.{end_date}",
            "select": "plan_date,slot,plan",
            "order": "plan_date.asc,slot.asc",
        },
    ) or []

    weekly = {}

    for row in rows:
        plan_date = row["plan_date"]
        plan = (row.get("plan") or "").strip()

        if not plan:
            continue

        weekly.setdefault(plan_date, []).append(plan)

    return weekly



