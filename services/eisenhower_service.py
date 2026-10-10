import logging

from supabase_client import get, post, update  

from config import TRAVEL_MODE_TASKS
from flask import session
logger = logging.getLogger(__name__)


# ==========================================================
# DATA ACCESS – EISENHOWER
# ==========================================================
# load_todo() and save_todo() lived here: the old form-post Eisenhower
# page's read and batch-save. Nothing has called them since /todo moved
# to per-task JSON routes, and save_todo wrote ids taken from the form
# without checking they belonged to the caller. Removed 2026-10-11.


# Retired: copy_open_tasks_from_previous_day. The previous implementation
# duplicated yesterday's un-done rows forward as a mutation, which
# distorted historical analytics (Monday's "N tasks done" became a lie
# after Tuesday's copy-forward) and had two bugs — a NameError from
# `user_id=session[user_id]` and a missing user_id scope on the
# prev_rows fetch (data-leak across users).
#
# The replacement pattern is the Morning Dashboard (/summary?view=daily),
# which shows overdue tasks as a READ-THROUGH view without mutation.
# That page is now the app's default landing page, so overdue surfaces
# naturally on first open. If you ever need the copy-forward semantics
# back, write them with proper user scoping + audit log + undo toast.


### Travel mode Code Changes ###
#
# Travel templates are stored per-user in the `travel_tasks` table.
# Run this migration once in Supabase before using the new UI:
#
#   create table if not exists travel_tasks (
#     id bigserial primary key,
#     user_id uuid not null,
#     category text not null default 'Default',
#     quadrant text not null default 'do',
#     task_text text not null,
#     subcategory text default 'General',
#     order_index int default 0,
#     created_at timestamptz default now()
#   );
#   create index if not exists travel_tasks_user_cat_idx
#     on travel_tasks (user_id, category);
#
# On first use for a given user, we lazy-seed this table with the
# hardcoded list from config.TRAVEL_MODE_TASKS under a default
# category named "Default".


def _seed_travel_tasks_if_empty(user_id):
    """First-run seeding: copy config.TRAVEL_MODE_TASKS into travel_tasks
    under category 'Default'. Idempotent — only seeds if user has zero rows."""
    existing = get(
        "travel_tasks",
        params={
            "user_id": f"eq.{user_id}",
            "select": "id",
            "limit": 1,
        },
    ) or []
    if existing:
        return 0

    payload = []
    for idx, (quadrant, text, subcat) in enumerate(TRAVEL_MODE_TASKS):
        payload.append({
            "user_id": user_id,
            "category": "Default",
            "quadrant": quadrant,
            "task_text": text,
            "subcategory": subcat,
            "order_index": idx,
        })
    if payload:
        try:
            post("travel_tasks", payload)
        except Exception as e:
            logger.warning("Travel-tasks seed failed: %s", e)
            return 0
    return len(payload)


def list_travel_categories(user_id):
    """Return sorted list of categories with task counts for a user."""
    _seed_travel_tasks_if_empty(user_id)
    rows = get(
        "travel_tasks",
        params={
            "user_id": f"eq.{user_id}",
            "select": "category",
            "limit": 5000,
        },
    ) or []
    counts = {}
    for r in rows:
        c = r.get("category") or "Default"
        counts[c] = counts.get(c, 0) + 1
    return [{"name": k, "count": v} for k, v in sorted(counts.items())]


def list_travel_tasks(user_id, category=None):
    _seed_travel_tasks_if_empty(user_id)
    params = {
        "user_id": f"eq.{user_id}",
        "select": "id,category,quadrant,task_text,subcategory,order_index",
        "order": "order_index.asc,id.asc",
        "limit": 5000,
    }
    if category:
        params["category"] = f"eq.{category}"
    return get("travel_tasks", params=params) or []


def enable_travel_mode(plan_date, category=None):
    """
    Insert Travel Mode tasks for the day from the user's configured
    travel_tasks table, optionally filtered by category.
    Idempotent: skips tasks already present on the target day.
    """
    user_id = session["user_id"]

    # Lazy seed (no-op if user already has rows)
    _seed_travel_tasks_if_empty(user_id)

    # Load template tasks from DB
    tpl_params = {
        "user_id": f"eq.{user_id}",
        "select": "quadrant,task_text,subcategory,order_index",
        "order": "order_index.asc,id.asc",
        "limit": 5000,
    }
    if category:
        tpl_params["category"] = f"eq.{category}"

    templates = get("travel_tasks", params=tpl_params) or []
    if not templates:
        return 0

    # Existing tasks for the target day — idempotency guard
    existing = (
        get(
            "todo_matrix",
            params={
                "user_id": f"eq.{user_id}",
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

    # Position seed per quadrant
    max_rows = (
        get(
            "todo_matrix",
            params={
                "user_id": f"eq.{user_id}",
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

    payload = []
    for t in templates:
        quadrant = t.get("quadrant") or "do"
        text = (t.get("task_text") or "").strip()
        if not text:
            continue

        key = (quadrant, text.lower())
        if key in existing_keys:
            continue

        pos = position_map.get(quadrant, -1) + 1
        position_map[quadrant] = pos

        payload.append({
            "plan_date": str(plan_date),
            "quadrant": quadrant,
            "task_text": text,
            "category": "Travel",
            "subcategory": t.get("subcategory") or "General",
            "is_done": False,
            "is_deleted": False,
            "position": pos,
            "user_id": user_id,
        })

    if payload:
        post("todo_matrix", payload)

    return len(payload)
def autosave_task(plan_date, task_id, quadrant, text=None, is_done=False, project_id=None):
    # -------------------------
    # NEW TASK → INSERT (Eisenhower direct entry)
    # -------------------------
    user_id=session["user_id"]
    if task_id.startswith("new_"):
        if not text:
            return {"id": task_id}

        rows = post(
            "todo_matrix?select=id",
            [{
                "plan_date": plan_date,
                "quadrant": quadrant,
                "task_text": text.strip(),
                "is_done": is_done,
                "is_deleted": False,
                "position": 999,
                "project_id": project_id,
                "user_id":user_id
            }],
            prefer="return=representation"
        ) or []

        if not rows:
            logger.error("Autosave insert failed for task: %s", task_id)
            return {"id": task_id}

        return {"id": str(rows[0]["id"])}

    # -------------------------
    # EXISTING TASK → DONE / UNDONE ONLY
    # -------------------------
    update(
        "todo_matrix",
        params={"id": f"eq.{task_id}","user_id":f"eq.{user_id}"},
        json={"is_done": is_done},
    )

    # -------------------------
    # 🔗 PROJECT SYNC (SAFE & ONE-WAY)
    # -------------------------
    if is_done:
        rows = get(
            "todo_matrix",
            params={
                "user_id":f"eq.{user_id}",
                "id": f"eq.{task_id}",
                "select": "source_task_id, recurring_instance_id",
            },
        )

        if not rows:
            return {"id": task_id}

        source_id = rows[0].get("source_task_id")
        recurring_instance_id = rows[0].get("recurring_instance_id")

        # ✅ Only non-recurring instances close the project task
        if source_id and not recurring_instance_id:
            update(
                "project_tasks",
                params={"task_id": f"eq.{source_id}","user_id":f"eq.{user_id}"},
                json={"status": "done"},
            )

    return {"id": task_id}
