from flask import Flask, request, redirect, url_for, render_template_string
from datetime import date, datetime, timedelta
import calendar

from supabase_client import get, post, delete
from logger import setup_logger

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
    now = datetime.now()
    return (now.hour * 60 + now.minute) // 30 + 1

# ===============================
# DATA ACCESS (SUPABASE REST)
# ===============================
def load_day(plan_date):
    # --- Default slots ---
    plans = {
        i: {"plan": "", "status": DEFAULT_STATUS}
        for i in range(1, TOTAL_SLOTS + 1)
    }

    reflection = ""
    habits = set()

    # --- Load slot data ---
    slot_rows = get(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date}",
            "select": "slot,plan,status"
        }
    )

    for r in slot_rows:
        plans[r["slot"]] = {
            "plan": r.get("plan") or "",
            "status": r.get("status") or DEFAULT_STATUS
        }

    # --- Load summary ---
    summary_rows = get(
        "daily_summary",
        params={
            "plan_date": f"eq.{plan_date}",
            "select": "reflection,habits"
        }
    )

    if summary_rows:
        reflection = summary_rows[0].get("reflection") or ""
        if summary_rows[0].get("habits"):
            habits = set(summary_rows[0]["habits"].split(","))

    return plans, reflection, habits

def save_day(plan_date, form):

    slot_payload = []

    for slot in range(1, TOTAL_SLOTS + 1):
        plan = form.get(f"plan_{slot}", "").strip()
        status = form.get(f"status_{slot}", DEFAULT_STATUS)

        if plan:
            slot_payload.append({
                "plan_date": str(plan_date),
                "slot": slot,
                "plan": plan,
                "status": status,
            })

    # ---- BATCH UPSERT (ONE CALL) ----
    if slot_payload:
        post(
            "daily_slots?on_conflict=plan_date,slot",
            slot_payload,
            prefer="resolution=merge-duplicates"
        )

    # ---- DELETE CLEARED SLOTS (ONE CALL) ----
    delete(
        "daily_slots",
        params={
            "plan_date": f"eq.{plan_date}",
            "slot": "gt.0",
            "plan": "is.null"
        }
    )

    # ---- SUMMARY (ONE CALL) ----
    reflection = form.get("reflection", "").strip()
    habits = ",".join(form.getlist("habits"))

    post(
        "daily_summary?on_conflict=plan_date",
        {
            "plan_date": str(plan_date),
            "reflection": reflection,
            "habits": habits,
        },
        prefer="resolution=merge-duplicates"
    )


# ===============================
# ROUTE
# ===============================
@app.route("/", methods=["GET", "POST"])
def plan_of_day():
    today = date.today()

    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    day_param = request.args.get("day")

    if day_param:
        plan_date = date(year, month, int(day_param))
    else:
        plan_date = today if (year == today.year and month == today.month) else date(year, month, 1)

    if request.method == "POST":
        save_day(plan_date, request.form)
        return redirect(
            url_for(
                "plan_of_day",
                year=plan_date.year,
                month=plan_date.month,
                day=plan_date.day,
                saved=1
            )
        )

    plans, reflection, habits = load_day(plan_date)

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
        statuses=STATUSES,
        total_slots=TOTAL_SLOTS,
        slot_labels={i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)},
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
:root {
  --bg:#f6f7f9; --card:#fff; --text:#1f2937;
  --border:#e5e7eb; --primary:#2563eb;
}
body { background:var(--bg); font-family:system-ui; padding:20px; }
.container { max-width:1100px; margin:auto; background:var(--card);
  padding:24px; border-radius:12px; }

.month-title { font-size:20px; font-weight:600; margin-bottom:6px; }
.month-controls { display:flex; gap:8px; margin-bottom:12px; }

.day-strip { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:20px; }
.day-btn {
  width:38px; height:38px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  text-decoration:none; color:var(--text);
  border:1px solid var(--border);
  background:#f9fafb; font-weight:600;
}
.day-btn.selected { background:var(--primary); color:#fff; }
.day-btn.today { border:2px solid var(--primary); }

table { width:100%; border-collapse:collapse; }
td { padding:8px; vertical-align:top; }
.time { width:160px; font-weight:500; }

.plan-input {
  width: 100%;
  min-height: 44px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--border);
  font-size: 14px;
  line-height: 1.4;
  background: #f9fafb;
  transition: 
    border-color 0.15s ease,
    box-shadow 0.15s ease,
    background 0.15s ease;
}

