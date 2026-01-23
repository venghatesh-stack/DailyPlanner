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
:root {
  --slot-height: 30px; /* desktop default */
}
html, body {
  height: 100%;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.container { max-width:1100px; margin:auto; background:#fff; padding:16px; border-radius:14px; }
.header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
.header a { font-weight:600; text-decoration:none; }
.time { color:#2563eb; font-weight:700; }
.month-controls { display:flex; gap:8px; margin-bottom:12px; }
.day-strip {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  overflow-y: hidden;
  scroll-behavior: smooth;
}

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
@media (max-width: 600px) {
  :root {
    --slot-height: 42px; /* try 40–48px */
  }

  .event-block {
    font-size: 15px;
    line-height: 1.35;
    padding: 10px;
  }
}


.event-block {
  pointer-events: auto;
  cursor: pointer;
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
.action-stack {
  z-index: 2000;
}

@media (max-width: 600px) {
  .checkin-btn {
    bottom: 160px;
  }
}
.streak-card {
  background: linear-gradient(135deg, #ecfeff, #f0fdf4);
  border-radius: 14px;
  padding: 14px;
  margin-bottom: 16px;
  border: 1px solid #e5e7eb;
}

.streak-count {
  font-size: 28px;
  font-weight: 800;
  color: #16a34a;
}

.streak-sub {
  font-size: 13px;
  opacity: 0.7;
}

.streak-broken {
  color: #ef4444;
}

.day-schedule {
  position: relative;
  min-height: calc(var(--slot-height) * {{ plans|length }});
}


.day-grid {
  position: relative;
}

.time-row {
  height: var(--slot-height);
  display: flex;
  align-items: center;
  box-sizing: border-box;
}

.time-column {
  width: 140px;
  flex-shrink: 0;
  font-size: 14px;
  color: #000;
}

.grid-line {
  flex: 1;
  height: 100%;
  border-bottom: 1px solid #eee;
}

.events-layer {
  position: absolute;
  top: 0;
  left: 140px; /* MUST match time-column width */
  right: 0;
  pointer-events: none;
}

.event-block {
  position: absolute;
  background: #dbeafe;
  border-left: 4px solid #2563eb;
  border-radius: 8px;
  padding: 8px;
  font-size: 14px;
  box-sizing: border-box;
  overflow:hidden;
  text-overflow:ellipsis;
  word-wrap:break-word;
  pointer-events: auto;
  cursor: pointer;
}

.date-strip {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 6px;
}

.date-pill {
  min-width: 52px;
  padding: 6px 8px;
  border-radius: 12px;
  text-align: center;
  text-decoration: none;
  color: #000;
  background: #f3f4f6;
  flex-shrink: 0;
}

.date-pill .dow {
  font-size: 11px;
  opacity: 0.6;
}

.date-pill .dom {
  font-size: 16px;
  font-weight: 600;
}

.date-pill.active {
  background: #2563eb;
  color: #fff;
}
html {
  scroll-behavior: smooth;
  overflow-anchor: none;
}
/* Space for fixed bottom actions */
:root {
  --action-bar-height: 190px;
}

body {
  padding-bottom: calc(
    var(--action-bar-height) + env(safe-area-inset-bottom)
  );
}
/* Prevent scroll chaining on mobile */
.checkin-drawer,
#summary-content {
  overscroll-behavior: contain;
}

</style>
</head>

<body>
<div class="container">
  <div class="header mobile-header">

    <!-- Row 1: Date + Time -->
    <div class="header-top">
      <div class="date">{{ today_display }}</div>
      <div class="time">🕒 <span id="clock"></span> IST</div>
    </div>

    <!-- Row 2: Navigation icons -->
    <div class="header-nav">
        <a href="/" title="Planner">🏠</a>

        <a href="/todo" title="Eisenhower Matrix">
          🎯
        </a>

        <button type="button" onclick="openSummary()" title="Daily Summary">
          📝
        </button>

        <a href="/summary?view=weekly" title="Weekly Summary">
          📆
        </a>
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

    <div class="date-strip" id="dateStrip">
      {% for d in days %}
        <a
          href="/?year={{year}}&month={{month}}&day={{d.day}}"
          class="date-pill {% if d.day==selected_day %}active{% endif %}"
          {% if d.day==selected_day %}id="selected-day"{% endif %}
        >
          <div class="dow">{{ d.strftime('%a') }}</div>
          <div class="dom">{{ d.day }}</div>
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

    <!-- ========================= -->
    <!-- PHASE B: DAY SCHEDULE -->
    <!-- ========================= -->

    <!-- ========================= -->
<!-- DAY SCHEDULE -->
<!-- ========================= -->

<h3>📅 Day Schedule</h3>

<div class="day-schedule">


  <!-- Time grid -->
  <div class="day-grid">
    {% for slot in plans %}
      <div class="time-row">
      {% if now_slot and slot == now_slot %}id="now-slot"{% endif %}>
        <div class="time-column">
          {{ slot_labels[slot] }}
        </div>
        <div class="grid-line"></div>
      </div>
    {% endfor %}
  </div>

  <!-- Event blocks overlay -->
  <div class="events-layer">
    {% for block in blocks %}
      <div class="event-block"
          onclick="editEvent({{ block.start_slot }}, {{ block.end_slot }})"
          style="
            top: calc({{ block.start_slot - 1 }} * var(--slot-height));
            height: calc({{ block.end_slot - block.start_slot + 1 }} * var(--slot-height));

          ">
         {% if block.recurring_id %}🔁 {% endif %}
         {{ block.text }}
        </div>
    {% endfor %}
  </div>

</div>



    <!-- Legacy hidden slot inputs (DO NOT REMOVE YET) -->
    <div style="display:none">
      {% for slot in plans %}
        <textarea name="plan_{{slot}}">{{ plans[slot].plan }}</textarea>
      {% endfor %}
    </div>

    
  

    <!-- HEALTH STREAK -->
    <div class="streak-card">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <strong>🔥 Health Streak</strong>

        {% if health_streak > 0 %}
          <span class="streak-count">{{ health_streak }} days</span>
        {% else %}
          <span class="streak-count streak-broken">0</span>
        {% endif %}
      </div>

      <div class="streak-sub">
        {% if streak_active_today %}
          ✅ Streak active today
        {% else %}
          ⚠️ Complete {{ min_health_habits }} health habits to continue
        {% endif %}
      </div>
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
<div id="summary-modal" style="
  position:fixed;
  inset:0;
  background:rgba(0,0,0,.35);
  display:none;
  align-items:center;
  justify-content:center;
  z-index:9999;">
  <div style="background:#fff;padding:18px;width:90%;max-width:420px;border-radius:14px;">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <h3 style="margin:0">📊 Daily Summary</h3>
      <button onclick="closeSummary()" style="
        border:none;
        background:none;
        font-size:18px;
        cursor:pointer">
        ✖
      </button>
    </div>

<div id="summary-content" style="
  margin-top:12px;
  max-height:65vh;
  overflow-y:auto;
">
</div> <!-- CLOSE summary-content -->

</div>
</div>


<script>
const PLAN_DATE = "{{ plan_date.isoformat() }}";

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
function openSummary() {
  fetch(`/summary?date=${PLAN_DATE}`)
    .then(r => r.text())
    .then(html => {
      document.getElementById("summary-content").innerHTML = html;
      document.getElementById("summary-modal").style.display = "flex";
    })
    .catch(err => {
      document.getElementById("summary-content").innerHTML =
        "<p style='color:red'>Failed to load summary</p>";
      document.getElementById("summary-modal").style.display = "flex";
      console.error(err);
    });
}


function closeSummary(){
  document.getElementById("summary-modal").style.display = "none";
}

</script>
<script>
/* ESC to close Daily Summary */
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") {
    const modal = document.getElementById("summary-modal");
    if (modal && modal.style.display === "flex") {
      closeSummary();
    }
  }
});
</script>
<script>
let touchStartY = null;
let isAtTop = false;

const summaryModal = document.getElementById("summary-modal");
const summaryContent = document.getElementById("summary-content");

summaryModal.addEventListener("touchstart", function (e) {
  if (e.touches.length !== 1) return;

  touchStartY = e.touches[0].clientY;
  isAtTop = summaryContent.scrollTop === 0;
});

summaryModal.addEventListener("touchmove", function (e) {
  if (!touchStartY || !isAtTop) return;

  const currentY = e.touches[0].clientY;
  const deltaY = currentY - touchStartY;

  // close only if pulled down from top
  if (deltaY > 80) {
    closeSummary();
    touchStartY = null;
  }
});

summaryModal.addEventListener("touchend", function () {
  touchStartY = null;
});
</script>

<script>
function syncHabit(cb) {
  const main = document.querySelector(
    'input[name="habits"][value="'+cb.dataset.habit+'"]'
  );
  if (main) main.checked = cb.checked;
}

function syncReflection(el) {
  const main = document.querySelector('textarea[name="reflection"]');
  if (main) main.value = el.value;
}
</script>
<script>
function editEvent(startSlot, endSlot) {
  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");

  // Collect text from the first slot (authoritative)
  fetch(`/slot/get?date=${PLAN_DATE}&slot=${startSlot}`)
    .then(r => r.json())
    .then(data => {
      content.innerHTML = `
        <h3>✏️ Edit Event</h3>
        <textarea id="editText" style="width:100%;min-height:140px;">
${data.text}
        </textarea><br><br>

        <button onclick="modal.style.display='none'">Cancel</button>
        <button onclick="saveEvent(${startSlot},${endSlot})">Save</button>
      `;
      modal.style.display = "flex";
    });
}

function saveEvent(startSlot, endSlot) {
  const text = document.getElementById("editText").value;

  fetch("/slot/update", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      plan_date: PLAN_DATE,
      start_slot: startSlot,
      end_slot: endSlot,
      text
    })
  }).then(() => location.reload());
}
</script>
<script>
document.addEventListener("DOMContentLoaded", () => {
  const selected = document.getElementById("selected-day");
  if (!selected) return;

  requestAnimationFrame(() => {
    selected.scrollIntoView({
      behavior: "smooth",
      inline: "center",
      block: "nearest"
    });
  });
});
</script>



<div id="checkin-drawer" class="checkin-drawer hidden">
  <div class="drawer-header">
    <strong>🧭 Daily Check-in</strong>
    <button type="button" onclick="toggleCheckin()">✖</button>
  </div>

  <p class="soft-hint">
    Make quick updates. Tap Save to persist.
  </p>

  <div class="section">
    <strong>Habits</strong>
    <div class="habits">
      {% for habit in habit_list %}
        <label class="habit-item">
          <input type="checkbox"
                 data-habit="{{ habit }}"
                 {% if habit in habits %}checked{% endif %}
                 onchange="syncHabit(this)">
          {{ habit }}
        </label>
      {% endfor %}
    </div>
  </div>

  <div class="section">
    <strong>Reflection</strong>
    <textarea
      rows="4"
      oninput="syncReflection(this)"
    >{{ reflection }}</textarea>
  </div>
</div>



</body>
</html>
"""
