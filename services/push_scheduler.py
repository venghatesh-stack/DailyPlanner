"""
Background scheduler that sends Web Push reminders for checklist items
whose reminder times match the user's local "now".

Design:
  * Runs every minute (APScheduler BackgroundScheduler).
  * For each user that has at least one active push subscription, we
    resolve their IANA timezone (cached in-process) and compute the
    local HH:MM and weekday.
  * For every checklist_reminder_times row whose time matches the local
    HH:MM and whose parent's schedule applies to today, we attempt to
    insert a row into checklist_reminder_log keyed on (item_id,
    sent_date, reminder_time) so each fire is independently deduped.
  * The unique constraint makes this safe across multiple gunicorn
    workers — only the first insert wins, and only that worker calls
    push_service.send_to_user().
  * Items with no child reminder_times rows fall back to the legacy
    checklist_items.reminder_time column for backwards compat.

The scheduler starts once inside create_app(); a module-level flag
prevents duplicate starts when the factory is invoked multiple times
(tests, reloads).
"""
import atexit
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from requests.exceptions import HTTPError

from services import announcer_push
from services import color_note_reminders
from services import loud
from services import push_service
from services import review_reminders
from supabase_client import get, post, update

logger = logging.getLogger(__name__)

_started = False
_scheduler = None

_TZ_CACHE: dict[str, ZoneInfo] = {}


def _resolve_tz(name):
    if not name:
        return ZoneInfo("Asia/Kolkata")
    cached = _TZ_CACHE.get(name)
    if cached:
        return cached
    try:
        z = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        z = ZoneInfo("Asia/Kolkata")
    _TZ_CACHE[name] = z
    return z


def _schedule_applies_today(schedule, schedule_days, weekday, today=None):
    """Does this schedule fire on `today`?

    THE LOGIC MOVED to services/checklist_schedule.py, unchanged, because
    three places needed it and the copies had drifted — the Day Board's had
    no branch for `weekdays` or `weekends` and showed those items every day.
    Anything reporting "you missed this" has to agree with the thing that
    reminded you.

    The signature is kept so callers do not change. `weekday` is now only
    used when `today` is absent, which no current caller does; the shared
    function derives the day from the date itself, since deriving it in the
    caller is exactly how the two versions came to disagree.
    """
    from services.checklist_schedule import applies_on

    if today is None:
        # Older callers passed a weekday and no date. Monthly and one-shot
        # schedules cannot be evaluated without the date, and returning
        # False for them is the pre-existing behaviour (no false positives).
        if schedule in ("monthly_dow", "monthly_dom", "once"):
            return False
        dow = (weekday + 1) % 7
        if schedule == "daily" or not schedule:
            return True
        if schedule == "weekdays":
            return dow in (1, 2, 3, 4, 5)
        if schedule == "weekends":
            return dow in (0, 6)
        if schedule == "custom":
            allowed = {int(x) for x in (schedule_days or "").split(",")
                       if x.strip().lstrip("-").isdigit()}
            return dow in allowed
        return False

    return applies_on(schedule, schedule_days, today)


def _users_with_active_subscriptions():
    subs = get(
        "push_subscriptions",
        {"is_active": "eq.true", "select": "user_id"},
    ) or []
    return {s["user_id"] for s in subs}


def _user_tz_name(user_id):
    # If the `timezone` column isn't present on this Supabase project
    # yet (e.g. migration not applied), fall back silently instead of
    # crashing every minute in the scheduler.
    try:
        rows = get("users", {"id": f"eq.{user_id}", "select": "timezone"}) or []
    except Exception:
        return "Asia/Kolkata"
    if rows:
        return rows[0].get("timezone") or "Asia/Kolkata"
    return "Asia/Kolkata"


