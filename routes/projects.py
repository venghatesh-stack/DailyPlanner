
from datetime import date, timedelta
import json
import logging

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from config import PRIORITY_MAP, SIMPLE_GOALS, SORT_PRESETS
from utils.user_tz import user_now, user_today
from routes.todo import group_tasks_smart

# Module-level logger. The project has a `logger.py` module that exports a
# setup_logger() factory, so we can't `import logger` and call logger.info()
# — that'd be calling a method on the module itself. Use Python's stdlib
# logging directly against the shared "daily_plan" name.
logger = logging.getLogger("daily_plan")
from services.gantt_service import build_gantt_tasks
from services.login_service import login_required
from services.task_service import complete_task_occurrence, compute_next_occurrence
from supabase_client import get, post, update

projects_bp = Blueprint("projects", __name__)


# ─────────────────────────────────────────────────────────────────
# Default OKR > KR > Initiative > Epic trio per project.
#
# Tasks without an explicit epic always fall through to this default
# epic. The trio is created lazily on project insert and also auto-
# heals on first task add (so an in-flight migration or a manually
# inserted project still gets defaults).
#
# The migration MIGRATION_DEFAULT_OKR_TRIO.sql backfills every existing
# project. Below mirrors that logic for the post-deploy path.
# ─────────────────────────────────────────────────────────────────

def _ensure_default_okr_trio(user_id, project_id):
    """Return the default epic_id for this project, creating the
    Inbox > Catch-all > Inbox > Inbox chain if any link is missing.
    Idempotent — runs at most one extra SELECT when the trio already
    exists, no inserts."""
    try:
        objs = get(
            "objectives",
            params={
                "user_id":    f"eq.{user_id}",
                "project_id": f"eq.{project_id}",
                "is_default": "eq.true",
                "is_deleted": "eq.false",
                "select":     "id",
                "limit":      1,
            },
        ) or []
        if objs:
            obj_id = objs[0]["id"]
        else:
            row = post("objectives", {
                "user_id":     user_id,
                "project_id":  project_id,
                "title":       "Uncategorized",
                "is_default":  True,
                "status":      "active",
                "time_horizon": "ongoing",
            })
            obj_id = (row or [{}])[0].get("id") if row else None
            if not obj_id:
                return None

        krs = get(
            "key_results",
            params={
                "user_id":      f"eq.{user_id}",
                "objective_id": f"eq.{obj_id}",
                "is_default":   "eq.true",
                "is_deleted":   "eq.false",
                "select":       "id",
                "limit":        1,
            },
        ) or []
        if krs:
            kr_id = krs[0]["id"]
        else:
            row = post("key_results", {
                "user_id":      user_id,
                "objective_id": obj_id,
                "title":        "—",
                "target_value": 100,
                "unit":         "%",
                "is_default":   True,
            })
            kr_id = (row or [{}])[0].get("id") if row else None
            if not kr_id:
                return None

        inits = get(
            "initiatives",
            params={
                "user_id":       f"eq.{user_id}",
                "key_result_id": f"eq.{kr_id}",
                "is_default":    "eq.true",
                "is_deleted":    "eq.false",
                "select":        "id",
                "limit":         1,
            },
        ) or []
        if inits:
            init_id = inits[0]["id"]
        else:
            row = post("initiatives", {
                "user_id":       user_id,
                "key_result_id": kr_id,
                "title":         "General",
                "is_default":    True,
                "status":        "active",
            })
            init_id = (row or [{}])[0].get("id") if row else None
            if not init_id:
                return None

        eps = get(
            "epics",
            params={
                "user_id":       f"eq.{user_id}",
                "initiative_id": f"eq.{init_id}",
                "is_default":    "eq.true",
                "is_deleted":    "eq.false",
                "select":        "id",
                "limit":         1,
            },
        ) or []
        if eps:
            return eps[0]["id"]
        row = post("epics", {
            "user_id":       user_id,
            "initiative_id": init_id,
            "title":         "Misc",
            "is_default":    True,
            "status":        "active",
        })
        return (row or [{}])[0].get("id") if row else None
    except Exception:
        logger.exception("ensure default trio failed for project %s", project_id)
        return None


def _default_epic_id(user_id, project_id):
    """Resolve the default epic for this project. Always safe to call —
    creates any missing link in the chain (ensure helper is idempotent
    when the trio is already present)."""
    return _ensure_default_okr_trio(user_id, project_id)

import re as _re_color

#: A project colour is a plain hex. It goes into inline styles, so nothing
#: else (no url(), no var(), no expressions) is ever accepted or rendered.
_PROJECT_COLOR_RE = _re_color.compile(r"#[0-9a-fA-F]{6}")


def _clean_project_color(value):
    value = (value or "").strip()
    return value.lower() if _PROJECT_COLOR_RE.fullmatch(value) else None


@projects_bp.route("/projects")
@login_required
def projects():
    user_id = session["user_id"]

    include_archived = request.args.get("include_archived", "0") == "1"

    params = {
        "user_id": f"eq.{user_id}",
        "order": "created_at.asc",
    }
    if not include_archived:
        params["is_archived"] = "eq.false"

    projects = get("projects", params=params) or []
    # The card puts the colour straight into a style attribute, so only a
    # plain #rrggbb is let through — whatever is in the column.
    for p in projects:
        p["color"] = _clean_project_color(p.get("color"))

    # Batch-fetch task counts for all projects in one query
    if projects:
        ids_str = ",".join(str(p["project_id"]) for p in projects)
        all_tasks = get("project_tasks", params={
            "project_id": f"in.({ids_str})",
            "is_eliminated": "eq.false",
            # Trashed work must not sit in the denominator either, or a
            # project's completion percentage counts tasks the user has
            # explicitly put in the bin.
            "status": _NOT_LIVE_FILTER,
            # Dates come along so the card can say WHEN, not just how
            # much. Measured 2026-08-30: 55 of 103 live tasks were
            # overdue and this page could not say so — two projects sat
            # at "3% · 29 remaining" in the same yellow as a project
            # started yesterday.
            "select": "project_id,status,due_date,revised_due_date",
        }) or []

        today_iso = user_today().isoformat()
        task_counts, done_counts = {}, {}
        overdue_counts, next_due = {}, {}
        for t in all_tasks:
            pid = t["project_id"]
            task_counts[pid] = task_counts.get(pid, 0) + 1
            if t["status"] == "done":
                done_counts[pid] = done_counts.get(pid, 0) + 1
                continue
            # EFFECTIVE DUE DATE — copied from agenda_service, not
            # reinvented: revised_due_date is the user's current intent
            # and due_date is the original. Three different answers to
            # "what is overdue" is exactly the bug this codebase has
            # already paid for once.
            eff = t.get("revised_due_date") or t.get("due_date")
            if not eff:
                continue
            eff = str(eff)[:10]
            if eff < today_iso:
                overdue_counts[pid] = overdue_counts.get(pid, 0) + 1
            elif pid not in next_due or eff < next_due[pid]:
                next_due[pid] = eff

        for p in projects:
            pid = p["project_id"]
            total = task_counts.get(pid, 0)
            done = done_counts.get(pid, 0)
            p["task_count"] = total
            p["done_count"] = done
            p["open_count"] = total - done
            p["overdue_count"] = overdue_counts.get(pid, 0)
            p["next_due"] = next_due.get(pid)
            p["completion_pct"] = round(done / total * 100) if total else 0

    return render_template(
        "projects.html",
        projects=projects,
        include_archived=include_archived,
    )

@projects_bp.route("/projects/<project_id>/set-sort", methods=["POST"])
@login_required
def set_project_sort(project_id):
    data = request.get_json() or {}
    sort = data.get("sort")

    if not sort:
        return jsonify({"error": "Missing sort"}), 400

    update(
        "projects",
        params={"project_id": f"eq.{project_id}", "user_id": f"eq.{session['user_id']}"},
        json={"default_sort": sort}
    )

    return jsonify({"status": "ok"})

