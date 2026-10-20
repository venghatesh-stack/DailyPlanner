
import logging
import threading
from datetime import date, datetime, timedelta
import os

from flask import Blueprint, jsonify, redirect, request, session, url_for
from supabase_client import delete as sb_delete
from supabase_client import get, post, update

logger = logging.getLogger("daily_plan")

from routes.planner import build_google_datetime, get_conflicts
from services.login_service import login_required
from services import event_recurrence
from services import events_calendar_service as events_cal
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from utils.dates import safe_date_from_string
from utils.planner_parser import parse_planner_input
SCOPES = [
    'https://www.googleapis.com/auth/calendar.events',
    # drive.file = files this app creates or that the user explicitly
    # opens with it. Used by the Knowledge Base page to manage PDFs in
    # the user's "knowledgebase2026" Drive folder. Non-sensitive scope,
    # no verification needed.
    'https://www.googleapis.com/auth/drive.file',
]
events_bp = Blueprint("events", __name__)
@events_bp.route("/api/v2/events")
@login_required
def list_events():
    """List events for the given date. Expands recurring series:
    one visible event per occurrence, including per-occurrence
    overrides (is_exception=true) and skipping dates in
    event_exceptions."""
    user_id = session["user_id"]
    plan_date_str = request.args.get("date")
    if not plan_date_str:
        return jsonify([])

    try:
        plan_date = date.fromisoformat(plan_date_str)
    except ValueError:
        return jsonify({"error": "Invalid date"}), 400

    # 1. Pull everything for this user that could possibly surface on
    # the target date. That includes:
    #    - single events where plan_date = target
    #    - recurring masters whose start <= target and (no end or end >= target)
    #    - per-occurrence exception rows where original_date = target
    all_rows = get(
        "daily_events",
        params={
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
        },
    ) or []

    singles = [r for r in all_rows
               if not r.get("recurrence_rule") and not r.get("is_exception")
               and r.get("plan_date") == plan_date_str]

    masters = [r for r in all_rows if r.get("recurrence_rule")]

    overrides_by_series_date = {
        (r.get("series_id"), r.get("original_date")): r
        for r in all_rows if r.get("is_exception")
    }

    # 2. Skip dates listed in event_exceptions for each series.
    skipped = get(
        "event_exceptions",
        params={"user_id": f"eq.{user_id}", "exception_date": f"eq.{plan_date_str}"},
    ) or []
    skipped_series = {row["series_id"] for row in skipped if row.get("reason") == "deleted"}

    # 3. Expand masters.
    expanded = []
    for m in masters:
        # Cheap bound check without importing event_recurrence for the single-date case.
        occurs = plan_date in event_recurrence.expand_occurrences(m, plan_date, plan_date)
        if not occurs:
            continue
        if m.get("series_id") in skipped_series:
            continue
        override = overrides_by_series_date.get((m.get("series_id"), plan_date_str))
        if override:
            # The user previously modified this single occurrence — show that.
            expanded.append({**override, "plan_date": plan_date_str,
                             "_is_recurring_instance": True,
                             "_series_id": m.get("series_id"),
                             "_master_id": m.get("id")})
        else:
            # Materialise a virtual instance from the master.
            expanded.append({
                **m,
                "plan_date": plan_date_str,
                "_is_recurring_instance": True,
                "_series_id": m.get("series_id"),
                "_master_id": m.get("id"),
            })

    # 4. Combine and sort.
    events = singles + expanded
    events.sort(key=lambda r: (r.get("start_time") or "00:00"))
    return jsonify(events)

