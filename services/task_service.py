from datetime import date
from supabase_client import post, update    

def occurs_on(task: dict, target_date: date) -> bool:
    if not task["is_recurring"]:
        return task["task_date"] == target_date

    if task.get("recurrence_end") and target_date > task["recurrence_end"]:
        return False

    if task["recurrence_type"] == "daily":
        return True

    if task["recurrence_type"] == "weekly":
        return target_date.weekday() in (task.get("recurrence_days") or [])

    if task["recurrence_type"] == "monthly":
        return task["task_date"].day == target_date.day

    return False
def complete_task_occurrence(user_id, task_id, task_date):
    return post(
        "task_overrides",
        {
            "user_id": user_id,
            "task_id": task_id,
            "task_date": task_date,
            "status": "done"
        }
    )
def skip_task_occurrence(user_id, task_id, task_date):
    return post(
        "task_overrides",
        {
            "user_id": user_id,
            "task_id": task_id,
            "task_date": task_date,
            "status": "skipped"
        }
    )
def update_task_occurrence(user_id, task_id, task_date, title=None, status=None):
    payload = {}
    if title is not None:
        payload["title"] = title
    if status is not None:
        payload["status"] = status

    return post(
        "task_overrides",
        {
            "user_id": user_id,
            "task_id": task_id,
            "task_date": task_date,
            **payload
        }
    )
def update_task(user_id, task_id, updates: dict):
    return update(
        "project_tasks",
        params={
            "id": f"eq.{task_id}",
            "user_id": f"eq.{user_id}"
        },
        json=updates
    )
def create_task(user_id, payload):
    return post(
        "project_tasks",
        {
            "user_id": user_id,
            **payload
        }
    )