/* Focus = premium feel */
.plan-input:focus {
  outline: none;
  background: #ffffff;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
}

/* Hover subtle */
.plan-input:hover {
  background: #ffffff;
}


.habits-grid {
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
  gap:10px; margin:20px 0;
}

.reflection-input {
  width:100%; min-height:120px;
  border-radius:10px; border:1px solid var(--border);
  padding:12px; resize:none;
}

.floating-actions {
  position:fixed; bottom:16px; left:50%;
  transform:translateX(-50%);
  background:#fff; border:1px solid var(--border);
  border-radius:12px; padding:10px 14px;
  display:flex; gap:10px;
}
.hidden { display:none; }
/* -------- Mobile Optimizations -------- */
@media (max-width: 768px) {

  table, tbody, tr, td {
    display: block;
    width: 100%;
  }

  tr {
    margin-bottom: 12px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }

  td.time {
    font-weight: 600;
    margin-bottom: 6px;
    width: 100%;
  }

select {
  width: 100%;
  padding: 8px 12px;
  border-radius: 999px; /* pill */
  border: 1px solid var(--border);
  background: #ffffff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease,
    background 0.15s ease;
}

/* Focus */
select:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
}
/* Status colors */
select[value="Nothing Planned"] { background:#f3f4f6; }
select[value="Yet to Start"]    { background:#fef3c7; }
select[value="In Progress"]    { background:#dbeafe; }
select[value="Closed"]         { background:#dcfce7; }
select[value="Deferred"]       { background:#fee2e2; }
tr {
  transition: background 0.15s ease;
}

tr:hover {
  background: #f9fafb;
}
.time {
  width: 160px;
  font-weight: 600;
  font-size: 13px;
  color: #374151;
}
@media (max-width: 768px) {
  textarea,
  select {
    font-size: 16px; /* prevents iOS zoom */
  }

  .plan-input {
    min-height: 64px;
  }
}


</style>
</head>

<body>
<div class="container">

{% if saved %}
<div id="save-msg" style="background:#dcfce7;color:#166534;padding:10px;border-radius:8px;margin-bottom:12px;font-weight:600;">
✅ Saved successfully
</div>
{% endif %}

<div class="month-title">{{ month_name }} {{ year }}</div>
<form method="get" class="month-controls">
  <input type="hidden" name="day" value="{{ selected_day }}">
  <select name="month" onchange="this.form.submit()">
    {% for m in range(1,13) %}
      <option value="{{m}}" {% if m==month %}selected{% endif %}>{{ calendar.month_name[m] }}</option>
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
   class="day-btn {% if d.day==selected_day %}selected{% endif %} {% if d==today %}today{% endif %}">
{{ d.day }}
</a>
{% endfor %}
</div>

<form method="post">

<table>
{% for slot in range(1,total_slots+1) %}
<tr>
<td class="time">{{ slot_labels[slot] }}</td>
<td>
<textarea class="plan-input" name="plan_{{slot}}" oninput="markDirty()">{{ plans[slot]['plan'] }}</textarea>
</td>
<td>
<select name="status_{{slot}}" onchange="markDirty()">
{% for s in statuses %}
<option value="{{s}}" {% if s==plans[slot]['status'] %}selected{% endif %}>{{s}}</option>
{% endfor %}
</select>
</td>
</tr>
{% endfor %}
</table>

<h3>✅ Habits</h3>
<div class="habits-grid">
{% for h in habit_list %}
<label>
<input type="checkbox" name="habits" value="{{h}}" {% if h in habits %}checked{% endif %} onchange="markDirty()"> {{ h }}
</label>
{% endfor %}
</div>

<h3>🪞 Reflection</h3>
<textarea name="reflection" class="reflection-input" oninput="markDirty()">{{ reflection }}</textarea>

<div id="floating-actions" class="floating-actions hidden">
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
    document.getElementById("floating-actions").classList.remove("hidden");
  }
}
document.addEventListener("DOMContentLoaded",()=>{
  document.getElementById("floating-actions").classList.add("hidden");
  const msg=document.getElementById("save-msg");
  if(msg) setTimeout(()=>msg.style.display="none",3000);
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    logger.info("Starting app (Supabase REST – stable mode)")
    app.run(debug=True)


