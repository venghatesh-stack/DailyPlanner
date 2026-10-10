"""
services/agenda_service.py
──────────────────────────
Unified "agenda item" query layer. Normalizes calendar events, Eisenhower
matrix tasks, project tasks, and habits into a single `Item` shape that
views (morning dashboard, calendar, timeline, search) can consume without
each re-implementing the joins.

Design principles
─────────────────
1. **One shape for all sources.** Every fetcher returns `list[dict]` with
   the same keys. Views sort/filter without caring which table a row came
   from.
2. **One join per concern.** Project names, OKR titles, recurrence labels
   are resolved here once and stamped onto items. Views shouldn't issue
   secondary lookups.
3. **Soft-delete honored.** Callers pass `include_deleted=False` by
   default. No call site should have to remember the `is_deleted=eq.false`
   PostgREST filter.
4. **Idempotent failures.** Every supabase call is try/except with a
   logged warning and an empty list fallback — one failing table should
   never break the whole dashboard.

Item shape
──────────
    {
      "id":           str | int,          # raw row id, prefixed when
                                           # ambiguous across sources
                                           # ("pt-7", "ev-3", "hb-11")
      "type":         "meeting" | "task" | "habit",
      "source":       "matrix" | "project" | "event" | "habit",
      "title":        str,
      "time":         "HH:MM" | None,
      "end_time":     "HH:MM" | None,
      "date":         "YYYY-MM-DD" | None,
      "done":         bool,
      "status":       "open" | "in_progress" | "done" | ...,
      "priority":     "high" | "medium" | "low" | None,
      "context":      str | None,          # project name / quadrant
      "link":         str | None,          # deep link to editing surface
      "project_id":   str | None,
      "objective_id": int | None,
      "key_result_id": int | None,
      "initiative_id": int | None,
      "recurrence":   "daily" | "weekly" | "monthly" | None,
      "delegated_to": str | None,
      # habit-only (present when type == "habit"):
      "habit_goal":    float | None,
      "habit_value":   float | None,
      "habit_unit":    str | None,
      "habit_type":    "boolean" | "number" | None,
      "progress_pct":  int | None,
      # overdue-only (present on overdue items):
      "days_overdue":  int,
    }
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Iterable, Optional

from supabase_client import get

logger = logging.getLogger(__name__)

QUADRANT_LABELS = {
    "do": "Do Now",
    "schedule": "Schedule",
    "delegate": "Delegate",
    "eliminate": "Eliminate",
}

_SORT_PRIORITY_WEIGHT = {"high": 1, "medium": 2, "low": 3}


# ═══════════════════════════════════════════════════════════
# Shared lookup helpers
# ═══════════════════════════════════════════════════════════

def _to_iso(plan_date) -> str:
    """Accepts a date or an ISO string; returns the ISO string form."""
    return plan_date.isoformat() if hasattr(plan_date, "isoformat") else str(plan_date)


def _safe_get(table: str, *, params: dict, action: str) -> list:
    """Wrapped supabase GET that never raises: logs + returns []."""
    try:
        return get(table, params=params) or []
    except Exception as e:
        logger.warning("agenda_service: %s failed: %s", action, e)
        return []


def _project_name_map(user_id: str, project_ids: Iterable) -> dict:
    """Map project_id → name for the given ids. Empty dict if no ids."""
    ids = {p for p in project_ids if p}
    if not ids:
        return {}
    rows = _safe_get(
        "projects",
        params={
            "user_id": f"eq.{user_id}",
            "project_id": f"in.({','.join(str(p) for p in ids)})",
            "select": "project_id,name",
        },
        action="project name lookup",
    )
    return {r["project_id"]: r.get("name") for r in rows}


def _kr_label_map(user_id: str, kr_ids: Iterable, initiative_ids: Iterable) -> dict:
    """Maps each id (key_result_id OR initiative_id) → a short label
    suitable for a chip on a task row. Initiatives are resolved to
    their parent KR title (one step up the OKR ladder), so a task
    linked to an initiative still surfaces the higher-level outcome.

    Returns: { id: "KR title", ... }  — same dict for both id types
    so the caller can do a single .get(...) without branching.
    Scoped to `user_id`: the ids come from task rows, and a task can be
    pointed at any id, so an unscoped lookup would print another user's
    key-result title on this user's board.
    """
    kr_ids_set = {x for x in kr_ids if x}
    init_ids_set = {x for x in initiative_ids if x}

    out: dict = {}

    if kr_ids_set:
        rows = _safe_get(
            "key_results",
            params={
                "user_id": f"eq.{user_id}",
                "id": f"in.({','.join(str(i) for i in kr_ids_set)})",
                "is_deleted": "eq.false",
                "select": "id,title",
            },
            action="key_result label lookup",
        )
        for r in rows:
            out[r["id"]] = (r.get("title") or "").strip() or None

    if init_ids_set:
        # Initiatives → fetch their key_result_id, then look up the KR title.
        init_rows = _safe_get(
            "initiatives",
            params={
                "user_id": f"eq.{user_id}",
                "id": f"in.({','.join(str(i) for i in init_ids_set)})",
                "select": "id,key_result_id",
            },
            action="initiative→KR lookup",
        )
        kr_ids_via_init = {r.get("key_result_id") for r in init_rows if r.get("key_result_id")}
        # Avoid refetching KRs we already have
        kr_ids_via_init -= set(out.keys())
        kr_titles: dict = {}
        if kr_ids_via_init:
            kr_rows = _safe_get(
                "key_results",
                params={
                    "user_id": f"eq.{user_id}",
                    "id": f"in.({','.join(str(i) for i in kr_ids_via_init)})",
                    "is_deleted": "eq.false",
                    "select": "id,title",
                },
                action="initiative→KR title lookup",
            )
            kr_titles = {r["id"]: (r.get("title") or "").strip() or None for r in kr_rows}
            out.update(kr_titles)

        # Map initiative_id → KR title for direct lookup by initiative_id too
        for r in init_rows:
            kr_id = r.get("key_result_id")
            if kr_id:
                out[r["id"]] = kr_titles.get(kr_id) or out.get(kr_id)

    return out


def _recurrence_map(recurring_ids: Iterable) -> dict:
    """Map recurring_id → recurrence type. Used by matrix tasks where the
    rule is stored separately in recurring_tasks."""
    ids = {r for r in recurring_ids if r}
    if not ids:
        return {}
    rows = _safe_get(
        "recurring_tasks",
        params={
            "id": f"in.({','.join(str(i) for i in ids)})",
            "select": "id,recurrence",
        },
        action="recurrence lookup",
    )
    return {r["id"]: r.get("recurrence") for r in rows}


def _days_overdue(due_date_iso, ref_date) -> int:
    """How many whole days in the past is due_date_iso relative to ref_date?
    Returns 0 when unparseable or not overdue."""
    if not due_date_iso:
        return 0
    try:
        dd = date.fromisoformat(str(due_date_iso))
        return max(0, (ref_date - dd).days)
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════
# Fetchers — one per source. Each returns list[dict] in the Item shape.
# ═══════════════════════════════════════════════════════════

def fetch_events(user_id: str, plan_date) -> list[dict]:
    """Calendar meetings for a single day from `daily_events`."""
    date_iso = _to_iso(plan_date)
    rows = _safe_get(
        "daily_events",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{date_iso}",
            "is_deleted": "eq.false",
            "select": "id,title,description,start_time,end_time,status,priority,quadrant",
            "order": "start_time.asc",
        },
        action="events fetch",
    )
    out = []
    for r in rows:
        title = (r.get("title") or "").strip()
        if not title:
            continue
        start = (r.get("start_time") or "")[:5] or None
        end = (r.get("end_time") or "")[:5] or None
        out.append({
            "id": f"ev-{r.get('id')}",
            "type": "meeting",
            "source": "event",
            "title": title,
            "time": start,
            "end_time": end,
            "date": date_iso,
            "done": r.get("status") == "done",
            "status": r.get("status") or "open",
            "priority": r.get("priority"),
            "context": (r.get("description") or "").strip() or None,
            "link": "/planner",
            "project_id": None,
            "recurrence": None,
            "delegated_to": None,
        })
    return out


def fetch_matrix_items(
    user_id: str,
    plan_date=None,
    *,
    include_done: bool = True,
    include_deleted: bool = False,
    project_name_map: Optional[dict] = None,
) -> list[dict]:
    """Eisenhower matrix rows for a date (or across all dates if plan_date
    is None, used for overdue scans)."""
    params = {
        "user_id": f"eq.{user_id}",
        "select": "id,task_text,is_done,status,priority,quadrant,task_time,"
                  "task_date,plan_date,category,project_id,recurring_id",
    }
    if not include_deleted:
        params["is_deleted"] = "eq.false"
    if plan_date is not None:
        params["plan_date"] = f"eq.{_to_iso(plan_date)}"

    rows = _safe_get("todo_matrix", params=params, action="matrix fetch")
    rows = [r for r in rows if (r.get("category") or "") != "Travel-archived"]
    if not include_done:
        rows = [r for r in rows if not r.get("is_done")]

    # Lookups we need in bulk
    if project_name_map is None:
        project_name_map = _project_name_map(
            user_id,
            (r.get("project_id") for r in rows),
        )
    rec_map = _recurrence_map(r.get("recurring_id") for r in rows)

    out = []
    for r in rows:
        title = (r.get("task_text") or "").strip()
        if not title:
            continue
        tt = (r.get("task_time") or "")[:5] or None
        ctx = project_name_map.get(r.get("project_id")) or QUADRANT_LABELS.get(r.get("quadrant"))
        out.append({
            "id": r.get("id"),
            "type": "task",
            "source": "matrix",
            "title": title,
            "time": tt,
            "end_time": None,
            "date": r.get("task_date") or r.get("plan_date"),
            "done": bool(r.get("is_done")),
            "status": r.get("status") or "open",
            "priority": r.get("priority"),
            "context": ctx,
            "link": "/todo",
            "project_id": r.get("project_id"),
            "recurrence": rec_map.get(r.get("recurring_id")),
            "delegated_to": None,
            "_quadrant": r.get("quadrant"),  # raw for views that care
        })
    return out


def fetch_project_items(
    user_id: str,
    *,
    due_on: Optional[str] = None,
    overdue_before: Optional[str] = None,
    project_id: Optional[str] = None,
    include_done: bool = True,
    project_name_map: Optional[dict] = None,
) -> list[dict]:
    """Project tasks, optionally filtered to due-on-date or overdue-before.

    - `due_on`: only rows with due_date == this ISO date
    - `overdue_before`: only rows with due_date < this ISO date AND not done
    - `project_id`: scope to a single project
    """
    params = {
        "user_id": f"eq.{user_id}",
        "is_eliminated": "eq.false",
        # Pull revised_due_date too so callers can fall back to it when
        # the parking migration hasn't been applied (column absent →
        # PostgREST silently omits the field, callers see None).
        "select": "task_id,task_text,status,priority,due_time,due_date,"
                  "revised_due_date,"
                  "project_id,initiative_id,key_result_id,delegated_to,is_recurring,"
                  "recurrence_type",
        # Order by revised first so the most-current intent leads.
        "order": "revised_due_date.asc",
        "limit": 400,
    }
    if project_id:
        params["project_id"] = f"eq.{project_id}"
    # Date filters now drive off revised_due_date so a user-pushed task
    # appears in "today" / "overdue" based on their current intent, not
    # the immutable original deadline. Pre-migration the column doesn't
    # exist, so supabase_client.get returns 400; we guard against that
    # by widening to the union of revised_due_date and due_date via a
    # PostgREST `or` clause when both possibilities are in play.
    if due_on:
        # Effective date == due_on. Match either revised (if set) or
        # due_date when revised is null.
        params["or"] = (
            f"(revised_due_date.eq.{due_on},"
            f"and(revised_due_date.is.null,due_date.eq.{due_on}))"
        )
    if overdue_before:
        # Effective date < overdue_before. Same union shape.
        params["or"] = (
            f"(revised_due_date.lt.{overdue_before},"
            f"and(revised_due_date.is.null,due_date.lt.{overdue_before}))"
        )
        params["status"] = "neq.done"
    if not include_done:
        params["status"] = "neq.done"

    rows = _safe_get("project_tasks", params=params, action="project tasks fetch")

    if project_name_map is None:
        project_name_map = _project_name_map(
            user_id,
            (r.get("project_id") for r in rows),
        )
    # OKR chip labels: resolve KR titles for tasks linked to a key_result
    # or (one ladder rung lower) an initiative.
    kr_label_map = _kr_label_map(
        user_id,
        (r.get("key_result_id") for r in rows),
        (r.get("initiative_id") for r in rows),
    )

    out = []
    for r in rows:
        title = (r.get("task_text") or "").strip()
        if not title:
            continue
        out.append({
            "id": f"pt-{r.get('task_id')}",
            "type": "task",
            "source": "project",
            "title": title,
            "kr_label": kr_label_map.get(r.get("key_result_id"))
                        or kr_label_map.get(r.get("initiative_id")),
            "time": (r.get("due_time") or "")[:5] or None,
            "end_time": None,
            # Show the effective date — what the user actually intends —
            # not the immutable original deadline. _days_overdue and the
            # parked-vs-overdue split downstream use this same field.
            "date": r.get("revised_due_date") or r.get("due_date"),
            "due_date": r.get("due_date"),  # original kept around for context
            "done": r.get("status") == "done",
            "status": r.get("status") or "open",
            "priority": r.get("priority"),
            "context": project_name_map.get(r.get("project_id")),
            "link": f"/projects/{r.get('project_id')}/tasks" if r.get("project_id") else None,
            "project_id": r.get("project_id"),
            "initiative_id": r.get("initiative_id"),
            "key_result_id": r.get("key_result_id"),
            "recurrence": r.get("recurrence_type") if r.get("is_recurring") else None,
            "delegated_to": r.get("delegated_to"),
        })
    return out


def fetch_habits(user_id: str, plan_date) -> list[dict]:
    """Habits with today's progress. Each habit becomes one item. `done`
    is computed from goal + today's logged value (or boolean checked)."""
    date_iso = _to_iso(plan_date)
    habit_rows = _safe_get(
        "habit_master",
        params={
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
            "select": "id,name,unit,goal,habit_type,position",
            "order": "position.asc",
        },
        action="habit master fetch",
    )
    if not habit_rows:
        return []

    entry_rows = _safe_get(
        "habit_entries",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{date_iso}",
            "select": "habit_id,value",
        },
        action="habit entries fetch",
    )
    value_map = {r["habit_id"]: float(r.get("value") or 0) for r in entry_rows}

    out = []
    for h in habit_rows:
        goal = float(h.get("goal") or 0)
        value = value_map.get(h["id"], 0.0)
        is_boolean = (h.get("habit_type") == "boolean")
        done = (value >= 1) if is_boolean else (goal > 0 and value >= goal)
        pct = 100 if done else (int(round(value / goal * 100)) if goal > 0 else 0)
        pct = max(0, min(100, pct))
        # Habit items carry BOTH the normalized Item-dict keys (title/
        # habit_value/etc.) AND the short keys (name/value/goal/unit)
        # that the summary.html template reads directly. Keeping both
        # avoids touching the template and preserves the legacy contract
        # from before the agenda-service refactor.
        name = h.get("name") or ""
        unit = h.get("unit")
        out.append({
            "id": f"hb-{h['id']}",
            "type": "habit",
            "source": "habit",
            "title": name,
            "name": name,          # template expects this
            "time": None,
            "end_time": None,
            "date": date_iso,
            "done": done,
            "status": "done" if done else "open",
            "priority": None,
            "context": None,
            "link": "/health",
            # Normalized (new) field names
            "habit_goal": goal,
            "habit_value": value,
            "habit_unit": unit,
            "habit_type": h.get("habit_type"),
            "progress_pct": pct,
            # Template-compatibility short names (pre-agenda-service)
            "goal": goal,
            "value": value,
            "unit": unit,
        })
    return out


