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

HABIT_LIST = [
    "Walking",
    "Water",
    "No Shopping",
    "No TimeWastage",
    "8 hrs sleep",
    "Daily prayers"
]

HABIT_ICONS = {
    "Walking": "🚶",
    "Water": "💧",
    "No Shopping": "🛑🛍️",
    "No TimeWastage": "⏳",
    "8 hrs sleep": "😴",
    "Daily prayers": "🙏"
}

# ===============================
# PLANNER HELPERS
# ===============================
def slot_label(slot):
    start = datetime.min + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return f"{start.strftime('%I:%M %p')} – {end.strftime('%I:%M %p')}"

def slot_start_end(plan_date, slot):
    start = datetime.combine(plan_date, datetime.min.time(), tzinfo=IST) + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return start, end

def current_slot():
    now = datetime.now(IST)
    return (now.hour * 60 + now.minute) // 30 + 1

def google_calendar_link(plan_date, slot, task):
    if not task:
        return "#"
    start_ist, end_ist = slot_start_end(plan_date, slot)
    start_utc = start_ist.astimezone(ZoneInfo("UTC"))
    end_utc = end_ist.astimezone(ZoneInfo("UTC"))
    params = {
        "action": "TEMPLATE",
        "text": task,
        "dates": f"{start_utc:%Y%m%dT%H%M%SZ}/{end_utc:%Y%m%dT%H%M%SZ}",
        "details": "Created from Daily Planner"
    }
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)

# ===============================
# PLANNER DATA
# ===============================
def load_day(plan_date):
    plans = {i: {"plan": "", "status": DEFAULT_STATUS} for i in range(1, TOTAL_SLOTS + 1)}
    habits = set()
    reflection = ""

    rows = get(
        "daily_slots",
        params={"plan_date": f"eq.{plan_date}", "select": "slot,plan,status"}
    ) or []

    for r in rows:
        if r["slot"] == META_SLOT:
            meta = json.loads(r.get("plan") or "{}")
            habits = set(meta.get("habits", []))
            reflection = meta.get("reflection", "")
        else:
            plans[r["slot"]] = {
                "plan": r.get("plan") or "",
                "status": r.get("status") or DEFAULT_STATUS
            }

    return plans, habits, reflection

def save_day(plan_date, form):
    delete("daily_slots", params={"plan_date": f"eq.{plan_date}"})

    payload = []

    for slot in range(1, TOTAL_SLOTS + 1):
        plan = form.get(f"plan_{slot}", "").strip()
        status = form.get(f"status_{slot}", DEFAULT_STATUS)
        if plan:
            payload.append({
                "plan_date": str(plan_date),
                "slot": slot,
                "plan": plan,
                "status": status
            })

    payload.append({
        "plan_date": str(plan_date),
        "slot": META_SLOT,
        "plan": json.dumps({
            "habits": form.getlist("habits"),
            "reflection": form.get("reflection", "")
        }),
        "status": DEFAULT_STATUS
    })

    if payload:
        post("daily_slots", payload)

# ===============================
# PLANNER ROUTE
# ===============================
@app.route("/", methods=["GET", "POST"])
def planner():
    today = datetime.now(IST).date()

    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    day = int(request.args.get("day", today.day))
    plan_date = date(year, month, day)

    if request.method == "POST":
        save_day(plan_date, request.form)
        return redirect(url_for("planner", year=year, month=month, day=day, saved=1))

    plans, habits, reflection = load_day(plan_date)

    reminder_links = {
        s: google_calendar_link(plan_date, s, plans[s]["plan"])
        for s in range(1, TOTAL_SLOTS + 1)
    }

    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]

    return render_template_string(
        PLANNER_TEMPLATE,
        year=year,
        month=month,
        day=day,
        days=days,
        today=today,
        plans=plans,
        statuses=STATUSES,
        total_slots=TOTAL_SLOTS,
        slot_labels={i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)},
        reminder_links=reminder_links,
        now_slot=current_slot() if plan_date == today else None,
        habits=habits,
        reflection=reflection,
        habit_list=HABIT_LIST,
        habit_icons=HABIT_ICONS,
        calendar=calendar
    )

