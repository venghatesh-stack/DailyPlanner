"""The capture inbox: one place to dump every task, and the router out.

WHAT THIS IS FOR
----------------
"it should be one source stop for capturing all the laundry list of my
tasks and then i should be able to send it to various things like quick
bucket, projects, inbox, references etc."

So Backlog is where a thought lands when there is no time to decide where
it belongs, and the Quick Bucket is the shorter list of things actually
prioritised to be done. Capture here, route out from here.

WHY THE PROJECT TASKS ARE STILL NOT RELOCATED
---------------------------------------------
This page used to be read-only, for a reason that still holds for one of
the two lists: `project_tasks` carries 40 columns to `quick_bucket`'s 21,
and physically moving a row drops its project, key result, initiative,
epic, sprint, priority and ordering. Project progress is computed from
live task counts, so relocating tasks would silently change the completion
figure on every project they came from.

The routes below therefore write in two different ways on purpose:

  * A CAPTURED item is a quick_bucket row, and routing it really does move
    it — it is created here and has nothing to lose.
  * A PROJECT task is never moved. Promoting one writes a bucket row that
    POINTS at it (quick_bucket.source_task_id) and dates the task for
    today. Both stay in place, the project's figures stay honest, and
    ticking the bucket item closes the task with it. A plain copy was the
    obvious alternative and it lies: two rows for one piece of work makes
    the planner report more outstanding than exists.

Inbox and References are NOT written from here. Both are URL pipelines with
metadata fetching, AI description and auto-categorising behind them; the
browser posts to their own endpoints and then calls /api/backlog/drop, so
there is one implementation of each rather than a poorer second one.

WHAT COUNTS AS BACKLOG
----------------------
Two different shapes of "no date on it yet":

  * Quick Bucket items in the FUTURE bucket — deliberately deferred, no
    deadline, no alarm.
  * Project tasks with no plan_date and no start_time — real work inside a
    project that has never been put on a day.

THE FUTURE RULE IS COPIED FROM THE PAGE, NOT REINVENTED. quick_bucket.js
groups an "at" item into Future when its pinned time falls beyond today, so
this does the same. A backlog that disagreed with the bucket page about what
is in Future would be worse than not having one — that lesson cost this
codebase three separate copies of the checklist schedule rule, each with a
different answer.
"""

import logging
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, render_template, request, session

from services.login_service import login_required
from supabase_client import get, post, update
from utils.user_tz import user_now, user_today

logger = logging.getLogger("daily_plan")
backlog_bp = Blueprint("backlog", __name__)

#: Statuses that mean the task is no longer outstanding. Matches
#: routes/todo.py's vocabulary, plus the two the project trash uses.
_CLOSED = {"done", "skipped", "deleted", "not_required"}


_REPEAT_WORDS = {
    "once": "once", "daily": "every day", "weekly": "every week",
    "monthly": "every month", "yearly": "every year", "custom": "on set days",
}


def _spoken_at(hhmm):
    """"19:45" → "7:45 PM". The panel reads times back this way too."""
    try:
        h, m = (int(x) for x in str(hhmm)[:5].split(":", 1))
    except (ValueError, TypeError):
        return str(hhmm)
    ampm = "AM" if h < 12 else "PM"
    h12 = 12 if h % 12 == 0 else h % 12
    return "%d:%02d %s" % (h12, m, ampm)


def _announced(user_id):
    """{say_text: "7:45 PM every day"} for this user's live announcements.

    KEYED BY TEXT, which is the same rule progress, notes and effort all
    follow here — an announcement carries no reference to the row it came
    from, and adding one would mean a column and a migration to show a
    chip. Text is what the user typed in both places, and a rename simply
    drops the chip rather than corrupting anything.
    """
    try:
        rows = get("announcer_items", params={
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
            "select": "say_text,at_time,repeat_rule,is_on",
            "limit": "200",
        }) or []
    except Exception:
        # The table arrives with MIGRATION_ANNOUNCER_SYNC.sql.
        logger.debug("backlog: announcer_items unavailable", exc_info=True)
        return {}

    out = {}
    for r in rows:
        text = (r.get("say_text") or "").strip()
        if not text or r.get("is_on") is False:
            continue
        out[text] = "%s %s" % (
            _spoken_at(r.get("at_time")),
            _REPEAT_WORDS.get(r.get("repeat_rule") or "daily", "every day"))
    return out


