import uuid
import os
import re
import logging
from datetime import date
from concurrent.futures import ThreadPoolExecutor

import requests as http_requests
from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for, flash
from supabase_client import get, post, update, delete
from services import shared_items_service
from services.login_service import login_required
from services.inbox_service import (
    detect_type, fetch_meta, auto_categorize, auto_label, KNOWN_LABELS,
)

logger = logging.getLogger("daily_plan")

inbox_bp = Blueprint("inbox_bp", __name__)

VALID_STATUSES = {"Unread", "Reading", "Done", "Saved"}

# Cap labels-per-item so a malicious or fat-fingered client can't shove
# 10k tags into one row. Five fixed-vocabulary labels exist today;
# allow some headroom for user-defined ones later.
_MAX_LABELS_PER_ITEM = 16
_MAX_LABEL_LEN = 32


def _sanitize_labels(raw) -> list[str]:
    """Normalise a labels patch from the client. Accepts a list of
    strings; trims, lowercases, drops empties and over-length entries,
    de-duplicates while preserving order, and caps the total. Returns
    an empty list (which clears the column) for null/non-list input —
    this is the user's intent when they unselect every chip."""
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


@inbox_bp.route("/inbox")
@login_required
def inbox_page():
    return render_template("inbox.html")


# Web Share Target (manifest.json → share_target.action). Android Chrome
# POSTs here as multipart/form-data when the user picks "DailyPlanner"
# from another app's share sheet, with the three params we declared
# (title, text, url). iOS doesn't support share_target — that's a
# Safari limitation, not something we can work around server-side.
_URL_RE = re.compile(r"https?://\S+")


@inbox_bp.route("/inbox/share", methods=["POST", "GET"])
def share_target():
    # NOTE: intentionally NOT decorated with @login_required so we can
    # stash unauthenticated shares in the session and finish them once
    # the user logs in. The share intent comes from another app — by
    # the time we redirect to /login the original POST body is gone, so
    # we save it ourselves before sending the user through auth.
    from flask_login import current_user

    # File shares (images / PDFs / docs from Android's share sheet) go to
    # chat, not the link inbox. Detect them up front. We can't stash a
    # binary across the login redirect, so an unauthenticated file share
    # just asks the user to log in and re-share.
    has_files = request.method == "POST" and any(
        f and f.filename for f in request.files.getlist("files")
    )

    if not current_user.is_authenticated:
        if has_files:
            try:
                flash("Open DailyPlanner, log in, then share the file again.", "warning")
            except Exception:
                pass
            return redirect(url_for("auth.login"))
        f = request.form if request.method == "POST" else request.args
        session["pending_share"] = {
            "url":   (f.get("url")   or "").strip(),
            "text":  (f.get("text")  or "").strip(),
            "title": (f.get("title") or "").strip(),
        }
        return redirect(url_for("auth.login", next="/inbox/share?resume=1"))

    if has_files:
        from routes.chat import handle_shared_files
        return handle_shared_files()

    # Resume path: after login, /inbox/share?resume=1 replays from session.
    if request.args.get("resume") == "1":
        stashed = session.pop("pending_share", None) or {}
        raw_url, raw_text, raw_title = (
            stashed.get("url", ""),
            stashed.get("text", ""),
            stashed.get("title", ""),
        )
    else:
        # Chrome sends form fields; some Android intents put the URL into
        # `text` instead of `url`. Fall back through title for completeness.
        f = request.form if request.method == "POST" else request.args
        raw_url   = (f.get("url")   or "").strip()
        raw_text  = (f.get("text")  or "").strip()
        raw_title = (f.get("title") or "").strip()

    candidate = raw_url
    if not candidate:
        # Pull the first http(s) URL out of the shared text/title blob.
        for src in (raw_text, raw_title):
            m = _URL_RE.search(src)
            if m:
                candidate = m.group(0).rstrip(").,;\"'")
                break

    if not candidate:
        # No URL anywhere — bounce to inbox with a hint. Better UX than a
        # silent failure; the user will at least know the share landed.
        try: flash("Share didn't include a link to save.", "warning")
        except Exception: pass
        return redirect(url_for("inbox_bp.inbox_page"))

    # Description: prefer text, then title; trim hard so AI/meta paths
    # don't see noise.
    desc = (raw_text if raw_text and raw_text != candidate else raw_title)[:500]

    # TWO STEPS (2026-10 redesign, "Share to Inbox" sheet). A share used to
    # be saved the instant it arrived, with whatever labels and category
    # the heuristics guessed, and always to the Inbox. Now the first hit
    # shows a short confirm page — preview, category, labels, and where it
    # goes (Inbox / TravelReads / References) — and the form on that page
    # posts back here with confirm=1 to save.
    if request.form.get("confirm") != "1":
        try:
            meta = fetch_meta(candidate)
        except Exception:
            logger.exception("share_target: metadata fetch failed for %s", candidate)
            meta = {}
        title = meta.get("title") or raw_title or candidate
        description = desc or meta.get("description") or ""
        content_type = detect_type(candidate)
        duration_seconds = int(meta.get("duration_seconds") or 0)
        try:
            category = auto_categorize(candidate, title, description)
            labels = auto_label(candidate, title, description, content_type, duration_seconds)
        except Exception:
            category, labels = "General", []
        return render_template(
            "inbox_share.html",
            url=candidate,
            domain=_share_domain(candidate),
            title=title,
            description=description,
            category=category,
            labels=list(labels or []),
            known_labels=sorted(KNOWN_LABELS),
            duration_seconds=duration_seconds,
            content_type=content_type,
        )

    # Step 2 — the confirm form. inbox_bp is CSRF-exempt because Android's
    # share sheet cannot send a token, but this form comes from our own
    # page, so its token is checked here.
    try:
        from flask_wtf.csrf import validate_csrf
        validate_csrf(request.form.get("csrf_token"))
    except Exception:
        return ("This page expired — share the link again.", 400)

    f = request.form
    title = (f.get("title") or candidate).strip()[:240]
    description = (f.get("description") or "").strip()[:600]
    category = (f.get("category") or "General").strip()[:60] or "General"
    labels = [l for l in f.getlist("labels") if l in KNOWN_LABELS]
    destination = f.get("destination") or "inbox"
    content_type = detect_type(candidate)
    try:
        duration_seconds = max(0, int(f.get("duration_seconds") or 0))
    except ValueError:
        duration_seconds = 0
    user_id = session["user_id"]

    try:
        if destination == "travel":
            row = {
                "user_id": user_id,
                "url": candidate,
                "title": title,
                "description": description,
                "source": _share_domain(candidate),
                "kind": "video" if content_type == "video" else "article",
                "priority": "high" if "priority" in labels else "medium",
                "status": "queued",
            }
            if duration_seconds:
                row["duration_minutes"] = max(1, round(duration_seconds / 60))
            post("travel_reads", row)
            flash("Saved to TravelReads.", "success")
            return redirect("/travel-reads")

        if destination == "references":
            import bleach
            post("reference_links", {
                "user_id": user_id,
                "title": title,
                "description": bleach.clean(description, tags=[], strip=True),
                "url": candidate,
                "tags": [],
                "category": category,
            })
            flash("Saved to References.", "success")
            return redirect("/references")

        row = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "url": candidate,
            "title": title,
            "description": description,
            "content_type": content_type,
            "category": category,
            "status": "Unread",
            "labels": labels,
        }
        if duration_seconds:
            row["duration_seconds"] = duration_seconds
        # Share-target POSTs from Android may be replayed by the Web Share
        # Target flow; dedupe via X-Client-Id if the sender provided one.
        share_client_id = request.headers.get("X-Client-Id") or None
        if share_client_id:
            row["client_id"] = share_client_id
            post(
                "inbox_links?on_conflict=user_id,client_id",
                row,
                prefer="resolution=merge-duplicates",
            )
        else:
            post("inbox_links", row)
    except Exception:
        # Don't 500 the share — land them somewhere they can retry.
        logger.exception("share_target failed for url=%s", candidate)
        try: flash("Couldn't save that link — try again from the inbox.", "error")
        except Exception: pass

    return redirect(url_for("inbox_bp.inbox_page"))


def _share_domain(url):
    try:
        from urllib.parse import urlparse
        return (urlparse(url).hostname or "").replace("www.", "")
    except Exception:
        return ""


