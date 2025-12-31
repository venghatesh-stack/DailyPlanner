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

# ===============================
# DAILY PLANNER DATA
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

    post("daily_slots?on_conflict=plan_date,slot", payload, prefer="resolution=merge-duplicates")

# ===============================
# TODO MATRIX DATA
# ===============================
def load_todo(plan_date):
    rows = get(
        "todo_matrix",
        params={"plan_date": f"eq.{plan_date}", "select": "quadrant,task_text"}
    ) or []

    data = {"do": "", "schedule": "", "delegate": "", "eliminate": ""}
    for r in rows:
        data[r["quadrant"]] += r["task_text"] + "\n"

    return data

def save_todo(plan_date, form):
    delete("todo_matrix", params={"plan_date": f"eq.{plan_date}"})

    payload = []
    for q in ["do", "schedule", "delegate", "eliminate"]:
        for line in form.get(q, "").splitlines():
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
    day = int(request.args.get("day", today.day))
    plan_date = date(year, month, day)

    if request.method == "POST":
        save_day(plan_date, request.form)
        return redirect(url_for("plan_of_day", year=year, month=month, day=day))

    plans, habits, reflection = load_day(plan_date)

    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]

    return render_template_string(
        PLANNER_TEMPLATE,
        plans=plans,
        days=days,
        selected_day=day,
        today=today,
        year=year,
        month=month,
        now_slot=current_slot() if plan_date == today else None,
        slot_labels={i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)},
        habit_list=HABIT_LIST,
        habit_icons=HABIT_ICONS,
        habits=habits,
        reflection=reflection,
        calendar=calendar
    )

@app.route("/todo", methods=["GET", "POST"])
def todo_page():
    plan_date = datetime.now(IST).date()

    if request.method == "POST":
        save_todo(plan_date, request.form)
        return redirect(url_for("todo_page"))

    todo = load_todo(plan_date)

    return render_template_string(TODO_TEMPLATE, todo=todo, plan_date=plan_date)

# ===============================
# PLANNER TEMPLATE
# ===============================
PLANNER_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:system-ui;background:#f6f7f9;padding:12px;padding-bottom:200px}
.container{max-width:1100px;margin:auto;background:#fff;padding:24px;border-radius:14px}
.current-slot{background:#eef2ff;border-left:4px solid #2563eb}
textarea{width:100%;min-height:80px;font-size:16px}
.day-strip{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.day-btn{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;border:1px solid #ddd;text-decoration:none;color:#000}
.day-btn.selected{background:#2563eb;color:#fff}
.floating-bar{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid #ddd;display:flex;gap:10px;padding:10px}
.floating-bar button{flex:1;padding:14px;font-size:16px}
</style>
</head>

<body>
<div class="container">
<a href="/todo">📋 To-Do Matrix</a>

<div class="day-strip">
{% for d in days %}
<a href="/?year={{year}}&month={{month}}&day={{d.day}}" class="day-btn {% if d.day==selected_day %}selected{% endif %}">{{d.day}}</a>
{% endfor %}
</div>

<form method="post" id="planner-form">
{% for slot in range(1,49) %}
<div class="{% if now_slot==slot %}current-slot{% endif %}">
<b>{{slot_labels[slot]}}</b>
<textarea name="plan_{{slot}}">{{plans[slot]["plan"]}}</textarea>
</div>
{% endfor %}
</form>
</div>

<div class="floating-bar">
<button type="submit" form="planner-form">Save</button>
<button type="button" onclick="location.reload()">Cancel</button>
</div>

<script>
// Focus only on initial load
window.addEventListener("load",()=>{
  const cur=document.querySelector(".current-slot textarea");
  if(cur){cur.focus();}
});
</script>
</body>
</html>
"""

# ===============================
# TODO TEMPLATE (FIXED)
# ===============================
TODO_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:system-ui;background:#f6f7f9;padding:16px}
.container{max-width:900px;margin:auto;background:#fff;padding:20px;border-radius:14px}
.matrix{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.box{border-radius:12px;padding:12px;border:1px solid #ddd}
textarea{width:100%;min-height:140px;font-size:15px}
.do{border-left:6px solid #22c55e}
.schedule{border-left:6px solid #3b82f6}
.delegate{border-left:6px solid #f59e0b}
.eliminate{border-left:6px solid #ef4444}
</style>
</head>

<body>
<div class="container">
<h2>Eisenhower Matrix – {{plan_date}}</h2>
<a href="/">⬅ Back to Planner</a>

<form method="post" onsubmit="preserveFocus()">
<div class="matrix">
<div class="box do"><h4>Do</h4><textarea name="do">{{todo.do}}</textarea></div>
<div class="box schedule"><h4>Schedule</h4><textarea name="schedule">{{todo.schedule}}</textarea></div>
<div class="box delegate"><h4>Delegate</h4><textarea name="delegate">{{todo.delegate}}</textarea></div>
<div class="box eliminate"><h4>Eliminate</h4><textarea name="eliminate">{{todo.eliminate}}</textarea></div>
</div>
<br>
<button type="submit">Save</button>
<button type="button" onclick="location.reload()">Cancel</button>
</form>
</div>

<script>
function preserveFocus(){
  const el=document.activeElement;
  if(el && el.name){
    sessionStorage.setItem("focus",el.name);
    sessionStorage.setItem("pos",el.selectionStart);
  }
}
window.addEventListener("load",()=>{
  const name=sessionStorage.getItem("focus");
  const pos=sessionStorage.getItem("pos");
  if(name){
    const el=document.querySelector(`[name='${name}']`);
    if(el){
      el.focus();
      el.setSelectionRange(pos,pos);
    }
    sessionStorage.clear();
  }
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    logger.info("Starting Daily Planner")
    app.run(debug=True)
