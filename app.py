from flask import Flask, request, redirect, url_for, render_template_string
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar

from supabase_client import get, post
from logger import setup_logger

# ===============================
# APP SETUP
# ===============================
IST = ZoneInfo("Asia/Kolkata")
app = Flask(__name__)
logger = setup_logger()

# ===============================
# CONSTANTS
# ===============================
TOTAL_SLOTS = 48

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
def today_ist():
    return datetime.now(IST).date()

def start_of_week(d):
    return d - timedelta(days=d.weekday())

def compute_habit_streak(habit, records):
    """Safe streak calculation – no DB writes"""
    streak = 0
    for r in sorted(records, key=lambda x: x["date"], reverse=True):
        if habit in r.get("habits", ""):
            streak += 1
        else:
            break
    return streak

# ===============================
# ROUTES
# ===============================
@app.route("/", methods=["GET", "POST"])
def index():
    selected_date = request.args.get("date")
    plan_date = (
        datetime.strptime(selected_date, "%Y-%m-%d").date()
        if selected_date else today_ist()
    )

    saved = False

    if request.method == "POST":
        habits = request.form.getlist("habits")
        reflection = request.form.get("reflection", "").strip()

        # 🔒 Validation
        if not reflection:
            return redirect(url_for("index", date=plan_date))

        payload = {
            "date": plan_date.isoformat(),
            "habits": ",".join(habits),
            "reflection": reflection,
        }

        post("/daily_reflection", payload)
        saved = True

    # Load existing day
    existing = get(f"/daily_reflection?date=eq.{plan_date.isoformat()}")
    habits_set = set()
    reflection = ""

    if existing:
        habits_set = set(existing[0].get("habits", "").split(","))
        reflection = existing[0].get("reflection", "")

    # Habit streaks (safe, computed)
    all_records = get("/daily_reflection?order=date.desc") or []
    habit_streaks = {
        h: compute_habit_streak(h, all_records) for h in HABIT_LIST
    }

    html = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: Arial; margin: 10px; padding-bottom: 100px; }
h2 { margin-top: 20px; }
.habits { display: flex; flex-wrap: wrap; gap: 10px; }
.habit {
  border: 1px solid #ccc;
  padding: 8px 12px;
  border-radius: 20px;
}
textarea {
  width: 100%;
  height: 120px;
  font-size: 14px;
}
.floating-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: white;
  border-top: 1px solid #ccc;
  padding: 10px;
  display: flex;
  gap: 10px;
}
.floating-bar button {
  flex: 1;
  padding: 12px;
  font-size: 16px;
}
.toast {
  position: fixed;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  background: #4CAF50;
  color: white;
  padding: 10px 20px;
  border-radius: 6px;
  display: none;
}
</style>
</head>

<body>

<div id="toast" class="toast">Saved successfully ✅</div>

<h2 id="current-date"></h2>
<h3 id="current-time"></h3>

<form method="POST">

<h2>Habits</h2>
<div class="habits">
{% for h in habits_list %}
<label class="habit">
  <input type="checkbox" name="habits" value="{{h}}" {% if h in habits %}checked{% endif %}>
  {{h}} (🔥 {{habit_streaks[h]}})
</label>
{% endfor %}
</div>

<h2>Reflection of the Day</h2>
<textarea name="reflection" placeholder="Write your reflection...">{{reflection}}</textarea>

<div class="floating-bar">
  <button type="submit">💾 Save</button>
  <button type="button" onclick="location.reload()">❌ Cancel</button>
</div>

</form>

<p style="margin-top:30px;">
  <a href="/weekly">📊 Weekly Review</a>
</p>

<script>
function updateClock(){
  const ist=new Date(new Date().toLocaleString("en-US",{timeZone:"Asia/Kolkata"}));
  document.getElementById("current-time").textContent=ist.toLocaleTimeString();
  document.getElementById("current-date").textContent=ist.toDateString();
}
setInterval(updateClock,1000);updateClock();

{% if saved %}
const toast=document.getElementById("toast");
toast.style.display="block";
setTimeout(()=>toast.style.display="none",2500);
{% endif %}
</script>

</body>
</html>
"""
    return render_template_string(
        html,
        habits_list=HABIT_LIST,
        habits=habits_set,
        reflection=reflection,
        habit_streaks=habit_streaks,
        saved=saved,
    )

# ===============================
# WEEKLY REVIEW (READ ONLY)
# ===============================
@app.route("/weekly")
def weekly():
    today = today_ist()
    start = start_of_week(today)
    end = start + timedelta(days=6)

    records = get(
        f"/daily_reflection?date=gte.{start}&date=lte.{end}&order=date.asc"
    ) or []

    html = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: Arial; margin: 10px; }
.day { border-bottom: 1px solid #ccc; padding: 10px 0; }
</style>
</head>
<body>

<h2>Weekly Review</h2>
<p>{{start}} → {{end}}</p>

{% for r in records %}
<div class="day">
  <strong>{{r.date}}</strong><br>
  Habits: {{r.habits}}<br>
  Reflection: {{r.reflection}}
</div>
{% endfor %}

<p><a href="/">⬅ Back</a></p>

</body>
</html>
"""
    return render_template_string(html, records=records, start=start, end=end)

# ===============================
# MAIN
# ===============================
if __name__ == "__main__":
    logger.info("Starting Daily Planner – Stable + Enhanced")
    app.run(debug=True)
