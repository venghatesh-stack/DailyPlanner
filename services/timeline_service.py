# services/timeline_service.py


from supabase_client import get
# services/timeline_service.py
from  datetime import date 
# services/timeline_service.py

# ==========================================================
# TIMELINE — PROJECT TASK LOADER
# ==========================================================

def load_timeline_tasks(user_id, project_id=None):
    """
    Load project tasks for timeline rendering.
    Supports optional project filter.
    """

    # -----------------------------
    # Load projects → name map
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
            continue

        tasks.append({
            "task_id": t["task_id"],
            "task_text": t["task_text"],
            "project_id": t.get("project_id"),
            "project_name": project_map.get(t.get("project_id")),
            "start_date": t.get("start_date"),
            "due_date": t.get("due_date"),
            "status": t.get("status"),
        })

    return tasks


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