def _due_fires_for_user(user_id, local_hhmm, local_weekday, today_iso):
    """Return a list of (item, reminder_time) tuples that should fire
    right now for this user. reminder_time is the full HH:MM:SS string
    (or None for the legacy items-only fallback path)."""
    from datetime import date as _date

    today = _date.fromisoformat(today_iso)

    items = get(
        "checklist_items",
        {
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
        },
    ) or []
    if not items:
        return []

    # PER-ITEM MUTE. Filtered in Python rather than added to the query above,
    # deliberately: this column arrives with MIGRATION_ANNOUNCER_MUTES.sql,
    # and get() has no PGRST204 retry — a query naming a column the live
    # database has not got yet would 400 and silence EVERY reminder for
    # everyone. Absent column reads as None, which is not muted.
    muted = [it for it in items if it.get("notify_muted")]
    if muted:
        logger.info("push: %d muted item(s) skipped for user %s",
                    len(muted), user_id)
    items = [it for it in items if not it.get("notify_muted")]
    if not items:
        return []
    items_by_id = {it["id"]: it for it in items}

    times = get(
        "checklist_reminder_times",
        {"user_id": f"eq.{user_id}"},
    ) or []
    items_with_children = {r["item_id"] for r in times}

    def _ok(it):
        if not _schedule_applies_today(it.get("schedule"), it.get("schedule_days"), local_weekday, today):
            return False
        end_str = it.get("recurrence_end")
        if end_str:
            try:
                if _date.fromisoformat(end_str) < today:
                    return False
            except Exception:
                pass
        return True

    due = []

    for r in times:
        rt_full = r.get("reminder_time") or ""
        if rt_full[:5] != local_hhmm:
            continue
        it = items_by_id.get(r["item_id"])
        if not it or not _ok(it):
            continue
        due.append((it, rt_full))

    # Legacy fallback: items that still rely on items.reminder_time and
    # have no child rows yet (shouldn't happen after migration but covers
    # any data we haven't normalized).
    for it in items:
        if it["id"] in items_with_children:
            continue
        rt = (it.get("reminder_time") or "")
        if rt[:5] != local_hhmm:
            continue
        if not _ok(it):
            continue
        due.append((it, rt))

    return due


def _claim_send_slot(item_id, user_id, sent_date, reminder_time):
    """Insert a reminder_log row; returns True if *this* worker wins.

    If another worker already inserted the same (item_id, sent_date,
    reminder_time), Postgres returns 409 and we skip sending."""
    payload = {"item_id": item_id, "user_id": user_id, "sent_date": sent_date}
    if reminder_time:
        payload["reminder_time"] = reminder_time
    try:
        post("checklist_reminder_log", payload, prefer="return=minimal")
        return True
    except HTTPError as e:
        if e.response is not None and e.response.status_code == 409:
            return False
        logger.exception("reminder_log insert failed for item %s", item_id)
        return False


def _refresh_day_board_pins(user_id, now_local):
    """Refresh a pinned Day Board summary — but only when it would actually
    look different.

    THE OBVIOUS DESIGN IS A TIMER, AND IT IS THE WRONG ONE. "Re-send every 15
    minutes" pushes an identical notification most of the time, because a day
    does not change every quarter hour, and each of those costs battery and
    push quota to tell the user nothing. So this hashes the summary TEXT and
    sends only when the hash moves — when an event starts, when a task is
    ticked, when the next thing becomes the current thing.

    Three guards on top of that:
      * a WINDOW, because a summary that refreshes at 3am is a notification
        that wakes you to say nothing;
      * a THROTTLE FLOOR, so ticking five checklist items in a row is one
        refresh rather than five;
      * a DATE ROLLOVER force-send, so the first refresh of a new morning
        always lands even if today's text happens to match yesterday's.
    """
    from routes import day_board

    rows = get("day_board_pins",
               {"user_id": f"eq.{user_id}", "is_active": "eq.true"}) or []
    if not rows:
        return
    pin = rows[0]

    start_h = pin.get("start_hour", 7)
    end_h = pin.get("end_hour", 22)
    if not (start_h <= now_local.hour <= end_h):
        return

    today = now_local.date()
    rolled_over = (pin.get("pinned_date") or "") != today.isoformat()

    # Throttle floor — checked before doing any of the query work below.
    last_sent = pin.get("last_sent_at")
    if last_sent and not rolled_over:
        try:
            prev = datetime.fromisoformat(str(last_sent).replace("Z", "+00:00"))
            gap = (now_local - prev.astimezone(now_local.tzinfo)).total_seconds() / 60
            if gap < (pin.get("min_interval_minutes") or 10):
                return
        except (ValueError, TypeError):
            pass                      # unparseable timestamp: treat as due

    summary = day_board.build_summary(
        user_id, today, now_minutes=now_local.hour * 60 + now_local.minute)
    sig = day_board.signature(summary)

    if sig == pin.get("last_signature") and not rolled_over:
        return                        # nothing the user would see has changed

    sent, _failed = day_board.send_pin(user_id, summary)
    if sent:
        update("day_board_pins", params={"user_id": f"eq.{user_id}"},
               json={"last_signature": sig,
                     "last_sent_at": now_local.isoformat(),
                     "pinned_date": today.isoformat()})


