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
    "Deferred",
]

STATUS_COLORS = {
    "Nothing Planned": "#e5e7eb",
    "Yet to Start": "#fde68a",
    "In Progress": "#bfdbfe",
    "Closed": "#bbf7d0",
    "Deferred": "#fecaca",
}

HABIT_LIST = [
    "Walking",
    "Water",
    "No Shopping",
    "No TimeWastage",
    "8 hrs sleep",
    "Daily prayers",
]

HABIT_ICONS = {
    "Walking": "🚶",
    "Water": "💧",
    "No Shopping": "🛑🛍️",
    "No TimeWastage": "⏳",
    "8 hrs sleep": "😴",
    "Daily prayers": "🙏",
}

# ===============================
# HELPERS
# ===============================
def slot_label(slot: int) -> str:
    start = datetime.min + timedelta(minutes=(slot - 1) * 30)
    end = start + timedelta(minutes=30)
    return f"{start.strftime('%I:%M %p')} – {end.strftime('%I:%M %p')}"

def slot_start_end(plan_date: date, slot: int):
    start = datetime.combine(plan_date, datetime.min.time(), tzinfo=IST) + timedelta(
        minutes=(slot - 1) * 30
    )
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
        "dates": f"{start_utc:%Y%m%dT%H%M%SZ}/{end_utc:%Y%m%dT%H%M%SZ}",
        "details": "Created from Daily Planner",
        "trp": "false",
    }
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)

# ===============================
# DATA ACCESS
# ===============================
def load_day(plan_date):
    plans = {i: {"plan": "", "status": DEFAULT_STATUS} for i in range(1, TOTAL_SLOTS + 1)}
    habits = set()
    reflection = ""

    rows = get(
        "daily_slots",
        params={"plan_date": f"eq.{plan_date}", "select": "slot,plan,status"},
    ) or []

    for r in rows:
        if r["slot"] == META_SLOT:
            meta = json.loads(r.get("plan") or "{}")
            habits = set(meta.get("habits", []))
            reflection = meta.get("reflection", "")
        else:
            plans[r["slot"]] = {
                "plan": r.get("plan") or "",
                "status": r.get("status") or DEFAULT_STATUS,
            }

    return plans, habits, reflection

def save_day(plan_date, form):
    payload = []

    for slot in range(1, TOTAL_SLOTS + 1):
        plan = form.get(f"plan_{slot}", "").strip()
        status = form.get(f"status_{slot}", DEFAULT_STATUS)
        if plan:
            payload.append(
                {
                    "plan_date": str(plan_date),
                    "slot": slot,
                    "plan": plan,
                    "status": status,
                }
            )

    payload.append(
        {
            "plan_date": str(plan_date),
            "slot": META_SLOT,
            "plan": json.dumps(
                {
                    "habits": form.getlist("habits"),
                    "reflection": form.get("reflection", "").strip(),
                }
            ),
            "status": DEFAULT_STATUS,
        }
    )

    post(
        "daily_slots?on_conflict=plan_date,slot",
        payload,
        prefer="resolution=merge-duplicates",
    )

# ===============================
# ROUTE
# ===============================
@app.route("/", methods=["GET", "POST"])
def planner():
    today = datetime.now(IST).date()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    day = int(request.args.get("day", today.day))
    plan_date = date(year, month, day)

    saved = request.args.get("saved")
    cancelled = request.args.get("cancelled")

    if request.method == "POST":
        save_day(plan_date, request.form)
        return redirect(url_for("planner", year=year, month=month, day=day, saved=1))

    plans, habits, reflection = load_day(plan_date)

    return render_template_string(
        TEMPLATE,
        plans=plans,
        habits=habits,
        reflection=reflection,
        habit_list=HABIT_LIST,
        habit_icons=HABIT_ICONS,
        statuses=STATUSES,
        status_colors=STATUS_COLORS,
        saved=saved,
        cancelled=cancelled,
        google_calendar_links={
            s: google_calendar_link(plan_date, s, plans[s]["plan"])
            for s in range(1, TOTAL_SLOTS + 1)
        },
        days=[date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)],
        year=year,
        month=month,
        selected_day=day,
        now_slot=current_slot() if plan_date == today else None,
        slot_labels={i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)},
        calendar=calendar,
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
body {
  font-family: system-ui;
  background: #f6f7f9;
  padding: 12px;
  padding-bottom: 220px;
}

