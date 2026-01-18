# ==========================================================
# TEMPLATE – DAILY PLANNER (UNCHANGED, STABLE)
# ==========================================================
##PLANNER_TEMPLATE = """<-- SAME AS YOUR RESTORED VERSION, UNCHANGED -->"""

PLANNER_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: system-ui; background:#f6f7f9; padding:12px; padding-bottom:220px; }
.container { max-width:1100px; margin:auto; background:#fff; padding:16px; border-radius:14px; }
.header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
.header a { font-weight:600; text-decoration:none; }
.time { color:#2563eb; font-weight:700; }
.month-controls { display:flex; gap:8px; margin-bottom:12px; }
.day-strip { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
.day-btn {
  width:36px; height:36px;
  border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  border:1px solid #ddd;
  text-decoration:none; color:#000;
}
.day-btn.selected { background:#2563eb; color:#fff; }
.slot { border-bottom:1px solid #eee; padding-bottom:12px; margin-bottom:12px; }
.current { background:#eef2ff; border-left:4px solid #2563eb; padding-left:8px; }
textarea { width:100%; min-height:90px; font-size:15px; }
.floating-bar {
  position:fixed;
  bottom:0; left:0; right:0;
  background:#fff;
  border-top:1px solid #ddd;
  padding:10px;
  display:flex;
  gap:10px;
}
.floating-bar button { flex:1; padding:14px; font-size:16px; }
.habits {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.habits-card {
  background: #fff;
  border-radius: 12px;
  padding: 12px;
  margin-bottom: 16px;
}

.habit-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-right: 12px;
  font-size: 14px;
}

.habit-count {
  float: right;
  font-size: 12px;
  opacity: 0.6;
}
.reflection-card textarea {
  width: 100%;
  border-radius: 8px;
  padding: 10px;
  font-size: 14px;
  resize: vertical;
}
.soft-hint {
  font-size: 12px;
  opacity: 0.6;
  margin-top: 6px;
}
.card {
  background:#fff;
  border-radius:12px;
  padding:12px;
  margin-top:16px;
}
.checkin-btn {
  position: fixed;
  bottom: 140px;            /* above Save bar */
  right: 16px;
  padding: 12px 16px;
  border-radius: 999px;
  border: none;
  background: #2563eb;
  color: #fff;
  font-size: 14px;
  box-shadow: 0 6px 16px rgba(0,0,0,.2);
  z-index: 1000;
}

.checkin-drawer {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  max-height: 75vh;
  background: #fff;
  border-radius: 16px 16px 0 0;
  box-shadow: 0 -10px 30px rgba(0,0,0,.25);
  padding: 16px;
  overflow-y: auto;
  z-index: 1001;
}

.checkin-drawer.hidden {
  display: none;
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.drawer-header button {
  border: none;
  background: transparent;
  font-size: 18px;
}
.action-stack {
  position: fixed;
  right: 16px;
  bottom: 24px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  z-index: 1000;
}

.action-btn {
  padding: 12px 16px;
  border-radius: 999px;
  border: none;
  font-size: 14px;
  box-shadow: 0 6px 16px rgba(0,0,0,.2);
}

.save-btn {
  background: #16a34a; /* green */
  color: #fff;
}

.cancel-btn {
  background: #ef4444; /* red */
  color: #fff;
}
.header-date {
  color: #2563eb;
  font-weight: 700;
  font-size: 18px;
}
.header-top {
  display:flex;
  justify-content:space-between;
  align-items:center;
}

.header-nav {
  display:flex;
  gap:16px;
  margin-top:6px;
}
.mobile-header {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.header-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-nav {
  display: flex;
  justify-content: space-around;
  font-size: 18px;
}

.header-nav a {
  text-decoration: none;
}

@media (max-width: 600px) {
  .checkin-btn {
    bottom: 160px;
  }
}

</style>
</head>

<body>
<div class="container">
<div class="header mobile-header">

  <!-- Row 1: Date + Time -->
  <div class="header-top">
    <div class="date">{{ today }}</div>
    <div class="time">🕒 <span id="clock"></span> IST</div>
  </div>

  <!-- Row 2: Navigation icons -->
  <div class="header-nav">
    <a href="/" title="Planner">🗓</a>
    <a href="/todo" title="Eisenhower">📋</a>
    <a href="/summary" title="Daily Summary">📊</a>
    <a href="/summary?view=weekly" title="Weekly Summary">🗓️</a>
  </div>

</div>

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
  {{d.day}}
</a>
{% endfor %}
</div>

<form method="post" id="planner-form">
<input type="hidden" name="year" value="{{ year }}">
<input type="hidden" name="month" value="{{ month }}">
<input type="hidden" name="day" value="{{ selected_day }}">


<h3>🧠 Smart Planner Input</h3>
<textarea
  name="smart_plan"
  placeholder="One task per line.
Example:
Meeting with Renganathar @9am to 10am $Critical %Office #review
Workout @6am to 7am $High %Personal"
  style="width:100%; min-height:120px; margin-bottom:16px;"
></textarea>

<h3>🗒 Tasks (No Time Yet)</h3>

{% for t in untimed_tasks %}
<div class="untimed-item"
     data-id="{{ t.id }}"
     data-text="{{ t.text | e }}"
     style="padding:8px 0;border-bottom:1px solid #eee;">

  <div>{{ t.text }}</div>

  <button type="button" onclick="promoteUntimed(this)" data-id="{{ t.id }}">📋 Promote</button>
  <button type="button" onclick="scheduleUntimed('{{ t.id }}')">🕒 Schedule</button>
</div>
{% endfor %}

{% for slot in plans %}
<div class="slot {% if now_slot==slot %}current{% endif %}">
  <strong>{{ slot_labels[slot] }}</strong>
  <textarea name="plan_{{slot}}">{{ plans[slot].plan }}</textarea>
</div>
{% endfor %}
<!-- =========================
     DAILY CHECK-IN DRAWER
========================= -->
<div id="checkin-drawer" class="checkin-drawer hidden">
  <div class="drawer-header">
    <strong>🧭 Daily Check-in</strong>
    <button type="button" onclick="toggleCheckin()">✖</button>
  </div>

  <!-- HABITS -->
  <div class="card habits-card">
    <div class="card-header">
      <strong>Daily Habits</strong>
      <span class="habit-count">
        {{ habits|length }} / {{ habit_list|length }}
      </span>
    </div>

    <div class="habits">
      {% for habit in habit_list %}
        <label class="habit-item">
          <input
            type="checkbox"
            name="habits"
            value="{{ habit }}"
            {% if habit in habits %}checked{% endif %}
          >
          <span class="habit-icon">
            {{ habit_icons.get(habit, "•") }}
          </span>
          {{ habit }}
        </label>
      {% endfor %}
    </div>

    {% if habits|length == 0 %}
      <div class="soft-hint">⏳ No habits checked yet</div>
    {% endif %}
  </div>

  <!-- REFLECTION -->
  <div class="card reflection-card">
    <div class="card-header">
      <strong>Daily Reflection</strong>
    </div>

    <textarea
      name="reflection"
      rows="4"
      placeholder="What went well? What didn’t? Anything to note for tomorrow…"
    >{{ reflection }}</textarea>

    {% if not reflection %}
      <div class="soft-hint">✍️ A few lines are enough</div>
    {% endif %}
  </div>
</div>


</form>
</div>

<div class="action-stack">
  <button
    type="button"
    class="checkin-btn"
    onclick="toggleCheckin()">
    🧭 Check-in
  </button>

  <button
    type="submit"
    form="planner-form"
    class="action-btn save-btn"
    onclick="closeCheckinIfOpen()">
    💾 Save
  </button>

  <button
    type="button"
    class="action-btn cancel-btn"
    onclick="location.reload()">
    ❌ Cancel
  </button>
</div>

<button
  type="button"
  class="checkin-btn"
  onclick="toggleCheckin()">
  🧭 Check-in
</button>

<!-- MODAL -->
<div id="modal" style="
  position:fixed;
  inset:0;
  background:rgba(0,0,0,.35);
  display:none;
  align-items:center;
  justify-content:center;
  z-index:9999;">
  <div id="modal-content" style="background:#fff;padding:18px;width:340px;border-radius:14px;"></div>
</div>


<script>
const PLAN_DATE = "{{ plan_date }}";

function updateClock(){
  const ist = new Date(new Date().toLocaleString("en-US",{timeZone:"Asia/Kolkata"}));
  document.getElementById("clock").textContent = ist.toLocaleTimeString();
}
setInterval(updateClock,1000); updateClock();

/* PROMOTE */
function promoteUntimed(btn){
  const id = btn.dataset.id;
  const item = btn.closest(".untimed-item");
  const text = item.dataset.text;

  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");

  content.innerHTML =
    "<h3>📋 Promote Task</h3>" +
    "<div id='preview'></div><br>" +
    "<button onclick=\\"confirmPromote('" + id + "','Q1')\\">🔥 Do</button><br>" +
    "<button onclick=\\"confirmPromote('" + id + "','Q2')\\">📅 Schedule</button><br>" +
    "<button onclick=\\"confirmPromote('" + id + "','Q3')\\">🤝 Delegate</button><br>" +
    "<button onclick=\\"confirmPromote('" + id + "','Q4')\\">🗑 Eliminate</button><br><br>" +
    "<button onclick=\\"modal.style.display='none'\\">Cancel</button>";

  content.querySelector("#preview").textContent = text;
  modal.style.display = "flex";
}

function confirmPromote(id, quadrant){
  fetch("/untimed/promote",{
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body:JSON.stringify({ id, quadrant, plan_date: PLAN_DATE })
  }).then(()=>location.reload());
}

/* SCHEDULE */
function scheduleUntimed(id){
  const item = document.querySelector(".untimed-item[data-id='"+id+"']");
  const text = item.dataset.text;

  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");

  content.innerHTML =
    "<h3>🕒 Schedule Task</h3>" +
    "<div id='preview'></div><br>" +
    "<label>Date</label><input type='date' id='d' value='"+PLAN_DATE+"'><br><br>" +
    "<label>Start</label><input type='time' id='t'><br><br>" +
    "<label>Duration</label>" +
    "<select id='dur'><option value='1'>30m</option><option value='2'>1h</option></select><br><br>" +
    "<button onclick=\\"modal.style.display='none'\\">Cancel</button> " +
    "<button onclick=\\"confirmSchedule('" + id + "')\\">Continue</button>";

  content.querySelector("#preview").textContent = text;
  modal.style.display = "flex";
}

function confirmSchedule(id){
  const item = document.querySelector(".untimed-item[data-id='"+id+"']");
  const newText = item.dataset.text;
  const date = document.getElementById("d").value;
  const time = document.getElementById("t").value;
  const slots = parseInt(document.getElementById("dur").value,10);

  if(!time){ alert("Select time"); return; }

  const [h,m] = time.split(":").map(Number);
  const start_slot = Math.floor((h*60+m)/30)+1;

  fetch("/untimed/slot-preview",{
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body:JSON.stringify({ plan_date:date,start_slot,slot_count:slots })
  }).then(r=>r.json()).then(preview=>{
    const combined = preview.map(p=>p.existing?p.existing+"\\n---\\n"+newText:newText).join("\\n\\n");

    const modal = document.getElementById("modal");
    const content = document.getElementById("modal-content");

    content.innerHTML =
      "<h3>✏️ Confirm</h3>" +
      "<textarea id='finalText' style='width:100%;min-height:160px;'></textarea><br><br>" +
      "<button onclick=\\"modal.style.display='none'\\">Cancel</button> " +
      "<button onclick=\\"saveFinalSchedule('" + id + "','" + date + "',"+start_slot+","+slots+")\\">Save</button>";

    document.getElementById("finalText").value = combined;
  });
}

function saveFinalSchedule(id,date,start_slot,slots){
  fetch("/untimed/schedule",{
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body:JSON.stringify({
      id,
      plan_date:date,
      start_slot,
      slot_count:slots,
      final_text:document.getElementById("finalText").value
    })
  }).then(()=>location.reload());
}
function toggleCheckin(){
  const drawer = document.getElementById("checkin-drawer");
  drawer.classList.toggle("hidden");
}
function closeCheckinIfOpen(){
  const drawer = document.getElementById("checkin-drawer");
  if (drawer && !drawer.classList.contains("hidden")) {
    drawer.classList.add("hidden");
  }
}

</script>

</body>
</html>
"""
