import calendar
from collections import OrderedDict
from datetime import date, datetime, timedelta

# Unified status set (matches project_tasks status dropdowns)
_OPEN_STATUSES = {"open", "in_progress"}
_RESOLVED_STATUSES = {"done", "skipped", "deleted"}
_ALL_STATUSES = _OPEN_STATUSES | _RESOLVED_STATUSES

# Legacy alias — any historical rows stored under the old label are surfaced
# as "deleted" to callers, and inbound "not_required" requests get mapped to
# "deleted" for backward compat.
def _normalize_status(s):
    s = (s or "").strip().lower()
    if s == "not_required":
        return "deleted"
    return s if s in _ALL_STATUSES else ""

# Priority vocabulary shared with project_tasks
_VALID_PRIORITIES = {"low", "medium", "high"}

# Schema note — run once in Supabase if not already present:
#   alter table todo_matrix add column if not exists priority text default 'medium';

from flask import Blueprint, jsonify, redirect, render_template, render_template_string, request, session, url_for

from auth import login_required
from config import IST
from utils.user_tz import user_now, user_today
from services.eisenhower_service import (
    autosave_task,
    enable_travel_mode,
    list_travel_categories,
    list_travel_tasks,
)
from supabase_client import delete as sb_delete
from services.recurring_service import materialize_recurring_tasks
from services.task_service import update_task_occurrence
from supabase_client import get, post, update
from templates.todo import TODO_TEMPLATE
import logging
logger = logging.getLogger(__name__)

todo_bp = Blueprint("todo", __name__)

# ==========================================================
# ROUTES – EISENHOWER MATRIX
# ==========================================================
@todo_bp.route("/todo", methods=["GET"])
@login_required
def todo():
    expire_old_eisenhower_tasks(session["user_id"])

    year = int(request.args.get("year", user_today().year))
    month = int(request.args.get("month", user_today().month))
    day = int(request.args.get("day", user_today().day))

    plan_date = date(year, month, day)

    user_id = session["user_id"]

    # 0️⃣ Materialize recurring tasks for this date (idempotent — safe to call always)
    try:
        materialize_recurring_tasks(plan_date, user_id)
    except Exception as e:
        logger.warning("Failed to materialize recurring tasks: %s", e)

    # 1️⃣ Fetch standalone Eisenhower tasks
    raw_tasks = get(
        "todo_matrix",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{plan_date.isoformat()}",
            "is_deleted": "eq.false"
        }
    )

    # 2️⃣ Fetch projects for labeling
    projects = get("projects", params={"user_id": f"eq.{user_id}"})
    project_map = {p["project_id"]: p["name"] for p in projects}

    # 2b️⃣ Build recurrence map for badge display
    recurring_ids = {t.get("recurring_id") for t in raw_tasks if t.get("recurring_id")}
    recurrence_map = {}
    if recurring_ids:
        rules = get(
            "recurring_tasks",
            params={
                "id": f"in.({','.join(str(r) for r in recurring_ids)})",
                "select": "id,recurrence",
            },
        ) or []
        recurrence_map = {r["id"]: r.get("recurrence") for r in rules}

    # 3️⃣ Normalize standalone tasks
    tasks = []
    for t in raw_tasks:
        tasks.append({
            "id": t["id"],
            "task_text": t["task_text"],
            "quadrant": t["quadrant"],
            "is_done": t.get("is_done", False),
            "status": t.get("status") or ("done" if t.get("is_done") else "open"),
            "priority": (t.get("priority") or "medium"),
            "recurrence": recurrence_map.get(t.get("recurring_id")),
            "project_id": t.get("project_id"),
            "project_name": project_map.get(t.get("project_id")),
            "source_task_id": t.get("source_task_id"),
            "task_date": t.get("task_date"),
            "task_time": t.get("task_time"),
            "delegated_to": t.get("delegated_to"),
            "source": "matrix",
        })

    # 4️⃣ Fetch planner events with quadrant set for this date
    events_with_q = get("daily_events", params={
        "user_id": f"eq.{user_id}",
        "plan_date": f"eq.{plan_date.isoformat()}",
        "is_deleted": "eq.false",
        "quadrant": "neq.",
        "select": "id,title,quadrant,status,start_time,end_time,priority",
    }) or []

    for e in events_with_q:
        if e.get("quadrant"):
            tasks.append({
                "id": f"ev-{e['id']}",
                "task_text": f"📅 {e.get('start_time','')[:5]} {e['title']}",
                "quadrant": e["quadrant"],
                "is_done": e.get("status") == "done",
                "status": e.get("status") or "open",
                "priority": (e.get("priority") or "medium"),
                "recurrence": None,
                "project_id": None,
                "project_name": None,
                "source_task_id": None,
                "source": "event",
            })

    # 5️⃣ Fetch project tasks with quadrant set
    # Include: non-recurring tasks due on/before selected date, OR any recurring task
    proj_tasks_q = get("project_tasks", params={
        "user_id": f"eq.{user_id}",
        "is_eliminated": "eq.false",
        "quadrant": "neq.",
        "select": "task_id,task_text,quadrant,status,priority,project_id,"
                  "due_date,due_time,delegated_to,"
                  "is_recurring,recurrence_type,recurrence_days,"
                  "initiative_id,key_result_id",
        "limit": 200,
    }) or []

    # 5b️⃣ Build an OKR display map for each task. The canonical path is
    # task → initiative → key_result → objective. Legacy rows that still
    # have only `key_result_id` set (pre-Initiative layer) get handled as
    # a fallback so no task loses its pill.
    initiative_ids = {t["initiative_id"] for t in proj_tasks_q if t.get("initiative_id")}
    legacy_kr_ids = {
        t["key_result_id"] for t in proj_tasks_q
        if t.get("key_result_id") and not t.get("initiative_id")
    }

    # task_id → {title (KR), goal_title (objective), color}
    okr_display_map = {}

    try:
        initiative_rows = []
        if initiative_ids:
            initiative_rows = get(
                "initiatives",
                params={
                    "user_id": f"eq.{user_id}",
                    "id": f"in.({','.join(str(i) for i in initiative_ids)})",
                    "is_deleted": "eq.false",
                    "select": "id,title,key_result_id",
                    "limit": 500,
                },
            ) or []

        # All KR ids we need — from initiatives AND from legacy direct links
        kr_ids_needed = {r["key_result_id"] for r in initiative_rows if r.get("key_result_id")}
        kr_ids_needed.update(legacy_kr_ids)

        kr_rows = []
        if kr_ids_needed:
            kr_rows = get(
                "key_results",
                params={
                    "user_id": f"eq.{user_id}",
                    "id": f"in.({','.join(str(i) for i in kr_ids_needed)})",
                    "is_deleted": "eq.false",
                    "select": "id,title,objective_id",
                    "limit": 500,
                },
            ) or []
        kr_by_id = {r["id"]: r for r in kr_rows}

        objective_ids_needed = {r["objective_id"] for r in kr_rows if r.get("objective_id")}
        objective_rows = []
        if objective_ids_needed:
            objective_rows = get(
                "objectives",
                params={
                    "user_id": f"eq.{user_id}",
                    "id": f"in.({','.join(str(i) for i in objective_ids_needed)})",
                    "is_deleted": "eq.false",
                    "select": "id,title,color",
                    "limit": 500,
                },
            ) or []
        objective_by_id = {r["id"]: r for r in objective_rows}

        # Map initiative → {kr, objective, initiative_title}
        initiative_meta = {}
        for i in initiative_rows:
            kr = kr_by_id.get(i.get("key_result_id")) or {}
            obj = objective_by_id.get(kr.get("objective_id")) or {}
            initiative_meta[i["id"]] = {
                "kr_title": kr.get("title"),
                "initiative_title": i.get("title"),
                "objective_title": obj.get("title"),
                "color": obj.get("color") or "#10b981",
                "initiative_id": i["id"],
                "key_result_id": kr.get("id"),
                "objective_id": obj.get("id"),
            }

        # Map legacy kr → {kr, objective}
        legacy_meta = {}
        for kr_id in legacy_kr_ids:
            kr = kr_by_id.get(kr_id)
            if not kr:
                continue
            obj = objective_by_id.get(kr.get("objective_id")) or {}
            legacy_meta[kr_id] = {
                "kr_title": kr.get("title"),
                "initiative_title": None,
                "objective_title": obj.get("title"),
                "color": obj.get("color") or "#10b981",
                "initiative_id": None,
                "key_result_id": kr.get("id"),
                "objective_id": obj.get("id"),
            }

        # Stamp each task's row
        for t in proj_tasks_q:
            meta = None
            if t.get("initiative_id"):
                meta = initiative_meta.get(t["initiative_id"])
            elif t.get("key_result_id"):
                meta = legacy_meta.get(t["key_result_id"])
            if meta:
                okr_display_map[t["task_id"]] = meta
    except Exception as e:
        logger.warning("OKR display lookup failed: %s", e)

    target_weekday = plan_date.weekday()
    today_iso = user_today().isoformat()
    parked_tasks = []

    for t in proj_tasks_q:
        if not t.get("quadrant"):
            continue

        # Skip completed tasks (unless we want to show them)
        if t.get("status") == "done":
            continue

        is_recurring = t.get("is_recurring")
        due_date_str = t.get("due_date")
        # Effective date for scheduling = the user's latest revision if
        # they've reset it, else fall back to the original due_date so
        # untouched tasks behave exactly as before. Recurring tasks
        # ignore this and use the recurrence rule.
        effective_date_str = t.get("revised_due_date") or due_date_str

        # Determine if this task applies to the selected date
        applies = False

        if is_recurring:
            # Recurring task — check if it matches the selected date
            rec_type = t.get("recurrence_type")
            if rec_type == "daily":
                applies = True
            elif rec_type == "weekly":
                days = t.get("recurrence_days") or []
                if target_weekday in days:
                    applies = True
            elif rec_type == "monthly":
                # Show on same day of month as effective date if set,
                # else every day.
                if effective_date_str:
                    try:
                        dd = date.fromisoformat(effective_date_str)
                        if plan_date.day == dd.day:
                            applies = True
                    except (ValueError, TypeError):
                        pass
            else:
                applies = True  # Unknown recurrence — show it
        else:
            # Non-recurring — drive scheduling off the effective date.
            if not effective_date_str:
                # No date at all → show today only.
                if plan_date == user_today():
                    applies = True
            else:
                try:
                    dd = date.fromisoformat(effective_date_str)
                    if dd < user_today() and plan_date == user_today():
                        # Effective date elapsed and we're rendering
                        # today's matrix — this task is "Parked". Stash
                        # it so the page can surface it in the Parked
                        # section instead of cluttering the quadrants.
                        parked_tasks.append({
                            "id": f"pt-{t['task_id']}",
                            "task_id": t["task_id"],
                            "task_text": t.get("task_text") or "",
                            "project_id": t.get("project_id"),
                            "project_name": project_map.get(t.get("project_id")),
                            "due_date": due_date_str,
                            "revised_due_date": t.get("revised_due_date"),
                            "effective_date": effective_date_str,
                            "days_overdue": (user_today() - dd).days,
                            "priority": t.get("priority") or "medium",
                            "quadrant": t.get("quadrant"),
                        })
                        continue
                    if dd <= plan_date:
                        applies = True
                except (ValueError, TypeError):
                    pass

        if not applies:
            continue

        recur_badge = ""
        if is_recurring:
            icons = {"daily": "🔁", "weekly": "🔁", "monthly": "🔁"}
            recur_badge = icons.get(t.get("recurrence_type"), "🔁") + " "

        okr_info = okr_display_map.get(t.get("task_id"))
        tasks.append({
            "id": f"pt-{t['task_id']}",
            "task_text": f"📋 {t['task_text']}",
            "quadrant": t["quadrant"],
            "is_done": t.get("status") == "done",
            "status": t.get("status") or "open",
            "priority": (t.get("priority") or "medium"),
            "recurrence": t.get("recurrence_type") if is_recurring else None,
            "project_id": t.get("project_id"),
            "project_name": project_map.get(t.get("project_id")),
            "source_task_id": None,
            "task_date": t.get("due_date"),
            "task_time": t.get("due_time"),
            "delegated_to": t.get("delegated_to"),
            "source": "project",
            # OKR pill: show the KR as the primary label, objective title in the tooltip.
            # When an initiative is present, it's also surfaced in the tooltip so the user
            # can distinguish two tasks under different initiatives of the same KR.
            "kr_title": okr_info["kr_title"] if okr_info else None,
            "kr_goal_title": okr_info["objective_title"] if okr_info else None,
            "kr_initiative_title": okr_info.get("initiative_title") if okr_info else None,
            "kr_color": okr_info["color"] if okr_info else None,
            # Raw OKR ids so the client can filter by Objective/KR/Initiative
            "objective_id": okr_info.get("objective_id") if okr_info else None,
            "key_result_id": okr_info.get("key_result_id") if okr_info else None,
            "initiative_id": okr_info.get("initiative_id") if okr_info else None,
        })

    # 4️⃣ Build Eisenhower view (NO due-date logic here)
    todo = build_eisenhower_view(tasks, plan_date)
    quadrant_counts = compute_quadrant_counts(todo)

    # Travel Mode is "on" for this day when there's at least one
    # non-deleted row with category=Travel. Used to toggle the header
    # button between "Travel Mode" (enable) and "Disable Travel Mode".
    travel_mode_active = any(
        (r.get("category") or "").lower() == "travel"
        for r in raw_tasks
    )

    # When travel mode is OFF but the user had previously disabled it
    # today (leaving soft-deleted Travel rows behind), surface a restore
    # prompt. Only run the extra query in that narrow window.
    travel_mode_restorable_count = 0
    if not travel_mode_active:
        try:
            restorable = get(
                "todo_matrix",
                params={
                    "user_id": f"eq.{user_id}",
                    "plan_date": f"eq.{plan_date.isoformat()}",
                    "category": "eq.Travel",
                    "is_deleted": "eq.true",
                    "status": "eq.deleted",
                    "select": "id",
                },
            ) or []
            travel_mode_restorable_count = len(restorable)
        except Exception as e:
            logger.warning("travel restorable lookup failed: %s", e)

    # 5️⃣ Render
    days = calendar.monthrange(year, month)[1]

    from datetime import datetime as dt
    from config import IST
    today = dt.now(IST).date().isoformat()

    # Sort parked tasks by most-overdue first so the user sees the
    # longest-stale items at the top — they're the highest-signal
    # candidates for either "do today" or "explicitly defer" decisions.
    parked_tasks.sort(key=lambda p: -(p.get("days_overdue") or 0))

    return render_template(
        "todo.html",
        todo=todo,
        plan_date=plan_date,
        year=year,
        month=month,
        today=today,
        quadrant_counts=quadrant_counts,
        projects=projects,
        travel_mode_active=travel_mode_active,
        travel_mode_restorable_count=travel_mode_restorable_count,
        parked_tasks=parked_tasks,
    )


