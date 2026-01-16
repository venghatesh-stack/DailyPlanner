import calendar
from datetime import date   
from supabase_client import get, post

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
