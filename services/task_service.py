from datetime import date, timedelta
from supabase_client import post, update    
import calendar
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


def compute_next_occurrence(task: dict, from_date: date) -> date | None:
    """
    Given a recurring task and the date it was completed on,
    return the next occurrence date.
    """

    rtype = task.get("recurrence_type")
    interval = int(task.get("recurrence_interval") or 1)

    if rtype == "daily":
        return from_date + timedelta(days=interval)

    if rtype == "weekly":
        days = sorted(task.get("recurrence_days") or [])
        if not days:
            return None

        today_wd = from_date.weekday()

        # find next weekday in the same week
        for d in days:
            if d > today_wd:
                return from_date + timedelta(days=(d - today_wd))

        # otherwise jump to next interval week
        next_week_start = from_date + timedelta(days=(7 * interval))
        return next_week_start + timedelta(days=(days[0] - next_week_start.weekday()))

    if rtype == "monthly":
        year = from_date.year
        month = from_date.month + interval

        # normalize year/month
        while month > 12:
            month -= 12
            year += 1

        day = min(
            from_date.day,
            calendar.monthrange(year, month)[1]
        )

        return date(year, month, day)

    return None