# ═══════════════════════════════════════════════════════════
# Composite views
# ═══════════════════════════════════════════════════════════

def fetch_done_today(user_id: str, plan_date) -> list[dict]:
    """All tasks the user marked done today — across both matrix and
    project sources. Used by the "Today's Recap" section at the bottom
    of the daily summary so completed work has a celebratory home and
    can still be unchecked if the user marked something done by mistake.

    "Today" is bounded by the plan_date the dashboard is being rendered
    for, not necessarily wall-clock today, so navigating to a past day's
    recap shows what was completed on that date.
    """
    iso = _to_iso(plan_date)
    day_start = f"{iso}T00:00:00"
    day_end = f"{iso}T23:59:59.999"

    # Matrix tasks: is_done=true, updated within the day
    matrix_rows = _safe_get(
        "todo_matrix",
        params={
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
            "is_done": "eq.true",
            "updated_at": f"gte.{day_start}",
            "and": f"(updated_at.lte.{day_end})",
            "select": "id,task_text,priority,task_date,plan_date,quadrant,"
                      "category,project_id,updated_at",
            "order": "updated_at.desc",
            "limit": 200,
        },
        action="done-today matrix fetch",
    )

    # Project tasks: status='done', updated within the day
    project_rows = _safe_get(
        "project_tasks",
        params={
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
            "is_eliminated": "eq.false",
            "status": "eq.done",
            "updated_at": f"gte.{day_start}",
            "and": f"(updated_at.lte.{day_end})",
            "select": "task_id,task_text,priority,due_date,project_id,"
                      "initiative_id,key_result_id,delegated_to,updated_at",
            "order": "updated_at.desc",
            "limit": 200,
        },
        action="done-today project fetch",
    )

    project_name_map = _project_name_map(
        user_id,
        [r.get("project_id") for r in matrix_rows]
        + [r.get("project_id") for r in project_rows],
    )
    kr_label_map = _kr_label_map(
        user_id,
        (r.get("key_result_id") for r in project_rows),
        (r.get("initiative_id") for r in project_rows),
    )

    items = []
    for r in matrix_rows:
        title = (r.get("task_text") or "").strip()
        if not title:
            continue
        items.append({
            "id": r.get("id"),
            "type": "task",
            "source": "matrix",
            "title": title,
            "done": True,
            "status": "done",
            "priority": r.get("priority"),
            "date": r.get("task_date") or r.get("plan_date"),
            "context": project_name_map.get(r.get("project_id"))
                       or QUADRANT_LABELS.get(r.get("quadrant")),
            "link": "/todo",
            "project_id": r.get("project_id"),
            "category": r.get("category"),
            "completed_at": r.get("updated_at"),
        })
    for r in project_rows:
        title = (r.get("task_text") or "").strip()
        if not title:
            continue
        items.append({
            "id": f"pt-{r.get('task_id')}",
            "type": "task",
            "source": "project",
            "title": title,
            "done": True,
            "status": "done",
            "priority": r.get("priority"),
            "date": r.get("due_date"),
            "context": project_name_map.get(r.get("project_id")),
            "kr_label": kr_label_map.get(r.get("key_result_id"))
                        or kr_label_map.get(r.get("initiative_id")),
            "link": "/projects",
            "project_id": r.get("project_id"),
            "category": None,
            "completed_at": r.get("updated_at"),
        })

    items.sort(key=lambda x: x.get("completed_at") or "", reverse=True)
    return items


