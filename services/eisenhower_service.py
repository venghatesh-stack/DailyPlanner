import logging
from supabase_client import get, post, update  
from datetime import timedelta
from config import TRAVEL_MODE_TASKS
logger = logging.getLogger(__name__)


# ==========================================================
# DATA ACCESS – EISENHOWER
# ==========================================================
def load_todo(plan_date):
    # ----------------------------
    # Load today's todo items
    # ----------------------------
    rows = (
        get(
            "todo_matrix",
            params={
                "plan_date": f"eq.{plan_date}",
                "is_deleted": "eq.false",
                "select": (
                    "id,quadrant,task_text,is_done,position,"
                    "task_date,task_time,recurring_id,"
                    "category,subcategory"
                ),
            },
        )
        or []
    )

    # ----------------------------
    # Load recurrence metadata
    # ----------------------------
    recurring_rows = (
        get(
            "recurring_tasks",
            params={"is_active": "eq.true", "select": "id,recurrence"},
        )
        or []
    )

    recurring_map = {r["id"]: r.get("recurrence") for r in recurring_rows}

    # ----------------------------
    # Build quadrant buckets
    # ----------------------------
    data = {"do": [], "schedule": [], "delegate": [], "eliminate": []}

    for r in rows:
        data[r["quadrant"]].append(
            {
                "id": r["id"],
                "text": r["task_text"],
                "done": bool(r.get("is_done")),
                "task_date": r.get("task_date"),
                "task_time": r.get("task_time"),
                "recurring": bool(r.get("recurring_id")),
                "recurrence": recurring_map.get(r.get("recurring_id")),
                "category": r.get("category") or "General",
                "subcategory": r.get("subcategory") or "General",
            }
        )

    # ----------------------------
    # Sort within each quadrant
    # ----------------------------
    for q in data:
        data[q].sort(
        key=lambda t: (
                t["task_date"] is None,
                t["task_date"] or "",
                t["task_time"] is None,
                t["task_time"] or "",
            )
        )

    ### Category, Sub Category Changes start here ###

    grouped = {}

    for q in data:
        grouped[q] = {}
        for t in data[q]:
            cat = t["category"]
            sub = t["subcategory"]
            grouped[q].setdefault(cat, {}).setdefault(sub, []).append(t)

    return grouped


### Category, Subcategory code ends here ###
def save_todo(plan_date, form):
    logger.info("Saving Eisenhower matrix (batched)")

    existing_rows = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{plan_date}",
            "is_deleted": "eq.false",
            "select": "id,recurring_id",
        },
    ) or []

    existing_ids = {str(r["id"]) for r in existing_rows}
    existing_recurring_map = {
        str(r["id"]): r.get("recurring_id") for r in existing_rows
    }

    updates = []
    inserts = []
    deleted_ids = set()

    # -----------------------------------
    # Process quadrants
    # -----------------------------------
    for quadrant in ["do", "schedule", "delegate", "eliminate"]:
        texts = form.getlist(f"{quadrant}[]")
        ids = form.getlist(f"{quadrant}_id[]")
        dates = form.getlist(f"{quadrant}_date[]")
        times = form.getlist(f"{quadrant}_time[]")
        categories = form.getlist(f"{quadrant}_category[]")
        subcategories = form.getlist(f"{quadrant}_subcategory[]")

        # ---- DONE STATE ----
        done_state = {}
        for k, v in form.to_dict(flat=False).items():
            if k.startswith(f"{quadrant}_done_state["):
                tid = k[len(f"{quadrant}_done_state["):-1]
                done_state[tid] = v

        # ---- DELETE STATE ----
        deleted_map = {}
        for k, v in form.to_dict(flat=False).items():
            if k.startswith(f"{quadrant}_deleted["):
                tid = k[len(f"{quadrant}_deleted["):-1]
                deleted_map[tid] = v[-1]

        # ---- ITERATE TASKS ----
        for idx, text in enumerate(texts):
            if idx >= len(ids):
                continue

            task_id = str(ids[idx])

            # ✅ AUTHORITATIVE DELETE
            if deleted_map.get(task_id) == "1":
                deleted_ids.add(task_id)
                continue

            text = (text or "").strip()
            if not text:
                continue

            payload = {
                "quadrant": quadrant,
                "task_text": text,
                "task_date": (
                  dates[idx] if idx < len(dates) and dates[idx]
                  else str(plan_date)),
                "task_time": (
                  times[idx] if idx < len(times) and times[idx]
                  else None
                ),
                "is_done": "1" in done_state.get(task_id, []),
                "position": idx,
                "is_deleted": False,
                "category": categories[idx] if idx < len(categories) else "General",
                "subcategory": subcategories[idx] if idx < len(subcategories) else "General",
            }

            # ✅ UPDATE vs INSERT (INSIDE LOOP)
            if task_id in existing_ids:
                update_row = {
                    "id": task_id,
                    "plan_date": str(plan_date),
                    **payload,
                }

                rid = existing_recurring_map.get(task_id)
                if rid:
                    update_row["recurring_id"] = rid

                updates.append(update_row)
            else:
                inserts.append({
                    "plan_date": str(plan_date),
                    **payload,
                })

    # -----------------------------------
    # WRITE CHANGES
    # -----------------------------------
    if updates:
        post(
            "todo_matrix?on_conflict=id",
            updates,
            prefer="resolution=merge-duplicates",
        )

    if inserts:
      for r in inserts:
        if not r.get("task_date"):
            r["task_date"] = str(plan_date)

      post("todo_matrix", inserts)

    if deleted_ids:
        update(
            "todo_matrix",
            params={"id": f"in.({','.join(deleted_ids)})"},
            json={"is_deleted": True},
        )

    logger.info(
        "Eisenhower save complete: %d updates, %d inserts, %d deletions",
        len(updates),
        len(inserts),
        len(deleted_ids),
    )


