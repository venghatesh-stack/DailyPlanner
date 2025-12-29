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
    "Walking",
    "Water",
    "No Shopping",
    "No TimeWastage",
    "8 hrs sleep",
    "Daily prayers"
]
HABIT_ICONS = {
    "Walking": "🚶‍♂️",
    "Water": "💧",
    "No Shopping": "🛒🚫",
    "No TimeWastage": "⏳🚫",
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

    # Convert to UTC for Google Calendar
    start_utc = start_ist.astimezone(ZoneInfo("UTC"))
    end_utc = end_ist.astimezone(ZoneInfo("UTC"))

    start_str = start_utc.strftime("%Y%m%dT%H%M%SZ")
    end_str = end_utc.strftime("%Y%m%dT%H%M%SZ")

    params = {
        "action": "TEMPLATE",
        "text": task,
        "dates": f"{start_str}/{end_str}",
        "details": "Created from Daily Planner",
        "trp": "false"
    }

    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)

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
            year=plan_date.year,
            month=plan_date.month,
            day=plan_date.day,
            saved=1
        ))

    plans, reflection, habits = load_day(plan_date)

    reminder_links = {
        slot: google_calendar_link(plan_date, slot, plans[slot]["plan"])
        for slot in range(1, TOTAL_SLOTS + 1)
    }

    days = [
        date(year, month, d)
        for d in range(1, calendar.monthrange(year, month)[1] + 1)
    ]

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
        habit_icons=HABIT_ICONS,
        statuses=STATUSES,
        total_slots=TOTAL_SLOTS,
        slot_labels={i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)},
        reminder_links=reminder_links,
        now_slot=current_slot() if plan_date == today else None,
        saved=request.args.get("saved"),
        calendar=calendar
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
body { font-family: system-ui; background:#f6f7f9; padding:20px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:24px; border-radius:14px; }

.header-bar {
  display:flex; justify-content:space-between; align-items:center;
  margin-bottom:10px; padding-bottom:10px; border-bottom:1px solid #e5e7eb;
}
.header-date { font-weight:600; color:#374151; }
.header-time { font-weight:700; color:#2563eb; }

.month-controls {
  display:flex; gap:8px; margin-bottom:16px;
}
.month-controls select {
  padding:6px 10px;
}

.day-strip { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
.day-btn {
  width:36px; height:36px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  border:1px solid #ddd; text-decoration:none;
}
.day-btn.selected { background:#2563eb; color:#fff; }

.current-slot { background:#eef2ff; border-left:4px solid #2563eb; }

.task-header {
  display:flex; justify-content:space-between; align-items:center;
  font-size:12px; font-weight:600; color:#6b7280; margin-bottom:4px;
}

.reminder-icon { text-decoration:none; font-size:16px; opacity:.75; }
.reminder-icon:hover { opacity:1; }

.floating-actions {
  position:fixed; bottom:16px; left:50%; transform:translateX(-50%);
  background:#fff; border:1px solid #ddd; padding:10px;
  border-radius:12px; display:none; gap:10px;
}
/* ---------- Mobile-first layout ---------- */
@media (max-width: 768px) {

  table, tbody, tr, td {
    display: block;
    width: 100%;
  }

  tr {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 12px;
    margin-bottom: 14px;
  }

  tr.current-slot {
    border-left: 4px solid #2563eb;
    background: #eef2ff;
  }

  td {
    padding: 0;
    margin-bottom: 10px;
  }

  td:first-child {
    font-weight: 600;
    color: #374151;
    margin-bottom: 6px;
  }

  textarea {
    width: 100%;
    min-height: 64px;
    font-size: 16px; /* prevent iOS zoom */
  }

  select {
    width: 100%;
    font-size: 16px;
  }

  .task-header {
    margin-bottom: 6px;
  }
}

</style>
</head>

<body>
<div class="container">

<div class="header-bar">
  <div class="header-date" id="current-date"></div>
  <div class="header-time">🕒 <span id="current-time"></span> IST</div>
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
{% if saved %}
<div id="save-msg" style="
  background:#dcfce7;
  color:#166534;
  padding:10px 14px;
  border-radius:10px;
  margin-bottom:12px;
  font-weight:600;
">
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
<table width="100%">
{% for slot in range(1,total_slots+1) %}
<tr id="slot-{{slot}}" class="{% if now_slot==slot %}current-slot{% endif %}">
<td>🕒 {{ slot_labels[slot] }}</td>
<td>
  <div class="task-header">
    <span>📝 Task</span>
    <a href="{{ reminder_links[slot] }}" class="reminder-icon" title="Add Google reminder">⏰</a>
  </div>
  <textarea name="plan_{{slot}}" oninput="markDirty()" style="width:100%">{{ plans[slot]['plan'] }}</textarea>
</td>
<td>
  <select name="status_{{slot}}" onchange="markDirty()">
  {% for s in statuses %}
    <option {% if s==plans[slot]['status'] %}selected{% endif %}>{{s}}</option>
  {% endfor %}
  </select>
</td>
</tr>
{% endfor %}
</table>
<h3>✅ Habits</h3>
<div style="
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
  gap:12px;
  margin-bottom:20px;
">
{% for h in habit_list %}
  <label style="
    display:flex;
    align-items:center;
    gap:10px;
    padding:10px 12px;
    border:1px solid #e5e7eb;
    border-radius:10px;
    background:#f9fafb;
    font-weight:500;
  ">
    <input type="checkbox"
           name="habits"
           value="{{ h }}"
           {% if h in habits %}checked{% endif %}
           onchange="markDirty()">
    <span style="font-size:18px">{{ habit_icons[h] }}</span>
    <span>{{ h }}</span>
  </label>
{% endfor %}
</div>

<h3>🪞 Reflection</h3>
<textarea name="reflection" oninput="markDirty()" style="width:100%">{{ reflection }}</textarea>

<div id="actions" class="floating-actions">
<button type="submit">Save</button>
<button type="button" onclick="location.reload()">Cancel</button>
</div>
</form>
</div>

<script>
let dirty=false;
function markDirty(){
  if(!dirty){
    dirty=true;
    document.getElementById("actions").style.display="flex";
  }
const msg = document.getElementById("save-msg");
if (msg) {
  setTimeout(() => msg.style.display = "none", 3000);
}
}


function updateClock(){
  const now=new Date();
  const utc=now.getTime()+now.getTimezoneOffset()*60000;
  const ist=new Date(utc+330*60000);

  document.getElementById("current-time").textContent =
    ist.toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:true});

  document.getElementById("current-date").textContent =
    ist.toLocaleDateString("en-IN",{weekday:"long",day:"numeric",month:"long",year:"numeric"});
}
updateClock();
setInterval(updateClock,1000);

document.addEventListener("DOMContentLoaded",()=>{
  const row=document.querySelector(".current-slot");
  if(row) row.scrollIntoView({behavior:"smooth",block:"center"});
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    logger.info("Starting Daily Planner (IST)")
    app.run(debug=True)