@projects_bp.route("/api/goals/simple", methods=["GET"])
@login_required
def simple_goals():
    """Just the goals, for the one picker that replaces four.

    /api/goals/picker returns the whole Objective → Key Result →
    Initiative tree and the client flattens it into "A › B › C" labels.
    That is the shape being hidden, so this returns the level the task
    now attaches to and nothing else.

    Objectives with no project are included deliberately: a task often
    serves a cross-cutting goal ("Learning") that belongs to no single
    project, and the old picker already allowed that via
    include_unassigned.
    """
    user_id = session["user_id"]
    project_id = (request.args.get("project_id") or "").strip()
    params = {
        "user_id": f"eq.{user_id}",
        "select": "id,title,project_id,time_horizon",
        "order": "title.asc",
        "limit": "200",
    }
    if project_id:
        params["or"] = f"(project_id.eq.{project_id},project_id.is.null)"
    try:
        rows = get("objectives", params=params) or []
    except Exception:
        logger.exception("simple goals: could not load objectives")
        return jsonify({"goals": []})
    return jsonify({"goals": [
        {"id": r["id"], "title": r.get("title") or "Untitled goal",
         "mine": bool(project_id) and r.get("project_id") == project_id}
        for r in rows
    ]})


@projects_bp.route("/projects/<project_id>/tasks")
@login_required
def project_tasks(project_id):
    user_id = session["user_id"]

    # ---------------------------------
    # Load project
    # ---------------------------------
    rows = get(
        "projects",
        params={"project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}"},
    )
    if not rows:
        return "Project not found", 404

    project = rows[0]

    # ---------------------------------
    # Read filters from URL
    # ---------------------------------
    hide_completed = request.args.get("hide_completed", "0") == "1"
    overdue_only   = request.args.get("overdue_only", "0") == "1"

    sort = request.args.get("sort") or project.get("default_sort", "smart")
    order = SORT_PRESETS.get(sort, SORT_PRESETS["smart"])

    # ---------------------------------
    # Fetch tasks (with server-side filtering)
    # ---------------------------------
    today = user_today()

    params = {
        "project_id": f"eq.{project_id}",
        "is_eliminated": "eq.false",
        "select": "task_id,task_text,status,due_date,due_time,priority,start_date,"
                  "duration_days,delegated_to,is_pinned,planned_hours,actual_hours,"
                  "is_recurring,recurrence_type,recurrence_days,recurrence_interval,"
                  "recurrence_end,auto_advance,order_index,created_at,"
                  "key_result_id,initiative_id,epic_id,sprint_id,objective_id",
        "order": order,
        "limit": 500,
    }

    # Push filters to database. ONE status filter, always — a task in the
    # recycle bin must not also be in the list, whatever else is toggled.
    params["status"] = _live_status_filter(also_hide_done=hide_completed or overdue_only)
    if overdue_only:
        params["due_date"] = f"lt.{today.isoformat()}"

    try:
        raw_tasks = get("project_tasks", params=params) or []
    except Exception as e:
        # objective_id arrives with MIGRATION_TASK_OBJECTIVE.sql, and a
        # migration file in the repo is not a column in production —
        # PostgREST answers a select for a missing column with a 400 and
        # get() has no retry of its own. Drop it and fetch again, so the
        # task page keeps working on an un-migrated database instead of
        # failing wholesale over one optional field.
        if ",objective_id" not in params.get("select", ""):
            raise
        logger.warning("project tasks: retrying select without objective_id (%s)", e)
        params["select"] = params["select"].replace(",objective_id", "")
        raw_tasks = get("project_tasks", params=params) or []

    tasks = [_build_task_dict(t, project, today) for t in raw_tasks]

    # Resolve OKR identifiers for each task so the client can filter by
    # Objective / Key Result / Initiative. Walk task → initiative → KR →
    # objective. Legacy rows with only key_result_id set still resolve.
    _stamp_okr_ids(tasks, user_id)

    # Batch-load subtasks for all tasks in ONE query
    task_ids = [t["task_id"] for t in tasks]
    subtask_map = {}
    if task_ids:
        ids_str = ",".join(str(tid) for tid in task_ids)
        all_subtasks = get("project_subtasks", params={
            "parent_task_id": f"in.({ids_str})",
            "select": "id,parent_task_id,title,is_done",
            "order": "created_at.asc",
            "limit": 1000,
        }) or []
        for st in all_subtasks:
            pid = st.get("parent_task_id")
            subtask_map.setdefault(pid, []).append(st)

    # Attach subtasks to each task
    for t in tasks:
        t["subtasks"] = subtask_map.get(t["task_id"], [])

    grouped_tasks = group_tasks_smart(tasks)

    return render_template(
        "project_tasks.html",
        simple_goals=SIMPLE_GOALS,
        project=project,
        grouped_tasks=grouped_tasks,
        today=today.isoformat(),
        selected_date=today.isoformat(),
        sort=sort,
        hide_completed=hide_completed,
        overdue_only=overdue_only,
    )


@projects_bp.route("/projects/<project_id>/trash")
@login_required
def project_tasks_trash(project_id):
    """Recycle bin: soft-deleted, skipped, or eliminated tasks within
    this project. Actions: restore (→ status=open), permanently archive
    (→ is_eliminated=true). Per project policy, no hard delete from here."""
    user_id = session["user_id"]

    rows = get(
        "projects",
        params={"project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}"},
    )
    if not rows:
        return "Project not found", 404
    project = rows[0]

    # Soft-deleted + skipped + eliminated rows, most recent first.
    # Status values that represent "not live": deleted, skipped, not_required.
    deleted_rows = get(
        "project_tasks",
        params={
            "project_id": f"eq.{project_id}",
            "user_id": f"eq.{user_id}",
            "or": "(status.eq.deleted,status.eq.skipped,status.eq.not_required,is_eliminated.eq.true)",
            "select": "task_id,task_text,status,due_date,priority,is_eliminated,updated_at",
            "order": "updated_at.desc",
            "limit": 500,
        },
    ) or []

    return render_template(
        "project_trash.html",
        project=project,
        rows=deleted_rows,
    )


@projects_bp.route("/projects/tasks/<task_id>/restore", methods=["POST"])
@login_required
def restore_project_task(task_id):
    """Restore a soft-deleted/skipped task. Sets status=open and
    is_eliminated=false. Idempotent."""
    user_id = session["user_id"]
    try:
        update(
            "project_tasks",
            params={"task_id": f"eq.{task_id}", "user_id": f"eq.{user_id}"},
            json={"status": "open", "is_eliminated": False},
        )
    except Exception as e:
        logger.exception("restore_project_task failed: %s", e)
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": "ok"})


@projects_bp.route("/projects/<project_id>/tasks/add", methods=["POST"])
@login_required
def add_project_task(project_id):
    text = request.form.get("task_text", "").strip()
    start_date = request.form.get("start_date") or user_today().isoformat()

    if not text:
        return redirect(url_for("projects.project_tasks", project_id=project_id))

    max_order = get_max_order_index(project_id)
    order_index = (max_order or 0) + 1

    # Drop the task into the project's default epic so it lives somewhere
    # in the OKR tree (mirrors the AJAX path).
    default_epic = _default_epic_id(session["user_id"], project_id)

    payload = {
        "project_id": project_id,
        "user_id": session["user_id"],
        "task_text": text,
        "status": "backlog",
        "start_date": start_date,
        "order_index": order_index,
    }
    if default_epic:
        payload["epic_id"] = default_epic

    post("project_tasks", payload)

    return redirect(url_for("projects.project_tasks", project_id=project_id))