@inbox_bp.route("/api/inbox", methods=["POST"])
@login_required
def create_inbox():
    data = request.get_json() or {}
    user_id = session["user_id"]

    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "url required"}), 400

    meta = fetch_meta(url)
    title = meta["title"]
    raw_desc = data.get("description", "").strip() or meta["description"]
    content_type = detect_type(url)
    category = auto_categorize(url, title, raw_desc)

    # AI-powered description if user didn't provide one and meta description
    # is weak. Skipped entirely for YouTube URLs because fetch_meta() now
    # gets the real description via the YouTube Data API — no need to ask
    # the AI to invent one.
    description = raw_desc
    is_youtube = bool(re.search(r"(?:youtube\.com|youtu\.be)", url, re.IGNORECASE))
    if (
        not data.get("description", "").strip()
        and len(raw_desc) < 50
        and not is_youtube
    ):
        try:
            from services.ai_service import call_gemini
            # Prompt is explicit that the AI should NOT try to fetch the
            # URL — earlier prompts asked "describe what this webpage is
            # about" and Gemini interpreted that as needing to visit the
            # page, then refused with "I don't have the ability to access
            # the webpage directly..." which leaked into descriptions.
            prompt = (
                "Write a one-sentence factual description of this link "
                "based ONLY on the title and URL below. Do NOT try to "
                "fetch the page. If you have no useful information, "
                "reply with the single word: SKIP.\n\n"
                f"Title: {title}\n"
                f"URL: {url}"
            )
            ai_desc = (call_gemini(prompt) or "").strip()
            if _ai_response_is_useful(ai_desc):
                description = ai_desc[:500]
        except Exception:
            pass  # Fall back to raw meta description

    duration_seconds = int(meta.get("duration_seconds") or 0)
    labels = auto_label(url, title, description, content_type, duration_seconds)

    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "url": url,
        "title": title,
        "description": description,
        "content_type": content_type,
        "category": category,
        "status": "Unread",
        "labels": labels,
    }
    # Source publish date — only YouTube fills this in today (via the
    # Data API), so non-YouTube saves leave the column NULL.
    if meta.get("published_at"):
        row["published_at"] = meta["published_at"]
    if duration_seconds:
        row["duration_seconds"] = duration_seconds
    # Idempotency for offline replays: see MIGRATION_OFFLINE_IDEMPOTENCY.
    client_id = (
        request.headers.get("X-Client-Id")
        or (data.get("client_id") or "").strip()
        or None
    )
    if client_id:
        row["client_id"] = client_id
        post(
            "inbox_links?on_conflict=user_id,client_id",
            row,
            prefer="resolution=merge-duplicates",
        )
    else:
        post("inbox_links", row)

    return jsonify({
        "success": True,
        "title": title,
        "description": description,
        "category": category,
        "content_type": content_type,
    })


@inbox_bp.route("/api/inbox", methods=["GET"])
@login_required
def get_inbox():
    user_id = session["user_id"]
    status_filter = request.args.get("status")
    category_filter = request.args.get("category")

    params = {
        "user_id": f"eq.{user_id}",
        "order": "created_at.desc",
        "select": (
            "id,url,title,description,content_type,is_favorite,category,"
            "status,created_at,published_at,duration_seconds,labels,"
            "transcript_note_id"
        ),
    }
    if status_filter:
        params["status"] = f"eq.{status_filter}"
    if category_filter:
        params["category"] = f"eq.{category_filter}"

    rows = get("inbox_links", params=params) or []

    # ── ITEMS OTHER PEOPLE SHARED WITH ME ────────────────────────────
    # Appended rather than merged into the query above, because the two
    # are authorised differently: mine are "user_id is me", theirs are
    # "there is a grant addressed to me". The id list that lifts the
    # user_id filter comes ONLY from those grants — that list IS the
    # authorisation, and nothing else may widen it.
    try:
        shares = get("shared_items", params={
            "shared_with": f"eq.{user_id}",
            "kind": "eq.inbox",
            "select": "item_ref,owner_id",
        }) or []
    except Exception:
        shares = []                      # table not migrated yet: own items only

    if shares:
        owner_of = {s["item_ref"]: s.get("owner_id") for s in shares if s.get("item_ref")}
        ids = ",".join(owner_of.keys())
        shared_params = {
            "id": f"in.({ids})",
            "order": "created_at.desc",
            "select": params["select"] + ",user_id",
        }
        if status_filter:
            shared_params["status"] = f"eq.{status_filter}"
        if category_filter:
            shared_params["category"] = f"eq.{category_filter}"
        shared_rows = get("inbox_links", params=shared_params) or []
        names = shared_items_service.display_names(
            [r.get("user_id") for r in shared_rows])
        mine = {r["id"] for r in rows}
        for r in shared_rows:
            if r["id"] in mine:
                continue                 # shared back to me; my own copy wins
            r.pop("user_id", None)
            # Says on the card who sent it, and that it is not yours to
            # edit — the writes below would silently no-op otherwise.
            r["shared_by"] = names.get(owner_of.get(r["id"]), "someone")
            r["can_edit"] = False
            rows.append(r)
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)

    # How many people each of MY items is shared with, for the chip on
    # the card. One query for the page, not one per card.
    if rows:
        try:
            out = get("shared_items", params={
                "owner_id": f"eq.{user_id}",
                "kind": "eq.inbox",
                "select": "item_ref,shared_with",
            }) or []
        except Exception:
            out = []
        counts = {}
        for sh in out:
            counts[sh["item_ref"]] = counts.get(sh["item_ref"], 0) + 1
        for r in rows:
            if not r.get("shared_by"):
                r["shared_with_count"] = counts.get(r["id"], 0)

    return jsonify(rows)


