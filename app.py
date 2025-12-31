from flask import Flask, request, redirect, url_for, render_template_string
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar

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
    ) or []

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

    logger.info("Planner save payload size: %d", len(payload))

    if payload:
        post(
            "daily_slots?on_conflict=plan_date,slot",
            payload,
            prefer="resolution=merge-duplicates",
        )

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
    rows = get("daily_habits", params={"plan_date": f"eq.{plan_date}"}) or []
    return {r["habit"]: r["done"] for r in rows}

def save_habits(plan_date, form):
    payload = [{
        "plan_date": str(plan_date),
        "habit": h,
        "done": form.get(f"habit_{h}") == "on"
    } for h in HABITS]

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
    if text:
        post(
            "daily_reflection?on_conflict=plan_date",
            [{"plan_date": str(plan_date), "reflection": text}],
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
    day = min(day, calendar.monthrange(year, month)[1])
    plan_date = date(year, month, day)

    if request.method == "POST":
        save_day(plan_date, request.form)
        save_habits(plan_date, request.form)
        save_reflection(plan_date, request.form)
        return redirect(url_for("planner", year=year, month=month, day=day, saved="1"))

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

# ===============================
# TEMPLATE
# ===============================
TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family:system-ui; background:#f6f7f9; padding:12px; padding-bottom:140px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:16px; border-radius:14px; }
.slot { margin-bottom:12px; }
textarea { width:100%; min-height:90px; font-size:16px; }
.status-pill {
  margin-top:6px;
  padding:6px 10px;
  border-radius:999px;
  border:1px solid #ddd;
  background:#f9fafb;
  font-size:14px;
}
.floating-bar {
  position:fixed; bottom:0; left:0; right:0;
  background:#fff; border-top:1px solid #ddd;
  display:flex; gap:10px; padding:10px;
}
.floating-bar button { flex:1; padding:14px; font-size:16px; }
</style>
</head>
<body>

{% if request.args.get("saved") %}
<div style="position:fixed;top:16px;left:50%;transform:translateX(-50%);
background:#16a34a;color:white;padding:12px 18px;border-radius:10px;">
✅ Data saved successfully
</div>
{% endif %}

<div class="container">
<form method="post" id="planner-form">
{% for slot in range(1,49) %}
<div class="slot">
  <b>{{slot_labels[slot]}}</b>
  <textarea name="plan_{{slot}}">{{plans[slot].text}}</textarea>

  <input type="hidden" id="status_{{slot}}" name="status_{{slot}}" value="{{plans[slot].status}}">
  <button type="button" class="status-pill" onclick="openStatusPopup({{slot}})">
    {{plans[slot].status}} ▾
  </button>
</div>
{% endfor %}
</form>
</div>

<div class="floating-bar">
  <button type="submit" form="planner-form">Save</button>
</div>

<!-- STATUS POPUP -->
<div id="status-popup" style="display:none;position:fixed;inset:0;
background:rgba(0,0,0,0.4);align-items:center;justify-content:center;">
  <div style="background:white;border-radius:12px;padding:12px;width:300px;">
    {% for s in STATUSES %}
    <button style="width:100%;padding:10px;margin:6px 0;"
            onclick="selectStatus('{{s}}')">{{s}}</button>
    {% endfor %}
    <button style="width:100%;padding:10px;" onclick="closeStatusPopup()">Cancel</button>
  </div>
</div>

<script>
let activeSlot=null;
function openStatusPopup(slot){activeSlot=slot;document.getElementById("status-popup").style.display="flex";}
function closeStatusPopup(){document.getElementById("status-popup").style.display="none";activeSlot=null;}
function selectStatus(s){
  const i=document.getElementById("status_"+activeSlot);
  i.value=s;
  i.parentElement.querySelector(".status-pill").textContent=s+" ▾";
  closeStatusPopup();
}
</script>

</body>
</html>
"""

if __name__ == "__main__":
    logger.info("Starting Daily Planner")
    app.run(debug=True)
