"""Day Sheet — a paper-planner style page for one day, wired to real data.

Layout follows the "Planner Template UI" design: a week strip, today's
focus and energy, an hourly schedule, Top 3, to-dos, a weekly habit grid,
notes and an end-of-day reflection.

WHAT IS STORED WHERE. Nothing is duplicated:
  focus                 -> daily_meta.daily_intent (same One Big Thing as
                           the dashboard and /day)
  reflection, gratitude -> daily_meta.reflection / .gratitude (same as /day)
  habits                -> habit_master + habit_entries (same as /health)
  schedule              -> events, matrix tasks and project tasks for the
                           day, from the agenda_service fetchers, shown
                           in their hour; read-only here
Only what is new lives in `day_sheets.data` (MIGRATION_DAY_SHEETS.sql):
  top3 [{text, done}] x3, todos [{text, done}], energy 0-5, notes,
  hours {"07": "text"}, tomorrow.
If that table is missing the page still works for everything else and
says which SQL file to run.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from auth import login_required
from services.agenda_service import (
    _sort_timed_then_untimed, fetch_bucket_items, fetch_events, fetch_matrix_items, fetch_project_items,
)
from supabase_client import get, post, update
from utils.user_tz import user_today

logger = logging.getLogger("daily_plan")
day_sheet_bp = Blueprint("day_sheet", __name__)

MIGRATION = "MIGRATION_DAY_SHEETS.sql"
MAX_TODOS = 30
MAX_LINE = 300
MAX_NOTES = 8000

# Planning methods (v355). The page shows a different planning card for
# each; all of them keep the schedule, habits, notes and reflection.
#   top3      Top 3 / MITs (the original card, uses `top3`)
#   135       1-3-5 rule: lists big(1) medium(3) small(5)
#   eisenhower  lists q_do, q_plan, q_delegate, q_drop
#   ivylee    Ivy Lee: six tasks in strict order, list ivy(6)
#   timeblock Top 3 plus a planned/actual column on the schedule (`actual`)
#   bujo      bullet-journal rapid log, list log (items carry `kind`)
#   manager   Top 3 outcomes + lists people and quick
TEMPLATES = ("top3", "135", "eisenhower", "ivylee", "timeblock", "bujo", "manager")
LIST_CAPS = {"big": 1, "medium": 3, "small": 5, "q_do": 12, "q_plan": 12, "q_delegate": 12,
             "q_drop": 12, "ivy": 6, "log": 60, "people": 20, "quick": 20}
BUJO_KINDS = ("task", "event", "note")
# Lists whose unfinished items can be carried to the next day.
CARRY_KEYS = ("top3", "todos") + tuple(LIST_CAPS)


def _parse_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return user_today()
    return date.fromisoformat(raw)


def _clean_sheet(raw):
    """Keep only known keys, with sane types and lengths."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}

    def items(v, n):
        res = []
        for it in (v if isinstance(v, list) else [])[:n]:
            it = it if isinstance(it, dict) else {}
            row = {"text": str(it.get("text") or "")[:MAX_LINE], "done": bool(it.get("done"))}
            if it.get("kind") in BUJO_KINDS:
                row["kind"] = it["kind"]
            if it.get("moved"):
                row["moved"] = True
            res.append(row)
        return res

    if "top3" in raw:
        t = items(raw["top3"], 3)
        out["top3"] = t + [{"text": "", "done": False}] * (3 - len(t))
    if "todos" in raw:
        out["todos"] = items(raw["todos"], MAX_TODOS)
    if "energy" in raw:
        try:
            out["energy"] = max(0, min(5, int(raw["energy"] or 0)))
        except (TypeError, ValueError):
            out["energy"] = 0
    if "notes" in raw:
        out["notes"] = str(raw["notes"] or "")[:MAX_NOTES]
    if "tomorrow" in raw:
        out["tomorrow"] = str(raw["tomorrow"] or "")[:1000]
    for key in ("hours", "actual"):
        if key in raw and isinstance(raw[key], dict):
            out[key] = _clean_hours(raw[key])
    if "template" in raw:
        out["template"] = raw["template"] if raw["template"] in TEMPLATES else ""
    if "lists" in raw and isinstance(raw["lists"], dict):
        out["lists"] = {k: items(v, LIST_CAPS[k]) for k, v in raw["lists"].items() if k in LIST_CAPS}
    return out


def _clean_hours(raw):
    hours = {}
    for k, v in raw.items():
        try:
            h = int(k)
        except (TypeError, ValueError):
            continue
        if 0 <= h <= 23 and str(v or "").strip():
            hours[f"{h:02d}"] = str(v)[:MAX_LINE]
    return hours