@todo_bp.route("/todo/toggle-done", methods=["POST"])
@login_required
def toggle_todo_done():
    data = request.get_json()

    task_id = data.get("id")

    if not task_id:
        return jsonify({"error": "Missing task id"}), 400

    # The agenda / today's plan view mixes rows from several tables in
    # one list and prefixes each id with its source ("matrix-<uuid>",
    # "bucket-<uuid>", "pt-<uuid>") so the client can route them back
    # to the right endpoint. This endpoint only handles matrix rows;
    # strip "matrix-" defensively and bounce the other prefixes with
    # a clean 4xx instead of letting Postgres reject the malformed
    # UUID with a 500.
    if isinstance(task_id, str):
        if task_id.startswith("matrix-"):
            task_id = task_id[len("matrix-"):]
        elif task_id.startswith("bucket-"):
            return jsonify({
                "error": "Bucket items must be toggled via /api/quick-bucket/<id>/done",
            }), 400
        elif task_id.startswith("pt-"):
            return jsonify({
                "error": "Project tasks must be toggled via /projects/tasks/status",
            }), 400

    # Unified status: open | in_progress | done | skipped | deleted
    # "not_required" is accepted for backward compatibility and mapped to "deleted".
    req_status = _normalize_status(data.get("status"))
    if req_status:
        status = req_status
    else:
        # Legacy checkbox path: is_done flag decides
        status = "done" if bool(data.get("is_done")) else "open"

    is_done = status in _RESOLVED_STATUSES
    is_soft_delete = (status == "deleted")

    # 1️⃣ Fetch task (need source_task_id + recurring_id before update)
    rows = get(
        "todo_matrix",
        params={
            "id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}",
            "select": "source_task_id,recurring_id,plan_date,quadrant,task_text,category,subcategory,project_id",
        },
    )
    task_row = rows[0] if rows else None
    if task_row is None:
        # Scoped to the caller above: no row means not theirs (or gone).
        return jsonify({"error": "Task not found"}), 404

    # 2️⃣ Update Eisenhower task — soft-delete flips is_deleted too
    todo_patch = {"is_done": is_done, "status": status}
    if is_soft_delete:
        todo_patch["is_deleted"] = True
    elif status == "open":
        # Re-opening a task should also undelete it (used by the undo path)
        todo_patch["is_deleted"] = False
    update(
        "todo_matrix",
        params={"id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
        json=todo_patch,
    )

    # 3️⃣ Sync back to project task (non-recurring only)
    if task_row:
        source_task_id = task_row.get("source_task_id")
        recurring_id = task_row.get("recurring_id")
        if source_task_id and not recurring_id:
            if is_soft_delete:
                update(
                    "project_tasks",
                    params={"task_id": f"eq.{source_task_id}", "user_id": f"eq.{session['user_id']}"},
                    json={"status": "deleted", "is_eliminated": True},
                )
            elif is_done:
                update(
                    "project_tasks",
                    params={"task_id": f"eq.{source_task_id}", "user_id": f"eq.{session['user_id']}"},
                    json={"status": status},
                )

    # 4️⃣ Recurring: pre-create the next occurrence so it appears on the next matching date
    next_occurrence_iso = None
    if is_done and task_row and task_row.get("recurring_id"):
        try:
            next_occurrence_iso = _create_next_recurring_instance(
                user_id=session["user_id"],
                recurring_id=task_row["recurring_id"],
                current_plan_date=date.fromisoformat(str(task_row["plan_date"])),
                fallback_quadrant=task_row.get("quadrant"),
                fallback_text=task_row.get("task_text"),
                fallback_category=task_row.get("category"),
                fallback_subcategory=task_row.get("subcategory"),
                fallback_project_id=task_row.get("project_id"),
            )
        except Exception as e:
            logger.warning("Failed to pre-create next recurring occurrence: %s", e)

    return jsonify({"status": "ok", "next_occurrence": next_occurrence_iso})


def _next_recurrence_date(rule, from_date):
    """Return the first date strictly after `from_date` that matches the rule, or None."""
    rtype = rule.get("recurrence")
    end = rule.get("end_date")
    end_date = date.fromisoformat(end) if end else None

    # Daily: next day
    if rtype == "daily":
        nxt = from_date + timedelta(days=1)
        return nxt if (not end_date or nxt <= end_date) else None

    # Weekly: scan next 7 days for matching weekday
    if rtype == "weekly":
        days = rule.get("days_of_week") or []
        if not days:
            return None
        for i in range(1, 8):
            nxt = from_date + timedelta(days=i)
            if nxt.weekday() in days:
                return nxt if (not end_date or nxt <= end_date) else None
        return None

    # Monthly: same day_of_month next month (clamped to last day of that month)
    if rtype == "monthly":
        dom = rule.get("day_of_month") or from_date.day
        year = from_date.year
        month = from_date.month + 1
        if month > 12:
            month = 1
            year += 1
        last_day = calendar.monthrange(year, month)[1]
        nxt = date(year, month, min(dom, last_day))
        return nxt if (not end_date or nxt <= end_date) else None

    return None


def _create_next_recurring_instance(user_id, recurring_id, current_plan_date,
                                    fallback_quadrant, fallback_text,
                                    fallback_category, fallback_subcategory,
                                    fallback_project_id):
    """
    Look up the recurring rule and insert a todo_matrix row for the next
    matching date. Idempotent — skips if a row already exists for that rule+date.
    Returns the ISO date of the next occurrence (or None).
    """
    rule_rows = get(
        "recurring_tasks",
        params={"id": f"eq.{recurring_id}", "is_active": "eq.true"},
    ) or []
    if not rule_rows:
        return None
    rule = rule_rows[0]

    next_date = _next_recurrence_date(rule, current_plan_date)
    if not next_date:
        return None

    # Idempotency guard
    existing = get(
        "todo_matrix",
        params={
            "user_id": f"eq.{user_id}",
            "recurring_id": f"eq.{recurring_id}",
            "plan_date": f"eq.{next_date.isoformat()}",
            "is_deleted": "eq.false",
            "select": "id",
            "limit": 1,
        },
    ) or []
    if existing:
        return next_date.isoformat()

    payload = {
        "user_id": user_id,
        "plan_date": next_date.isoformat(),
        "task_date": next_date.isoformat(),
        "quadrant": rule.get("quadrant") or fallback_quadrant,
        "task_text": rule.get("task_text") or fallback_text,
        "category": rule.get("category") or fallback_category or "General",
        "subcategory": rule.get("subcategory") or fallback_subcategory or "General",
        "is_done": False,
        "is_deleted": False,
        "status": "open",
        "recurring_id": recurring_id,
    }
    if fallback_project_id:
        payload["project_id"] = fallback_project_id

    try:
        post("todo_matrix", payload)
    except Exception as e:
        logger.warning("Insert next recurring instance failed: %s", e)
        return None

    return next_date.isoformat()


# Retired: POST /todo/copy-prev. It duplicated yesterday's unfinished
# rows into today, which distorted historical analytics and had two
# bugs (NameError + missing user_id scope). The Morning Dashboard
# (/summary?view=daily) now surfaces overdue items as a read-through
# view — no duplication required.
def _parse_iso_z(s):
    """Parse an ISO-8601 timestamp from Supabase into a tz-naive UTC datetime.
    Supabase emits offsets like '+00:00', so we normalise to UTC and drop tz
    info — this lets us subtract against datetime.utcnow() (also tz-naive)
    without raising "can't subtract offset-naive and offset-aware"."""
    from datetime import datetime as _dt, timezone as _tz
    if not s:
        return None
    # Normalise both 'Z' and '+00:00' suffixes to a Python-parseable form.
    raw = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        dt = _dt.fromisoformat(raw)
    except ValueError:
        # Fall back to naive parse for any oddly formatted legacy rows.
        return _dt.fromisoformat(s.rstrip("Z"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(_tz.utc).replace(tzinfo=None)
    return dt


@todo_bp.route("/api/v2/timer/start", methods=["POST"])
@login_required
def timer_start():
    """Start a time-tracking session on a task.
    Body: { "source": "matrix"|"project"|"event"|"adhoc",
            "matrix_task_id"?: uuid, "project_task_id"?: uuid,
            "event_id"?: uuid, "label"?: "...",
            "mode"?: "stopwatch"|"pomodoro",
            "target_seconds"?: int }
    If a session for the same task is already running, returns it instead of
    starting a duplicate (idempotent so refreshing doesn't double-count).
    """
    from datetime import datetime as _dt
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}
    source = (data.get("source") or "adhoc").strip()
    if source not in ("matrix", "project", "event", "adhoc"):
        return jsonify({"error": "invalid source"}), 400

    mode = (data.get("mode") or "stopwatch").strip()
    if mode not in ("stopwatch", "pomodoro"):
        mode = "stopwatch"
    target_seconds = data.get("target_seconds")
    try:
        target_seconds = int(target_seconds) if target_seconds is not None else None
    except (TypeError, ValueError):
        target_seconds = None
    if mode == "pomodoro" and (not target_seconds or target_seconds <= 0):
        target_seconds = 25 * 60  # sensible default

    # Single active timer policy: stop any other running timer first so the
    # global widget always reflects exactly one in-flight session.
    # select=* keeps us robust to whether the pomodoro migration has run.
    others = get(
        "task_time_logs",
        params={
            "user_id": f"eq.{user_id}",
            "ended_at": "is.null",
            "select": "*",
            "order": "started_at.desc",
        },
    ) or []
    for o in others:
        # If it's the same task we're starting, prefer to resume rather than stop.
        same = False
        for k in ("matrix_task_id", "project_task_id", "event_id"):
            if data.get(k) and o.get(k) == data.get(k):
                same = True
                break
        if same:
            return jsonify({"id": o["id"], "started_at": o["started_at"], "resumed": True})
        _stop_log(user_id, o)

    label = (data.get("label") or "").strip() or None
    payload = {
        "user_id": user_id,
        "source": source,
        "matrix_task_id":  data.get("matrix_task_id"),
        "project_task_id": data.get("project_task_id"),
        "event_id":        data.get("event_id"),
        "label":           label,
        "started_at":      _dt.utcnow().isoformat() + "Z",
    }
    # Only include pomodoro-specific fields when relevant. The columns have
    # sensible defaults (mode='stopwatch', paused_seconds=0) so omitting
    # them keeps inserts working even if the migration hasn't been applied.
    if mode == "pomodoro":
        payload["mode"] = "pomodoro"
        if target_seconds:
            payload["target_seconds"] = target_seconds
    # Adhoc sessions get an adhoc_task_id so the Focus Log can aggregate
    # totals per label. Best-effort — if the adhoc_tasks migration hasn't
    # run yet, just skip and the row inserts without the back-pointer.
    if source == "adhoc" and label:
        try:
            from routes.focus_log import find_or_create_adhoc_task
            tid = find_or_create_adhoc_task(user_id, label)
            if tid:
                payload["adhoc_task_id"] = tid
        except Exception as _e:
            logging.getLogger("daily_plan").warning(
                "find_or_create_adhoc_task failed: %s", _e
            )
    rows = post("task_time_logs", payload)
    return jsonify({
        "id": rows[0]["id"] if rows else None,
        "started_at": payload["started_at"],
        "mode": mode,
        "target_seconds": target_seconds,
    })


def _stop_log(user_id, row):
    """Compute duration honouring pauses and stamp ended_at on the row.
    Used both by /timer/stop and the auto-stop in /timer/start."""
    from datetime import datetime as _dt
    ended = _dt.utcnow()
    started = _parse_iso_z(row["started_at"])
    paused_seconds = int(row.get("paused_seconds") or 0)
    if row.get("paused_at"):
        # Currently paused — count the still-paused interval as paused too.
        paused_at = _parse_iso_z(row["paused_at"])
        paused_seconds += int((ended - paused_at).total_seconds())
    duration = max(0, int((ended - started).total_seconds()) - paused_seconds)
    update(
        "task_time_logs",
        params={"id": f"eq.{row['id']}", "user_id": f"eq.{user_id}"},
        json={
            "ended_at": ended.isoformat() + "Z",
            "duration_seconds": duration,
            "paused_seconds": paused_seconds,
            "paused_at": None,
        },
    )
    return duration


@todo_bp.route("/api/v2/timer/stop", methods=["POST"])
@login_required
def timer_stop():
    """Stop a running timer. Body: { "id": uuid }
    Subtracts paused time so duration reflects actual focus."""
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}
    log_id = data.get("id")
    if not log_id:
        return jsonify({"error": "id required"}), 400

    rows = get(
        "task_time_logs",
        params={"id": f"eq.{log_id}", "user_id": f"eq.{user_id}",
                "select": "*"},
    ) or []
    if not rows:
        return jsonify({"error": "log not found"}), 404
    row = rows[0]
    if row.get("ended_at"):
        return jsonify({"ok": True, "already_stopped": True})

    duration = _stop_log(user_id, row)
    return jsonify({"ok": True, "duration_seconds": duration})


@todo_bp.route("/api/v2/timer/pause", methods=["POST"])
@login_required
def timer_pause():
    """Pause a running timer. Body: { "id": uuid }
    Stamps paused_at; the elapsed-since-pause interval is added to
    paused_seconds on resume (or stop)."""
    from datetime import datetime as _dt
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}
    log_id = data.get("id")
    if not log_id:
        return jsonify({"error": "id required"}), 400

    rows = get(
        "task_time_logs",
        params={"id": f"eq.{log_id}", "user_id": f"eq.{user_id}",
                "select": "*"},
    ) or []
    if not rows:
        return jsonify({"error": "log not found"}), 404
    row = rows[0]
    if row.get("ended_at"):
        return jsonify({"error": "already stopped"}), 400
    if row.get("paused_at"):
        return jsonify({"ok": True, "already_paused": True, "paused_at": row["paused_at"]})

    now_iso = _dt.utcnow().isoformat() + "Z"
    update(
        "task_time_logs",
        params={"id": f"eq.{log_id}", "user_id": f"eq.{user_id}"},
        json={"paused_at": now_iso},
    )
    return jsonify({"ok": True, "paused_at": now_iso})


