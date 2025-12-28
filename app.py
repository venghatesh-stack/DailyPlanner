from flask import Flask, request, redirect, url_for, render_template_string
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

# ===============================
# HELPERS
# ===============================
def slot_label(slot: int) -> str:
    start = datetime.min + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return f"{start.strftime('%I:%M %p')} – {end.strftime('%I:%M %p')}"

def current_slot() -> int:
    now = datetime.now(IST)
    return (now.hour * 60 + now.minute) // 30 + 1

# ===============================
# DATA ACCESS
# ===============================
def load_day(plan_date):
    plans = {i: {"plan": "", "status": DEFAULT_STATUS} for i in range(1, TOTAL_SLOTS + 1)}
    reflection = ""
    habits = set()

    rows = get(
        "daily_slots",
        params={"plan_date": f"eq.{plan_date}", "select": "slot,plan,status"}
    )

    for r in rows:
        plans[r["slot"]] = {
            "plan": r.get("plan") or "",
            "status": r.get("status") or DEFAULT_STATUS
        }

    summary = get(
        "daily_summary",
        params={"plan_date": f"eq.{plan_date}", "select": "reflection,habits"}
    )

    if summary:
        reflection = summary[0].get("reflection") or ""
        if summary[0].get("habits"):
            habits = set(summary[0]["habits"].split(","))

    return plans, reflection, habits

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

    if payload:
        post(
            "daily_slots?on_conflict=plan_date,slot",
            payload,
            prefer="resolution=merge-duplicates"
        )

    post(
        "daily_summary?on_conflict=plan_date",
        {
            "plan_date": str(plan_date),
            "reflection": form.get("reflection", "").strip(),
            "habits": ",".join(form.getlist("habits"))
        },
        prefer="resolution=merge-duplicates"
    )

# ===============================
# ROUTE
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
            year=year,
            month=month,
            day=plan_date.day,
            saved=1
        ))

    plans, reflection, habits = load_day(plan_date)
    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]

    return render_template_string(
        TEMPLATE,
        year=year,
        month=month,
        month_name=calendar.month_name[month],
        days=days,
        selected_day=plan_date.day,
        today=today,
        plans=plans,
        reflection=reflection,
        habits=habits,
        habit_list=HABIT_LIST,
        statuses=STATUSES,
        total_slots=TOTAL_SLOTS,
        slot_labels={i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)},
        now_slot=current_slot() if plan_date == today else None,
        saved=request.args.get("saved")
    )

# ===============================
# TEMPLATE
# ===============================
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {
  --bg:#f6f7f9; --card:#fff; --border:#e5e7eb; --primary:#2563eb;
}
body { background:var(--bg); font-family:system-ui; padding:20px; }
.container { max-width:1100px; margin:auto; background:var(--card); padding:24px; border-radius:14px; }

.header-bar {
  display:flex; justify-content:space-between; align-items:center;
  margin-bottom:16px; padding-bottom:10px; border-bottom:1px solid var(--border);
}
.header-date { font-weight:600; }
.header-time { display:flex; align-items:center; gap:6px; font-weight:700; color:var(--primary); }
.clock-icon { font-size:18px; }
.tz { font-size:11px; opacity:.8; }

