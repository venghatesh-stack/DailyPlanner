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
STATUSES = [
    "Nothing Planned",
    "Yet to Start",
    "In Progress",
    "Closed",
    "Deferred",
]

DEFAULT_STATUS = "Yet to Start"

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
# DATA – DAILY PLANNER
# ===============================
def load_day(plan_date):
    plans = {
    i: {"text": "", "status": DEFAULT_STATUS}
    for i in range(1, TOTAL_SLOTS + 1)
    }

    rows = get(
    "daily_slots",
    params={"plan_date": f"eq.{plan_date}", "select": "slot,plan,status"},
  ) 


    for r in rows:
        if r["slot"] != META_SLOT:
            plans[r["slot"]] = {
             "text": r.get("plan") or "",
             "status": r.get("status") or DEFAULT_STATUS,
      }


    return plans

def save_day(plan_date, form):
    payload = []
    for slot in range(1, TOTAL_SLOTS + 1):
     text = form.get(f"plan_{slot}", "").strip()
     status = form.get(f"status_{slot}", DEFAULT_STATUS)

    if text:
      payload.append({
        "plan_date": str(plan_date),
        "slot": slot,
        "plan": text,
        "status": status,
    })


    if payload:
        post(
            "daily_slots?on_conflict=plan_date,slot",
            payload,
            prefer="resolution=merge-duplicates",
        )

# ===============================
# DATA – TODO MATRIX
# ===============================
def load_todo(plan_date):
    rows = get("todo_matrix", params={"plan_date": f"eq.{plan_date}"}) or []
    data = {"do": [], "schedule": [], "delegate": [], "eliminate": []}
    for r in rows:
        data[r["quadrant"]].append(r["task_text"])
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
                    "task_text": line.strip(),
                })
    if payload:
        post("todo_matrix", payload)
# ===============================
# DATA – HABITS & REFLECTION
# ===============================
HABITS = [
    "Walking",
    "Water",
    "No Shopping",
    "No TimeWastage",
    "8 hrs sleep",
    "Daily prayers",
]

def load_habits(plan_date):
    rows = get(
        "daily_habits",
        params={"plan_date": f"eq.{plan_date}"}
    ) or []
    return {r["habit"]: r["done"] for r in rows}
def save_habits(plan_date, form):
    payload = []
    for h in HABITS:
        payload.append({
            "plan_date": str(plan_date),
            "habit": h,
            "done": form.get(f"habit_{h}") == "on"
        })

    if payload:
        post(
            "daily_habits?on_conflict=plan_date,habit",
            payload,
            prefer="resolution=merge-duplicates"
        )


def load_reflection(plan_date):
    rows = get(
        "daily_reflection",
        params={"plan_date": f"eq.{plan_date}", "select": "reflection"}
    ) or []
    return rows[0]["reflection"] if rows else ""

def save_reflection(plan_date, form):
    text = form.get("reflection", "").strip()
    if not text:
        return

    post(
        "daily_reflection?on_conflict=plan_date",
        [{
            "plan_date": str(plan_date),
            "reflection": text
        }],
        prefer="resolution=merge-duplicates"
    )

# ===============================
# ROUTES
# ===============================
@app.route("/", methods=["GET", "POST"])
def planner():
    today = datetime.now(IST).date()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    day = int(request.args.get("day", today.day))
    last_day = calendar.monthrange(year, month)[1]
    day = min(day, last_day)
    plan_date = date(year, month, day)


    if request.method == "POST":
      save_day(plan_date, request.form)
      save_habits(plan_date, request.form)
      save_reflection(plan_date, request.form)
      return redirect(url_for("planner", year=year, month=month, day=day,saved="1"))


    return render_template_string(
        TEMPLATE,
        plans=load_day(plan_date),
        days=[date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)],
        year=year,
        month=month,
        selected_day=day,
        now_slot=current_slot() if plan_date == today else None,
        slot_labels={i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)},
        calendar=calendar,
        habits=load_habits(plan_date),
        habit_list=HABITS,
        reflection=load_reflection(plan_date),

    )

@app.route("/todo", methods=["GET", "POST"])
def todo():
    plan_date = datetime.now(IST).date()
    if request.method == "POST":
        save_todo(plan_date, request.form)
        return redirect(url_for("todo"))
    return render_template_string(TODO_TEMPLATE, todo=load_todo(plan_date), plan_date=plan_date)

# ===============================
# TEMPLATE – DAILY PLANNER
# ===============================
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family:system-ui; background:#f6f7f9; padding:12px; padding-bottom:140px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:16px; border-radius:14px; }