@todo_bp.route("/api/v2/timer/resume", methods=["POST"])
@login_required
def timer_resume():
    """Resume a paused timer. Body: { "id": uuid }
    Folds (now - paused_at) into paused_seconds and clears paused_at."""
    from datetime import datetime as _dt
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}
    log_id = data.get("id")
    if not log_id:
        return jsonify({"error": "id required"}), 400

    rows = get(
        "task_time_logs",
        params={"id": f"eq.{log_id}", "user_id": f"eq.{user_id}",
                "select": "*"},
    ) or []
    if not rows:
        return jsonify({"error": "log not found"}), 404
    row = rows[0]
    if row.get("ended_at"):
        return jsonify({"error": "already stopped"}), 400
    if not row.get("paused_at"):
        return jsonify({"ok": True, "not_paused": True})

    now = _dt.utcnow()
    paused_at = _parse_iso_z(row["paused_at"])
    delta = max(0, int((now - paused_at).total_seconds()))
    new_paused = int(row.get("paused_seconds") or 0) + delta
    update(
        "task_time_logs",
        params={"id": f"eq.{log_id}", "user_id": f"eq.{user_id}"},
        json={"paused_at": None, "paused_seconds": new_paused},
    )
    return jsonify({"ok": True, "paused_seconds": new_paused})


