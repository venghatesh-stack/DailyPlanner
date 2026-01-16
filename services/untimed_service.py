import json
from supabase_client import get, update
META_SLOT = "__meta__"
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
  row = rows[0]


  meta = json.loads(row.get("plan") or "{}")

  cleaned = []

  for t in meta.get("untimed_tasks", []):
      if isinstance(t, str):
          # Legacy string → skip only if text matches
          if f"legacy_{hash(t)}" != task_id:
              cleaned.append({
                  "id": f"legacy_{hash(t)}",
                  "text": t
              })
      else:
          if t.get("id") != task_id:
              cleaned.append(t)

  meta["untimed_tasks"] = cleaned


  update(
      "daily_slots",
      params={
          "plan_date": f"eq.{plan_date}",
          "slot": f"eq.{META_SLOT}",
      },
      json={"plan": json.dumps(meta)},
  )