def copy_open_tasks_from_previous_day(plan_date):
    prev_date = plan_date - timedelta(days=1)

    prev_rows = (
        get(
            "todo_matrix",
            params={
                "plan_date": f"eq.{prev_date}",
                "is_deleted": "eq.false",
                "select": "quadrant,task_text,is_done,task_date,task_time,category,subcategory",
            },
        )
        or []
    )

    if not prev_rows:
        return 0

    today_rows = (
        get(
            "todo_matrix",
            params={
                "plan_date": f"eq.{plan_date}",
                "select": "quadrant,task_text,position",
                "is_deleted": "eq.false",
            },
        )
        or []
    )

    today_tasks = {
        (r["quadrant"], (r["task_text"] or "").strip().lower()) for r in today_rows
    }

    # Build max position per quadrant ONCE
    max_pos = {}
    for r in today_rows:
        q = r["quadrant"]
        max_pos[q] = max(max_pos.get(q, -1), r.get("position", -1))

    payload = []

    for r in prev_rows:
        if r.get("is_done"):
            continue

        key = (r["quadrant"], (r["task_text"] or "").strip().lower())
        if key in today_tasks:
            continue

        next_pos = max_pos.get(r["quadrant"], -1) + 1
        max_pos[r["quadrant"]] = next_pos

        payload.append(
            {
                "plan_date": str(plan_date),
                "quadrant": r["quadrant"],
                "task_text": r["task_text"],
                "is_done": False,
                "is_deleted": False,  # 👈 REQUIRED
                "task_date": r.get("task_date") or str(plan_date),
                "task_time": r.get("task_time"),
                "position": next_pos,
                "category": r.get("category") or "General",
                "subcategory": r.get("subcategory") or "General",
            }
        )

    if payload:
        post("todo_matrix", payload)

    return len(payload)


### Travel mode Code Changes ###


def enable_travel_mode(plan_date):
    """
    Insert Travel Mode tasks for the day.
    Idempotent: inserts only missing tasks.
    """

    existing = (
        get(
            "todo_matrix",
            params={
                "plan_date": f"eq.{plan_date}",
                "is_deleted": "eq.false",
                "select": "quadrant,task_text",
            },
        )
        or []
    )

    existing_keys = {
        (r["quadrant"], (r["task_text"] or "").strip().lower()) for r in existing
    }

    payload = []
    max_rows = (
        get(
            "todo_matrix",
            params={
                "plan_date": f"eq.{plan_date}",
                "is_deleted": "eq.false",
                "select": "quadrant,position",
            },
        )
        or []
    )

    position_map = {}
    for r in max_rows:
        q = r["quadrant"]
        position_map[q] = max(position_map.get(q, -1), r.get("position", -1))

    for quadrant, text, subcat in TRAVEL_MODE_TASKS:
        key = (quadrant, text.lower())
        if key in existing_keys:
            continue

        pos = position_map.get(quadrant, -1) + 1
        position_map[quadrant] = pos

        ### Category, Sub Category Changes start here ###

        payload.append(
            {
                "plan_date": str(plan_date),
                "quadrant": quadrant,
                "task_text": text,
                "category": "Travel",
                "subcategory": subcat,
                "is_done": False,
                "is_deleted": False,
                "position": pos,
            }
        )

        ### Category, Subcategory code ends here ###

    if payload:
        post("todo_matrix", payload)

    return len(payload)