@inbox_bp.route("/api/inbox/<item_id>", methods=["PATCH"])
@login_required
def update_inbox(item_id):
    user_id = session["user_id"]
    data = request.get_json() or {}

    allowed = {}
    if "status" in data:
        if data["status"] not in VALID_STATUSES:
            return jsonify({"error": "invalid status"}), 400
        allowed["status"] = data["status"]
    if "category" in data:
        allowed["category"] = data["category"]
    if "title" in data:
        allowed["title"] = data["title"]
    if "description" in data:
        allowed["description"] = data["description"]
    if "labels" in data:
        allowed["labels"] = _sanitize_labels(data.get("labels"))

    if not allowed:
        return jsonify({"error": "nothing to update"}), 400

    # Conflict detection for offline edits: clients that queued a write
    # while offline include If-Unmodified-Since with the row's
    # updated_at as of the queue time. When the SW replays, if the row
    # has been touched on another device in the meantime, we return
    # 409 with both versions so the page can ask the user what to keep.
    if_unmod = request.headers.get("If-Unmodified-Since")
    if if_unmod:
        rows = get(
            "inbox_links",
            params={
                "id":      f"eq.{item_id}",
                "user_id": f"eq.{user_id}",
                "select":  "id,updated_at,status,category,title,description,labels",
            },
        ) or []
        if rows and (rows[0].get("updated_at") or "") > if_unmod:
            return jsonify({
                "error":  "conflict",
                "server": rows[0],
                "client": allowed,
            }), 409

    # OWNERSHIP IS THE FILTER, and it has to be SAID. The update below
    # matches nothing when the item belongs to someone else — which is
    # correct — but replying {"success": true} to a write that changed
    # no rows tells a recipient of a shared item that their edit stuck.
    # It did not. Shared items are read-only for the recipient.
    owned = get("inbox_links", params={
        "id": f"eq.{item_id}", "user_id": f"eq.{user_id}",
        "select": "id", "limit": "1",
    }) or []
    if not owned:
        return jsonify({
            "error": "This item belongs to someone else — you can read it, "
                     "but only its owner can change it.",
        }), 403

    update("inbox_links", params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"}, json=allowed)
    return jsonify({"success": True})


@inbox_bp.route("/api/inbox/<item_id>/favorite", methods=["POST"])
@login_required
def favorite(item_id):
    user_id = session["user_id"]

    rows = get("inbox_links", params={
        "id": f"eq.{item_id}",
        "user_id": f"eq.{user_id}",
        "select": "id,is_favorite",
    }) or []

    if not rows:
        return jsonify({"error": "not found"}), 404

    current = rows[0].get("is_favorite", False)
    update("inbox_links", params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"}, json={"is_favorite": not current})
    return jsonify({"success": True})


@inbox_bp.route("/api/inbox/<item_id>", methods=["DELETE"])
@login_required
def delete_inbox(item_id):
    user_id = session["user_id"]
    # Same reason as the PATCH above: a recipient deleting a shared item
    # must be told it is not theirs, not shown a success for a delete
    # that removed nothing and a card that reappears on refresh.
    owned = get("inbox_links", params={
        "id": f"eq.{item_id}", "user_id": f"eq.{user_id}",
        "select": "id", "limit": "1",
    }) or []
    if not owned:
        return jsonify({
            "error": "This item belongs to someone else — only its owner "
                     "can remove it.",
        }), 403
    delete("inbox_links", params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"})
    return jsonify({"success": True})


# Google API error reasons → human hints. Lets the Inbox surface the
# actual cause (e.g. key missing YouTube Data API in its allowlist)
# instead of a vague "search unavailable" so the user can fix it.
_GOOGLE_ERROR_HINTS = {
    "API_KEY_SERVICE_BLOCKED": (
        "API key isn't authorised for this service. In Google Cloud Console "
        "→ APIs & Services → Credentials, open the key, and either pick "
        "'Don't restrict key' or add this API to the allowed list."
    ),
    "API_DISABLED": (
        "API not enabled on this Google Cloud project. Enable it under "
        "APIs & Services → Library."
    ),
    "rateLimitExceeded": (
        "Daily search limit reached (100 free queries/day). Resets at "
        "midnight US Pacific time. Raise the cap in Google Cloud Console "
        "if you want more (Custom Search bills $5 per 1,000 queries above "
        "the free tier)."
    ),
    "quotaExceeded": (
        "Daily search limit reached (100 free queries/day). Resets at "
        "midnight US Pacific time. Raise the cap in Google Cloud Console "
        "if you want more (Custom Search bills $5 per 1,000 queries above "
        "the free tier)."
    ),
    "keyInvalid": "API key is invalid. Check GOOGLE_API_KEY in .env.",
    "keyExpired": "API key has expired.",
    "ipRefererBlocked": (
        "API key has HTTP-referrer / IP restrictions that block server-side "
        "calls. Remove or relax those restrictions on the key."
    ),
}

# Reasons we want the frontend to show as a *visible* banner instead of
# hiding the section. Quota errors are expected, actionable info; config
# errors (key restrictions, billing) are noise after the user has set up
# the integration once.
_GOOGLE_QUOTA_REASONS = {"rateLimitExceeded", "quotaExceeded"}


def _google_error_kind(payload):
    """Classify a Google error response as 'quota' (worth showing to the
    user) or 'config' (worth hiding once setup is done). Returned as a
    side-channel so the frontend can pick which one to surface."""
    err = (payload or {}).get("error", {}) or {}
    for det in err.get("details", []) or []:
        if det.get("reason") in _GOOGLE_QUOTA_REASONS:
            return "quota"
    for e in err.get("errors", []) or []:
        if e.get("reason") in _GOOGLE_QUOTA_REASONS:
            return "quota"
    return "config"


def _google_error_hint(payload):
    """Pull the actionable hint from a Google API error body. Looks at the
    structured `error.details[].reason` first (newer APIs), then falls back
    to legacy `error.errors[].reason`, then to `error.message`."""
    err = (payload or {}).get("error", {}) or {}
    for det in err.get("details", []) or []:
        reason = det.get("reason")
        if reason in _GOOGLE_ERROR_HINTS:
            return _GOOGLE_ERROR_HINTS[reason]
    for e in err.get("errors", []) or []:
        reason = e.get("reason")
        if reason in _GOOGLE_ERROR_HINTS:
            return _GOOGLE_ERROR_HINTS[reason]
    return err.get("message") or "Search unavailable"


# LLM refusal phrases we don't want leaking into the description field.
# Gemini in particular loves to apologise when it can't do what you
# asked; these openers are the dead giveaway. Match is case-insensitive
# and only at the start of the response so legitimate descriptions
# containing these phrases are not over-filtered.
_AI_REFUSAL_PREFIXES = (
    "unfortunately",
    "i don't have",
    "i do not have",
    "i can't",
    "i cannot",
    "i'm unable",
    "i am unable",
    "without more",
    "without further",
    "as an ai",
    "i'm sorry",
    "i am sorry",
    "ai service",   # historic prefix our wrapper used for upstream errors
    "skip",         # explicit signal we asked for in the prompt
)


def _ai_response_is_useful(text):
    """Return True only if the AI gave us something we'd actually want to
    save as a description — long enough to be informative and not opening
    with a refusal / apology / SKIP signal."""
    if not text or len(text) < 15:
        return False
    lowered = text.lower().lstrip("*-_ \t\n")
    for prefix in _AI_REFUSAL_PREFIXES:
        if lowered.startswith(prefix):
            return False
    return True


_YT_ID_RE_PY = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def _yt_extract_id(url: str) -> str | None:
    m = _YT_ID_RE_PY.search(url or "")
    return m.group(1) if m else None


def _yt_parse_duration(iso: str) -> int:
    """ISO 8601 duration ('PT1H23M45S', 'PT5M30S') → total seconds.
    Returns 0 for unparseable input rather than raising — view fields
    should never blow up the search response."""
    if not iso or not iso.startswith("PT"):
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return 0
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def _yt_enrich(items: list, api_key: str, prefetched_channel_ids: list = None) -> list:
    """Decorate YouTube search results with duration, view count,
    channel id, and subscriber count.

    Calls youtube/v3/videos for duration+views+channelId, and
    youtube/v3/channels for subscriber counts. The two calls are
    fired in parallel via ThreadPoolExecutor — saves ~200ms per
    search vs running them sequentially.

    Channel ids passed via `prefetched_channel_ids` (e.g. extracted
    from a search.list response) let the channels call run without
    waiting for the videos call to finish first. If not provided,
    the channels call is fired with an empty id list initially and
    re-fired once videos.list returns the channel ids — slightly
    slower but still correct.

    Best-effort: any sub-call failure leaves the field as None and
    returns the items as-is rather than failing the whole search.
    Total cost: 2 quota units."""
    if not items:
        return items
    video_ids = [_yt_extract_id(it.get("url") or "") for it in items]
    video_ids = [v for v in video_ids if v]
    if not video_ids:
        return items

    def _fetch_videos():
        out = {}
        try:
            r = http_requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "id": ",".join(video_ids),
                    "part": "contentDetails,statistics,snippet",
                    "key": api_key,
                },
                timeout=8,
            )
            if r.status_code == 200:
                for v in r.json().get("items", []):
                    out[v["id"]] = {
                        "duration_seconds": _yt_parse_duration(
                            v.get("contentDetails", {}).get("duration", "")
                        ),
                        "view_count": int(
                            v.get("statistics", {}).get("viewCount", 0) or 0
                        ),
                        "channel_id": v.get("snippet", {}).get("channelId", ""),
                    }
            else:
                logger.warning("yt_enrich videos.list http=%s body=%r",
                               r.status_code, r.text[:200])
        except Exception as e:
            logger.warning("yt_enrich videos.list exception: %s", e)
        return out

    def _fetch_channels(channel_ids):
        out = {}
        if not channel_ids:
            return out
        try:
            r = http_requests.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={
                    "id": ",".join(channel_ids),
                    "part": "statistics",
                    "key": api_key,
                },
                timeout=8,
            )
            if r.status_code == 200:
                for c in r.json().get("items", []):
                    stats = c.get("statistics", {}) or {}
                    if stats.get("hiddenSubscriberCount"):
                        out[c["id"]] = None
                    else:
                        out[c["id"]] = int(stats.get("subscriberCount", 0) or 0)
            else:
                logger.warning("yt_enrich channels.list http=%s body=%r",
                               r.status_code, r.text[:200])
        except Exception as e:
            logger.warning("yt_enrich channels.list exception: %s", e)
        return out

    if prefetched_channel_ids:
        # Fire both in parallel — channels call doesn't need to wait
        # for videos.list because the caller already harvested the
        # channel ids from the search response.
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_videos = pool.submit(_fetch_videos)
            f_channels = pool.submit(
                _fetch_channels, list(set(prefetched_channel_ids))
            )
            video_meta = f_videos.result()
            channel_subs = f_channels.result()
    else:
        # Fall back to the sequential path when channel ids aren't
        # available upfront (e.g. _yt_enrich is reused from the
        # channel-uploads endpoint, where the search response shape
        # is different).
        video_meta = _fetch_videos()
        channel_ids_from_videos = list({
            m["channel_id"] for m in video_meta.values() if m.get("channel_id")
        })
        channel_subs = _fetch_channels(channel_ids_from_videos)

    enriched = []
    for it in items:
        vid = _yt_extract_id(it.get("url") or "") or ""
        meta = video_meta.get(vid, {})
        cid = meta.get("channel_id") or it.get("channel_id") or ""
        out = dict(it)
        out["duration_seconds"] = meta.get("duration_seconds", 0)
        out["view_count"] = meta.get("view_count", 0)
        out["channel_id"] = cid
        out["subscriber_count"] = channel_subs.get(cid)
        enriched.append(out)
    return enriched


