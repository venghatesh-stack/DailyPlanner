
from supabase_client import get, update
def remove_untimed_task(user_id, plan_date, task_id):
    rows = get(
        "daily_meta",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date}",
            "select": "untimed_tasks",
        },
    )

    if not rows:
        return

    meta = rows[0]
    existing = meta.get("untimed_tasks") or []

    cleaned = []

    for t in existing:
        # Defensive: tolerate legacy formats just in case
        if isinstance(t, str):
            legacy_id = f"legacy_{hash(t)}"
            if legacy_id != task_id:
                cleaned.append({
                    "id": legacy_id,
                    "text": t,
                })
        else:
            if t.get("id") != task_id:
                cleaned.append(t)

    update(
        "daily_meta",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": str(plan_date),
        },
        data={
            "untimed_tasks": cleaned,
        },
    )
