from flask import Flask, request, redirect, url_for, render_template_string
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar
import json

from supabase_client import get, post, delete
from logger import setup_logger

IST = ZoneInfo("Asia/Kolkata")

app = Flask(__name__)
logger = setup_logger()

TOTAL_SLOTS = 48
META_SLOT = 0

# ===============================
# HELPERS
# ===============================
def slot_label(slot):
    start = datetime.min + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return f"{start.strftime('%I:%M %p')} – {end.strftime('%I:%M %p')}"

def current_slot():
    now = datetime.now(IST)
    return (now.hour * 60 + now.minute) // 30 + 1

# ===============================
# DAILY PLANNER DATA
# ===============================
def load_day(plan_date):
    plans = {i: "" for i in range(1, TOTAL_SLOTS + 1)}
    rows = get("daily_slots", params={
        "plan_date": f"eq.{plan_date}",
        "select": "slot,plan"
    }) or []

    for r in rows:
        if r["slot"] != META_SLOT:
            plans[r["slot"]] = r.get("plan") or ""

    return plans

def save_day(plan_date, form):
    payload = []
    for slot in range(1, TOTAL_SLOTS + 1):
        text = form.get(f"plan_{slot}", "").strip()
        if text:
            payload.append({
                "plan_date": str(plan_date),
                "slot": slot,
                "plan": text
            })

    if payload:
        post("daily_slots?on_conflict=plan_date,slot", payload, prefer="resolution=merge-duplicates")

# ===============================
# TODO (EISENHOWER MATRIX)
# ===============================
def load_todo(plan_date):
    rows = get("todo_matrix", params={
        "plan_date": f"eq.{plan_date}"
    }) or []

    data = {"do": [], "schedule": [], "delegate": [], "eliminate": []}
    for r in rows:
        data[r["quadrant"]].append(r["task_text"])
    return data

def save_todo(plan_date, form):
    delete("todo_matrix", params={"plan_date": f"eq.{plan_date}"})

    payload = []
    for q in ["do", "schedule", "delegate", "eliminate"]:
        for line in form.get(q, "").splitlines():
            line = line.strip()
            if line:
                payload.append({
                    "plan_date": str(plan_date),
                    "quadrant": q,
                    "task_text": line
                })
    if payload:
        post("todo_matrix", payload)

# ===============================
# ROUTES
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
        return redirect(url_for("planner", year=year, month=month, day=day))

    plans = load_day(plan_date)
    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]

    return render_template_string(
        PLANNER_TEMPLATE,
        plans=plans,
        days=days,
        year=year,
        month=month,
        selected_day=day,
        now_slot=current_slot() if plan_date == today else None,
        slot_labels={i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)}
    )

@app.route("/todo", methods=["GET", "POST"])
def todo():
    today = datetime.now(IST).date()
    plan_date = today

    if request.method == "POST":
        save_todo(plan_date, request.form)
        return redirect(url_for("todo"))

    todo = load_todo(plan_date)
    return render_template_string(TODO_TEMPLATE, todo=todo, plan_date=plan_date)

# ===============================
# TEMPLATES
# ===============================
PLANNER_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family:system-ui; background:#f6f7f9; padding:12px; padding-bottom:160px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:20px; border-radius:14px; }
.day-strip { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
.day-btn { width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; border:1px solid #ddd; text-decoration:none; }
.day-btn.selected { background:#2563eb; color:#fff; }
.current-slot { background:#eef2ff; border-left:4px solid #2563eb; padding-left:8px; }
textarea { width:100%; min-height:80px; font-size:16px; }
.floating { position:fixed; bottom:0; left:0; right:0; background:#fff; border-top:1px solid #ddd; display:flex; gap:10px; padding:10px; }
.floating button { flex:1; padding:14px; font-size:16px; }
</style>
</head>
<body>

<div class="container">
<a href="/todo">📋 To-Do Matrix</a>

<div class="day-strip">
{% for d in days %}
<a href="/?year={{year}}&month={{month}}&day={{d.day}}" class="day-btn {% if d.day==selected_day %}selected{% endif %}">
{{d.day}}
</a>
{% endfor %}
</div>

<form method="post" id="planner-form" onsubmit="preserveFocus()">
{% for slot in range(1,49) %}
<div class="{% if now_slot==slot %}current-slot{% endif %}">
<b>{{slot_labels[slot]}}</b>
<textarea name="plan_{{slot}}">{{plans[slot]}}</textarea>
</div>
{% endfor %}
</form>
</div>

<div class="floating">
<button type="submit" form="planner-form">Save</button>
<button type="button" onclick="cancelEdit()">Cancel</button>
</div>

<script>
function preserveFocus(){
  const el=document.activeElement;
  if(el?.name){
    sessionStorage.setItem("focus", el.name);
    sessionStorage.setItem("pos", el.selectionStart);
    sessionStorage.setItem("scroll", window.scrollY);
  }
}
function cancelEdit(){
  preserveFocus();
  location.reload();
}
window.onload=()=>{
  const name=sessionStorage.getItem("focus");
  if(name){
    const el=document.querySelector(`[name='${name}']`);
    if(el){
      el.focus();
      el.setSelectionRange(sessionStorage.getItem("pos"),sessionStorage.getItem("pos"));
      window.scrollTo(0,sessionStorage.getItem("scroll"));
    }
    sessionStorage.clear();
    return;
  }
  const cur=document.querySelector(".current-slot textarea");
  if(cur){cur.scrollIntoView({block:"center"});cur.focus();}
}
</script>

</body>
</html>
"""

TODO_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:system-ui;background:#f6f7f9;padding:20px;}
.container{max-width:1100px;margin:auto;background:#fff;padding:20px;border-radius:14px;}
.matrix{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
.quad{border:1px solid #e5e7eb;border-radius:12px;padding:14px;}
textarea{width:100%;min-height:140px;font-size:15px;}
@media(max-width:768px){.matrix{grid-template-columns:1fr}}
</style>
</head>
<body>

<div class="container">
<h2>Eisenhower Matrix – {{plan_date}}</h2>
<a href="/">⬅ Daily Planner</a>

<form method="post">
<div class="matrix">
<div class="quad"><h3>🔥 Do</h3><textarea name="do">{{todo.do|join("\\n")}}</textarea></div>
<div class="quad"><h3>📅 Schedule</h3><textarea name="schedule">{{todo.schedule|join("\\n")}}</textarea></div>
<div class="quad"><h3>🤝 Delegate</h3><textarea name="delegate">{{todo.delegate|join("\\n")}}</textarea></div>
<div class="quad"><h3>🗑 Eliminate</h3><textarea name="eliminate">{{todo.eliminate|join("\\n")}}</textarea></div>
</div>
<button style="margin-top:16px;padding:14px;width:100%;">Save</button>
</form>
</div>

</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True)