@projects_bp.route("/projects/tasks/send-to-eisenhower", methods=["POST"])
@login_required
def send_project_task_to_eisenhower():
    data = request.get_json() or {}

    task_id = data.get("task_id")
    plan_date = data.get("plan_date")
    quadrant = (data.get("quadrant") or "do").lower()

    if not task_id or not plan_date:
        return jsonify({"error": "Missing task_id or plan_date"}), 400

    rows = get(
        "project_tasks",
        params={"task_id": f"eq.{task_id}"}
    )

    if not rows:
        return jsonify({"error": "Task not found"}), 404

    task = rows[0]
    existing = get(
    "todo_matrix",
    params={
        "source_task_id": f"eq.{task_id}",
        "plan_date": f"eq.{plan_date}",
    }
)

    if existing:
     return jsonify({"status": "already-sent"})

    post(
        "todo_matrix",
        {
            "task_text": task["task_text"],   # ✅ FIXED
            "plan_date": plan_date,           # ✅ REQUIRED
            "quadrant": quadrant,              # ✅ CHECK constraint
            "project_id": task.get("project_id"),
            "user_id": session["user_id"],     # ✅ IMPORTANT
            "source_task_id": task_id,
            "is_done": False,
        }
    )

    return jsonify({"status": "ok"})




@projects_bp.route("/projects/tasks/status", methods=["POST"])
@login_required
def update_project_task_status():
    data = request.get_json(force=True)

    task_id   = data["task_id"]
    status    = data["status"]
    task_date = data.get("date")
    user_id   = session["user_id"]

    # Load base task (rule)
    rows = get(
        "project_tasks",
        params={
            "task_id": f"eq.{task_id}",
            "user_id": f"eq.{user_id}"
        }
    )

    if not rows:
        return jsonify({"error": "Task not found"}), 404

    task = rows[0]

    # ------------------------------------------------
    # CASE 1: recurring + per-day completion
    # ------------------------------------------------
    if task_date and task.get("is_recurring"):
        if status == "done":
            complete_task_occurrence(
                user_id=user_id,
                task_id=task_id,
                task_date=task_date
            )

            # 🔁 AUTO-ADVANCE (if enabled)
            # Preserve the original `due_date - start_date` delta so a
            # 3-day recurring task stays 3 days long every cycle. The old
            # code set due_date = start_date, which silently collapsed
            # multi-day recurring tasks to a single day.
            if task.get("auto_advance", True):
                next_date = compute_next_occurrence(
                    task,
                    date.fromisoformat(task_date)
                )

                if next_date:
                    duration_days = 0
                    try:
                        if task.get("start_date") and task.get("due_date"):
                            d0 = date.fromisoformat(task["start_date"])
                            d1 = date.fromisoformat(task["due_date"])
                            duration_days = max((d1 - d0).days, 0)
                    except (TypeError, ValueError):
                        duration_days = 0
                    next_due = next_date + timedelta(days=duration_days)
                    update(
                        "project_tasks",
                        params={"task_id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
                        json={
                            "start_date": next_date.isoformat(),
                            "due_date": next_due.isoformat(),
                            "status": "open"
                        }
                    )

        return jsonify({"status": "ok"})

    # ------------------------------------------------
    # CASE 2: normal (non-recurring) task
    # ------------------------------------------------
    # Normalize legacy "not_required" → "deleted"
    if status == "not_required":
        status = "deleted"

    patch = {"status": status}
    if status == "deleted":
        # Soft delete: flip is_eliminated so filtered listings stop showing it
        patch["is_eliminated"] = True
    elif status == "open":
        # Undo path — reopen also un-eliminates
        patch["is_eliminated"] = False

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}", "user_id": f"eq.{user_id}"},
        json=patch,
    )

    # Auto-progress: if this task ladders up to an auto-tracked KR, refresh
    # the KR's current_value. Lazy-imported to avoid a circular ref since
    # routes/goals.py imports from routes/todo (which projects.py uses).
    try:
        from routes.goals import recompute_kr_auto_progress_for_task
        recompute_kr_auto_progress_for_task(user_id, task_id)
    except Exception:
        pass

    return jsonify({"status": "ok"})


# ==========================================================
# BULK UPDATE (selection mode)
# ==========================================================

_PT_VALID_PRIORITIES = {"low", "medium", "high"}
_PT_PRIORITY_RANK = {"high": 1, "medium": 2, "low": 3}
#: Statuses the RECYCLE BIN claims. Anything here is not live work, and the
#: project's task list must agree — see _NOT_LIVE_FILTER below.
_PT_TRASHED_STATUSES = ("deleted", "skipped", "not_required")

#: The filter that keeps the two in step.
#:
#: THE BUG THIS FIXES. The live list filtered ONLY on is_eliminated, while
#: the trash page selects `status in (deleted, skipped, not_required) OR
#: is_eliminated`. Setting a task to "deleted" happens to flip is_eliminated
#: as well, so that case looked fine — but "skipped" does not, so a skipped
#: task appeared in the project AND in its own recycle bin at the same time.
#:
#: Fixed by filtering on the STATUS rather than by making every writer
#: remember to set a second flag. Two flags kept in sync by convention is
#: precisely how they drift apart.
_NOT_LIVE_FILTER = "not.in.(%s)" % ",".join(_PT_TRASHED_STATUSES)


def _live_status_filter(also_hide_done=False):
    """PostgREST filter for "still live", optionally hiding completed too.

    Built as ONE filter because `status` is a single query parameter — a
    second assignment silently replaces the first, which is how a
    hide-completed toggle could have quietly undone this.
    """
    hidden = list(_PT_TRASHED_STATUSES)
    if also_hide_done:
        hidden.append("done")
    return "not.in.(%s)" % ",".join(hidden)


_PT_OPEN_STATUSES = {"open", "in_progress"}
_PT_RESOLVED_STATUSES = {"done", "skipped", "deleted"}
_PT_ALL_STATUSES = _PT_OPEN_STATUSES | _PT_RESOLVED_STATUSES

@projects_bp.route("/projects/tasks/bulk-update", methods=["POST"])
@login_required
def bulk_update_project_tasks():
    """
    Apply a patch to many project_tasks rows at once.

    Body: { ids: [task_id, ...], patch: { status?, priority? } }

    Soft-delete semantics: status='deleted' also sets is_eliminated=true.
    Setting priority also updates priority_rank (1=high, 2=medium, 3=low).
    All writes are scoped to the authenticated user.
    """
    data = request.get_json(force=True) or {}
    ids = data.get("ids") or []
    patch = data.get("patch") or {}

    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "ids required"}), 400
    if not isinstance(patch, dict) or not patch:
        return jsonify({"error": "patch required"}), 400

    user_id = session["user_id"]

    # Build the DB patch
    db_patch = {}

    if "status" in patch:
        status = (patch["status"] or "").strip().lower()
        # Legacy alias
        if status == "not_required":
            status = "deleted"
        if status not in _PT_ALL_STATUSES:
            return jsonify({"error": "invalid status"}), 400
        db_patch["status"] = status
        if status == "deleted":
            db_patch["is_eliminated"] = True
        elif status == "open":
            # Reopening un-eliminates (symmetric with per-row update)
            db_patch["is_eliminated"] = False

    if "priority" in patch:
        priority = (patch["priority"] or "").strip().lower()
        if priority not in _PT_VALID_PRIORITIES:
            return jsonify({"error": "invalid priority"}), 400
        db_patch["priority"] = priority
        db_patch["priority_rank"] = _PT_PRIORITY_RANK[priority]

    if not db_patch:
        return jsonify({"error": "no valid fields in patch"}), 400

    # Sanitize IDs: keep non-empty strings only
    clean_ids = [str(i) for i in ids if isinstance(i, (str, int)) and str(i)]
    if not clean_ids:
        return jsonify({"error": "no valid ids"}), 400

    # Single bulk UPDATE scoped to the user
    update(
        "project_tasks",
        params={
            "user_id": f"eq.{user_id}",
            "task_id": f"in.({','.join(clean_ids)})",
        },
        json=db_patch,
    )

    return jsonify({"status": "ok", "updated": len(clean_ids)})


@projects_bp.route("/projects/tasks/unsend", methods=["POST"])
@login_required
def unsend_task_from_eisenhower():
    data = request.get_json() or {}

    task_id = data.get("task_id")
    scope = data.get("scope", "today_future")  # optional

    if not task_id:
        return jsonify({"error": "Missing task_id"}), 400

    today = user_today().isoformat()

    # ---------------------------------------------
    # Remove Eisenhower entries linked to this task
    # ---------------------------------------------
    params = {
        "source_task_id": f"eq.{task_id}",
        "is_deleted": "eq.false",
        "user_id": f"eq.{session['user_id']}",
    }

    # Optional safety: only today & future
    if scope == "today_future":
        params["plan_date"] = f"gte.{today}"

    update(
        "todo_matrix",
        params=params,
        json={"is_deleted": True},
    )

    return jsonify({"status": "ok"})



