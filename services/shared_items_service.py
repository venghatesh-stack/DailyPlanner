"""Sharing an item with someone, for a day and a time.

One implementation for every kind of shareable thing — inbox links and
prep topics today, whatever comes next tomorrow. The alternative was a
share module per feature, and the four prep banks are already the proof
of how that ends: the same job done four times, fixed once.

WHAT A SHARE IS
    this thing → these people → that day and time → done or not.

WHO CAN DO WHAT
    The owner shares, unshares, and sees who finished and when. The
    recipient sees it in their calendar and can mark it done. A recipient
    cannot edit the item itself; for inbox links that is enforced by the
    `user_id = me` filter every write already carries, and stated back as
    a 403 rather than a silent no-op.

WHY completed_at LIVES HERE AND NOT ON THE ITEM
    There is one row per (item, recipient), so completion is naturally
    per person. Two people given the same article finish it on different
    days — that is the whole of "tell me who has completed it and the
    date in which it was completed".
"""

import logging
import re
from datetime import date, datetime, timezone

from supabase_client import delete, get, post, update

logger = logging.getLogger("daily_plan")

KINDS = ("inbox", "prep")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
MAX_TITLE = 300


def _clean_time(raw):
    """"HH:MM" or None. Anything else is dropped rather than stored — a
    half-parsed time in a calendar is worse than no time."""
    if not raw or not isinstance(raw, str):
        return None
    m = _TIME_RE.match(raw.strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def _clean_date(raw):
    if not raw or not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw.strip()[:10]).isoformat()
    except ValueError:
        return None


def people(user_id):
    """Everyone else who can be shared with: the other active accounts.

    Names only. Picking a person needs a name; the email address is
    somebody's personal data and does not belong in a page payload.
    """
    try:
        rows = get("users", params={
            "select": "id,email,display_name,is_active",
            "order": "display_name.asc",
        }) or []
    except Exception:
        logger.exception("shared_items: could not list people")
        return []
    # When a family allowlist (CHAT_USER_EMAILS) is configured, only those
    # people are offered — the same people chat and family tasks are for.
    # It used to list every active account to anyone signed in. Without an
    # allowlist the old behaviour stays (accounts are invite-only anyway),
    # so sharing keeps working on installs that never set one.
    try:
        from routes.chat import _allowlist
        family = _allowlist()
    except Exception:
        family = set()
    out = []
    for r in rows:
        if r["id"] == user_id or r.get("is_active") is False:
            continue
        if family and (r.get("email") or "").strip().lower() not in family:
            continue
        name = (r.get("display_name") or "").strip() or \
            (r.get("email") or "").split("@", 1)[0]
        out.append({"user_id": r["id"], "name": name or "someone"})
    return out


def display_names(user_ids):
    ids = [i for i in {u for u in user_ids if u}]
    if not ids:
        return {}
    try:
        rows = get("users", params={
            "id": f"in.({','.join(ids)})",
            "select": "id,email,display_name",
        }) or []
    except Exception:
        return {}
    out = {}
    for r in rows:
        name = (r.get("display_name") or "").strip() or \
            (r.get("email") or "").split("@", 1)[0]
        out[r["id"]] = name or "someone"
    return out


def grants_for(owner_id, kind, item_ref):
    """Who this item is currently shared with, as the share dialog needs
    it: the ids to tick, plus who has finished and when."""
    rows = get("shared_items", params={
        "owner_id": f"eq.{owner_id}",
        "kind": f"eq.{kind}",
        "item_ref": f"eq.{item_ref}",
        "select": "id,shared_with,due_date,due_time,completed_at",
    }) or []
    names = display_names([r["shared_with"] for r in rows])
    for r in rows:
        r["name"] = names.get(r["shared_with"], "someone")
    return rows