def _cse_thumbnail(item):
    """CSE thumbnails appear under different pagemap keys depending on the
    site. Pick the first one that exists, return "" otherwise."""
    pagemap = item.get("pagemap", {}) or {}
    for k in ("cse_thumbnail", "cse_image"):
        arr = pagemap.get(k) or []
        if arr and arr[0].get("src"):
            return arr[0]["src"]
    return ""


def _key_fingerprint(api_key):
    """Render the API key as <first 8>...<last 5> so it's identifiable
    in logs without exposing the secret. Five trailing chars matches
    the user's request and makes it trivial to compare with what's in
    Google Cloud Console (which shows the full key on click)."""
    if not api_key:
        return "<missing>"
    if len(api_key) <= 13:
        return "<short:%d>" % len(api_key)
    return "%s...%s" % (api_key[:8], api_key[-5:])


def _log_google_failure(label, response, query, api_key, cx=None):
    """Dump everything useful from a Google API failure: status, the exact
    machine-readable reason codes (errors[].reason + details[].reason +
    metadata.consumer/service), the message, response headers that hint
    at quota / billing, and a truncated body. Lets a future read of the
    log answer "why did this 403?" without having to reproduce.

    project_number is parsed out of the consumer field ("projects/12345")
    and given its own slot so you can read it at a glance — answering
    "did Google see the call hit the project I expected?"."""
    try:
        payload = response.json()
    except Exception:
        payload = {}
    err = (payload or {}).get("error", {}) or {}
    reasons = [e.get("reason") for e in err.get("errors", []) or [] if e.get("reason")]
    detail_reasons = [d.get("reason") for d in err.get("details", []) or [] if d.get("reason")]
    consumer = service = None
    for d in err.get("details", []) or []:
        md = d.get("metadata") or {}
        if md.get("consumer") and not consumer:
            consumer = md["consumer"]
        if md.get("service") and not service:
            service = md["service"]
    project_number = None
    if consumer and consumer.startswith("projects/"):
        project_number = consumer.split("/", 1)[1]
    quota_headers = {
        k: response.headers.get(k)
        for k in ("X-Goog-Quota-User", "Retry-After", "X-RateLimit-Remaining")
        if response.headers.get(k)
    }
    logger.warning(
        "%s search FAILED: http=%s status=%s key=%s cx=%s "
        "project_number=%s service=%s reasons=%s details=%s "
        "quota_headers=%s msg=%r query=%r body=%r",
        label,
        response.status_code,
        err.get("status"),
        _key_fingerprint(api_key),
        cx or "<n/a>",
        project_number,
        service,
        reasons,
        detail_reasons,
        quota_headers,
        (err.get("message") or "")[:300],
        query[:80],
        response.text[:500],
    )


def _extract_readable_html(html: str) -> dict:
    """Heuristic article-content extractor. Looks for the densest text
    container (<article>, <main>, or the <div> with the most direct text),
    strips chrome (nav/aside/footer/script), and sanitises with bleach
    so we never inject untrusted markup straight into the page.

    Returns {title, byline, content, length} where content is sanitised
    HTML safe to drop into innerHTML."""
    from bs4 import BeautifulSoup
    import bleach

    soup = BeautifulSoup(html or "", "lxml")

    # Title: prefer og:title, then <title>.
    title = ""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    if not title and soup.title:
        title = (soup.title.get_text() or "").strip()

    # Byline: try common author meta tags.
    byline = ""
    for sel in (
        ("meta", {"name": "author"}),
        ("meta", {"property": "article:author"}),
    ):
        tag = soup.find(*sel)
        if tag and tag.get("content"):
            byline = tag["content"].strip()
            break

    # Strip stuff that's never article content. Removed in-place so the
    # remaining tree only has body-ish elements when we look for the
    # main container below.
    for tag_name in (
        "script", "style", "noscript", "iframe", "form", "button",
        "nav", "aside", "footer", "header", "menu",
    ):
        for tag in soup.find_all(tag_name):
            tag.decompose()
    # Strip elements with role="navigation" / "banner" / "contentinfo".
    for tag in soup.find_all(attrs={"role": ["navigation", "banner", "contentinfo"]}):
        tag.decompose()

    # Find the densest text container. <article> is the canonical hint;
    # fall back to <main>, then to whichever <div> has the most direct
    # paragraph text.
    container = soup.find("article") or soup.find("main")
    if not container:
        candidates = []
        for div in soup.find_all(["div", "section"]):
            text = div.get_text(" ", strip=True)
            if len(text) > 200:
                candidates.append((len(text), div))
        if candidates:
            candidates.sort(reverse=True)
            container = candidates[0][1]
    if not container:
        container = soup.body or soup

    # Sanitise — keep only readable tags + safe attrs.
    raw = str(container)
    allowed_tags = [
        "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
        "a", "ul", "ol", "li", "blockquote", "pre", "code",
        "em", "strong", "i", "b", "u", "s",
        "img", "figure", "figcaption",
        "table", "thead", "tbody", "tr", "th", "td",
        "div", "span",
    ]
    allowed_attrs = {
        "*": ["class"],
        "a": ["href", "title", "rel", "target"],
        "img": ["src", "alt", "width", "height"],
    }
    cleaned = bleach.clean(
        raw,
        tags=allowed_tags,
        attributes=allowed_attrs,
        strip=True,
    )
    # Force every link to open in a new tab — we're showing a remote
    # article inline, links should not nuke the planner page.
    cleaned = bleach.linkify(
        cleaned,
        callbacks=[bleach.callbacks.target_blank, bleach.callbacks.nofollow],
        skip_tags=["pre", "code"],
    )

    return {
        "title": title,
        "byline": byline,
        "content": cleaned,
        "length": len(cleaned),
    }


_MAX_TRANSCRIPT_CHARS = 500_000   # ~250 pages, generous but bounded


def _resolve_default_project(user_id):
    """Find the user's default project (is_default=true), falling back
    to one literally named 'Inbox'. Returns project_id or None.
    Mirrors the helper agenda_service uses so the watch-today task
    lands in the same project as auto-converted notes."""
    rows = get("projects", params={
        "user_id": f"eq.{user_id}",
        "is_default": "eq.true",
        "is_archived": "eq.false",
        "select": "project_id",
        "limit": "1",
    }) or []
    if rows:
        return rows[0]["project_id"]
    rows = get("projects", params={
        "user_id": f"eq.{user_id}",
        "name": "ilike.Inbox",
        "is_archived": "eq.false",
        "select": "project_id",
        "limit": "1",
    }) or []
    return rows[0]["project_id"] if rows else None