def promote_due(user_id, today, lead_days=1):
    """Move backlog items into the Quick Bucket before their deadline bites.

    "it should move it in to quick bucket one day before the duration
    expires automatically."

    A deadline you have to notice yourself is a deadline you will miss —
    that is the whole reason the backlog needed dates. This is the half
    that makes them worth capturing: the day before something is due, it
    stops being backlog and joins the list you actually work from.

    LAZY, NOT SCHEDULED. It runs when either page is opened rather than on
    a timer, because a background job that quietly stops is exactly the
    failure this app keeps hitting — and there is no point promoting an
    item into a list nobody is looking at. Opening either page is also the
    only moment the result can be seen.

    Idempotent: an item already out of `future` is not matched again.
    Returns the number moved, and never raises — a failure here must not
    take the page down with it.
    """
    cutoff = (today + timedelta(days=lead_days)).isoformat()
    base = {
        "user_id": f"eq.{user_id}",
        "is_deleted": "eq.false",
        "is_done": "eq.false",
        "time_bucket": "eq.future",
        "backlog_due": f"lte.{cutoff}",
        "limit": "200",
    }
    try:
        try:
            rows = get("quick_bucket", params={**base, "select": "id,source_task_id,backlog_due"}) or []
        except Exception:
            # source_task_id not migrated yet: plain rows, plain rule.
            rows = get("quick_bucket", params={**base, "select": "id"}) or []
    except Exception:
        # The column arrives with MIGRATION_BACKLOG_ROUTING.sql. Until then
        # this is a feature that does not exist yet, not an error.
        logger.debug("backlog: backlog_due unavailable", exc_info=True)
        return 0
    # Rows mirroring a dated project task (a study plan, for example)
    # belong to their own day, not the day before: a day early would put
    # two days of tasks in the bucket at once.
    rows = [r for r in rows
            if not (r.get("source_task_id") and (r.get("backlog_due") or "") > today.isoformat())]

    moved = 0
    for r in rows:
        try:
            update("quick_bucket",
                   {"id": f"eq.{r['id']}", "user_id": f"eq.{user_id}"},
                   # due_at stays NULL: this is a deadline, not a countdown,
                   # and writing one would start a calendar alarm nobody
                   # asked for. backlog_due is kept so the date still shows
                   # and still goes red if it is missed.
                   {"time_bucket": "now"})
            moved += 1
        except Exception:
            logger.warning("backlog: could not promote %s", r.get("id"),
                           exc_info=True)
    if moved:
        logger.info("backlog: promoted %s item(s) due by %s", moved, cutoff)
    return moved


class _neg_str:
    """Sort a string DESCENDING inside an otherwise ascending key."""

    __slots__ = ("s",)

    def __init__(self, s):
        self.s = s

    def __lt__(self, other):
        return self.s > other.s

    def __eq__(self, other):
        return self.s == other.s


def _future_bucket(user_id, today):
    """Quick Bucket rows that are deferred with no deadline."""
    rows = get("quick_bucket", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "eq.false",
        "is_done": "eq.false",
        "select": "id,text,time_bucket,due_at,priority_label,created_at,"
                  "planned_minutes,backlog_due",
        "limit": "1000",
    }) or []

    def _dated(r):
        """Attach how the deadline is going: late, today, or n days out."""
        by = r.get("backlog_due")
        if not by:
            return {**r, "overdue": False, "due_in": None, "by": None}
        try:
            d = date.fromisoformat(str(by)[:10])
        except (TypeError, ValueError):
            return {**r, "overdue": False, "due_in": None, "by": None}
        left = (d - today).days
        return {**r, "by": d.strftime("%d %b"), "due_in": left,
                "overdue": left < 0}

    out = []
    for r in rows:
        bucket = (r.get("time_bucket") or "").lower()
        if bucket == "future":
            out.append(_dated({**r, "when": None}))
            continue
        # An "at" item is Future only when its pinned moment is past today —
        # the same test the bucket page applies.
        if bucket == "at" and r.get("due_at"):
            try:
                due = datetime.fromisoformat(
                    r["due_at"].replace("Z", "+00:00")).astimezone(user_now().tzinfo)
            except (ValueError, TypeError):
                continue
            if due.date() > today:
                out.append(_dated({**r, "when": due.strftime("%d %b")}))

    # LATE FIRST, then by how little time is left, then newest. A backlog
    # sorted purely by capture date buries the thing that is already
    # overdue under everything typed since.
    out.sort(key=lambda r: (
        0 if r.get("overdue") else 1,
        r["due_in"] if r.get("due_in") is not None else 10 ** 6,
        # Newest first inside a group, so recent captures stay findable.
        _neg_str(r.get("created_at") or ""),
    ))
    return out


