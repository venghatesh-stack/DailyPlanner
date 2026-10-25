"""TravelReads — a curated queue of articles, videos, and podcasts to
consume while travelling.

Endpoints:
    GET  /travel-reads                                  page render
    GET  /api/travel-reads                              list (active)
    POST /api/travel-reads                              add (auto-fetch metadata)
    POST /api/travel-reads/<id>/update                  edit fields
    POST /api/travel-reads/<id>/status                  change status
    POST /api/travel-reads/<id>/archive                 soft delete
    POST /api/travel-reads/<id>/transcript-paste        save user-pasted transcript

Soft-delete only — items the user "removes" set status='archived'
(matching the project's no-hard-delete convention).

Transcription is paste-only: the user captures the transcript on
their own machine (bookmarklet that scrapes YouTube's caption track
and copies it to the clipboard, or YouTube's own "Show transcript"
panel) and pastes it in. Server-side auto-transcription via yt-dlp
was removed because YouTube blocks both caption fetches AND audio
downloads from cloud-host IPs.
"""

import logging
import re
from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, jsonify, render_template, request, session

from auth import login_required
from supabase_client import get, post, update
from services.inbox_service import fetch_meta, detect_type, auto_label

logger = logging.getLogger("daily_plan")
travel_reads_bp = Blueprint("travel_reads", __name__)


VALID_KINDS = {"article", "video", "podcast", "audio", "other"}
VALID_PRIORITIES = {"low", "medium", "high"}
VALID_STATUSES = {"queued", "in_progress", "done", "archived"}

_MAX_TITLE = 240
_MAX_DESC = 600
_MAX_NOTES = 10000   # ~2000 words — generous room for video summaries
_MAX_LABELS_PER_ITEM = 16
_MAX_LABEL_LEN = 32


def _sanitize_labels(raw) -> list[str]:
    """Normalise a labels patch from the client. Mirrors the helper in
    routes/inbox.py — kept duplicated rather than shared because the
    two routes already evolve independently and a one-liner doesn't
    earn its own module."""
    if not isinstance(raw, list):
        return []
    seen = set()
    out: list[str] = []
    for v in raw:
        if not isinstance(v, str):
            continue
        s = v.strip().lower()
        if not s or len(s) > _MAX_LABEL_LEN:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= _MAX_LABELS_PER_ITEM:
            break
    return out


# ─── Helpers ─────────────────────────────────────────────────────


_YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/embed/)([A-Za-z0-9_-]{6,})"
)


def _youtube_video_id(url: str):
    """Return the YouTube video ID encoded in a URL, or None."""
    m = _YOUTUBE_ID_RE.search(url or "")
    return m.group(1) if m else None


def _normalize_kind(raw: str, url: str) -> str:
    raw = (raw or "").strip().lower()
    if raw in VALID_KINDS:
        return raw
    # Auto-detect if not provided.
    t = detect_type(url or "")
    if t == "video":
        return "video"
    if t == "article":
        return "article"
    if t == "pdf":
        return "article"
    return "article"   # default — most "TravelReads" links are articles