def _load_sheet(user_id, d):
    """(data, available). available is False when the table is missing."""
    try:
        rows = get("day_sheets", params={"user_id": f"eq.{user_id}", "sheet_date": f"eq.{d}",
                                         "select": "data", "limit": "1"}) or []
    except Exception:
        logger.warning("day sheet read failed (migration missing?)", exc_info=True)
        return {}, False
    return (rows[0].get("data") or {}) if rows else {}, True


def _meta(user_id, d):
    try:
        rows = get("daily_meta", params={"user_id": f"eq.{user_id}", "plan_date": f"eq.{d}",
                                         "select": "daily_intent,reflection,gratitude", "limit": "1"}) or []
    except Exception:
        logger.warning("day sheet: daily_meta read failed", exc_info=True)
        rows = []
    r = rows[0] if rows else {}
    return {"focus": r.get("daily_intent") or "", "reflection": r.get("reflection") or "",
            "gratitude": r.get("gratitude") or ""}


def _save_meta(user_id, d, fields):
    if not fields:
        return
    existing = get("daily_meta", {"user_id": f"eq.{user_id}", "plan_date": f"eq.{d}", "select": "user_id"}) or []
    if existing:
        update("daily_meta", params={"user_id": f"eq.{user_id}", "plan_date": f"eq.{d}"}, json=fields)
    else:
        post("daily_meta", {"user_id": user_id, "plan_date": d.isoformat(), **fields}, prefer="return=minimal")


def _week(d):
    start = d - timedelta(days=d.weekday())
    return [start + timedelta(days=i) for i in range(7)]


def _habit_masters(user_id):
    return get("habit_master", params={"user_id": f"eq.{user_id}", "is_deleted": "eq.false",
                                       "select": "id,name,unit,goal,habit_type,position",
                                       "order": "position.asc"}) or []


def _habit_entries(user_id, week):
    return get("habit_entries", params={
        "user_id": f"eq.{user_id}",
        "and": f"(plan_date.gte.{week[0]},plan_date.lte.{week[-1]})",
        "select": "habit_id,plan_date,value"}) or []


def _habits(masters, entries, week):
    if not masters:
        return []
    vals = {(e["habit_id"], str(e["plan_date"])[:10]): float(e.get("value") or 0) for e in entries}
    out = []
    for h in masters:
        is_bool = h.get("habit_type") == "boolean"
        goal = float(h.get("goal") or 0) or 1.0
        days = []
        for wd in week:
            v = vals.get((h["id"], wd.isoformat()), 0.0)
            days.append({"date": wd.isoformat(), "value": v, "done": v >= (1 if is_bool else goal)})
        out.append({"id": h["id"], "name": h.get("name") or "", "boolean": is_bool,
                    "goal": goal, "unit": "" if is_bool else (h.get("unit") or "").lower(), "days": days})
    return out


def _schedule(items):
    """Items from the four agenda fetchers -> (timed, untimed)."""
    _sort_timed_then_untimed(items)
    timed, untimed = [], []
    for i in items:
        it = {"title": i.get("title") or "", "time": i.get("time"), "end_time": i.get("end_time"),
              "source": i.get("source") or "", "done": bool(i.get("done")) or (i.get("status") == "done")}
        (timed if it["time"] else untimed).append(it)
    return timed, untimed


def _payload(user_id, d):
    """Everything the page needs, read in ONE round of parallel requests.

    WHY: the first version made its reads one after another (sheet, meta,
    habits, entries) and called build_dashboard for the schedule, which
    fans out to ten readers (overdue, upcoming, inbox health, ...) when
    this page needs four. Each read is a full trip to Supabase, so the
    page cost the sum. Now all eight reads go at once and the page costs
    the slowest one. No request context is touched inside the threads:
    user_id and the date are passed in.
    """
    week = _week(d)
    iso = d.isoformat()
    jobs = {
        "sheet": (lambda: _load_sheet(user_id, d), ({}, False)),
        "meta": (lambda: _meta(user_id, d), {"focus": "", "reflection": "", "gratitude": ""}),
        "events": (lambda: fetch_events(user_id, d), []),
        "matrix": (lambda: fetch_matrix_items(user_id, d), []),
        "project": (lambda: fetch_project_items(user_id, due_on=iso), []),
        "bucket": (lambda: fetch_bucket_items(user_id, d)[0], []),
        "masters": (lambda: _habit_masters(user_id), []),
        "entries": (lambda: _habit_entries(user_id, week), []),
    }

    def run(label, fn, fallback):
        try:
            return fn()
        except Exception:
            logger.warning("day sheet: %s failed", label, exc_info=True)
            return fallback

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futs = {k: pool.submit(run, k, fn, fb) for k, (fn, fb) in jobs.items()}
        out = {k: f.result() for k, f in futs.items()}

    data, available = out["sheet"]
    sheet = _clean_sheet({"top3": [], "todos": [], "energy": 0, "notes": "", "tomorrow": "", "hours": {},
                          "actual": {}, "template": "", "lists": {},
                          **(data if isinstance(data, dict) else {})})
    timed, untimed = _schedule(out["events"] + out["matrix"] + out["project"] + out["bucket"])
    return {
        "date": iso, "today": user_today().isoformat(),
        "week": [w.isoformat() for w in week],
        "available": available, "migration": MIGRATION,
        "sheet": sheet, "meta": out["meta"],
        "timed": timed, "untimed": untimed,
        "habits": _habits(out["masters"], out["entries"], week),
    }


