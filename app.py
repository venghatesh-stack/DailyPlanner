from flask import Flask, request, redirect, url_for, render_template_string
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar
import urllib.parse
import json

from supabase_client import get, post
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

    rows = get(
        "daily_slots",
        params={"plan_date": f"eq.{plan_date}", "select": "slot,plan,status"},
    ) or []

    for r in rows:
        if r["slot"] != META_SLOT:
            plans[r["slot"]] = {
                "plan": r.get("plan") or "",
                "status": r.get("status") or DEFAULT_STATUS,
            }

    return plans

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

    if payload:
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

    plans = load_day(plan_date)

    return render_template_string(
        TEMPLATE,
        plans=plans,
        statuses=STATUSES,
        status_colors=STATUS_COLORS,
        saved=saved,
        cancelled=cancelled,
        year=year,
        month=month,
        selected_day=day,
        days=[date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)],
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
body { font-family: system-ui; background:#f6f7f9; padding:12px; padding-bottom:180px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:16px; border-radius:12px; }

table { width:100%; border-collapse:collapse; }
th, td { padding:8px; vertical-align:top; }

th { text-align:left; font-size:14px; color:#374151; }
textarea { width:100%; min-height:60px; font-size:15px; }

.status-select {
  padding:6px 8px;
  border-radius:999px;
  font-weight:600;
  border:none;
}

.current-slot td {
  background:#eef2ff;
}

.toast {
  position:fixed;
  top:16px;
  left:50%;
  transform:translateX(-50%);
  background:#111827;
  color:#fff;
  padding:10px 16px;
  border-radius:10px;
  z-index:10000;
}

.floating-bar {
  position:fixed;
  left:0; right:0;
  bottom:env(safe-area-inset-bottom);
  background:#fff;
  border-top:1px solid #e5e7eb;
  display:flex;
  gap:12px;
  padding:12px;
  z-index:10000;
}
.floating-bar button {
  flex:1;
  padding:14px;
  font-size:16px;
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

<table>
<tr>
  <th style="width:140px;">Time</th>
  <th>Task</th>
  <th style="width:160px;">Status</th>
</tr>

<form method="post" id="planner-form">
{% for slot in range(1,49) %}
<tr class="{% if now_slot==slot %}current-slot{% endif %}">
  <td>{{slot_labels[slot]}}</td>
  <td>
    <textarea name="plan_{{slot}}">{{plans[slot]['plan']}}</textarea>
  </td>
  <td>
    <select name="status_{{slot}}" class="status-select"
            style="background:{{status_colors[plans[slot]['status']]}}">
      {% for s in statuses %}
        <option value="{{s}}" {% if s==plans[slot]['status'] %}selected{% endif %}>
          {{s}}
        </option>
      {% endfor %}
    </select>
  </td>
</tr>
{% endfor %}
</form>
</table>

</div>

<div class="floating-bar">
  <button type="submit" form="planner-form">💾 Save</button>
  <button type="button" onclick="cancel()">❌ Cancel</button>
</div>

<script>
setTimeout(() => document.querySelectorAll('.toast').forEach(t => t.remove()), 2000);

function cancel(){
  const u = new URL(window.location);
  u.searchParams.set("cancelled", "1");
  window.location = u.toString();
}
</script>

</body>
</html>
"""

if __name__ == "__main__":
    logger.info("Starting Daily Planner – rollback stable build")
    app.run(debug=True)