def _source_from_url(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def _thumbnail_for(url: str, kind: str) -> str | None:
    """Best-effort thumbnail. YouTube has predictable URLs; everything
    else falls back to None for now (we could parse og:image later)."""
    yt_id = _youtube_video_id(url)
    if yt_id:
        # hqdefault is 480x360, available for nearly every video.
        return f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"
    return None


# ─── Page ────────────────────────────────────────────────────────


@travel_reads_bp.route("/travel-reads", methods=["GET"])
@login_required
def travel_reads_page():
    return render_template(
        "travel_reads.html",
        kinds=sorted(VALID_KINDS),
        priorities=["high", "medium", "low"],
    )


# ─── API: list ───────────────────────────────────────────────────


@travel_reads_bp.route("/api/travel-reads", methods=["GET"])
@login_required
def list_travel_reads():
    user_id = session["user_id"]
    rows = get(
        "travel_reads",
        params={
            "user_id": f"eq.{user_id}",
            "status": "neq.archived",
            "select": (
                "id,url,title,description,thumbnail_url,source,kind,"
                "duration_minutes,priority,status,notes,transcript_note_id,"
                "labels,added_at,started_at,finished_at,updated_at"
            ),
            "order": "status.asc,added_at.desc",
            "limit": "500",
        },
    ) or []

    prio_rank = {"high": 0, "medium": 1, "low": 2}
    status_rank = {"in_progress": 0, "queued": 1, "done": 2}
    # Newest first within a bucket (two stable sorts; hash() of the
    # timestamp string used to randomise this order on every restart).
    rows.sort(key=lambda r: r.get("added_at") or "", reverse=True)
    rows.sort(key=lambda r: (
        status_rank.get(r.get("status") or "queued", 1),
        prio_rank.get(r.get("priority") or "medium", 1),
    ))

    # Aggregate stats for the header strip.
    queued = [r for r in rows if (r.get("status") or "queued") == "queued"]
    in_progress = [r for r in rows if (r.get("status") or "") == "in_progress"]
    done = [r for r in rows if (r.get("status") or "") == "done"]

    def _sum_minutes(items):
        return sum(int(r.get("duration_minutes") or 0) for r in items)

    return jsonify({
        "items": rows,
        "stats": {
            "queued": len(queued),
            "in_progress": len(in_progress),
            "done": len(done),
            "queued_minutes": _sum_minutes(queued + in_progress),
        },
    })


# ─── API: add ────────────────────────────────────────────────────


@travel_reads_bp.route("/api/travel-reads", methods=["POST"])
@login_required
def add_travel_read():
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}

    url = (data.get("url") or "").strip()
    if not url or not re.match(r"^https?://", url):
        return jsonify({"error": "Valid URL required (http/https)"}), 400

    # User-supplied overrides; otherwise auto-fetch.
    title = (data.get("title") or "").strip()[:_MAX_TITLE]
    description = (data.get("description") or "").strip()[:_MAX_DESC]
    if not title or not description:
        meta = fetch_meta(url)
        if not title:
            title = (meta.get("title") or url)[:_MAX_TITLE]
        if not description:
            description = (meta.get("description") or "")[:_MAX_DESC]

    kind = _normalize_kind(data.get("kind"), url)
    priority = (data.get("priority") or "medium").strip().lower()
    if priority not in VALID_PRIORITIES:
        priority = "medium"

    duration_raw = data.get("duration_minutes")
    duration = None
    if duration_raw not in (None, ""):
        try:
            duration = max(0, int(duration_raw))
        except (TypeError, ValueError):
            duration = None

    # Auto-suggested mode/length labels — the user can override these
    # via chip toggles after the fact. Duration is sourced from the
    # user-supplied minutes since travel_reads doesn't fetch the
    # YouTube Data API on save.
    duration_seconds = (duration or 0) * 60
    labels = auto_label(url, title, description, kind, duration_seconds)

    payload = {
        "user_id": user_id,
        "url": url,
        "title": title,
        "description": description,
        "thumbnail_url": _thumbnail_for(url, kind),
        "source": _source_from_url(url),
        "kind": kind,
        "duration_minutes": duration,
        "priority": priority,
        "status": "queued",
        "labels": labels,
        "notes": (data.get("notes") or "").strip()[:_MAX_NOTES] or None,
    }

    try:
        rows = post("travel_reads", payload)
    except Exception as e:
        logger.error("travel_reads insert failed: %s", e)
        return jsonify({"error": "Couldn't save — please try again."}), 502

    return jsonify({"ok": True, "item": rows[0] if rows else None})


# ─── API: bulk add ───────────────────────────────────────────────

_MAX_BULK = 100


def parse_bulk(text):
    """One item per line: `URL | minutes | title | note`. Only the URL is
    required; blank lines and lines starting with # are skipped."""
    items, errors = [], []
    for n, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [x.strip() for x in line.split("|")]
        url = parts[0]
        if not re.match(r"^https?://\S+$", url):
            errors.append(f"Line {n}: not a link")
            continue
        minutes = None
        if len(parts) > 1 and parts[1]:
            m = re.search(r"\d+", parts[1])
            minutes = int(m.group()) if m else None
        items.append({"url": url, "minutes": minutes,
                      "title": parts[2] if len(parts) > 2 else "",
                      "note": " | ".join(parts[3:]) if len(parts) > 3 else ""})
    return items, errors