@projects_bp.route("/projects/tasks/update-date", methods=["POST"])
@login_required
def update_project_task_date():
    """Reschedule a project task to a new effective date.

    Writes to `revised_due_date` so the original `due_date` stays as
    an audit trail of the deadline that was first set. The Eisenhower
    matrix and project listings page are now driven by revised_due_date
    (or due_date if no revision yet).

    Body accepts either an explicit `due_date` (legacy callers) — which
    despite the field name now sets revised_due_date — or a relative
    `shift_days` shortcut from the "+1d / +3d / next week" buttons.
    """
    from datetime import date as _date, timedelta as _td

    data = request.get_json() or {}
    task_id = data.get("task_id")
    new_date = data.get("due_date")

    if not task_id:
        return jsonify({"error": "Missing task id"}), 400

    if not new_date:
        try:
            shift = int(data.get("shift_days") or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid shift_days"}), 400
        if shift > 0:
            new_date = (_date.today() + _td(days=shift)).isoformat()

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
        json={"revised_due_date": new_date},
    )
    logger.info(f"👉 task_id={task_id}, revised_due_date={new_date}")
    return jsonify({"status": "ok", "revised_due_date": new_date, "due_date": new_date})
@projects_bp.route("/projects/tasks/<task_id>/update", methods=["POST"])
@login_required
def update_task(task_id):
    data = request.json or {}

    # Build update payload safely (PATCH semantics)
    updates = {}

    allowed_fields = [
        "task_text",
        "start_date",
        "due_date",
        "revised_due_date",
        "due_time",
        "notes",
        "status",
        "planned_hours",
        "actual_hours",
        "priority",
        "elimination_reason",
        "duration_days",
        "delegated_to",
        "is_recurring",
        "recurrence_type",
        "recurrence_days",
        "recurrence_interval",
        "recurrence_end",
        "auto_advance",
        "quadrant",
        "key_result_id",
        "initiative_id",
        "epic_id",
        "sprint_id",
    ]

    for field in allowed_fields:
        if field in data:
            updates[field] = data[field]

    # 🔒 Safety: never allow task_text to be null
    if "task_text" in updates and updates["task_text"] is None:
        return jsonify({
            "error": "task_text cannot be null"
        }), 400

    # 🛑 No-op protection
    if not updates:
        return jsonify({"status": "noop"})
    if "start_time" in updates and updates["start_time"] == "":
        updates["start_time"] = None
    # Empty string → NULL for key_result_id so the FK doesn't blow up
    if "key_result_id" in updates and updates["key_result_id"] == "":
        updates["key_result_id"] = None
    if "initiative_id" in updates and updates["initiative_id"] == "":
        updates["initiative_id"] = None
    if "epic_id" in updates and updates["epic_id"] == "":
        updates["epic_id"] = None
    if "sprint_id" in updates and updates["sprint_id"] == "":
        updates["sprint_id"] = None

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
        json=updates
    )

    return jsonify({"status": "ok"})



@projects_bp.route("/projects/tasks/update-duration", methods=["POST"])
@login_required
def update_task_duration():
    data = request.get_json()

    task_id = data["task_id"]
    duration_days = int(data["duration_days"])

    # 1️⃣ Fetch start_date from DB (source of truth)
    rows = get(
        "project_tasks",
        params={
            "task_id": f"eq.{task_id}",
            "user_id": f"eq.{session['user_id']}",
            "select": "start_date",
        },
    )

    if not rows or not rows[0].get("start_date"):
        return jsonify({"error": "Missing start date"}), 400

    start_date = date.fromisoformat(rows[0]["start_date"])

    # 2️⃣ ✅ Compute due date HERE
    due_date = compute_due_date(start_date, duration_days)

    # 3️⃣ Persist everything
    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
        json={
            "duration_days": duration_days,
            "due_date": due_date.isoformat(),
        },
    )

    return jsonify({
        "due_date": due_date.isoformat()
    })


@projects_bp.route("/projects/tasks/update-delegation", methods=["POST"])
@login_required
def update_delegation():
    data = request.get_json()

    update(
        "project_tasks",
        params={"task_id": f"eq.{data['id']}", "user_id": f"eq.{session['user_id']}"},
        json={
            "delegated_to": data.get("delegated_to")
        }
    )

    return "", 204

@projects_bp.route("/projects/tasks/eliminate", methods=["POST"])
@login_required
def eliminate_task():
    data = request.get_json()

    task_id = data["id"]
    reason = data.get("reason")

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
        json={
            "is_eliminated": True,
            "elimination_reason": reason,
        }
    )

    return "", 204

@projects_bp.route("/projects/tasks/update-time", methods=["POST"])
@login_required
def update_due_time():
    data = request.get_json()

    update(
        "project_tasks",
        params={"task_id": f"eq.{data['id']}", "user_id": f"eq.{session['user_id']}"},
        json={
            "due_time": data.get("due_time")
        }
    )

    return "", 204
@projects_bp.route("/projects/tasks/update-planning", methods=["POST"])
@login_required
def update_task_planning():
    data = request.get_json()

    task_id = data.get("task_id")
    start_str = (data.get("start_date") or "").strip()

    if not task_id or not start_str:
        return jsonify({"error": "task_id and start_date are required"}), 400

    try:
        start = date.fromisoformat(start_str)
    except ValueError:
        return jsonify({"error": "Invalid start_date format"}), 400

    days    = int(data.get("duration_days") or 1)

    due_date = start + timedelta(days=days)  # noqa: F821

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
        json={
            "start_date": str(start),
            "duration_days": days,
            "due_date": str(due_date),
        }
    )

    return jsonify({
        "due_date": str(due_date)
    })
@projects_bp.route("/projects/<project_id>/gantt")
@login_required
def project_gantt(project_id):
    tasks = get(
        "project_tasks",
        params={
            "project_id": f"eq.{project_id}",
            "user_id": f"eq.{session['user_id']}",
            "is_eliminated": "eq.false",
            "select": "task_id,task_text,start_date,duration_days,planned_hours,actual_hours",
            "order": "start_date.asc",
            "limit": 500,
        },
    ) or []

    gantt_tasks = build_gantt_tasks(tasks)

    # Pass the list directly; the template renders it via `| tojson`.
    return render_template(
        "project_gantt.html",
        project_id=project_id,
        gantt_tasks=gantt_tasks,
    )
@projects_bp.route("/projects/tasks/update-planned", methods=["POST"])
@login_required
def update_planned():
    data = request.get_json()
    update(
        "project_tasks",
        params={"task_id": f"eq.{data['task_id']}", "user_id": f"eq.{session['user_id']}"},
        json={"planned_hours": data["planned_hours"]}
    )
    return "", 204


@projects_bp.route("/projects/tasks/update-actual", methods=["POST"])
@login_required
def update_actual():
    data = request.get_json()
    update(
        "project_tasks",
        params={"task_id": f"eq.{data['task_id']}", "user_id": f"eq.{session['user_id']}"},
        json={"actual_hours": data["actual_hours"]}
    )
    return "", 204
@projects_bp.route("/projects/tasks/update-priority", methods=["POST"])
@login_required
def update_priority():
    data = request.get_json()
    task_id = data["task_id"]
    priority = data["priority"]

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
        json={
            "priority": priority,
            "priority_rank": PRIORITY_MAP.get(priority, 2)
        }
    )

    return {"status": "ok"}


