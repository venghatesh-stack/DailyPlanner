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
@@ -84,8 +66,6 @@
# ===============================
def load_day(plan_date):
    plans = {i: {"plan": "", "status": DEFAULT_STATUS} for i in range(1, TOTAL_SLOTS + 1)}
    reflection = ""
    habits = set()

    rows = get("daily_slots", params={
        "plan_date": f"eq.{plan_date}",
@@ -98,31 +78,23 @@
            "status": r.get("status") or DEFAULT_STATUS
        }

    summary = get("daily_summary", params={
        "plan_date": f"eq.{plan_date}",
        "select": "reflection,habits"
    })

    if summary:
        reflection = summary[0].get("reflection") or ""
        if summary[0].get("habits"):
            habits = set(h.strip() for h in summary[0]["habits"].split(",") if h.strip())

    return plans, reflection, habits
    return plans

def save_day(plan_date, form):
    payload = []

    for slot in range(1, TOTAL_SLOTS + 1):
        plan = form.get(f"plan_{slot}", "").strip()
        status = form.get(f"status_{slot}", DEFAULT_STATUS)

        if not plan:
            continue

        payload.append({
            "plan_date": str(plan_date),
            "slot": slot,
            "plan": plan,
            "status": form.get(f"status_{slot}", DEFAULT_STATUS)
            "status": status
        })

    if payload:
@@ -132,16 +104,6 @@
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
@@ -165,7 +127,7 @@
            saved=1
        ))

    plans, reflection, habits = load_day(plan_date)
    plans = load_day(plan_date)

    reminder_links = {
        slot: google_calendar_link(plan_date, slot, plans[slot]["plan"])
@@ -185,10 +147,6 @@
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
@@ -201,7 +159,8 @@
# ===============================
# TEMPLATE
# ===============================
TEMPLATE = """<!DOCTYPE html>
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
@@ -212,71 +171,109 @@
.header-bar { display:flex; justify-content:space-between; margin-bottom:12px; }
.header-time { font-weight:700; color:#2563eb; }

.focus-toggle { font-weight:600; color:#2563eb; cursor:pointer; margin-bottom:12px; }
.month-controls { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
.day-strip { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }

.current-slot { background:#eef2ff; border-left:4px solid #2563eb; }
.day-btn {
  width:36px; height:36px;
  border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  border:1px solid #ddd;
  text-decoration:none; color:#000;
}
.day-btn.selected { background:#2563eb; color:#fff; }

.hidden-slot { display:none !important; }
table { width:100%; border-collapse:collapse; }
td { padding:8px; border-bottom:1px solid #eee; }

.focus-now { outline:2px solid #22c55e; }
.focus-next { outline:2px dashed #60a5fa; }
.current-slot { background:#eef2ff; border-left:4px solid #2563eb; }

/* Status colors */
.status-nothing-planned { background:#f3f4f6; }
.status-yet-to-start { background:#fef3c7; }
.status-in-progress { background:#dbeafe; }
.status-closed { background:#dcfce7; }
.status-deferred { background:#fee2e2; }

.row-error { background:#fee2e2 !important; }
</style>
</head>

<body>

{% if saved %}
<div id="save-msg" style="position:fixed;bottom:80px;left:50%;transform:translateX(-50%);
background:#dcfce7;padding:10px 16px;border-radius:999px;font-weight:600;">
✅ Saved successfully
<div style="
  position:fixed; bottom:20px; left:50%;
  transform:translateX(-50%);
  background:#dcfce7;
  padding:10px 16px;
  border-radius:999px;
  font-weight:600;">
  ✅ Saved successfully
</div>
{% endif %}

<div id="task-error" style="display:none;position:fixed;bottom:80px;left:50%;
transform:translateX(-50%);background:#fee2e2;color:#991b1b;
padding:10px 16px;border-radius:999px;font-weight:600;">
❌ Tasks cannot be empty. Rows highlighted in red must be corrected.
</div>

<div class="container">

<div class="header-bar">
  <div id="current-date"></div>
  <div class="header-time">🕒 <span id="current-time"></span> IST</div>
</div>

<div id="focus-toggle" class="focus-toggle">
🎯 Focus mode ON — <u>Show full day</u>
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
{{ d.day }}
</a>
{% endfor %}
</div>

<form method="post">
<table width="100%">
<table>
{% for slot in range(1,total_slots+1) %}
<tr data-status="{{ plans[slot]['status'] }}" class="{% if now_slot==slot %}current-slot{% endif %}">
<td>{{ slot_labels[slot] }}</td>
<td><textarea name="plan_{{slot}}">{{ plans[slot]['plan'] }}</textarea></td>
<tr class="
  {% if now_slot==slot %}current-slot{% endif %}
  status-{{ plans[slot]['status'].lower().replace(' ','-') }}
">
<td>
<select name="status_{{slot}}">
{% for s in statuses %}
<option {% if s==plans[slot]['status'] %}selected{% endif %}>{{s}}</option>
{% endfor %}
</select>
  {{ slot_labels[slot] }}
  {% if plans[slot]['plan'] %}
    <a href="{{ reminder_links[slot] }}" target="_blank">⏰</a>
  {% endif %}
</td>
<td>
  <textarea name="plan_{{slot}}" style="width:100%">{{ plans[slot]['plan'] }}</textarea>
</td>
<td>
  <select name="status_{{slot}}">
  {% for s in statuses %}
    <option {% if s==plans[slot]['status'] %}selected{% endif %}>{{s}}</option>
  {% endfor %}
  </select>
</td>
</tr>
{% endfor %}
</table>

<div style="margin-top:20px">
<button type="button" onclick="validateAndSubmit()">Save</button>
<button type="button" onclick="location.reload()">Cancel</button>
<div style="margin-top:16px; text-align:center">
  <button type="submit">Save</button>
  <button type="button" onclick="location.reload()">Cancel</button>
</div>
</form>
</div>
@@ -288,67 +285,12 @@
  document.getElementById("current-date").textContent=ist.toDateString();
}
setInterval(updateClock,1000);updateClock();

function statusKey(s){return s.toLowerCase().replace(/\\s+/g,"-");}

function applyStatusColors(){
  document.querySelectorAll("tr[data-status]").forEach(r=>{
    r.className=r.className.replace(/status-\\S+/g,"");
    r.classList.add("status-"+statusKey(r.dataset.status));
  });
}

function validateAndSubmit(){
  let bad=false, first=null;
  document.querySelectorAll("tr[data-status]").forEach(r=>{
    const t=r.querySelector("textarea");
    r.classList.remove("row-error");
    if(r.dataset.status!=="Nothing Planned" && !t.value.trim()){
      r.classList.add("row-error");
      bad=true; if(!first) first=t;
    }
  });
  if(bad){
    document.getElementById("task-error").style.display="block";
    first.scrollIntoView({behavior:"smooth",block:"center"});
    first.focus(); return;
  }
  document.querySelector("form").submit();
}

let focus=true;
document.getElementById("focus-toggle").onclick=()=>{
  focus=!focus;
  document.getElementById("focus-toggle").innerHTML=
    focus?"🎯 Focus mode ON — <u>Show full day</u>":"📅 Full day view — <u>Enable focus</u>";
  applyFocus();
};

function applyFocus(){
  const rows=[...document.querySelectorAll("tr")];
  let found=false,next=0;
  rows.forEach(r=>{
    r.style.display="";
    if(!focus) return;
    if(r.classList.contains("current-slot")){found=true;return;}
    const t=r.querySelector("textarea");
    if(found && t.value.trim() && next<2){next++;return;}
    r.style.display="none";
  });
}

document.addEventListener("keydown",e=>{
  if(e.key.toLowerCase()==="f"){focus=!focus;applyFocus();}
});

document.addEventListener("DOMContentLoaded",()=>{
  applyStatusColors();
  applyFocus();
});
</script>

</body>
</html>"""
</html>
"""

if __name__ == "__main__":
    logger.info("Starting Daily Planner")
    logger.info("Starting Daily Planner (baseline)")
    app.run(debug=True)
