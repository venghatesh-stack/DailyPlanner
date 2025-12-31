from flask import Flask, request, redirect, url_for, render_template_string
from datetime import date, datetime
from zoneinfo import ZoneInfo
import calendar

from supabase_client import get, post, delete
from logger import setup_logger

IST = ZoneInfo("Asia/Kolkata")

app = Flask(__name__)
logger = setup_logger()

# ===============================
# CONSTANTS
# ===============================
STATUSES = [
    "Nothing Planned",
    "Yet to Start",
    "In Progress",
    "Closed",
    "Deferred"
]

# ===============================
# ROOT (SAFE PLACEHOLDER)
# ===============================
@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("todo"))

# ===============================
# TODO – DATA
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

    notes = ""

    for r in rows:
        if r.get("position") == -1:
            notes = r.get("notes") or ""
            continue

        q = r.get("quadrant")
        if q in todo:
            todo[q].append({
                "text": r.get("task_text", ""),
                "done": bool(r.get("is_done"))
            })

    return todo, notes


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
                    "position": idx
                })

    notes = form.get("random_notes", "").strip()
    if notes:
        payload.append({
            "plan_date": str(plan_date),
            "position": -1,
            "notes": notes
        })

    if payload:
        post("todo_matrix", payload)

# ===============================
# TODO – ROUTE
# ===============================
@app.route("/todo", methods=["GET", "POST"])
def todo():
    today = datetime.now(IST).date()

    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    day = int(request.args.get("day", today.day))
    plan_date = date(year, month, day)

    if request.method == "POST":
        save_todo(plan_date, request.form)
        return redirect(url_for("todo", year=year, month=month, day=day))

    todo, notes = load_todo(plan_date)
    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]

    return render_template_string(
        TODO_TEMPLATE,
        todo=todo,
        random_notes=notes,
        plan_date=plan_date,
        year=year,
        month=month,
        day=day,
        days=days,
        calendar=calendar,
    )

# ===============================
# TODO – TEMPLATE (FULL, SAFE)
# ===============================
TODO_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: system-ui; background:#f6f7f9; padding:16px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:20px; border-radius:14px; }

.header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
.day-strip { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; }

.day-btn {
  width:34px; height:34px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  border:1px solid #ddd; text-decoration:none; color:#000;
}
.day-btn.selected { background:#2563eb; color:#fff; }

.matrix { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.quad { border:1px solid #e5e7eb; border-radius:12px; padding:12px; background:#f9fafb; }

.task { display:flex; gap:6px; align-items:center; margin-bottom:6px; }
.task input[type="text"] { flex:1; padding:6px; }

textarea { width:100%; min-height:120px; padding:8px; }

@media(max-width:768px){
  .matrix { grid-template-columns:1fr; }
}
</style>
</head>

<body>
<div class="container">

<div class="header">
  <h2>📋 Eisenhower Matrix – {{ plan_date }}</h2>
</div>

<div class="day-strip">
{% for d in days %}
<a href="/todo?year={{year}}&month={{month}}&day={{d.day}}"
   class="day-btn {% if d.day==day %}selected{% endif %}">
{{ d.day }}
</a>
{% endfor %}
</div>

<form method="post">

<div class="matrix">
{% for q, label in {
  'do':'🔥 Do',
  'schedule':'📅 Schedule',
  'delegate':'🤝 Delegate',
  'eliminate':'🗑 Eliminate'
}.items() %}
<div class="quad">
  <h3>{{ label }}</h3>

  {% for t in todo[q] %}
  <div class="task">
    <input type="hidden" name="{{q}}_done[]" value="{{ 1 if t.done else 0 }}">
    <input type="checkbox" {% if t.done %}checked{% endif %} disabled>
    <input type="text" name="{{q}}_text[]" value="{{ t.text }}">
  </div>
  {% endfor %}

  <div class="task">
    <input type="hidden" name="{{q}}_done[]" value="0">
    <input type="text" name="{{q}}_text[]" placeholder="Add task">
  </div>
</div>
{% endfor %}
</div>

<h3>🧠 Random Thoughts</h3>
<textarea name="random_notes">{{ random_notes }}</textarea>

<div style="margin-top:14px;">
  <button type="submit" style="padding:12px 18px;">💾 Save</button>
</div>

</form>
</div>
</body>
</html>
"""

# ===============================
# ENTRY POINT
# ===============================
if __name__ == "__main__":
    logger.info("Starting Daily Planner – stable")
    app.run(debug=True)
