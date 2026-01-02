## Eisenhower Matrix + Daily Planner integrated. Calender control working
from flask import Flask, request, redirect, url_for, render_template_string, session
from functools import wraps
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar
import urllib.parse
import json

from supabase_client import get, post,delete,update  
from logger import setup_logger

# ==========================================================
# APP SETUP
# ==========================================================
IST = ZoneInfo("Asia/Kolkata")
app = Flask(__name__)
logger = setup_logger()
# ==========================================================
# Log in codestarts here
# ==========================================================

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "changeme")

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

# ==========================================================
# Log in code ends here
# ==========================================================

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
MOTIVATIONAL_QUOTES = [
    {"icon": "🎯", "text": "Focus on what matters, not what screams loudest."},
    {"icon": "⏳", "text": "Urgent is not always important."},
    {"icon": "🧠", "text": "Clarity comes from prioritization."},
    {"icon": "📌", "text": "Do the right thing, not everything."},
    {"icon": "📅", "text": "What you schedule gets done."},
    {"icon": "🌱", "text": "Small progress each day adds up."},
    {"icon": "✂️", "text": "Decide what not to do."},
    {"icon": "🧭", "text": "Your priorities shape your future."},
    {"icon": "⚡", "text": "Action beats intention."},
    {"icon": "☀️", "text": "Important tasks deserve calm attention."}
]
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
            "select": "id,quadrant,task_text,is_done,position,task_date,task_time",
            "order": "position.asc"
        }
    ) or []

    data = {"do": [], "schedule": [], "delegate": [], "eliminate": []}
    for r in rows:
      data[r["quadrant"]].append({
            "id": r["id"],
            "text": r["task_text"],
            "done": bool(r.get("is_done")),
            "task_date": r.get("task_date"),
            "task_time": r.get("task_time")
        })
    for q in data:
        data[q].sort(
            key=lambda t: (
                t["task_date"] is None,   # False first (has date), True last (no date)
                t["task_date"] or ""
            )
        )


    return data

def save_todo(plan_date, form):
    logger.info("Saving Eisenhower matrix")

    existing_rows = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{plan_date}",
            "select": "id"
        }
    ) or []

    existing_ids = {str(row["id"]) for row in existing_rows}
    seen_ids = set()

    for quadrant in ["do", "schedule", "delegate", "eliminate"]:

        texts = form.getlist(f"{quadrant}[]")
        dates = form.getlist(f"{quadrant}_date[]")
        times = form.getlist(f"{quadrant}_time[]")
        ids   = form.getlist(f"{quadrant}_id[]")

        # -----------------------------------
        # 1️⃣ Build done_state FIRST
        # -----------------------------------
        done_state = {}
        prefix = f"{quadrant}_done_state["

        for key, values in form.to_dict(flat=False).items():
            if key.startswith(prefix) and key.endswith("]"):
                task_id = key[len(prefix):-1]
                done_state[task_id] = values

        # -----------------------------------
        # 2️⃣ Now process tasks ONCE
        # -----------------------------------
        for idx, text in enumerate(texts):
            text = text.strip()
            if not text:
                continue

            task_id = ids[idx] if idx < len(ids) else None
            if not task_id:
                continue

            task_date = dates[idx] if idx < len(dates) and dates[idx] else None
            task_time = times[idx] if idx < len(times) and times[idx] else None

            is_done = "1" in done_state.get(str(task_id), [])

            payload = {
                "quadrant": quadrant,
                "task_text": text,
                "task_date": task_date,
                "task_time": task_time,
                "is_done": is_done,
                "position": idx
            }

            if str(task_id) in existing_ids:
                seen_ids.add(str(task_id))
                update(
                    "todo_matrix",
                    params={"id": f"eq.{task_id}"},
                    json=payload
                )
            else:
                payload["plan_date"] = str(plan_date)
                post("todo_matrix", payload)

    removed_ids = existing_ids - seen_ids
    for task_id in removed_ids:
        delete(
            "todo_matrix",
            params={"id": f"eq.{task_id}"}
        )