@travel_reads_bp.route("/api/travel-reads/bulk", methods=["POST"])
@login_required
def bulk_add_travel_reads():
    """Add many links at once, in the order given: the first line shows
    first in the queue. Links already in the queue are skipped."""
    from datetime import timedelta, timezone
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}
    items, errors = parse_bulk(data.get("text"))
    if not items:
        return jsonify({"error": "No links found. One per line: URL | minutes | title | note",
                        "errors": errors}), 400
    if len(items) > _MAX_BULK:
        return jsonify({"error": f"Up to {_MAX_BULK} links at a time"}), 400
    priority = (data.get("priority") or "medium").strip().lower()
    if priority not in VALID_PRIORITIES:
        priority = "medium"
    try:
        have = {r.get("url") for r in (get("travel_reads", params={
            "user_id": f"eq.{user_id}", "status": "neq.archived",
            "select": "url", "limit": "1000"}) or [])}
    except Exception:
        have = set()
    now = datetime.now(timezone.utc)
    added, skipped = [], 0
    for i, it in enumerate(items):
        if it["url"] in have:
            skipped += 1
            continue
        have.add(it["url"])
        title = it["title"][:_MAX_TITLE]
        description = ""
        if not title:
            meta = fetch_meta(it["url"])
            title = (meta.get("title") or it["url"])[:_MAX_TITLE]
            description = (meta.get("description") or "")[:_MAX_DESC]
        kind = _normalize_kind("", it["url"])
        payload = {
            "user_id": user_id, "url": it["url"], "title": title, "description": description,
            "thumbnail_url": _thumbnail_for(it["url"], kind), "source": _source_from_url(it["url"]),
            "kind": kind, "duration_minutes": it["minutes"], "priority": priority,
            "status": "queued", "notes": it["note"][:_MAX_NOTES] or None,
            # Earlier lines get a later timestamp so they list first.
            "added_at": (now - timedelta(seconds=i)).isoformat(),
            "labels": auto_label(it["url"], title, description, kind, (it["minutes"] or 0) * 60),
        }
        try:
            rows = post("travel_reads", payload)
        except Exception as e:
            logger.error("travel_reads bulk insert failed: %s", e)
            errors.append(f"Could not save {it['url']}")
            continue
        if rows:
            added.append(rows[0])
    return jsonify({"ok": True, "added": len(added), "skipped": skipped,
                    "errors": errors, "items": added})


# ─── Ready-made packs (data/travel_packs/*.json) ──────────────────

import json as _json
import os as _os

_PACK_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "data", "travel_packs")


def _load_pack(slug):
    if not re.fullmatch(r"[a-z0-9-]{1,60}", slug or ""):
        return None
    try:
        with open(_os.path.join(_PACK_DIR, slug + ".json"), encoding="utf-8") as fh:
            return _json.load(fh)
    except (OSError, ValueError):
        return None


@travel_reads_bp.route("/api/travel-reads/packs", methods=["GET"])
@login_required
def list_packs():
    out = []
    try:
        names = sorted(f[:-5] for f in _os.listdir(_PACK_DIR) if f.endswith(".json"))
    except OSError:
        names = []
    for slug in names:
        pk = _load_pack(slug)
        if pk:
            items = pk.get("items") or []
            out.append({"slug": slug, "title": pk.get("title") or slug, "description": pk.get("description") or "",
                        "count": len(items), "minutes": sum(int(i.get("minutes") or 0) for i in items)})
    return jsonify({"packs": out})