@day_sheet_bp.route("/day-sheet")
@login_required
def page():
    try:
        d = _parse_date(request.args.get("date"))
    except ValueError:
        return redirect(url_for("day_sheet.page"))
    # The data is embedded in the page, so opening it is one request,
    # not the page and then a second trip for its data.
    return render_template("day_sheet.html", sheet_date=d.isoformat(),
                           payload=_payload(session["user_id"], d))


@day_sheet_bp.route("/api/day-sheet")
@login_required
def load():
    user_id = session["user_id"]
    try:
        d = _parse_date(request.args.get("date"))
    except ValueError:
        return jsonify({"error": "Invalid date"}), 400
    return jsonify(_payload(user_id, d))


@day_sheet_bp.route("/api/day-sheet", methods=["POST"])
@login_required
def save():
    """Partial save. Body: {date, sheet?: {...}, focus?, reflection?, gratitude?}."""
    user_id = session["user_id"]
    body = request.get_json(silent=True) or {}
    try:
        d = _parse_date(body.get("date"))
    except ValueError:
        return jsonify({"error": "Invalid date"}), 400

    meta = {}
    for key, col in (("focus", "daily_intent"), ("reflection", "reflection"), ("gratitude", "gratitude")):
        if key in body:
            meta[col] = (str(body.get(key) or "").strip()[:4000]) or None

    # The page sends the WHOLE sheet (it is small), so this is a single
    # upsert with no read-merge-write round trip first. The daily_meta
    # save runs alongside it.
    sheet = _clean_sheet(body.get("sheet")) if isinstance(body.get("sheet"), dict) else None

    def save_sheet():
        post("day_sheets?on_conflict=user_id,sheet_date",
             {"user_id": user_id, "sheet_date": d.isoformat(), "data": sheet,
              "updated_at": datetime.now(timezone.utc).isoformat()},
             prefer="resolution=merge-duplicates,return=minimal")

    jobs = {}
    if meta:
        jobs["meta"] = lambda: _save_meta(user_id, d, meta)
    if sheet:
        jobs["sheet"] = save_sheet
    errors = {}
    if jobs:
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futs = {k: pool.submit(fn) for k, fn in jobs.items()}
            for k, f in futs.items():
                try:
                    f.result()
                except Exception as e:
                    errors[k] = e
                    logger.warning("day sheet: %s save failed", k, exc_info=True)
    if "sheet" in errors and _table_missing(errors["sheet"]):
        return jsonify({"error": f"Run {MIGRATION} in Supabase to save this part", "migration": MIGRATION}), 409
    if errors:
        return jsonify({"error": "Could not save"}), 500
    return jsonify({"ok": True})


def _open_items(rows, key):
    """Unfinished, non-empty, not already moved. In the bullet journal only
    tasks move (events and notes stay on their day)."""
    return [r for r in rows if r.get("text", "").strip() and not r.get("done") and not r.get("moved")
            and (key != "log" or r.get("kind", "task") == "task")]