def share(owner_id, *, kind, item_ref, user_ids, title=None, url=None,
          bank=None, due_date=None, due_time=None, valid_ids=None):
    """Replace the set of people this item is shared with.

    THE WHOLE SET, not a delta, so a retry or a replayed offline write
    cannot double-share or half-unshare. Ids that are not accounts on
    this instance are dropped rather than stored — a grant addressed to
    a stranger is worse than a failed share.

    An existing grant keeps its completed_at: re-sharing to add a second
    person must not quietly un-finish the first.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")

    allowed = valid_ids if valid_ids is not None else \
        {p["user_id"] for p in people(owner_id)}
    wanted = {u for u in (user_ids or []) if isinstance(u, str) and u in allowed}

    existing = get("shared_items", params={
        "owner_id": f"eq.{owner_id}",
        "kind": f"eq.{kind}",
        "item_ref": f"eq.{item_ref}",
        "select": "id,shared_with",
    }) or []
    current = {r["shared_with"]: r["id"] for r in existing}

    d, t = _clean_date(due_date), _clean_time(due_time)

    for uid in wanted - set(current):
        post("shared_items", {
            "kind": kind,
            "item_ref": item_ref,
            "bank": bank,
            "item_title": (title or "")[:MAX_TITLE] or None,
            "item_url": url or None,
            "owner_id": owner_id,
            "shared_with": uid,
            "due_date": d,
            "due_time": t,
        }, prefer="return=minimal")

    # Someone already on the list gets the new schedule, and keeps their
    # completion. Changing when a thing is due does not un-do it.
    for uid in wanted & set(current):
        update("shared_items", params={"id": f"eq.{current[uid]}"},
               json={"due_date": d, "due_time": t,
                     "item_title": (title or "")[:MAX_TITLE] or None,
                     "item_url": url or None})

    for uid in set(current) - wanted:
        delete("shared_items", {"id": f"eq.{current[uid]}"})

    return sorted(wanted)


def assigned_to(user_id):
    """Everything shared WITH this person — the chat calendar.

    Ordered the way it will be read: by the day it is wanted, soonest
    first, with undated items last rather than first (a null sorts before
    every date, which would put "someday" above "today").
    """
    rows = get("shared_items", params={
        "shared_with": f"eq.{user_id}",
        "select": "id,kind,item_ref,bank,item_title,item_url,owner_id,"
                  "due_date,due_time,completed_at,created_at",
        "order": "due_date.asc.nullslast,due_time.asc.nullsfirst",
        "limit": "400",
    }) or []
    names = display_names([r["owner_id"] for r in rows])
    for r in rows:
        r["from_name"] = names.get(r["owner_id"], "someone")
        r.pop("owner_id", None)
    return rows


def sent_by(owner_id):
    """Everything this person has shared, with who finished it and when.

    Grouped by item so the answer reads as one line per thing rather than
    one per person-thing pair.
    """
    rows = get("shared_items", params={
        "owner_id": f"eq.{owner_id}",
        "select": "id,kind,item_ref,bank,item_title,item_url,shared_with,"
                  "due_date,due_time,completed_at,created_at",
        "order": "created_at.desc",
        "limit": "400",
    }) or []
    names = display_names([r["shared_with"] for r in rows])
    grouped = {}
    for r in rows:
        key = (r["kind"], r["item_ref"])
        g = grouped.setdefault(key, {
            "kind": r["kind"], "item_ref": r["item_ref"], "bank": r.get("bank"),
            "item_title": r.get("item_title"), "item_url": r.get("item_url"),
            "due_date": r.get("due_date"), "due_time": r.get("due_time"),
            "people": [],
        })
        g["people"].append({
            "name": names.get(r["shared_with"], "someone"),
            "completed_at": r.get("completed_at"),
        })
    for g in grouped.values():
        g["done_count"] = sum(1 for p in g["people"] if p["completed_at"])
        g["total"] = len(g["people"])
    return list(grouped.values())


def set_completed(user_id, share_id, done=True):
    """Mark a share done, or undo it. RECIPIENT ONLY — the filter is the
    authorisation, so it is applied in the query and checked afterwards
    rather than assumed."""
    rows = get("shared_items", params={
        "id": f"eq.{share_id}", "shared_with": f"eq.{user_id}",
        "select": "id", "limit": "1",
    }) or []
    if not rows:
        return None
    stamp = datetime.now(timezone.utc).isoformat() if done else None
    update("shared_items", params={"id": f"eq.{share_id}",
                                   "shared_with": f"eq.{user_id}"},
           json={"completed_at": stamp})
    return stamp if done else ""
