"""Color Notes: ColorNote-style sticky notes.

Each note is a coloured card holding either free text or a checklist. Notes
can be pinned, given a reminder (one-off or repeating, delivered as a push
notification by services/color_note_reminders.py), archived, or moved to
Trash and restored. "Delete forever" sets purged_at; rows are never hard
deleted (the app-wide soft-delete rule).

Endpoints (JSON unless noted):
    GET  /color-notes                       page
    GET  /api/color-notes                   every note not purged
    POST /api/color-notes                   create
    POST /api/color-notes/<id>              update fields
    POST /api/color-notes/<id>/trash        move to Trash
    POST /api/color-notes/<id>/restore      back from Trash
    POST /api/color-notes/<id>/purge        delete forever (from Trash)
    POST /api/color-notes/trash/empty       delete forever: all of Trash

Table: color_notes (MIGRATION_COLOR_NOTES.sql).
"""
import logging
import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request, session
from requests.exceptions import HTTPError

from auth import login_required
from supabase_client import get, post, update

logger = logging.getLogger("daily_plan")
color_notes_bp = Blueprint("color_notes", __name__)

TABLE = "color_notes"
COLORS = ("red", "orange", "yellow", "green", "blue", "purple", "black", "gray", "white")
KINDS = ("text", "checklist")
REPEATS = ("none", "daily", "weekly", "monthly", "yearly")
MAX_TITLE = 300
MAX_BODY = 100_000
MAX_ITEMS = 500
MAX_ITEM_TEXT = 2_000
FIELDS = ("id,kind,title,body,items,color,is_pinned,is_archived,remind_at,remind_repeat,"
          "last_reminded_at,notify_pinned,created_at,updated_at,deleted_at")
# A note in the notification shade: silent, no vibration, replaced in place
# when refreshed, and kept until dismissed (same as the pinned Day Board).
SHADE = {"silent": True, "renotify": False, "vibrate": [], "requireInteraction": True}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _missing_table(e):
    """True when the migration has not been run yet."""
    resp = getattr(e, "response", None)
    if resp is None:
        return "color_notes" in str(e) and ("does not exist" in str(e) or "PGRST205" in str(e))
    try:
        code = (resp.json() or {}).get("code")
    except Exception:
        code = None
    return code in ("42P01", "PGRST205") or resp.status_code == 404


