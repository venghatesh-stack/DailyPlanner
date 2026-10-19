"""Link Color Notes reminders to the Daily Checklist (and so to Google Calendar).

A note with a reminder gets one checklist item, in the "Color Notes" group,
with the same date/time and repeat. The checklist already does two things
well that a note on its own did not:

  * it mirrors every reminder to Google Calendar with a popup at the exact
    time (services/checklist_calendar_service.py). Calendar alerts are
    treated as first-class by Android, so they pop up even on phones whose
    vendor quietly demotes web notifications;
  * it puts the reminder on the day's list, where it can be ticked off.

Repeat mapping (checklist schedule):
    none    -> once         schedule_days = local date (YYYY-MM-DD)
    daily   -> daily
    weekly  -> custom       schedule_days = weekday, Sun=0..Sat=6
    monthly -> monthly_dom  schedule_days = day of month (31 = last day)
    yearly  -> once         this year's date; moved on when it fires

The note keeps checklist_item_id. Removing the reminder, archiving, or
trashing the note removes the checklist item and its Calendar events.
"""
import logging
from datetime import datetime

from supabase_client import delete as sb_delete
from supabase_client import get, post, update

logger = logging.getLogger(__name__)

NOTES = "color_notes"
ITEMS = "checklist_items"
GROUP = "Color Notes"


def _tz(user_id):
    from services import push_scheduler
    return push_scheduler._resolve_tz(push_scheduler._user_tz_name(user_id))


def _label(note):
    title = (note.get("title") or "").strip()
    if not title:
        if note.get("kind") == "checklist":
            first = next((i.get("text", "").strip() for i in (note.get("items") or [])
                          if (i.get("text") or "").strip()), "")
            title = first or "Checklist note"
        else:
            title = " ".join((note.get("body") or "").split())[:60] or "Note"
    return "\U0001F4DD " + title[:120]


def _details(note):
    from services.color_note_reminders import preview
    text = preview(note, limit=400)
    return (text + "\n\n" if text else "") + "From Color Notes"


def plan(note, tz):
    """The checklist fields for this note's reminder, or None if it should
    have no checklist item."""
    if (not note.get("remind_at") or note.get("deleted_at") or note.get("purged_at")
            or note.get("is_archived")):
        return None
    when = datetime.fromisoformat(str(note["remind_at"]).replace("Z", "+00:00")).astimezone(tz)
    repeat = note.get("remind_repeat") or "none"
    if repeat == "daily":
        schedule, days = "daily", None
    elif repeat == "weekly":
        schedule, days = "custom", str((when.weekday() + 1) % 7)
    elif repeat == "monthly":
        schedule, days = "monthly_dom", str(when.day)
    else:                                   # none, yearly
        schedule, days = "once", when.date().isoformat()
    h = when.hour
    return {
        "name": _label(note),
        "notes": _details(note),
        "schedule": schedule,
        "schedule_days": days,
        "time_of_day": "morning" if h < 12 else "afternoon" if h < 17 else "evening",
        "reminder_time": when.strftime("%H:%M:00"),
        "group_name": GROUP,
    }


def _remove_item(user_id, item_id):
    from routes import checklist as ck
    rows = get(ITEMS, {"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"}) or []
    children = get("checklist_reminder_times", {"item_id": f"eq.{item_id}", "user_id": f"eq.{user_id}"}) or []
    update(ITEMS, {"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
           {"is_deleted": True, "google_event_id": None})
    sb_delete("checklist_reminder_times", {"item_id": f"eq.{item_id}", "user_id": f"eq.{user_id}"})
    events = [c.get("google_event_id") for c in children if c.get("google_event_id")]
    if rows and rows[0].get("google_event_id"):
        events.append(rows[0]["google_event_id"])
    if events:
        import threading

        def _cleanup():
            for ev in events:
                try:
                    ck.cal_sync.delete_from_calendar(user_id, ev)
                except Exception:
                    logger.debug("calendar delete failed for %s", ev, exc_info=True)
        threading.Thread(target=_cleanup, daemon=True).start()


def sync(user_id, note):
    """Create, update or remove the checklist item for `note`. Returns the
    checklist item id now linked (or None). Never raises."""
    try:
        return _sync(user_id, note)
    except Exception:
        logger.exception("color note -> checklist sync failed for %s", note.get("id"))
        return note.get("checklist_item_id")


def _sync(user_id, note):
    from routes import checklist as ck
    want = plan(note, _tz(user_id))
    item_id = note.get("checklist_item_id")
    current = None
    if item_id:
        rows = get(ITEMS, {"id": f"eq.{item_id}", "user_id": f"eq.{user_id}", "is_deleted": "eq.false"}) or []
        current = rows[0] if rows else None

    if want is None:
        if current:
            _remove_item(user_id, item_id)
        if item_id:
            update(NOTES, {"id": f"eq.{note['id']}", "user_id": f"eq.{user_id}"}, {"checklist_item_id": None})
        return None

    times = [want.pop("reminder_time")]
    if current is None:
        rows = post(ITEMS, dict(want, user_id=user_id, reminder_time=times[0], position=9999,
                                is_deleted=False), prefer="return=representation") or []
        if not rows:
            return None
        row = rows[0]
        added, removed = ck._reconcile_reminder_times(user_id, row["id"], times)
        if added or removed:
            ck._sync_children_calendar_async(user_id, row, added, removed)
        update(NOTES, {"id": f"eq.{note['id']}", "user_id": f"eq.{user_id}"}, {"checklist_item_id": row["id"]})
        return row["id"]

    changed = {k: v for k, v in want.items() if (current.get(k) or None) != (v or None)}
    if (str(current.get("reminder_time") or "")[:8]) != times[0]:
        changed["reminder_time"] = times[0]
    if changed:
        update(ITEMS, {"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"}, changed)
        current.update(changed)
    added, removed = ck._reconcile_reminder_times(user_id, item_id, times)
    if added or removed:
        ck._sync_children_calendar_async(user_id, current, added, removed)
    elif {"name", "schedule", "schedule_days"} & set(changed):
        # Same time, but the Calendar event's title or repeat changed.
        ck._resync_all_children_calendar_async(user_id, current)
    return item_id


def add_today(user_id, note):
    """'Add to today's checklist' for a note without a reminder: a one-off,
    anytime item for today. Returns the new item id."""
    today = datetime.now(_tz(user_id)).date().isoformat()
    rows = post(ITEMS, {"user_id": user_id, "name": _label(note), "notes": _details(note),
                        "schedule": "once", "schedule_days": today, "time_of_day": "anytime",
                        "group_name": GROUP, "position": 9999, "is_deleted": False},
                prefer="return=representation") or []
    return rows[0]["id"] if rows else None

