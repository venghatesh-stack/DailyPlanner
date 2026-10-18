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
          "last_reminded_at,created_at,updated_at,deleted_at")


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
    return _set(note_id, {"deleted_at": _now(), "is_pinned": False})


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