def _clean_items(raw):
    out = []
    for it in (raw or [])[:MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text") or "")[:MAX_ITEM_TEXT]
        iid = str(it.get("id") or "")[:40] or uuid.uuid4().hex[:12]
        out.append({"id": iid, "text": text, "done": bool(it.get("done"))})
    return out


def _parse_when(value):
    """An ISO time from the browser (with offset or Z) -> UTC ISO string, or None."""
    if value in (None, ""):
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Reminder time is not a valid date")
    if dt.tzinfo is None:
        raise ValueError("Reminder time needs a timezone")
    return dt.astimezone(timezone.utc).isoformat()


def _clean(data, partial):
    """Validate the editable fields. Unknown keys are ignored."""
    out = {}
    if "kind" in data or not partial:
        kind = data.get("kind") or "text"
        if kind not in KINDS:
            raise ValueError("Unknown note type")
        out["kind"] = kind
    if "title" in data or not partial:
        out["title"] = str(data.get("title") or "").strip()[:MAX_TITLE]
    if "body" in data or not partial:
        body = str(data.get("body") or "")
        if len(body) > MAX_BODY:
            raise ValueError("Note is too long")
        out["body"] = body
    if "items" in data or not partial:
        out["items"] = _clean_items(data.get("items"))
    if "color" in data or not partial:
        color = data.get("color") or "yellow"
        if color not in COLORS:
            raise ValueError("Unknown colour")
        out["color"] = color
    for flag in ("is_pinned", "is_archived"):
        if flag in data:
            out[flag] = bool(data[flag])
    if "remind_at" in data:
        out["remind_at"] = _parse_when(data.get("remind_at"))
    if "remind_repeat" in data:
        rep = data.get("remind_repeat") or "none"
        if rep not in REPEATS:
            raise ValueError("Unknown repeat")
        out["remind_repeat"] = rep
    return out


def _one(user_id, note_id):
    rows = get(TABLE, {"id": f"eq.{note_id}", "user_id": f"eq.{user_id}",
                       "purged_at": "is.null", "select": FIELDS}) or []
    return rows[0] if rows else None


@color_notes_bp.route("/color-notes", methods=["GET"])
@login_required
def page():
    return render_template("color_notes.html", colors=COLORS)


@color_notes_bp.route("/api/color-notes", methods=["GET"])
@login_required
def list_notes():
    user_id = session["user_id"]
    try:
        rows = get(TABLE, {"user_id": f"eq.{user_id}", "purged_at": "is.null",
                           "select": FIELDS, "order": "updated_at.desc", "limit": "2000"}) or []
    except Exception as e:
        if _missing_table(e):
            return jsonify({"items": [], "migration_pending": True})
        raise
    return jsonify({"items": rows})


@color_notes_bp.route("/api/color-notes", methods=["POST"])
@login_required
def create_note():
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    try:
        payload = _clean(data, partial=False)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    payload["user_id"] = user_id
    try:
        rows = post(TABLE, payload)
    except Exception as e:
        if _missing_table(e):
            return jsonify({"error": "Run MIGRATION_COLOR_NOTES.sql in Supabase first."}), 503
        raise
    return jsonify({"item": rows[0] if rows else payload}), 201


@color_notes_bp.route("/api/color-notes/<note_id>", methods=["POST"])
@login_required
def update_note(note_id):
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    try:
        patch = _clean(data, partial=True)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not _one(user_id, note_id):
        return jsonify({"error": "Note not found"}), 404
    if not patch:
        return jsonify({"item": _one(user_id, note_id)})
    patch["updated_at"] = _now()
    update(TABLE, {"id": f"eq.{note_id}", "user_id": f"eq.{user_id}"}, patch)
    return jsonify({"item": _one(user_id, note_id)})


def _set(note_id, fields):
    user_id = session["user_id"]
    if not _one(user_id, note_id):
        return jsonify({"error": "Note not found"}), 404
    update(TABLE, {"id": f"eq.{note_id}", "user_id": f"eq.{user_id}"}, fields)
    return jsonify({"item": _one(user_id, note_id), "ok": True})


@color_notes_bp.route("/api/color-notes/<note_id>/trash", methods=["POST"])
@login_required
def trash_note(note_id):
    return _set(note_id, {"deleted_at": _now(), "is_pinned": False, "notify_pinned": False})


@color_notes_bp.route("/api/color-notes/<note_id>/restore", methods=["POST"])
@login_required
def restore_note(note_id):
    return _set(note_id, {"deleted_at": None, "updated_at": _now()})


@color_notes_bp.route("/api/color-notes/<note_id>/purge", methods=["POST"])
@login_required
def purge_note(note_id):
    user_id = session["user_id"]
    note = _one(user_id, note_id)
    if not note:
        return jsonify({"error": "Note not found"}), 404
    if not note.get("deleted_at"):
        return jsonify({"error": "Move the note to Trash first"}), 409
    update(TABLE, {"id": f"eq.{note_id}", "user_id": f"eq.{user_id}"},
           {"purged_at": _now(), "remind_at": None})
    return jsonify({"ok": True})


@color_notes_bp.route("/api/color-notes/trash/empty", methods=["POST"])
@login_required
def empty_trash():
    user_id = session["user_id"]
    update(TABLE, {"user_id": f"eq.{user_id}", "deleted_at": "not.is.null", "purged_at": "is.null"},
           {"purged_at": _now(), "remind_at": None})
    return jsonify({"ok": True})


def shade_text(note, limit=400):
    """What the pinned notification shows: the text, or one line per open item."""
    if note.get("kind") == "checklist":
        items = [i for i in (note.get("items") or []) if (i.get("text") or "").strip()]
        open_items = [i for i in items if not i.get("done")]
        lines = ["\u2610 " + i["text"].strip() for i in open_items[:10]]
        if len(open_items) > 10:
            lines.append(f"+{len(open_items) - 10} more")
        done = len(items) - len(open_items)
        if done:
            lines.append(f"\u2611 {done} done")
        text = "\n".join(lines) or "All items checked"
    else:
        text = (note.get("body") or "").strip() or "Tap to open"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


@color_notes_bp.route("/api/color-notes/<note_id>/notify", methods=["POST"])
@login_required
def notify_pin(note_id):
    """Pin a note to the notification shade (on) or stop showing it (off).
    Calling it again with on=true refreshes the notification in place."""
    from services import push_service
    user_id = session["user_id"]
    note = _one(user_id, note_id)
    if not note:
        return jsonify({"error": "Note not found"}), 404
    on = bool((request.get_json(silent=True) or {}).get("on", True))
    if on and note.get("deleted_at"):
        return jsonify({"error": "Restore the note first"}), 409
    update(TABLE, {"id": f"eq.{note_id}", "user_id": f"eq.{user_id}"}, {"notify_pinned": on})
    sent = failed = 0
    if on:
        title = (note.get("title") or "").strip() or "Note"
        sent, failed = push_service.send_to_user(
            user_id, title=f"\U0001F4CC {title}", body=shade_text(note),
            url=f"/color-notes?open={note_id}", tag=f"cnote-pin-{note_id}",
            extra=SHADE, urgency="normal")
    return jsonify({"item": _one(user_id, note_id), "on": on, "sent": sent, "failed": failed,
                    "tag": f"cnote-pin-{note_id}"})


# ── Home-screen widget (Android companion app) ───────────────────────────
# The widget cannot use the browser's login cookie, so each phone gets its
# own token. Only its SHA-256 is stored; the token itself is shown once, as a
# dpnotes://connect link the app opens to configure itself. Tokens can only
# read notes and tick checklist items, and can be revoked from the page.
import hashlib
import secrets
from urllib.parse import quote

TOKENS = "widget_tokens"
WIDGET_FIELDS = "id,kind,title,body,items,color,is_pinned,remind_at,remind_repeat,updated_at"


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _token_user():
    """The user id for this request's widget token, or None."""
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token or len(token) > 200:
        return None
    try:
        rows = get(TOKENS, {"token_hash": f"eq.{_hash(token)}", "revoked_at": "is.null",
                            "select": "id,user_id,last_used_at"}) or []
    except Exception:
        return None
    if not rows:
        return None
    row = rows[0]
    try:
        update(TOKENS, {"id": f"eq.{row['id']}"}, {"last_used_at": _now()})
    except Exception:
        pass
    return row["user_id"]


@color_notes_bp.route("/api/color-notes/widget-tokens", methods=["GET"])
@login_required
def widget_tokens():
    try:
        rows = get(TOKENS, {"user_id": f"eq.{session['user_id']}", "revoked_at": "is.null",
                            "select": "id,label,created_at,last_used_at", "order": "created_at.desc"}) or []
    except Exception as e:
        if _missing_table(e) or "widget_tokens" in str(e):
            return jsonify({"items": [], "migration_pending": True})
        raise
    return jsonify({"items": rows})


@color_notes_bp.route("/api/color-notes/widget-token", methods=["POST"])
@login_required
def new_widget_token():
    label = str((request.get_json(silent=True) or {}).get("label") or "Android widget").strip()[:60]
    token = "dpw_" + secrets.token_urlsafe(32)
    try:
        post(TOKENS, {"user_id": session["user_id"], "token_hash": _hash(token), "label": label})
    except Exception as e:
        return jsonify({"error": "Run MIGRATION_COLOR_NOTES.sql in Supabase first."}), 503
    server = request.host_url.rstrip("/")
    if server.startswith("http://") and not server.startswith(("http://localhost", "http://127.")):
        server = "https://" + server[len("http://"):]
    return jsonify({"token": token, "server": server,
                    "connect_url": f"dpnotes://connect?server={quote(server, safe='')}&token={quote(token, safe='')}"}), 201


@color_notes_bp.route("/api/color-notes/widget-token/<tid>/revoke", methods=["POST"])
@login_required
def revoke_widget_token(tid):
    update(TOKENS, {"id": f"eq.{tid}", "user_id": f"eq.{session['user_id']}"}, {"revoked_at": _now()})
    return jsonify({"ok": True})


@color_notes_bp.route("/api/widget/notes", methods=["GET"])
def widget_notes():
    user_id = _token_user()
    if not user_id:
        return jsonify({"error": "Not connected. Open the widget app and connect again."}), 401
    scope = request.args.get("scope") or "pinned"
    params = {"user_id": f"eq.{user_id}", "deleted_at": "is.null", "purged_at": "is.null",
              "is_archived": "is.false", "select": WIDGET_FIELDS,
              "order": "is_pinned.desc,updated_at.desc", "limit": "25"}
    rows = get(TABLE, params) or []
    pinned = [r for r in rows if r.get("is_pinned")]
    if scope == "pinned" and pinned:
        rows = pinned
    return jsonify({"notes": rows, "scope": "pinned" if (scope == "pinned" and pinned) else "recent",
                    "server_time": _now()})


@color_notes_bp.route("/api/widget/notes/<note_id>/toggle", methods=["POST"])
def widget_toggle(note_id):
    user_id = _token_user()
    if not user_id:
        return jsonify({"error": "Not connected"}), 401
    item_id = str((request.get_json(silent=True) or {}).get("item_id") or "")
    note = _one(user_id, note_id)
    if not note or note.get("kind") != "checklist":
        return jsonify({"error": "Note not found"}), 404
    items = note.get("items") or []
    hit = False
    for it in items:
        if it.get("id") == item_id:
            it["done"] = not it.get("done")
            hit = True
    if not hit:
        return jsonify({"error": "Item not found"}), 404
    update(TABLE, {"id": f"eq.{note_id}", "user_id": f"eq.{user_id}"}, {"items": items, "updated_at": _now()})
    note = _one(user_id, note_id)
    if note and note.get("notify_pinned"):
        try:
            from services import push_service
            title = (note.get("title") or "").strip() or "Note"
            push_service.send_to_user(user_id, title=f"\U0001F4CC {title}", body=shade_text(note),
                                      url=f"/color-notes?open={note_id}", tag=f"cnote-pin-{note_id}",
                                      extra=SHADE, urgency="normal")
        except Exception:
            logger.debug("shade refresh after widget toggle failed", exc_info=True)
    return jsonify({"ok": True, "note": note})