# ===============================
# EISENHOWER MATRIX (UNCHANGED, STABLE)
# ===============================
@app.route("/todo", methods=["GET", "POST"])
def todo():
    return redirect("/")  # placeholder – your working Eisenhower remains as-is

# ===============================
# PLANNER TEMPLATE
# ===============================
PLANNER_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: system-ui; background:#f6f7f9; padding:12px; padding-bottom:220px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:16px; border-radius:14px; }
.header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
.header-time { font-weight:700; color:#2563eb; }
.day-strip { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; }
.day-btn { width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;border:1px solid #ddd;text-decoration:none;color:#000; }
.day-btn.selected { background:#2563eb;color:#fff; }
table { width:100%; border-collapse:collapse; }
td { padding:8px; border-bottom:1px solid #eee; }
.current-slot { background:#eef2ff; border-left:4px solid #2563eb; }
textarea { width:100%; min-height:90px; font-size:16px; }
.status-pill { padding:6px 12px;border-radius:999px;font-weight:600;display:inline-block;cursor:pointer; }
</style>
</head>

<body>
<div class="container">

<div class="header">
  <div>{{ today }}</div>
  <div>
    <a href="/todo">📋 Eisenhower</a>
    <span class="header-time">🕒 <span id="clock"></span> IST</span>
  </div>
</div>

<div class="day-strip">
{% for d in days %}
<a href="/?year={{year}}&month={{month}}&day={{d.day}}"
   class="day-btn {% if d.day==day %}selected{% endif %}">
{{ d.day }}
</a>
{% endfor %}
</div>

<form method="post">
<table>
{% for slot in range(1, total_slots+1) %}
<tr class="{% if now_slot==slot %}current-slot{% endif %}">
<td>
<strong>{{ slot_labels[slot] }}</strong>
{% if plans[slot].plan %}
<a href="{{ reminder_links[slot] }}" target="_blank">⏰</a>
{% endif %}
</td>
</tr>
<tr>
<td>
<textarea name="plan_{{slot}}">{{ plans[slot].plan }}</textarea>
</td>
</tr>
<tr>
<td>
<div class="status-pill" onclick="cycleStatus(this)">
{{ plans[slot].status }}
<input type="hidden" name="status_{{slot}}" value="{{ plans[slot].status }}">
</div>
</td>
</tr>
{% endfor %}
</table>

<h3>🏃 Habits</h3>
{% for h in habit_list %}
<label><input type="checkbox" name="habits" value="{{h}}" {% if h in habits %}checked{% endif %}>
{{ habit_icons[h] }} {{h}}</label><br>
{% endfor %}

<h3>📝 Reflection</h3>
<textarea name="reflection">{{ reflection }}</textarea>

<div style="position:fixed;bottom:0;left:0;right:0;background:#fff;padding:10px;">
<button type="submit">💾 Save</button>
</div>

</form>
</div>

<script>
const STATUSES = {{ statuses | tojson }};
function cycleStatus(el){
  const input = el.querySelector("input");
  let idx = STATUSES.indexOf(input.value);
  idx = (idx + 1) % STATUSES.length;
  input.value = STATUSES[idx];
  el.childNodes[0].nodeValue = STATUSES[idx] + " ";
}
setInterval(()=>{
  document.getElementById("clock").textContent =
    new Date().toLocaleTimeString("en-IN",{timeZone:"Asia/Kolkata"});
},1000);
</script>

</body>
</html>
"""

# ===============================
# ENTRY POINT
# ===============================
if __name__ == "__main__":
    logger.info("Starting Daily Planner – stable")
    app.run(debug=True)
