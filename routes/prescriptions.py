"""Prescriptions: photos or PDFs of prescriptions, kept private.

Files live in the PRIVATE Supabase Storage bucket `prescriptions` (see
MIGRATION_PRESCRIPTIONS.sql). Unlike /photos, which uses a public bucket,
nothing here has a public URL: /api/prescriptions/<id>/file/<n> streams
the file only to its signed-in owner, with no-store caching, and the
service worker never caches /api/.

Metadata (who it is for, doctor, clinic, date, notes) is one row in
`prescriptions`; one prescription can have several pages (files jsonb).
Deleting is soft, as everywhere in the app.
"""
import logging
import mimetypes
import uuid
from datetime import date, datetime, timezone

import requests
from flask import Blueprint, Response, abort, jsonify, render_template, request, session

from auth import login_required
from supabase_client import SUPABASE_KEY, SUPABASE_URL, get, post, update

logger = logging.getLogger("daily_plan")

prescriptions_bp = Blueprint("prescriptions", __name__)

BUCKET = "prescriptions"
MAX_BYTES = 10 * 1024 * 1024
MAX_FILES = 8
ALLOWED = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp",
    "image/heic": "heic", "image/heif": "heif", "application/pdf": "pdf",
}
FIELDS = ("title", "patient", "doctor", "clinic", "notes")
LIMITS = {"title": 120, "patient": 60, "doctor": 80, "clinic": 100, "notes": 4000}
MIGRATION = "MIGRATION_PRESCRIPTIONS.sql"


def _headers(extra=None):
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    h.update(extra or {})
    return h


def _clean(form):
    out = {}
    for f in FIELDS:
        if f in form:
            out[f] = (form.get(f) or "").strip()[:LIMITS[f]]
    if "prescribed_on" in form:
        raw = (form.get("prescribed_on") or "").strip()
        try:
            out["prescribed_on"] = date.fromisoformat(raw).isoformat() if raw else None
        except ValueError:
            raise ValueError("Date must be YYYY-MM-DD")
    return out


def _mime_for(f):
    mime = (f.mimetype or "").lower()
    if mime not in ALLOWED:
        guessed, _ = mimetypes.guess_type(f.filename or "")
        mime = (guessed or "").lower()
        if not mime and (f.filename or "").lower().endswith((".heic", ".heif")):
            mime = "image/heic"
    return mime if mime in ALLOWED else None


def _store(user_id, f):
    """Upload one file to the private bucket. Returns its files[] entry."""
    mime = _mime_for(f)
    if not mime:
        raise ValueError(f"{f.filename}: only photos (JPG, PNG, WebP, HEIC) or PDF")
    data = f.stream.read()
    if not data:
        raise ValueError(f"{f.filename}: empty file")
    if len(data) > MAX_BYTES:
        raise ValueError(f"{f.filename}: too large (max 10 MB)")
    key = f"{user_id}/{uuid.uuid4().hex}.{ALLOWED[mime]}"
    r = requests.post(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{key}",
                      headers=_headers({"Content-Type": mime, "x-upsert": "false"}),
                      data=data, timeout=60)
    if not r.ok:
        logger.error("prescription upload %s: %s", r.status_code, r.text[:300])
        if r.status_code in (400, 404) and "not found" in r.text.lower():
            raise RuntimeError(f"Storage bucket missing: run {MIGRATION} in Supabase")
        raise RuntimeError("Upload failed, please try again")
    return {"key": key, "mime": mime, "size": len(data), "name": (f.filename or "")[:120]}


def _remove(keys):
    if not keys:
        return
    try:
        requests.delete(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}",
                        headers=_headers({"Content-Type": "application/json"}),
                        json={"prefixes": keys}, timeout=30)
    except requests.RequestException:
        logger.warning("prescription file cleanup failed", exc_info=True)


def _own(user_id, pid):
    try:
        rows = get("prescriptions", params={"id": f"eq.{pid}", "user_id": f"eq.{user_id}",
                                            "is_deleted": "eq.false", "select": "*", "limit": "1"}) or []
    except Exception:
        return None
    return rows[0] if rows else None


def _view(r):
    files = r.get("files") or []
    return {
        "id": r["id"], "title": r.get("title") or "", "patient": r.get("patient") or "",
        "doctor": r.get("doctor") or "", "clinic": r.get("clinic") or "",
        "prescribed_on": r.get("prescribed_on"), "notes": r.get("notes") or "",
        "created_at": r.get("created_at"),
        "files": [{"n": i, "mime": f.get("mime"), "name": f.get("name") or f"Page {i + 1}",
                   "size": f.get("size"), "url": f"/api/prescriptions/{r['id']}/file/{i}"}
                  for i, f in enumerate(files)],
    }


@prescriptions_bp.route("/prescriptions")
@login_required
def page():
    return render_template("prescriptions.html")


@prescriptions_bp.route("/api/prescriptions")
@login_required
def list_items():
    try:
        rows = get("prescriptions", params={
            "user_id": f"eq.{session['user_id']}", "is_deleted": "eq.false", "select": "*",
            "order": "prescribed_on.desc.nullslast,created_at.desc", "limit": "500"}) or []
    except Exception:
        logger.warning("prescriptions list failed (migration missing?)", exc_info=True)
        return jsonify({"items": [], "available": False, "migration": MIGRATION})
    return jsonify({"items": [_view(r) for r in rows], "available": True})