def fetch_overdue(user_id: str, plan_date) -> list[dict]:
    """All overdue items (both matrix + project) sorted most-overdue first.
    Stamps `days_overdue` onto each."""
    iso = _to_iso(plan_date)
    ref = plan_date if isinstance(plan_date, date) else date.fromisoformat(iso)

    # Project tasks with due_date in the past and still not done
    project_items = fetch_project_items(user_id, overdue_before=iso)

    # Matrix tasks whose effective date elapsed and still not done.
    # Match the project_tasks pattern: prefer revised_due_date, fall
    # back to task_date if no revision yet (or pre-migration rows).
    matrix_rows = _safe_get(
        "todo_matrix",
        params={
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
            "is_done": "eq.false",
            "or": (
                f"(revised_due_date.lt.{iso},"
                f"and(revised_due_date.is.null,task_date.lt.{iso}))"
            ),
            "select": "id,task_text,priority,task_date,revised_due_date,"
                      "quadrant,category,project_id",
            "order": "revised_due_date.asc",
            "limit": 200,
        },
        action="overdue matrix fetch",
    )
    project_name_map = _project_name_map(
        user_id,
        [r.get("project_id") for r in matrix_rows] + [p.get("project_id") for p in project_items],
    )
    matrix_items = []
    for r in matrix_rows:
        if (r.get("category") or "") == "Travel-archived":
            continue
        title = (r.get("task_text") or "").strip()
        if not title:
            continue
        matrix_items.append({
            "id": r.get("id"),
            "type": "task",
            "source": "matrix",
            "title": title,
            "time": None,
            "end_time": None,
            # Effective date drives the days-overdue computation. Falls
            # back to task_date when revised_due_date hasn't been set
            # (legacy rows or pre-migration).
            "date": r.get("revised_due_date") or r.get("task_date"),
            "due_date": r.get("task_date"),
            "done": False,
            "status": "open",
            "priority": r.get("priority"),
            "context": project_name_map.get(r.get("project_id")) or QUADRANT_LABELS.get(r.get("quadrant")),
            "link": "/todo",
            "project_id": r.get("project_id"),
            "category": r.get("category"),
        })

    # Fill in project context names we already fetched.
    for it in project_items:
        if not it.get("context") and it.get("project_id"):
            it["context"] = project_name_map.get(it["project_id"])

    combined = matrix_items + project_items
    for it in combined:
        it["days_overdue"] = _days_overdue(it.get("date"), ref)

    combined.sort(key=lambda x: (-(x.get("days_overdue") or 0), x.get("title") or ""))
    return combined