def copy_open_tasks_from_previous_day(plan_date):
    prev_date = plan_date - timedelta(days=1)

    # Load yesterday's tasks
    prev_rows = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{prev_date}",
            "select": "quadrant,task_text,is_done,position,task_date,task_time",
            "order": "position.asc"
        }
    ) or []

    if not prev_rows:
        return 0

    # Load today's tasks to see which quadrants already exist
    today_rows = get(
        "todo_matrix",
        params={
            "plan_date": f"eq.{plan_date}",
            "select": "quadrant"
        }
    ) or []

    existing_quadrants = {r["quadrant"] for r in today_rows}

    payload = []
    for r in prev_rows:
        # Copy ONLY open tasks
        if r.get("is_done"):
            continue

        # Copy ONLY if quadrant is missing today
        if r["quadrant"] in existing_quadrants:
            continue

        payload.append({
          "plan_date": str(plan_date),
          "quadrant": r["quadrant"],
          "task_text": r["task_text"],
          "is_done": False,
          "task_date": r.get("task_date"),
          "task_time": r.get("task_time"),
          "position": r.get("position", 0)
      })
    if payload:
      post("todo_matrix", payload)

    return len(payload)
# ==========================================================
# Log in codestarts here
# ==========================================================

LOGIN_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Login</title>
  <style>
    body {
      font-family: system-ui;
      background: #f6f7f9;
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100vh;
      margin: 0;
    }
    .login-box {
      background: #fff;
      padding: 24px;
      border-radius: 14px;
      width: 300px;
      box-shadow: 0 10px 25px rgba(0,0,0,.08);
    }
    h3 { margin-top: 0; }
    input {
      width: 100%;
      padding: 10px;
      margin-top: 10px;
      font-size: 15px;
    }
    button {
      width: 100%;
      padding: 12px;
      margin-top: 14px;
      font-size: 15px;
      font-weight: 600;
    }
    .error {
      color: #dc2626;
      font-size: 13px;
      margin-top: 10px;
    }
  </style>
</head>
<body>
  <form method="post" class="login-box">
    <h3>🔒 Login</h3>
    <input type="password" name="password" placeholder="Password" autofocus>
    <button type="submit">Continue</button>
    {% if error %}
      <div class="error">{{ error }}</div>
    {% endif %}
  </form>