@travel_reads_bp.route("/api/travel-reads/packs/<slug>/add", methods=["POST"])
@login_required
def add_pack(slug):
    """Queue every item of a pack, in order, with its notes. An item already
    in the queue is not added twice; if it has no notes yet, it gets the
    pack's notes."""
    from datetime import timedelta, timezone
    user_id = session["user_id"]
    pk = _load_pack(slug)
    if not pk:
        return jsonify({"error": "Pack not found"}), 404
    try:
        existing = {r.get("url"): r for r in (get("travel_reads", params={
            "user_id": f"eq.{user_id}", "status": "neq.archived",
            "select": "id,url,notes", "limit": "1000"}) or [])}
    except Exception:
        existing = {}
    now = datetime.now(timezone.utc)
    added = filled = 0
    for i, it in enumerate(pk.get("items") or []):
        url = it.get("url") or ""
        notes = (it.get("notes") or "")[:_MAX_NOTES] or None
        if url in existing:
            row = existing[url]
            if notes and not (row.get("notes") or "").strip():
                update("travel_reads", {"id": f"eq.{row['id']}", "user_id": f"eq.{user_id}"}, {"notes": notes})
                filled += 1
            continue
        kind = _normalize_kind(it.get("kind") or "", url)
        title = (it.get("title") or url)[:_MAX_TITLE]
        minutes = it.get("minutes")
        labels = auto_label(url, title, "", kind, int(minutes or 0) * 60)
        for extra in (it.get("labels") or []) + ["drivable"]:
            if extra not in labels:
                labels.append(extra)
        post("travel_reads", {
            "user_id": user_id, "url": url, "title": title,
            "description": (it.get("description") or "")[:_MAX_DESC],
            "thumbnail_url": _thumbnail_for(url, kind), "source": _source_from_url(url),
            "kind": kind, "duration_minutes": minutes, "priority": "medium", "status": "queued",
            "notes": notes, "labels": sorted(labels),
            "added_at": (now - timedelta(seconds=i)).isoformat(),
        })
        added += 1
    return jsonify({"ok": True, "added": added, "notes_filled": filled})


# ─── API: update fields ──────────────────────────────────────────


@travel_reads_bp.route("/api/travel-reads/<read_id>/update", methods=["POST"])
@login_required
def update_travel_read(read_id):
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}

    patch = {}
    if "title" in data:
        v = (data.get("title") or "").strip()
        if not v:
            return jsonify({"error": "Title required"}), 400
        patch["title"] = v[:_MAX_TITLE]
    if "description" in data:
        patch["description"] = (data.get("description") or "").strip()[:_MAX_DESC] or None
    if "kind" in data:
        v = (data.get("kind") or "").strip().lower()
        patch["kind"] = v if v in VALID_KINDS else "article"
    if "priority" in data:
        v = (data.get("priority") or "").strip().lower()
        patch["priority"] = v if v in VALID_PRIORITIES else "medium"
    if "duration_minutes" in data:
        v = data.get("duration_minutes")
        if v in (None, ""):
            patch["duration_minutes"] = None
        else:
            try:
                patch["duration_minutes"] = max(0, int(v))
            except (TypeError, ValueError):
                patch["duration_minutes"] = None
    if "notes" in data:
        patch["notes"] = (data.get("notes") or "").strip()[:_MAX_NOTES] or None
    if "labels" in data:
        patch["labels"] = _sanitize_labels(data.get("labels"))

    if not patch:
        return jsonify({"ok": True, "noop": True})

    try:
        update(
            "travel_reads",
            params={"id": f"eq.{read_id}", "user_id": f"eq.{user_id}"},
            json=patch,
        )
    except Exception as e:
        logger.error("travel_reads update failed: %s", e)
        return jsonify({"error": "Couldn't save — please try again."}), 502

    return jsonify({"ok": True, "patch": patch})


# ─── API: status ─────────────────────────────────────────────────


