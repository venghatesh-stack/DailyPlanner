from flask import Flask, request, redirect, url_for, render_template_string
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar
import urllib.parse

from supabase_client import get, post
from logger import setup_logger

IST = ZoneInfo("Asia/Kolkata")

app = Flask(__name__)
logger = setup_logger()

# ===============================
# CONSTANTS
# ===============================
TOTAL_SLOTS = 48
DEFAULT_STATUS = "Nothing Planned"

STATUSES = [
    "Nothing Planned",
    "Yet to Start",
    "In Progress",
    "Closed",
    "Deferred"
]

HABIT_LIST = [
    ("Walking", "🚶"),
    ("Water", "💧"),
    ("No Shopping", "🛒❌"),
    ("No TimeWastage", "⏳"),
    ("8 hrs sleep", "😴"),
    ("Daily prayers", "🙏")
]

# ===============================
# HELPERS
# ===============================
def slot_label(slot: int) -> str:
    start = datetime.min + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"

def ist_now():
    return datetime.now(IST)

def today_ist():
    return ist_now().date()

def is_past_slot(selected_date, slot):
    if selected_date != today_ist():
        return False
    slot_time = datetime.combine(selected_date, datetime.min.time()) + timedelta(minutes=(slot - 1) * 30)
    return slot_time < ist_now()

# ===============================
# ROUTE
# ===============================
@app.route("/", methods=["GET", "POST"])
def index():
    today = today_ist()

    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    day = int(request.args.get("day", today.day))

    selected_date = date(year, month, day)

    message = ""
    error = ""

    if request.method == "POST":
        tasks = []
        for slot in range(1, TOTAL_SLOTS + 1):
            desc = request.form.get(f"desc_{slot}", "").strip()
            status = request.form.get(f"status_{slot}", DEFAULT_STATUS)

            if desc:
                tasks.append({
                    "date": selected_date.isoformat(),
                    "slot": slot,
                    "description": desc,
                    "status": status
                })

        if not tasks:
            error = "Cannot save empty tasks."
        else:
            post("tasks", tasks)
            logger.info(f"Saved tasks for {selected_date}")
            message = "Saved successfully!"

        habits = request.form.getlist("habits")
        reflection = request.form.get("reflection", "").strip()

        post("daily_meta", [{
            "date": selected_date.isoformat(),
            "habits": ",".join(habits),
            "reflection": reflection
        }])

    task_rows = get("tasks", {"date": selected_date.isoformat()})
    task_map = {row["slot"]: row for row in task_rows}

    meta = get("daily_meta", {"date": selected_date.isoformat()})
    habits_selected = set()
    reflection_text = ""

    if meta:
        habits_selected = set(meta[0].get("habits", "").split(","))
        reflection_text = meta[0].get("reflection", "")

    cal = calendar.monthcalendar(year, month)

    return render_template_string(TEMPLATE,
        year=year,
        month=month,
        day=day,
        selected_date=selected_date,
        cal=cal,
        calendar=calendar,
        task_map=task_map,
        STATUSES=STATUSES,
        TOTAL_SLOTS=TOTAL_SLOTS,
        slot_label=slot_label,
        is_past_slot=is_past_slot,
        today=today,
        message=message,
        error=error,
        HABIT_LIST=HABIT_LIST,
        habits_selected=habits_selected,
        reflection_text=reflection_text,
        ist_now=ist_now
    )

# ===============================
# TEMPLATE
# ===============================
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Planner</title>

<style>
body { font-family: Arial, sans-serif; margin-bottom: 90px; }
.header { text-align: center; margin-bottom: 10px; }
.time { font-size: 14px; color: gray; }
table { width: 100%; border-collapse: collapse; }
td, th { padding: 6px; border-bottom: 1px solid #eee; }
.past { background: #f8f8f8; color: #999; }
.current { background: #e6f3ff; }
.habits, .reflection { border: 1px solid #ddd; padding: 10px; margin: 10px 0; border-radius: 8px; }
.floating { position: fixed; bottom: 0; left: 0; right: 0; background: #fff; border-top: 1px solid #ccc; padding: 10px; display: flex; gap: 10px; }
button { flex: 1; padding: 12px; font-size: 16px; }
.toast { position: fixed; top: 10px; left: 50%; transform: translateX(-50%); background: #333; color: #fff; padding: 10px 20px; border-radius: 6px; }
.toast.error { background: #c0392b; }
</style>

<script>
setInterval(() => {
  document.getElementById("clock").innerText =
    new Date().toLocaleTimeString("en-IN");
}, 1000);
</script>

</head>
<body>

<div class="header">
  <h2>{{ selected_date.strftime('%A, %d %b %Y') }}</h2>
  <div class="time" id="clock">{{ ist_now().strftime('%H:%M:%S') }}</div>
</div>

{% if message %}
<div class="toast">{{ message }}</div>
{% endif %}
{% if error %}
<div class="toast error">{{ error }}</div>
{% endif %}

<form method="POST">

<table>
{% for slot in range(1, TOTAL_SLOTS + 1) %}
{% set row = task_map.get(slot) %}
<tr class="{% if is_past_slot(selected_date, slot) %}past{% endif %}">
  <td>🕒 {{ slot_label(slot) }}</td>
  <td>
    <input style="width:100%" name="desc_{{slot}}" value="{{ row.description if row else '' }}">
  </td>
  <td>
    <select name="status_{{slot}}">
      {% for s in STATUSES %}
      <option value="{{s}}" {% if row and row.status==s %}selected{% endif %}>{{s}}</option>
      {% endfor %}
    </select>
  </td>
</tr>
{% endfor %}
</table>

<div class="habits">
<h3>Habits</h3>
{% for h, icon in HABIT_LIST %}
<label>
<input type="checkbox" name="habits" value="{{h}}" {% if h in habits_selected %}checked{% endif %}>
{{ icon }} {{ h }}
</label><br>
{% endfor %}
</div>

<div class="reflection">
<h3>🧠 Reflection of the Day</h3>
<textarea name="reflection" style="width:100%" rows="4">{{ reflection_text }}</textarea>
</div>

<div class="floating">
<button type="submit">💾 Save</button>
<a href="/" style="flex:1"><button type="button">❌ Cancel</button></a>
</div>

</form>

</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True)
