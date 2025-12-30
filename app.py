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
    "Walking": "🚶",
    "Water": "💧",
    "No Shopping": "🛑🛍️",
    "No TimeWastage": "⏳",
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

def compute_streak(habit, meta_rows):
    streak = 0
    for r in meta_rows:
        try:
            meta = json.loads(r["plan"] or "{}")
            if habit in meta.get("habits", []):
                streak += 1
            else:
                break
        except Exception:
            break
    return streak

# ===============================
# DATA ACCESS
# ===============================
def load_day(plan_date):
    plans = {i: {"plan": "", "status": DEFAULT_STATUS} for i in range(1, TOTAL_SLOTS + 1)}
    habits = set()
    reflection = ""

    rows = get("daily_slots", params={
        "plan_date": f"eq.{plan_date}",
        "select": "slot,plan,status"
    }) or []

    for r in rows:
        if r["slot"] == META_SLOT:
            try:
                meta = json.loads(r.get("plan") or "{}")
                habits = set(meta.get("habits", []))
                reflection = meta.get("reflection", "")
            except Exception:
                pass
        else:
            plans[r["slot"]] = {
                "plan": r.get("plan") or "",
                "status": r.get("status") or DEFAULT_STATUS
            }

    return plans, habits, reflection

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

    payload.append({
        "plan_date": str(plan_date),
        "slot": META_SLOT,
        "plan": json.dumps({
            "habits": form.getlist("habits"),
            "reflection": form.get("reflection", "").strip()
        }),
        "status": DEFAULT_STATUS
    })

    post(
        "daily_slots?on_conflict=plan_date,slot",
        payload,
        prefer="resolution=merge-duplicates"
    )

# ===============================
# ROUTES
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

    plans, habits, reflection = load_day(plan_date)

    meta_rows = get("daily_slots", params={
        "slot": f"eq.{META_SLOT}",
        "order": "plan_date.desc"
    }) or []

    habit_streaks = {h: compute_streak(h, meta_rows) for h in HABIT_LIST}

    reminder_links = {
        slot: google_calendar_link(plan_date, slot, plans[slot]["plan"])
        for slot in range(1, TOTAL_SLOTS + 1)
    }

    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]

    return render_template_string(
        TEMPLATE,
        year=year,
        month=month,
        days=days,
        selected_day=plan_date.day,
        today=today,
        plans=plans,
        statuses=STATUSES,
        total_slots=TOTAL_SLOTS,
        slot_labels={i: slot_label(i) for i in range(1, TOTAL_SLOTS + 1)},
        reminder_links=reminder_links,
        now_slot=current_slot() if plan_date == today else None,
        saved=request.args.get("saved"),
        habits=habits,
        reflection=reflection,
        habit_list=HABIT_LIST,
        habit_icons=HABIT_ICONS,
        habit_streaks=habit_streaks,
        calendar=calendar
    )

