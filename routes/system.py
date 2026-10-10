from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from supabase_client import get
from services.login_service import login_required
from services import loud

system_bp = Blueprint("system", __name__)


@system_bp.route("/api/client-inert", methods=["POST"])
@login_required
def client_inert():
    """A browser-side feature reporting that it did nothing.

    THE POINT. Two features shipped this month that never ran on any page —
    both bailed out of initialising because they were called before the list
    they needed existed. Nothing was broken enough to throw, so nothing was
    logged, and the only way it surfaced was a person noticing an absence
    weeks later. A console warning would not have helped: nobody has the
    console open on their phone.

    So the client reports its own inertness here and it lands in the server
    log next to everything else.

    DELIBERATELY UNINTERESTING. It logs and returns; it stores nothing,
    trusts nothing, and reads only two short fields. Rate limiting is the
    caller's job (see dpInert in global.js) and the throttle in services.loud
    is the backstop.
    """
    data = request.get_json(silent=True) or {}
    feature = str(data.get("feature") or "")[:80]
    why = str(data.get("why") or "")[:200]
    if not feature:
        return jsonify({"ok": True})
    loud.bailed("client: " + feature, why,
                user_id=session.get("user_id"),
                page=str(data.get("page") or "")[:120])
    return jsonify({"ok": True})


@system_bp.route("/ping")
def ping():
    return "OK", 200


@system_bp.route("/favicon.ico")
def favicon():
    return "", 204


@system_bp.route("/pending")
def pending_page():
    """Page that reads the offline-write queue out of the user's
    IndexedDB and lets them inspect or delete entries before they
    sync. Entirely client-rendered — the server holds nothing here."""
    return render_template("pending.html")


@system_bp.route("/open", methods=["GET", "POST"])
@login_required
def file_handler():
    """File Handler API + protocol handler entry point.

    Manifest's file_handlers route .ics / .md / .csv → /open. The
    browser POSTs a multipart form with one file field; we sniff the
    extension and redirect to the right surface. The protocol handler
    (web+dailyplanner://) hits the GET path with ?u=<encoded URL>.

    No file processing here yet — we just route. Each destination page
    can pull the file from sessionStorage on the client if it needs
    the contents."""
    # Protocol handler — incoming web+dailyplanner://something
    if request.method == "GET":
        url = (request.args.get("u") or "").strip()
        # Currently the only thing we route on is the path component.
        # Future: parse `add-task?text=...` style intents.
        if url.startswith("inbox"):
            return redirect(url_for("inbox_bp.inbox_page"))
        if url.startswith("check"):
            return redirect("/checklist")
        return redirect(url_for("inbox_bp.inbox_page"))

    # File handler — POST with multipart/form-data, one or more files.
    f = request.files.get("file") or next(iter(request.files.values()), None)
    if not f or not f.filename:
        return redirect(url_for("inbox_bp.inbox_page"))
    ext = (f.filename.rsplit(".", 1)[-1] or "").lower()
    # Stash the raw bytes briefly in the user's session so the
    # destination page can offer to import. Cap at 256 KB to stay
    # well under typical session-cookie size limits.
    try:
        blob = f.read(256 * 1024)
        session["pending_file"] = {
            "name": f.filename,
            "ext":  ext,
            # session can serialize bytes via flask's signed-cookie
            # only as a string — base64 keeps it round-trippable.
            "b64":  __import__("base64").b64encode(blob).decode("ascii"),
        }
    except Exception:
        pass

    if ext == "ics":
        return redirect("/planner")          # calendar import lives here
    if ext in ("md", "markdown"):
        return redirect("/scribble")         # notes
    if ext == "csv":
        return redirect("/portfolio")        # transactions / holdings import
    return redirect(url_for("inbox_bp.inbox_page"))


@system_bp.route("/offline")
def offline():
    # Self-contained page the service worker serves when a navigation
    # request fails (no network and no cached copy). Must NOT extend
    # base.html — base.html pulls runtime dependencies we may not have
    # cached. Login-free by design so it works in any auth state.
    return render_template("offline.html")


@system_bp.route("/api/badge")
@login_required
def badge_count():
    """Aggregate "needs your attention" count for the App Badging API.

    Combines:
      - Inbox unread items   (status = Unread, not archived)
      - Today's checklist items not yet ticked

    Schema notes:
      - inbox_links soft-delete uses `is_archived`, not `is_deleted`
      - checklist_items has no `is_done` column; completion is tracked
        in checklist_ticks(item_id, tick_date, reminder_time). An
        item is "done today" iff at least one tick row for that item
        exists with tick_date = today. Items with multiple reminder
        fires count as done when ANY fire is ticked — keeps the
        badge simple (rule the badge represents: "do I have anything
        outstanding today").
    """
    from datetime import date as _date
    user_id = session["user_id"]
    today = _date.today().isoformat()
    total = 0

    try:
        # inbox_links hard-deletes (no soft-delete column at all), so
        # a plain status filter is enough.
        rows = get(
            "inbox_links",
            params={
                "user_id": f"eq.{user_id}",
                "status":  "eq.Unread",
                "select":  "id",
                "limit":   200,
            },
        ) or []
        total += len(rows)
    except Exception:
        pass

    try:
        items = get(
            "checklist_items",
            params={
                "user_id":    f"eq.{user_id}",
                "is_deleted": "eq.false",
                "select":     "id",
                "limit":      500,
            },
        ) or []
        if items:
            ticks = get(
                "checklist_ticks",
                params={
                    "user_id":   f"eq.{user_id}",
                    "tick_date": f"eq.{today}",
                    "select":    "item_id",
                    "limit":     500,
                },
            ) or []
            ticked_ids = {t["item_id"] for t in ticks}
            total += sum(1 for i in items if i["id"] not in ticked_ids)
    except Exception:
        pass

    return jsonify({"count": total})


