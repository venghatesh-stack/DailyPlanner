# services/timeline_service.py

from datetime import date
from collections import defaultdict
from supabase_client import get


def load_timeline_tasks(user_id):
    today = date.today().isoformat()

    rows = get(
        "project_tasks",
        params={
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
            "order": "due_date.asc.nullslast,created_at.asc",
            "select": "id,task_text,status,due_date,project_id"
        }
    ) or []

    today_tasks = []
    future_tasks = defaultdict(list)

    for t in rows:
        due = t.get("due_date")

        if not due or due <= today:
            today_tasks.append(t)
        else:
            future_tasks[due].append(t)

    return today_tasks, dict(future_tasks)
