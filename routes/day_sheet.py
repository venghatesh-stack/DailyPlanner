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
                           day, from agenda_service.build_dashboard, shown
                           in their hour; read-only here
Only what is new lives in `day_sheets.data` (MIGRATION_DAY_SHEETS.sql):
  top3 [{text, done}] x3, todos [{text, done}], energy 0-5, notes,
  hours {"07": "text"}, tomorrow.
If that table is missing the page still works for everything else and
says which SQL file to run.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from auth import login_required
from services.agenda_service import build_dashboard
from supabase_client import get, post, update
from utils.user_tz import user_today

logger = logging.getLogger("daily_plan")
day_sheet_bp = Blueprint("day_sheet", __name__)

MIGRATION = "MIGRATION_DAY_SHEETS.sql"
MAX_TODOS = 30
MAX_LINE = 300
MAX_NOTES = 8000


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
            res.append({"text": str(it.get("text") or "")[:MAX_LINE], "done": bool(it.get("done"))})
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
    if "hours" in raw and isinstance(raw["hours"], dict):
        hours = {}
        for k, v in raw["hours"].items():
            try:
                h = int(k)
            except (TypeError, ValueError):
                continue
            if 0 <= h <= 23 and str(v or "").strip():
                hours[f"{h:02d}"] = str(v)[:MAX_LINE]
        out["hours"] = hours
    return out


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


def _habits(user_id, week):
    try:
        masters = get("habit_master", params={"user_id": f"eq.{user_id}", "is_deleted": "eq.false",
                                              "select": "id,name,unit,goal,habit_type,position",
                                              "order": "position.asc"}) or []
    except Exception:
        logger.warning("day sheet: habits read failed", exc_info=True)
        return []
    if not masters:
        return []
    try:
        entries = get("habit_entries", params={
            "user_id": f"eq.{user_id}",
            "and": f"(plan_date.gte.{week[0]},plan_date.lte.{week[-1]})",
            "select": "habit_id,plan_date,value"}) or []
    except Exception:
        entries = []
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


def _schedule(user_id, d):
    try:
        dash = build_dashboard(user_id, d)
    except Exception:
        logger.warning("day sheet: dashboard failed", exc_info=True)
        return [], []
    timed, untimed = [], []
    for i in dash.get("today_items") or []:
        it = {"title": i.get("title") or "", "time": i.get("time"), "end_time": i.get("end_time"),
              "source": i.get("source") or "", "done": bool(i.get("done")) or (i.get("status") == "done")}
        (timed if it["time"] else untimed).append(it)
    return timed, untimed


@day_sheet_bp.route("/day-sheet")
@login_required
def page():
    try:
        d = _parse_date(request.args.get("date"))
    except ValueError:
        return redirect(url_for("day_sheet.page"))
    return render_template("day_sheet.html", sheet_date=d.isoformat())


@day_sheet_bp.route("/api/day-sheet")
@login_required
def load():
    user_id = session["user_id"]
    try:
        d = _parse_date(request.args.get("date"))
    except ValueError:
        return jsonify({"error": "Invalid date"}), 400
    data, available = _load_sheet(user_id, d)
    sheet = _clean_sheet({"top3": [], "todos": [], "energy": 0, "notes": "", "tomorrow": "", "hours": {},
                          **(data if isinstance(data, dict) else {})})
    timed, untimed = _schedule(user_id, d)
    week = _week(d)
    return jsonify({
        "date": d.isoformat(), "today": user_today().isoformat(),
        "week": [w.isoformat() for w in week],
        "available": available, "migration": MIGRATION,
        "sheet": sheet, "meta": _meta(user_id, d),
        "timed": timed, "untimed": untimed,
        "habits": _habits(user_id, week),
    })


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
    try:
        _save_meta(user_id, d, meta)
    except Exception:
        logger.exception("day sheet: daily_meta save failed")
        return jsonify({"error": "Could not save"}), 500

    patch = _clean_sheet(body.get("sheet"))
    if patch:
        current, available = _load_sheet(user_id, d)
        if not available:
            return jsonify({"error": f"Run {MIGRATION} in Supabase to save this part", "migration": MIGRATION}), 409
        merged = {**(current if isinstance(current, dict) else {}), **patch}
        try:
            post("day_sheets?on_conflict=user_id,sheet_date",
                 {"user_id": user_id, "sheet_date": d.isoformat(), "data": merged,
                  "updated_at": datetime.now(timezone.utc).isoformat()},
                 prefer="resolution=merge-duplicates")
        except Exception:
            logger.exception("day sheet save failed")
            return jsonify({"error": "Could not save"}), 500
    return jsonify({"ok": True})


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