def _undated_project_tasks(user_id):
    """Open project tasks that have never been put on a day.

    `is_eliminated` is the flag the projects UI treats as removed — NOT
    `is_deleted`, which the project task list does not even filter on.
    """
    rows = get("project_tasks", params={
        "user_id": f"eq.{user_id}",
        "is_eliminated": "eq.false",
        "select": "task_id,task_text,status,project_id,due_date,priority,created_at,"
                  "plan_date,start_time",
        "limit": "2000",
    }) or []

    tasks = [
        r for r in rows
        if not r.get("plan_date") and not r.get("start_time")
        and (r.get("status") or "open").lower() not in _CLOSED
    ]

    names = {}
    ids = {r.get("project_id") for r in tasks if r.get("project_id")}
    if ids:
        projects = get("projects", params={
            "user_id": f"eq.{user_id}",
            "project_id": f"in.({','.join(str(i) for i in ids)})",
            "select": "project_id,name",
            "limit": "500",
        }) or []
        names = {p["project_id"]: p.get("name") or "Untitled project"
                 for p in projects}

    # Grouped by project, because the grouping is the whole reason these
    # stay where they are. A flat list here would be the move it is meant
    # to avoid, just rendered.
    groups = {}
    for t in tasks:
        pid = t.get("project_id")
        g = groups.setdefault(pid, {"project_id": pid,
                                    "name": names.get(pid, "No project"),
                                    "tasks": []})
        g["tasks"].append(t)
    ordered = sorted(groups.values(),
                     key=lambda g: (-len(g["tasks"]), g["name"].lower()))
    for g in ordered:
        g["tasks"].sort(key=lambda t: (t.get("due_date") or "9999",
                                       t.get("created_at") or ""))
    return ordered, len(tasks)


@backlog_bp.route("/backlog")
@login_required
def backlog_page():
    user_id = session["user_id"]
    today = user_today()

    # Before reading the list, act on anything whose deadline is one day
    # out — otherwise the page shows work as "not yet prioritised" that
    # should already have moved.
    try:
        promote_due(user_id, today)
    except Exception:
        logger.warning("backlog: promotion sweep failed", exc_info=True)

    try:
        future = _future_bucket(user_id, today)
    except Exception:
        logger.warning("backlog: bucket read failed", exc_info=True)
        future = []

    # Which of these already speak for themselves.
    try:
        spoken = _announced(user_id)
    except Exception:
        logger.warning("backlog: announcement read failed", exc_info=True)
        spoken = {}
    for row in future:
        row["announced"] = spoken.get((row.get("text") or "").strip())
    try:
        projects, task_count = _undated_project_tasks(user_id)
    except Exception:
        logger.warning("backlog: project task read failed", exc_info=True)
        projects, task_count = [], 0

    try:
        picker = get("projects", params={
            "user_id": f"eq.{user_id}",
            "select": "project_id,name",
            "order": "name.asc",
            "limit": "500",
        }) or []
    except Exception:
        logger.warning("backlog: project picker read failed", exc_info=True)
        picker = []

    return render_template(
        "backlog.html",
        all_projects=picker,
        future=future,
        projects=projects,
        task_count=task_count,
        total=len(future) + task_count,
        today=today.isoformat(),
    )


# ─────────────────────────────────────────────────────────────────────
# CAPTURE AND ROUTE
# ─────────────────────────────────────────────────────────────────────

def _own_bucket_row(user_id, item_id):
    rows = get("quick_bucket", params={
        "id": f"eq.{item_id}",
        "user_id": f"eq.{user_id}",
        "select": "id,text,time_bucket,is_deleted",
        "limit": "1",
    }) or []
    return rows[0] if rows else None