@projects_bp.route("/projects/<project_id>/archive", methods=["POST"])
@login_required
def archive_project(project_id):
    """
    Soft-delete a project. The row stays in the DB with is_archived=true.
    Listings filter by is_archived=eq.false, so an archived project
    disappears from the UI but can be restored (see restore_project).

    Tasks under the project are not cascaded — they keep their current
    is_eliminated state. Archiving a project is reversible; a user who
    wanted to also delete the tasks would do that step explicitly.
    """
    update(
        "projects",
        params={
            "project_id": f"eq.{project_id}",
            "user_id": f"eq.{session['user_id']}",
        },
        json={"is_archived": True},
    )
    return jsonify({"status": "ok"})


@projects_bp.route("/projects/<project_id>/restore", methods=["POST"])
@login_required
def restore_project(project_id):
    """Un-archive a previously soft-deleted project."""
    update(
        "projects",
        params={
            "project_id": f"eq.{project_id}",
            "user_id": f"eq.{session['user_id']}",
        },
        json={"is_archived": False},
    )
    return jsonify({"status": "ok"})


@projects_bp.route("/sprints")
@login_required
def all_sprints():
    """Cross-project sprint dashboard.

    Lists every active + upcoming sprint across all the user's
    non-archived projects, plus recently-ended ones for context.
    Useful when you're juggling several projects and want a single
    "what's happening this week" view.
    """
    user_id = session["user_id"]

    # Pull projects so we can name each sprint's parent.
    projects = get(
        "projects",
        params={
            "user_id":     f"eq.{user_id}",
            "is_archived": "eq.false",
            "select":      "project_id,name",
            "limit":       500,
        },
    ) or []
    name_by_pid = {p["project_id"]: p.get("name") for p in projects}
    if not name_by_pid:
        return render_template("sprints_all.html", buckets=[], today=user_today().isoformat())

    sprints = get(
        "sprints",
        params={
            "user_id":    f"eq.{user_id}",
            "project_id": f"in.({','.join(name_by_pid.keys())})",
            "is_deleted": "eq.false",
            "select":     "id,name,starts_on,ends_on,is_active,project_id",
            "order":      "is_active.desc,starts_on.asc.nullslast,created_at.desc",
            "limit":      500,
        },
    ) or []

    today = user_today()
    today_iso = today.isoformat()
    buckets = {"active": [], "upcoming": [], "no_dates": [], "recent": []}
    for s in sprints:
        s["project_name"] = name_by_pid.get(s["project_id"]) or "(unnamed)"
        starts, ends = s.get("starts_on"), s.get("ends_on")
        if s.get("is_active"):
            buckets["active"].append(s)
        elif starts and starts > today_iso:
            buckets["upcoming"].append(s)
        elif ends and ends < today_iso:
            buckets["recent"].append(s)
        elif not starts and not ends:
            buckets["no_dates"].append(s)
        else:
            # Has dates but currently within range AND not marked active —
            # treat as active for visibility.
            buckets["active"].append(s)

    # Cap "recent" to last 30 days and trim to 10 — context, not noise.
    from datetime import timedelta as _td
    cutoff = (today - _td(days=30)).isoformat()
    buckets["recent"] = [s for s in buckets["recent"] if (s.get("ends_on") or "") >= cutoff][:10]

    return render_template(
        "sprints_all.html",
        active=buckets["active"],
        upcoming=buckets["upcoming"],
        no_dates=buckets["no_dates"],
        recent=buckets["recent"],
        today=today_iso,
    )


@projects_bp.route("/projects/new", methods=["GET", "POST"])
@login_required
def create_project():
    if request.method == "POST":
        # ONE ENDPOINT, TWO CALLERS. The full form still posts a form and
        # still gets a redirect; the list page's inline quick-add posts
        # JSON and gets the new row back so it can drop a card in without
        # a round trip to a separate page. A second create endpoint would
        # be a second place for the default-OKR-trio provisioning below
        # to be forgotten.
        data = request.get_json(silent=True) or {}
        wants_json = bool(data)
        name = (data.get("name") if wants_json
                else request.form.get("name", "")).strip()
        description = (data.get("description") if wants_json
                       else request.form.get("description", "")) or ""
        description = description.strip()

        if not name:
            if wants_json:
                return jsonify({"error": "Give the project a name first"}), 400
            return "Project name is required", 400

        raw_color = (data.get("color") if wants_json else request.form.get("color")) or ""
        color = _clean_project_color(raw_color)

        user_id = session.get("user_id")
        payload = {
            "name": name,
            "description": description or None,
            "user_id": user_id,
        }
        # projects.color comes from MIGRATION_PROJECT_COLOR.sql. Before it
        # runs, post() strips the unknown column and retries, so creating a
        # project never fails over a colour.
        if color:
            payload["color"] = color
        rows = post("projects", payload)
        # Provision the default Inbox > Catch-all > Inbox > Inbox trio
        # so tasks added without an explicit epic have somewhere to go.
        new_project_id = (rows or [{}])[0].get("project_id") if rows else None
        if new_project_id:
            _ensure_default_okr_trio(user_id, new_project_id)

        if wants_json:
            row = (rows or [{}])[0] if rows else {}
            # Shaped exactly like the cards the list renders, so the
            # client has nothing to invent: a brand-new project has no
            # tasks, so every count is zero by definition.
            return jsonify({"project": {
                "project_id": new_project_id,
                "name": row.get("name") or name,
                "description": row.get("description"),
                "color": color,
                "is_archived": False,
                "task_count": 0, "done_count": 0, "open_count": 0,
                "overdue_count": 0, "next_due": None, "completion_pct": 0,
            }})

        return redirect("/projects")

    return render_template("project_new.html")

@projects_bp.route("/projects/tasks/bulk-add", methods=["POST"])
@login_required
def bulk_add_tasks():
    data = request.json or {}

    project_id = data.get("project_id")
    tasks = data.get("tasks", [])

    if not project_id:
        return jsonify({"error": "project_id missing"}), 400

    if not tasks:
        return jsonify({"error": "no tasks provided"}), 400

    today = user_today().isoformat()

    # Fetch max order_index ONCE (not per task)
    max_order = get_max_order_index(project_id) or 0

    rows = []
    for idx, text in enumerate(tasks):
        if not text.strip():
            continue

        rows.append({
            "project_id": project_id,
            "task_text": text.strip(),
            "start_date": today,
            "priority": "medium",
            "priority_rank": PRIORITY_MAP["medium"],
            "order_index": max_order + idx + 1,
            "duration_days": 0,
            "status": "open",
            "user_id": session["user_id"]
        })

    if not rows:
        return jsonify({"error": "no valid tasks"}), 400

    insert_many("project_tasks", rows)

    return jsonify({
        "status": "ok",
        "count": len(rows)
    })
@projects_bp.route("/projects/<project_id>/export-csv")
@login_required
def export_csv(project_id):
    """Export all tasks and subtasks as CSV."""
    from flask import Response
    import csv
    import io

    user_id = session["user_id"]

    # Verify project ownership
    proj = get("projects", params={
        "project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}",
        "select": "name"
    })
    if not proj:
        return "Project not found", 404

    project_name = proj[0]["name"]

    # Fetch tasks
    tasks = get("project_tasks", params={
        "project_id": f"eq.{project_id}",
        "is_eliminated": "eq.false",
        "select": "task_id,task_text,status,priority,start_date,due_date,due_time,"
                  "duration_days,planned_hours,actual_hours,delegated_to,notes,"
                  "is_pinned,is_recurring,recurrence_type",
        "order": "order_index.asc",
    }) or []

    # Batch-fetch subtasks
    task_ids = [t["task_id"] for t in tasks]
    subtask_map = {}
    if task_ids:
        ids_str = ",".join(str(tid) for tid in task_ids)
        subtasks = get("project_subtasks", params={
            "parent_task_id": f"in.({ids_str})",
            "select": "parent_task_id,title,is_done",
            "order": "created_at.asc",
        }) or []
        for st in subtasks:
            subtask_map.setdefault(st["parent_task_id"], []).append(st)

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "task", "parent", "status", "priority", "start_date", "due_date",
        "due_time", "duration", "planned_hours", "actual_hours",
        "delegated_to", "is_pinned", "recurring", "notes"
    ])

    for t in tasks:
        writer.writerow([
            t.get("task_text", ""),
            "",  # no parent — it's a task
            t.get("status", ""),
            t.get("priority", ""),
            t.get("start_date", ""),
            t.get("due_date", ""),
            t.get("due_time", ""),
            t.get("duration_days", ""),
            t.get("planned_hours", ""),
            t.get("actual_hours", ""),
            t.get("delegated_to", ""),
            "yes" if t.get("is_pinned") else "",
            t.get("recurrence_type", "") if t.get("is_recurring") else "",
            t.get("notes", ""),
        ])

        # Write subtasks for this task
        for st in subtask_map.get(t["task_id"], []):
            writer.writerow([
                st.get("title", ""),
                t.get("task_text", ""),  # parent = task name
                "done" if st.get("is_done") else "open",
                "", "", "", "", "", "", "", "", "", "", "",
            ])

    csv_data = output.getvalue()
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in project_name)

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_tasks.csv"'}
    )


