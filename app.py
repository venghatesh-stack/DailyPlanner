import Flask, request, redirect, url_for, render_template_string
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
        status = form.get(f"status_{slot}", DEFAULT_STATUS)
        if plan:
            payload.append({
                "plan_date": str(plan_date),
                "slot": slot,
                "plan": plan,
                "status": status
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
        month_name=calendar.month_name[month],
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
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: system-ui; background:#f6f7f9; padding:12px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:16px; border-radius:14px; }

.header-bar { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
.header-date { font-weight:600; }
.header-time { font-weight:700; color:#2563eb; }

.month-controls { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
.day-strip { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }

.day-btn {
  width:38px; height:38px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  border:1px solid #ddd; text-decoration:none;
}
.day-btn.selected { background:#2563eb; color:#fff; }

.current-slot { background:#eef2ff; border-left:4px solid #2563eb; }

table { width:100%; border-collapse:collapse; }
tr { border-bottom:1px solid #eee; }

textarea, select {
  width:100%;
  font-size:16px;
  padding:8px;
}

/* ===== ACTION BAR ===== */
.floating-actions {
  display: none;
  gap: 12px;
}

/* Desktop: centered action bar */
@media (min-width: 769px) {
  .floating-actions {
    position: sticky;
    bottom: 12px;
    justify-content: center;
    margin-top: 24px;
  }

  .floating-actions button {
    min-width: 180px;
  }
}

/* Mobile: full-width thumb-friendly */
@media (max-width: 768px) {
  .floating-actions {
    position: sticky;
    bottom: 12px;
  }

  .floating-actions button {
    flex: 1;
    padding: 14px;
    font-size: 16px;
  }
}




.floating-actions button {
  flex:1;
  padding:14px;
  font-size:16px;
  border-radius:12px;
}
/* ===== DESKTOP TABLE LAYOUT (RESTORE) ===== */
@media (min-width: 769px) {

  table {
    width: 100%;
    border-collapse: collapse;
  }

  tr {
    display: table-row;
  }

  td {
    display: table-cell;
    vertical-align: top;
    padding: 10px;
  }

  /* Column widths */
  td:nth-child(1) {
    width: 180px; /* time */
    white-space: nowrap;
    font-weight: 600;
  }

  td:nth-child(2) {
    width: auto; /* task */
  }

  td:nth-child(3) {
    width: 180px; /* status */
  }

  textarea {
    min-height: 48px;
  }

  select {
    width: 100%;
  }
}

/* ===== MOBILE CARD LAYOUT ONLY ===== */
@media (max-width: 768px) {

  table, tr, td {
    display: block;
    width: 100%;
  }

  tr {
    margin-bottom: 14px;
    padding: 12px;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    background: #fff;
  }

  td {
    padding: 6px 0;
  }

  td:nth-child(1) {
    font-weight: 600;
    margin-bottom: 6px;
  }

  textarea {
    min-height: 64px;
  }
}

/* Status background colors */
/* ===== Status row colors ===== */
.status-nothing-planned { background:#f3f4f6; }
.status-yet-to-start    { background:#fef3c7; }
.status-in-progress     { background:#dbeafe; }
.status-closed          { background:#dcfce7; }
.status-deferred        { background:#fee2e2; }

/* Desktop table clarity */
tr[class^="status-"] td {
  background: inherit;
}

/* Left accent bar */
tr[class^="status-"] {
  border-left: 6px solid rgba(0,0,0,0.08);
}

/* ===== Status dropdown colors ===== */
select.status-nothing-planned { background:#f3f4f6; }
select.status-yet-to-start    { background:#fef3c7; }
select.status-in-progress     { background:#dbeafe; }
select.status-closed          { background:#dcfce7; }
select.status-deferred        { background:#fee2e2; }

select {
  font-weight: 600;
}
/* ===== Validation error styling ===== */
.row-error {
  background: #fee2e2 !important; /* light red */
}

.row-error td {
  background: #fee2e2 !important;
}

.row-error textarea {
  border: 2px solid #ef4444;
  background: #fff5f5;
}
/* Collapsed empty slots */
.hidden-slot {
  display: none !important;
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
<div id="task-error" style="
  display:none;
  background:#fee2e2;
  color:#991b1b;
  padding:12px 14px;
  border-radius:10px;
  margin-bottom:12px;
  font-weight:600;
">
  ❌ Tasks cannot be empty. Rows highlighted in red must be corrected.
</div>
<div id="collapse-toggle" style="
  display:none;
  margin-bottom:12px;
  font-weight:600;
  color:#2563eb;
  cursor:pointer;
">
  ⏳ <span id="hidden-count"></span> empty slots hidden — <u>Show</u>
</div>

<form method="post">
<table>
{% for slot in range(1,total_slots+1) %}
<tr
  class="{% if now_slot==slot %}current-slot{% endif %}"
  data-status="{{ plans[slot]['status'] }}">

<td>🕒 {{ slot_labels[slot] }}</td>
<td>
<textarea name="plan_{{slot}}" rows="2" oninput="markDirty()">{{ plans[slot]['plan'] }}</textarea>
</td>
<td>
<select name="status_{{slot}}" onchange="markDirty()">
{% for s in statuses %}
<option {% if s==plans[slot]['status'] %}selected{% endif %}>{{s}}</option>
{% endfor %}
</select>
</td>
</tr>
{% endfor %}
</table>

<h3>✅ Habits</h3>
{% for h in habit_list %}
<label>
<input type="checkbox" name="habits" value="{{h}}" {% if h in habits %}checked{% endif %} onchange="markDirty()">
{{ habit_icons[h] }} {{ h }}
</label><br>
{% endfor %}

<h3>🪞 Reflection</h3>
<textarea name="reflection" rows="4" oninput="markDirty()">{{ reflection }}</textarea>

<div id="actions" class="floating-actions">
<button type="button" onclick="validateAndSubmit()">Save</button>
<button type="button" onclick="location.reload()">Cancel</button>
</div>
</form>
</div>

<script>
let dirty=false;
function markDirty(){
  document.getElementById("actions").style.display = "flex";
}

function validateAndSubmit() {
  const rows = document.querySelectorAll("tr[data-status]");
  const errorBox = document.getElementById("task-error");

  let firstInvalidTextarea = null;
  let hasErrors = false;

  // Clear previous errors
  rows.forEach(row => row.classList.remove("row-error"));

  rows.forEach(row => {
    const status = row.dataset.status;
    const textarea = row.querySelector("textarea");

    const isInvalid =
      status &&
      status !== "Nothing Planned" &&
      textarea &&
      textarea.value.trim() === "";

    if (isInvalid) {
      hasErrors = true;
      row.classList.add("row-error");

      if (!firstInvalidTextarea) {
        firstInvalidTextarea = textarea;
      }
    }
  });

  if (hasErrors) {
    errorBox.style.display = "block";

    firstInvalidTextarea.scrollIntoView({
      behavior: "smooth",
      block: "center"
    });
    firstInvalidTextarea.focus();

    // ensure collapsed rows stay visible
    if (typeof applyCollapse === "function") {
      applyCollapse();
    }

    return; // 🚫 stop submit
  }

  errorBox.style.display = "none";

  // ✅ submit form programmatically
  document.querySelector("form[method='post']").submit();
}


function updateClock(){
  const now=new Date();
  const utc=now.getTime()+now.getTimezoneOffset()*60000;
  const ist=new Date(utc+330*60000);
  document.getElementById("current-time").textContent =
    ist.toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:true});
  document.getElementById("current-date").textContent =
    ist.toLocaleDateString("en-IN",{weekday:"long",day:"numeric",month:"long",year:"numeric"});
}
updateClock();
setInterval(updateClock,1000);
const msg = document.getElementById("save-msg");
if (msg) {
  setTimeout(() => {
    msg.style.transition = "opacity 0.4s ease";
    msg.style.opacity = "0";
    setTimeout(() => msg.remove(), 400);
  }, 2500);
}
let lastHeight = window.innerHeight;
const actions = document.getElementById("actions");

window.addEventListener("resize", () => {
  if (!actions) return;

  const currentHeight = window.innerHeight;
  const keyboardOpen = currentHeight < lastHeight - 120;

  if (keyboardOpen) {
    // Move buttons above keyboard
    actions.style.bottom = "calc(100vh - " + currentHeight + "px + 12px)";
  } else {
    // Reset position
    actions.style.bottom = "env(safe-area-inset-bottom, 12px)";
  }

  lastHeight = currentHeight;
});
function statusKey(status) {
  return status.toLowerCase().replace(/\s+/g, "-");
}

function applyStatusColors() {
  document.querySelectorAll("tr[data-status]").forEach(row => {
    const status = row.dataset.status;
    if (!status) return;

    const key = statusKey(status);

    // Clean old status classes
    row.className = row.className.replace(/\bstatus-\S+/g, "");
    row.classList.add("status-" + key);

    // Apply to dropdown also
    const select = row.querySelector("select");
    if (select) {
      select.className = select.className.replace(/\bstatus-\S+/g, "");
      select.classList.add("status-" + key);
    }
  });
}



document.querySelectorAll("select[name^='status_']").forEach(sel => {
  sel.addEventListener("change", e => {
    const row = e.target.closest("tr");
    row.dataset.status = e.target.value;
    applyStatusColors();
    markDirty();
  });
});


document.addEventListener("DOMContentLoaded", () => {
  applyStatusColors();
  applyCollapse();
});


let collapsed = true;

function isEmptySlot(row) {
  const status = row.dataset.status;
  const textarea = row.querySelector("textarea");

  if (!textarea) return false;

  const isCurrent = row.classList.contains("current-slot");
  const hasError = row.classList.contains("row-error");

  return (
    !isCurrent &&
    !hasError &&
    (!textarea.value.trim()) &&
    (status === "Nothing Planned")
  );
}

function applyCollapse() {
  const rows = document.querySelectorAll("tr[data-status]");
  let hiddenCount = 0;

  rows.forEach(row => {
    if (collapsed && isEmptySlot(row)) {
      row.classList.add("hidden-slot");
      hiddenCount++;
    } else {
      row.classList.remove("hidden-slot");
    }
  });

  const toggle = document.getElementById("collapse-toggle");
  const countSpan = document.getElementById("hidden-count");

  if (hiddenCount > 0) {
    toggle.style.display = "block";
    countSpan.textContent = hiddenCount;
    toggle.innerHTML = collapsed
      ? `⏳ <span id="hidden-count">${hiddenCount}</span> empty slots hidden — <u>Show</u>`
      : `⬆️ Hide empty slots`;
  } else {
    toggle.style.display = "none";
  }
}

document.getElementById("collapse-toggle").onclick = () => {
  collapsed = !collapsed;
  applyCollapse();
};

</script>
</body>
</html>
"""

if __name__ == "__main__":
    logger.info("Starting Daily Planner")
    app.run(debug=True)










