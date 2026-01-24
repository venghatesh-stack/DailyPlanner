# services/timeline_service.py

from datetime import date
from supabase_client import get

def load_timeline_tasks(user_id):
    today = date.today().isoformat()

    rows = get(
    "project_tasks",
    params={
        "user_id": f"eq.{user_id}",
        "status": "neq.done",
        "select": "id,task_text,status,due_date,project_id,created_at",
        "order": "due_date.asc,created_at.asc",
    },
    ) or []


    today_tasks = []
    future_tasks = []

    for r in rows:
        due = r.get("due_date")

        if due == today:
            today_tasks.append(r)
        elif due and due > today:
            future_tasks.append(r)

    return today_tasks, future_tasks
