from flask import Flask, request, redirect, url_for, render_template_string
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar
import urllib.parse
import json

from supabase_client import get, post
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
# HELPERS
# ===============================
def slot_label(slot: int) -> str:
    start = datetime.min + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return f"{start.strftime('%I:%M %p')} – {end.strftime('%I:%M %p')}"

def slot_start_end(plan_date: date, slot: int):
    start = datetime.combine(plan_date, datetime.min.time(), tzinfo=IST) + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return start, end

def current_slot() -> int:
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
        "dates": f"{start_utc.strftime('%Y%m%dT%H%M%SZ')}/{end_utc.strftime('%Y%m%dT%H%M%SZ')}",
        "details": "Created from Daily Planner",
        "trp": "false"
    }
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)

# ===============================
# DATA ACCESS
# ===============================
def load_day(plan_date):
    plans = {i: {"plan": "", "status": DEFAULT_STATUS} for i in range(1, TOTAL_SLOTS + 1)}
    habits = set()
    reflection = ""

    rows = get("daily_slots", params={
        "plan_date": f"eq.{plan_date}",
        "select": "slot,plan,status"
    }) or []

    for r in rows:
        if r["slot"] == META_SLOT:
            try:
                meta = json.loads(r.get("plan") or "{}")
                habits = set(meta.get("habits", []))
                reflection = meta.get("reflection", "")
            except Exception:
                pass
        else:
            plans[r["slot"]] = {
                "plan": r.get("plan") or "",
                "status": r.get("status") or DEFAULT_STATUS
            }

    return plans, habits, reflection

def save_day(plan_date, form):
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
            "reflection": form.get("reflection", "").strip()
        }),
        "status": DEFAULT_STATUS
    })

    post(
        "daily_slots?on_conflict=plan_date,slot",
        payload,
        prefer="resolution=merge-duplicates"
    )

# ===============================
# ROUTES
# ===============================
@app.route("/", methods=["GET", "POST"])
def plan_of_day():
    today = datetime.now(IST).date()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    day_param = request.args.get("day")
    plan_date = date(year, month, int(day_param)) if day_param else today

    if request.method == "POST":
        save_day(plan_date, request.form)
        return redirect(url_for(
            "plan_of_day",
            year=plan_date.year,
            month=plan_date.month,
            day=plan_date.day,
            saved=1
        ))

    plans, habits, reflection = load_day(plan_date)

    reminder_links = {
        slot: google_calendar_link(plan_date, slot, plans[slot]["plan"])
        for slot in range(1, TOTAL_SLOTS + 1)
    }

    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]

    return render_template_string(
        TEMPLATE,
        year=year,
        month=month,
        days=days,
        selected_day=plan_date.day,
        plans=plans,
        statuses=STATUSES,
        total_slots=TOTAL_SLOTS,
        slot_labels={i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)},
        reminder_links=reminder_links,
        now_slot=current_slot() if plan_date == today else None,
        saved=request.args.get("saved"),
        habits=habits,
        reflection=reflection,
        habit_list=HABIT_LIST,
        habit_icons=HABIT_ICONS,
        calendar=calendar
    )

@app.route("/weekly")
def weekly():
    today = datetime.now(IST).date()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)

    rows = get("daily_slots", params={
        "plan_date": f"gte.{start}",
        "order": "plan_date.asc"
    }) or []

    return render_template_string(WEEKLY_TEMPLATE, rows=rows, start=start, end=end)

# ===============================
# TEMPLATE
# ===============================
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: system-ui; background:#f6f7f9; padding:12px; padding-bottom:170px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:16px; border-radius:14px; }

.day-strip { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
.day-btn { width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;border:1px solid #ddd;text-decoration:none;color:#000; }
.day-btn.selected { background:#2563eb;color:#fff; }

table { width:100%; border-collapse:collapse; }
td { padding:8px; border-bottom:1px solid #eee; }

.slot-time { background:#f9fafb; font-weight:600; }
.slot-task textarea { width:100%; min-height:60px; font-size:16px; }
.slot-status select { width:100%; padding:8px; }

.floating-bar {
  position:fixed;
  bottom:0; left:0; right:0;
  background:#fff;
  border-top:1px solid #ddd;
  padding:10px;
  display:flex;
  gap:10px;
  z-index:9999;
}
.floating-bar button, .floating-bar a {
  flex:1;
  padding:14px;
  font-size:16px;
  text-align:center;
}
</style>
</head>

<body>

<div class="container">
<form method="post" id="planner-form">

<table>
{% for slot in range(1,total_slots+1) %}
<tr class="slot-time">
  <td colspan="3">
    {{ slot_labels[slot] }}
    {% if plans[slot]['plan'] %}
      <a href="{{ reminder_links[slot] }}" target="_blank">⏰</a>
    {% endif %}
  </td>
</tr>
<tr class="slot-task">
  <td colspan="3">
    <textarea name="plan_{{slot}}">{{ plans[slot]['plan'] }}</textarea>
  </td>
</tr>
<tr class="slot-status">
  <td colspan="3">
    <select name="status_{{slot}}">
      {% for s in statuses %}
        <option {% if s==plans[slot]['status'] %}selected{% endif %}>{{s}}</option>
      {% endfor %}
    </select>
  </td>
</tr>
{% endfor %}
</table>

<h3>🏃 Habits</h3>
{% for h in habit_list %}
<label>
<input type="checkbox" name="habits" value="{{h}}" {% if h in habits %}checked{% endif %}>
{{ habit_icons[h] }} {{h}}
</label>
{% endfor %}

<h3>📝 Reflection</h3>
<textarea name="reflection" rows="3">{{reflection}}</textarea>

</form>
</div>

<div class="floating-bar">
  <button type="submit" form="planner-form">💾 Save</button>
  <button type="button" onclick="window.location.reload()">❌ Cancel</button>
  <a href="/weekly">📊 Weekly</a>
</div>

</body>
</html>
"""

WEEKLY_TEMPLATE = """
<!DOCTYPE html>
<html>
<body>
<h2>Weekly Summary</h2>
<p>{{start}} → {{end}}</p>
{% for r in rows %}
{% if r.slot == 0 %}
<div>{{ r.plan_date }} – {{ r.plan }}</div>
{% endif %}
{% endfor %}
<a href="/">Back</a>
</body>
</html>
"""

if __name__ == "__main__":
    logger.info("Starting Daily Planner (stable restored build)")
    app.run(debug=True)