def _sort_timed_then_untimed(items: list[dict]) -> None:
    """Sort in place: items with time first (ascending), then untimed
    (alphabetic tie-break by title), priority ties to highest first."""
    items.sort(key=lambda it: (
        it.get("time") is None,
        it.get("time") or "",
        _SORT_PRIORITY_WEIGHT.get(it.get("priority") or "", 4),
        (it.get("title") or "").lower(),
    ))


def fetch_bucket_items(user_id: str, plan_date) -> tuple[list[dict], list[dict]]:
    """Tasks Bucket items relevant to the dashboard for `plan_date`.

    Returns (active, done_today) where each list uses the standard
    Item shape, so the dashboard merges them alongside meetings,
    matrix tasks, and project tasks without special-casing them in
    the template.

    Active = not done, not deleted, not in the 'future' bucket
    (future is explicitly deferred). Items in 'now' / 'Nm' / 'Nh'
    buckets all show up. Items with a due_at get its HH:MM as the
    `time` field so they sort chronologically; bucket='now' shows
    no time.

    Done-today = is_done=true with done_at on `plan_date`. Used
    only when plan_date is today — past dates skip the done set.
    """
    today_iso = _to_iso(plan_date)
    rows = _safe_get(
        "quick_bucket",
        params={
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
            "select": "id,text,time_bucket,due_at,is_done,done_at,created_at",
            "limit": "500",
        },
        action="quick_bucket fetch",
    )

    active: list[dict] = []
    done: list[dict] = []
    for r in rows:
        text = (r.get("text") or "").strip()
        if not text:
            continue
        is_done = bool(r.get("is_done"))
        bucket = (r.get("time_bucket") or "now")

        if is_done:
            done_at = r.get("done_at") or ""
            if done_at[:10] != today_iso:
                continue  # done on a different day
        else:
            if bucket == "future":
                continue  # explicitly deferred, not for today's plan

        # Derive a HH:MM time from due_at when present, in the user's
        # local zone. Falls back to None for now/future buckets.
        time_str = None
        due_at = r.get("due_at")
        if due_at and not is_done:
            try:
                s = due_at.replace("Z", "+00:00")
                dt = datetime.fromisoformat(s)
                time_str = dt.astimezone().strftime("%H:%M")
            except Exception:
                pass

        # Tag the bucket category in the context so the agenda row
        # makes its origin obvious ("Tasks Bucket · 2H") without
        # adding a new badge column.
        ctx_parts = ["Tasks Bucket"]
        if bucket and bucket not in ("now", "future"):
            ctx_parts.append(bucket.upper())
        ctx = " · ".join(ctx_parts)

        item = {
            "id": f"bucket-{r.get('id')}",
            "type": "task",
            "source": "bucket",
            "title": text,
            "time": time_str,
            "end_time": None,
            "date": today_iso,
            "done": is_done,
            "status": "done" if is_done else "open",
            "priority": None,
            "context": ctx,
            "link": "/quick-bucket",
            "project_id": None,
            "recurrence": None,
            "delegated_to": None,
        }
        (done if is_done else active).append(item)
    return active, done