.day-strip { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:20px; }
.day-btn {
  width:36px; height:36px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  border:1px solid var(--border); background:#f9fafb;
  text-decoration:none; font-weight:600; color:#111;
}
.day-btn.selected { background:var(--primary); color:#fff; }

table { width:100%; border-collapse:collapse; }
td { padding:8px; vertical-align:top; }

.current-slot {
  background:#eef2ff;
  border-left:4px solid var(--primary);
}

.plan-input {
  width:100%; min-height:44px; padding:10px 12px;
  border-radius:10px; border:1px solid var(--border);
  background:#f9fafb;
}

.status-select {
  width:100%; padding:8px 12px; border-radius:999px;
  border:1px solid var(--border); font-weight:600;
}

.status-nothing-planned { background:#e5e7eb; color:#374151; }
.status-yet-to-start { background:#fed7aa; color:#9a3412; }
.status-in-progress { background:#dbeafe; color:#1e40af; }
.status-closed { background:#dcfce7; color:#166534; }
.status-deferred { background:#fee2e2; color:#991b1b; }

.habits-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:10px; }

.floating-actions {
  position:fixed; bottom:16px; left:50%; transform:translateX(-50%);
  background:#fff; border:1px solid var(--border);
  padding:10px 14px; border-radius:12px; display:flex; gap:10px;
}
.hidden { display:none; }

@media(max-width:768px){
  table, tr, td { display:block; width:100%; }
}
</style>
</head>

<body>
<div class="container">

<div class="header-bar">
  <div class="header-date" id="current-date"></div>
  <div class="header-time">
    <span class="clock-icon">🕒</span>
    <span id="current-time"></span>
    <span class="tz">IST</span>
  </div>
</div>

{% if saved %}
<div style="background:#dcfce7;padding:10px;border-radius:8px;margin-bottom:12px;font-weight:600">
✅ Saved successfully
</div>
{% endif %}

<div class="day-strip">
{% for d in days %}
<a href="/?year={{year}}&month={{month}}&day={{d.day}}"
   class="day-btn {% if d.day==selected_day %}selected{% endif %}">
{{ d.day }}
</a>
{% endfor %}
</div>

<form method="post">
<table>
{% for slot in range(1,total_slots+1) %}
<tr id="slot-{{slot}}" class="{% if now_slot==slot %}current-slot{% endif %}">
<td>{{ slot_labels[slot] }}</td>
<td><textarea class="plan-input" name="plan_{{slot}}" oninput="markDirty()">{{ plans[slot]['plan'] }}</textarea></td>
<td>
<select name="status_{{slot}}" class="status-select"
        onchange="updateStatusColor(this); markDirty()">
{% for s in statuses %}
<option value="{{s}}" {% if s==plans[slot]['status'] %}selected{% endif %}>{{s}}</option>
{% endfor %}
</select>
</td>
</tr>
{% endfor %}
</table>

<h3>Habits</h3>
<div class="habits-grid">
{% for h in habit_list %}
<label><input type="checkbox" name="habits" value="{{h}}" {% if h in habits %}checked{% endif %} onchange="markDirty()"> {{h}}</label>
{% endfor %}
</div>

<h3>Reflection</h3>
<textarea name="reflection" class="plan-input" oninput="markDirty()">{{ reflection }}</textarea>

<div id="floating-actions" class="floating-actions hidden">
<button type="submit">Save</button>
<button type="button" onclick="location.reload()">Cancel</button>
</div>
</form>
</div>

<script>
let dirty = false;

function markDirty(){
  if(!dirty){
    dirty = true;
    document.getElementById("floating-actions").classList.remove("hidden");
  }
}

function updateISTClock(){
  const now = new Date();
  const utc = now.getTime() + now.getTimezoneOffset()*60000;
  const ist = new Date(utc + 330*60000);

  document.getElementById("current-time").textContent =
    ist.toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:true});

  document.getElementById("current-date").textContent =
    ist.toLocaleDateString("en-IN",{weekday:"long",day:"numeric",month:"long",year:"numeric"});
}
updateISTClock();
setInterval(updateISTClock,1000);

function updateStatusColor(el){
  el.className = "status-select";
  if(el.value==="Nothing Planned") el.classList.add("status-nothing-planned");
  if(el.value==="Yet to Start") el.classList.add("status-yet-to-start");
  if(el.value==="In Progress") el.classList.add("status-in-progress");
  if(el.value==="Closed") el.classList.add("status-closed");
  if(el.value==="Deferred") el.classList.add("status-deferred");
}

document.addEventListener("DOMContentLoaded",()=>{
  document.querySelectorAll(".status-select").forEach(updateStatusColor);
  const row = document.querySelector(".current-slot");
  if(row) setTimeout(()=>row.scrollIntoView({behavior:"smooth",block:"center"}),300);
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    logger.info("Starting Daily Planner (IST)")
    app.run(debug=True)