@inbox_bp.route("/api/inbox/<item_id>/watch-today", methods=["POST"])
@login_required
def watch_today(item_id):
    """Schedule an inbox item for today's plan by creating a project
    task with the link in the notes field, due_date = today. The task
    flows into Today's Plan automatically because the dashboard pulls
    open tasks with due_date = today across all projects.

    The inbox row's status flips to 'Reading' so the user can tell at
    a glance which items are queued for today vs still untriaged."""
    user_id = session["user_id"]

    rows = get("inbox_links", params={
        "id": f"eq.{item_id}",
        "user_id": f"eq.{user_id}",
        "select": "id,url,title,content_type",
        "limit": "1",
    }) or []
    if not rows:
        return jsonify({"error": "not found"}), 404
    item = rows[0]

    project_id = _resolve_default_project(user_id)
    if not project_id:
        return jsonify({
            "error": (
                "No default project found. Open Projects, mark one as "
                "default (or create one named 'Inbox'), then try again."
            ),
        }), 422

    # Compose a one-line task title. Prepend a play emoji so the row
    # is identifiable as an inbox-watch item in the project list.
    title = (item.get("title") or item.get("url") or "Watch link")[:240]
    is_video = (item.get("content_type") or "").lower() == "video"
    prefix = "▶ " if is_video else "📖 "
    task_text = f"{prefix}{title}"
    today_str = date.today().isoformat()
    notes_body = f"From inbox · {item.get('url') or ''}"

    try:
        post("project_tasks", {
            "project_id": project_id,
            "user_id": user_id,
            "task_text": task_text,
            "notes": notes_body,
            "due_date": today_str,
            "priority": "medium",
            "priority_rank": 2,
            "status": "open",
        })
    except Exception as e:
        logger.warning("watch_today task insert failed: %s", e)
        return jsonify({"error": f"Could not create task: {e}"}), 500

    # Flip inbox status to Reading so the card visually distinguishes
    # itself from untriaged Unread items.
    try:
        update(
            "inbox_links",
            params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
            json={"status": "Reading"},
        )
    except Exception as e:
        logger.warning("watch_today status update failed: %s", e)

    return jsonify({"ok": True, "due_date": today_str})


@inbox_bp.route("/api/inbox/<item_id>/transcript-auto", methods=["POST"])
@login_required
def transcript_auto(item_id):
    """Best-effort: try fetching the YouTube transcript server-side via
    youtube-transcript-api (no key needed). Returns 200 on success with
    the saved note id; returns 422 'unavailable' on failure so the
    frontend can pop the manual paste modal as a fallback.

    YouTube blocks /api/timedtext from cloud-host IPs (Render, AWS,
    GCP) so a meaningful fraction of these calls fail with IpBlocked
    or NoTranscriptFound — we don't treat that as a server error."""
    user_id = session["user_id"]

    rows = get("inbox_links", params={
        "id": f"eq.{item_id}",
        "user_id": f"eq.{user_id}",
        "select": "id,url,title,transcript_note_id",
        "limit": "1",
    }) or []
    if not rows:
        return jsonify({"error": "not found"}), 404
    item = rows[0]

    if item.get("transcript_note_id"):
        return jsonify({
            "ok": True,
            "note_id": item["transcript_note_id"],
            "existing": True,
        })

    vid = _yt_extract_id(item.get("url") or "")
    if not vid:
        return jsonify({"error": "Not a YouTube URL"}), 400

    # Lazy import — keeps Flask boot fast for users who never use
    # this feature, and means the dependency missing only breaks
    # this single endpoint rather than the whole app.
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            TranscriptsDisabled, NoTranscriptFound, VideoUnavailable,
        )
    except ImportError:
        logger.warning("transcript_auto: youtube_transcript_api not installed")
        return jsonify({
            "error": "auto-transcript not available — paste manually",
            "fallback": "paste",
        }), 422

    try:
        # Prefer English transcripts; fall back to whatever's available.
        try:
            tx = YouTubeTranscriptApi.get_transcript(vid, languages=["en"])
        except NoTranscriptFound:
            tx = YouTubeTranscriptApi.get_transcript(vid)
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
        logger.info("transcript_auto unavailable for %s: %s", vid, e.__class__.__name__)
        return jsonify({
            "error": f"Transcript unavailable: {e.__class__.__name__}",
            "fallback": "paste",
        }), 422
    except Exception as e:
        # IP-blocked errors come back as a generic Exception with
        # "blocked" / "Too Many Requests" in the message. Log + fall
        # back to manual paste rather than 500-ing.
        logger.info(
            "transcript_auto failed for %s (likely cloud-IP block): %s",
            vid, str(e)[:200],
        )
        return jsonify({
            "error": "Transcript fetch blocked — try the bookmarklet",
            "fallback": "paste",
        }), 422

    # Flatten the segment list into a single paragraph of text.
    text = " ".join((seg.get("text") or "").strip() for seg in tx if seg.get("text"))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return jsonify({"error": "Transcript was empty", "fallback": "paste"}), 422
    if len(text) > _MAX_TRANSCRIPT_CHARS:
        text = text[:_MAX_TRANSCRIPT_CHARS]

    title = (item.get("title") or "Transcript").strip()[:200]
    url = item.get("url") or ""
    note_payload = {
        "user_id": user_id,
        "title": f"📝 {title}",
        "content": (
            f"_Auto-captured transcript from [{url}]({url})_\n\n"
            + text
        ),
        "notebook": "Transcripts",
        "is_pinned": False,
    }
    try:
        note_rows = post("scribble_notes", note_payload)
        note_id = note_rows[0]["id"] if note_rows else None
        if not note_id:
            raise RuntimeError("Note save returned no id.")
    except Exception as e:
        logger.warning("transcript_auto note insert failed: %s", e)
        return jsonify({"error": f"Could not save transcript: {e}"}), 500

    try:
        update(
            "inbox_links",
            params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
            json={"transcript_note_id": note_id},
        )
    except Exception as e:
        logger.warning("transcript_auto back-link failed: %s", e)

    return jsonify({"ok": True, "note_id": note_id, "existing": False, "auto": True})


@inbox_bp.route("/api/inbox/<item_id>/transcript-paste", methods=["POST"])
@login_required
def transcript_paste(item_id):
    """Save a transcript the user pasted in. Mirrors the TravelReads
    flow: server-side fetching of YouTube captions is blocked from
    cloud-host IPs, so the user grabs the transcript on their own
    machine (via bookmarklet or YouTube's "Show transcript" panel)
    and pastes it here.

    The transcript is stored as a scribble note in the 'Transcripts'
    notebook with a markdown link back to the original YouTube URL.
    The note id is back-referenced on the inbox row so the card can
    show "View transcript" instead of "Transcribe" on subsequent
    visits.

    Body: {"text": "..."}
    """
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Paste some transcript text first."}), 400
    if len(text) > _MAX_TRANSCRIPT_CHARS:
        return jsonify({
            "error": f"Transcript too long — keep it under {_MAX_TRANSCRIPT_CHARS:,} chars.",
        }), 413

    rows = get("inbox_links", params={
        "id": f"eq.{item_id}",
        "user_id": f"eq.{user_id}",
        "select": "id,url,title,transcript_note_id",
        "limit": "1",
    }) or []
    if not rows:
        return jsonify({"error": "Not found"}), 404
    item = rows[0]

    # If a transcript already exists, hand back the existing note id
    # rather than silently appending — keeps notes deduplicated.
    if item.get("transcript_note_id"):
        return jsonify({
            "ok": True,
            "note_id": item["transcript_note_id"],
            "existing": True,
        })

    title = (item.get("title") or "Transcript").strip()[:200]
    url = item.get("url") or ""
    note_payload = {
        "user_id": user_id,
        "title": f"📝 {title}",
        "content": (
            f"_Transcript from [{url}]({url})_\n\n"
            + text
        ),
        "notebook": "Transcripts",
        "is_pinned": False,
    }
    try:
        note_rows = post("scribble_notes", note_payload)
        note_id = note_rows[0]["id"] if note_rows else None
        if not note_id:
            raise RuntimeError("Note save returned no id.")
    except Exception as e:
        logger.warning("transcript_paste note insert failed: %s", e)
        return jsonify({"error": f"Could not save transcript: {e}"}), 500

    try:
        update(
            "inbox_links",
            params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
            json={"transcript_note_id": note_id},
        )
    except Exception as e:
        # Note is saved either way; don't fail the request just because
        # the back-reference didn't persist. The user can still find
        # the transcript via Notes → Transcripts.
        logger.warning("transcript_paste back-link failed: %s", e)

    return jsonify({"ok": True, "note_id": note_id, "existing": False})


