# services/timeline_service.py

from supabase_client import get
# services/timeline_service.py
from  datetime import date 
def load_timeline_tasks(user_id):
    today = date.today()

    rows = get(
        "project_tasks",
        params={
            "user_id": f"eq.{user_id}",
            # ⬇️ fetch ALL, filter in Python (Supabase-safe)
            "select": "id,task_text,status,due_date,project_id,created_at",
            "order": "created_at.asc",
        },
    ) or []

    today_tasks = []
    future_tasks = {}

    for r in rows:
        # ❌ ignore done tasks in Python
        if r.get("status") == "done":
            continue

        due = r.get("due_date")
        if not due:
            continue

        due_date = date.fromisoformat(due)

        if due_date == today:
            today_tasks.append(r)
        elif due_date > today:
            future_tasks.setdefault(due, []).append(r)

    # Python-side sorting (safe)
    today_tasks.sort(key=lambda x: x["created_at"])
    for d in future_tasks:
        future_tasks[d].sort(key=lambda x: x["created_at"])

    return today_tasks, future_tasks

