from flask import Flask, request, redirect, url_for, render_template_string
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar
import urllib.parse
import json

from supabase_client import get, post, delete
from logger import setup_logger

IST = ZoneInfo("Asia/Kolkata")

app = Flask(__name__)
logger = setup_logger()

# ===============================
# CONSTANTS
# ===============================
TOTAL_SLOTS = 48
META_SLOT = 0
DEFAULT_STATUS = "Nothing Planned"

STATUSES = [
    "Nothing Planned",
    "Yet to Start",
    "In Progress",
    "Closed",
    "Deferred"
]

# ===============================
# HELPERS
# ===============================
def current_slot():
    now = datetime.now(IST)
    return (now.hour * 60 + now.minute) // 30 + 1


# ===============================
# TODO: LOAD
# ===============================
def load_todo(plan_date):
    rows = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{plan_date}",
            "select": "quadrant,task_text,is_done,position,notes",
            "order": "position.asc"
        }
    ) or []

    todo = {
        "do": [],
        "schedule": [],
        "delegate": [],
        "eliminate": []
    }

    random_notes = ""

    for r in rows:
        if r.get("position") == -1:
            random_notes = r.get("notes") or ""
            continue

        q = r.get("quadrant")
        if q in todo:
            todo[q].append({
                "text": r.get("task_text", ""),
                "done": bool(r.get("is_done")),
            })

    return todo, random_notes


# ===============================
# TODO: SAVE
# ===============================
def save_todo(plan_date, form):
    delete("todo_matrix", params={"plan_date": f"eq.{plan_date}"})

    payload = []

    for quadrant in ["do", "schedule", "delegate", "eliminate"]:
        texts = form.getlist(f"{quadrant}_text[]")
        dones = form.getlist(f"{quadrant}_done[]")

        for idx, text in enumerate(texts):
            if text.strip():
                payload.append({
                    "plan_date": str(plan_date),
                    "quadrant": quadrant,
                    "task_text": text.strip(),
                    "is_done": dones[idx] == "1",
                    "position": idx,
                })

    notes = form.get("random_notes", "").strip()
    if notes:
        payload.append({
            "plan_date": str(plan_date),
            "position": -1,
            "notes": notes
        })

    ### Changed from
    # if payload:
    #        
    #        post("todo_matrix", payload)

    ### Change to
    if payload:
        post("todo_matrix", payload)


# ===============================
# TODO: CARRY FORWARD
# ===============================
def carry_forward_unfinished(from_date, to_date):
    rows = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{from_date}",
            "is_done": "eq.false",
            "select": "quadrant,task_text"
        }
    ) or []

    if not rows:
        return

    ### Changed from
    # payload = []
    # delete(...) AFTER insert

    ### Change to
    delete(
        "todo_matrix",
        params={
            "plan_date": f"eq.{to_date}",
            "is_done": "eq.false"
        }
    )

    existing = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{to_date}",
            "select": "quadrant,position"
        }
    ) or []

    position_map = {"do": 0, "schedule": 0, "delegate": 0, "eliminate": 0}

    for r in existing:
        q = r.get("quadrant")
        pos = r.get("position")
        if q in position_map and isinstance(pos, int):
            position_map[q] = max(position_map[q], pos + 1)

    payload = []

    for r in rows:
        q = r.get("quadrant")

        ### Changed from
        # payload.append({... position_map[q] ...})

        ### Change to
        if q not in position_map:
            continue

        payload.append({
            "plan_date": str(to_date),
            "quadrant": q,
            "task_text": r.get("task_text", "").strip(),
            "is_done": False,
            "position": position_map[q],
        })

        position_map[q] += 1

    if payload:
        post("todo_matrix", payload)


# ===============================
# ROUTES
# ===============================

@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("todo"))

@app.route("/todo", methods=["GET", "POST"])
def todo():
    today = datetime.now(IST).date()

    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    day = int(request.args.get("day", today.day))
    plan_date = date(year, month, day)

    if request.method == "POST":
        save_todo(plan_date, request.form)
        return redirect(url_for("todo", year=year, month=month, day=day, saved=1))

    todo, random_notes = load_todo(plan_date)

    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]

    return render_template_string(
        TODO_TEMPLATE,
        todo=todo,
        random_notes=random_notes,
        plan_date=plan_date,
        year=year,
        month=month,
        day=day,
        days=days,
        calendar=calendar,
    )


# ===============================
# TEMPLATE (ONLY JS FIX SHOWN)
# ===============================
TODO_TEMPLATE = """
<script>
function cycleStatus(el){
  const input = el.querySelector("input");

  ### Changed from
  // el.textContent = STATUS_ORDER[i];

  ### Change to
  let idx = STATUS_ORDER.indexOf(input.value);
  idx = (idx + 1) % STATUS_ORDER.length;
  input.value = STATUS_ORDER[idx];
  el.childNodes[0].nodeValue = STATUS_ORDER[idx] + " ";
}
</script>
"""

if __name__ == "__main__":
    logger.info("Starting Daily Planner – stable")
    app.run(debug=True)