@inbox_bp.route("/api/inbox/<item_id>/move-to-travel", methods=["POST"])
@login_required
def move_to_travel(item_id):
    """Copy an inbox item into travel_reads, then soft-delete the inbox row.
    Per project policy (no hard delete), the original is marked done so
    the user can still find it via the Done filter if they regret it."""
    user_id = session["user_id"]

    rows = get("inbox_links", params={
        "id": f"eq.{item_id}",
        "user_id": f"eq.{user_id}",
        "select": "id,url,title,description,content_type,category",
    }) or []
    if not rows:
        return jsonify({"error": "not found"}), 404

    src = rows[0]
    url = src.get("url") or ""
    if not url:
        return jsonify({"error": "saved row has no url"}), 422

    # Map inbox content_type → travel_reads kind. Inbox uses "video" for
    # YouTube already; everything else collapses to "article".
    kind = "video" if (src.get("content_type") or "").lower() == "video" else "article"
    domain = ""
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).hostname or ""
        domain = domain.replace("www.", "")
    except Exception:
        pass

    # If it's a YouTube URL, fetch real duration so the queue total is
    # accurate without the user having to type a number.
    duration_minutes = None
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if api_key:
        vid = _yt_extract_id(url)
        if vid:
            try:
                r = http_requests.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={"id": vid, "part": "contentDetails", "key": api_key},
                    timeout=6,
                )
                if r.status_code == 200:
                    items = r.json().get("items", [])
                    if items:
                        secs = _yt_parse_duration(
                            items[0].get("contentDetails", {}).get("duration", "")
                        )
                        if secs:
                            duration_minutes = max(1, round(secs / 60))
            except Exception:
                pass

    travel_row = {
        "user_id": user_id,
        "url": url,
        "title": (src.get("title") or url)[:240],
        "description": (src.get("description") or "")[:600],
        "source": domain,
        "kind": kind,
        "priority": "medium",
        "status": "queued",
    }
    if duration_minutes:
        travel_row["duration_minutes"] = duration_minutes

    try:
        post("travel_reads", travel_row)
    except Exception as e:
        logger.warning("move_to_travel insert failed: %s", e)
        return jsonify({"error": "Could not add to TravelReads"}), 500

    # Soft-delete: mark Done in inbox so it disappears from the default
    # "Unread" filter but is still recoverable via the Done filter.
    update(
        "inbox_links",
        params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
        json={"status": "Done"},
    )
    return jsonify({"success": True, "kind": kind, "duration_minutes": duration_minutes})


@inbox_bp.route("/api/inbox/channel-uploads", methods=["GET"])
@login_required
def channel_uploads():
    """List recent uploads from a YouTube channel, given either the
    channel's id (cheaper, 2 calls) or a video id from that channel
    (3 calls — first looks up the channel from the video).

    Returns the same shape as /api/inbox/search results, including
    duration / view count, so the frontend can reuse its render path."""
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return jsonify({"error": "GOOGLE_API_KEY not set"}), 503

    channel_id = request.args.get("channelId", "").strip()
    video_id = request.args.get("videoId", "").strip()

    # If the caller only knows a video id, look up its channel first.
    if not channel_id and video_id:
        try:
            r = http_requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"id": video_id, "part": "snippet", "key": api_key},
                timeout=6,
            )
            if r.status_code != 200:
                return jsonify({"error": "Could not look up video"}), 502
            items = r.json().get("items", [])
            if not items:
                return jsonify({"error": "video not found"}), 404
            channel_id = items[0]["snippet"].get("channelId", "")
        except Exception as e:
            logger.warning("channel_uploads video lookup failed: %s", e)
            return jsonify({"error": "lookup failed"}), 500

    if not channel_id:
        return jsonify({"error": "channelId or videoId required"}), 400

    try:
        # channels.list → uploads playlist id + channel name + sub count
        r = http_requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={
                "id": channel_id,
                "part": "contentDetails,snippet,statistics",
                "key": api_key,
            },
            timeout=8,
        )
        if r.status_code != 200:
            return jsonify({"error": "channel lookup failed"}), 502
        chans = r.json().get("items", [])
        if not chans:
            return jsonify({"error": "channel not found"}), 404
        chan = chans[0]
        uploads_id = (
            chan.get("contentDetails", {})
                .get("relatedPlaylists", {})
                .get("uploads", "")
        )
        chan_title = chan.get("snippet", {}).get("title", "")
        chan_thumb = (
            chan.get("snippet", {}).get("thumbnails", {})
                .get("default", {}).get("url", "")
        )
        chan_stats = chan.get("statistics", {}) or {}
        subs = (
            None if chan_stats.get("hiddenSubscriberCount")
            else int(chan_stats.get("subscriberCount", 0) or 0)
        )

        # playlistItems.list → 10 most recent uploads
        r = http_requests.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={
                "playlistId": uploads_id,
                "part": "snippet",
                "maxResults": 10,
                "key": api_key,
            },
            timeout=8,
        )
        if r.status_code != 200:
            return jsonify({"error": "uploads lookup failed"}), 502
        uploads = []
        for it in r.json().get("items", []):
            snip = it.get("snippet", {}) or {}
            vid = (snip.get("resourceId") or {}).get("videoId", "")
            if not vid:
                continue
            uploads.append({
                "url": f"https://www.youtube.com/watch?v={vid}",
                "title": snip.get("title", ""),
                "description": (snip.get("description") or "")[:200],
                "thumbnail": (snip.get("thumbnails") or {})
                              .get("medium", {}).get("url", ""),
                "channel": chan_title,
                "channel_id": channel_id,
                "published_at": snip.get("publishedAt", ""),
            })

        # Enrich with duration + view count for each. Reuses the same
        # helper the search endpoint uses, so the frontend can render
        # uploads with the exact same component.
        uploads = _yt_enrich(uploads, api_key)
        return jsonify({
            "channel": {
                "id": channel_id,
                "title": chan_title,
                "thumbnail": chan_thumb,
                "subscriber_count": subs,
            },
            "uploads": uploads,
        })
    except Exception as e:
        logger.warning("channel_uploads exception: %s", e)
        return jsonify({"error": f"failed: {e}"}), 500


@inbox_bp.route("/api/inbox/preview", methods=["GET"])
@login_required
def inbox_preview():
    """Server-side reader-mode for an article URL. Fetches the page,
    extracts the main content with BeautifulSoup heuristics, sanitises
    with bleach, and returns clean HTML the frontend can drop inline.

    Used by the Inbox "Read" button so users can read articles without
    leaving the planner — and works for sites that block iframe
    embedding via X-Frame-Options."""
    url = request.args.get("url", "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return jsonify({"error": "valid URL required"}), 400

    try:
        r = http_requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; DailyPlanner/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            },
            allow_redirects=True,
        )
        if r.status_code >= 400:
            logger.warning("inbox_preview fetch %s: http=%s", url, r.status_code)
            return jsonify({"error": f"Source returned {r.status_code}"}), 502
        # Cap response size so a giant page can't blow up the parser.
        html = r.text[:1_000_000]
        result = _extract_readable_html(html)
        if not result.get("content") or result["length"] < 100:
            return jsonify({"error": "Could not extract readable content"}), 422
        return jsonify(result)
    except Exception as e:
        logger.warning("inbox_preview exception %s: %s", url, e)
        return jsonify({"error": f"Fetch failed: {e}"}), 500


