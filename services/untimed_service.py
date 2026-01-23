import json
from supabase_client import get, post
from config import DEFAULT_STATUS,META_SLOT

def remove_untimed_task(plan_date, task_id):
    rows = get(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date}",
            "slot": f"eq.{META_SLOT}",
            "select": "plan",
        },
    )

    if not rows:
        return

    meta = json.loads(rows[0].get("plan") or "{}")

    cleaned = []

    for t in meta.get("untimed_tasks", []):
        if isinstance(t, str):
            # Legacy string → reconstruct ID and compare
            legacy_id = f"legacy_{hash(t)}"
            if legacy_id != task_id:
                cleaned.append({
                    "id": legacy_id,
                    "text": t
                })
        else:
            if t.get("id") != task_id:
                cleaned.append(t)

    meta["untimed_tasks"] = cleaned

    # 🔑 ALWAYS UPSERT META_SLOT
    post(
        "daily_slots?on_conflict=plan_date,slot",
        {
            "plan_date": str(plan_date),
            "slot": META_SLOT,
            "plan": json.dumps(meta),
            "status": DEFAULT_STATUS,
        },
        prefer="resolution=merge-duplicates",
    )
