# services/timeline_service.py


from supabase_client import get
# services/timeline_service.py
from  datetime import date 
# services/timeline_service.py
from datetime import date
from supabase_client import get
from datetime import date
from flask import request
from supabase_client import get

def load_timeline_tasks(user_id):
    today = date.today()

    hide_completed = request.args.get("hide_completed", "1") == "1"
    overdue_only   = request.args.get("overdue_only", "0") == "1"

    rows = get(
        "project_tasks",
        params={
            "user_id": f"eq.{user_id}",
            "select": """
                task_id,
                task_text,
                status,
                due_date,
                start_date,
                project_id,
                created_at,
                is_recurring,
                recurrence_type,
                recurrence_days
            """,
            "order": "created_at.asc",
        },
    ) or []

    today_tasks = []
    future_tasks = {}

    for r in rows:
        # 1️⃣ Hide completed
        if hide_completed and r.get("status") == "done":
            continue

        due = r.get("due_date")
        if not due:
            continue

        due_date = date.fromisoformat(due)

        # 2️⃣ Overdue-only filter
        if overdue_only and due_date >= today:
            continue

        # 3️⃣ Attach recurrence badge
        r["recurrence_badge"] = build_recurrence_badge(r)

        # 4️⃣ Grouping
        if due_date == today:
            today_tasks.append(r)
        elif due_date > today:
            future_tasks.setdefault(due, []).append(r)

    # Sorting
    today_tasks.sort(key=lambda x: x["created_at"])
    for d in future_tasks:
        future_tasks[d].sort(key=lambda x: x["created_at"])

    return today_tasks, future_tasks



def build_recurrence_badge(task):
    rtype = task.get("recurrence_type")

    if rtype == "daily":
        return "🔁 Daily"

    if rtype == "weekly":
        days = task.get("recurrence_days") or []
        names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
        short = " ".join(names[d] for d in days)
        return f"🔁 {short}"

    if rtype == "monthly":

     if task.get("start_date"):
        d = task["start_date"]
        if isinstance(d, str):
            d = date.fromisoformat(d)
        return f"🔁 Monthly · {d.day}"


    return None
