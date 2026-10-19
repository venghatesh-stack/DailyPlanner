"""Reminders for Color Notes, sent as Web Push notifications.

The push scheduler calls fire() every minute for each user with an active
push subscription. A note is due when its remind_at has passed (within the
last GRACE, so a server that was asleep for a day does not flood the phone
with week-old reminders) and it is not in Trash or the Archive.

Exactly-once across gunicorn workers: the claim is a row in
checklist_reminder_log keyed on uuid5(note id + the reminder time), the same
unique index the checklist and revision reminders use. Whoever inserts first
sends; everyone else gets a 409 and skips. No extra table is needed.

After sending, a repeating reminder moves to its next occurrence after now;
a one-off is cleared. That PATCH is filtered on the remind_at we fired, so if
the user changed the reminder in the meantime, their new time wins.
"""
import calendar
import logging
import uuid
from datetime import datetime, timedelta, timezone

from requests.exceptions import HTTPError

from services import push_service
from supabase_client import get, post, update

logger = logging.getLogger(__name__)

TABLE = "color_notes"
GRACE = timedelta(hours=6)
_NS = uuid.UUID("2b7f5c1e-9a3d-4e8b-b1c2-7d6e5f4a3b2c")


def _parse(ts):
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _add_months(dt, n):
    m = dt.month - 1 + n
    y, m = dt.year + m // 12, m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def next_occurrence(when, repeat, now, tz):
    """The first repeat of `when` that is after `now`, stepping in the
    user's local time so 9:00 stays 9:00 across months. None for 'none'."""
    if repeat not in ("daily", "weekly", "monthly", "yearly"):
        return None
    local = when.astimezone(tz)
    k = 0
    while True:
        k += 1
        if repeat == "daily":
            nxt = local + timedelta(days=k)
        elif repeat == "weekly":
            nxt = local + timedelta(weeks=k)
        elif repeat == "monthly":
            nxt = _add_months(local, k)
        else:
            nxt = _add_months(local, 12 * k)
        if nxt > now:
            return nxt.astimezone(timezone.utc)
        if k > 5000:
            return None


def preview(note, limit=140):
    """The notification body: the text, or the unchecked checklist items."""
    if note.get("kind") == "checklist":
        items = [i.get("text", "").strip() for i in (note.get("items") or [])
                 if not i.get("done") and (i.get("text") or "").strip()]
        text = " · ".join(items) if items else "All items checked"
    else:
        text = " ".join((note.get("body") or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _claim(user_id, note_id, remind_at, today):
    item = uuid.uuid5(_NS, f"{note_id}|{remind_at}")
    try:
        post("checklist_reminder_log", {"item_id": str(item), "user_id": str(user_id),
                                        "sent_date": today}, prefer="return=minimal")
        return True
    except HTTPError as e:
        if e.response is None or e.response.status_code != 409:
            logger.exception("color note reminder: claim failed for %s", note_id)
        return False


def due(user_id, now_utc):
    try:
        return get(TABLE, {
            "user_id": f"eq.{user_id}", "remind_at": f"lte.{now_utc.isoformat()}",
            "deleted_at": "is.null", "purged_at": "is.null", "is_archived": "is.false",
            "select": "id,kind,title,body,items,color,remind_at,remind_repeat,checklist_item_id,is_archived,deleted_at",
            "limit": "50"}) or []
    except Exception:
        # Table not created yet (migration pending): nothing to remind.
        logger.debug("color notes reminder query failed for %s", user_id, exc_info=True)
        return []


def fire(user_id, now_local):
    """Send every due note reminder for this user. Returns the ids sent."""
    tz = now_local.tzinfo
    now_utc = now_local.astimezone(timezone.utc)
    sent = []
    for note in due(user_id, now_utc):
        raw = note.get("remind_at")
        if not raw:
            continue
        when = _parse(raw)
        nxt = next_occurrence(when, note.get("remind_repeat") or "none", now_utc, tz)
        move = {"remind_at": nxt.isoformat() if nxt else None,
                "last_reminded_at": now_utc.isoformat()}
        if now_utc - when > GRACE:
            # Missed long ago (server asleep): move it on quietly.
            update(TABLE, {"id": f"eq.{note['id']}", "remind_at": f"eq.{raw}"}, move)
            continue
        if not _claim(user_id, note["id"], raw, now_local.date().isoformat()):
            continue
        if not note.get("checklist_item_id"):
            # Linked notes are announced by their checklist item (push) and
            # its Google Calendar event, at this same minute: one alert, not two.
            title = (note.get("title") or "").strip() or "Note reminder"
            push_service.send_to_user(user_id, title=f"📝 {title}", body=preview(note),
                                      url=f"/color-notes?open={note['id']}",
                                      tag=f"cnote-{note['id']}")
        update(TABLE, {"id": f"eq.{note['id']}", "remind_at": f"eq.{raw}"}, move)
        if note.get("checklist_item_id") and (note.get("remind_repeat") == "yearly"):
            # A yearly reminder is a one-off checklist item: move it to next year.
            from services import color_note_links
            color_note_links.sync(user_id, dict(note, remind_at=move["remind_at"]))
        sent.append(note["id"])
    return sent
