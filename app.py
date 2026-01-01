from flask import Flask, request, redirect, url_for, render_template_string
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar
import urllib.parse
import json

from supabase_client import get, post,delete 
from logger import setup_logger

# ==========================================================
# APP SETUP
# ==========================================================
IST = ZoneInfo("Asia/Kolkata")
app = Flask(__name__)
logger = setup_logger()

# ==========================================================
# CONSTANTS
# ==========================================================
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

# ==========================================================
# HELPERS
# ==========================================================
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

# ==========================================================
# DATA ACCESS – DAILY PLANNER
# ==========================================================
def load_day(plan_date):
    plans = {i: {"plan": "", "status": DEFAULT_STATUS} for i in range(1, TOTAL_SLOTS + 1)}
    habits = set()
    reflection = ""

    rows = get(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date}",
            "select": "slot,plan,status"
        }
    ) or []

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

# ==========================================================
# DATA ACCESS – EISENHOWER
# ==========================================================
def load_todo(plan_date):
    rows = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{plan_date}",
            "select": "id,quadrant,task_text,is_done,position",
            "order": "position.asc"
        }
    ) or []

    data = {"do": [], "schedule": [], "delegate": [], "eliminate": []}
    for r in rows:
        data[r["quadrant"]].append({
            "id": r["id"],
            "text": r["task_text"],
            "done": bool(r.get("is_done")),
        })
    return data

def save_todo(plan_date, form):
    # Clear existing tasks for the day
    logger.info("Saving Eisenhower matrix")

    delete(
        "todo_matrix",
        params={"plan_date": f"eq.{plan_date}"}
    )

    payload = []
    for quadrant in ["do", "schedule", "delegate", "eliminate"]:
      texts = form.getlist(f"{quadrant}[]")
      checked_indexes = {
            int(i)
            for i in form.getlist(f"{quadrant}_done[]")
            if i.isdigit()
      }



      for idx, text in enumerate(texts):
        text = text.strip()
        if not text:
            continue
        is_done = idx in checked_indexes
        payload.append({
            "plan_date": str(plan_date),
            "quadrant": quadrant,
            "task_text": text,
            "is_done": is_done,
            "position": idx
        })

    if payload:
        post("todo_matrix", payload)
    logger.info(
    f"Eisenhower saved: date={plan_date}, tasks={len(payload)}"
)