def fetch_upcoming(user_id: str, plan_date) -> dict:
    """Open matrix tasks dated AFTER plan_date, grouped by horizon.

    Returns a dict with three buckets so the morning dashboard can
    render Tomorrow / This week / Future sections under the today
    list — answers the user's question "what's coming up" without
    them having to navigate to the matrix or calendar.
    """
    from datetime import timedelta as _td
    today = plan_date if hasattr(plan_date, "year") else date.fromisoformat(_to_iso(plan_date))
    tomorrow_iso = _to_iso(today + _td(days=1))
    week_end_iso = _to_iso(today + _td(days=7))

    rows = _safe_get(
        "todo_matrix",
        params={
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
            "is_done": "eq.false",
            "plan_date": f"gt.{_to_iso(today)}",
            "select": "id,task_text,plan_date,project_id,priority,quadrant,task_time,task_date",
            "order": "plan_date.asc",
            "limit": "200",
        },
        action="upcoming matrix fetch",
    )
    project_name_map = _project_name_map(
        user_id, (r.get("project_id") for r in rows),
    )

    def _normalise(r):
        title = (r.get("task_text") or "").strip()
        if not title:
            return None
        return {
            "id": "matrix-" + str(r.get("id")),
            "type": "task",
            "source": "matrix",
            "title": title,
            "time": ((r.get("task_time") or "")[:5]) or None,
            "end_time": None,
            "date": r.get("plan_date"),
            "done": False,
            "status": "open",
            "priority": r.get("priority"),
            "context": project_name_map.get(r.get("project_id"))
                       or QUADRANT_LABELS.get(r.get("quadrant")),
            "link": "/todo",
            "project_id": r.get("project_id"),
        }

    tomorrow: list[dict] = []
    this_week: list[dict] = []
    future:    list[dict] = []
    for r in rows:
        item = _normalise(r)
        if not item:
            continue
        d = item["date"] or ""
        if d == tomorrow_iso:
            tomorrow.append(item)
        elif d <= week_end_iso:
            this_week.append(item)
        else:
            future.append(item)
    return {"tomorrow": tomorrow, "this_week": this_week, "future": future}


