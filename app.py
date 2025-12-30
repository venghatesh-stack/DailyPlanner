from flask import Flask, request, render_template_string, redirect, url_for
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar

from supabase_client import get, post
from logger import setup_logger

IST = ZoneInfo("Asia/Kolkata")

app = Flask(__name__)
logger = setup_logger()

# ===============================
# CONSTANTS
# ===============================
TOTAL_SLOTS = 48

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
def slot_label(slot: int) -> str:
    start = datetime.min + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"

def today_ist():
    return datetime.now(IST).date()

# ===============================
# DATA ACCESS (ALIGNED TO YOUR TABLES)
# ===============================
def load_day(plan_date):
    rows = get(
        "daily_tasks",
        {
            "plan_date": f"eq.{plan_date}",
            "select": "slot,task,status"
        }
    )

    data = {i: {"task": "", "status": "Nothing Planned"} for i in range(1, TOTAL_SLOTS + 1)}

    for r in rows:
        data[r["slot"]] = {
            "task": r.get("task") or "",
            "status": r.get("status") or "Nothing Planned"
        }

    return data


def load_summary(plan_date):
    rows = get(
        "daily_summary",
        {
            "plan_date": f"eq.{plan_date}",
            "select": "habits,reflection"
        }
    )

    if not rows:
        return set(), ""

    habits = set((rows[0].get("habits") or "").split(","))
    reflection = rows[0].get("reflection") or ""
    return habits, reflection


# ===============================
# ROUTE
# ===============================
@app.route("/", methods=["GET", "POST"])
def index():
    plan_date = request.args.get("date")
    if plan_date:
        plan_date = date.fromisoformat(plan_date)
    else:
        plan_date = today_ist()

    if request.method == "POST":
        rows = []

        for slot in range(1, TOTAL_SLOTS + 1):
            task = request.form.get(f"task_{slot}", "").strip()
            status = request.form.get(f"status_{slot}", "Nothing Planned")

            if task:
                rows.append({
                    "plan_date": plan_date.isoformat(),
                    "slot": slot,
                    "task": task,
                    "status": status
                })

        if rows:
            post(
                "daily_tasks?on_conflict=plan_date,slot",
                rows,
                prefer="resolution=merge-duplicates"
            )

        habits = request.form.getlist("habits")
        reflection = request.form.get("reflection", "").strip()

        post(
            "daily_summary?on_conflict=plan_date",
            [{
                "plan_date": plan_date.isoformat(),
                "habits": ",".join(habits),
                "reflection": reflection
            }],
            prefer="resolution=merge-duplicates"
        )

        return redirect(url_for("index", date=plan_date.isoformat()))

    tasks = load_day(plan_date)
    habits, reflection = load_summary(plan_date)

    return render_template_string(
        TEMPLATE,
        plan_date=plan_date,
        tasks=tasks,
        STATUSES=STATUSES,
        slot_label=slot_label,
        habits=habits,
        reflection=reflection
    )

# ===============================
# TEMPLATE (UNCHANGED STRUCTURE)
# ===============================
TEMPLATE = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Planner</title>
</head>
<body>

<h2>{{ plan_date }}</h2>

<form method="POST">

<table border="1" width="100%">
{% for slot in range(1, 49) %}
<tr>
  <td>{{ slot_label(slot) }}</td>
  <td>
    <input style="width:100%" name="task_{{slot}}" value="{{ tasks[slot].task }}">
  </td>
  <td>
    <select name="status_{{slot}}">
      {% for s in STATUSES %}
      <option value="{{s}}" {% if tasks[slot].status == s %}selected{% endif %}>{{s}}</option>
      {% endfor %}
    </select>
  </td>
</tr>
{% endfor %}
</table>

<h3>Habits</h3>
<label><input type="checkbox" name="habits" value="Walking" {% if "Walking" in habits %}checked{% endif %}> Walking</label><br>
<label><input type="checkbox" name="habits" value="Water" {% if "Water" in habits %}checked{% endif %}> Water</label><br>

<h3>Reflection</h3>
<textarea name="reflection" rows="4" style="width:100%">{{ reflection }}</textarea>

<br><br>
<button type="submit">Save</button>

</form>

</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True)