# ==========================================================
# ROUTES – DAILY PLANNER
# ==========================================================
@app.route("/", methods=["GET", "POST"])
def planner():
    today = datetime.now(IST).date()

    if request.method == "POST":
      year = int(request.form["year"])
      month = int(request.form["month"])
      day = int(request.form["day"])
    else:
      year = int(request.args.get("year", today.year))
      month = int(request.args.get("month", today.month))
      day = int(request.args.get("day", today.day))

    plan_date = date(year, month, day)
    logger.info(f"Saving planner for date={plan_date}")


    if request.method == "POST":
        save_day(plan_date, request.form)
        return redirect(url_for("planner", year=year, month=month, day=plan_date.day, saved=1))

    plans, habits, reflection = load_day(plan_date)

    days = [
        date(year, month, d)
        for d in range(1, calendar.monthrange(year, month)[1] + 1)
    ]

    reminder_links = {
        slot: google_calendar_link(plan_date, slot, plans[slot]["plan"])
        for slot in range(1, TOTAL_SLOTS + 1)
    }

    return render_template_string(
        PLANNER_TEMPLATE,
        year=year,
        month=month,
        days=days,
        selected_day=plan_date.day,
        today=today,
        plans=plans,
        statuses=STATUSES,
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

# ==========================================================
# ROUTES – EISENHOWER MATRIX
# ==========================================================
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

    todo = load_todo(plan_date)

    return render_template_string(
        TODO_TEMPLATE,
        todo=todo,
        plan_date=plan_date
    )

# ==========================================================
# TEMPLATE – DAILY PLANNER (UNCHANGED, STABLE)
# ==========================================================
##PLANNER_TEMPLATE = """<-- SAME AS YOUR RESTORED VERSION, UNCHANGED -->"""

PLANNER_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: system-ui; background:#f6f7f9; padding:12px; padding-bottom:220px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:16px; border-radius:14px; }

.header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
.header a { font-weight:600; text-decoration:none; }
.time { color:#2563eb; font-weight:700; }

.month-controls { display:flex; gap:8px; margin-bottom:12px; }
.day-strip { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }

.day-btn {
  width:36px; height:36px;
  border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  border:1px solid #ddd;
  text-decoration:none; color:#000;
}
.day-btn.selected { background:#2563eb; color:#fff; }

.slot { border-bottom:1px solid #eee; padding-bottom:12px; margin-bottom:12px; }
.current { background:#eef2ff; border-left:4px solid #2563eb; padding-left:8px; }

textarea { width:100%; min-height:90px; font-size:15px; }

.status-pill {
  display:inline-block;
  padding:6px 12px;
  border-radius:999px;
  font-weight:600;
  cursor:pointer;
}
.status-Nothing\\ Planned { background:#e5e7eb; }
.status-Yet\\ to\\ Start { background:#fde68a; }
.status-In\\ Progress { background:#bfdbfe; }
.status-Closed { background:#bbf7d0; }
.status-Deferred { background:#fecaca; }

.floating-bar {
  position:fixed;
  bottom:env(safe-area-inset-bottom,0);
  left:0; right:0;
  background:#fff;
  border-top:1px solid #ddd;
  padding:10px;
  display:flex;
  gap:10px;
}
.floating-bar button { flex:1; padding:14px; font-size:16px; }
</style>
</head>

<body>

<div class="container">

<div class="header">
  <div>{{ today }}</div>
  <div>
    <a href="/todo">📋 Eisenhower</a>
    &nbsp;&nbsp;
    <span class="time">🕒 <span id="clock"></span> IST</span>
  </div>
</div>

<form method="get" class="month-controls">
  <input type="hidden" name="day" value="{{ selected_day }}">
  <select name="month" onchange="this.form.submit()">
    {% for m in range(1,13) %}
      <option value="{{m}}" {% if m==month %}selected{% endif %}>
        {{ calendar.month_name[m] }}
      </option>
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
  {{d.day}}
</a>
{% endfor %}
</div>

<form method="post" id="planner-form">
<input type="hidden" name="year" value="{{ year }}">
<input type="hidden" name="month" value="{{ month }}">
<input type="hidden" name="day" value="{{ selected_day }}">

{% for slot in plans %}
<div class="slot {% if now_slot==slot %}current{% endif %}">
  <strong>{{ slot_labels[slot] }}</strong>
  {% if plans[slot].plan %}
    <a href="{{ reminder_links[slot] }}" target="_blank">⏰</a>
  {% endif %}
  <textarea name="plan_{{slot}}">{{ plans[slot].plan }}</textarea>

  <div class="status-pill status-{{ plans[slot].status }}" onclick="cycleStatus(this)">
    {{ plans[slot].status }}
    <input type="hidden" name="status_{{slot}}" value="{{ plans[slot].status }}">
  </div>
</div>
{% endfor %}

<h3>🏃 Habits</h3>
{% for h in habit_list %}
<label>
  <input type="checkbox" name="habits" value="{{h}}" {% if h in habits %}checked{% endif %}>
  {{ habit_icons[h] }} {{h}}
</label><br>
{% endfor %}

<h3>📝 Reflection</h3>
<textarea name="reflection">{{ reflection }}</textarea>

</form>
</div>

<div class="floating-bar">
  <button type="submit" form="planner-form">💾 Save</button>
  <button type="button" onclick="window.location.reload()">❌ Cancel</button>
</div>

<script>
function updateClock(){
  const ist = new Date(new Date().toLocaleString("en-US",{timeZone:"Asia/Kolkata"}));
  document.getElementById("clock").textContent = ist.toLocaleTimeString();
}
setInterval(updateClock,1000); updateClock();

const STATUS_ORDER = {{ statuses|tojson }};
function cycleStatus(el){
  const input = el.querySelector("input");
  let idx = STATUS_ORDER.indexOf(input.value);
  idx = (idx + 1) % STATUS_ORDER.length;
  input.value = STATUS_ORDER[idx];
  el.childNodes[0].nodeValue = STATUS_ORDER[idx] + " ";
}
</script>

</body>
</html>
"""
# NOTE: Use the exact PLANNER_TEMPLATE you already validated as correct.
# (Intentionally not duplicated again to avoid accidental edits.)

# ==========================================================
# TEMPLATE – EISENHOWER MATRIX
# ==========================================================
TODO_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: system-ui; background:#f6f7f9; padding:16px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:20px; border-radius:14px; }
.matrix { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.quad { border:1px solid #e5e7eb; border-radius:12px; padding:12px; }
.task { display:flex; gap:8px; align-items:center; margin-bottom:6px; }
.task input[type=text] { flex:1; padding:6px; }
@media(max-width:768px){ .matrix{ grid-template-columns:1fr; } }
</style>
</head>

<body>
<div class="container">
<h2>📋 Eisenhower Matrix – {{ plan_date }}</h2>
<a href="/">⬅ Back to Daily Planner</a>

<form method="post">
<div class="matrix">

{% for q,label in [
 ('do','🔥 Do Now'),
 ('schedule','📅 Schedule'),
 ('delegate','🤝 Delegate'),
 ('eliminate','🗑 Eliminate')
] %}
<div class="quad">
<h3>{{label}}</h3>

<div id="{{q}}">
{% for t in todo[q] %}
  <div class="task">
    
   <input type="checkbox"
       name="{{q}}_done[]"
       value="{{ loop.index0 }}"
       {% if t.done %}checked{% endif %}>

    <input type="text" name="{{q}}[]" value="{{t.text}}">

    <button type="button" onclick="this.parentElement.remove()">−</button>
  </div>
{% endfor %}
</div>

<button type="button" onclick="addTask('{{q}}')">+ Add</button>
</div>
{% endfor %}

</div>

<br>
<button type="submit">💾 Save</button>
</form>
</div>


<script>
function addTask(q){
  const div = document.getElementById(q);
  const row = document.createElement("div");
  row.className = "task";
  row.innerHTML = `
    <input type="checkbox" name="${q}_done[]">
    <input type="text" name="${q}[]" autofocus>
    <button type="button" onclick="this.parentElement.remove()">−</button>
  `;
  div.appendChild(row);
}
</script>

</body>
</html>
"""

# ==========================================================
# ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    logger.info("Starting Daily Planner – stable + Eisenhower")
    app.run(debug=True)