@todo_bp.route("/api/v2/timer/active", methods=["GET"])
@login_required
def timer_active():
    """Return all currently-running timers for the user (usually 0 or 1).
    Used on page load to restore the timer UI when the user returns.
    For each row also resolves the task title so the global widget can
    display "Pomodoro · <task name>" without a second round-trip."""
    user_id = session["user_id"]
    rows = get(
        "task_time_logs",
        params={
            "user_id": f"eq.{user_id}",
            "ended_at": "is.null",
            "select": "*",
            "order": "started_at.desc",
        },
    ) or []

    # Resolve titles in bulk so the global widget can show "Pomodoro · <task>"
    # without a second round-trip. Column names follow the existing schema:
    # todo_matrix.task_text, project_tasks.task_text, daily_events.title.
    matrix_ids  = [r["matrix_task_id"]  for r in rows if r.get("matrix_task_id")]
    project_ids = [r["project_task_id"] for r in rows if r.get("project_task_id")]
    event_ids   = [r["event_id"]        for r in rows if r.get("event_id")]
    title_map = {}
    if matrix_ids:
        mrows = get("todo_matrix",
                    params={"id": f"in.({','.join(matrix_ids)})",
                            "user_id": f"eq.{user_id}",
                            "select": "id,task_text"}) or []
        for m in mrows:
            title_map[("matrix", m["id"])] = m.get("task_text")
    if project_ids:
        prows = get("project_tasks",
                    params={"task_id": f"in.({','.join(project_ids)})",
                            "user_id": f"eq.{user_id}",
                            "select": "task_id,task_text"}) or []
        for p in prows:
            title_map[("project", p["task_id"])] = p.get("task_text")
    if event_ids:
        erows = get("daily_events",
                    params={"id": f"in.({','.join(event_ids)})",
                            "user_id": f"eq.{user_id}",
                            "select": "id,title"}) or []
        for e in erows:
            title_map[("event", e["id"])] = e.get("title")

    for r in rows:
        if r.get("matrix_task_id"):
            r["title"] = title_map.get(("matrix", r["matrix_task_id"]))
        elif r.get("project_task_id"):
            r["title"] = title_map.get(("project", r["project_task_id"]))
        elif r.get("event_id"):
            r["title"] = title_map.get(("event", r["event_id"]))
        else:
            r["title"] = r.get("label")

    return jsonify({"active": rows})