@day_sheet_bp.route("/api/day-sheet/carry", methods=["POST"])
@login_required
def carry():
    """Move unfinished items of the given lists to the next day's sheet.

    Body: {date, keys: ["ivy", "log", ...]}. The items stay on today's
    sheet marked `moved` (shown as "-> tomorrow"), so carrying twice does
    not copy them twice. Tomorrow gets them in the same list: Ivy Lee puts
    them FIRST (that is the method), Top 3 fills empty slots, the rest
    append. Duplicates (same text) and items past a list's cap are skipped.
    Returns today's updated sheet so the page can replace its copy.
    """
    user_id = session["user_id"]
    body = request.get_json(silent=True) or {}
    try:
        d = _parse_date(body.get("date"))
    except ValueError:
        return jsonify({"error": "Invalid date"}), 400
    keys = [k for k in (body.get("keys") or []) if k in CARRY_KEYS]
    if not keys:
        return jsonify({"error": "Nothing to carry"}), 400
    nxt = d + timedelta(days=1)
    (src, ok1), (dst, ok2) = _load_sheet(user_id, d), _load_sheet(user_id, nxt)
    if not (ok1 and ok2):
        return jsonify({"error": f"Run {MIGRATION} in Supabase first", "migration": MIGRATION}), 409
    src = _clean_sheet({"top3": [], "todos": [], "lists": {}, **(src or {})})
    dst = _clean_sheet({"top3": [], "todos": [], "lists": {}, **(dst or {})})
    if not dst.get("template") and src.get("template"):
        dst["template"] = src["template"]

    moved = skipped = 0
    for key in keys:
        if key in ("top3", "todos"):
            s_rows, d_rows, cap = src[key], dst[key], 3 if key == "top3" else MAX_TODOS
        else:
            s_rows = src["lists"].setdefault(key, [])
            d_rows, cap = dst["lists"].setdefault(key, []), LIST_CAPS[key]
        have = {r["text"].strip().lower() for r in d_rows if r.get("text", "").strip()}
        new = []
        for r in _open_items(s_rows, key):
            t = r["text"].strip()
            if t.lower() in have:
                r["moved"] = True          # already on tomorrow: just mark it
                continue
            row = {"text": t, "done": False}
            if key == "log":
                row["kind"] = "task"
            new.append((r, row))
            have.add(t.lower())
        filled = [x for x in d_rows if x.get("text", "").strip()]
        room = cap - len(filled)
        take, rest = new[:max(room, 0)], new[max(room, 0):]
        skipped += len(rest)
        rows = [row for _, row in take]
        if key == "ivy":
            merged = rows + filled           # carried tasks go first
        else:
            merged = filled + rows
        if key == "top3":
            merged += [{"text": "", "done": False}] * (3 - len(merged))
        if key in ("top3", "todos"):
            dst[key] = merged
        else:
            dst["lists"][key] = merged
        for r, _ in take:
            r["moved"] = True
        moved += len(take)

    now = datetime.now(timezone.utc).isoformat()
    for day, data in ((nxt, dst), (d, src)):          # tomorrow first: never mark moved without the copy
        post("day_sheets?on_conflict=user_id,sheet_date",
             {"user_id": user_id, "sheet_date": day.isoformat(), "data": data, "updated_at": now},
             prefer="resolution=merge-duplicates,return=minimal")
    return jsonify({"ok": True, "moved": moved, "skipped": skipped, "to": nxt.isoformat(),
                    "sheet": _clean_sheet({"top3": [], "todos": [], "energy": 0, "notes": "", "tomorrow": "",
                                           "hours": {}, "actual": {}, "template": "", "lists": {}, **src})})


def _table_missing(exc):
    text = str(getattr(getattr(exc, "response", None), "text", "") or exc).lower()
    return "day_sheets" in text or "does not exist" in text or "pgrst205" in text or "42p01" in text


@day_sheet_bp.route("/api/day-sheet/habit", methods=["POST"])
@login_required
def tick_habit():
    """Tick or untick a habit for a date. Ticking a number habit logs its
    goal; unticking clears the day. Same table /health writes to."""
    user_id = session["user_id"]
    body = request.get_json(silent=True) or {}
    habit_id = body.get("habit_id")
    try:
        d = date.fromisoformat(str(body.get("date") or ""))
    except ValueError:
        return jsonify({"error": "Invalid date"}), 400
    if not habit_id:
        return jsonify({"error": "habit_id required"}), 400
    rows = get("habit_master", params={"id": f"eq.{habit_id}", "user_id": f"eq.{user_id}",
                                       "select": "goal,habit_type", "limit": "1"}) or []
    if not rows:
        return jsonify({"error": "Not found"}), 404
    h = rows[0]
    value = 0.0
    if body.get("done"):
        value = 1.0 if h.get("habit_type") == "boolean" else (float(h.get("goal") or 0) or 1.0)
    post("habit_entries?on_conflict=user_id,habit_id,plan_date",
         {"user_id": user_id, "habit_id": habit_id, "plan_date": d.isoformat(), "value": value},
         prefer="resolution=merge-duplicates")
    return jsonify({"ok": True, "value": value})
