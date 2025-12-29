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
    reflection = ""
    habits = set()

    rows = get("daily_slots", params={
        "plan_date": f"eq.{plan_date}",
        "select": "slot,plan,status"
    })

    for r in rows:
        plans[r["slot"]] = {
            "plan": r.get("plan") or "",
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

def save_day(plan_date, form):
    payload = []

    for slot in range(1, TOTAL_SLOTS + 1):
        plan = form.get(f"plan_{slot}", "").strip()
        if not plan:
            continue

        payload.append({
            "plan_date": str(plan_date),
            "slot": slot,
            "plan": plan,
            "status": form.get(f"status_{slot}", DEFAULT_STATUS)
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
TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: system-ui; background:#f6f7f9; padding:12px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:16px; border-radius:14px; }

.header-bar { display:flex; justify-content:space-between; margin-bottom:12px; }
.header-time { font-weight:700; color:#2563eb; }

.focus-toggle { font-weight:600; color:#2563eb; cursor:pointer; margin-bottom:12px; }

.current-slot { background:#eef2ff; border-left:4px solid #2563eb; }

.focus-now { outline:2px solid #22c55e; }
.focus-next { outline:2px dashed #60a5fa; }

.status-nothing-planned { background:#f3f4f6; }
.status-yet-to-start { background:#fef3c7; }
.status-in-progress { background:#dbeafe; }
.status-closed { background:#dcfce7; }
.status-deferred { background:#fee2e2; }

.row-error { background:#fee2e2 !important; }

.reminder-link {
  text-decoration:none;
  font-size:18px;
  margin-left:8px;
}
</style>
</head>

<body>

{% if saved %}
<div id="save-msg" style="position:fixed;bottom:80px;left:50%;transform:translateX(-50%);
background:#dcfce7;padding:10px 16px;border-radius:999px;font-weight:600;">
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
</div>

<form method="post">
<table width="100%">
{% for slot in range(1,total_slots+1) %}
<tr data-status="{{ plans[slot]['status'] }}" class="{% if now_slot==slot %}current-slot{% endif %}">
<td>
  {{ slot_labels[slot] }}
  {% if plans[slot]['plan'] %}
    <a href="{{ reminder_links[slot] }}" target="_blank" class="reminder-link" title="Add to Google Calendar">⏰</a>
  {% endif %}
</td>
<td><textarea name="plan_{{slot}}">{{ plans[slot]['plan'] }}</textarea></td>
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
</div>
</form>
</div>

<script>
function updateClock(){
  const ist=new Date(new Date().toLocaleString("en-US",{timeZone:"Asia/Kolkata"}));
  document.getElementById("current-time").textContent=ist.toLocaleTimeString();
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

if __name__ == "__main__":
    logger.info("Starting Daily Planner")
    app.run(debug=True)