.header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
.header-time { font-weight:700; color:#2563eb; }

.day-strip { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
.day-btn {
  width:36px; height:36px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  border:1px solid #ddd; text-decoration:none; color:#000;
}
.day-btn.selected { background:#2563eb; color:#fff; }

.slot { margin-bottom:12px; }
.current-slot { background:#eef2ff; border-left:4px solid #2563eb; padding-left:8px; }

textarea { width:100%; min-height:90px; font-size:16px; }

.floating-bar {
  position:fixed;
  bottom:env(safe-area-inset-bottom);
  left:0; right:0;
  background:#fff;
  border-top:1px solid #ddd;
  display:flex;
  gap:10px;
  padding:10px;
  z-index:9999;
}
.floating-bar button { flex:1; padding:14px; font-size:16px; }

.time-filter { display:flex; gap:20px; margin-bottom:12px; }
.time-wheel select { height:120px; width:90px; font-size:16px; }
</style>
</head>

<body>
{% if request.args.get("saved") %}
<div id="toast"
     style="position:fixed;
            top:16px;
            left:50%;
            transform:translateX(-50%);
            background:#16a34a;
            color:white;
            padding:12px 18px;
            border-radius:10px;
            font-weight:600;
            z-index:10000;">
  ✅ Data saved successfully
</div>
<script>
  setTimeout(()=>{
    const t=document.getElementById("toast");
    if(t) t.remove();
  },2000);
</script>
{% endif %}

<div class="container">

<div class="header">
  <a href="/todo" style="font-weight:600;color:#2563eb;text-decoration:none;">📋 To-Do Matrix</a>
  <div class="header-time">🕒 <span id="current-time"></span> IST</div>
</div>

<form method="get" style="display:flex;gap:8px;margin-bottom:12px;">
  <input type="hidden" name="day" value="{{selected_day}}">
  <select name="month" onchange="this.form.submit()">
    {% for m in range(1,13) %}
      <option value="{{m}}" {% if m==month %}selected{% endif %}>
        {{calendar.month_name[m]}}
      </option>
    {% endfor %}
  </select>

  <select name="year" onchange="this.form.submit()">
    {% for y in range(year-5, year+6) %}
      <option value="{{y}}" {% if y==year %}selected{% endif %}>
        {{y}}
      </option>
    {% endfor %}
  </select>
</form>



<div class="time-filter">
  <div class="time-wheel">
    <label>From</label><br>
    <select id="timeFrom">
      {% for h in range(0,24) %}{% for m in (0,30) %}
        {% set t="%02d:%02d"|format(h,m) %}
        <option value="{{t}}" {% if t=="06:00" %}selected{% endif %}>{{t}}</option>
      {% endfor %}{% endfor %}
    </select>
  </div>

  <div class="time-wheel">
    <label>To</label><br>
    <select id="timeTo">
      {% for h in range(0,24) %}{% for m in (0,30) %}
        {% set t="%02d:%02d"|format(h,m) %}
        <option value="{{t}}" {% if t=="18:00" %}selected{% endif %}>{{t}}</option>
      {% endfor %}{% endfor %}
    </select>
  </div>
</div>
<div class="day-strip">
{% for d in days %}
<a href="/?year={{year}}&month={{month}}&day={{d.day}}"
   class="day-btn {% if d.day==selected_day %}selected{% endif %}">
   {{d.day}}
</a>
{% endfor %}
</div>


<form method="post" id="planner-form">
{% for slot in range(1,49) %}
<div class="slot {% if now_slot==slot %}current-slot{% endif %}" data-slot="{{slot}}">
  <b>{{slot_labels[slot]}}</b>
  <textarea name="plan_{{slot}}">{{plans[slot].text}}</textarea>
</div>
{% endfor %}
<hr style="margin:24px 0;">

<h3>✅ Habits</h3>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
  {% for h in habit_list %}
  <label style="display:flex;align-items:center;gap:8px;">
    <input type="checkbox" name="habit_{{h}}" {% if habits.get(h) %}checked{% endif %}>
    {{h}}
  </label>
  {% endfor %}
</div>

<hr style="margin:24px 0;">

<h3>📝 Reflection of the Day</h3>
<textarea name="reflection" style="min-height:120px;">{{reflection}}</textarea>

</form>
</div>

<div class="floating-bar">
  <button type="submit" form="planner-form">Save</button>
  <button type="button" onclick="window.history.back()">Cancel</button>
</div>

<script>
// CLOCK
function updateClock(){
  const ist=new Date(new Date().toLocaleString("en-US",{timeZone:"Asia/Kolkata"}));
  document.getElementById("current-time").textContent=ist.toLocaleTimeString();
}
setInterval(updateClock,1000);updateClock();

// TIME FILTER
function mins(t){const[x,y]=t.split(":").map(Number);return x*60+y;}
function applyFilter(){
  const f=mins(timeFrom.value), t=mins(timeTo.value);
  document.querySelectorAll("[data-slot]").forEach(el=>{
    const s=(el.dataset.slot-1)*30;
    el.style.display=(s>=f && s<t)?"":"none";
  });
}
timeFrom.onchange=timeTo.onchange=applyFilter;
applyFilter();

// FOCUS PERSISTENCE
let lastFocus=null;
document.addEventListener("focusin",e=>{
  if(e.target.tagName==="TEXTAREA"){
    lastFocus={name:e.target.name,pos:e.target.selectionStart,scroll:window.scrollY};
    sessionStorage.setItem("focus",JSON.stringify(lastFocus));
  }
});
window.addEventListener("load",()=>{
  const saved=sessionStorage.getItem("focus");
  if(saved){
    const f=JSON.parse(saved);
    const el=document.querySelector(`[name='${f.name}']`);
    if(el){
      el.focus();
      el.setSelectionRange(f.pos,f.pos);
      window.scrollTo(0,f.scroll);
      return;
    }
  }
  const cur=document.querySelector(".current-slot textarea");
  if(cur){cur.focus();cur.scrollIntoView({block:"center"});}
});
</script>
</body>
</html>
"""

# ===============================
# TEMPLATE – TODO (ISOLATED)
# ===============================
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
    logger.info("Starting Daily Planner (stable)")
    app.run(debug=True)