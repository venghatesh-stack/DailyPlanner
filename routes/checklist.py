"""
Daily Checklist — recurring items the user wants to be reminded about
each day (take meds, stretch, drink water, etc). Each item can have any
number of reminder times stored in checklist_reminder_times; if any are
set, the push scheduler fires a Web Push notification at each matching
local time on the matching schedule.

Distinct from `habits`: habits track quantity/streak; checklists just
need to be ticked off for the day. Each scheduled fire (a row in
checklist_reminder_times) is ticked off independently — an item with
3 reminders has 3 separate "settle" actions per day.

`checklist_items.reminder_time` is kept as a legacy mirror of the first
child row's time so older code/queries still see something sensible.
"""
import logging
import threading
from datetime import date, datetime
from datetime import time as dtime

from flask import Blueprint, jsonify, render_template, request, session
from requests.exceptions import HTTPError

logger = logging.getLogger(__name__)

from auth import login_required
from services import checklist_calendar_service as cal_sync
from services import checklist_history
from supabase_client import delete as sb_delete
from supabase_client import get, post, update
from utils.user_tz import user_today

checklist_bp = Blueprint("checklist", __name__)


VALID_SCHEDULES = {
    "daily", "weekdays", "weekends", "custom",
    # Monthly variants. `schedule_days` encodes the parameters:
    #   monthly_dow → "WEEK:DAY" e.g. "-1:6" = last Saturday (DAY uses
    #                Sun=0..Sat=6; WEEK is 1..5 for nth-of-month or -1
    #                for the last occurrence).
    #   monthly_dom → "N" where N is 1..31, or "-1" for the last day
    #                 of the month.
    "monthly_dow", "monthly_dom",
    # One-shot: fires only on the date in schedule_days ("YYYY-MM-DD").
    # The list endpoint hides it on every other day.
    "once",
}
VALID_TIMES_OF_DAY = {"morning", "afternoon", "evening", "anytime"}