@todo_bp.route("/todo/reschedule", methods=["POST"])
@login_required
def reschedule_eisenhower_task():
    """Push a matrix task's task_date forward (or to a specific date).

    Body shapes accepted:
      { "id": "<uuid>", "due_date": "YYYY-MM-DD" }     # explicit date
      { "id": "<uuid>", "shift_days": 1 }              # +1 day from today
      { "id": "<uuid>", "shift_days": 7 }              # next week, etc.

    Returns the new due_date so the client can confirm and update its
    own DOM without a full refresh.
    """
    from datetime import date as _date, timedelta as _td

    data = request.get_json(force=True) or {}
    task_id = data.get("id")
    if not task_id:
        return jsonify({"error": "Missing task id"}), 400

    new_date = data.get("due_date")
    if not new_date:
        try:
            shift = int(data.get("shift_days") or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid shift_days"}), 400
        if shift <= 0:
            return jsonify({"error": "shift_days must be positive"}), 400
        new_date = (_date.today() + _td(days=shift)).isoformat()

    user_id = session["user_id"]
    update(
        "todo_matrix",
        params={"id": f"eq.{task_id}", "user_id": f"eq.{user_id}"},
        json={"task_date": new_date, "plan_date": new_date},
    )
    return jsonify({"status": "ok", "due_date": new_date})


@todo_bp.route("/todo/move", methods=["POST"])
@login_required
def move_eisenhower_task():
    data = request.get_json()
    task_id = data["id"]
    quadrant = data["quadrant"]
    

    update(
        "todo_matrix",
        params={"id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
        json={"quadrant": quadrant}
    )

    return jsonify({"status": "ok"})


@todo_bp.route("/todo/travel-mode", methods=["POST"])
@login_required
def travel_mode():
    user_id = session["user_id"]
    year = int(request.form["year"])
    month = int(request.form["month"])
    day = int(request.form["day"])
    plan_date = date(year, month, day)

    # Optional travel template category (e.g. "Domestic", "International").
    # When omitted, ALL of the user's travel_tasks are applied.
    category = (request.form.get("category") or "").strip() or None

    # When the user picks "Start fresh" in the restore modal, push any
    # previously soft-deleted travel rows into a frozen bucket so they
    # stop showing up as restorable. Soft-delete only — per project
    # policy, no hard delete.
    if request.form.get("archive_previous") == "1":
        try:
            update(
                "todo_matrix",
                params={
                    "user_id": f"eq.{user_id}",
                    "plan_date": f"eq.{plan_date.isoformat()}",
                    "category": "eq.Travel",
                    "is_deleted": "eq.true",
                },
                json={"category": "Travel-archived"},
            )
        except Exception as e:
            logger.warning("archive_previous travel rows failed: %s", e)

    added = enable_travel_mode(plan_date, category=category)
    logger.info(f"Travel Mode enabled: {added} tasks added (category={category})")

    return redirect(url_for(
        "todo.todo",
        year=plan_date.year, month=plan_date.month, day=plan_date.day,
        travel=1,
    ))


@todo_bp.route("/todo/travel-mode/disable", methods=["POST"])
@login_required
def travel_mode_disable():
    """Soft-delete only the PRISTINE travel-category tasks on this
    plan_date — rows the user hasn't touched (not completed, not moved
    through a non-open status). Rows the user edited (checked off,
    marked in_progress/skipped, etc.) are preserved so the user never
    loses work.

    Soft-delete only (is_deleted=true + status=deleted) — per project
    policy we never hard-delete."""
    user_id = session["user_id"]
    year = int(request.form["year"])
    month = int(request.form["month"])
    day = int(request.form["day"])
    plan_date = date(year, month, day)

    try:
        travel_rows = get(
            "todo_matrix",
            params={
                "user_id": f"eq.{user_id}",
                "plan_date": f"eq.{plan_date.isoformat()}",
                "category": "eq.Travel",
                "is_deleted": "eq.false",
                "select": "id,is_done,status",
            },
        ) or []

        pristine_ids = [
            r["id"] for r in travel_rows
            if not r.get("is_done") and (r.get("status") in (None, "", "open"))
        ]
        kept = len(travel_rows) - len(pristine_ids)

        if pristine_ids:
            update(
                "todo_matrix",
                params={
                    "id": f"in.({','.join(str(i) for i in pristine_ids)})",
                },
                json={"is_deleted": True, "status": "deleted"},
            )

        logger.info(
            "Travel Mode disabled: %d pristine tasks soft-deleted, %d kept (edited/completed)",
            len(pristine_ids), kept,
        )
    except Exception as e:
        logger.exception("Failed to disable Travel Mode: %s", e)

    return redirect(url_for(
        "todo.todo",
        year=plan_date.year, month=plan_date.month, day=plan_date.day,
    ))


@todo_bp.route("/todo/travel-mode/restore", methods=["POST"])
@login_required
def travel_mode_restore():
    """Restore the travel rows that were soft-deleted by the most recent
    disable. Un-deletes them and resets status to 'open'."""
    user_id = session["user_id"]
    year = int(request.form["year"])
    month = int(request.form["month"])
    day = int(request.form["day"])
    plan_date = date(year, month, day)

    try:
        update(
            "todo_matrix",
            params={
                "user_id": f"eq.{user_id}",
                "plan_date": f"eq.{plan_date.isoformat()}",
                "category": "eq.Travel",
                "is_deleted": "eq.true",
                "status": "eq.deleted",
            },
            json={"is_deleted": False, "status": "open"},
        )
    except Exception as e:
        logger.exception("Failed to restore Travel Mode: %s", e)

    return redirect(url_for(
        "todo.todo",
        year=plan_date.year, month=plan_date.month, day=plan_date.day,
    ))


# ==========================================================
# ROUTES – BULK UPDATE (selection mode)
# ==========================================================

@todo_bp.route("/todo/bulk-update", methods=["POST"])
@login_required
def todo_bulk_update():
    """
    Apply a patch to many todo_matrix rows at once.

    Body: { ids: [uuid, ...], patch: { status?, priority? } }

    Only the Eisenhower matrix owns these rows (source='matrix' on the
    client side). Event/project-sourced cards render read-only in the
    matrix and are rejected here by the user_id scope — their IDs are
    prefixed ('ev-', 'pt-') so the lookup naturally finds nothing.

    Soft-delete (status='deleted') also flips is_deleted=true and
    cascades is_eliminated=true to any linked project_tasks rows.
    """
    data = request.get_json(force=True) or {}
    ids = data.get("ids") or []
    patch = data.get("patch") or {}

    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "ids required"}), 400
    if not isinstance(patch, dict) or not patch:
        return jsonify({"error": "patch required"}), 400

    user_id = session["user_id"]

    # Build the actual DB patch from the validated fields
    db_patch = {}

    if "status" in patch:
        status = _normalize_status(patch["status"])
        if not status:
            return jsonify({"error": "invalid status"}), 400
        db_patch["status"] = status
        db_patch["is_done"] = status in _RESOLVED_STATUSES
        if status == "deleted":
            db_patch["is_deleted"] = True
        elif status == "open":
            # Reopening also un-deletes (used by undo from trash)
            db_patch["is_deleted"] = False

    if "priority" in patch:
        priority = (patch["priority"] or "").strip().lower()
        if priority not in _VALID_PRIORITIES:
            return jsonify({"error": "invalid priority"}), 400
        db_patch["priority"] = priority

    # Extended fields for the unified detail panel (Option B). Matrix rows
    # get a subset of the project-task schema so a single panel UI can
    # edit both sources with one code path on the client.
    if "task_text" in patch:
        text = (patch.get("task_text") or "").strip()
        if text:
            db_patch["task_text"] = text
    if "task_date" in patch:
        # YYYY-MM-DD or null to clear
        v = patch["task_date"]
        db_patch["task_date"] = (v or None)
    if "task_time" in patch:
        v = patch["task_time"]
        db_patch["task_time"] = (v or None)
    if "quadrant" in patch:
        q = (patch.get("quadrant") or "").strip().lower()
        if q and q not in ("do", "schedule", "delegate", "eliminate"):
            return jsonify({"error": "invalid quadrant"}), 400
        db_patch["quadrant"] = q or None
    if "delegated_to" in patch:
        db_patch["delegated_to"] = (patch.get("delegated_to") or None)

    if not db_patch:
        return jsonify({"error": "no valid fields in patch"}), 400

    # Sanitize IDs — only keep non-empty strings and strip client-side prefixes
    # we know are not matrix rows (ev-, pt-).
    clean_ids = [
        str(i) for i in ids
        if isinstance(i, (str, int)) and str(i) and not str(i).startswith(("ev-", "pt-"))
    ]
    if not clean_ids:
        return jsonify({"error": "no valid matrix ids"}), 400

    # Fetch the rows BEFORE updating so we can cascade soft-deletes to
    # linked project tasks (only non-recurring ones get cascaded).
    existing = get(
        "todo_matrix",
        params={
            "user_id": f"eq.{user_id}",
            "id": f"in.({','.join(clean_ids)})",
            "is_deleted": "eq.false",
            "select": "id,source_task_id,recurring_id",
            "limit": len(clean_ids),
        },
    ) or []

    if not existing:
        return jsonify({"status": "ok", "updated": 0})

    matrix_ids = [r["id"] for r in existing]

    # Single bulk update
    update(
        "todo_matrix",
        params={
            "user_id": f"eq.{user_id}",
            "id": f"in.({','.join(str(i) for i in matrix_ids)})",
        },
        json=db_patch,
    )

    # Cascade soft-delete to linked project tasks (non-recurring only)
    if db_patch.get("status") == "deleted":
        cascade_ids = [
            str(r["source_task_id"]) for r in existing
            if r.get("source_task_id") and not r.get("recurring_id")
        ]
        if cascade_ids:
            update(
                "project_tasks",
                params={
                    "user_id": f"eq.{user_id}",
                    "task_id": f"in.({','.join(cascade_ids)})",
                },
                json={"status": "deleted", "is_eliminated": True},
            )
    elif db_patch.get("status") in _RESOLVED_STATUSES and db_patch["status"] != "deleted":
        # Also cascade plain done/skipped to the linked project_tasks row
        cascade_ids = [
            str(r["source_task_id"]) for r in existing
            if r.get("source_task_id") and not r.get("recurring_id")
        ]
        if cascade_ids:
            update(
                "project_tasks",
                params={
                    "user_id": f"eq.{user_id}",
                    "task_id": f"in.({','.join(cascade_ids)})",
                },
                json={"status": db_patch["status"]},
            )

    return jsonify({"status": "ok", "updated": len(matrix_ids)})