@system_bp.route("/api/search")
@login_required
def global_search():
    """Cross-table search palette (Cmd+K).

    Query params: q=<text>, limit=<int, default 30>

    Searches: project_tasks.task_text, todo_matrix.task_text,
    scribble_notes.title+body, reference_links.title+url,
    inbox_links.title+url, projects.name. Each result has a uniform
    shape: { type, id, title, snippet, url, badge }.

    Uses PostgREST `ilike` for case-insensitive substring match.
    Per-table limit caps blast radius; client de-dups by url.
    """
    user_id = session["user_id"]
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"results": []})

    try:
        limit = max(1, min(50, int(request.args.get("limit") or 30)))
    except (TypeError, ValueError):
        limit = 30
    per_table = max(3, limit // 5)
    pattern = f"ilike.*{q}*"
    out = []

    # 1. Project tasks
    try:
        rows = get(
            "project_tasks",
            params={
                "user_id": f"eq.{user_id}",
                "is_eliminated": "eq.false",
                "task_text": pattern,
                "select": "task_id,task_text,project_id,status,due_date",
                "limit": per_table,
            },
        ) or []
        for r in rows:
            out.append({
                "type": "project_task",
                "id": r["task_id"],
                "title": r.get("task_text") or "(untitled task)",
                "snippet": (
                    f"Due {r['due_date']}" if r.get("due_date") else None
                ),
                "url": f"/projects/{r.get('project_id')}/tasks#{r['task_id']}"
                       if r.get("project_id") else "/projects",
                "badge": "Task",
            })
    except Exception:
        pass

    # 2. Matrix (Eisenhower) tasks
    try:
        rows = get(
            "todo_matrix",
            params={
                "user_id": f"eq.{user_id}",
                "is_deleted": "eq.false",
                "task_text": pattern,
                "select": "id,task_text,quadrant,task_date",
                "limit": per_table,
            },
        ) or []
        for r in rows:
            out.append({
                "type": "matrix_task",
                "id": r["id"],
                "title": r.get("task_text") or "(untitled)",
                "snippet": (
                    f"{r.get('quadrant') or ''}"
                    + (f" · {r['task_date']}" if r.get("task_date") else "")
                ),
                "url": "/todo",
                "badge": "Matrix",
            })
    except Exception:
        pass

    # 3. Scribble notes (title OR content match — two passes). The text
    # column is `content`, and notes use is_deleted for soft-delete.
    try:
        for col in ("title", "content"):
            rows = get(
                "scribble_notes",
                params={
                    "user_id": f"eq.{user_id}",
                    "is_deleted": "eq.false",
                    col: pattern,
                    "select": "id,title,content",
                    "limit": per_table,
                },
            ) or []
            for r in rows:
                body = (r.get("content") or "").strip()
                snippet = body[:90] + ("…" if len(body) > 90 else "")
                out.append({
                    "type": "note",
                    "id": r["id"],
                    "title": r.get("title") or "(untitled note)",
                    "snippet": snippet,
                    "url": f"/scribble/{r['id']}",
                    "badge": "Note",
                })
    except Exception:
        pass

    # 4. Reference links (no is_deleted column; search title/url/desc)
    try:
        for col in ("title", "url", "description"):
            rows = get(
                "reference_links",
                params={
                    "user_id": f"eq.{user_id}",
                    col: pattern,
                    "select": "id,title,url,description",
                    "limit": per_table,
                },
            ) or []
            for r in rows:
                out.append({
                    "type": "reference",
                    "id": r["id"],
                    "title": r.get("title") or r.get("url") or "(link)",
                    "snippet": (r.get("description") or r.get("url") or "")[:90],
                    "url": r.get("url") or "/references",
                    "badge": "Reference",
                })
    except Exception:
        pass

    # 5. Inbox links (no is_deleted column; text col is `description`)
    try:
        for col in ("title", "url", "description"):
            rows = get(
                "inbox_links",
                params={
                    "user_id": f"eq.{user_id}",
                    col: pattern,
                    "select": "id,title,url,description",
                    "limit": per_table,
                },
            ) or []
            for r in rows:
                out.append({
                    "type": "inbox",
                    "id": r["id"],
                    "title": r.get("title") or r.get("url") or "(link)",
                    "snippet": (r.get("description") or r.get("url") or "")[:90],
                    "url": r.get("url") or "/inbox",
                    "badge": "Inbox",
                })
    except Exception:
        pass

    # 6. Projects (by name)
    try:
        rows = get(
            "projects",
            params={
                "user_id": f"eq.{user_id}",
                "is_archived": "eq.false",
                "name": pattern,
                "select": "project_id,name,description",
                "limit": per_table,
            },
        ) or []
        for r in rows:
            out.append({
                "type": "project",
                "id": r["project_id"],
                "title": r.get("name") or "(unnamed)",
                "snippet": (r.get("description") or "")[:90],
                "url": f"/projects/{r['project_id']}/tasks",
                "badge": "Project",
            })
    except Exception:
        pass

    # 7. Quick Bucket tasks
    try:
        rows = get("quick_bucket", params={
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
            "text": pattern,
            "select": "id,text,time_bucket,is_done",
            "limit": per_table,
        }) or []
        for r in rows:
            out.append({
                "type": "quick_bucket",
                "id": r["id"],
                "title": r.get("text") or "(task)",
                "snippet": "Done" if r.get("is_done") else (r.get("time_bucket") or "Quick Bucket"),
                "url": "/quick-bucket",
                "badge": "Quick",
            })
    except Exception:
        pass

    # 8. Checklist items (text column is `name`)
    try:
        rows = get("checklist_items", params={
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false",
            "name": pattern,
            "select": "id,name,group_name",
            "limit": per_table,
        }) or []
        for r in rows:
            out.append({
                "type": "checklist", "id": r["id"],
                "title": r.get("name") or "(item)",
                "snippet": r.get("group_name") or None,
                "url": "/checklist", "badge": "Checklist",
            })
    except Exception:
        pass

    # 10. Calendar events (title or description)
    try:
        for col in ("title", "description"):
            rows = get("daily_events", params={
                "user_id": f"eq.{user_id}",
                "is_deleted": "eq.false",
                col: pattern,
                "select": "id,title,description,plan_date",
                "limit": per_table,
            }) or []
            for r in rows:
                out.append({
                    "type": "event", "id": r["id"],
                    "title": r.get("title") or "(event)",
                    "snippet": r.get("plan_date") or None,
                    "url": "/calendar", "badge": "Event",
                })
    except Exception:
        pass

    # 11. Travel reads (title/description/url)
    try:
        for col in ("title", "description"):
            rows = get("travel_reads", params={
                "user_id": f"eq.{user_id}",
                col: pattern,
                "select": "id,title,url,description",
                "limit": per_table,
            }) or []
            for r in rows:
                out.append({
                    "type": "travel_read", "id": r["id"],
                    "title": r.get("title") or r.get("url") or "(read)",
                    "snippet": (r.get("description") or "")[:90] or None,
                    "url": r.get("url") or "/travel-reads", "badge": "Read",
                })
    except Exception:
        pass

    # 12. Grocery items (column is `item`)
    try:
        rows = get("groceries", params={
            "user_id": f"eq.{user_id}",
            "item": pattern,
            "select": "id,item,category",
            "limit": per_table,
        }) or []
        for r in rows:
            out.append({
                "type": "grocery", "id": r["id"],
                "title": r.get("item") or "(item)",
                "snippet": r.get("category") or None,
                "url": "/grocery", "badge": "Grocery",
            })
    except Exception:
        pass

    # 13. Money — expenses / income / transfers (category or note)
    try:
        for col in ("category", "note"):
            rows = get("expenses", params={
                "user_id": f"eq.{user_id}",
                "deleted_at": "is.null",
                col: pattern,
                "select": "id,kind,amount,category,note,spent_on",
                "limit": per_table,
            }) or []
            for r in rows:
                amt = r.get("amount")
                sign = "+" if r.get("kind") == "income" else ("⇄" if r.get("kind") == "transfer" else "−")
                bits = [f"{sign}₹{amt}" if amt is not None else None, r.get("spent_on")]
                out.append({
                    "type": "expense", "id": r["id"],
                    "title": r.get("category") or r.get("note") or "(money)",
                    "snippet": " · ".join([b for b in bits if b]) or None,
                    "url": "/expenses", "badge": "Money",
                })
    except Exception:
        pass

    # 9. Family tasks (shared across the family — filter by title only).
    # Same gate as /family-tasks itself: only people on the family
    # allowlist may see them. Search used to return them to any account.
    try:
        from routes.chat import user_allowed as _family_member
        rows = [] if not _family_member() else get("family_tasks", params={
            "deleted_at": "is.null",
            "title": pattern,
            "select": "id,title,created_by_name",
            "limit": per_table,
        }) or []
        for r in rows:
            out.append({
                "type": "family_task", "id": r["id"],
                "title": r.get("title") or "(task)",
                "snippet": (f"by {r['created_by_name']}" if r.get("created_by_name") else None),
                "url": "/family-tasks", "badge": "Family",
            })
    except Exception:
        pass

    # De-dup by (type, id) and cap to limit
    seen = set()
    deduped = []
    for r in out:
        key = (r["type"], r["id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
        if len(deduped) >= limit:
            break

    return jsonify({"results": deduped, "query": q})