@inbox_bp.route("/api/inbox/search", methods=["GET"])
@login_required
def search_web():
    """Search YouTube for videos matching a query."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        logger.warning("YouTube search: GOOGLE_API_KEY missing")
        return jsonify({"error": "GOOGLE_API_KEY not set in .env."}), 503

    logger.info("YouTube search: q=%r key=%s", query[:80], _key_fingerprint(api_key))

    try:
        r = http_requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": 6,
                "key": api_key,
            },
            timeout=8,
        )
        if r.status_code != 200:
            _log_google_failure("YouTube", r, query, api_key)
            try:
                payload = r.json()
            except Exception:
                payload = {}
            hint = _google_error_hint(payload)
            return jsonify({"error": f"YouTube: {hint}"}), 503

        items = r.json().get("items", [])
        logger.info("YouTube search: q=%r items=%d", query[:80], len(items))
        results = []
        prefetched_channel_ids = []
        for item in items:
            vid = item["id"].get("videoId", "")
            snip = item.get("snippet", {})
            cid = snip.get("channelId", "")
            if cid:
                prefetched_channel_ids.append(cid)
            results.append({
                "url": f"https://www.youtube.com/watch?v={vid}",
                "title": snip.get("title", ""),
                "description": snip.get("description", "")[:200],
                "thumbnail": snip.get("thumbnails", {}).get("medium", {}).get("url", ""),
                "channel": snip.get("channelTitle", ""),
                "channel_id": cid,
                "published_at": snip.get("publishedAt", ""),
            })
        # Enrich with duration / view count / subscriber count. We pass
        # the channel ids harvested from the search response so the
        # subscribers call can run in parallel with the duration call —
        # ~200ms saving per search.
        results = _yt_enrich(results, api_key, prefetched_channel_ids)
        return jsonify(results)
    except Exception as e:
        logger.exception("YouTube search exception: q=%r err=%s", query[:80], e)
        return jsonify({"error": f"YouTube: {e}"}), 500


@inbox_bp.route("/api/inbox/search-discover", methods=["GET"])
@login_required
def search_discover():
    """Free-of-charge cross-source search. Hits Hacker News (Algolia)
    and dev.to in parallel, both keyless and uncapped. Quota-free,
    bill-free — sits alongside the YouTube and CSE Articles searches
    as a third "Discover" panel.

    HN: real full-text search across all submitted stories. Returns
    points + comment counts as decision signals.
    dev.to: their public API has no free-text search, only tag
    filtering. We try the query as a tag (lowercased, alphanumerics
    only); if it doesn't match a tag, dev.to silently returns []."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    results = []

    # ── Hacker News via Algolia ─────────────────────────────────
    try:
        r = http_requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={
                "query": query,
                "tags": "story",
                "hitsPerPage": 5,
            },
            timeout=6,
        )
        if r.status_code == 200:
            for hit in r.json().get("hits", []):
                # Stories without a URL are Ask HN / Show HN posts —
                # they live only on news.ycombinator.com. Use the HN
                # discussion URL instead so the user can still save
                # something useful.
                story_url = hit.get("url") or (
                    f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
                    if hit.get("objectID") else None
                )
                if not story_url or not hit.get("title"):
                    continue
                results.append({
                    "url": story_url,
                    "title": hit["title"],
                    "source": "Hacker News",
                    "points": hit.get("points") or 0,
                    "comments": hit.get("num_comments") or 0,
                    "discussion_url": (
                        f"https://news.ycombinator.com/item?id={hit['objectID']}"
                        if hit.get("objectID") else None
                    ),
                })
        else:
            logger.warning("HN search http=%s body=%r", r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("HN search exception: %s", e)

    # ── dev.to by tag ──────────────────────────────────────────
    # The public API filters articles by tag (?tag=…), but has no
    # free-text search endpoint. Strip the query down to a single
    # tag-shaped token and try it; tag misses just yield no items
    # which is fine — Hacker News covers the multi-word case.
    tag = re.sub(r"[^a-z0-9]", "", query.lower())[:30]
    if tag:
        try:
            r = http_requests.get(
                "https://dev.to/api/articles",
                params={"tag": tag, "per_page": 5, "top": "7"},
                timeout=6,
                headers={"Accept": "application/json"},
            )
            if r.status_code == 200:
                for art in r.json():
                    if not art.get("url") or not art.get("title"):
                        continue
                    user = art.get("user") or {}
                    results.append({
                        "url": art["url"],
                        "title": art["title"],
                        "source": "dev.to",
                        "reactions": art.get("public_reactions_count") or 0,
                        "comments": art.get("comments_count") or 0,
                        "author": user.get("name") or "",
                        "reading_time": art.get("reading_time_minutes") or 0,
                    })
            else:
                logger.warning("devto http=%s body=%r", r.status_code, r.text[:200])
        except Exception as e:
            logger.warning("devto exception: %s", e)

    logger.info(
        "Discover search: q=%r items=%d (hn+devto)", query[:80], len(results),
    )
    return jsonify(results)


@inbox_bp.route("/api/inbox/search-articles", methods=["GET"])
@login_required
def search_articles():
    """Search articles via Google Programmable Search Engine (CSE).

    The CSE — created at https://programmablesearchengine.google.com/ —
    is the thing that decides which publishers are searched (Medium,
    Substack, dev.to, freecodecamp, etc.). This endpoint just relays
    the query and reformats results to match the YouTube payload shape
    so the frontend can render both side by side.
    """
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    api_key = os.environ.get("GOOGLE_API_KEY", "")
    cse_id = os.environ.get("GOOGLE_CSE_ID", "")
    if not api_key:
        logger.warning("CSE search: GOOGLE_API_KEY missing")
        return jsonify({"error": "GOOGLE_API_KEY not set in .env."}), 503
    if not cse_id:
        logger.warning("CSE search: GOOGLE_CSE_ID missing")
        return jsonify({
            "error": (
                "Articles search not configured. Create a Programmable "
                "Search Engine at programmablesearchengine.google.com, set "
                "GOOGLE_CSE_ID in .env, and add 'Custom Search API' to your "
                "GOOGLE_API_KEY's allowed services."
            )
        }), 503

    logger.info(
        "CSE search: q=%r key=%s cx=%s",
        query[:80], _key_fingerprint(api_key), cse_id,
    )

    try:
        r = http_requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "q": query,
                "cx": cse_id,
                "num": 6,
                "key": api_key,
                "safe": "off",
            },
            timeout=8,
        )
        if r.status_code != 200:
            _log_google_failure("CSE", r, query, api_key, cx=cse_id)
            try:
                payload = r.json()
            except Exception:
                payload = {}
            hint = _google_error_hint(payload)
            kind = _google_error_kind(payload)
            return jsonify({"error": f"Articles: {hint}", "kind": kind}), 503

        items = r.json().get("items", [])
        logger.info("CSE search: q=%r items=%d", query[:80], len(items))
        results = []
        for item in items:
            results.append({
                "url": item.get("link", ""),
                "title": item.get("title", ""),
                "description": (item.get("snippet", "") or "")[:240],
                "source": item.get("displayLink", ""),
                "thumbnail": _cse_thumbnail(item),
            })
        return jsonify(results)
    except Exception as e:
        logger.exception("CSE search exception: q=%r err=%s", query[:80], e)
        return jsonify({"error": f"Articles: {e}"}), 500


# ── Drive Queue ─────────────────────────────────────────────────────────────
# A "what fits my commute" view that pulls drivable-labelled items from
# both inbox_links and travel_reads, packs them greedy-by-priority +
# longest-first to fill a target minute count, and renders a sequenced
# playlist. Items show estimated length and open in their native player
# (YouTube embed, Spotify open, etc.).
#
# Why both tables: the user's listening backlog lives in two places.
# TravelReads is the explicit "consume later" queue; Inbox is the
# raw-capture firehose. A drive view that ignored either would feel
# half-empty.

@inbox_bp.route("/drive-queue", methods=["GET"])
@login_required
def drive_queue_page():
    return render_template("drive_queue.html")


def _yt_id_for_drive(url: str) -> str:
    """Best-effort YouTube id extraction. Reused from the inbox helper
    so the drive-queue picks up the same URL formats."""
    return _yt_extract_id(url) or ""