def build_dashboard(user_id: str, plan_date) -> dict:
    """Morning dashboard composition.

    Returns the same shape `get_morning_dashboard` did, so callers don't
    need to change. Under the hood it fans out to the fetchers above.

    ── WHY THIS FANS OUT ACROSS THREADS ──────────────────────────────
    Reported 2026-08-30: "clicking todays plan is very slow". Measured:
    the page made SIXTEEN Supabase round trips one after another, and
    that was with every table empty — a populated account adds the
    project-name, key-result and recurrence lookups on top. Every one of
    those is a full internet round trip from the app host, so the page
    cost the SUM of them: latency times twenty, before Jinja saw a byte.

    None of these ten depend on each other — they are ten independent
    reads that get stapled together at the end — so the sum was never
    necessary; the page only ever needed the slowest one. The work is
    pure network waiting, which releases the GIL, so threads give close
    to the full speed-up.

    SAFE TO THREAD because nothing in this module touches Flask's
    request context: every fetcher takes user_id and plan_date as plain
    arguments and supabase_client.get() is a bare `requests` call. If a
    fetcher ever needs `session`, read it in the caller and pass it in —
    a thread has no request context and would fail at import of the
    first `session[...]`.
    """
    def _run(label, fn, fallback):
        # One failing table must not take the dashboard with it — the
        # same bargain _safe_get makes, extended to the fetchers that do
        # their own compositing.
        try:
            return fn()
        except Exception as e:
            logger.warning("agenda_service: %s failed: %s", label, e)
            return fallback

    jobs = {
        "events":       (lambda: fetch_events(user_id, plan_date), []),
        "matrix":       (lambda: fetch_matrix_items(user_id, plan_date), []),
        "project":      (lambda: fetch_project_items(user_id, due_on=_to_iso(plan_date)), []),
        "habits":       (lambda: fetch_habits(user_id, plan_date), []),
        "overdue":      (lambda: fetch_overdue(user_id, plan_date), []),
        "done_today":   (lambda: fetch_done_today(user_id, plan_date), []),
        "intent":       (lambda: _fetch_daily_intent(user_id, plan_date), {}),
        "inbox_health": (lambda: fetch_inbox_health(user_id, plan_date), None),
        "bucket":       (lambda: fetch_bucket_items(user_id, plan_date), ([], [])),
        "upcoming":     (lambda: fetch_upcoming(user_id, plan_date),
                         {"tomorrow": [], "this_week": [], "future": []}),
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {k: pool.submit(_run, k, fn, fallback)
                   for k, (fn, fallback) in jobs.items()}
        out = {k: f.result() for k, f in futures.items()}

    events = out["events"]
    matrix_items = out["matrix"]
    project_due_today = out["project"]
    habits = out["habits"]
    overdue_all = out["overdue"]
    done_today = out["done_today"]
    intent = out["intent"]
    inbox_health = out["inbox_health"]
    bucket_active, bucket_done = out["bucket"]
    upcoming = out["upcoming"]

    # Single timeline: meetings + matrix tasks + project tasks + Tasks
    # Bucket items merged chronologically. The template's filter chips
    # use each row's data-type / data-source to show subsets without
    # re-querying. Done-today bucket rows feed the global done-today
    # list so the morning tally still reflects bucket closures.
    today_items = events + matrix_items + project_due_today + bucket_active
    done_today = done_today + bucket_done
    _sort_timed_then_untimed(today_items)

    # Split overdue into "active overdue" (1-2 days old) and "parked"
    # (3+ days old). Anything older than the user's reasonable triage
    # window goes into a separate list so the morning view stays
    # focused. The parked section gets a one-tap revise control.
    OVERDUE_WINDOW_DAYS = 2
    overdue = [it for it in overdue_all
               if (it.get("days_overdue") or 0) <= OVERDUE_WINDOW_DAYS]
    parked  = [it for it in overdue_all
               if (it.get("days_overdue") or 0) >  OVERDUE_WINDOW_DAYS]

    # Counts for the hero line
    meeting_count = sum(1 for it in today_items if it["type"] == "meeting")
    task_count = sum(1 for it in today_items if it["type"] == "task")
    habits_done = sum(1 for h in habits if h["done"])

    return {
        "today_items": today_items,
        "overdue": overdue,
        "parked":  parked,
        "done_today": done_today,
        "habits": habits,
        "intent": intent,
        "inbox_health": inbox_health,
        "upcoming": upcoming,
        "counts": {
            "meetings": meeting_count,
            "tasks": task_count,
            "bucket": len(bucket_active),
            "tomorrow":  len(upcoming["tomorrow"]),
            "this_week": len(upcoming["this_week"]),
            "future":    len(upcoming["future"]),
            "habits": len(habits),
            "habits_done": habits_done,
            "overdue": len(overdue),
            "parked":  len(parked),
            "done_today": len(done_today),
        },
    }


def fetch_inbox_health(user_id: str, plan_date) -> dict | None:
    """Compute a small health snapshot of the user's default project.

    Returns None when:
      - no default project exists yet (user hasn't run a checklist
        convert and never manually created an Inbox), OR
      - the inbox is healthy enough that surfacing a card would be
        noise (≤ 5 open and 0 stale).

    Otherwise returns:
      {
        "project_id": str,
        "project_name": str,
        "open_count": int,
        "no_due_count": int,             # subset of open with no due_date
        "stale_count": int,              # open + no due_date + > 14d old
        "stale_sample": [<title>, ...],  # up to 5 titles for the card
        "level": "ok" | "watch" | "crowded",
        "link": "/projects/<id>/tasks",
      }
    """
    from datetime import timedelta

    # Resolve default project, falling back to a project literally
    # named "Inbox" in case the migration hasn't been run yet (or the
    # user created one manually before is_default existed).
    proj = _safe_get(
        "projects",
        params={
            "user_id": f"eq.{user_id}",
            "is_default": "eq.true",
            "is_archived": "eq.false",
            "select": "project_id,name",
            "limit": "1",
        },
        action="default project fetch",
    )
    if not proj:
        proj = _safe_get(
            "projects",
            params={
                "user_id": f"eq.{user_id}",
                "name": "ilike.Inbox",
                "is_archived": "eq.false",
                "select": "project_id,name",
                "limit": "1",
            },
            action="inbox project fetch",
        )
    if not proj:
        return None

    project_id = proj[0]["project_id"]
    project_name = proj[0].get("name") or "Inbox"

    # Open tasks in that project. We exclude `done` and the soft-delete
    # flags. Both legacy `is_deleted` and current `is_eliminated` are
    # filtered to match how the project pages list tasks.
    tasks = _safe_get(
        "project_tasks",
        params={
            "project_id": f"eq.{project_id}",
            "user_id": f"eq.{user_id}",
            "is_eliminated": "eq.false",
            "is_deleted": "eq.false",
            "status": "neq.done",
            "select": "task_id,task_text,status,due_date,created_at,priority",
            "limit": "1000",
        },
        action="inbox tasks fetch",
    )

    open_count = len(tasks)
    no_due_count = sum(1 for t in tasks if not t.get("due_date"))

    stale_threshold = (plan_date - timedelta(days=14)).isoformat()
    stale = []
    for t in tasks:
        if t.get("due_date"):
            continue
        created = (t.get("created_at") or "")[:10]
        if created and created < stale_threshold:
            stale.append(t)
    # Most-stale first (oldest created_at).
    stale.sort(key=lambda t: t.get("created_at") or "")
    stale_sample = [(t.get("task_text") or "").strip() or "(untitled)"
                    for t in stale[:5]]

    # Don't surface the card unless there's something interesting.
    # Threshold: ≤5 open and 0 stale → quiet.
    if open_count <= 5 and not stale:
        return None

    if open_count > 15 or len(stale) > 3:
        level = "crowded"
    elif open_count > 8 or stale:
        level = "watch"
    else:
        level = "ok"

    return {
        "project_id": project_id,
        "project_name": project_name,
        "open_count": open_count,
        "no_due_count": no_due_count,
        "stale_count": len(stale),
        "stale_sample": stale_sample,
        "level": level,
        "link": f"/projects/{project_id}/tasks",
    }


def _fetch_daily_intent(user_id: str, plan_date) -> dict:
    """Returns {"text": str | None, "done": bool} for the day's intent.
    Degrades to {"text": None, "done": False} if the daily_intent
    columns haven't been migrated yet (column-not-in-schema-cache),
    so the UI just doesn't render the focus card on un-migrated DBs."""
    iso = _to_iso(plan_date)
    rows = _safe_get(
        "daily_meta",
        params={
            "user_id": f"eq.{user_id}",
            "plan_date": f"eq.{iso}",
            "select": "daily_intent,daily_intent_done",
        },
        action="daily intent fetch",
    )
    if not rows:
        return {"text": None, "done": False}
    r = rows[0]
    return {
        "text": (r.get("daily_intent") or "").strip() or None,
        "done": bool(r.get("daily_intent_done")),
    }
