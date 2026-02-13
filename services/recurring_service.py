import calendar
from datetime import date   
from supabase_client import get, post
from config import TOTAL_SLOTS,DEFAULT_STATUS
def matches_recurrence(rule, target_date):
    start = date.fromisoformat(rule["start_date"])

    if target_date < start:
        return False

    if rule.get("end_date") and target_date > date.fromisoformat(rule["end_date"]):
        return False

    rtype = rule["recurrence_type"]

    if rtype == "daily":
        return True

    if rtype == "weekly":
        return target_date.weekday() in (rule["days_of_week"] or [])

    if rtype == "interval":
        delta = (target_date - start).days
        return delta % rule["interval_value"] == 0

    if rtype == "monthly":
        return target_date.day == start.day

    return False

def materialize_recurring_tasks(plan_date,user_):
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
                "task_date": str(plan_date),
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
def materialize_recurring_slots(plan_date, user_id):
    rules = get(
        "recurring_slots",
        params={
            "user_id": f"eq.{user_id}",
            "is_active": "eq.true",
            "start_date": f"lte.{plan_date}",
            "or": f"(end_date.is.null,end_date.gte.{plan_date})",
        },
    ) or []

    payload = []

    for rule in rules:
        if not matches_recurrence(rule, plan_date):
            continue

        for i in range(rule["slot_count"]):
            slot = rule["start_slot"] + i
            if 1 <= slot <= TOTAL_SLOTS:
                payload.append({
                    "plan_date": str(plan_date),
                    "slot": slot,
                    "plan": rule["title"],
                    "status": DEFAULT_STATUS,
                })

    if payload:
        post(
            "daily_slots?on_conflict=plan_date,slot",
            payload,
            prefer="resolution=ignore-duplicates",
        )
# ==========================================================
# TIMELINE — PROJECT TASKS
# ==========================================================

def normalize_timeline_task(t, project_name=None):
    return {
        "task_id": t["task_id"],
        "task_text": t["task_text"],
        "project_id": t.get("project_id"),
        "project_name": project_name,
        "due_date": t.get("due_date"),
        "start_date": t.get("start_date"),
        "status": t.get("status"),
    }


def load_timeline_tasks(user_id, project_id=None):
    """
    Load project tasks for timeline rendering.
    Supports optional project filter.
    """

    # -----------------------------
    # Load projects for name map
    # -----------------------------
    projects = get(
        "projects",
        params={
            "user_id": f"eq.{user_id}",
            "select": "project_id,name"
        }
    ) or []

    project_map = {
        p["project_id"]: p["name"]
        for p in projects
    }

    # -----------------------------
    # Build task query
    # -----------------------------
    params = {
        "user_id": f"eq.{user_id}",
        "is_eliminated": "eq.false",
        "select": "task_id,task_text,project_id,start_date,due_date,status",
        "order": "due_date.asc"
    }

    if project_id:
        params["project_id"] = f"eq.{project_id}"

    rows = get("project_tasks", params=params) or []

    tasks = []

    for t in rows:
        if not (t.get("due_date") or t.get("start_date")):
            continue  # timeline requires date anchor

        tasks.append(
            normalize_timeline_task(
                t,
                project_map.get(t.get("project_id"))
            )
        )

    return tasks