@inbox_bp.route("/api/drive-queue", methods=["GET"])
@login_required
def drive_queue_api():
    """Build a drive playlist that fills `minutes` ±10%.

    Pulls every drivable item from inbox_links (status != Done) and
    travel_reads (status != done|archived), normalises to a common
    shape (title, url, source, est_minutes, est_known), then packs:
        1. Sort: priority-tag first, then longest-first within a
           bucket (longest-first matches the "fill the slot" intent;
           bin-packing micro-optimal isn't worth the code).
        2. Greedy fill until total reaches the target window. If a
           candidate would overflow by >10% of target, skip it; the
           next shorter one might fit cleanly.

    Items without a known duration get a generous default (15 min)
    so they're still pickable, but with `est_known: false` so the UI
    can show "~15m" instead of "15m"."""
    user_id = session["user_id"]
    try:
        target_min = max(5, min(240, int(request.args.get("minutes", 60))))
    except (TypeError, ValueError):
        target_min = 60
    target_secs = target_min * 60

    # ── Pull from inbox_links ─────────────────────────────────────
    inbox_rows = get("inbox_links", params={
        "user_id": f"eq.{user_id}",
        "status": "neq.Done",
        "labels": "cs.{drivable}",   # PostgREST: array contains 'drivable'
        "select": "id,url,title,description,duration_seconds,labels",
        "limit": "200",
    }) or []

    # ── Pull from travel_reads ────────────────────────────────────
    # Done + archived items shouldn't surface — re-listening to
    # finished items pollutes the queue.
    tr_rows = get("travel_reads", params={
        "user_id": f"eq.{user_id}",
        "status": "not.in.(archived,done)",
        "labels": "cs.{drivable}",
        "select": (
            "id,url,title,description,duration_minutes,labels,source,kind"
        ),
        "limit": "200",
    }) or []

    DEFAULT_SECS = 15 * 60   # used when an item's duration is unknown

    candidates = []
    for r in inbox_rows:
        secs = int(r.get("duration_seconds") or 0)
        candidates.append({
            "source_table": "inbox",
            "id": r.get("id"),
            "url": r.get("url") or "",
            "title": r.get("title") or r.get("url") or "Untitled",
            "description": (r.get("description") or "")[:200],
            "labels": list(r.get("labels") or []),
            "est_seconds": secs or DEFAULT_SECS,
            "est_known": secs > 0,
            "youtube_id": _yt_id_for_drive(r.get("url") or ""),
        })
    for r in tr_rows:
        mins = int(r.get("duration_minutes") or 0)
        secs = mins * 60
        candidates.append({
            "source_table": "travel_reads",
            "id": r.get("id"),
            "url": r.get("url") or "",
            "title": r.get("title") or r.get("url") or "Untitled",
            "description": (r.get("description") or "")[:200],
            "labels": list(r.get("labels") or []),
            "est_seconds": secs or DEFAULT_SECS,
            "est_known": secs > 0,
            "youtube_id": _yt_id_for_drive(r.get("url") or ""),
        })

    # Stable sort: priority-flagged items first, then longest first
    # within each tier. Longest-first means the queue front-loads big
    # commitments — drivers like to lock into a 45-min talk early
    # and let short clips fill the gap at the end.
    def _prio_key(c):
        has_priority = "priority" in c["labels"]
        return (0 if has_priority else 1, -c["est_seconds"])
    candidates.sort(key=_prio_key)

    # ── Greedy pack ───────────────────────────────────────────────
    overshoot_tolerance = int(target_secs * 0.10)
    picked = []
    used_secs = 0
    for c in candidates:
        if used_secs >= target_secs:
            break
        remaining = target_secs - used_secs
        # Skip candidates that would overshoot the target by more than
        # the tolerance — we'd rather fall short by a few minutes than
        # commit to a 45-min lecture when only 20 min of drive is left.
        if c["est_seconds"] > remaining + overshoot_tolerance:
            continue
        picked.append(c)
        used_secs += c["est_seconds"]

    return jsonify({
        "target_minutes": target_min,
        "filled_minutes": round(used_secs / 60),
        "items": picked,
        "candidate_count": len(candidates),
    })


@inbox_bp.route("/api/inbox/backfill", methods=["POST"])
@login_required
def backfill_metadata():
    """One-shot backfill for rows saved before labels / duration_seconds /
    published_at columns existed.

    YouTube rows: re-fetch via videos.list (batches of 50, 1 quota unit
    each) and fill in the missing columns. Skips rows that already have
    a value — no clobber.

    All rows: re-run auto_label() and write the result, but ONLY when
    the row currently has zero labels. This means user-edited labels
    survive — backfill is additive for old rows, untouched for new.

    Operates on the caller's user_id only. Returns a summary the UI
    surfaces in a toast so you can see what happened."""
    user_id = session["user_id"]
    api_key = os.environ.get("GOOGLE_API_KEY", "")

    # ── Inbox rows ───────────────────────────────────────────────────
    inbox_rows = get("inbox_links", params={
        "user_id": f"eq.{user_id}",
        "select": (
            "id,url,title,description,content_type,"
            "labels,duration_seconds,published_at"
        ),
        "limit": "5000",
    }) or []

    yt_meta: dict[str, dict] = {}
    if api_key:
        # Collect every YouTube id whose row is missing duration OR
        # publish date. Dedupe so the same id isn't fetched twice.
        ids_to_fetch = []
        for r in inbox_rows:
            vid = _yt_extract_id(r.get("url") or "")
            if not vid:
                continue
            if r.get("duration_seconds") and r.get("published_at"):
                continue
            ids_to_fetch.append(vid)
        ids_to_fetch = list(dict.fromkeys(ids_to_fetch))

        # videos.list caps at 50 ids per call. Each batch is 1 quota unit.
        for i in range(0, len(ids_to_fetch), 50):
            chunk = ids_to_fetch[i:i + 50]
            try:
                resp = http_requests.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={
                        "id": ",".join(chunk),
                        "part": "snippet,contentDetails",
                        "key": api_key,
                    },
                    timeout=15,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "backfill YouTube batch http=%s body=%r",
                        resp.status_code, resp.text[:200],
                    )
                    continue
                for v in resp.json().get("items", []):
                    snip = v.get("snippet", {}) or {}
                    cd = v.get("contentDetails", {}) or {}
                    yt_meta[v["id"]] = {
                        "duration_seconds": _yt_parse_duration(cd.get("duration", "")),
                        "published_at": snip.get("publishedAt", ""),
                    }
            except Exception as e:
                logger.warning("backfill YouTube batch exception: %s", e)

    inbox_updated = 0
    inbox_youtube_enriched = 0
    for r in inbox_rows:
        patch = {}
        vid = _yt_extract_id(r.get("url") or "")
        if vid and vid in yt_meta:
            ym = yt_meta[vid]
            if ym["duration_seconds"] and not r.get("duration_seconds"):
                patch["duration_seconds"] = ym["duration_seconds"]
            if ym["published_at"] and not r.get("published_at"):
                patch["published_at"] = ym["published_at"]
            if patch:
                inbox_youtube_enriched += 1

        # Recompute labels only when the row currently has none. A user
        # who already toggled chips by hand owns those labels — backfill
        # must not silently rewrite them.
        if not (r.get("labels") or []):
            duration_for_label = (
                patch.get("duration_seconds")
                or r.get("duration_seconds") or 0
            )
            new_labels = auto_label(
                r.get("url") or "",
                r.get("title") or "",
                r.get("description") or "",
                r.get("content_type") or "",
                duration_for_label,
            )
            if new_labels:
                patch["labels"] = new_labels

        if not patch:
            continue
        try:
            update(
                "inbox_links",
                params={"id": f"eq.{r['id']}", "user_id": f"eq.{user_id}"},
                json=patch,
            )
            inbox_updated += 1
        except Exception as e:
            logger.warning("backfill inbox row %s failed: %s", r.get("id"), e)

    # ── TravelReads rows ─────────────────────────────────────────────
    # Only label rows that have none yet — same no-clobber rule. We
    # don't enrich duration_minutes here because the user-supplied
    # value is authoritative for travel_reads (no API fetch on save).
    tr_rows = get("travel_reads", params={
        "user_id": f"eq.{user_id}",
        "status": "neq.archived",
        "select": "id,url,title,description,kind,duration_minutes,labels",
        "limit": "5000",
    }) or []

    tr_updated = 0
    for r in tr_rows:
        if r.get("labels"):
            continue
        secs = (r.get("duration_minutes") or 0) * 60
        new_labels = auto_label(
            r.get("url") or "",
            r.get("title") or "",
            r.get("description") or "",
            r.get("kind") or "",
            secs,
        )
        if not new_labels:
            continue
        try:
            update(
                "travel_reads",
                params={"id": f"eq.{r['id']}", "user_id": f"eq.{user_id}"},
                json={"labels": new_labels},
            )
            tr_updated += 1
        except Exception as e:
            logger.warning("backfill travel row %s failed: %s", r.get("id"), e)

    return jsonify({
        "ok": True,
        "inbox_total": len(inbox_rows),
        "inbox_updated": inbox_updated,
        "inbox_youtube_enriched": inbox_youtube_enriched,
        "travel_total": len(tr_rows),
        "travel_updated": tr_updated,
    })
