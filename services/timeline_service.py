# services/timeline_service.py

from datetime import date
from supabase_client import get

from datetime import date

def load_timeline_tasks(user_id):
    today = date.today()

    rows = get(
        "project_tasks",
        params={
            "user_id": f"eq.{user_id}",
            "status": "neq.done",
            "select": "id,task_text,status,due_date,project_id,created_at",
            # ❌ NO order on nullable columns
            "order": "created_at.asc",
        },
    ) or []

    today_tasks = []
    future_tasks = []

    for r in rows:
        due = r.get("due_date")

        if not due:
            # no date → ignore for timeline
            continue

        due_date = date.fromisoformat(due)

        if due_date == today:
            today_tasks.append(r)
        elif due_date > today:
            future_tasks.append(r)

    # ✅ Explicit sorting in Python
    today_tasks.sort(key=lambda x: x["created_at"])
    future_tasks.sort(key=lambda x: x["due_date"])

    return today_tasks, future_tasks