@travel_reads_bp.route("/api/travel-reads/<read_id>/status", methods=["POST"])
@login_required
def set_status(read_id):
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}
    new_status = (data.get("status") or "").strip().lower()
    if new_status not in VALID_STATUSES:
        return jsonify({"error": "invalid status"}), 400

    patch = {"status": new_status}
    now_iso = datetime.utcnow().isoformat()
    if new_status == "in_progress":
        patch["started_at"] = now_iso
    if new_status == "done":
        patch["finished_at"] = now_iso
    if new_status == "archived":
        patch["archived_at"] = now_iso

    try:
        update(
            "travel_reads",
            params={"id": f"eq.{read_id}", "user_id": f"eq.{user_id}"},
            json=patch,
        )
    except Exception as e:
        logger.error("travel_reads status update failed: %s", e)
        return jsonify({"error": "Couldn't update — please try again."}), 502

    return jsonify({"ok": True, "status": new_status})


@travel_reads_bp.route("/api/travel-reads/<read_id>/archive", methods=["POST"])
@login_required
def archive_travel_read(read_id):
    """Soft-delete shorthand — sets status='archived'."""
    user_id = session["user_id"]
    try:
        update(
            "travel_reads",
            params={"id": f"eq.{read_id}", "user_id": f"eq.{user_id}"},
            json={"status": "archived", "archived_at": datetime.utcnow().isoformat()},
        )
    except Exception as e:
        logger.error("travel_reads archive failed: %s", e)
        return jsonify({"error": "Couldn't remove — please try again."}), 502

    return jsonify({"ok": True})


# ─── API: transcript-paste ──────────────────────────────────────


_MAX_PASTE_CHARS = 500_000   # ~250 pages — generous, but bounded


def _save_transcript_note(user_id, item, text: str, source_label: str) -> str:
    """Persist `text` as a scribble note in the 'Transcripts' notebook
    and link it back to the travel_reads row. Returns the note id."""
    title = (item.get("title") or "Transcript").strip()[:200]
    note_payload = {
        "user_id": user_id,
        "title": f"📝 {title}",
        "content": (
            f"_{source_label} from [{item.get('url')}]({item.get('url')})_\n\n"
            + text
        ),
        "notebook": "Transcripts",
        "is_pinned": False,
    }
    note_rows = post("scribble_notes", note_payload)
    note_id = note_rows[0]["id"] if note_rows else None
    if not note_id:
        raise RuntimeError("Save returned no id.")
    try:
        update(
            "travel_reads",
            params={"id": f"eq.{item['id']}", "user_id": f"eq.{user_id}"},
            json={"transcript_note_id": note_id},
        )
    except Exception as e:
        logger.warning("link transcript_note_id failed: %s", e)
        # Note is saved either way; don't fail the request.
    return note_id


def _load_item(user_id: str, read_id: str):
    rows = get(
        "travel_reads",
        params={
            "id": f"eq.{read_id}",
            "user_id": f"eq.{user_id}",
            "select": "id,url,title,kind,transcript_note_id",
            "limit": "1",
        },
    ) or []
    return rows[0] if rows else None


@travel_reads_bp.route("/api/travel-reads/<read_id>/transcript-paste", methods=["POST"])
@login_required
def transcript_paste(read_id):
    """Save a transcript the user pasted in (option C — bypasses cloud-IP
    blocks on YouTube's caption endpoint by using the user's residential
    IP via a browser bookmarklet, or by copy-pasting from YouTube's
    'Show transcript' panel).

    Body: {"text": "..."}
    """
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Paste some transcript text first."}), 400
    if len(text) > _MAX_PASTE_CHARS:
        return jsonify({
            "error": f"Transcript too long — keep it under {_MAX_PASTE_CHARS:,} chars.",
        }), 413

    item = _load_item(user_id, read_id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    if item.get("transcript_note_id"):
        return jsonify({
            "ok": True,
            "already_transcribed": True,
            "note_id": item["transcript_note_id"],
        })

    try:
        note_id = _save_transcript_note(user_id, item, text, "Pasted transcript")
    except Exception as e:
        logger.error("paste transcript save failed: %s", e)
        return jsonify({"error": "Couldn't save transcript note."}), 502

    snippet = text[:280] + ("…" if len(text) > 280 else "")
    return jsonify({
        "ok": True,
        "note_id": note_id,
        "note_url": f"/notes/scribble/{note_id}",
        "char_count": len(text),
        "snippet": snippet,
    })