# ==========================================================
# ROUTES – TRAVEL TEMPLATE CRUD
# ==========================================================

@todo_bp.route("/travel/categories", methods=["GET"])
@login_required
def travel_categories():
    return jsonify({"categories": list_travel_categories(session["user_id"])})


@todo_bp.route("/travel/tasks", methods=["GET"])
@login_required
def travel_tasks_list():
    category = (request.args.get("category") or "").strip() or None
    return jsonify({"tasks": list_travel_tasks(session["user_id"], category=category)})


@todo_bp.route("/travel/tasks", methods=["POST"])
@login_required
def travel_tasks_create():
    data = request.get_json(force=True) or {}
    text = (data.get("task_text") or "").strip()
    if not text:
        return jsonify({"error": "task_text required"}), 400

    category = (data.get("category") or "Default").strip() or "Default"
    quadrant = (data.get("quadrant") or "do").strip().lower()
    if quadrant not in ("do", "schedule", "delegate", "eliminate"):
        quadrant = "do"
    subcategory = (data.get("subcategory") or "General").strip() or "General"

    # Place at end of the category's order
    existing = get(
        "travel_tasks",
        params={
            "user_id": f"eq.{session['user_id']}",
            "category": f"eq.{category}",
            "select": "order_index",
            "order": "order_index.desc",
            "limit": 1,
        },
    ) or []
    next_order = (existing[0]["order_index"] + 1) if existing else 0

    rows = post("travel_tasks", {
        "user_id": session["user_id"],
        "category": category,
        "quadrant": quadrant,
        "task_text": text,
        "subcategory": subcategory,
        "order_index": next_order,
    })
    return jsonify({"status": "ok", "task": rows[0] if rows else None})


@todo_bp.route("/travel/tasks/<int:task_id>", methods=["PATCH"])
@login_required
def travel_tasks_update(task_id):
    data = request.get_json(force=True) or {}
    allowed = {"category", "quadrant", "task_text", "subcategory", "order_index"}
    patch = {k: v for k, v in data.items() if k in allowed}
    if not patch:
        return jsonify({"error": "no valid fields"}), 400

    if "quadrant" in patch:
        q = (patch["quadrant"] or "").strip().lower()
        if q not in ("do", "schedule", "delegate", "eliminate"):
            return jsonify({"error": "invalid quadrant"}), 400
        patch["quadrant"] = q
    if "task_text" in patch:
        patch["task_text"] = (patch["task_text"] or "").strip()
        if not patch["task_text"]:
            return jsonify({"error": "task_text required"}), 400

    update(
        "travel_tasks",
        params={
            "id": f"eq.{task_id}",
            "user_id": f"eq.{session['user_id']}",
        },
        json=patch,
    )
    return jsonify({"status": "ok"})


