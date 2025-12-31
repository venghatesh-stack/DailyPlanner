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
# DATA ACCESS : DAILY PLANNER
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
# DATA ACCESS : TODO MATRIX
# ===============================
def load_todo(plan_date):
    rows = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{plan_date}",
            "select": "id,quadrant,task_text"
        }
    ) or []

    data = {"do": [], "schedule": [], "delegate": [], "eliminate": []}
    for r in rows:
        data[r["quadrant"]].append(r)

    return data

def save_todo(plan_date, form):
    delete("todo_matrix", params={"plan_date": f"eq.{plan_date}"})

    payload = []
    for q in ["do", "schedule", "delegate", "eliminate"]:
        text = form.get(q, "").strip()
        if text:
            for line in text.splitlines():
                if line.strip():
                    payload.append({
                        "plan_date": str(plan_date),
                        "quadrant": q,
                        "task_text": line.strip()
                    })

    if payload:
        post("todo_matrix", payload)

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
        today=today,
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

@app.route("/todo", methods=["GET", "POST"])
def todo_page():
    today = datetime.now(IST).date()
    plan_date = today

    if request.method == "POST":
        save_todo(plan_date, request.form)
        return redirect(url_for("todo_page", saved=1))

    todo = load_todo(plan_date)

    return render_template_string(
        TODO_TEMPLATE,
        todo=todo,
        plan_date=plan_date,
        saved=request.args.get("saved")
    )

# ===============================
# TEMPLATE (HTML + JS)
# ===============================
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {
  font-family: system-ui;
  background:#f6f7f9;
  padding:12px;
  padding-bottom:220px;
}
.container {
  max-width:1100px;
  margin:auto;
  background:#fff;
  padding:20px;
  padding-top:28px;
  border-radius:14px;
}
.header-bar {
  display:flex;
  justify-content:space-between;
  align-items:center;
  min-height:36px;
}
.header-time { font-weight:700; color:#2563eb; }
.month-controls, .day-strip { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
.day-btn {
  width:36px; height:36px;
  border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  border:1px solid #ddd;
  text-decoration:none; color:#000;
}
.day-btn.selected { background:#2563eb; color:#fff; }
table { width:100%; border-collapse:collapse; }
td { padding:8px; border-bottom:1px solid #eee; }
.current-slot { background:#eef2ff; border-left:4px solid #2563eb; }
textarea { width:100%; min-height:90px; font-size:16px; }
.floating-bar {
  position:fixed;
  bottom:0; left:0; right:0;
  background:#fff;
  border-top:1px solid #ddd;
  display:flex;
  padding:10px;
  gap:10px;
}
.floating-bar button { flex:1; padding:14px; font-size:16px; }
</style>
</head>

<body>

{% if saved %}
<div style="position:fixed;bottom:90px;left:50%;transform:translateX(-50%);
background:#dcfce7;padding:10px 16px;border-radius:999px;font-weight:600;">
✅ Saved successfully
</div>
{% endif %}

<div class="container">

<div class="header-bar">
  <div id="current-date"></div>
  <div style="display:flex;gap:14px;align-items:center;">
    <a href="/todo">📋 To-Do Matrix</a>
    <div class="header-time">🕒 <span id="current-time"></span> IST</div>
  </div>
</div>

<form method="get" class="month-controls">
  <input type="hidden" name="day" value="{{ selected_day }}">
  <select name="month" onchange="this.form.submit()">
    {% for m in range(1,13) %}
      <option value="{{m}}" {% if m==month %}selected{% endif %}>{{ calendar.month_name[m] }}</option>
    {% endfor %}
  </select>
  <select name="year" onchange="this.form.submit()">
    {% for y in range(year-5, year+6) %}
      <option value="{{y}}" {% if y==year %}selected{% endif %}>{{y}}</option>
    {% endfor %}
  </select>
</form>

<div class="day-strip">
{% for d in days %}
<a href="/?year={{year}}&month={{month}}&day={{d.day}}"
   class="day-btn {% if d.day==selected_day %}selected{% endif %}">
{{ d.day }}
</a>
{% endfor %}
</div>

<form method="post" id="planner-form">
<table>
{% for slot in range(1,total_slots+1) %}
<tr class="{% if now_slot==slot %}current-slot{% endif %}" data-slot="{{slot}}">
  <td>{{ slot_labels[slot] }}</td>
</tr>
<tr>
  <td><textarea name="plan_{{slot}}">{{ plans[slot]['plan'] }}</textarea></td>
</tr>
{% endfor %}
</table>
</form>
</div>

<div class="floating-bar">
  <button type="submit" form="planner-form">💾 Save</button>
  <button type="button" onclick="cancelEdit()">❌ Cancel</button>
</div>

<script>
function updateClock(){
  const ist = new Date(new Date().toLocaleString("en-US",{timeZone:"Asia/Kolkata"}));
  document.getElementById("current-time").textContent = ist.toLocaleTimeString();
  document.getElementById("current-date").textContent = ist.toDateString();
}
setInterval(updateClock,1000); updateClock();

function cancelEdit(){
  const url = new URL(window.location.href);
  url.searchParams.delete("saved");
  window.location.href = url.toString();
}

window.addEventListener("load", () => {
  const dayBtn = document.querySelector(".day-btn.selected");
  if(dayBtn) dayBtn.scrollIntoView({inline:"center"});

  const currentRow = document.querySelector(".current-slot");
  if(currentRow){
    currentRow.scrollIntoView({block:"center"});
    const textarea = currentRow.nextElementSibling?.querySelector("textarea");
    if(textarea){
      textarea.focus();
      textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    }
  }
});
</script>

</body>
</html>
"""

# ===============================
# TODO TEMPLATE
# ===============================
TODO_TEMPLATE = """
<!DOCTYPE html>
<html>
<body>
<h2>Eisenhower Matrix – {{ plan_date }}</h2>
<form method="post">
<textarea name="do">{% for t in todo.do %}{{t.task_text}}{% endfor %}</textarea>
<textarea name="schedule">{% for t in todo.schedule %}{{t.task_text}}{% endfor %}</textarea>
<textarea name="delegate">{% for t in todo.delegate %}{{t.task_text}}{% endfor %}</textarea>
<textarea name="eliminate">{% for t in todo.eliminate %}{{t.task_text}}{% endfor %}</textarea>
<button type="submit">Save</button>
</form>
<a href="/">Back</a>
</body>
</html>
"""

if __name__ == "__main__":
    logger.info("Starting Daily Planner")
    app.run(debug=True)