def _own_task_row(user_id, task_id):
    rows = get("project_tasks", params={
        "task_id": f"eq.{task_id}",
        "user_id": f"eq.{user_id}",
        "select": "task_id,task_text,project_id,plan_date,status",
        "limit": "1",
    }) or []
    return rows[0] if rows else None


@backlog_bp.route("/api/backlog/capture", methods=["POST"])
@login_required
def capture():
    """Dump one or many lines into the backlog.

    Pasting a list is the whole point of a laundry list, so every non-blank
    LINE becomes its own item. The bucket page's "@5m" and "@1pm" tokens are
    deliberately NOT parsed here: those pin a time, and a thing with a time
    on it is not backlog.
    """
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}
    raw = (data.get("text") or "")

    lines = [ln.strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln][:100]
    if not lines:
        return jsonify({"error": "Text required"}), 400

    # HOW LONG IT WILL TAKE, captured while you still know.
    # Estimating an hour of backlog later, item by item, is a job nobody
    # does — so the effort figures stay empty and "what can I fit in the
    # next 40 minutes" can never be answered. Optional, and applied to
    # every line of a pasted block, which is the common case: a list of
    # similar small jobs.
    try:
        minutes = int(data.get("minutes") or 0)
    except (TypeError, ValueError):
        minutes = 0
    minutes = max(0, min(600, minutes))

    # "has to do by X days (take the current date as the baseline)."
    # Counted from today rather than asked for as a date: when you are
    # emptying your head onto a page, "3 days" is the thing you know and
    # "the 26th" is arithmetic you have to stop and do.
    try:
        days = int(data.get("days") or 0)
    except (TypeError, ValueError):
        days = 0
    days = max(0, min(3650, days))
    due = (user_today() + timedelta(days=days)).isoformat() if days else None

    made = []
    for ln in lines:
        try:
            row = {
                "user_id": user_id,
                "text": ln[:2000],
                "time_bucket": "future",
                "is_done": False,
                "is_deleted": False,
            }
            if minutes:
                row["planned_minutes"] = minutes
            if due:
                row["backlog_due"] = due
            res = post("quick_bucket", row)
            if res:
                made.append(res[0])
        except Exception:
            logger.exception("backlog capture failed for one line")

    if not made:
        return jsonify({"error": "Could not save"}), 500
    return jsonify({"status": "ok", "created": made})