@app.route("/weekly")
def weekly():
    today = datetime.now(IST).date()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)

    rows = get("daily_slots", params={
        "plan_date": f"gte.{start}",
        "order": "plan_date.asc"
    }) or []

    return render_template_string(
        WEEKLY_TEMPLATE,
        rows=rows,
        start=start,
        end=end
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
body { font-family: system-ui; background:#f6f7f9; padding:12px; padding-bottom:160px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:16px; border-radius:14px; }

.header-bar { display:flex; justify-content:space-between; margin-bottom:12px; }
.header-time { font-weight:700; color:#2563eb; }

.month-controls { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
.day-strip { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }

.day-btn {
  width:36px; height:36px;
  border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  border:1px solid #ddd;
  text-decoration:none; color:#000;
}
.day-btn.selected { background:#2563eb; color:#fff; }

table { width:100%; border-collapse:collapse; }
td { padding:8px; border-bottom:1px solid #eee; vertical-align:top; }

.current-slot { background:#eef2ff; border-left:4px solid #2563eb; }

.status-nothing-planned { background:#f3f4f6; }
.status-yet-to-start { background:#fef3c7; }
.status-in-progress { background:#dbeafe; }
.status-closed { background:#dcfce7; }
.status-deferred { background:#fee2e2; }

.habits { display:flex; flex-wrap:wrap; gap:10px; margin:12px 0; }
.habit { border:1px solid #ddd; padding:6px 12px; border-radius:20px; }

textarea { width:100%; }

.floating-bar {
  position:fixed;
  bottom:0;
  left:0;
  right:0;
  background:#fff;
  border-top:1px solid #ddd;
  padding:10px;
  display:flex;
  gap:10px;
  z-index:2000;
}
.floating-bar button { flex:1; padding:12px; font-size:16px; }
</style>
</head>

<body>

{% if saved %}
<div id="save-toast" style="position:fixed;bottom:90px;left:50%;
transform:translateX(-50%);
background:#dcfce7;padding:10px 16px;border-radius:999px;font-weight:600;">
✅ Saved successfully
</div>
{% endif %}

<div class="container">

<div class="header-bar">
  <div id="current-date"></div>
  <div class="header-time">🕒 <span id="current-time"></span> IST</div>
</div>

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
   class="day-btn {% if d.day==selected_day %}selected{% endif %}">
{{ d.day }}
</a>
{% endfor %}
</div>

<form method="post">

<table>
{% for slot in range(1,total_slots+1) %}
<tr class="{% if now_slot==slot %}current-slot{% endif %}
status-{{ plans[slot]['status'].lower().replace(' ','-') }}">
<td>
  {{ slot_labels[slot] }}
  {% if plans[slot]['plan'] %}
    <a href="{{ reminder_links[slot] }}" target="_blank">⏰</a>
  {% endif %}
</td>
<td>
  <textarea name="plan_{{slot}}">{{ plans[slot]['plan'] }}</textarea>
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

<h3 style="margin-top:24px">🏃 Habits</h3>
<div class="habits">
{% for h in habit_list %}
<label class="habit">
  <input type="checkbox" name="habits" value="{{h}}" {% if h in habits %}checked{% endif %}>
  {{ habit_icons[h] }} {{h}} {% if habit_streaks[h] > 0 %}🔥{{habit_streaks[h]}}{% endif %}
</label>
{% endfor %}
</div>

<h3>📝 Reflection of the day</h3>
<textarea name="reflection" rows="3">{{reflection}}</textarea>

</form>

</div>

<div class="floating-bar">
  <button type="submit" formmethod="post">💾 Save</button>
  <button type="button" onclick="cancelEdit()">❌ Cancel</button>
  <a href="/weekly" style="flex:1;text-align:center;line-height:44px;text-decoration:none;">📊 Weekly</a>
</div>

<script>
function updateClock(){
  const ist=new Date(new Date().toLocaleString("en-US",{timeZone:"Asia/Kolkata"}));
  document.getElementById("current-time").textContent=ist.toLocaleTimeString();
  document.getElementById("current-date").textContent=ist.toDateString();
}
setInterval(updateClock,1000);updateClock();

window.addEventListener("load", () => {
  const cur = document.querySelector(".current-slot textarea");
  if(cur){ cur.focus(); cur.scrollIntoView({behavior:"smooth",block:"center"}); }
});

function cancelEdit(){
  const url = new URL(window.location.href);
  url.searchParams.delete("saved");
  window.location.href = url.toString();
}

{% if saved %}
setTimeout(()=>{ const t=document.getElementById("save-toast"); if(t) t.remove(); },2500);
{% endif %}
</script>

</body>
</html>
"""

WEEKLY_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: system-ui; padding:16px; }
.day { border-bottom:1px solid #ddd; padding:10px 0; }
</style>
</head>
<body>

<h2>📊 Weekly Summary</h2>
<p>{{start}} → {{end}}</p>

{% for r in rows %}
{% if r.slot == 0 %}
<div class="day">
<strong>{{r.plan_date}}</strong><br>
{{ r.plan }}
</div>
{% endif %}
{% endfor %}

<p><a href="/">⬅ Back</a></p>

</body>
</html>
"""

if __name__ == "__main__":
    logger.info("Starting Daily Planner (final stable build)")
    app.run(debug=True)