@projects_bp.route("/projects/tasks/import-csv", methods=["POST"])
@login_required
def import_csv():
    """Import tasks and subtasks from parsed CSV data (sent as JSON from client)."""
    data = request.get_json() or {}
    project_id = data.get("project_id")
    rows = data.get("rows", [])

    if not project_id or not rows:
        return jsonify({"error": "project_id and rows required"}), 400

    user_id = session["user_id"]
    max_order = get_max_order_index(project_id) or 0

    created_tasks = 0
    created_subtasks = 0

    # First pass: create all tasks
    task_map = {}  # row_index -> task_id
    for idx, row in enumerate(rows):
        task_text = (row.get("task") or "").strip()
        if not task_text:
            continue

        # Skip if this is a subtask row (has parent)
        if row.get("parent"):
            continue

        result = post("project_tasks", {
            "project_id": project_id,
            "user_id": user_id,
            "task_text": task_text,
            "status": row.get("status", "open"),
            "priority": row.get("priority", "medium"),
            "start_date": row.get("start_date") or user_today().isoformat(),
            "due_date": row.get("due_date") or None,
            # Mirror due_date → revised_due_date on insert so the parking
            # filter (revised_due_date < today) sees the original
            # deadline immediately. Pre-migration this column won't
            # exist and supabase_client.post strips it on PGRST204.
            "revised_due_date": row.get("due_date") or None,
            "duration_days": int(row["duration"]) if row.get("duration") else 0,
            "planned_hours": float(row["planned_hours"]) if row.get("planned_hours") else None,
            "notes": row.get("notes") or None,
            "order_index": max_order + idx + 1,
            "priority_rank": PRIORITY_MAP.get(row.get("priority", "medium"), 2),
        })

        if result:
            task_id = result[0].get("task_id")
            task_map[task_text] = task_id
            created_tasks += 1

    # Second pass: create subtasks
    for row in rows:
        parent_name = (row.get("parent") or "").strip()
        subtask_text = (row.get("task") or "").strip()

        if not parent_name or not subtask_text:
            continue

        parent_task_id = task_map.get(parent_name)
        if not parent_task_id:
            continue

        try:
            post("project_subtasks", {
                "project_id": project_id,
                "parent_task_id": parent_task_id,
                "title": subtask_text,
                "is_done": False,
            })
            created_subtasks += 1
        except Exception:
            pass  # Skip FK failures

    return jsonify({
        "status": "ok",
        "tasks_created": created_tasks,
        "subtasks_created": created_subtasks,
    })


@projects_bp.route("/projects/tasks/pin", methods=["POST"])
@login_required
def toggle_pin():
    data = request.get_json() or {}

    task_id = data.get("task_id")
    is_pinned = data.get("is_pinned")

    if not task_id:
        return jsonify({"error": "Missing task_id"}), 400

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
        json={"is_pinned": bool(is_pinned)}
    )

    return jsonify({"status": "ok"})
@projects_bp.route("/projects/tasks/reorder", methods=["POST"])
@login_required
def reorder_tasks():
    data = request.get_json() or {}

    dragged = data.get("dragged_id")
    target = data.get("target_id")

    if not dragged or not target:
        return jsonify({"error": "Missing task ids"}), 400

    rows = get(
        "project_tasks",
        params={
            "task_id": f"in.({dragged},{target})",
            "user_id": f"eq.{session['user_id']}",
            "select": "task_id,order_index,due_date,priority_rank,is_pinned"
        }
    )

    if len(rows) != 2:
        return jsonify({"error": "Tasks not found"}), 404

    a, b = rows
    if (
    a.get("due_date") != b.get("due_date")
    or a.get("priority_rank") != b.get("priority_rank")
    or a.get("is_pinned") != b.get("is_pinned")
    ):
        return jsonify({"error": "Tasks must have the same due date, priority, and pin status to reorder"}), 400
    # 🔄 swap order_index
    update(
        "project_tasks",
        params={"task_id": f"eq.{a['task_id']}", "user_id": f"eq.{session['user_id']}"},
        json={"order_index": b["order_index"]}
    )
    update(
        "project_tasks",
        params={"task_id": f"eq.{b['task_id']}", "user_id": f"eq.{session['user_id']}"},
        json={"order_index": a["order_index"]}
    )

    return jsonify({"status": "ok"})
@projects_bp.route("/api/v2/project-tasks")
@login_required
def get_project_tasks():
    user_id = session["user_id"]
    date = request.args.get("date")

    if not date:
        return jsonify([])

    try:
        tasks = get(
            "project_tasks",
            params={
                "user_id": f"eq.{user_id}",
                "is_eliminated": "eq.false",
                "status": "neq.done",
                "or": f"(due_date.is.null,due_date.lte.{date})",
                # plan_date is in the select because the calendar needs it to
                # know WHICH day a timed task belongs to. Without it every
                # task with a start_time redrew its chip on this day and every
                # later one, since the filter below is due_date <= date.
                "select": "task_id,task_text,priority,project_id,start_time,due_date,"
                          "plan_date,is_recurring,recurrence_type",
                "limit": 200,
            }
        ) or []
    except Exception as e:
        import logging
        logging.getLogger("daily_plan").error("project-tasks API error: %s", str(e))
        tasks = []

    return jsonify(tasks)

@projects_bp.route("/api/v2/project-tasks/<task_id>/schedule", methods=["POST"])
@login_required
def schedule_project_task(task_id):
    data = request.json

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
        json={
            "plan_date": data["plan_date"],
            "start_time": data["start_time"],
        }
    )

    return {"ok": True}
@projects_bp.route("/api/v2/project-tasks/<task_id>", methods=["GET"])
@login_required
def get_single_project_task(task_id):

    task = get(
        "project_tasks",
        params={
            "task_id": f"eq.{task_id}",
            "user_id": f"eq.{session['user_id']}",
            "select": "*"
        }
    )

    return jsonify(task[0] if task else {})
@projects_bp.route("/api/v2/project-tasks/<task_id>", methods=["PUT"])
@login_required
def update_project_task(task_id):

    data = request.get_json(silent=True) or {}

    allowed_fields = {
        "task_text",
        "notes",
        "status",
        "priority",
        "planned_hours",
        "actual_hours",
        "duration_days",
        "due_date",
        "start_time",
        "recurrence",
        "recurrence_type",
        "recurrence_interval",
        "recurrence_end"
    }

    update_payload = {
        k: v for k, v in data.items()
        if k in allowed_fields
    }

    # ✅ normalize empty strings safely
    update_payload = {
        k: (None if isinstance(v, str) and v.strip() == "" else v)
        for k, v in update_payload.items()
    }

    # ✅ normalize numeric fields
    for field in ["planned_hours", "actual_hours", "duration_days"]:
        if field in update_payload:
            val = update_payload[field]

            if val is None:
                continue

            try:
                update_payload[field] = int(float(val))
            except:
                update_payload[field] = None

    # ✅ normalize date/time fields
    for field in ["due_date", "start_time"]:
        if field in update_payload:
            val = update_payload[field]

            if val is None:
                continue

            val = str(val).strip()
            update_payload[field] = val if val else None

    if not update_payload:
        return jsonify({"error": "No valid fields to update"}), 400

    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
        json=update_payload
    )

    return jsonify({"success": True})


