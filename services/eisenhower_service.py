import logging

from supabase_client import get, post, update  

from datetime import timedelta ,datetime
from config import TRAVEL_MODE_TASKS
from flask import session
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
    moved_count = 0
    moved_dates = set()
    task_ids = [
      v for k, v in form.items()
      if k.endswith("_id[]") and not v.startswith("new_")
    ]
    existing_rows = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{plan_date}",
            "is_deleted": "eq.false",
            "select": "id,plan_date,recurring_id",
        },
    ) or []
    

    existing_ids = {str(r["id"]) for r in existing_rows}
    existing_recurring_map = {
        str(r["id"]): r.get("recurring_id") for r in existing_rows
    }
    original_dates = {
    str(r["id"]): datetime.fromisoformat(r["plan_date"]).date()
    for r in existing_rows
    }
    updates = []
    inserts = []
    # ==================================================
    # AUTHORITATIVE DELETE PASS (MUST BE FIRST)
    # ==================================================
    deleted_ids = set()
    for k, v in form.to_dict(flat=False).items():
        if "_deleted[" in k and v[-1] == "1":
            task_id = k.split("[", 1)[1].rstrip("]")
            deleted_ids.add(task_id)

    if deleted_ids:
        # --------------------------------------------------
        # NEVER update rows deleted in this request
        # --------------------------------------------------
    

        safe_deleted_ids = [
        i for i in deleted_ids if not i.startswith("new_")
        ]

        if safe_deleted_ids:
        
            update(
                "todo_matrix",
                params={"id": f"in.({','.join(safe_deleted_ids)})"},
                json={"is_deleted": True},
            )

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

       
        
        # ---- ITERATE TASKS ----
        for idx, text in enumerate(texts):
            if idx >= len(ids):
                continue

            task_id = str(ids[idx])

            # ✅ AUTHORITATIVE DELETE
            if task_id in deleted_ids:
                continue

            text = (text or "").strip()
            if not text:
                continue
            task_plan_date = (
                datetime.strptime(dates[idx], "%Y-%m-%d").date()
                if idx < len(dates) and dates[idx]
                else plan_date
            )
            original_date = original_dates.get(task_id, plan_date)
            if original_date and task_plan_date != original_date:
                moved_count += 1
                moved_dates.add(task_plan_date)


            payload = {
                "quadrant": quadrant,
                "task_text": text,
                "task_date": (
                  dates[idx] if idx < len(dates) and dates[idx]
                  else str(task_plan_date )),
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
            # -------------------------------
            # NEW TASKS → ALWAYS INSERT
            # -------------------------------
            if task_id.startswith("new_"):
                continue #autosave already handled it. 


            # -------------------------------
            # EXISTING TASKS → UPDATE
            # -------------------------------
            elif task_id in existing_ids:
                update_row = {
                    "id": task_id,
                    "plan_date": str(task_plan_date ),
                    **payload,
                }

                rid = existing_recurring_map.get(task_id)
                if rid:
                    update_row["recurring_id"] = rid

                updates.append(update_row)
            else:
                # SAFETY FALLBACK — treat as new
                if task_id.startswith("new_"):
                 continue

                inserts.append({
                    "plan_date": str(task_plan_date ),
                    **payload,
                })

    # -----------------------------------
    # WRITE CHANGES
    # -----------------------------------
    updates = [
                u for u in updates
                if str(u.get("id")) not in deleted_ids
        ]
   
    if updates:
        post(
            "todo_matrix?on_conflict=id",
            updates,
            prefer="resolution=merge-duplicates",
        )



    # -----------------------------------
    # DEDUPE INSERTS (autosave safety)
    # -----------------------------------
    seen = set()
    deduped_inserts = []

    for r in inserts:
        key = (
            r["plan_date"],
            r["quadrant"],
            r["task_text"].strip(),
            r.get("category"),
            r.get("subcategory"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped_inserts.append(r)

    inserts = deduped_inserts
    if inserts:
        for r in inserts:
            if not r.get("task_date"):
                r["task_date"] = str(plan_date)

        post("todo_matrix", inserts)


    if moved_count:
        parts = []
        for d, count in sorted(moved_by_date.items()):
            parts.append(f"{count} task{'s' if count > 1 else ''} → {d.strftime('%d %b')}")
        session["toast"] = {
        "type": "info",
        "message": (
            f"📅 {moved_count} task(s) moved to "
            + ", ".join(sorted(d.strftime('%d %b %Y') for d in moved_dates))
        ),
    }

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

def autosave_task(plan_date, task_id, quadrant, text, is_done):
    text = (text or "").strip()
    if not text:
        return {"id": task_id}

    # NEW TASK → INSERT ONCE
    if task_id.startswith("new_"):
        rows = post(
            "todo_matrix?select=id",
            [{
                "plan_date": plan_date,
                "quadrant": quadrant,
                "task_text": text,
                "is_done": is_done,
                "is_deleted": False,
                "position": 999,
            }],
            prefer="return=representation"
        ) or []

        if not rows or "id" not in rows[0]:
            logger.error("Autosave insert failed for task: %s", task_id)
            return {"id": task_id}

        return {"id": str(rows[0]["id"])}

    # EXISTING TASK → UPDATE
    update(
        "todo_matrix",
        params={"id": f"eq.{task_id}"},
        json={
            "task_text": text,
            "is_done": is_done,
        },
    )

    return {"id": task_id}