</body>
</html>
"""

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("planner"))
        return render_template_string(LOGIN_TEMPLATE, error="Invalid password")

    return render_template_string(LOGIN_TEMPLATE)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ==========================================================
# Log in code ends here
# ==========================================================
@app.route("/health", methods=["GET", "HEAD"])
def health():
    return "OK", 200
# ==========================================================
# ROUTES – DAILY PLANNER
# ==========================================================
@app.route("/", methods=["GET", "POST"])
@login_required
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
@login_required
def todo():
    today = datetime.now(IST).date()

    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    day = int(request.args.get("day", today.day))
    plan_date = date(year, month, day)

    if request.method == "POST":
        save_todo(plan_date, request.form)
        return redirect(url_for("todo", year=year, month=month, day=day,saved=1))

    todo = load_todo(plan_date)

    days = [
        date(year, month, d)
        for d in range(1, calendar.monthrange(year, month)[1] + 1)
    ]
    quote = MOTIVATIONAL_QUOTES[plan_date.day % len(MOTIVATIONAL_QUOTES)]
    return render_template_string(
        TODO_TEMPLATE,
        todo=todo,
        plan_date=plan_date,
        year=year,
        month=month,
        days=days,
        calendar=calendar,
        quote=quote
    )

@app.route("/todo/copy-prev", methods=["POST"])
@login_required
def copy_prev_todo():
    today = datetime.now(IST).date()

    year = int(request.form.get("year", today.year))
    month = int(request.form.get("month", today.month))
    day = int(request.form.get("day", today.day))
    plan_date = date(year, month, day)

    copied = copy_open_tasks_from_previous_day(plan_date)
    logger.info(f"Copied {copied} Eisenhower tasks from previous day")

    return redirect(url_for("todo", year=year, month=month, day=day))

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
{% if saved %}
<div id="toast"
     style="
       position: fixed;
       bottom: 90px;
       left: 50%;
       transform: translateX(-50%);
       background: #16a34a;
       color: white;
       padding: 12px 20px;
       border-radius: 999px;
       font-weight: 600;
       box-shadow: 0 10px 25px rgba(0,0,0,.15);
       z-index: 9999;
     ">
  ✅ Saved successfully
</div>

<script>
  setTimeout(() => {
    const toast = document.getElementById("toast");
    if (toast) toast.remove();
  }, 2500);
</script>
{% endif %}

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
body { font-family: system-ui; background:#f6f7f9; padding:16px;padding-bottom: calc(120px + env(safe-area-inset-bottom)); /* 👈 ADD THIS */ }
.container { max-width:1100px; margin:auto; background:#fff; padding:20px; border-radius:14px; }
@media (max-width: 767px) {
  .matrix {
    grid-template-columns: 1fr;
  }
}

.quad { border:1px solid #e5e7eb; border-radius:12px; padding:12px; }
.quad > div {
  margin-top: 8px;
}
.matrix {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

summary {
  font-weight: 600;
  font-size: 16px;
  cursor: pointer;
  list-style: none;
}

summary::-webkit-details-marker {
  display: none;
}

.floating-bar {
  position: fixed;
  bottom: env(safe-area-inset-bottom, 0);
  left: 0;
  right: 0;
  background: #ffffff;
  border-top: 1px solid #e5e7eb;
  padding: 10px;
  display: flex;
  gap: 10px;
  z-index: 999;
}

.floating-bar button {
  flex: 1;
  padding: 14px;
  font-size: 16px;
  font-weight: 600;
  border-radius: 10px;
  border: none;
}

.floating-bar .save {
  background: #2563eb;
  color: white;
}

.floating-bar .cancel {
  background: #e5e7eb;
}
/* ===== Google Tasks–style Eisenhower ===== */

.task {
  padding: 10px 0;
}

.task + .task {
  border-top: 1px solid #eee;
}

/* Main row */
.task-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* Index */
.task-index {
  color: #9ca3af;
  font-size: 14px;
}

/* Checkbox */
.task-main input[type="checkbox"] {
  width: 18px;
  height: 18px;
}

/* Task text */
.task-main input[type="text"] {
  flex: 1;
  border: none;
  font-size: 16px;
  background: transparent;
  padding: 4px 0;
}

.task-main input[type="text"]:focus {
  outline: none;
  border-bottom: 2px solid #2563eb;
}

.task-delete {
  background: none;
  border: none;
  font-size: 20px;
  color: #dc2626;          /* 👈 visible red */
  cursor: pointer;
  padding: 8px;           /* 👈 touch target */
  border-radius: 8px;
  opacity: 0.85;
}

.task-delete:hover,
.task-delete:active {
  background: rgba(220, 38, 38, 0.12);
  opacity: 1;
}


/* Meta row */
.task-meta input {
  border: 1px solid #e5e7eb;
  background: #f9fafb;
  border-radius: 6px;
  padding: 2px 6px;
  font-size: 12px;
}

.task-meta {
  margin-left: 34px;
  margin-top: 6px;
  display: flex;
  gap: 10px;
}


/* Completed task */
.task.done {
  opacity: 0.6;
}

.task.done input[type="text"] {
  text-decoration: line-through;
}
@media (max-width: 767px) {
  .task-main input[type="checkbox"] {
    transform: scale(1.25);
  }

  .task-delete {
    font-size: 20px;
  }
}
/* ===== Motivational Quote ===== */

.motivation {
  position: relative;   /* 👈 REQUIRED */
  margin: 20px 0 36px;
  padding: 16px 18px;
  border-radius: 14px;
  background: linear-gradient(135deg, #f8fafc, #eef2ff);
  border-left: 4px solid #6366f1;
  display: flex;
  gap: 14px;
}


.motivation-icon {
  font-size: 22px;
  line-height: 1;
}

.motivation-text {
  font-size: 17px;
  font-style: italic;
  font-weight: 500;     /* 👈 semi-bold, tasteful */
  line-height: 1.6;
  color: #1f2937;
  max-width: 640px;
}
.motivation::before {
  content: "Reflection";
  position: absolute;
  top: -12px;
  left: 16px;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6366f1;
  font-weight: 600;
  background: #fff;
  padding: 0 6px;
}

.motivation {
  animation: quoteFade 0.4s ease-out;
}

@keyframes quoteFade {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
/* Mobile tuning */
@media (max-width: 767px) {
  .motivation {
    padding: 12px 14px;
    font-size: 13px;
  }
}

</style>
</head>

<body>
<div class="container">
<a href="/">⬅ Back to Daily Planner</a>
<div class="page-header">
  <h2>📋 Eisenhower Matrix – {{ plan_date }}</h2>
  <button type="submit"
          formaction="/todo/copy-prev"
          style="margin:16px 0;">
    📥 Copy open tasks from previous day
  </button>
</div>

<form method="get" style="margin:12px 0;">
  <input type="hidden" name="day" value="{{ plan_date.day }}">

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
<div class="floating-bar">
  <button type="submit"
          form="todo-form"
          class="save">
    💾 Save
  </button>

  <button type="button"
          class="cancel"
          onclick="window.location.reload()">
    ❌ Cancel
  </button>
</div>

<div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px;">
{% for d in days %}
  <a href="/todo?year={{year}}&month={{month}}&day={{d.day}}"
     style="
       width:36px;height:36px;
       display:flex;align-items:center;justify-content:center;
       border-radius:50%;
       text-decoration:none;
       border:1px solid #ddd;
       color:#000;
       {% if d.day == plan_date.day %}
         background:#2563eb;color:#fff;
       {% endif %}
     ">
    {{ d.day }}
  </a>
{% endfor %}
</div>
{% if quote %}
<div class="motivation">
  <span class="motivation-icon">{{ quote.icon }}</span>
  <span class="motivation-text">{{ quote.text }}</span>
</div>
{% endif %}
<form method="post" id="todo-form">

  <!-- ============================= -->
  <!-- MATRIX CONTAINER (GRID)       -->
  <!-- ============================= -->
  <div class="matrix">

    <!-- Hidden inputs: belong to the form -->
    <input type="hidden" name="year" value="{{ year }}">
    <input type="hidden" name="month" value="{{ month }}">
    <input type="hidden" name="day" value="{{ plan_date.day }}">

    <!-- ================================= -->
    <!-- START: QUADRANT LOOP (4 times)   -->
    <!-- ================================= -->
    {% for q, label in [
      ('do','🔥 Do Now'),
      ('schedule','📅 Schedule'),
      ('delegate','🤝 Delegate'),
      ('eliminate','🗑 Eliminate')
    ] %}

      <!-- ONE QUADRANT -->
      <details class="quad" open>

        <!-- Quadrant title -->
        <summary>{{ label }}</summary>

        <!-- Tasks container for this quadrant -->
        <div id="{{ q }}">

          <!-- START: TASK LOOP (N times) -->
          {% for t in todo[q] %}
         
           <div class="task {% if t.done %}done{% endif %}">
            <input type="hidden" name="{{ q }}_id[]" value="{{ t.id }}">
            <!-- LINE 1: serial + checkbox + text + delete -->
            <div class="task-main">
              <span class="task-index">{{ loop.index }}.</span>
              <input type="hidden"
                    name="{{q}}_done_state[{{ t.id }}]"
                    value="0">

              <input type="checkbox"
                    name="{{q}}_done_state[{{ t.id }}]"
                    value="1"
                    {% if t.done %}checked{% endif %} onchange="toggleDone(this)">


           <textarea name="{{q}}[]"
            class="task-text"
            rows="1"
            placeholder="Add a task"
            oninput="autoGrow(this)">{{ t.text }}</textarea>



              <button type="button"
                  class="task-delete"
                  title="Delete"
                  onclick="this.closest('.task').remove()">🗑</button>

            </div>

            <!-- LINE 2: date + time -->
              <div class="task-meta">
                <input type="date"
                      name="{{q}}_date[]"
                      value="{{ t.task_date or '' }}">

                <input type="time"
                      name="{{q}}_time[]"
                      value="{{ t.task_time or '' }}">
              </div>

          </div>

          {% endfor %}
          <!-- END: TASK LOOP -->

        </div>

        <!-- Add button belongs to THIS quadrant -->
        <button type="button" onclick="addTask('{{ q }}')">
          + Add
        </button>

      </details>
      <!-- END ONE QUADRANT -->

      <br>

    {% endfor %}
    <!-- ================================= -->
    <!-- END: QUADRANT LOOP                -->
    <!-- ================================= -->

  </div>
  <!-- END MATRIX -->

  <!-- ================================= -->
  <!-- ACTION BUTTONS (ONCE ONLY)        -->
  <!-- ================================= -->



</form>

</div>


<script>
function addTask(q){
  const div = document.getElementById(q);
  const row = document.createElement("div");
  row.className = "task";

  const id = "new_" + Date.now();

  row.innerHTML = `
    <div class="task-main">
      <span class="task-index">*</span>

      <input type="hidden" name="${q}_id[]" value="${id}">

      <input type="hidden" name="${q}_done_state[${id}]" value="0">
      <input type="checkbox" name="${q}_done_state[${id}]" value="1" onchange="toggleDone(this)">

      <input type="text" name="${q}[]" autofocus>

      <button type="button"
              class="task-delete"
              onclick="this.closest('.task').remove()">🗑</button>
    </div>

    <div class="task-meta">
      <input type="date" name="${q}_date[]">
      <input type="time" name="${q}_time[]">
    </div>
  `;

  div.appendChild(row);
}
let autoSaveTimer = null;

function toggleDone(checkbox) {
  const task = checkbox.closest(".task");
  if (!task) return;

  // UI update (already correct)
  if (checkbox.checked) {
    task.classList.add("done");
  } else {
    task.classList.remove("done");
  }

  // Debounced auto-save (prevents rapid submits)
  if (autoSaveTimer) {
    clearTimeout(autoSaveTimer);
  }

 autoSaveTimer = setTimeout(() => {
  const form = document.getElementById("todo-form");
  if (form) {
    form.submit(); // IMPORTANT: use submit(), not requestSubmit()
  }
}, 500);

}

</script>
{% if request.args.get('saved') %}
<div id="toast"
     style="
       position: fixed;
       bottom: 90px;
       left: 50%;
       transform: translateX(-50%);
       background: #2563eb;
       color: white;
       padding: 12px 20px;
       border-radius: 999px;
       font-weight: 600;
       box-shadow: 0 10px 25px rgba(0,0,0,.15);
       z-index: 9999;
     ">
  ✅ Saved successfully
</div>

<script>
  setTimeout(() => {
    const toast = document.getElementById("toast");
    if (toast) toast.remove();
  }, 2500);
</script>
{% endif %}

</body>
</html>
"""

# ==========================================================
# ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    logger.info("Starting Daily Planner – stable + Eisenhower")
    app.run(debug=True)