@projects_bp.route("/api/v2/project-tasks/<task_id>/complete", methods=["POST"])
@login_required
def complete_task(task_id):
    update(
        "project_tasks",
        params={"task_id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
        json={"is_completed": True}
    )

    return {"ok": True}

# ── Subtask ownership ────────────────────────────────────────────────────
# project_subtasks has no user_id column, so ownership is the parent
# task's. Every subtask route used to act on whatever id it was given —
# list, add, toggle and delete all worked across users.
def _owns_task(task_id):
    if not task_id:
        return False
    rows = get("project_tasks", params={
        "task_id": f"eq.{task_id}",
        "user_id": f"eq.{session['user_id']}",
        "select": "task_id",
    }) or []
    return bool(rows)


def _owns_subtask(sub_id):
    if not sub_id:
        return False
    rows = get("project_subtasks", params={
        "id": f"eq.{sub_id}",
        "select": "parent_task_id",
    }) or []
    return bool(rows) and _owns_task(rows[0].get("parent_task_id"))


@projects_bp.route("/subtask/list/<task_id>")
@login_required
def list_subtasks(task_id):
    if not _owns_task(task_id):
        return jsonify([])
    params = {
        "parent_task_id": f"eq.{task_id}",
        "select": "id,title,is_done",
        "order": "id.asc",
    }
    # Hide soft-deleted rows when that column exists; if it doesn't, the
    # filter silently matches everything (PostgREST ignores missing cols
    # in some cases — harmless fallback).
    params["is_deleted"] = "eq.false"
    try:
        rows = get("project_subtasks", params=params) or []
    except Exception:
        # Fallback for environments where is_deleted hasn't been migrated yet
        params.pop("is_deleted", None)
        rows = get("project_subtasks", params=params) or []
    return jsonify(rows)


@projects_bp.route("/subtask/add", methods=["POST"])
@login_required
def add_subtask():
    data = request.get_json()
    title = (data.get("title") or "").strip()

    if not title:
        return jsonify({"error": "Subtask title required"}), 400

    task_id = data.get("task_id")
    project_id = data.get("project_id")
    if not _owns_task(task_id):
        return jsonify({"error": "Task not found"}), 404

    # IMPORTANT: Run this SQL in Supabase to fix FK (points to todo_matrix instead of project_tasks):
    #   ALTER TABLE project_subtasks DROP CONSTRAINT project_subtasks_parent_task_id_fkey;
    #   ALTER TABLE project_subtasks ADD CONSTRAINT project_subtasks_parent_task_id_fkey
    #     FOREIGN KEY (parent_task_id) REFERENCES project_tasks(task_id) ON DELETE CASCADE;

    try:
        rows = post(
            "project_subtasks",
            {
                "project_id": project_id,
                "parent_task_id": task_id,
                "title": title,
                "is_done": False,
            },
        )
        if rows:
            return jsonify(rows[0])
    except Exception as e:
        logger.error("Subtask add failed: %s", str(e))
        return jsonify({"error": "Failed to add subtask. Check database constraints."}), 500

    return jsonify({"id": None, "title": title, "is_done": False})

@projects_bp.route("/subtask/toggle", methods=["POST"])
@login_required
def toggle_subtask():
    data = request.get_json(force=True) or {}
    if not _owns_subtask(data.get("id")):
        return jsonify({"error": "Subtask not found"}), 404

    update(
        "project_subtasks",
        params={"id": f"eq.{data['id']}"},
        json={"is_done": bool(data.get("is_done"))},
    )

    return ("", 204)


@projects_bp.route("/subtask/delete", methods=["POST"])
@login_required
def delete_subtask():
    """Soft-delete a subtask by flipping is_deleted=true.

    Per project policy (see user feedback memory): all deletes are soft,
    never hard. If the `is_deleted` column is missing on project_subtasks,
    run this migration:
        ALTER TABLE project_subtasks
          ADD COLUMN IF NOT EXISTS is_deleted boolean DEFAULT false,
          ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
        NOTIFY pgrst, 'reload schema';
    """
    from datetime import datetime, timezone

    data = request.get_json(force=True) or {}
    sub_id = data.get("id")
    if not sub_id:
        return jsonify({"error": "Subtask id required"}), 400
    if not _owns_subtask(sub_id):
        return jsonify({"error": "Subtask not found"}), 404

    try:
        update(
            "project_subtasks",
            params={"id": f"eq.{sub_id}"},
            json={
                "is_deleted": True,
                "deleted_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:
        logger.exception("delete_subtask failed")
        return jsonify({"error": f"Delete failed: {e}"}), 500

    return jsonify({"status": "ok"})

def _stamp_okr_ids(tasks, user_id):
    """Resolve and attach objective_id / key_result_id / initiative_id to each task.

    Tasks link to an Initiative; KR and Objective are resolved by walking up
    (initiative → key_result → objective). Legacy tasks that still have a
    direct key_result_id (pre-Initiative layer) also get objective_id filled.
    """
    # A TASK FILED STRAIGHT AGAINST A GOAL NEEDS NO WALK. objective_id is
    # the simple path (config.SIMPLE_GOALS); everything below is the old
    # ladder, still here for rows that were filed the long way round and
    # for when the flag is turned back off.
    direct = [t for t in tasks if t.get("objective_id")]

    # Epics: tasks may carry epic_id only (no initiative_id yet). Resolve
    # epic → initiative so the rest of the walk picks them up.
    epic_ids = {t.get("epic_id") for t in tasks if t.get("epic_id") and not t.get("initiative_id")}
    epic_to_initiative = {}
    if epic_ids:
        epic_rows = get(
            "epics",
            params={
                "user_id":    f"eq.{user_id}",
                "id":         f"in.({','.join(str(i) for i in epic_ids)})",
                "is_deleted": "eq.false",
                "select":     "id,initiative_id",
                "limit":      500,
            },
        ) or []
        epic_to_initiative = {r["id"]: r.get("initiative_id") for r in epic_rows}
        # Patch the in-memory tasks so downstream walks see the resolved id.
        for t in tasks:
            if t.get("epic_id") and not t.get("initiative_id"):
                t["initiative_id"] = epic_to_initiative.get(t["epic_id"])

    initiative_ids = {t["initiative_id"] for t in tasks if t.get("initiative_id")}
    legacy_kr_ids = {
        t["key_result_id"] for t in tasks
        if t.get("key_result_id") and not t.get("initiative_id")
    }

    initiative_rows = []
    if initiative_ids:
        initiative_rows = get(
            "initiatives",
            params={
                "user_id": f"eq.{user_id}",
                "id": f"in.({','.join(str(i) for i in initiative_ids)})",
                "is_deleted": "eq.false",
                "select": "id,key_result_id",
                "limit": 500,
            },
        ) or []
    initiative_to_kr = {r["id"]: r.get("key_result_id") for r in initiative_rows}

    kr_ids_needed = set(initiative_to_kr.values()) | legacy_kr_ids
    kr_ids_needed = {k for k in kr_ids_needed if k}

    kr_to_objective = {}
    if kr_ids_needed:
        kr_rows = get(
            "key_results",
            params={
                "user_id": f"eq.{user_id}",
                "id": f"in.({','.join(str(i) for i in kr_ids_needed)})",
                "is_deleted": "eq.false",
                "select": "id,objective_id",
                "limit": 500,
            },
        ) or []
        kr_to_objective = {r["id"]: r.get("objective_id") for r in kr_rows}

    for t in tasks:
        init_id = t.get("initiative_id")
        kr_id = initiative_to_kr.get(init_id) if init_id else t.get("key_result_id")
        obj_id = kr_to_objective.get(kr_id) if kr_id else None
        t["key_result_id"] = kr_id
        # A GOAL FILED DIRECTLY WINS AND IS NOT OVERWRITTEN. This line
        # used to assign unconditionally, which set objective_id back to
        # None for every task filed the simple way — the walk finds
        # nothing because there is no initiative to walk from, which is
        # the entire point of filing it directly.
        if not t.get("objective_id"):
            t["objective_id"] = obj_id


def _build_task_dict(t, project, today):
    """Build a normalised task dict for template rendering."""
    due = t.get("due_date")

    # Pre-format due label server-side to avoid client-side flash
    due_label = None
    if due:
        try:
            due_d = date.fromisoformat(due)
            diff = (due_d - today).days
            if diff == 0:
                due_label = "⏰ Today"
            elif diff == 1:
                due_label = "⏰ Tomorrow"
            elif diff < 0:
                due_label = f"⚠ {abs(diff)}d overdue"
            else:
                due_label = f"📅 In {diff}d"
        except ValueError:
            due_label = f"📅 {due}"

    return {
        "task_id": t["task_id"],
        "task_text": t["task_text"],
        "status": t.get("status"),
        "done": t.get("status") == "done",
        "start_date": t.get("start_date"),
        "duration_days": t.get("duration_days") or 0,
        "due_date": due,
        "due_label": due_label,
        "due_time": t.get("due_time"),
        "delegated_to": t.get("delegated_to"),
        "project_name": project["name"],
        "priority": t.get("priority", "medium"),
        "priority_rank": PRIORITY_MAP.get(t.get("priority"), 2),
        "is_pinned": t.get("is_pinned", False),
        "planned_hours": t.get("planned_hours") or 0,
        "actual_hours": t.get("actual_hours") or 0,
        "is_recurring": t.get("is_recurring", False),
        "recurrence_type": t.get("recurrence_type", "none"),
        "recurrence_days": t.get("recurrence_days"),
        "recurrence_interval": t.get("recurrence_interval"),
        "recurrence_end": t.get("recurrence_end"),
        "auto_advance": t.get("auto_advance", True),
        "recurrence_badge": build_recurrence_badge(t),
        "occurrence_date": due or today.isoformat(),
        "eisenhower_sent": False,
        "missed_eisenhower": False,
        "eisenhower_plan_date": None,
        "key_result_id": t.get("key_result_id"),
        "initiative_id": t.get("initiative_id"),
    }


@projects_bp.route("/projects/<project_id>/tasks/add-ajax", methods=["POST"])
@login_required
def add_project_task_ajax(project_id):
    """Async task add — returns rendered card HTML + task_id.

    Accepts an optional `initiative_id`. When empty/null the task is tied
    only to the project (no initiative linkage) — valid by design so users
    can add quick tasks without forcing them into an OKR hierarchy.
    """
    data = request.get_json() or {}
    text = (data.get("task_text") or "").strip()
    if not text:
        return jsonify({"error": "Task text required"}), 400

    priority = data.get("priority", "medium")
    start_date = data.get("start_date") or user_today().isoformat()

    # Normalize the initiative id: empty string / "null" / None → NULL
    raw_init = data.get("initiative_id")
    initiative_id = raw_init if (raw_init and str(raw_init).strip() not in ("", "null")) else None
    raw_epic = data.get("epic_id")
    epic_id = raw_epic if (raw_epic and str(raw_epic).strip() not in ("", "null")) else None
    raw_sprint = data.get("sprint_id")
    sprint_id = raw_sprint if (raw_sprint and str(raw_sprint).strip() not in ("", "null")) else None

    # No epic supplied → drop into the project's default epic so every
    # task lives somewhere in the OKR tree. _default_epic_id lazily
    # provisions the trio if the migration hasn't run yet.
    if not epic_id:
        epic_id = _default_epic_id(session["user_id"], project_id)

    # When an epic is picked but no initiative, back-fill from the epic's
    # parent so legacy filters that key on initiative_id keep working.
    if epic_id and not initiative_id:
        ep_rows = get(
            "epics",
            params={
                "id":         f"eq.{epic_id}",
                "user_id":    f"eq.{session['user_id']}",
                "is_deleted": "eq.false",
                "select":     "initiative_id",
                "limit":      1,
            },
        ) or []
        if ep_rows:
            initiative_id = ep_rows[0].get("initiative_id") or None

    # THE GOAL, filed directly. Optional and additive: a request that
    # sends none behaves exactly as before.
    raw_goal = data.get("objective_id")
    objective_id = raw_goal if (raw_goal and str(raw_goal).strip() not in ("", "null")) else None

    max_order = get_max_order_index(project_id)
    payload = {
        "project_id": project_id,
        "user_id": session["user_id"],
        "task_text": text,
        "status": "open",
        "priority": priority,
        "priority_rank": PRIORITY_MAP.get(priority, 2),
        "start_date": start_date,
        "order_index": (max_order or 0) + 1,
    }
    if initiative_id:
        payload["initiative_id"] = initiative_id
    if epic_id:
        payload["epic_id"] = epic_id
    if objective_id:
        payload["objective_id"] = objective_id
    if sprint_id:
        payload["sprint_id"] = sprint_id
    # Optional due_date — the v2 tree-tab "+ Task" dialog passes one;
    # the legacy sticky add-bar leaves it null and the user sets it
    # later via the task detail panel.
    due_date = (data.get("due_date") or "").strip() or None
    if due_date:
        payload["due_date"] = due_date

    try:
        result = post("project_tasks", payload)
    except Exception as e:
        # THE COLUMN MAY NOT BE THERE YET. objective_id ships with
        # MIGRATION_TASK_OBJECTIVE.sql, and a migration file in the repo
        # is not a column in production — this codebase has been caught
        # by exactly that before. Retry without it so adding a task keeps
        # working on an un-migrated database; the goal is simply not
        # recorded until the migration runs.
        if "objective_id" not in payload:
            raise
        logger.warning("project task insert retry without objective_id: %s", e)
        payload.pop("objective_id", None)
        result = post("project_tasks", payload)

    if not result:
        return jsonify({"error": "Insert failed"}), 500

    raw = result[0]
    today = user_today()

    # Minimal project stub for _build_task_dict
    project_stub = {"name": ""}
    task = _build_task_dict(raw, project_stub, today)

    # THE SAME ROW THE LIST RENDERS, not a lookalike. This used to return
    # _project_task_card.html — a card — while the page is a table of
    # rows, so the client could not use it and reloaded the whole page
    # after every task. Rendering the list's own partial means the added
    # row is, by construction, identical to the one a refresh would draw.
    # group_tasks_smart returns EVERY bucket, empty ones included, so the
    # first key is always "Today" whatever the task's date. Take the
    # bucket that actually holds it.
    _grouped = group_tasks_smart([task])
    group = next((k for k, v in _grouped.items() if v), "")
    html = render_template(
        "_project_task_row.html",
        t=task,
        group_name=group,
        today=today.isoformat(),
    )
    return jsonify({
        "html": html,
        "task_id": raw["task_id"],
        # Which section it belongs in, decided by the SAME grouper the
        # page uses. Letting the client guess is how a task ends up under
        # "Today" until you refresh and find it under "Later".
        "group": group,
    })


def compute_due_date(start_date, duration_days):
    return start_date + timedelta(days=duration_days)


def get_max_order_index(project_id):
    rows = get(
        "project_tasks",
        params={
            "project_id": f"eq.{project_id}",
            "select": "order_index",
            "order": "order_index.desc",
            "limit": 1
        }
    )
    return rows[0]["order_index"] if rows else None

def build_recurrence_badge(t):
    if not t.get("is_recurring"):
        return None

    rtype = t.get("recurrence_type")

    if rtype == "daily":
        return "🔁 Daily"

    if rtype == "weekly":
        return "🔁 Weekly"

    if rtype == "monthly":
        return "🔁 Monthly"

    return "🔁"
def insert_many(table, rows, prefer="return=representation"):
    """
    Insert multiple rows into a Supabase table.
    rows: list[dict]
    """
    return post(table, rows, prefer=prefer)





@projects_bp.route("/projects/list")
@login_required
def list_projects():

    projects = get(
        "projects",
        params={
            "user_id": f"eq.{session['user_id']}",
            "order": "name.asc"
        }
    )

    return jsonify(projects or [])