def _parse_reminder_time(value):
    """Accept 'HH:MM' or 'HH:MM:SS' or empty string/None. Returns a
    Postgres-friendly string or None."""
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None
    parts = value.split(":")
    if len(parts) < 2 or len(parts) > 3:
        raise ValueError(f"Invalid time: {value}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2]) if len(parts) == 3 else 0
    return dtime(hh, mm, ss).isoformat()


def _parse_reminder_times(raw):
    """Accept a list of HH:MM/HH:MM:SS strings (or a single string for
    backwards compat). Returns a list of unique HH:MM:SS strings sorted
    chronologically, or [] if nothing was supplied."""
    if raw is None:
        return None  # sentinel: client didn't send the key at all
    if isinstance(raw, str):
        raw = [raw] if raw.strip() else []
    if not isinstance(raw, list):
        raise ValueError("reminder_times must be a list")
    out = set()
    for v in raw:
        parsed = _parse_reminder_time(v)
        if parsed:
            out.add(parsed)
    return sorted(out)


def _parse_end_date(value):
    """Accept 'YYYY-MM-DD' or empty. Returns ISO string or None."""
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None
    return date.fromisoformat(value).isoformat()


def _normalize_group(value):
    """Normalise a user-typed group name to Title Case so 'health',
    'Health', 'HEALTH' all collapse to 'Health'. Empty → None."""
    if not value:
        return None
    cleaned = " ".join(str(value).strip().split())
    if not cleaned:
        return None
    return cleaned.title()


def _serialize(item, tick_map, times_map):
    """tick_map: {(item_id, hhmmss_or_None): True}
       times_map: {item_id: [time_row, ...]} ordered by position/time."""
    rows = times_map.get(item["id"], [])
    reminder_times = []
    for r in rows:
        t = (r.get("reminder_time") or "")[:5]  # HH:MM
        full = (r.get("reminder_time") or "")
        reminder_times.append({
            "id": r["id"],
            "time": t,
            "ticked": tick_map.get((item["id"], full), False),
        })

    # Legacy single field: first time if any, else whatever is on parent.
    legacy_time = reminder_times[0]["time"] if reminder_times else (item.get("reminder_time") or "")[:5]

    if reminder_times:
        all_ticked = all(rt["ticked"] for rt in reminder_times)
    else:
        # No child rows — fall back to the legacy NULL-keyed tick.
        all_ticked = tick_map.get((item["id"], None), False)

    return {
        "id": item["id"],
        "name": item["name"],
        "notes": item.get("notes") or "",
        "schedule": item.get("schedule") or "daily",
        "schedule_days": item.get("schedule_days") or "",
        "time_of_day": item.get("time_of_day") or "anytime",
        "reminder_time": legacy_time,
        "reminder_times": reminder_times,
        "recurrence_end": item.get("recurrence_end") or "",
        "group_name": item.get("group_name") or "",
        "position": item.get("position") or 9999,
        "ticked": all_ticked,
    }


def _reconcile_reminder_times(user_id, item_id, desired_times):
    """Diff existing checklist_reminder_times rows for this item against
    `desired_times` (a list of HH:MM:SS strings). Inserts missing rows,
    deletes removed rows. Returns (added_rows, removed_rows) so the
    caller can sync Calendar accordingly."""
    existing = get(
        "checklist_reminder_times",
        {"item_id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
    ) or []
    existing_by_time = {(r.get("reminder_time") or ""): r for r in existing}
    desired_set = set(desired_times)

    removed = [r for t, r in existing_by_time.items() if t not in desired_set]
    for r in removed:
        sb_delete(
            "checklist_reminder_times",
            {"id": f"eq.{r['id']}", "user_id": f"eq.{user_id}"},
        )

    added = []
    for pos, t in enumerate(desired_times):
        if t in existing_by_time:
            # Keep position in sync with new ordering.
            current_pos = existing_by_time[t].get("position")
            if current_pos != pos:
                update(
                    "checklist_reminder_times",
                    params={"id": f"eq.{existing_by_time[t]['id']}",
                            "user_id": f"eq.{user_id}"},
                    json={"position": pos},
                )
            continue
        try:
            inserted = post(
                "checklist_reminder_times",
                {
                    "item_id": item_id,
                    "user_id": user_id,
                    "reminder_time": t,
                    "position": pos,
                },
                prefer="return=representation",
            )
        except HTTPError:
            logger.exception("Failed to insert reminder_time %s for item %s", t, item_id)
            continue
        if inserted:
            added.append(inserted[0])

    return added, removed


def _sync_children_calendar_async(user_id, item_row, added, removed):
    """Background: delete Calendar events for removed rows, create events
    for added rows. Supabase is the source of truth; Calendar is best-effort."""
    def _work():
        for r in removed:
            ev = r.get("google_event_id")
            if not ev:
                continue
            try:
                cal_sync.delete_from_calendar(user_id, ev)
            except Exception:
                logger.exception("Calendar delete failed for event %s", ev)

        for r in added:
            payload = {**item_row,
                       "reminder_time": r["reminder_time"],
                       "google_event_id": None}
            try:
                new_id = cal_sync.sync_to_calendar(user_id, payload)
            except Exception:
                logger.exception("Calendar insert failed for child %s", r.get("id"))
                continue
            if new_id:
                update(
                    "checklist_reminder_times",
                    params={"id": f"eq.{r['id']}", "user_id": f"eq.{user_id}"},
                    json={"google_event_id": new_id},
                )

    threading.Thread(target=_work, name=f"cal-children-{item_row.get('id')}",
                     daemon=True).start()


def _resync_all_children_calendar_async(user_id, item_row):
    """Background: re-push every existing child row to Calendar (name,
    schedule, notes may have changed on the parent)."""
    def _work():
        rows = get(
            "checklist_reminder_times",
            {"item_id": f"eq.{item_row['id']}", "user_id": f"eq.{user_id}"},
        ) or []
        for r in rows:
            payload = {**item_row,
                       "reminder_time": r["reminder_time"],
                       "google_event_id": r.get("google_event_id")}
            try:
                new_id = cal_sync.sync_to_calendar(user_id, payload)
            except Exception:
                logger.exception("Calendar resync failed for child %s", r.get("id"))
                continue
            if new_id and new_id != r.get("google_event_id"):
                update(
                    "checklist_reminder_times",
                    params={"id": f"eq.{r['id']}", "user_id": f"eq.{user_id}"},
                    json={"google_event_id": new_id},
                )

    threading.Thread(target=_work, name=f"cal-resync-{item_row.get('id')}",
                     daemon=True).start()


# ─────────────────────────────────────────────
#  PAGE
# ─────────────────────────────────────────────
def _requested_date():
    """The date the caller is asking about, defaulting to today.

    The checklist has always been a TODAY surface, and mostly should stay
    one. This exists for a narrower reason: the Day Board links each row to
    the section that owns it, and a board showing Thursday could not link
    its checklist rows anywhere, because this page had no way to be told
    which day it meant. A bad or missing value falls back to today rather
    than erroring — a wrong date in a URL is a bad link, not a failure the
    user can act on.
    """
    raw = (request.args.get("date") or "").strip()
    if not raw:
        return user_today()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return user_today()


@checklist_bp.route("/checklist")
@login_required
def checklist_page():
    on = _requested_date()
    today = user_today()
    # Yesterday's misses, on today's view only. A checklist is a daily
    # loop and the only feedback that changes behaviour is about the loop
    # you just finished — on a historical view the line would be noise
    # about a day two days before the one you are reading.
    yesterday = None
    if on == today:
        try:
            yesterday = checklist_history.yesterday_summary(session["user_id"], today)
        except Exception:
            logger.warning("yesterday summary failed", exc_info=True)
    return render_template("checklist.html",
                           plan_date=on.isoformat(),
                           is_today=(on == today),
                           today=today.isoformat(),
                           yesterday=yesterday)


@checklist_bp.route("/checklist/history")
@login_required
def checklist_history_page():
    """Adherence over time, built from ticks that were always being stored
    and never read for any day but today.

    The window is a query arg because the useful question changes: 14 days
    answers "am I keeping this up", 90 answers "did that ever stick".
    """
    try:
        days = int(request.args.get("days") or 30)
    except (TypeError, ValueError):
        days = 30
    days = max(7, min(checklist_history.MAX_DAYS, days))

    end = _requested_date()
    data = checklist_history.load(session["user_id"], end, days, today=user_today())
    return render_template("checklist_history.html",
                           data=data,
                           days=days,
                           today=user_today().isoformat(),
                           options=(14, 30, 90, 180))


# ─────────────────────────────────────────────
#  LIST
# ─────────────────────────────────────────────
@checklist_bp.route("/api/checklist/mutes", methods=["GET"])
@login_required
def checklist_mutes():
    """Every checklist item with its reminder times and whether it is muted.

    Powers the notification list inside the announcements dialog. Muting is
    per ITEM rather than per reminder time: someone silencing "take
    vitamins" means all of it, and a half-muted item is a state nobody would
    be able to reason about later.
    """
    user_id = session["user_id"]
    items = get("checklist_items", {
        "user_id": f"eq.{user_id}",
        "is_deleted": "eq.false",
        "order": "position.asc,created_at.asc",
    }) or []
    times = get("checklist_reminder_times", {
        "user_id": f"eq.{user_id}",
        "select": "item_id,reminder_time",
        "order": "reminder_time.asc",
    }) or []

    by_item = {}
    for t in times:
        by_item.setdefault(t["item_id"], []).append(
            str(t.get("reminder_time") or "")[:5])

    out = []
    for it in items:
        # Fall back to the legacy single-column time, which the scheduler
        # still honours for items that never gained child rows.
        stamps = by_item.get(it["id"]) or (
            [str(it["reminder_time"])[:5]] if it.get("reminder_time") else [])
        if not stamps:
            continue          # nothing to notify about, so nothing to mute
        out.append({
            "id": it["id"],
            "name": it.get("name") or it.get("title") or "",
            "times": stamps,
            # Absent column (migration not yet run) reads as not muted.
            "muted": bool(it.get("notify_muted")),
        })
    return jsonify({"items": out})


@checklist_bp.route("/api/checklist/mutes/<item_id>", methods=["POST"])
@login_required
def set_checklist_mute(item_id):
    """Mute or unmute one item's push reminders.

    A mute is a FLAG, never a deletion of the reminder times — unmuting has
    to restore the exact schedule, which is the entire difference between
    this and the old advice to 'remove its reminder times'.
    """
    user_id = session["user_id"]
    muted = bool((request.get_json(silent=True) or {}).get("muted"))
    try:
        # update(table, FILTERS, PAYLOAD) — filters first.
        update("checklist_items", {
            "id": f"eq.{item_id}",
            "user_id": f"eq.{user_id}",
        }, {"notify_muted": muted})
    except Exception:
        # The commonest cause is the migration not having been run. Say so
        # rather than returning a bare 500 that looks like a bug.
        logger.warning("checklist mute failed for %s", item_id, exc_info=True)
        return jsonify({
            "ok": False,
            "error": "Could not save. If this is new, "
                     "MIGRATION_ANNOUNCER_MUTES.sql may not have been run yet.",
        }), 500
    return jsonify({"ok": True, "id": item_id, "muted": muted})


@checklist_bp.route("/api/checklist/items", methods=["GET"])
@login_required
def list_items():
    user_id = session["user_id"]
    # Named `today` throughout this function for the day being SHOWN, which
    # is today unless the caller asked for another one.
    today = _requested_date().isoformat()

    items = get(
        "checklist_items",
        {
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
            "order": "position.asc,created_at.asc",
        },
    ) or []

    # One-shot items appear only on their scheduled day — before/after
    # they'd just be clutter on the daily list. Soft-deleted rows are
    # already excluded above; this filter is for never-deleted "once"
    # items whose day has passed (or is yet to come).
    items = [
        it for it in items
        if it.get("schedule") != "once"
        or (it.get("schedule_days") or "").strip() == today
    ]

    times = get(
        "checklist_reminder_times",
        {
            "user_id": f"eq.{user_id}",
            "order": "position.asc,reminder_time.asc",
        },
    ) or []
    times_map = {}
    for r in times:
        times_map.setdefault(r["item_id"], []).append(r)

    ticks = get(
        "checklist_ticks",
        {
            "user_id": f"eq.{user_id}",
            "tick_date": f"eq.{today}",
        },
    ) or []
    tick_map = {(t["item_id"], t.get("reminder_time")): True for t in ticks}

    return jsonify({
        "items": [_serialize(i, tick_map, times_map) for i in items],
        "date": today,
    })


# ─────────────────────────────────────────────
#  CREATE
# ─────────────────────────────────────────────
@checklist_bp.route("/api/checklist/items", methods=["POST"])
@login_required
def create_item():
    user_id = session["user_id"]
    data = request.get_json() or {}

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    schedule = (data.get("schedule") or "daily").strip()
    if schedule not in VALID_SCHEDULES:
        return jsonify({"error": f"Invalid schedule: {schedule}"}), 400

    time_of_day = (data.get("time_of_day") or "anytime").strip()
    if time_of_day not in VALID_TIMES_OF_DAY:
        return jsonify({"error": f"Invalid time_of_day: {time_of_day}"}), 400

    # New multi-time field takes precedence; fall back to legacy single
    # field so older clients still work.
    try:
        if "reminder_times" in data:
            times = _parse_reminder_times(data.get("reminder_times")) or []
        else:
            single = _parse_reminder_time(data.get("reminder_time"))
            times = [single] if single else []
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        recurrence_end = _parse_end_date(data.get("recurrence_end"))
    except ValueError:
        return jsonify({"error": "Invalid end date"}), 400

    schedule_days = (data.get("schedule_days") or "").strip()
    group_name = _normalize_group(data.get("group_name"))

    legacy_first = times[0] if times else None

    try:
        inserted = post(
            "checklist_items",
            {
                "user_id": user_id,
                "name": name,
                "notes": (data.get("notes") or "").strip() or None,
                "schedule": schedule,
                "schedule_days": schedule_days or None,
                "time_of_day": time_of_day,
                "reminder_time": legacy_first,
                "recurrence_end": recurrence_end,
                "group_name": group_name,
                "position": int(data.get("position") or 9999),
                "is_deleted": False,
            },
            prefer="return=representation",
        )
    except HTTPError as e:
        return jsonify({"error": f"Database error: {e}"}), 500

    row = inserted[0]

    added, removed = _reconcile_reminder_times(user_id, row["id"], times)
    if added or removed:
        _sync_children_calendar_async(user_id, row, added, removed)

    # Re-list this item's children so the response reflects truth.
    times_rows = get(
        "checklist_reminder_times",
        {"item_id": f"eq.{row['id']}", "user_id": f"eq.{user_id}",
         "order": "position.asc,reminder_time.asc"},
    ) or []
    return jsonify(_serialize(row, {}, {row["id"]: times_rows}))


# ─────────────────────────────────────────────
#  UPDATE
# ─────────────────────────────────────────────
@checklist_bp.route("/api/checklist/items/<item_id>", methods=["PATCH"])
@login_required
def update_item(item_id):
    user_id = session["user_id"]
    data = request.get_json() or {}

    existing = get(
        "checklist_items",
        {"id": f"eq.{item_id}", "user_id": f"eq.{user_id}", "is_deleted": "eq.false"},
    )
    if not existing:
        return jsonify({"error": "Item not found"}), 404

    patch = {}
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            return jsonify({"error": "Name cannot be empty"}), 400
        patch["name"] = name
    if "notes" in data:
        patch["notes"] = (data["notes"] or "").strip() or None
    if "schedule" in data:
        if data["schedule"] not in VALID_SCHEDULES:
            return jsonify({"error": "Invalid schedule"}), 400
        patch["schedule"] = data["schedule"]
    if "schedule_days" in data:
        patch["schedule_days"] = (data["schedule_days"] or "").strip() or None
    if "time_of_day" in data:
        if data["time_of_day"] not in VALID_TIMES_OF_DAY:
            return jsonify({"error": "Invalid time_of_day"}), 400
        patch["time_of_day"] = data["time_of_day"]
    if "recurrence_end" in data:
        try:
            patch["recurrence_end"] = _parse_end_date(data["recurrence_end"])
        except ValueError:
            return jsonify({"error": "Invalid end date"}), 400
    if "group_name" in data:
        patch["group_name"] = _normalize_group(data["group_name"])
    if "position" in data:
        patch["position"] = int(data["position"])

    # Reminder times — parse either the new multi-field or fall back to
    # the legacy single-value field. Either being present updates the
    # child rows; neither present leaves them alone.
    desired_times = None
    if "reminder_times" in data:
        try:
            desired_times = _parse_reminder_times(data.get("reminder_times")) or []
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    elif "reminder_time" in data:
        try:
            single = _parse_reminder_time(data.get("reminder_time"))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        desired_times = [single] if single else []

    if desired_times is not None:
        patch["reminder_time"] = desired_times[0] if desired_times else None

    if not patch and desired_times is None:
        return jsonify({"error": "Nothing to update"}), 400

    if patch:
        update(
            "checklist_items",
            params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
            json=patch,
        )

    fresh_rows = get(
        "checklist_items",
        {"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
    ) or []
    fresh = fresh_rows[0] if fresh_rows else existing[0]

    if desired_times is not None:
        added, removed = _reconcile_reminder_times(user_id, item_id, desired_times)
        if added or removed:
            _sync_children_calendar_async(user_id, fresh, added, removed)
        # If schedule / name / notes also changed, refresh the surviving
        # children too so their Calendar event bodies match.
        body_relevant = {"name", "notes", "schedule", "schedule_days", "recurrence_end"}
        if any(k in patch for k in body_relevant):
            _resync_all_children_calendar_async(user_id, fresh)
    else:
        # Children unchanged but the parent's body fields may have moved
        # — re-push to Calendar so existing events stay in sync.
        body_relevant = {"name", "notes", "schedule", "schedule_days", "recurrence_end"}
        if any(k in patch for k in body_relevant):
            _resync_all_children_calendar_async(user_id, fresh)

    return jsonify({"success": True})


# ─────────────────────────────────────────────
#  SOFT DELETE
# ─────────────────────────────────────────────
@checklist_bp.route("/api/checklist/items/<item_id>", methods=["DELETE"])
@login_required
def delete_item(item_id):
    user_id = session["user_id"]

    existing = get(
        "checklist_items",
        {"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
    ) or []
    parent_event = existing[0].get("google_event_id") if existing else None

    child_rows = get(
        "checklist_reminder_times",
        {"item_id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
    ) or []

    update(
        "checklist_items",
        params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
        json={"is_deleted": True, "google_event_id": None},
    )
    # Hard-delete child reminder_time rows — they're config, not user
    # data, and the parent's is_deleted flag is what hides the item.
    sb_delete(
        "checklist_reminder_times",
        {"item_id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
    )

    event_ids = [r.get("google_event_id") for r in child_rows if r.get("google_event_id")]
    if parent_event:
        event_ids.append(parent_event)
    if event_ids:
        def _cleanup():
            for ev in event_ids:
                try:
                    cal_sync.delete_from_calendar(user_id, ev)
                except Exception:
                    logger.exception("Background calendar delete failed")
        threading.Thread(target=_cleanup, daemon=True).start()

    return jsonify({"success": True})


# ─────────────────────────────────────────────
#  TICK / UNTICK
# ─────────────────────────────────────────────
def _ownership_ok(user_id, item_id):
    owner = get(
        "checklist_items",
        {"id": f"eq.{item_id}", "user_id": f"eq.{user_id}", "is_deleted": "eq.false"},
    )
    return bool(owner)


@checklist_bp.route("/api/checklist/items/<item_id>/tick", methods=["POST"])
@login_required
def tick_item(item_id):
    user_id = session["user_id"]
    today = user_today().isoformat()

    if not _ownership_ok(user_id, item_id):
        return jsonify({"error": "Item not found"}), 404

    body = request.get_json(silent=True) or {}
    try:
        rt = _parse_reminder_time(body.get("reminder_time"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # `all=true` is the "main checkbox" path — tick every child reminder
    # for today. Useful for items with several daily reminders.
    if body.get("all"):
        children = get(
            "checklist_reminder_times",
            {"item_id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
        ) or []
        if not children:
            return _insert_tick(user_id, item_id, today, None)
        for c in children:
            _insert_tick(user_id, item_id, today, c["reminder_time"])
        return jsonify({"success": True})

    return _insert_tick(user_id, item_id, today, rt)


def _insert_tick(user_id, item_id, today, reminder_time):
    try:
        payload = {"user_id": user_id, "item_id": item_id, "tick_date": today}
        if reminder_time:
            payload["reminder_time"] = reminder_time
        post("checklist_ticks", payload, prefer="return=minimal")
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 409:
            return jsonify({"success": True, "already": True})
        raise
    return jsonify({"success": True})


@checklist_bp.route("/api/checklist/items/<item_id>/untick", methods=["POST"])
@login_required
def untick_item(item_id):
    user_id = session["user_id"]
    today = user_today().isoformat()

    if not _ownership_ok(user_id, item_id):
        return jsonify({"error": "Item not found"}), 404

    body = request.get_json(silent=True) or {}
    try:
        rt = _parse_reminder_time(body.get("reminder_time"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    params = {
        "user_id": f"eq.{user_id}",
        "item_id": f"eq.{item_id}",
        "tick_date": f"eq.{today}",
    }

    if body.get("all"):
        # Drop every tick for this item today, regardless of reminder_time.
        sb_delete("checklist_ticks", params)
        return jsonify({"success": True})

    if rt:
        params["reminder_time"] = f"eq.{rt}"
    else:
        params["reminder_time"] = "is.null"

    sb_delete("checklist_ticks", params)
    return jsonify({"success": True})


# ─────────────────────────────────────────────
#  GROUPS  /  CALENDAR SYNC  /  REORDER
# ─────────────────────────────────────────────
@checklist_bp.route("/api/checklist/groups", methods=["GET"])
@login_required
def list_groups():
    """Return the distinct group names this user has used, alphabetical.
    Powers the <datalist> autocomplete in the edit modal."""
    user_id = session["user_id"]
    rows = get(
        "checklist_items",
        {
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
            "group_name": "not.is.null",
            "select": "group_name",
        },
    ) or []
    names = sorted({(r.get("group_name") or "").strip() for r in rows if r.get("group_name")})
    return jsonify({"groups": [n for n in names if n]})


@checklist_bp.route("/api/checklist/sync-calendar", methods=["POST"])
@login_required
def sync_calendar():
    """Backfill: create Google Calendar events for every checklist
    reminder_time row that doesn't have a google_event_id yet. Safe to
    run multiple times — already-synced rows are skipped."""
    user_id = session["user_id"]

    rows = get(
        "checklist_reminder_times",
        {
            "user_id": f"eq.{user_id}",
            "google_event_id": "is.null",
        },
    ) or []
    if not rows:
        return jsonify({"success": True, "synced": 0, "skipped": 0,
                        "failed": 0, "total_candidates": 0})

    # Pull all referenced parent items in one shot.
    item_ids = ",".join(sorted({r["item_id"] for r in rows}))
    parents = get(
        "checklist_items",
        {"id": f"in.({item_ids})", "user_id": f"eq.{user_id}",
         "is_deleted": "eq.false"},
    ) or []
    parent_by_id = {p["id"]: p for p in parents}

    synced = skipped = failed = 0
    for r in rows:
        parent = parent_by_id.get(r["item_id"])
        if not parent:
            skipped += 1
            continue
        payload = {**parent,
                   "reminder_time": r["reminder_time"],
                   "google_event_id": None}
        try:
            new_id = cal_sync.sync_to_calendar(user_id, payload)
        except Exception:
            failed += 1
            continue
        if new_id:
            update(
                "checklist_reminder_times",
                params={"id": f"eq.{r['id']}", "user_id": f"eq.{user_id}"},
                json={"google_event_id": new_id},
            )
            synced += 1
        else:
            skipped += 1

    return jsonify({
        "success": True,
        "synced": synced,
        "skipped": skipped,
        "failed": failed,
        "total_candidates": len(rows),
    })


@checklist_bp.route("/api/checklist/reorder", methods=["POST"])
@login_required
def reorder_items():
    user_id = session["user_id"]
    data = request.get_json() or {}
    order = data.get("order") or []

    for pos, item_id in enumerate(order):
        update(
            "checklist_items",
            params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
            json={"position": pos},
        )
    return jsonify({"success": True})
