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
body { font-family:system-ui; background:#f6f7f9; padding:12px; padding-bottom:220px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:16px; border-radius:14px; }

.toast {
  position:fixed;
  top:16px; left:50%;
  transform:translateX(-50%);
  background:#111827;
  color:#fff;
  padding:10px 16px;
  border-radius:10px;
  z-index:10000;
}

.status-pill {
  display:inline-block;
  padding:6px 12px;
  border-radius:999px;
  font-weight:600;
  cursor:pointer;
}

.floating-bar {
  position:fixed;
  left:0; right:0;
  bottom:env(safe-area-inset-bottom);
  background:#fff;
  border-top:1px solid #ddd;
  display:flex;
  gap:10px;
  padding:10px;
  z-index:9999;
}
.floating-bar button { flex:1; padding:14px; font-size:16px; }
</style>
</head>

<body>

{% if saved %}
<div class="toast">✅ Saved successfully</div>
{% endif %}
{% if cancelled %}
<div class="toast">❌ Changes discarded</div>
{% endif %}

<form method="post" id="planner-form">
{% for slot in range(1,49) %}
<div>
  <b>{{slot_labels[slot]}}</b>
  <textarea name="plan_{{slot}}">{{plans[slot]['plan']}}</textarea>

  <div class="status-pill"
       style="background:{{status_colors[plans[slot]['status']]}}"
       onclick="cycleStatus(this)">
    {{plans[slot]['status']}}
  </div>
  <input type="hidden" name="status_{{slot}}" value="{{plans[slot]['status']}}">
</div>
{% endfor %}
</form>

<div class="floating-bar">
  <button type="submit" form="planner-form">💾 Save</button>
  <button type="button" onclick="cancel()">❌ Cancel</button>
</div>

<script>
setTimeout(()=>document.querySelectorAll('.toast').forEach(t=>t.remove()),2000);

const STATUS_ORDER = {{statuses|tojson}};
const STATUS_COLORS = {{status_colors|tojson}};

function cycleStatus(el){
  const input = el.nextElementSibling;
  let idx = STATUS_ORDER.indexOf(input.value);
  idx = (idx + 1) % STATUS_ORDER.length;
  input.value = STATUS_ORDER[idx];
  el.textContent = STATUS_ORDER[idx];
  el.style.background = STATUS_COLORS[input.value];
}

function cancel(){
  const url = new URL(window.location);
  url.searchParams.set("cancelled", "1");
  window.location = url.toString();
}
</script>

</body>
</html>
"""

if __name__ == "__main__":
    logger.info("Starting Daily Planner – architect-grade stable build")
    app.run(debug=True)