@events_bp.route("/api/v2/events", methods=["POST"])
@login_required
def create_event():
    user_id = session["user_id"]
    data = request.json or {}
    force = data.get("force", False)

    if data["end_time"] <= data["start_time"]:
        return jsonify({"error": "Invalid time range"}), 400

    # Recurrence fields (optional). parse_recurrence returns {} if rule is missing.
    try:
        rec = event_recurrence.parse_recurrence(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    conflicts = get_conflicts(
        user_id,
        data["plan_date"],
        data["start_time"],
        data["end_time"]
    )

    if conflicts and not force:
        return jsonify({
            "conflict": True,
            "conflicting_events": conflicts
        }), 409

    payload = {
        "user_id": user_id,
        "plan_date": data["plan_date"],
        "start_time": data["start_time"],
        "end_time": data["end_time"],
        "title": data["title"],
        "description": data.get("description", ""),
        "priority": data.get("priority", "medium"),
        "quadrant": data.get("quadrant") or None,
        "reminder_minutes": data.get("reminder_minutes", 10),
    }
    payload.update(rec)

    response1 = post("daily_events", payload, prefer="return=representation")
    created_row = response1[0] if response1 else None

    # If recurring, the master's series_id should equal its own id so
    # the expander can find it and exceptions can reference it.
    if created_row and created_row.get("recurrence_rule"):
        update(
            "daily_events",
            params={"id": f"eq.{created_row['id']}", "user_id": f"eq.{user_id}"},
            json={"series_id": created_row["id"]},
        )
        created_row["series_id"] = created_row["id"]

    # Google sync in the background so the UI returns fast.
    gcal_connected = bool(get("user_google_tokens", {"user_id": f"eq.{user_id}"}) or [])
    if created_row and gcal_connected:
        def _sync():
            try:
                gid = events_cal.sync_create(user_id, created_row)
                if gid:
                    update(
                        "daily_events",
                        params={"id": f"eq.{created_row['id']}", "user_id": f"eq.{user_id}"},
                        json={"google_event_id": gid},
                    )
            except Exception:
                logger.exception("Background Google sync failed on create")
        threading.Thread(target=_sync, daemon=True).start()

    return jsonify({
        "success": True,
        "id": created_row.get("id") if created_row else None,
        "gcal_synced": gcal_connected,  # kicked off; actual result async
        "gcal_error": None,
    })


# ──────────────────────────────────────────────────────────────
# Google Calendar connection status
# ──────────────────────────────────────────────────────────────
@events_bp.route("/api/v2/google-status")
@login_required
def google_status():
    """Tell the client whether the user has a usable Google Calendar link.

    Returns {connected, needs_reauth, login_url}. `connected` is true only
    when the stored refresh token is still valid; `needs_reauth` flips on
    when we have a row but refresh fails (revoked / expired), so the UI
    can distinguish "never linked" from "link is dead, please reconnect".
    """
    user_id = session["user_id"]
    try:
        rows = get("user_google_tokens", params={"user_id": f"eq.{user_id}"}) or []
    except Exception as e:
        logger.warning("google_status lookup failed: %s", e)
        rows = []

    if not rows:
        return jsonify({
            "connected": False,
            "needs_reauth": False,
            "login_url": url_for("events.google_login"),
        })

    # Probe the refresh token. _credentials() refreshes when the access
    # token is expired; a revoked refresh token raises RefreshError.
    try:
        creds = events_cal._credentials(user_id)
        connected = creds is not None
        needs_reauth = not connected
    except RefreshError:
        connected = False
        needs_reauth = True
    except Exception as e:
        logger.warning("google_status token probe failed: %s", e)
        connected = False
        needs_reauth = False

    return jsonify({
        "connected": connected,
        "needs_reauth": needs_reauth,
        "login_url": url_for("events.google_login"),
    })


@events_bp.route("/api/v2/events/<event_id>", methods=["PUT"])
@login_required
def update_event(event_id):
    """Update a calendar event. Supports recurrence edit scopes:

      scope='this'      — only this occurrence (creates an override row)
      scope='following' — this and all future occurrences (splits series)
      scope='all'       — every occurrence (updates the master)
      scope omitted     — legacy single-event update
    """
    user_id = session["user_id"]
    data = request.json or {}
    force = data.get("force", False)
    scope = (data.get("scope") or "").strip().lower()
    occurrence_date = data.get("occurrence_date")  # YYYY-MM-DD the user was looking at

    # Load the target row — either the event_id itself, or if the client
    # passed a master id (from an expanded virtual instance) we still
    # need to handle it. We branch on what we find.
    rows = get("daily_events", params={"id": f"eq.{event_id}", "user_id": f"eq.{user_id}"}) or []
    if not rows:
        return jsonify({"error": "Event not found"}), 404
    row = rows[0]

    # Build the new field values (always validated, even for 'this' scope
    # since the override row will copy these).
    if not data.get("start_time") or not data.get("end_time"):
        return jsonify({"error": "start_time and end_time are required"}), 400
    if data["end_time"] <= data["start_time"]:
        return jsonify({"error": "Invalid time range"}), 400

    try:
        rec = event_recurrence.parse_recurrence(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    core_fields = {
        "start_time": data["start_time"],
        "end_time": data["end_time"],
    }
    if data.get("title") is not None:
        core_fields["title"] = data["title"]
    if "description" in data:
        core_fields["description"] = data.get("description", "")
    if data.get("priority"):
        core_fields["priority"] = data["priority"]
    if "quadrant" in data:
        core_fields["quadrant"] = data.get("quadrant") or None
    if "reminder_minutes" in data:
        core_fields["reminder_minutes"] = int(data.get("reminder_minutes") or 10)

    # ── SCOPE: this occurrence only ─────────────────
    if scope == "this":
        if not occurrence_date:
            return jsonify({"error": "occurrence_date is required for scope='this'"}), 400
        series_id = row.get("series_id") or row.get("id")
        # Insert override row (is_exception=true) OR update an existing one.
        existing_override = get(
            "daily_events",
            params={
                "user_id": f"eq.{user_id}",
                "series_id": f"eq.{series_id}",
                "original_date": f"eq.{occurrence_date}",
                "is_exception": "eq.true",
            },
        ) or []
        if existing_override:
            override_id = existing_override[0]["id"]
            update(
                "daily_events",
                params={"id": f"eq.{override_id}", "user_id": f"eq.{user_id}"},
                json={**core_fields, "plan_date": occurrence_date},
            )
        else:
            override_body = {
                "user_id": user_id,
                "plan_date": occurrence_date,
                "original_date": occurrence_date,
                "series_id": series_id,
                "is_exception": True,
                "is_deleted": False,
                **core_fields,
            }
            post("daily_events", override_body, prefer="return=minimal")

        # Google: patch the single instance.
        master_gid = row.get("google_event_id")
        if master_gid:
            _background_gcal(lambda: events_cal.sync_exception_override(
                user_id, master_gid, occurrence_date, core_fields))
        return jsonify({"success": True, "scope": "this"})

    # ── SCOPE: this and following ───────────────────
    if scope == "following":
        if not occurrence_date:
            return jsonify({"error": "occurrence_date is required for scope='following'"}), 400
        split_date = date.fromisoformat(occurrence_date)

        # 1. Cap the original master so it ends the day before the split.
        series_id = row.get("series_id") or row.get("id")
        original_master = get("daily_events",
                              params={"id": f"eq.{series_id}", "user_id": f"eq.{user_id}"}) or []
        if not original_master:
            return jsonify({"error": "Series master not found"}), 404
        original_master = original_master[0]

        cap = (split_date - timedelta(days=1)).isoformat()
        # If the cap is before the master's start, delete the whole original series.
        if cap < original_master["plan_date"]:
            update("daily_events",
                   params={"id": f"eq.{series_id}", "user_id": f"eq.{user_id}"},
                   json={"is_deleted": True})
            if original_master.get("google_event_id"):
                _background_gcal(lambda: events_cal.sync_delete(
                    user_id, original_master["google_event_id"]))
        else:
            update("daily_events",
                   params={"id": f"eq.{series_id}", "user_id": f"eq.{user_id}"},
                   json={"recurrence_end": cap, "recurrence_count": None})
            # Update google-side master to respect the new end.
            refreshed = get("daily_events", params={"id": f"eq.{series_id}"}) or []
            if refreshed and refreshed[0].get("google_event_id"):
                _background_gcal(lambda: events_cal.sync_update(user_id, refreshed[0]))

        # 2. Create a new master starting from the split date with the new data.
        #    The new series uses the payload's recurrence_* (or defaults to
        #    the same rule as the old master).
        new_rec = rec or {
            "recurrence_rule": original_master.get("recurrence_rule"),
            "recurrence_days": original_master.get("recurrence_days"),
            "recurrence_end": original_master.get("recurrence_end"),
            "recurrence_count": None,
        }
        new_body = {
            "user_id": user_id,
            "plan_date": occurrence_date,
            **core_fields,
            **new_rec,
        }
        new_rows = post("daily_events", new_body, prefer="return=representation")
        if new_rows:
            new_id = new_rows[0]["id"]
            update("daily_events",
                   params={"id": f"eq.{new_id}", "user_id": f"eq.{user_id}"},
                   json={"series_id": new_id})
            _background_gcal(lambda: _create_and_store_gid(user_id, new_id))

        return jsonify({"success": True, "scope": "following"})

    # ── SCOPE: all / default ────────────────────────
    # Updates the row itself. If this was a master of a series, it updates
    # the whole series. If it was a single event, just updates it.
    patch = {**core_fields}
    if rec:
        patch.update(rec)

    update("daily_events",
           params={"id": f"eq.{event_id}", "user_id": f"eq.{user_id}"},
           json=patch)

    refreshed = get("daily_events",
                    params={"id": f"eq.{event_id}", "user_id": f"eq.{user_id}"}) or []
    if refreshed:
        _background_gcal(lambda: events_cal.sync_update(user_id, refreshed[0]))
    return jsonify({"success": True, "scope": scope or "single"})


def _background_gcal(fn):
    """Run a Google-sync call in a daemon thread — keeps the request fast."""
    t = threading.Thread(target=fn, daemon=True)
    t.start()


def _create_and_store_gid(user_id, local_id):
    """Insert on Google, write back the returned id. Called from threads."""
    rows = get("daily_events", params={"id": f"eq.{local_id}", "user_id": f"eq.{user_id}"}) or []
    if not rows:
        return
    gid = events_cal.sync_create(user_id, rows[0])
    if gid:
        update("daily_events",
               params={"id": f"eq.{local_id}", "user_id": f"eq.{user_id}"},
               json={"google_event_id": gid})

@events_bp.route("/api/calendar.ics")
def ical_feed():
    """RFC 5545 ICS feed of the user's daily_events. Read-only.

    Security: doesn't require an active session — it's intended to be
    subscribed to by external calendars (Apple Cal, Outlook, Notion Cal)
    that can't carry session cookies. Auth is via a query-token argument
    derived from the user's id + a server-side secret. Without a valid
    token, returns 401.

    URL shape:
      /api/calendar.ics?u=<user_id>&t=<token>

    Date window: rolling -30d to +180d to keep the file small.
    """
    import hmac
    import hashlib
    import os as _os
    from datetime import date as _date, timedelta as _td, datetime as _dt
    from flask import Response

    user_id = (request.args.get("u") or "").strip()
    token = (request.args.get("t") or "").strip()
    if not user_id or not token:
        return ("Missing u or t", 401)

    secret = (_os.environ.get("ICAL_FEED_SECRET")
              or _os.environ.get("FLASK_SECRET_KEY") or "")
    expected = hmac.new(secret.encode(), user_id.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(token, expected):
        return ("Invalid token", 401)

    today = _date.today()
    start = today - _td(days=30)
    end = today + _td(days=180)

    rows = get(
        "daily_events",
        params={
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
            "and": f"(plan_date.gte.{start.isoformat()},plan_date.lte.{end.isoformat()})",
            "select": "id,plan_date,start_time,end_time,title,description,status",
            "order": "plan_date.asc",
            "limit": 1000,
        },
    ) or []

    def _esc_ics(s):
        if s is None: return ""
        return (str(s).replace("\\", "\\\\")
                       .replace(",", "\\,")
                       .replace(";", "\\;")
                       .replace("\n", "\\n"))

    def _to_dt_utc(date_iso, time_hhmm):
        if not time_hhmm:
            return None
        try:
            return _dt.fromisoformat(f"{date_iso}T{time_hhmm}:00").strftime("%Y%m%dT%H%M%S")
        except Exception:
            return None

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//DailyPlanner//Personal//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:DailyPlanner",
        "X-WR-TIMEZONE:UTC",
    ]
    now_stamp = _dt.utcnow().strftime("%Y%m%dT%H%M%SZ")
    for r in rows:
        plan_date = r.get("plan_date")
        title = (r.get("title") or "").strip() or "(untitled)"
        desc = r.get("description") or ""
        start_dt = _to_dt_utc(plan_date, r.get("start_time"))
        end_dt = _to_dt_utc(plan_date, r.get("end_time"))
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{r.get('id')}@dailyplanner")
        lines.append(f"DTSTAMP:{now_stamp}")
        if start_dt and end_dt:
            lines.append(f"DTSTART:{start_dt}")
            lines.append(f"DTEND:{end_dt}")
        else:
            # All-day event
            ymd = (plan_date or "").replace("-", "")
            if ymd:
                lines.append(f"DTSTART;VALUE=DATE:{ymd}")
                lines.append(f"DTEND;VALUE=DATE:{ymd}")
        lines.append(f"SUMMARY:{_esc_ics(title)}")
        if desc:
            lines.append(f"DESCRIPTION:{_esc_ics(desc)}")
        if r.get("status") == "done":
            lines.append("STATUS:CONFIRMED")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    body = "\r\n".join(lines) + "\r\n"
    return Response(body, mimetype="text/calendar; charset=utf-8")


@events_bp.route("/api/calendar/feed-url")
@login_required
def ical_feed_url():
    """Returns the user's personal feed URL with HMAC token.
    Settings page can show this so the user knows what to subscribe."""
    import hmac
    import hashlib
    import os as _os
    user_id = session["user_id"]
    secret = (_os.environ.get("ICAL_FEED_SECRET")
              or _os.environ.get("FLASK_SECRET_KEY") or "")
    token = hmac.new(secret.encode(), user_id.encode(), hashlib.sha256).hexdigest()[:32]
    return jsonify({"url": f"/api/calendar.ics?u={user_id}&t={token}"})


@events_bp.route("/api/v2/events/<event_id>/toggle-status", methods=["POST"])
@login_required
def toggle_event_status(event_id):
    """Lightweight status toggle for a daily_events row.

    Body: { "status": "done" | "open" | "in_progress" }

    Used by the weekly summary's in-row strike-off button. The full PUT
    endpoint requires start_time/end_time/recurrence parsing — overkill
    for a single status flip.
    """
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}
    status = (data.get("status") or "").strip()
    if status not in ("done", "open", "in_progress", "skipped"):
        return jsonify({"error": "invalid status"}), 400

    rows = get(
        "daily_events",
        params={"id": f"eq.{event_id}", "user_id": f"eq.{user_id}", "select": "id"},
    ) or []
    if not rows:
        return jsonify({"error": "Event not found"}), 404

    update(
        "daily_events",
        params={"id": f"eq.{event_id}", "user_id": f"eq.{user_id}"},
        json={"status": status},
    )
    return ("", 204)


@events_bp.route("/api/v2/events/<event_id>", methods=["DELETE"])
@login_required
def delete_event(event_id):
    """Delete an event. Query params:

      ?scope=this&occurrence_date=YYYY-MM-DD   — skip this occurrence only
      ?scope=following&occurrence_date=...     — end series the day before this
      ?scope=all                                — delete the whole series / single event
      scope omitted                            — legacy single-event delete
    """
    user_id = session["user_id"]
    scope = (request.args.get("scope") or "").strip().lower()
    occurrence_date = request.args.get("occurrence_date")

    rows = get("daily_events", params={"id": f"eq.{event_id}", "user_id": f"eq.{user_id}"}) or []
    if not rows:
        return jsonify({"error": "Event not found"}), 404
    row = rows[0]

    # ── SCOPE: this occurrence only ─────────────────
    if scope == "this":
        if not occurrence_date:
            return jsonify({"error": "occurrence_date required"}), 400
        series_id = row.get("series_id") or row.get("id")
        # Insert a skip row (idempotent via UNIQUE constraint).
        try:
            post("event_exceptions", {
                "series_id": series_id,
                "user_id": user_id,
                "exception_date": occurrence_date,
                "reason": "deleted",
            }, prefer="return=minimal")
        except Exception:
            # Already exists — that's fine.
            pass

        # If there's an override row for this date, soft-delete it.
        overrides = get("daily_events", params={
            "user_id": f"eq.{user_id}",
            "series_id": f"eq.{series_id}",
            "original_date": f"eq.{occurrence_date}",
            "is_exception": "eq.true",
        }) or []
        for o in overrides:
            update("daily_events",
                   params={"id": f"eq.{o['id']}", "user_id": f"eq.{user_id}"},
                   json={"is_deleted": True})

        # Google: cancel the single instance.
        if row.get("google_event_id"):
            _background_gcal(lambda: events_cal.sync_exception_cancel(
                user_id, row["google_event_id"], occurrence_date, row.get("start_time")))
        return jsonify({"ok": True, "scope": "this"})

    # ── SCOPE: this and following ───────────────────
    if scope == "following":
        if not occurrence_date:
            return jsonify({"error": "occurrence_date required"}), 400
        split_date = date.fromisoformat(occurrence_date)
        series_id = row.get("series_id") or row.get("id")
        cap = (split_date - timedelta(days=1)).isoformat()

        master = get("daily_events",
                     params={"id": f"eq.{series_id}", "user_id": f"eq.{user_id}"}) or []
        if not master:
            return jsonify({"error": "Series master not found"}), 404
        master = master[0]

        if cap < master["plan_date"]:
            # Deleting everything — soft-delete the master.
            update("daily_events",
                   params={"id": f"eq.{series_id}", "user_id": f"eq.{user_id}"},
                   json={"is_deleted": True})
            if master.get("google_event_id"):
                _background_gcal(lambda: events_cal.sync_delete(user_id, master["google_event_id"]))
        else:
            update("daily_events",
                   params={"id": f"eq.{series_id}", "user_id": f"eq.{user_id}"},
                   json={"recurrence_end": cap, "recurrence_count": None})
            refreshed = get("daily_events", params={"id": f"eq.{series_id}"}) or []
            if refreshed and refreshed[0].get("google_event_id"):
                _background_gcal(lambda: events_cal.sync_update(user_id, refreshed[0]))
        return jsonify({"ok": True, "scope": "following"})

    # ── SCOPE: all (default for recurring masters) ──
    update("daily_events",
           params={"id": f"eq.{event_id}", "user_id": f"eq.{user_id}"},
           json={"is_deleted": True})

    if row.get("google_event_id"):
        _background_gcal(lambda: events_cal.sync_delete(user_id, row["google_event_id"]))

    return jsonify({"ok": True, "scope": scope or "single"})

@events_bp.post("/api/v2/events/resync")
@login_required
def resync_unsynced_events():
    """Backfill daily_events rows missing a google_event_id to Google.

    Use case: token was revoked so the background sync silently skipped a
    batch of newly created events. After reconnecting via /google-login,
    POST here to push those rows up.
    """
    user_id = session["user_id"]

    token_rows = get("user_google_tokens", params={"user_id": f"eq.{user_id}"}) or []
    if not token_rows:
        return jsonify({
            "error": "Not connected to Google Calendar",
            "login_url": url_for("events.google_login"),
        }), 400

    try:
        creds = events_cal._credentials(user_id)
    except RefreshError:
        return jsonify({
            "error": "Google token is revoked or expired — please reconnect",
            "needs_reauth": True,
            "login_url": url_for("events.google_login"),
        }), 400
    if creds is None:
        return jsonify({
            "error": "Could not load Google credentials",
            "login_url": url_for("events.google_login"),
        }), 400

    params = {
        "user_id": f"eq.{user_id}",
        "is_deleted": "eq.false",
        "google_event_id": "is.null",
    }
    # ?from=YYYY-MM-DD: only events on or after that day (so a button press
    # never floods Google with months of old entries).
    since = (request.args.get("from") or "").strip()
    if since:
        try:
            params["plan_date"] = f"gte.{date.fromisoformat(since).isoformat()}"
        except ValueError:
            return jsonify({"error": "Invalid from date"}), 400
    rows = get("daily_events", params=params) or []

    # Skip per-occurrence override rows — they patch existing Google
    # instances via sync_exception_override, not a fresh insert.
    candidates = [r for r in rows if not r.get("is_exception")]

    synced = 0
    failed = 0
    for r in candidates:
        gid = events_cal.sync_create(user_id, r)
        if gid:
            update(
                "daily_events",
                params={"id": f"eq.{r['id']}", "user_id": f"eq.{user_id}"},
                json={"google_event_id": gid},
            )
            synced += 1
        else:
            failed += 1

    return jsonify({
        "total": len(candidates),
        "synced": synced,
        "failed": failed,
    })


@events_bp.post("/api/v2/smart-create")
@login_required
def smart_create():
    data = request.json or {}

    text = data.get("text", "").strip()
    date = safe_date_from_string(data.get("date"))

    created = []
    failed = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        try:
            parsed = parse_planner_input(line, date)

            payload = {
                "plan_date": str(parsed["date"]),
                "start_time": parsed["start"].strftime("%H:%M"),
                "end_time": parsed["end"].strftime("%H:%M"),
                "title": parsed["title"],
            }
            user_id = session["user_id"]
            result, status = insert_event(user_id, payload)

            if status == 200:
                created.append(payload)
            else:
                failed.append({
                    "line": raw_line,
                    "error": result
                })

        except Exception as e:
            failed.append({
                "line": raw_line,
                "error": str(e)
            })

    return jsonify({
        "status": "ok",
        "created_count": len(created),
        "failed_count": len(failed),
        "failed": failed
    })
@events_bp.post("/api/v2/ai-parse-events")
@login_required
def ai_parse_events():
    """Use AI to parse natural language into events, then create them."""
    data = request.json or {}
    text = data.get("text", "").strip()
    plan_date = data.get("date") or safe_date_from_string(None)

    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        from services.ai_service import call_gemini

        prompt = f"""Parse the following text into calendar events for date {plan_date}.
Return ONLY a JSON array of objects, each with: title, start_time (HH:MM 24h), end_time (HH:MM 24h).
If duration is mentioned but no end time, calculate end_time from start + duration.
If time is in 12h format (2pm, 3:30 AM), convert to 24h.
If no time is mentioned, skip that line.
Each event on a separate line in the input.

Input:
{text}

Output JSON array only, no markdown, no explanation:"""

        ai_response = call_gemini(prompt)

        if not ai_response or ai_response.startswith("AI service"):
            return jsonify({"error": "AI unavailable", "created_count": 0}), 503

        # Parse JSON from AI response
        import json
        # Clean markdown wrapping if present
        cleaned = ai_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        events_list = json.loads(cleaned)
        if not isinstance(events_list, list):
            events_list = [events_list]

        user_id = session["user_id"]
        created = 0

        for ev in events_list:
            title = ev.get("title", "").strip()
            start = ev.get("start_time", "").strip()
            end = ev.get("end_time", "").strip()

            if not title or not start or not end:
                continue

            # Validate time format
            try:
                int(start.split(":")[0])
                int(end.split(":")[0])
            except (ValueError, IndexError):
                continue

            try:
                result, status = insert_event(user_id, {
                    "plan_date": str(plan_date),
                    "start_time": start,
                    "end_time": end,
                    "title": title,
                    "description": "",
                    "priority": "medium",
                }, force=True)
                if status == 200:
                    created += 1
            except Exception as e:
                logger.warning("AI event create failed: %s", e)

        return jsonify({"status": "ok", "created_count": created})

    except json.JSONDecodeError:
        return jsonify({"error": "AI returned invalid format", "created_count": 0}), 500
    except Exception as e:
        logger.error("AI parse events error: %s", e)
        return jsonify({"error": str(e), "created_count": 0}), 500


@events_bp.route('/google-login')
@login_required
def google_login():
    flow = Flow.from_client_config(
    {
        "web": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    },
    scopes=SCOPES,
    redirect_uri=url_for('events.oauth2callback', _external=True)
    )

    authorization_url, state = flow.authorization_url(
    access_type='offline',
    include_granted_scopes='true',
    prompt='consent'
    )

    # Persist BOTH the state token AND the PKCE code_verifier so the
    # callback can rebuild the Flow correctly. Modern google-auth-oauthlib
    # (>=1.0) enables PKCE by default — without restoring code_verifier,
    # Google's token endpoint returns: "invalid_grant: Missing code verifier".
    session['state'] = state
    session['google_oauth_code_verifier'] = flow.code_verifier
    return redirect(authorization_url)

def credentials_to_dict(credentials):
    return {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes
    }
@events_bp.route('/oauth2callback')
@login_required
def oauth2callback():

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=SCOPES,
        state=session.get("state"),
        redirect_uri=url_for("events.oauth2callback", _external=True)
    )

    # Restore the PKCE code_verifier that was generated when the auth URL
    # was built in /google-login. Without this, Google rejects the token
    # exchange with: "invalid_grant: Missing code verifier".
    code_verifier = session.pop("google_oauth_code_verifier", None)
    if code_verifier:
        flow.code_verifier = code_verifier

    # Google's redirect URL may come in over HTTP behind Render's proxy even
    # though the actual public URL is HTTPS. Rewrite it so oauthlib's strict
    # HTTPS check doesn't fail, and so the state/PKCE validation sees the
    # canonical URL.
    authorization_response = request.url
    if authorization_response.startswith("http://"):
        authorization_response = "https://" + authorization_response[len("http://"):]

    try:
        flow.fetch_token(authorization_response=authorization_response)
    except Exception as e:
        logger.exception("oauth2callback: token exchange failed")
        return (
            "<h2>Google Calendar connection failed</h2>"
            f"<p>{e}</p>"
            "<p><a href='/google-login'>Try again</a> or "
            "<a href='/calendar'>back to calendar</a>.</p>",
            400,
        )

    credentials = flow.credentials

    creds_dict = credentials_to_dict(credentials)
    user_id = session["user_id"]

    # 🔥 MANUAL UPSERT (since you don't use supabase upsert)
    existing = get(
        "user_google_tokens",
        {"user_id": f"eq.{user_id}"}
    )

    if existing:
        update(
            "user_google_tokens",
            params={"user_id": f"eq.{user_id}"},
            json={
                "access_token": creds_dict["token"],
                "refresh_token": creds_dict["refresh_token"],
                "token_uri": creds_dict["token_uri"],
                "client_id": creds_dict["client_id"],
                "client_secret": creds_dict["client_secret"],
                "scopes": ",".join(creds_dict["scopes"])
            }
        )
    else:
        post(
            "user_google_tokens",
            {
                "user_id": user_id,
                "access_token": creds_dict["token"],
                "refresh_token": creds_dict["refresh_token"],
                "token_uri": creds_dict["token_uri"],
                "client_id": creds_dict["client_id"],
                "client_secret": creds_dict["client_secret"],
                "scopes": ",".join(creds_dict["scopes"])
            }
        )

    return redirect("/planner-v2")

