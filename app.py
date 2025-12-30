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
    "Walking", "Water", "No Shopping",
    "No TimeWastage", "8 hrs sleep", "Daily prayers"
]

HABIT_ICONS = {
    "Walking": "🚶‍♂️", "Water": "💧", "No Shopping": "🛒🚫",
    "No TimeWastage": "⏳🚫", "8 hrs sleep": "😴", "Daily prayers": "🙏"
}

# ---------- HELPERS ----------
def slot_label(slot):
    start = datetime.min + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return f"{start.strftime('%I:%M %p')} – {end.strftime('%I:%M %p')}"

def slot_start_end(plan_date, slot):
    start = datetime.combine(plan_date, datetime.min.time(), tzinfo=IST) + timedelta(minutes=(slot - 1) * 30)
    return start, start + timedelta(minutes=30)

def current_slot():
    now = datetime.now(IST)
    return (now.hour * 60 + now.minute) // 30 + 1

def google_calendar_link(plan_date, slot, task):
    if not task:
        return "#"
    s, e = slot_start_end(plan_date, slot)
    s, e = s.astimezone(ZoneInfo("UTC")), e.astimezone(ZoneInfo("UTC"))
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode({
        "action": "TEMPLATE",
        "text": task,
        "dates": f"{s.strftime('%Y%m%dT%H%M%SZ')}/{e.strftime('%Y%m%dT%H%M%SZ')}"
    })

# ---------- DATA ----------
def load_day(plan_date):
    plans = {i: {"plan": "", "status": DEFAULT_STATUS} for i in range(1, TOTAL_SLOTS + 1)}
    rows = get("daily_slots", params={"plan_date": f"eq.{plan_date}", "select": "slot,plan,status"})
    for r in rows:
        plans[r["slot"]] = {"plan": r["plan"] or "", "status": r["status"] or DEFAULT_STATUS}
    return plans

def save_day(plan_date, form):
    payload = []
    for slot in range(1, TOTAL_SLOTS + 1):
        plan = form.get(f"plan_{slot}", "").strip()
        status = form.get(f"status_{slot}", DEFAULT_STATUS)
        if status != DEFAULT_STATUS and not plan:
            continue  # HARD BACKEND SAFETY
        if plan:
            payload.append({
                "plan_date": str(plan_date),
                "slot": slot,
                "plan": plan,
                "status": status
            })
    if payload:
        post("daily_slots?on_conflict=plan_date,slot", payload, prefer="resolution=merge-duplicates")

# ---------- ROUTE ----------
@app.route("/", methods=["GET", "POST"])
def plan_of_day():
    today = datetime.now(IST).date()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    day = int(request.args.get("day", today.day))
    plan_date = date(year, month, day)

    if request.method == "POST":
        save_day(plan_date, request.form)
        return redirect(url_for("plan_of_day", year=year, month=month, day=day, saved=1))

    plans = load_day(plan_date)
    reminder_links = {i: google_calendar_link(plan_date, i, plans[i]["plan"]) for i in range(1, TOTAL_SLOTS + 1)}

    return render_template_string(
        TEMPLATE,
        plans=plans,
        reminder_links=reminder_links,
        statuses=STATUSES,
        total_slots=TOTAL_SLOTS,
        slot_labels={i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)},
        now_slot=current_slot() if plan_date == today else None,
        year=year,
        month=month,
        days=[date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)],
        selected_day=day,
        saved=request.args.get("saved"),
        calendar=calendar
    )

# ---------- TEMPLATE ----------
TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:system-ui;background:#f6f7f9;padding:12px}
.container{max-width:1100px;margin:auto;background:#fff;padding:16px;border-radius:14px}

.status-nothing-planned{background:#f3f4f6}
.status-yet-to-start{background:#fef3c7}
.status-in-progress{background:#dbeafe}
.status-closed{background:#dcfce7}
.status-deferred{background:#fee2e2}

.current-slot{border-left:4px solid #2563eb;background:#eef2ff}
.row-error{background:#fee2e2!important}

.floating-actions{
  position:fixed;left:0;right:0;bottom:12px;
  background:#fff;padding:12px;border-top:1px solid #ddd;
  display:flex;gap:12px;z-index:9999
}
.floating-actions button{flex:1;padding:14px;font-size:16px;border-radius:12px}
</style>
</head>

<body>

{% if saved %}
<div style="position:fixed;bottom:80px;left:50%;transform:translateX(-50%);
background:#dcfce7;padding:10px 16px;border-radius:999px;font-weight:600">
✅ Saved successfully
</div>
{% endif %}

<div id="error-toast" style="display:none;position:fixed;bottom:80px;left:50%;
transform:translateX(-50%);background:#fee2e2;color:#991b1b;
padding:10px 16px;border-radius:999px;font-weight:600">
❌ Task description required
</div>

<div class="container">
<form method="post">
<table width="100%">
{% for slot in range(1,total_slots+1) %}
<tr data-status="{{plans[slot]['status']}}" class="{% if now_slot==slot %}current-slot{% endif %}">
<td>{{slot_labels[slot]}} <a href="{{reminder_links[slot]}}" target="_blank">⏰</a></td>
<td><textarea name="plan_{{slot}}" oninput="markDirty()">{{plans[slot]['plan']}}</textarea></td>
<td>
<select name="status_{{slot}}" onchange="onStatusChange(this)">
{% for s in statuses %}<option {% if s==plans[slot]['status'] %}selected{% endif %}>{{s}}</option>{% endfor %}
</select>
</td>
</tr>
{% endfor %}
</table>

<div class="floating-actions">
<button id="saveBtn" type="button" onclick="validateAndSubmit()" disabled>Save</button>
<button type="button" onclick="location.reload()">Cancel</button>
</div>
</form>
</div>

<script>
function statusKey(s){return s.toLowerCase().replace(/\\s+/g,'-')}
function applyStatusColors(){
 document.querySelectorAll('tr[data-status]').forEach(r=>{
  r.className=r.className.replace(/status-\\S+/g,'')
  r.classList.add('status-'+statusKey(r.dataset.status))
 })
}
function onStatusChange(sel){
 sel.closest('tr').dataset.status=sel.value
 applyStatusColors();markDirty()
}
function markDirty(){document.getElementById('saveBtn').disabled=false}
function validateAndSubmit(){
 let bad=false,first=null
 document.querySelectorAll('tr[data-status]').forEach(r=>{
  const t=r.querySelector('textarea')
  r.classList.remove('row-error')
  if(r.dataset.status!=='Nothing Planned'&&!t.value.trim()){
    r.classList.add('row-error');bad=true;if(!first)first=t
  }
 })
 if(bad){
  document.getElementById('error-toast').style.display='block'
  first.scrollIntoView({behavior:'smooth',block:'center'});first.focus();return
 }
 document.querySelector('form').submit()
}
applyStatusColors()
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True)