@backlog_bp.route("/api/backlog/drop", methods=["POST"])
@login_required
def drop():
    """Soft-delete a captured item once the browser has routed it onward.

    Used by the Inbox and References routes, which are posted straight to
    their own endpoints so their metadata pipelines still run. NEVER a hard
    delete — the row stays, flagged.
    """
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}
    item_id = data.get("id")
    if not item_id:
        return jsonify({"error": "id required"}), 400
    if not _own_bucket_row(user_id, item_id):
        return jsonify({"error": "Not found"}), 404
    update("quick_bucket",
           {"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
           {"is_deleted": True})
    return jsonify({"status": "ok"})


@backlog_bp.route("/api/backlog/send", methods=["POST"])
@login_required
def send():
    """Route one backlog entry to where it actually belongs.

    `kind` says which of the two lists the row came from, because they are
    treated differently on purpose — see the module docstring.
    """
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}
    kind = (data.get("kind") or "bucket").strip().lower()
    dest = (data.get("to") or "").strip().lower()
    item_id = data.get("id")

    if not item_id:
        return jsonify({"error": "id required"}), 400

    # ── a project task: dated, never relocated ───────────────────────
    if kind == "task":
        if dest != "quick":
            return jsonify({"error": "A project task can only be sent to the "
                                     "Quick Bucket"}), 400
        task = _own_task_row(user_id, item_id)
        if not task:
            return jsonify({"error": "Not found"}), 404

        today = user_today().isoformat()
        from routes.quick_bucket import BUCKET_SET, _due_at_for
        bucket = (data.get("bucket") or "now").strip().lower()
        if bucket not in BUCKET_SET or bucket == "future":
            bucket = "now"
        try:
            res = post("quick_bucket", {
                "user_id": user_id,
                "text": ((data.get("text") or "").strip()
                         or task.get("task_text") or "Task")[:2000],
                "time_bucket": bucket,
                "due_at": _due_at_for(bucket),
                "is_done": False,
                "is_deleted": False,
                "source_task_id": task["task_id"],
            })
        except Exception:
            logger.exception("backlog: promoting a project task failed")
            return jsonify({"error": "Could not promote. If this persists the "
                                     "MIGRATION_BACKLOG_ROUTING.sql migration "
                                     "may not have been run."}), 500

        # Dating it is what takes it OUT of the backlog: backlog is defined
        # as "no plan_date and no start_time", so without this the task
        # would still sit here after being promoted.
        try:
            update("project_tasks",
                   {"task_id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
                   {"plan_date": today})
        except Exception:
            logger.exception("backlog: dating the promoted task failed")

        return jsonify({"status": "ok", "created": (res or [None])[0],
                        "plan_date": today})

    # ── a captured item: really moved ────────────────────────────────
    row = _own_bucket_row(user_id, item_id)
    if not row:
        return jsonify({"error": "Not found"}), 404
    text = (row.get("text") or "").strip()

    if dest == "quick":
        # Same table, same row — "prioritised" IS a bucket, so nothing is
        # copied and nothing can drift.
        #
        # WHICH bucket is the whole decision being made here. Sending
        # everything to "now" would move the pile rather than prioritise
        # it, which is the opposite of what the Quick Bucket is for.
        from routes.quick_bucket import BUCKET_SET, _due_at_for
        bucket = (data.get("bucket") or "now").strip().lower()
        if bucket not in BUCKET_SET or bucket == "future":
            bucket = "now"
        patch = {"time_bucket": bucket, "due_at": _due_at_for(bucket)}
        new_text = (data.get("text") or "").strip()
        if new_text:
            patch["text"] = new_text[:2000]
        # The estimate travels with the row because it IS the row — only
        # the bucket changes. It is offered again here because moving
        # something into the list you work from is the moment you actually
        # know how long it will take, and an item captured without one
        # would otherwise never get one.
        if "minutes" in data:
            try:
                mins = int(data.get("minutes") or 0)
            except (TypeError, ValueError):
                mins = 0
            patch["planned_minutes"] = max(0, min(600, mins)) or None
        update("quick_bucket",
               {"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"}, patch)
        return jsonify({"status": "ok", "time_bucket": bucket})

    if dest == "project":
        project_id = data.get("project_id")
        if not project_id:
            return jsonify({"error": "Pick a project"}), 400
        owns = get("projects", params={
            "project_id": f"eq.{project_id}",
            "user_id": f"eq.{user_id}",
            "select": "project_id",
            "limit": "1",
        }) or []
        if not owns:
            return jsonify({"error": "Not found"}), 404
        payload = {
            "project_id": project_id,
            "user_id": user_id,
            "task_text": ((data.get("text") or "").strip() or text)[:2000],
            # The project's own backlog status, so it lands as work to be
            # planned rather than as work already underway.
            "status": "backlog",
            "start_date": user_today().isoformat(),
        }
        due = (data.get("due_date") or "").strip()
        if due:
            payload["due_date"] = due[:10]
            # The parking filter reads revised_due_date, so an insert that
            # sets only due_date is invisible to it — mirrored the way the
            # projects page mirrors it.
            payload["revised_due_date"] = due[:10]
        pri = (data.get("priority") or "").strip().lower()
        if pri in ("high", "medium", "low"):
            payload["priority"] = pri
        try:
            post("project_tasks", payload)
        except Exception:
            logger.exception("backlog: creating the project task failed")
            return jsonify({"error": "Could not add to that project"}), 500
        update("quick_bucket",
               {"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
               {"is_deleted": True})
        return jsonify({"status": "ok"})

    if dest == "note":
        try:
            post("scribble_notes", {
                "user_id": user_id,
                "title": ((data.get("title") or "").strip() or text)[:120],
                "content": (data.get("content") or "").strip() or text,
                "notebook": (data.get("notebook") or "").strip() or "Backlog",
            })
        except Exception:
            logger.exception("backlog: creating the note failed")
            return jsonify({"error": "Could not save the note"}), 500
        update("quick_bucket",
               {"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
               {"is_deleted": True})
        return jsonify({"status": "ok"})

    return jsonify({"error": "Unknown destination"}), 400