.container {
  max-width: 1100px;
  margin: auto;
  background: #fff;
  padding: 16px;
  border-radius: 14px;
}

.slot-row {
  display: grid;
  grid-template-columns: 140px 1fr 140px;
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
}

.slot-time {
  font-weight: 600;
  font-size: 14px;
}

.slot-task {
  width: 100%;
  min-height: 60px;
  font-size: 15px;
}

.status-pill {
  text-align: center;
  padding: 8px 10px;
  border-radius: 999px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.current-slot {
  background: #eef2ff;
  border-left: 4px solid #2563eb;
  padding-left: 8px;
}

.toast {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  background: #111827;
  color: #fff;
  padding: 10px 16px;
  border-radius: 10px;
  z-index: 10000;
}

.floating-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: env(safe-area-inset-bottom);
  background: #fff;
  border-top: 1px solid #e5e7eb;
  display: flex;
  gap: 12px;
  padding: 12px;
  z-index: 10000;
  box-shadow: 0 -4px 20px rgba(0,0,0,.08);
}

.floating-bar button {
  flex: 1;
  padding: 14px;
  font-size: 16px;
}

@media (max-width: 768px) {
  .slot-row {
    grid-template-columns: 100px 1fr;
    grid-template-areas:
      "time status"
      "task task";
  }
  .slot-time { grid-area: time; }
  .slot-task { grid-area: task; }
  .status-pill { grid-area: status; justify-self: end; }
}
</style>
</head>

<body>
<div class="container">

{% if saved %}
<div class="toast">✅ Saved successfully</div>
{% endif %}
{% if cancelled %}
<div class="toast">❌ Changes discarded</div>
{% endif %}

<form method="post" id="planner-form">
{% for slot in range(1,49) %}
<div class="slot-row {% if now_slot==slot %}current-slot{% endif %}">
  <div class="slot-time">{{slot_labels[slot]}}</div>

  <textarea class="slot-task" name="plan_{{slot}}">{{plans[slot]['plan']}}</textarea>

  <div class="status-pill"
       style="background:{{status_colors[plans[slot]['status']]}}"
       onclick="openStatusPicker(this)">
    {{plans[slot]['status']}}
  </div>

  <input type="hidden" name="status_{{slot}}" value="{{plans[slot]['status']}}">
</div>
{% endfor %}
</form>
</div>

<div class="floating-bar">
  <button type="submit" form="planner-form">💾 Save</button>
  <button type="button" onclick="cancelChanges()">❌ Cancel</button>
</div>

<div id="status-sheet" style="display:none;position:fixed;left:0;right:0;bottom:0;
background:#fff;border-top-left-radius:16px;border-top-right-radius:16px;
box-shadow:0 -10px 30px rgba(0,0,0,.15);z-index:10001;padding:16px;">
  <h3>Change status</h3>
  <div id="status-options"></div>
  <button onclick="closeStatusPicker()" style="margin-top:12px;width:100%;padding:12px;">
    Cancel
  </button>
</div>

<script>
setTimeout(() => document.querySelectorAll('.toast').forEach(t => t.remove()), 2000);

let activeStatusEl = null;
const STATUS_ORDER = {{statuses|tojson}};
const STATUS_COLORS = {{status_colors|tojson}};

function openStatusPicker(el){
  activeStatusEl = el;
  const c = document.getElementById("status-options");
  c.innerHTML = "";
  STATUS_ORDER.forEach(s => {
    const b = document.createElement("button");
    b.textContent = s;
    b.style.cssText = "width:100%;padding:12px;margin-bottom:8px;border-radius:10px;border:none;background:" + STATUS_COLORS[s];
    b.onclick = () => setStatus(s);
    c.appendChild(b);
  });
  document.getElementById("status-sheet").style.display = "block";
}

function setStatus(s){
  const input = activeStatusEl.nextElementSibling;
  input.value = s;
  activeStatusEl.textContent = s;
  activeStatusEl.style.background = STATUS_COLORS[s];
  closeStatusPicker();
}

function closeStatusPicker(){
  document.getElementById("status-sheet").style.display = "none";
}

function cancelChanges(){
  const u = new URL(window.location);
  u.searchParams.set("cancelled", "1");
  window.location = u.toString();
}
</script>

</body>
</html>
"""

if __name__ == "__main__":
    logger.info("Starting Daily Planner – stabilized UI build")
    app.run(debug=True)