def insert_google_event(event_row):
    user_id = session.get("user_id")
    if not user_id:
        return None
    rows = get(
        "user_google_tokens",
        {"user_id": f"eq.{user_id}"}
    )

    if not rows:
        return None

    row = rows[0]

    credentials = Credentials(
        token=row["access_token"],
        refresh_token=row["refresh_token"],
        token_uri=row["token_uri"],
        client_id=row["client_id"],
        client_secret=row["client_secret"],
        scopes=row["scopes"].split(",")
    )

    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

        update(
            "user_google_tokens",
            params={"user_id": f"eq.{user_id}"},
            json={
                "access_token": credentials.token,
                "updated_at": datetime.utcnow().isoformat()
            }
        )

    service = build("calendar", "v3", credentials=credentials)

    start_iso = build_google_datetime(event_row["plan_date"], event_row["start_time"])
    end_iso = build_google_datetime(event_row["plan_date"], event_row["end_time"])

    event_body = {
        "summary": event_row["title"],
        "description": event_row.get("description", ""),
        "start": {
            "dateTime": start_iso,
            "timeZone": "Asia/Kolkata"
        },
        "end": {
            "dateTime": end_iso,
            "timeZone": "Asia/Kolkata"
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": int(event_row.get("reminder_minutes") or 10)}
            ]
        }
    }

    created = service.events().insert(
        calendarId="primary",
        body=event_body
    ).execute()

    return created.get("id")

def insert_event(user_id, data, force=False):
    if data["end_time"] <= data["start_time"]:
        return {"error": "Invalid time range"}, 400

    conflicts = get_conflicts(
        user_id,
        data["plan_date"],
        data["start_time"],
        data["end_time"]
    )

    if conflicts and not force:
        return {
            "conflict": True,
            "conflicting_events": conflicts
        }, 409

    response1 = post("daily_events", {
        "user_id": user_id,
        "plan_date": data["plan_date"],
        "start_time": data["start_time"],
        "end_time": data["end_time"],
        "title": data["title"],
        "description": data.get("description", ""),
        "priority": data.get("priority", "medium"),
        "reminder_minutes": data.get("reminder_minutes", 10),
    })

    created_row = response1[0] if response1 else None

    # 🔥 GOOGLE AUTO SYNC HERE
    if created_row:
        try:
            google_id = insert_google_event(created_row)

            if google_id:
                update(
                    "daily_events",
                    params={"id": f"eq.{created_row['id']}"},
                    json={"google_event_id": google_id}
                )
        except Exception as e:
            logger.warning("Google sync failed on insert: %s", e)

    return {"success": True}, 200