@todo_bp.route("/travel/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def travel_tasks_delete(task_id):
    sb_delete(
        "travel_tasks",
        params={
            "id": f"eq.{task_id}",
            "user_id": f"eq.{session['user_id']}",
        },
    )
    return jsonify({"status": "ok"})


@todo_bp.route("/travel/categories", methods=["POST"])
@login_required
def travel_categories_create():
    """
    Create a new travel category.

    Body accepts three shapes:
      1) { name, tasks: [{quadrant, task_text, subcategory}, ...] }
         Creates the category with exactly these rows (used by the Undo flow
         after a category delete).
      2) { name, source_category, template_ids: [int, ...] }
         Copies the specific IDs from any of the user's existing rows.
      3) { name, source_category }
         Copies every task from source_category (defaults to "Default").

    The new rows always get a fresh order_index starting at 0.
    """
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400

    user_id = session["user_id"]

    # Refuse if category already exists for this user
    existing_same = get(
        "travel_tasks",
        params={
            "user_id": f"eq.{user_id}",
            "category": f"eq.{name}",
            "select": "id",
            "limit": 1,
        },
    ) or []
    if existing_same:
        return jsonify({"error": f'Category "{name}" already exists'}), 409

    # --- Shape 1: raw tasks (undo restore) ---
    raw_tasks = data.get("tasks")
    if isinstance(raw_tasks, list):
        payload = []
        for idx, t in enumerate(raw_tasks):
            text = (t.get("task_text") or "").strip()
            if not text:
                continue
            q = (t.get("quadrant") or "do").strip().lower()
            if q not in ("do", "schedule", "delegate", "eliminate"):
                q = "do"
            payload.append({
                "user_id": user_id,
                "category": name,
                "quadrant": q,
                "task_text": text,
                "subcategory": (t.get("subcategory") or "General").strip() or "General",
                "order_index": idx,
            })
        if not payload:
            return jsonify({"error": "tasks list is empty"}), 400
        post("travel_tasks", payload)
        return jsonify({"status": "ok", "copied": len(payload)})

    # --- Shapes 2 & 3: copy from an existing category ---
    # Ensure Default is seeded for first-run users
    from services.eisenhower_service import _seed_travel_tasks_if_empty
    _seed_travel_tasks_if_empty(user_id)

    template_ids = data.get("template_ids")
    source_category = (data.get("source_category") or "Default").strip() or "Default"

    if isinstance(template_ids, list) and template_ids:
        ids_csv = ",".join(str(int(i)) for i in template_ids if str(i).isdigit())
        if not ids_csv:
            return jsonify({"error": "template_ids must be integers"}), 400
        src = get(
            "travel_tasks",
            params={
                "user_id": f"eq.{user_id}",
                "id": f"in.({ids_csv})",
                "select": "quadrant,task_text,subcategory,order_index",
                "order": "order_index.asc,id.asc",
                "limit": 5000,
            },
        ) or []
    else:
        src = get(
            "travel_tasks",
            params={
                "user_id": f"eq.{user_id}",
                "category": f"eq.{source_category}",
                "select": "quadrant,task_text,subcategory,order_index",
                "order": "order_index.asc,id.asc",
                "limit": 5000,
            },
        ) or []

    if not src:
        # Create an empty category so the user can still add tasks to it
        post("travel_tasks", {
            "user_id": user_id,
            "category": name,
            "quadrant": "do",
            "task_text": "New travel task (edit me)",
            "subcategory": "General",
            "order_index": 0,
        })
        return jsonify({"status": "ok", "copied": 0, "placeholder": True})

    payload = []
    for idx, t in enumerate(src):
        payload.append({
            "user_id": user_id,
            "category": name,
            "quadrant": t.get("quadrant") or "do",
            "task_text": (t.get("task_text") or "").strip(),
            "subcategory": t.get("subcategory") or "General",
            "order_index": idx,
        })

    post("travel_tasks", payload)
    return jsonify({"status": "ok", "copied": len(payload)})


@todo_bp.route("/travel/categories/rename", methods=["POST"])
@login_required
def travel_categories_rename():
    data = request.get_json(force=True) or {}
    old = (data.get("old_name") or "").strip()
    new = (data.get("new_name") or "").strip()
    if not old or not new or old == new:
        return jsonify({"error": "old_name and new_name required and must differ"}), 400
    update(
        "travel_tasks",
        params={
            "user_id": f"eq.{session['user_id']}",
            "category": f"eq.{old}",
        },
        json={"category": new},
    )
    return jsonify({"status": "ok"})


@todo_bp.route("/travel/categories/delete", methods=["POST"])
@login_required
def travel_categories_delete():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    sb_delete(
        "travel_tasks",
        params={
            "user_id": f"eq.{session['user_id']}",
            "category": f"eq.{name}",
        },
    )
    return jsonify({"status": "ok"})

@todo_bp.route("/todo/autosave", methods=["POST"])
@login_required
def todo_autosave():
    data = request.get_json(force=True)
    logger.info("AUTOSAVE DATA: %s", data)

    if "plan_date" not in data or "quadrant" not in data:
        return jsonify({"ignored": True})

    # NEW task (no id) — insert directly
    if "id" not in data:
        user_id = session["user_id"]
        text = (data.get("task_text") or "").strip()
        if not text:
            return jsonify({"ignored": True})

        project_id = data.get("project_id") or None
        source_task_id = None

        quadrant = data["quadrant"]
        due_date = data.get("due_date") or data["plan_date"]
        task_time = data.get("task_time") or None
        delegated_to = data.get("delegated_to") or None
        priority = (data.get("priority") or "medium").strip().lower()
        if priority not in _VALID_PRIORITIES:
            priority = "medium"

        # Quadrant-specific date logic
        if quadrant == "eliminate":
            due_date = None

        # If project selected, also create a project_tasks row
        if project_id:
            try:
                _PRIO_RANK = {"high": 1, "medium": 2, "low": 3}
                pt_rows = post("project_tasks", {
                    "project_id": project_id,
                    "user_id": user_id,
                    "task_text": text,
                    "status": "open",
                    "priority": priority,
                    "priority_rank": _PRIO_RANK.get(priority, 2),
                    "start_date": data["plan_date"],
                    "due_date": due_date,
                    # Mirror to revised_due_date so the task is visible
                    # in the matrix immediately under the parking filter.
                    "revised_due_date": due_date,
                    "due_time": task_time,
                    "delegated_to": delegated_to,
                    "quadrant": quadrant,
                    "order_index": 0,
                })
                if pt_rows:
                    source_task_id = pt_rows[0].get("task_id")
            except Exception as e:
                logger.warning("Failed to create project task from Eisenhower: %s", e)

        # Match the shape that _create_next_recurring_instance uses (which
        # is the only Supabase insert path proven to work against the live
        # schema). The `category` / `subcategory` / `status` fields are
        # NOT-NULL in the current todo_matrix schema — omitting them on the
        # direct autosave path caused a 400 ("null value in column ...
        # violates not-null constraint").
        row_data = {
            "user_id": user_id,
            "plan_date": data["plan_date"],
            "task_date": due_date,
            "quadrant": quadrant,
            "task_text": text,
            "category": data.get("category") or "General",
            "subcategory": data.get("subcategory") or "General",
            "is_done": bool(data.get("is_done", False)),
            "is_deleted": False,
            "status": "done" if bool(data.get("is_done", False)) else "open",
            "priority": priority,
        }
        if task_time:
            row_data["task_time"] = task_time
        if project_id:
            row_data["project_id"] = project_id
        if delegated_to:
            row_data["delegated_to"] = delegated_to
        if source_task_id:
            row_data["source_task_id"] = source_task_id

        # 🔁 Recurring rule — create if specified
        recurrence = (data.get("recurrence") or "").strip().lower() or None
        if recurrence in ("daily", "weekly", "monthly"):
            try:
                plan_d = date.fromisoformat(data["plan_date"])
                rule_payload = {
                    "user_id": user_id,
                    "quadrant": quadrant,
                    "task_text": text,
                    "recurrence": recurrence,
                    "start_date": data["plan_date"],
                    "is_active": True,
                    "category": "General",
                    "subcategory": "General",
                    "day_of_month": plan_d.day if recurrence == "monthly" else None,
                    "days_of_week": [plan_d.weekday()] if recurrence == "weekly" else None,
                }
                rule_rows = post("recurring_tasks", rule_payload)
                if rule_rows:
                    row_data["recurring_id"] = rule_rows[0]["id"]
            except Exception as e:
                logger.warning("Failed to create recurring rule from Eisenhower: %s", e)

        try:
            rows = post("todo_matrix", row_data)
        except Exception as e:
            # Don't crash the worker on a schema mismatch — return a clean
            # JSON error so the client can show a toast instead of a blank 500.
            logger.exception("todo_autosave: insert failed")
            return jsonify({
                "error": f"Failed to save task: {e}",
                "hint": "Check the server log for the exact Supabase error "
                        "(the response body is now captured in supabase_client.post)."
            }), 500
        new_row = rows[0] if rows else None
        new_id = new_row.get("id") if new_row else None

        # Render the new row into the shared task-card partial so the client
        # can drop the HTML straight into the DOM (no reload required).
        rendered_html = None
        if new_row:
            project_name = None
            if project_id:
                try:
                    proj_rows = get(
                        "projects",
                        params={
                            "project_id": f"eq.{project_id}",
                            "user_id": f"eq.{user_id}",
                            "select": "name",
                            "limit": 1,
                        },
                    ) or []
                    if proj_rows:
                        project_name = proj_rows[0].get("name")
                except Exception as e:
                    logger.warning("project lookup for quick-add failed: %s", e)

            normalized = {
                "id": new_id,
                "task_text": text,
                "quadrant": quadrant,
                "is_done": bool(row_data.get("is_done", False)),
                "status": row_data.get("status") or "open",
                "priority": priority,
                "recurrence": recurrence if recurrence in ("daily", "weekly", "monthly") else None,
                "project_id": project_id,
                "project_name": project_name,
                "source_task_id": source_task_id,
                "source": "matrix",
                "task_date": row_data.get("task_date"),
                "task_time": row_data.get("task_time"),
                "delegated_to": delegated_to,
                # Defensive defaults for fields the template may reference
                # via `{% if t.xxx %}` — keeps Jinja's Undefined out of the
                # picture entirely.
                "objective_id": None,
                "key_result_id": None,
                "initiative_id": None,
                "kr_title": None,
                "kr_goal_title": None,
                "kr_initiative_title": None,
                "kr_color": None,
            }
            try:
                rendered_html = render_template(
                    "_em_task_card.html",
                    t=normalized,
                    q=quadrant,
                )
            except Exception as e:
                logger.exception("Failed to render _em_task_card.html: %s", e)

        return jsonify({
            "status": "ok",
            "id": new_id,
            "quadrant": quadrant,
            "html": rendered_html,
        })

    task_id = data["id"]

    # 🔹 EXISTING task — full autosave
    result = autosave_task(
        plan_date=data["plan_date"],
        task_id=task_id,
        quadrant=data["quadrant"],
        text=data.get("task_text"),
        is_done=data.get("is_done", False),
    )

    # 🔒 Preserve project_id if present
    if "project_id" in data:
        update(
            "todo_matrix",
            params={"id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
            json={"project_id": data["project_id"]},
        )

    # 🔁 Sync completion back to project task (if linked)
    if "is_done" in data:
        # get() has no `single` argument — passing one raised a TypeError,
        # so this sync to the linked project task never ran.
        found = get(
            "todo_matrix",
            params={"id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}", "select": "source_task_id"},
        ) or []
        row = found[0] if found else None

        if row and row.get("source_task_id"):
            update(
                "project_tasks",
                params={"task_id": f"eq.{row['source_task_id']}", "user_id": f"eq.{session['user_id']}"},
                json={
                    "status": "done" if data["is_done"] else "open"
                }
            )

    return jsonify(result)

@todo_bp.route("/todo/set-project", methods=["POST"])
@login_required
def todo_set_project():
    data = request.get_json(force=True)

    task_id = data.get("id")
    project_id = data.get("project_id")

    if not task_id:
        return jsonify({"error": "Missing task id"}), 400
    # The project must be the caller's too, or a task could be filed into
    # someone else's project. An empty value clears the link.
    if project_id and not get("projects", params={
            "project_id": f"eq.{project_id}",
            "user_id": f"eq.{session['user_id']}",
            "select": "project_id", "limit": 1}):
        return jsonify({"error": "Project not found"}), 404

    update(
        "todo_matrix",
        params={"id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
        json={"project_id": project_id},
    )

    return jsonify({"status": "ok"})
# ==========================================================
# ROUTES – DAILY PLANNER
# ==========================================================


def empty_quadrant():
    return {"tasks": []}



def build_eisenhower_view(tasks, plan_date):
    """
    Build Eisenhower matrix ONLY from todo_matrix tasks.
    No inference. No due-date logic. No urgency computation.
    """

    todo = {
        "do": empty_quadrant(),
        "schedule": empty_quadrant(),
        "delegate": empty_quadrant(),
        "eliminate": empty_quadrant(),
    }

    for t in tasks:
        quadrant = t.get("quadrant")
        if quadrant not in todo:
            continue  # safety guard

        task = {
            "id": t["id"],
            "task_text": t["task_text"],
            "is_done": t.get("is_done", False),
            "status": t.get("status"),
            "priority": t.get("priority") or "medium",
            "recurrence": t.get("recurrence"),
            "source": t.get("source", "matrix"),
            "project_id": t.get("project_id"),
            "project_name": t.get("project_name"),
            "source_task_id": t.get("source_task_id"),
            "task_date": t.get("task_date"),
            "task_time": t.get("task_time"),
            "delegated_to": t.get("delegated_to"),
            "objective_id": t.get("objective_id"),
            "key_result_id": t.get("key_result_id"),
            "initiative_id": t.get("initiative_id"),
            "kr_title": t.get("kr_title"),
            "kr_goal_title": t.get("kr_goal_title"),
            "kr_initiative_title": t.get("kr_initiative_title"),
            "kr_color": t.get("kr_color"),
        }

        # Each quadrant has a single bucket
        todo[quadrant]["tasks"].append(task)

    return todo

def parse_date(d):
    if isinstance(d, str):
        return datetime.fromisoformat(d).date()
    return d

def compute_quadrant_counts(todo):
    counts = {}

    for q, data in todo.items():
        tasks = data["tasks"]
        total = len(tasks)
        done = sum(1 for t in tasks if t.get("is_done"))

        counts[q] = {
            "total": total,
            "done": done
        }

    return counts



def compute_urgency(due_date, due_time):
    # 🚫 Missing date or time → no urgency
    if not due_date or not due_time:
        return None

    # Normalize due_time (Supabase may return HH:MM or HH:MM:SS)
    if isinstance(due_time, str):
        parsed = None
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                parsed = datetime.strptime(due_time, fmt).time()
                break
            except ValueError:
                continue
        due_time = parsed

    if not due_time:
        return None

    now = datetime.now()
    due_dt = datetime.combine(due_date, due_time)

    if due_dt < now:
        return "overdue"    # 🔴
    elif due_dt <= now + timedelta(hours=2):
        return "soon"       # 🟠
    return None


def normalize_task(t, project_name=None):
    return {
        "task_id": t["task_id"],
        "text": t.get("task_text") or t.get("text"),
        "status": t.get("status"),
        "done": t.get("status") == "done",
        "due_date": parse_date(t.get("due_date")),
        "due_time": t.get("due_time"),
        "delegated_to": t.get("delegated_to"),
        "elimination_reason": t.get("elimination_reason"),
        "project_id": t.get("project_id"),
        "project_name": project_name,
        "recurring": bool(t.get("recurrence")),
        "recurrence": t.get("recurrence"),
    }
def expire_old_eisenhower_tasks(user_id):
    today = user_today().isoformat()

    rows = get(
        "todo_matrix",
        params={
            "user_id": f"eq.{user_id}",
            "is_done": "eq.false",
            "is_deleted": "eq.false",
            "plan_date": f"lt.{today}",
            "select": "id,source_task_id",
            "limit": 500,
        }
    )

    if not rows:
        return

    # Batch update: mark all expired tasks as deleted in ONE call
    expired_ids = ",".join(str(r["id"]) for r in rows)
    update(
        "todo_matrix",
        params={"id": f"in.({expired_ids})"},
        json={"is_deleted": True}
    )

    # Batch restore: reopen linked project tasks in ONE call
    source_ids = [str(r["source_task_id"]) for r in rows if r.get("source_task_id")]
    if source_ids:
        update(
            "project_tasks",
            params={"task_id": f"in.({','.join(source_ids)})"},
            json={"status": "open"}
        )


@todo_bp.route("/set_recurrence", methods=["POST"])
@login_required
def set_recurrence():
    data = request.get_json()
    task_id = data["task_id"]
    recurrence = data.get("recurrence")

    # Safety: block unsaved tasks
    if task_id.startswith("new_"):
        return ("", 204)

    # Load the task instance
    found = get("todo_matrix", params={"id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"}) or []
    if not found:
        return jsonify({"error": "Task not found"}), 404
    task = found[0]

    # ----------------------------
    # FIX 3: prevent duplicate rules
    # ----------------------------
    existing = get(
        "recurring_tasks",
        params={
            "task_text": f"eq.{task['task_text']}",
            "quadrant": f"eq.{task['quadrant']}",
            "start_date": f"eq.{task['plan_date']}",
            "is_active": "eq.true",
            "user_id": f"eq.{session['user_id']}",
        },
    )

    if existing:
        # Rule already exists → do nothing (idempotent)
        return ("", 204)

    # ----------------------------
    # Create recurring rule
    # ----------------------------
    rule=post(
        "recurring_tasks",
        {
            # user_id is NOT NULL on recurring_tasks; without it the insert
            # failed and "repeat this task" never created a rule.
            "user_id": session["user_id"],
            "quadrant": task["quadrant"],
            "task_text": task["task_text"],
            "recurrence": recurrence,
            "start_date": task["plan_date"],
            "is_active": True,
            "category": task.get("category") or "General",
            "subcategory": task.get("subcategory") or "General",
            "day_of_month": (
            date.fromisoformat(task["plan_date"]).day
            if recurrence == "monthly"
            else None
            ),
            "days_of_week": (
                [date.fromisoformat(task["plan_date"]).weekday()]
                if recurrence == "weekly"
                else None
            ),
         },
    )
    update(
    "todo_matrix",
    params={"id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
    json={"recurring_id": rule[0]["id"]},
    )

    return ("", 204)

@todo_bp.route("/delete_recurring", methods=["POST"])
@login_required
def delete_recurring():
    data = request.get_json()
    task_id = data["task_id"]

    # Load the task instance for TODAY
    found = get(
        "todo_matrix",
        params={"id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"},
    ) or []
    if not found:
        return jsonify({"error": "Task not found"}), 404
    task = found[0]

    recurring_id = task.get("recurring_id")
    if not recurring_id:
        return ("", 204)

    # Stop recurrence from yesterday onwards
    end_date = date.fromisoformat(task["plan_date"]) - timedelta(days=1)

    update(
        "recurring_tasks",
        params={"id": f"eq.{recurring_id}", "user_id": f"eq.{session['user_id']}"},
        json={"end_date": str(end_date)},
    )

    # Also remove TODAY's instance
    update("todo_matrix", params={"id": f"eq.{task_id}", "user_id": f"eq.{session['user_id']}"}, json={"is_deleted": True})

    return ("", 204)



def group_tasks_smart(tasks):
    today = user_today()
    tomorrow = today + timedelta(days=1)            

    # Week ends on Sunday
    end_of_week = today + timedelta(days=(6 - today.weekday()))

    # End of month
    next_month = today.replace(day=28) + timedelta(days=4)
    end_of_month = next_month.replace(day=1) - timedelta(days=1)

    groups = OrderedDict({
        "Today": [],
        "Tomorrow": [],
        "This Week": [],
        "This Month": [],
        "Later": []
    })

    for t in tasks:
        d = t.get("start_date") or t.get("due_date")

        if not d:
            groups["Later"].append(t)
            continue

        if isinstance(d, str):
            d = date.fromisoformat(d)

        if d == today:
            groups["Today"].append(t)
        elif d == tomorrow:
            groups["Tomorrow"].append(t)
        elif tomorrow < d <= end_of_week:
            groups["This Week"].append(t)
        elif d <= end_of_month:
            groups["This Month"].append(t)
        else:
            groups["Later"].append(t)

    # Optional: sort inside each group
    for key in groups:
        groups[key].sort(key=_sort_key)

    return groups

@todo_bp.route("/tasks/occurrence/update", methods=["POST"])
@login_required
def update_task_occurrence_route():
    data = request.get_json()

    update_task_occurrence(
        user_id=session["user_id"],
        task_id=data["task_id"],
        task_date=data["date"],
        title=data.get("title"),
        status=data.get("status")
    )

    return "", 204

def _sort_key(task):
    """
    Normalizes start_date / due_date for safe sorting.
    Handles:
    - datetime.date
    - ISO date strings
    - None
    """
    d = task.get("start_date") or task.get("due_date")

    if not d:
        return date.max

    if isinstance(d, str):
        return date.fromisoformat(d)

    return d