def tick():
    """Called every minute. Safe to call manually for debugging."""
    try:
        user_ids = _users_with_active_subscriptions()
    except Exception:
        logger.exception("Could not list active push subscriptions")
        return

    if not user_ids:
        return

    for user_id in user_ids:
        try:
            tz = _resolve_tz(_user_tz_name(user_id))
            now_local = datetime.now(tz)
            hhmm = now_local.strftime("%H:%M")
            weekday = now_local.weekday()  # Mon=0..Sun=6
            today = now_local.date().isoformat()

            # Pinned Day Board first, and in its own try: a failure here
            # (missing table, bad row) must not stop the checklist reminders
            # below, which are the notifications with an actual deadline.
            try:
                _refresh_day_board_pins(user_id, now_local)
            except Exception:
                logger.debug("Day Board pin refresh skipped for %s", user_id,
                             exc_info=True)

            # ANNOUNCEMENTS. Speech needs the page visible, so a locked
            # phone hears nothing — a browser limitation, not something we
            # can engineer around. A notification is the only thing that
            # reaches a locked screen, so each announcement fires as one
            # too. In its own try for the same reason as the pins above.
            try:
                for a_item, a_time in announcer_push.fires_for_user(
                        user_id, now_local):
                    cid = a_item.get("client_id")
                    if not announcer_push.claim(user_id, cid, today, a_time):
                        continue
                    body, when = announcer_push.spoken_label(a_item, a_time)
                    sent, failed = push_service.send_to_user(
                        user_id,
                        title=f"🔔 {when}",
                        body=body,
                        tag=f"announce-{cid}-{a_time.replace(':', '')}",
                        url="/day-board",
                    )
                    # A FIRE THAT REACHED NOBODY IS THE "it did not go off"
                    # REPORT. The claim row proves the scheduler ran; it
                    # proves nothing about delivery, and treating the two as
                    # the same is how "it fired" and "you heard it" got
                    # confused. Say so where the user can see it.
                    # The claim proves the scheduler ran; this is the only
                    # record of whether anything received it.
                    announcer_push.record_delivery(
                        user_id, cid, today, a_time, sent, failed)
                    if not sent:
                        loud.bailed(
                            "announcement notification",
                            "fired but reached no device — no active push "
                            "subscription",
                            at=a_time, failed=failed)
            except Exception:
                logger.debug("announcement push skipped for %s", user_id,
                             exc_info=True)

            # Color Notes reminders (one-off or repeating).
            try:
                color_note_reminders.fire(user_id, now_local)
            except Exception:
                logger.debug("color note reminder skipped for %s", user_id,
                             exc_info=True)

            # Spaced-repetition reviews due on Random thoughts (08:00, 20:00).
            try:
                review_reminders.fire(user_id, now_local)
            except Exception:
                logger.debug("review reminder skipped for %s", user_id,
                             exc_info=True)

            fires = _due_fires_for_user(user_id, hhmm, weekday, today)
            for it, rt in fires:
                if not _claim_send_slot(it["id"], user_id, today, rt):
                    continue
                title = "✓ Daily Checklist"
                body = it["name"]
                # Use the fire's HH:MM in the tag so the same item firing
                # at different times produces distinct notifications.
                tag_suffix = (rt or "")[:5].replace(":", "")
                push_service.send_to_user(
                    user_id,
                    title=title,
                    body=body,
                    url="/checklist",
                    tag=f"cl-{it['id']}-{tag_suffix}" if tag_suffix else f"cl-{it['id']}",
                )
        except Exception:
            logger.exception("Scheduler tick failed for user %s", user_id)


def start(app=None):
    """Start the background scheduler exactly once per process."""
    global _started, _scheduler
    if _started:
        return

    # Skip scheduler when running under a fork-spawn test runner or when
    # reminders are explicitly disabled — handy for local dev too.
    if os.environ.get("DISABLE_PUSH_SCHEDULER") == "1":
        logger.info("Push scheduler disabled via DISABLE_PUSH_SCHEDULER=1")
        _started = True
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("APScheduler not installed — push reminders disabled")
        _started = True
        return

    sched = BackgroundScheduler(daemon=True, timezone="UTC")
    sched.add_job(tick, "cron", second=5, id="checklist_push_tick", max_instances=1, coalesce=True)
    sched.start()

    atexit.register(lambda: sched.shutdown(wait=False))
    _scheduler = sched
    _started = True
    logger.info("Push reminder scheduler started")