@prescriptions_bp.route("/api/prescriptions", methods=["POST"])
@login_required
def create():
    user_id = session["user_id"]
    uploads = [f for f in request.files.getlist("files") if f and f.filename]
    if not uploads:
        return jsonify({"error": "Add at least one photo or PDF"}), 400
    if len(uploads) > MAX_FILES:
        return jsonify({"error": f"Up to {MAX_FILES} files at a time"}), 400
    try:
        meta = _clean(request.form)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    stored = []
    try:
        for f in uploads:
            stored.append(_store(user_id, f))
    except ValueError as e:
        _remove([s["key"] for s in stored])
        return jsonify({"error": str(e)}), 400
    except (RuntimeError, requests.RequestException) as e:
        _remove([s["key"] for s in stored])
        return jsonify({"error": str(e)}), 502
    row = {"user_id": user_id, "files": stored, **meta}
    if not row.get("title"):
        row["title"] = "Prescription"
    try:
        out = post("prescriptions", row)
    except Exception:
        _remove([s["key"] for s in stored])
        logger.exception("prescription insert failed")
        return jsonify({"error": f"Could not save. Has {MIGRATION} been run in Supabase?"}), 500
    return jsonify({"ok": True, "item": _view(out[0]) if out else None}), 201


@prescriptions_bp.route("/api/prescriptions/<pid>", methods=["POST"])
@login_required
def edit(pid):
    """Change the details, and optionally add pages (multipart 'files')."""
    user_id = session["user_id"]
    row = _own(user_id, pid)
    if not row:
        return jsonify({"error": "Not found"}), 404
    try:
        changes = _clean(request.form)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    uploads = [f for f in request.files.getlist("files") if f and f.filename]
    files = list(row.get("files") or [])
    if len(files) + len(uploads) > MAX_FILES * 2:
        return jsonify({"error": "Too many pages on one prescription"}), 400
    added = []
    try:
        for f in uploads:
            added.append(_store(user_id, f))
    except ValueError as e:
        _remove([s["key"] for s in added])
        return jsonify({"error": str(e)}), 400
    except (RuntimeError, requests.RequestException) as e:
        _remove([s["key"] for s in added])
        return jsonify({"error": str(e)}), 502
    if added:
        changes["files"] = files + added
    if not changes:
        return jsonify({"ok": True, "item": _view(row)})
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    update("prescriptions", {"id": f"eq.{pid}", "user_id": f"eq.{user_id}"}, changes)
    return jsonify({"ok": True, "item": _view({**row, **changes})})


@prescriptions_bp.route("/api/prescriptions/<pid>/file/<int:n>/delete", methods=["POST"])
@login_required
def delete_page(pid, n):
    user_id = session["user_id"]
    row = _own(user_id, pid)
    files = list((row or {}).get("files") or [])
    if not row or not (0 <= n < len(files)):
        return jsonify({"error": "Not found"}), 404
    if len(files) == 1:
        return jsonify({"error": "A prescription needs at least one page; delete the prescription instead"}), 400
    gone = files.pop(n)
    update("prescriptions", {"id": f"eq.{pid}", "user_id": f"eq.{user_id}"},
           {"files": files, "updated_at": datetime.now(timezone.utc).isoformat()})
    _remove([gone.get("key")])
    return jsonify({"ok": True, "item": _view({**row, "files": files})})


@prescriptions_bp.route("/api/prescriptions/<pid>/delete", methods=["POST"])
@login_required
def delete(pid):
    """Soft delete: the row is hidden, the files are kept (restorable)."""
    user_id = session["user_id"]
    if not _own(user_id, pid):
        return jsonify({"error": "Not found"}), 404
    update("prescriptions", {"id": f"eq.{pid}", "user_id": f"eq.{user_id}"},
           {"is_deleted": True, "deleted_at": datetime.now(timezone.utc).isoformat()})
    return jsonify({"ok": True})


@prescriptions_bp.route("/api/prescriptions/<pid>/file/<int:n>")
@login_required
def file(pid, n):
    """Stream one page to its owner. Never a public URL, never cached."""
    row = _own(session["user_id"], pid)
    files = (row or {}).get("files") or []
    if not row or not (0 <= n < len(files)):
        abort(404)
    f = files[n]
    key = f.get("key") or ""
    if not key.startswith(f"{session['user_id']}/"):
        abort(404)
    try:
        r = requests.get(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{key}",
                         headers=_headers(), timeout=60)
    except requests.RequestException:
        abort(502)
    if not r.ok:
        abort(404)
    mime = f.get("mime") or r.headers.get("Content-Type") or "application/octet-stream"
    name = (f.get("name") or f"prescription-{n + 1}.{ALLOWED.get(mime, 'bin')}").replace('"', "")
    disp = "attachment" if request.args.get("download") else "inline"
    return Response(r.content, mimetype=mime, headers={
        "Cache-Control": "private, no-store",
        "Content-Disposition": f'{disp}; filename="{name}"',
        "X-Content-Type-Options": "nosniff",
    })
