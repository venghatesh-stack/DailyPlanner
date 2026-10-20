"use strict";

/* ═══════════════════════════════════════════════════════════════════
   PLANNER V2 — Google Calendar-style Day / 3-Day / Week planner
   ═══════════════════════════════════════════════════════════════════ */

/* ──────────────────────────
   CONSTANTS
   ────────────────────────── */
const HOUR_HEIGHT = 60;   // px per hour
const SNAP = 15;          // 15-minute snap grid (matches Google Calendar)

/* Live time badge shown during drag-to-create / drag-to-move so the user
   can see exactly where the event will land before releasing. Created
   lazily on first use and reused across every drag. */
let _dragTimeBadge = null;
function _ensureDragBadge() {
  if (_dragTimeBadge && document.body.contains(_dragTimeBadge)) return _dragTimeBadge;
  _dragTimeBadge = document.createElement("div");
  _dragTimeBadge.className = "drag-time-badge";
  document.body.appendChild(_dragTimeBadge);
  return _dragTimeBadge;
}
function _showDragBadge(text, clientX, clientY) {
  const el = _ensureDragBadge();
  el.textContent = text;
  el.style.display = "block";
  // Position slightly above-right of the cursor so the badge doesn't
  // cover the snap line or the pointer itself.
  const pad = 14;
  const w = el.offsetWidth || 120;
  const x = Math.min(window.innerWidth - w - 8, clientX + pad);
  const y = Math.max(8, clientY - 36);
  el.style.left = x + "px";
  el.style.top  = y + "px";
}
function _hideDragBadge() {
  if (_dragTimeBadge) _dragTimeBadge.style.display = "none";
}
function _fmtTimeLabel(mins) {
  // 15:30 → "3:30 PM" — more readable than 24h in a fleeting badge
  mins = _clampMinutes(mins);
  const h24 = Math.floor(mins / 60);
  const m = mins % 60;
  const h12 = ((h24 + 11) % 12) + 1;
  const ampm = h24 < 12 ? "AM" : "PM";
  return `${h12}:${String(m).padStart(2,"0")} ${ampm}`;
}
function _fmtDurLabel(mins) {
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}
const TOTAL_HOURS = 24;
const GRID_HEIGHT = HOUR_HEIGHT * TOTAL_HOURS;

/* ──────────────────────────
   STATE
   ────────────────────────── */
let currentDate = getISTDate();          // YYYY-MM-DD anchor
let currentView = "day";                 // "day" | "3day" | "week"
let eventsMap = new Map();               // date-string -> array of events
let floatingTasks = [];
let selected = null;                     // event being edited
let popoverEvent = null;                 // event shown in popover
let draggedTask = null;
let snapLine = null;

// Drag-to-create state
let creatingEvent = false;
let pendingCreate = false;
let createStartY = 0;
let createStartX = 0;
let createColDate = null;
let ghostEvent = null;

// Mini-cal state
let miniCalMonth = null;   // Date object for displayed month
let miniCalYear = null;

// Current-time timer
let timeLineInterval = null;

/* ══════════════════════════════════════════════════════════════
   1. TIME / DATE HELPERS
   ══════════════════════════════════════════════════════════════ */

function getISTNow() {
  return new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" })
  );
}

function getISTDate() {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

function formatTime(t) {
  if (!t) return "";
  return t.slice(0, 5);
}

function minutes(t) {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

function toTime(mins) {
  mins = Math.max(0, Math.min(1439, mins));
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

// Clamp a column-local y-coordinate into the grid's valid range so
// a pointer captured above the column or past midnight can't produce
// negative or out-of-day time offsets. The grid is 24 * HOUR_HEIGHT
// tall — anything outside that is clipped.
function _clampColY(y) {
  if (typeof HOUR_HEIGHT !== "number" || !HOUR_HEIGHT) return Math.max(0, y);
  const max = 24 * HOUR_HEIGHT - 1;
  return Math.min(max, Math.max(0, y));
}
function _clampMinutes(m) {
  return Math.max(0, Math.min(1439, m));
}

function calculateEndTime(start, duration) {
  return toTime(minutes(start) + parseInt(duration));
}

function normalizeDuration(mins) {
  const allowed = [15, 30, 45, 60, 90, 120];
  for (const d of allowed) {
    if (mins <= d) return d;
  }
  return 120;
}

function formatHour(hour) {
  if (hour === 0) return "12 AM";
  if (hour < 12) return `${hour} AM`;
  if (hour === 12) return "12 PM";
  return `${hour - 12} PM`;
}

function formatTimeRange(start, end) {
  return `${formatTime12(start)} - ${formatTime12(end)}`;
}

function formatTime12(t) {
  if (!t) return "";
  const [h, m] = t.split(":").map(Number);
  const ampm = h < 12 ? "AM" : "PM";
  const h12 = h % 12 || 12;
  return m === 0 ? `${h12} ${ampm}` : `${h12}:${String(m).padStart(2, "0")} ${ampm}`;
}

/** Parse "YYYY-MM-DD" into a local Date (no timezone shift). */
function parseLocalDate(str) {
  const [y, m, d] = str.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** Format a Date to "YYYY-MM-DD". */
function dateToStr(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Add days to a YYYY-MM-DD string, return new YYYY-MM-DD. */
function addDays(dateStr, n) {
  const d = parseLocalDate(dateStr);
  d.setDate(d.getDate() + n);
  return dateToStr(d);
}

/** Get Monday of the week containing dateStr. */
function getMonday(dateStr) {
  const d = parseLocalDate(dateStr);
  const day = d.getDay(); // 0=Sun
  const diff = (day === 0 ? -6 : 1 - day);
  d.setDate(d.getDate() + diff);
  return dateToStr(d);
}

/* ══════════════════════════════════════════════════════════════
   2. VISIBLE DATES CALCULATION
   ══════════════════════════════════════════════════════════════ */

function getVisibleDates() {
  if (currentView === "day") {
    return [currentDate];
  }
  if (currentView === "3day") {
    return [currentDate, addDays(currentDate, 1), addDays(currentDate, 2)];
  }
  // week: Mon-Sun
  const monday = getMonday(currentDate);
  const dates = [];
  for (let i = 0; i < 7; i++) {
    dates.push(addDays(monday, i));
  }
  return dates;
}

/* ══════════════════════════════════════════════════════════════
   3. VIEW SWITCHING / NAVIGATION
   ══════════════════════════════════════════════════════════════ */

function setView(view) {
  currentView = view;

  // Update button active state
  document.querySelectorAll(".view-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.view === view);
  });

  // Set body data attribute for CSS
  document.body.dataset.view = view;

  buildGrid();
  loadAllEvents();
}

function changeDate(delta) {
  if (currentView === "day") {
    currentDate = addDays(currentDate, delta);
  } else if (currentView === "3day") {
    currentDate = addDays(currentDate, delta * 3);
  } else {
    currentDate = addDays(currentDate, delta * 7);
  }
  buildGrid();
  loadAllEvents();
}

function goToday() {
  currentDate = getISTDate();
  buildGrid();
  loadAllEvents();
  setTimeout(scrollToNow, 300);
}

/* ══════════════════════════════════════════════════════════════
   4. HEADER TITLE
   ══════════════════════════════════════════════════════════════ */

function updateHeaderTitle() {
  const el = document.getElementById("header-title");
  if (!el) return;

  const d = parseLocalDate(currentDate);
  const months = ["January","February","March","April","May","June",
                  "July","August","September","October","November","December"];
  const monthsShort = ["Jan","Feb","Mar","Apr","May","Jun",
                       "Jul","Aug","Sep","Oct","Nov","Dec"];

  if (currentView === "day") {
    el.textContent = `${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
  } else if (currentView === "3day") {
    const end = parseLocalDate(addDays(currentDate, 2));
    if (d.getMonth() === end.getMonth()) {
      el.textContent = `${monthsShort[d.getMonth()]} ${d.getDate()} - ${end.getDate()}, ${d.getFullYear()}`;
    } else {
      el.textContent = `${monthsShort[d.getMonth()]} ${d.getDate()} - ${monthsShort[end.getMonth()]} ${end.getDate()}, ${d.getFullYear()}`;
    }
  } else {
    el.textContent = `${monthsShort[d.getMonth()]} ${d.getFullYear()}`;
  }
}

/* ══════════════════════════════════════════════════════════════
   5. GRID BUILDING (columns, headers, time gutter)
   ══════════════════════════════════════════════════════════════ */

function buildGrid() {
  const dates = getVisibleDates();
  const today = getISTDate();

  updateHeaderTitle();
  buildDayHeaders(dates, today);
  buildTimeGutter();
  buildColumns(dates, today);
  renderMiniCal();
}

function buildDayHeaders(dates, today) {
  const container = document.getElementById("day-headers");
  if (!container) return;

  const dayNames = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];

  container.innerHTML = dates.map(ds => {
    const d = parseLocalDate(ds);
    const isToday = ds === today;
    return `<div class="gcal-day-header ${isToday ? "today" : ""}" data-date="${ds}">
      <span class="day-name">${dayNames[d.getDay()]}</span>
      <span class="day-number ${isToday ? "today-number" : ""}">${d.getDate()}</span>
    </div>`;
  }).join("");
}

function buildTimeGutter() {
  const gutter = document.getElementById("time-gutter");
  if (!gutter) return;

  gutter.innerHTML = "";
  gutter.style.height = GRID_HEIGHT + "px";

  for (let hour = 0; hour < TOTAL_HOURS; hour++) {
    const label = document.createElement("div");
    label.className = "hour-label";
    label.style.top = (hour * HOUR_HEIGHT) + "px";
    label.textContent = hour === 0 ? "" : formatHour(hour);
    gutter.appendChild(label);
  }
}

function buildColumns(dates, today) {
  const container = document.getElementById("gcal-columns");
  if (!container) return;

  container.innerHTML = "";

  dates.forEach(ds => {
    const col = document.createElement("div");
    col.className = "gcal-day-col";
    col.dataset.date = ds;
    if (ds === today) col.classList.add("today");

    col.style.height = GRID_HEIGHT + "px";

    // Hour lines
    for (let hour = 0; hour < TOTAL_HOURS; hour++) {
      const line = document.createElement("div");
      line.className = "hour-line";
      line.style.top = (hour * HOUR_HEIGHT) + "px";
      col.appendChild(line);
    }

    // Drag-and-drop listeners (desktop)
    col.addEventListener("dragover", onColumnDragOver);
    col.addEventListener("dragleave", onColumnDragLeave);
    col.addEventListener("drop", onColumnDrop);

    // Drag-to-create (pointer)
    col.addEventListener("pointerdown", onColumnPointerDown);

    container.appendChild(col);
  });

  // Render the current-time line
  renderCurrentTimeLine();
}

/* ══════════════════════════════════════════════════════════════
   6. DATA LOADING
   ══════════════════════════════════════════════════════════════ */

async function loadAllEvents() {
  const dates = getVisibleDates();
  eventsMap.clear();

  // Fetch all dates in parallel — each date fetches independently
  const fetches = dates.map(async (ds) => {
    let eventData = [];
    let taskData = [];

    try {
      const evRes = await fetch(`/api/v2/events?date=${ds}`);
      if (evRes.ok) eventData = await evRes.json();
    } catch (e) { console.warn("Events fetch failed for", ds, e); }

    try {
      const taskRes = await fetch(`/api/v2/project-tasks?date=${ds}`);
      if (taskRes.ok) {
        const raw = await taskRes.json();
        taskData = Array.isArray(raw) ? raw : [];
      }
    } catch (e) { console.warn("Tasks fetch failed for", ds, e); }

    // A timed task belongs to ONE day: the plan_date that drag-to-schedule
    // sets alongside start_time. The endpoint's filter is
    // `due_date is null OR due_date <= date`, which is right for the
    // unscheduled backlog below but wrong here — without the plan_date
    // check a task scheduled for 9am Monday drew a chip at 9am on Tuesday,
    // Wednesday and every day after, until it was marked done.
    // Tasks with no plan_date keep the old behaviour so nothing that was
    // scheduled before this fix silently vanishes off the grid.
    //
    // AND THEN DEDUPE AGAINST THE EVENTS. A prep topic scheduled from a
    // study page writes BOTH a calendar event and a project task, on
    // purpose: the event is what the grid draws, the task is what the
    // project list and the todo show — and the task needs to keep its time
    // or the todo entry is useless. Without this filter both are drawn and
    // the same topic appears on the day twice, which is what "repeating
    // twice" was. Matching on title + start time is enough because that is
    // exactly what the scheduler writes to both rows.
    const evKeys = new Set(
      eventData.map(e => (e.title || "").trim().toLowerCase() + "|" + (e.start_time || ""))
    );
    const timedTasks = taskData.filter(
      t => t.start_time
        && (!t.plan_date || t.plan_date === ds)
        && !evKeys.has((t.task_text || "").trim().toLowerCase() + "|" + t.start_time)
    );

    const combined = [
      ...eventData.map(e => ({ ...e, type: "event" })),
      ...timedTasks.map(t => ({
        ...t,
        task_id: t.task_id,
        title: t.task_text,
        end_time: calculateEndTime(t.start_time, 30),
        type: "project",
        priority: t.priority || "medium",
        is_recurring: !!t.is_recurring,
        recurrence_type: t.recurrence_type || null
      }))
    ];

    eventsMap.set(ds, combined);

    if (ds === currentDate) {
      floatingTasks = taskData;
    }
  });

  await Promise.all(fetches);
  renderAllColumns();
  renderFloatingTasks(floatingTasks);
  renderMiniCal();
}

/* ══════════════════════════════════════════════════════════════
   7. EVENT RENDERING
   ══════════════════════════════════════════════════════════════ */

function renderAllColumns() {
  const dates = getVisibleDates();

  dates.forEach(ds => {
    const col = document.querySelector(`.gcal-day-col[data-date="${ds}"]`);
    if (!col) return;

    // Remove old event chips
    col.querySelectorAll(".event-chip").forEach(c => c.remove());

    const dayEvents = eventsMap.get(ds) || [];
    if (!dayEvents.length) return;

    const positioned = computeLayout(dayEvents);

    positioned.forEach(ev => {
      const chip = document.createElement("div");
      chip.className = "event-chip";
      chip.dataset.id = ev.id || ev.task_id;
      chip.dataset.type = ev.type;

      // Priority class
      if (ev.type === "project") {
        chip.classList.add("p-project");
      } else {
        chip.classList.add(`p-${ev.priority || "medium"}`);
      }

      /* MISSED: the slot has gone by and nothing marked it done.
         Shading it is the whole point of looking at a past day — an
         unmarked chip that looks identical to a future one tells you
         nothing about whether the day actually happened.

         MEASURED FROM THE END, NOT THE START. An event running 19:00-20:00
         is not missed at 19:01; it is missed at 20:00. Where no end time is
         recorded the start is used, since that is all that is known.

         `done` is the only status treated as complete — anything else
         (open, or absent) is still outstanding. */
      const _endsAt = ev.end_time || ev.start_time;
      if (_endsAt && (ev.status || "open") !== "done") {
        const [_h, _m] = String(_endsAt).split(":");
        const _p = ds.split("-");
        const _due = new Date(+_p[0], +_p[1] - 1, +_p[2], +_h || 0, +_m || 0, 0, 0);
        if (_due.getTime() < Date.now()) chip.classList.add("is-missed");
      }

      // Position
      chip.style.top = ev.top + "px";
      chip.style.height = Math.max(ev.height, 18) + "px";
      chip.style.left = `calc(${ev.left}% + 2px)`;
      chip.style.width = `calc(${ev.width}% - 4px)`;

      // Content
      const timeStr = formatTime(ev.start_time);
      const title = ev.task_text || ev.title || "";
      const isSmall = ev.height < 36;
      const qBadge = ev.quadrant ? `<span class="chip-quadrant cq-${ev.quadrant}">${ev.quadrant}</span>` : "";
      const recurBadge = ev.is_recurring
        ? `<span class="chip-recur" title="Repeats${ev.recurrence_type ? ' (' + ev.recurrence_type + ')' : ''}">🔁</span>`
        : "";
      const prioDot = ev.type === "project"
        ? `<span class="chip-prio-dot prio-${ev.priority || 'medium'}" title="${(ev.priority || 'medium').toUpperCase()} priority"></span>`
        : "";

      if (isSmall) {
        chip.innerHTML = `<span class="chip-title">${prioDot}${recurBadge} ${qBadge} ${timeStr} ${title}</span>`;
      } else {
        chip.innerHTML = `
          <div class="chip-time">${prioDot}${recurBadge} ${timeStr} ${qBadge}</div>
          <div class="chip-title">${title}</div>
        `;
      }

      // Click -> popover
      chip.addEventListener("click", (e) => {
        e.stopPropagation();
        showPopover(ev, chip, ds);
      });

      // Drag to move (desktop)
      chip.draggable = true;
      chip.addEventListener("dragstart", (e) => {
        draggedTask = { ...ev, _sourceDate: ds };
        e.dataTransfer.effectAllowed = "move";
        // Make chip semi-transparent during drag
        setTimeout(() => chip.style.opacity = "0.4", 0);
      });
      chip.addEventListener("dragend", () => {
        chip.style.opacity = "";
      });

      // Touch drag for mobile
      attachChipTouchDrag(chip, ev, ds);

      col.appendChild(chip);
    });
  });

  // Re-render current time line
  renderCurrentTimeLine();
}

/* ──────────────────────────
   Layout Engine (overlap columns)
   ────────────────────────── */
function computeLayout(events) {
  if (!events.length) return [];

  const enriched = events
    .filter(ev => ev.start_time)
    .map(ev => {
      const start = minutes(ev.start_time);
      const end = minutes(ev.end_time);
      return {
        ...ev,
        _start: start,
        _end: end,
        top: (start / 60) * HOUR_HEIGHT,
        height: ((end - start) / 60) * HOUR_HEIGHT
      };
    });

  enriched.sort((a, b) => a._start - b._start || a._end - b._end);

  // Build overlap clusters
  // Adjacent events (end === start) are NOT overlapping — use strict < / >
  const clusters = [];
  enriched.forEach(ev => {
    let placed = false;
    for (const cluster of clusters) {
      if (cluster.some(e => ev._start < e._end && ev._end > e._start)) {
        cluster.push(ev);
        placed = true;
        break;
      }
    }
    if (!placed) clusters.push([ev]);
  });

  // Assign columns within each cluster
  clusters.forEach(cluster => {
    const columns = [];
    cluster.forEach(ev => {
      let placed = false;
      for (let i = 0; i < columns.length; i++) {
        const last = columns[i][columns[i].length - 1];
        if (ev._start >= last._end) { // adjacent (start === end) fits in same column
          columns[i].push(ev);
          ev._col = i;
          placed = true;
          break;
        }
      }
      if (!placed) {
        columns.push([ev]);
        ev._col = columns.length - 1;
      }
    });

    const totalCols = columns.length;
    cluster.forEach(ev => {
      if (totalCols === 1) {
        ev.width = 100;
        ev.left = 0;
      } else {
        ev.width = 100 / totalCols;
        ev.left = ev._col * ev.width;
      }
    });
  });

  return enriched;
}

/* ══════════════════════════════════════════════════════════════
   8. CURRENT TIME LINE
   ══════════════════════════════════════════════════════════════ */

function renderCurrentTimeLine() {
  // Remove existing
  document.querySelectorAll(".current-time-line").forEach(el => el.remove());

  const today = getISTDate();
  const col = document.querySelector(`.gcal-day-col[data-date="${today}"]`);
  if (!col) return;

  const now = getISTNow();
  const minutesNow = now.getHours() * 60 + now.getMinutes();
  const top = (minutesNow / 60) * HOUR_HEIGHT;

  const line = document.createElement("div");
  line.className = "current-time-line";
  line.style.top = top + "px";

  // Red dot
  const dot = document.createElement("div");
  dot.className = "current-time-dot";
  line.appendChild(dot);

  col.appendChild(line);
}

function startTimeLineUpdater() {
  if (timeLineInterval) clearInterval(timeLineInterval);
  timeLineInterval = setInterval(renderCurrentTimeLine, 60000);
}

/* ══════════════════════════════════════════════════════════════
   9. AUTO-SCROLL
   ══════════════════════════════════════════════════════════════ */

function scrollToNow() {
  const scroll = document.getElementById("gcal-scroll");
  if (!scroll) return;
  const now = getISTNow();
  const top = (now.getHours() * 60 + now.getMinutes()) / 60 * HOUR_HEIGHT;
  scroll.scrollTo({ top: Math.max(0, top - 200), behavior: "smooth" });
}

function scrollTo7AM() {
  const scroll = document.getElementById("gcal-scroll");
  if (!scroll) return;

  // 7am is a sensible default for a day that starts in the morning, and it
  // was silently HIDING anything scheduled before it. Study topics booked
  // with no time land at 00:00 — deliberately, so they sit at the top of
  // the day the way an all-day row does — and 00:00 is seven hours above
  // this scroll position, so the calendar looked empty while the entries
  // were there the whole time.
  //
  // So: start at 7am, unless the day actually has something earlier, in
  // which case start just above THAT.
  let earliest = 7 * 60;
  (eventsMap.get(currentDate) || []).forEach(ev => {
    const m = minutes(ev.start_time);
    if (typeof m === "number" && !isNaN(m) && m < earliest) earliest = m;
  });
  scroll.scrollTop = Math.max(0, (earliest / 60) * HOUR_HEIGHT - 20);
}

/* ══════════════════════════════════════════════════════════════
   10. MINI CALENDAR
   ══════════════════════════════════════════════════════════════ */

function renderMiniCal() {
  const container = document.getElementById("mini-cal");
  if (!container) return;

  const anchor = parseLocalDate(currentDate);
  if (miniCalMonth === null) {
    miniCalMonth = anchor.getMonth();
    miniCalYear = anchor.getFullYear();
  }

  const today = getISTDate();
  const dayNames = ["Mo","Tu","We","Th","Fr","Sa","Su"];

  // First day of month
  const first = new Date(miniCalYear, miniCalMonth, 1);
  let startDay = first.getDay(); // 0=Sun
  startDay = startDay === 0 ? 6 : startDay - 1; // Convert to Mon=0

  const daysInMonth = new Date(miniCalYear, miniCalMonth + 1, 0).getDate();

  const monthNames = ["January","February","March","April","May","June",
                      "July","August","September","October","November","December"];

  let html = `<div class="mini-cal-header">
    <button class="mini-cal-nav" onclick="miniCalNav(-1)"><i data-feather="chevron-left"></i></button>
    <span class="mini-cal-title">${monthNames[miniCalMonth]} ${miniCalYear}</span>
    <button class="mini-cal-nav" onclick="miniCalNav(1)"><i data-feather="chevron-right"></i></button>
  </div>`;

  html += `<div class="mini-cal-grid">`;
  dayNames.forEach(dn => {
    html += `<div class="mini-cal-dayname">${dn}</div>`;
  });

  // Empty cells before first day
  for (let i = 0; i < startDay; i++) {
    html += `<div class="mini-cal-day empty"></div>`;
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const ds = `${miniCalYear}-${String(miniCalMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const isToday = ds === today;
    const isSelected = ds === currentDate;
    const classes = ["mini-cal-day"];
    if (isToday) classes.push("today");
    if (isSelected) classes.push("selected");

    html += `<div class="${classes.join(" ")}" onclick="miniCalSelect('${ds}')">${d}</div>`;
  }

  html += `</div>`;

  container.innerHTML = html;

  if (window.feather) feather.replace();
}

function miniCalNav(delta) {
  miniCalMonth += delta;
  if (miniCalMonth < 0) { miniCalMonth = 11; miniCalYear--; }
  if (miniCalMonth > 11) { miniCalMonth = 0; miniCalYear++; }
  renderMiniCal();
}

function miniCalSelect(dateStr) {
  currentDate = dateStr;
  const d = parseLocalDate(dateStr);
  miniCalMonth = d.getMonth();
  miniCalYear = d.getFullYear();
  buildGrid();
  loadAllEvents();
}

/* ══════════════════════════════════════════════════════════════
   11. EVENT POPOVER
   ══════════════════════════════════════════════════════════════ */

function showPopover(ev, chipEl, dateStr) {
  closePopover();
  popoverEvent = { ...ev, _date: dateStr };

  const popover = document.getElementById("event-popover");
  if (!popover) return;

  // Fill content
  const dot = document.getElementById("popover-dot");
  const pClass = ev.type === "project" ? "project" : (ev.priority || "medium");
  dot.className = `popover-color-dot p-${pClass}`;

  document.getElementById("popover-title").textContent = ev.task_text || ev.title || "";
  document.getElementById("popover-time").textContent = formatTimeRange(ev.start_time, ev.end_time);
  renderLinkedText(document.getElementById("popover-desc"), ev.description || ev.notes || "");

  // On mobile, let CSS render the popover as a bottom-sheet (see planner_v2.css @media).
  // Clear any inline positioning from a previous desktop-view invocation.
  const isMobile = window.matchMedia("(max-width: 768px)").matches;
  if (isMobile) {
    popover.style.top = "";
    popover.style.left = "";
    popover.classList.remove("hidden");
  } else {
    // Position near chip (desktop)
    const rect = chipEl.getBoundingClientRect();
    popover.style.top = (rect.top + window.scrollY) + "px";
    popover.style.left = (rect.right + 8) + "px";
    popover.classList.remove("hidden");

    // Adjust if offscreen right
    requestAnimationFrame(() => {
      const pr = popover.getBoundingClientRect();
      if (pr.right > window.innerWidth - 10) {
        popover.style.left = (rect.left - pr.width - 8) + "px";
      }
      if (pr.bottom > window.innerHeight - 10) {
        popover.style.top = (window.innerHeight - pr.height - 10 + window.scrollY) + "px";
      }
    });
  }

  if (window.feather) feather.replace();
}

function closePopover() {
  const popover = document.getElementById("event-popover");
  if (popover) popover.classList.add("hidden");
  popoverEvent = null;
}

function editFromPopover() {
  if (!popoverEvent) return;
  const ev = popoverEvent;
  closePopover();
  if (ev.type === "project") {
    openTaskCard(ev.task_id);
  } else {
    openModal(ev);
  }
}

function deleteFromPopover() {
  if (!popoverEvent) return;
  const ev = popoverEvent;
  closePopover();

  if (ev.type === "project") {
    // Cannot delete project tasks from here; open task card instead
    openTaskCard(ev.task_id);
    return;
  }

  deleteEventById(ev.id);
}

/* ══════════════════════════════════════════════════════════════
   12. EVENT MODAL (create / edit)
   ══════════════════════════════════════════════════════════════ */

function openCreateModal(prefillDate, prefillStart, prefillEnd) {
  hideConflict();
  selected = null;

  document.getElementById("modal-title").textContent = "New Event";
  document.getElementById("start-time").value = prefillStart || "";
  document.getElementById("end-time").value = prefillEnd || (prefillStart ? toTime(minutes(prefillStart) + 30) : "");
  _refreshAllTimePillDisplays();
  document.getElementById("event-priority").value = "medium";
  document.getElementById("event-title").value = "";
  document.getElementById("event-desc").value = "";

  // Reset reminder
  const select = document.getElementById("reminder-select");
  const custom = document.getElementById("custom-reminder");
  select.value = "10";
  custom.value = "";
  custom.style.display = "none";

  // Reset quadrant
  document.querySelectorAll(".quad-btn").forEach(b => b.classList.remove("active"));
  document.querySelector('.quad-btn[data-q=""]')?.classList.add("active");

  // Reset recurrence
  const ruleSel = document.getElementById("recurrence-rule");
  if (ruleSel) {
    ruleSel.value = "";
    document.querySelectorAll("#recurrence-days input[type=checkbox]").forEach(cb => cb.checked = false);
    document.getElementById("recurrence-end-mode").value = "never";
    document.getElementById("recurrence-end-date").value = "";
    document.getElementById("recurrence-end-count").value = "";
    onRecurrenceRuleChange();
  }

  // Hide delete button for new events
  const delBtn = document.getElementById("delete-btn");
  if (delBtn) delBtn.style.display = "none";

  document.getElementById("modal").classList.remove("hidden");
  updateDurationLabel();

  setTimeout(() => {
    const focus = prefillStart ? document.getElementById("event-title") : document.getElementById("start-time");
    focus?.focus();
  }, 50);
}

function openModal(ev) {
  hideConflict();
  selected = ev;

  document.getElementById("modal-title").textContent = "Edit Event";
  document.getElementById("start-time").value = formatTime(ev.start_time) || "";
  document.getElementById("end-time").value = formatTime(ev.end_time) || "";
  _refreshAllTimePillDisplays();
  document.getElementById("event-priority").value = ev.priority || "medium";
  document.getElementById("event-title").value = ev.task_text || ev.title || "";
  document.getElementById("event-desc").value = ev.description || "";

  // Recurrence fields — pre-populate from master (ev carries the master's fields when it's a recurring instance)
  const ruleSel = document.getElementById("recurrence-rule");
  if (ruleSel) {
    ruleSel.value = ev.recurrence_rule || "";
    onRecurrenceRuleChange();

    // Day picker for custom
    const daySet = new Set((ev.recurrence_days || "").split(",").filter(Boolean));
    document.querySelectorAll("#recurrence-days input[type=checkbox]").forEach(cb => {
      cb.checked = daySet.has(cb.value);
    });

    // End mode
    const endMode = document.getElementById("recurrence-end-mode");
    if (ev.recurrence_end) {
      endMode.value = "on";
      document.getElementById("recurrence-end-date").value = ev.recurrence_end;
    } else if (ev.recurrence_count) {
      endMode.value = "after";
      document.getElementById("recurrence-end-count").value = ev.recurrence_count;
    } else {
      endMode.value = "never";
    }
    onRecurrenceEndModeChange();
  }

  // Reminder
  const select = document.getElementById("reminder-select");
  const custom = document.getElementById("custom-reminder");
  select.value = "10";
  custom.value = "";
  custom.style.display = "none";

  if (ev.reminder_minutes !== undefined && ev.reminder_minutes !== null) {
    const reminder = parseInt(ev.reminder_minutes);
    if ([0, 5, 10, 15, 30, 60].includes(reminder)) {
      select.value = String(reminder);
    } else {
      select.value = "custom";
      custom.value = reminder;
      custom.style.display = "block";
    }
  }

  // Set quadrant
  document.querySelectorAll(".quad-btn").forEach(b => b.classList.remove("active"));
  const qVal = ev.quadrant || "";
  const qBtn = document.querySelector(`.quad-btn[data-q="${qVal}"]`);
  if (qBtn) qBtn.classList.add("active");

  // Show delete button for existing events
  const delBtn = document.getElementById("delete-btn");
  if (delBtn) delBtn.style.display = "";

  document.getElementById("modal").classList.remove("hidden");
  updateDurationLabel();

  if (window.feather) feather.replace();
}

function closeModal() {
  document.getElementById("modal").classList.add("hidden");
  selected = null;
}

function updateEndFromStart() {
  // When start changes, move end to keep same duration
  const start = document.getElementById("start-time").value;
  const end = document.getElementById("end-time").value;
  if (!start) return;

  const startMin = minutes(start);
  const endMin = end ? minutes(end) : startMin + 30;
  let dur = endMin - startMin;
  if (dur <= 0) dur = 30; // If end is before start, default 30min

  document.getElementById("end-time").value = toTime(startMin + dur);
  _refreshAllTimePillDisplays();
  updateDurationLabel();
}

function updateDurationFromEnd() {
  // When end changes, update duration label
  updateDurationLabel();
}

function updateDurationLabel() {
  const start = document.getElementById("start-time").value;
  const end = document.getElementById("end-time").value;
  const label = document.getElementById("duration-label");
  if (!label) return;

  if (!start || !end) {
    label.textContent = "—";
    document.getElementById("duration").value = 30;
    return;
  }

  const dur = minutes(end) - minutes(start);
  if (dur <= 0) { label.textContent = "Invalid"; return; }

  // Format nicely
  if (dur < 60) {
    label.textContent = dur + " min";
  } else {
    const h = Math.floor(dur / 60);
    const m = dur % 60;
    label.textContent = m ? `${h}h ${m}m` : `${h} hour${h > 1 ? "s" : ""}`;
  }

  // Update hidden duration select for backward compat
  document.getElementById("duration").value = dur;

  // Highlight matching duration preset chip inside the End field
  document.querySelectorAll("#duration-presets .time-chip").forEach(btn => {
    const val = parseInt(btn.getAttribute("onclick")?.match(/\d+/)?.[0] || 0);
    btn.classList.toggle("active", val === dur);
  });

  // Also highlight the Start preset chip if it matches an exact preset
  _syncStartPresetChips(start);
}

function setDuration(mins) {
  const start = document.getElementById("start-time").value;
  if (!start) {
    showToast("Set a start time first", "error");
    return;
  }
  document.getElementById("end-time").value = toTime(minutes(start) + mins);
  _syncTimePillDisplay("end-time");
  updateDurationLabel();
}

// ─── New helpers for the pill-style time control ──────────────
// The pills are now display-only — backed by a hidden <input>. The
// clock face popover (openClockPicker) is the sole time-entry UI.
// The native <input type="time"> has been removed entirely to stop
// browsers from opening their own mini picker in parallel.
function openTimePicker(inputId) {
  openClockPicker(inputId);
}

// Update the visible .time-pill-display span whenever the hidden
// input's value changes. Called from the clock picker, presets,
// clearTimeField, openCreateModal, and openModal.
function _syncTimePillDisplay(inputId) {
  const input = document.getElementById(inputId);
  const display = document.getElementById(inputId + "-display");
  if (!input || !display) return;
  const raw = (input.value || "").trim();
  if (!raw) {
    display.textContent = display.dataset.placeholder || "Set time";
    display.classList.add("empty");
    return;
  }
  // Render as "3:00 PM" for readability
  const [h, m] = raw.split(":").map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) {
    display.textContent = raw;
    display.classList.remove("empty");
    return;
  }
  const ampm = h < 12 ? "AM" : "PM";
  const h12 = ((h + 11) % 12) + 1;
  display.textContent = `${h12}:${String(m).padStart(2, "0")} ${ampm}`;
  display.classList.remove("empty");
}
// Expose via a helper the modal/reset flows can call
function _refreshAllTimePillDisplays() {
  _syncTimePillDisplay("start-time");
  _syncTimePillDisplay("end-time");
}

/* ═══════════════════════════════════════════════════════════
   GOOGLE CALENDAR EXPORT — pushes the current modal's values
   into Google Calendar's TEMPLATE URL with a 10-minute reminder
   pre-set. Works for both create and edit modes because it
   just reads the live input values.
   ═══════════════════════════════════════════════════════════ */
function addCurrentModalToGoogleCalendar() {
  const title   = (document.getElementById("event-title")?.value || "Untitled event").trim();
  const desc    = (document.getElementById("event-desc")?.value || "").trim();
  const start   = (document.getElementById("start-time")?.value || "").trim();
  const end     = (document.getElementById("end-time")?.value || "").trim();
  const dateStr = (selected && selected.plan_date) || currentDate || getISTDate();

  if (!start || !end) {
    showToast("Set a start and end time first", "error");
    return;
  }
  if (!dateStr) {
    showToast("No date selected", "error");
    return;
  }

  // Google's TEMPLATE URL wants dates like 20260405T090000/20260405T100000
  // (local time with no Z, so Google treats it as the user's own tz — which
  // is what we want since IST times are what the user sees here).
  const yyyymmdd = dateStr.replaceAll("-", "");
  const startStamp = start.replace(":", "") + "00";  // "09:00" → "090000"
  const endStamp   = end.replace(":", "") + "00";

  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: title,
    details: desc
      ? `${desc}\n\nCreated from Daily Planner`
      : "Created from Daily Planner",
    dates: `${yyyymmdd}T${startStamp}/${yyyymmdd}T${endStamp}`,
    ctz: "Asia/Kolkata",      // render in IST so times match what you see here
    trp: "true",
  });

  // Google Calendar's add-event TEMPLATE URL honors `reminders` via the
  // `add` flow (for authenticated users). For the quick-add TEMPLATE form
  // the reminder is applied through the calendar's default. We pass the
  // hint in the details for visibility and set the URL's reminder param
  // that the Chrome extension / Safari web extension understand.
  params.set("reminders", "10");

  const url = "https://calendar.google.com/calendar/render?" + params.toString();
  window.open(url, "_blank", "noopener");
  showToast("Opening Google Calendar…", "success");
}

// ═════════════════════════════════════════════════════════════
// CLOCK PICKER — Material-style two-phase picker (hour → minute)
// Renders as an SVG clock face with numbered hour positions, a
// draggable hand, and an AM/PM toggle. Lightweight, keyboard-safe,
// and mobile-friendly.
// ═════════════════════════════════════════════════════════════
let _clockState = {
  inputId: null,
  hour12: 9,       // 1..12
  minute: 0,       // 0..59
  ampm: "AM",
  mode: "hour",    // "hour" | "minute"
};

function openClockPicker(inputId) {
  const input = document.getElementById(inputId);
  if (!input) return;

  // Seed from the input's current value if present
  const existing = (input.value || "").trim();
  if (existing && /^\d{1,2}:\d{2}/.test(existing)) {
    const [hh, mm] = existing.split(":").map(Number);
    _clockState.ampm = hh >= 12 ? "PM" : "AM";
    _clockState.hour12 = ((hh + 11) % 12) + 1;
    _clockState.minute = mm || 0;
  } else {
    // Sensible default: 9:00 AM for start, 9:30 AM for end
    if (inputId === "end-time") {
      _clockState.hour12 = 9;
      _clockState.minute = 30;
    } else {
      _clockState.hour12 = 9;
      _clockState.minute = 0;
    }
    _clockState.ampm = "AM";
  }
  _clockState.inputId = inputId;
  _clockState.mode = "hour";

  _renderClockPicker();
}

function closeClockPicker() {
  const el = document.getElementById("clock-picker");
  const overlay = document.getElementById("clock-picker-overlay");
  el?.classList.remove("open");
  overlay?.classList.remove("open");
  _clockState.inputId = null;
}

function _renderClockPicker() {
  let overlay = document.getElementById("clock-picker-overlay");
  let host = document.getElementById("clock-picker");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "clock-picker-overlay";
    overlay.className = "clock-picker-overlay";
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeClockPicker();
    });
    document.body.appendChild(overlay);
  }
  if (!host) {
    host = document.createElement("div");
    host.id = "clock-picker";
    host.className = "clock-picker";
    host.setAttribute("role", "dialog");
    host.setAttribute("aria-label", "Time picker");
    document.body.appendChild(host);
  }

  const { hour12, minute, ampm, mode, inputId } = _clockState;
  const label = inputId === "end-time" ? "Set end time" : "Set start time";
  const hourStr = String(hour12);
  const minStr = String(minute).padStart(2, "0");

  host.innerHTML = `
    <div class="cp-header">
      <div class="cp-title">${label}</div>
      <button type="button" class="cp-close" onclick="closeClockPicker()" aria-label="Close">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <path d="M6 6l12 12M18 6L6 18"/>
        </svg>
      </button>
    </div>

    <div class="cp-display">
      <button type="button" class="cp-big ${mode === 'hour' ? 'active' : ''}"
              onclick="_clockSetMode('hour')">${hourStr}</button>
      <span class="cp-colon">:</span>
      <button type="button" class="cp-big ${mode === 'minute' ? 'active' : ''}"
              onclick="_clockSetMode('minute')">${minStr}</button>
      <div class="cp-ampm">
        <button type="button" class="cp-ampm-btn ${ampm === 'AM' ? 'active' : ''}"
                onclick="_clockSetAmPm('AM')">AM</button>
        <button type="button" class="cp-ampm-btn ${ampm === 'PM' ? 'active' : ''}"
                onclick="_clockSetAmPm('PM')">PM</button>
      </div>
    </div>

    <div class="cp-face-wrap">
      ${_renderClockFace()}
    </div>

    <div class="cp-actions">
      <button type="button" class="cp-btn cp-btn-ghost" onclick="closeClockPicker()">Cancel</button>
      <button type="button" class="cp-btn cp-btn-primary" onclick="_clockConfirm()">
        ${mode === 'hour' ? 'Next' : 'Done'}
      </button>
    </div>
  `;

  overlay.classList.add("open");
  host.classList.add("open");

  // Wire up number-node clicks
  host.querySelectorAll(".cp-num").forEach(node => {
    node.addEventListener("click", () => {
      const val = parseInt(node.dataset.val, 10);
      if (_clockState.mode === "hour") {
        _clockState.hour12 = val === 0 ? 12 : val;
      } else {
        _clockState.minute = val;
      }
      _renderClockPicker();
    });
  });
}

function _renderClockFace() {
  const { mode, hour12, minute } = _clockState;
  const size = 260;
  const cx = size / 2;
  const cy = size / 2;
  const rOuter = 108;   // where hour numbers sit
  const rMinor = 84;    // inner ring for 13-24 (unused here, 12-hour mode)

  // Build hour numbers (1..12) arranged around the circle
  const hourNodes = [];
  for (let h = 1; h <= 12; h++) {
    const angle = ((h - 3) * 2 * Math.PI) / 12; // 12 at top
    const x = cx + rOuter * Math.cos(angle);
    const y = cy + rOuter * Math.sin(angle);
    const selected = mode === "hour" && hour12 === h;
    hourNodes.push(`
      <g class="cp-num ${selected ? 'selected' : ''}" data-val="${h}">
        <circle cx="${x}" cy="${y}" r="18" />
        <text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="central"
              font-size="17" font-weight="700">${h}</text>
      </g>
    `);
  }

  // Build minute markers (0, 5, 10, ... 55) — only labeled at 5-min steps
  const minuteNodes = [];
  for (let m = 0; m < 60; m += 5) {
    const angle = ((m / 5 - 3) * 2 * Math.PI) / 12;
    const x = cx + rOuter * Math.cos(angle);
    const y = cy + rOuter * Math.sin(angle);
    const selected = mode === "minute" && minute === m;
    minuteNodes.push(`
      <g class="cp-num ${selected ? 'selected' : ''}" data-val="${m}">
        <circle cx="${x}" cy="${y}" r="18" />
        <text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="central"
              font-size="15" font-weight="700">${String(m).padStart(2, '0')}</text>
      </g>
    `);
  }

  // Hand: line from center to the selected number
  let handAngle = 0;
  let handReach = rOuter;
  if (mode === "hour") {
    handAngle = ((hour12 - 3) * 2 * Math.PI) / 12;
  } else {
    handAngle = ((minute / 5 - 3) * 2 * Math.PI) / 12;
  }
  const hx = cx + handReach * Math.cos(handAngle);
  const hy = cy + handReach * Math.sin(handAngle);

  const nodes = mode === "hour" ? hourNodes : minuteNodes;

  return `
    <svg class="cp-face" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">
      <circle class="cp-face-bg" cx="${cx}" cy="${cy}" r="${size / 2 - 4}" />
      <line class="cp-hand" x1="${cx}" y1="${cy}" x2="${hx}" y2="${hy}" />
      <circle class="cp-hand-end" cx="${hx}" cy="${hy}" r="18" />
      <circle class="cp-hand-center" cx="${cx}" cy="${cy}" r="4" />
      ${nodes.join("")}
    </svg>
  `;
}

function _clockSetMode(mode) {
  _clockState.mode = mode;
  _renderClockPicker();
}
function _clockSetAmPm(v) {
  _clockState.ampm = v;
  _renderClockPicker();
}
function _clockConfirm() {
  if (_clockState.mode === "hour") {
    _clockState.mode = "minute";
    _renderClockPicker();
    return;
  }
  // Minute mode → commit and close
  const input = document.getElementById(_clockState.inputId);
  if (input) {
    let h24 = _clockState.hour12 % 12;        // 12 AM → 0, 1..11 AM → 1..11
    if (_clockState.ampm === "PM") h24 += 12; // 1 PM → 13, 12 PM → 12
    const hhmm = `${String(h24).padStart(2, "0")}:${String(_clockState.minute).padStart(2, "0")}`;
    input.value = hhmm;
    _syncTimePillDisplay(_clockState.inputId);
    // Fire the change event so existing listeners run (updateDurationLabel,
    // updateEndFromStart, etc.)
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }
  closeClockPicker();
}

// Close on Escape
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && document.getElementById("clock-picker")?.classList.contains("open")) {
    closeClockPicker();
  }
});

function clearTimeField(inputId) {
  const el = document.getElementById(inputId);
  if (!el) return;
  el.value = "";
  // If start is cleared, clear end too (end without start is meaningless)
  if (inputId === "start-time") {
    const endEl = document.getElementById("end-time");
    if (endEl) endEl.value = "";
  }
  _refreshAllTimePillDisplays();
  updateDurationLabel();
  _syncStartPresetChips("");
}

function setTimeFromPreset(btn) {
  const field = btn.dataset.field;
  const time = btn.dataset.time;
  if (!field || !time) return;

  const input = document.getElementById(field);
  if (!input) return;

  const prevEnd = document.getElementById("end-time")?.value || "";
  const prevStart = document.getElementById("start-time")?.value || "";
  input.value = time;

  // If setting Start and an End already exists, slide End to maintain the
  // same duration (Google Calendar behavior). If no End yet, default to +30.
  if (field === "start-time") {
    const endEl = document.getElementById("end-time");
    if (endEl) {
      if (prevStart && prevEnd) {
        const dur = Math.max(15, minutes(prevEnd) - minutes(prevStart));
        endEl.value = toTime(minutes(time) + dur);
      } else {
        endEl.value = toTime(minutes(time) + 30);
      }
    }
  }

  _refreshAllTimePillDisplays();
  updateDurationLabel();
}

// Highlight a Start preset chip if the current start-time matches it
function _syncStartPresetChips(startValue) {
  document.querySelectorAll('.time-chip[data-field="start-time"]').forEach(c => {
    c.classList.toggle("active", startValue && c.dataset.time === startValue.slice(0, 5));
  });
}

// Legacy compat
function updateEndPreview() { updateDurationLabel(); }

function pickQuadrant(btn) {
  document.querySelectorAll(".quad-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
}

function getSelectedQuadrant() {
  const active = document.querySelector(".quad-btn.active");
  return active ? active.dataset.q || null : null;
}

function handleReminderSelect() {
  const select = document.getElementById("reminder-select");
  const custom = document.getElementById("custom-reminder");
  custom.style.display = select.value === "custom" ? "block" : "none";
}

function getReminderMinutes() {
  const select = document.getElementById("reminder-select");
  const custom = document.getElementById("custom-reminder");
  if (select.value === "custom") {
    return parseInt(custom.value || 0);
  }
  return parseInt(select.value);
}

// ── Recurrence UI helpers ─────────────────────────────────────
function onRecurrenceRuleChange() {
  const rule = document.getElementById("recurrence-rule").value;
  document.getElementById("recurrence-days-wrap").style.display =
    rule === "custom" ? "" : "none";
  document.getElementById("recurrence-end-wrap").style.display =
    rule ? "" : "none";
}

function onRecurrenceEndModeChange() {
  const mode = document.getElementById("recurrence-end-mode").value;
  document.getElementById("recurrence-end-date").style.display  = mode === "on"    ? "" : "none";
  document.getElementById("recurrence-end-count").style.display = mode === "after" ? "" : "none";
}

function collectRecurrenceFields() {
  const rule = document.getElementById("recurrence-rule").value || null;
  if (!rule) return { recurrence_rule: null };
  const days = Array.from(document.querySelectorAll("#recurrence-days input:checked"))
                    .map(cb => cb.value).join(",");
  const mode = document.getElementById("recurrence-end-mode").value;
  const end = mode === "on"    ? (document.getElementById("recurrence-end-date").value || null)  : null;
  const cnt = mode === "after" ? (document.getElementById("recurrence-end-count").value || null) : null;
  return {
    recurrence_rule: rule,
    recurrence_days: rule === "custom" ? days : null,
    recurrence_end: end,
    recurrence_count: cnt ? parseInt(cnt, 10) : null,
  };
}

// Prompt: this / following / all — resolves to 'this'|'following'|'all' or null.
function promptRecurringScope(verb) {
  return new Promise(resolve => {
    const bd = document.createElement("div");
    bd.className = "cal-recurring-dialog-backdrop";
    bd.innerHTML = `
      <div class="cal-recurring-dialog" role="dialog" aria-modal="true">
        <h3>${verb} recurring event</h3>
        <label><input type="radio" name="rs" value="this" checked> This event only</label>
        <label><input type="radio" name="rs" value="following"> This and following events</label>
        <label><input type="radio" name="rs" value="all"> All events</label>
        <div class="dialog-actions">
          <button class="btn btn-ghost" data-act="cancel">Cancel</button>
          <button class="btn btn-primary" data-act="ok">OK</button>
        </div>
      </div>`;
    document.body.appendChild(bd);
    bd.addEventListener("click", (e) => {
      if (e.target === bd || e.target.dataset.act === "cancel") {
        document.body.removeChild(bd);
        resolve(null);
      } else if (e.target.dataset.act === "ok") {
        const pick = bd.querySelector('input[name="rs"]:checked')?.value || "this";
        document.body.removeChild(bd);
        resolve(pick);
      }
    });
  });
}

async function saveEvent() {
  const start = document.getElementById("start-time").value;
  const end = document.getElementById("end-time").value;

  if (!start) {
    showToast("Please enter a start time", "error");
    return;
  }
  if (!end || minutes(end) <= minutes(start)) {
    showToast("End time must be after start time", "error");
    return;
  }

  const payload = {
    plan_date: (selected && (selected.plan_date || selected._date)) || currentDate,
    start_time: start,
    end_time: end,
    title: document.getElementById("event-title").value,
    description: document.getElementById("event-desc").value,
    priority: document.getElementById("event-priority").value,
    quadrant: getSelectedQuadrant(),
    reminder_minutes: getReminderMinutes(),
    ...collectRecurrenceFields(),
  };

  // If editing a recurring instance, ask which scope.
  const isRecurringInstance = selected && (
    selected._is_recurring_instance ||
    (selected.recurrence_rule && selected.type !== "project")
  );
  if (isRecurringInstance) {
    const scope = await promptRecurringScope("Edit");
    if (!scope) return;  // user cancelled
    payload.scope = scope;
    payload.occurrence_date = selected.plan_date || currentDate;
  }

  let url, method;

  if (selected) {
    if (selected.type === "project") {
      url = `/api/v2/project-tasks/${selected.task_id}`;
      method = "PUT";
    } else {
      // Use the master id (series_id if present) for scope=following/all,
      // or the exception row for scope=this on an already-modified occurrence.
      const targetId = payload.scope === "this"
        ? (selected._master_id || selected.id)
        : (selected._master_id || selected.id);
      url = `/api/v2/events/${targetId}`;
      method = "PUT";
    }
  } else {
    url = "/api/v2/events";
    method = "POST";
  }

  try {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      let data = {};
      try { data = await res.json(); } catch {}

      if (data.conflict) {
        showConflictDialog(data.conflicting_events, payload);
        return;
      }

      showToast("Save failed", "error");
      return;
    }

    // Read the sync flag the server returned so we can tell the user
    // whether it reached Google Calendar or not.
    let resBody = {};
    try { resBody = await res.json(); } catch {}

    closeModal();
    if (resBody.gcal_synced) {
      showToast("Saved & synced to Google Calendar", "success");
    } else if (resBody.gcal_error) {
      showToast("Saved locally (Google sync failed)", "info");
    } else if (_gcalConnected === false) {
      // User hasn't connected Google yet — nudge them once
      showToast("Saved. Connect Google Calendar to auto-sync", "info");
    } else {
      showToast("Event saved", "success");
    }
    loadAllEvents();

  } catch (err) {
    console.error("Save error:", err);
    showToast("Save failed", "error");
  }
}

// ═══════════════════════════════════════════════════════════
// Google Calendar connection state — auto-checked on page load,
// drives the "Auto-sync" status pill in the modal header.
// ═══════════════════════════════════════════════════════════
let _gcalConnected = null;    // null = unknown, true/false once fetched
let _gcalNeedsReauth = false;
let _gcalLoginUrl = "/google-login";

async function loadGoogleStatus() {
  try {
    const r = await fetch("/api/v2/google-status");
    if (!r.ok) return;
    const data = await r.json();
    _gcalConnected = !!data.connected;
    _gcalNeedsReauth = !!data.needs_reauth;
    if (data.login_url) _gcalLoginUrl = data.login_url;
    _renderGcalStatusPill();
  } catch (err) {
    console.warn("google-status failed:", err);
  }
}

function _renderGcalStatusPill() {
  const pill = document.getElementById("gcal-status-pill");
  if (!pill) return;
  if (_gcalConnected === true) {
    pill.classList.add("connected");
    pill.classList.remove("disconnected");
    pill.title = "Google Calendar connected — events auto-sync with a 10-minute reminder";
    pill.querySelector(".gcal-status-text").textContent = "Auto-sync on";
  } else if (_gcalNeedsReauth === true) {
    pill.classList.add("disconnected");
    pill.classList.remove("connected");
    pill.title = "Google token expired or revoked — click to reconnect";
    pill.querySelector(".gcal-status-text").textContent = "Reconnect Google";
  } else if (_gcalConnected === false) {
    pill.classList.add("disconnected");
    pill.classList.remove("connected");
    pill.title = "Click to connect your Google Calendar for auto-sync";
    pill.querySelector(".gcal-status-text").textContent = "Connect Google";
  }
}

// Clicking the status pill:
// • If not connected → starts OAuth flow
// • If connected     → opens the manual Google Calendar export URL
function onGcalStatusClick() {
  if (_gcalConnected === false) {
    window.location.href = _gcalLoginUrl;
  } else {
    addCurrentModalToGoogleCalendar();
  }
}

// Kick off the check when the page loads
document.addEventListener("DOMContentLoaded", loadGoogleStatus);

async function deleteEvent() {
  if (!selected || !selected.id) return;

  const isRecurringInstance = selected._is_recurring_instance ||
    (selected.recurrence_rule && selected.type !== "project");

  if (isRecurringInstance) {
    const scope = await promptRecurringScope("Delete");
    if (!scope) return;
    const targetId = selected._master_id || selected.id;
    const qs = new URLSearchParams({
      scope,
      occurrence_date: selected.plan_date || currentDate,
    });
    try {
      await fetch(`/api/v2/events/${targetId}?${qs}`, { method: "DELETE" });
      showToast("Deleted", "success");
      closeModal();
      loadAllEvents();
    } catch (err) {
      showToast("Delete failed", "error");
    }
    return;
  }

  await deleteEventById(selected.id);
  closeModal();
}

async function deleteEventById(id) {
  try {
    await fetch(`/api/v2/events/${id}`, { method: "DELETE" });
    showToast("Event deleted", "success");
    loadAllEvents();
  } catch (err) {
    showToast("Delete failed", "error");
  }
}

function hideConflict() {
  const section = document.getElementById("conflict-section");
  if (section) section.style.display = "none";
}

function showConflictDialog(conflicts, payload) {
  const list = document.getElementById("conflict-list");
  const section = document.getElementById("conflict-section");

  list.innerHTML = conflicts.map(c =>
    `<div style="margin:6px 0;">
       ${formatTime(c.start_time)} - ${formatTime(c.end_time)}: ${c.title}
     </div>`
  ).join("");

  section.style.display = "flex";

  document.getElementById("accept-conflict").onclick = async (e) => {
    if (e) { e.preventDefault(); e.stopPropagation(); }
    payload.force = true;

    // Mirror saveEvent()'s URL/method logic so editing doesn't create a duplicate
    let url, method;
    if (selected) {
      if (selected.type === "project") {
        url = `/api/v2/project-tasks/${selected.task_id}`;
        method = "PUT";
      } else {
        url = `/api/v2/events/${selected.id}`;
        method = "PUT";
      }
    } else {
      url = "/api/v2/events";
      method = "POST";
    }

    try {
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      hideConflict();
      closeModal();
      showToast("Event saved (conflict accepted)", "success");
      loadAllEvents();
    } catch (err) {
      console.error("Accept conflict failed:", err);
      showToast("Failed to save", "error");
    }
  };

  if (window.feather) feather.replace();
}

/* ══════════════════════════════════════════════════════════════
   13. PROJECT TASK MODAL
   ══════════════════════════════════════════════════════════════ */

async function openTaskCard(taskId) {
  selected = { task_id: taskId };

  try {
    const res = await fetch(`/api/v2/project-tasks/${taskId}`);
    if (!res.ok) throw new Error("Failed to load task");
    const task = await res.json();

    document.getElementById("task-title").value = task.task_text || "";
    document.getElementById("task-description").value = task.notes || "";
    document.getElementById("task-planned-hours").value = task.planned_hours || 0;
    document.getElementById("task-actual-hours").value = task.actual_hours || 0;
    document.getElementById("task-status").value = task.status || "open";
    document.getElementById("task-priority").value = task.priority || "medium";
    document.getElementById("task-duration").value = task.duration_days || 0;
    document.getElementById("task-due-date").value = task.due_date || "";
    document.getElementById("task-start-time").value = task.start_time || "";

    document.getElementById("task-card-modal").classList.add("show");
    document.getElementById("task-card-modal").classList.remove("hidden");
  } catch (err) {
    showToast("Failed to load task", "error");
  }
}

async function saveTaskCard() {
  const taskId = selected?.task_id;
  if (!taskId) return;

  const payload = {
    task_text: document.getElementById("task-title").value,
    notes: document.getElementById("task-description").value,
    status: document.getElementById("task-status").value,
    priority: document.getElementById("task-priority").value,
    planned_hours: parseFloat(document.getElementById("task-planned-hours").value) || 0,
    actual_hours: parseFloat(document.getElementById("task-actual-hours").value) || 0,
    duration_days: parseInt(document.getElementById("task-duration").value) || 0,
    due_date: document.getElementById("task-due-date").value,
    start_time: document.getElementById("task-start-time").value
  };

  try {
    const res = await fetch(`/api/v2/project-tasks/${taskId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error("Save failed");
    closeTaskCard();
    showToast("Task saved", "success");
    loadAllEvents();
  } catch (err) {
    showToast("Save failed", "error");
  }
}

function closeTaskCard() {
  const modal = document.getElementById("task-card-modal");
  modal.classList.remove("show");
  modal.classList.add("hidden");
  selected = null;
}

function adjustTaskNumber(btn, direction) {
  const wrapper = btn.closest(".number-control");
  const input = wrapper.querySelector("input");
  const step = parseFloat(input.step || 1);
  let value = parseFloat(input.value || 0);
  value += direction * step;
  if (value < 0) value = 0;
  if (value > 999) value = 999;
  input.value = parseFloat(value.toFixed(2));
}

/* ══════════════════════════════════════════════════════════════
   14. FLOATING TASKS (sidebar)
   ══════════════════════════════════════════════════════════════ */

function renderFloatingTasks(tasks) {
  const container = document.getElementById("floating-tasks");
  if (!container) return;
  container.innerHTML = "";

  // Only genuinely unscheduled tasks. A plan_date means the task has been
  // given a day even if it was given no clock time — /ai-sde's scheduler
  // does exactly that, deliberately, so the topic's calendar chip comes
  // from its event row and not from the task as well. Listing it here as
  // "unscheduled" would be the same double-entry in a different panel,
  // and it would pile up: every topic she has planned but not yet ticked
  // off would sit in this list from its day onward.
  const unscheduled = (tasks || []).filter(t => !t.start_time && !t.plan_date);

  if (!unscheduled.length) {
    container.innerHTML = `<div class="empty-state">No unscheduled tasks</div>`;
    return;
  }

  const priorityOrder = { high: 0, medium: 1, low: 2 };
  const todayStr = getISTDate();

  // Sort: priority high->low, then by due date
  unscheduled.sort((a, b) => {
    const pa = priorityOrder[a.priority || "medium"] ?? 1;
    const pb = priorityOrder[b.priority || "medium"] ?? 1;
    if (pa !== pb) return pa - pb;
    if (a.due_date && b.due_date) return a.due_date.localeCompare(b.due_date);
    if (a.due_date) return -1;
    if (b.due_date) return 1;
    return 0;
  });

  unscheduled.forEach(task => {
    const div = document.createElement("div");
    div.className = "floating-task";
    div.draggable = true;

    const priority = task.priority || "medium";
    const projectName = task.projects?.name || "";
    const isOverdue = task.due_date && task.due_date < todayStr;

    if (isOverdue) div.classList.add("overdue-floating");

    div.innerHTML = `
      <div class="floating-title">${task.task_text || ""}</div>
      ${projectName ? `<div class="floating-project">${projectName}</div>` : ""}
      <div class="floating-meta">
        <span class="floating-priority p-${priority}">${priority.toUpperCase()}</span>
        ${task.due_date ? `<span class="floating-due">${task.due_date}</span>` : ""}
      </div>
    `;

    // Click -> open task card
    div.addEventListener("click", (e) => {
      e.stopPropagation();
      openTaskCard(task.task_id);
    });

    // Desktop drag
    div.addEventListener("dragstart", () => {
      draggedTask = { ...task, type: "project" };
    });

    // Touch drag for mobile
    attachFloatingTouchDrag(div, task);

    container.appendChild(div);
  });
}

/* ══════════════════════════════════════════════════════════════
   15. DRAG & DROP — Desktop (column handlers)
   ══════════════════════════════════════════════════════════════ */

function onColumnDragOver(e) {
  e.preventDefault();
  if (!draggedTask) return;

  const col = e.currentTarget;
  const rect = col.getBoundingClientRect();
  // getBoundingClientRect already reflects the current scroll position —
  // don't add scrollTop on top of it.
  const y = _clampColY(e.clientY - rect.top);
  const minutesFromTop = (y / HOUR_HEIGHT) * 60;
  const snapped = _clampMinutes(Math.round(minutesFromTop / SNAP) * SNAP);
  const top = (snapped / 60) * HOUR_HEIGHT;

  // Show snap line
  let line = col.querySelector(".snap-line");
  if (!line) {
    line = document.createElement("div");
    line.className = "snap-line";
    col.appendChild(line);
  }
  line.style.top = top + "px";

  // Live time badge — shows the exact start time the drop will land at,
  // plus the end time based on the dragged item's duration (default 30m
  // for unscheduled tasks or if we can't infer).
  let durMin = 30;
  if (draggedTask.start_time && draggedTask.end_time) {
    durMin = Math.max(SNAP, minutes(draggedTask.end_time) - minutes(draggedTask.start_time));
  }
  const endM = _clampMinutes(snapped + durMin);
  _showDragBadge(
    `${_fmtTimeLabel(snapped)} – ${_fmtTimeLabel(endM)} · ${_fmtDurLabel(endM - snapped)}`,
    e.clientX,
    e.clientY
  );
}

function onColumnDragLeave(e) {
  const col = e.currentTarget;
  const line = col.querySelector(".snap-line");
  if (line) line.remove();
  _hideDragBadge();
}

async function onColumnDrop(e) {
  e.preventDefault();
  if (!draggedTask) return;

  const col = e.currentTarget;
  const targetDate = col.dataset.date;

  // Clean snap line + drag badge
  const line = col.querySelector(".snap-line");
  if (line) line.remove();
  _hideDragBadge();

  const rect = col.getBoundingClientRect();
  const y = _clampColY(e.clientY - rect.top);
  const minutesFromTop = (y / HOUR_HEIGHT) * 60;
  const snapped = _clampMinutes(Math.round(minutesFromTop / SNAP) * SNAP);

  const newStart = toTime(snapped);

  if (draggedTask.type === "project") {
    const end = calculateEndTime(newStart, 30);
    await fetch(`/api/v2/project-tasks/${draggedTask.task_id}/schedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_date: targetDate, start_time: newStart, end_time: end })
    });
  } else {
    const duration = (draggedTask._end || minutes(draggedTask.end_time)) - (draggedTask._start || minutes(draggedTask.start_time));
    const newEnd = toTime(snapped + duration);

    await fetch(`/api/v2/events/${draggedTask.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan_date: targetDate,
        start_time: newStart,
        end_time: newEnd,
        title: draggedTask.title
      })
    });
  }

  draggedTask = null;
  showToast("Event moved", "success");
  loadAllEvents();
}

/* ══════════════════════════════════════════════════════════════
   16. DRAG-TO-CREATE
   ──────────────────────────────────────────────────────────────
   Desktop (mouse/pen): immediate drag on pointerdown.
   Touch: long-press (450ms) to enter create mode — otherwise the
   browser's native vertical scroll wins and create never fires.
   Once committed, a non-passive touchmove handler preventDefault()s
   scroll so dragging the ghost event works.
   ══════════════════════════════════════════════════════════════ */

let holdTimer = null;
let activePointerId = null;

function onColumnPointerDown(e) {
  // Ignore if on an event chip or button
  if (e.target.closest(".event-chip")) return;
  if (e.target.closest("button")) return;

  // Only the primary pointer
  if (e.isPrimary === false) return;

  const col = e.currentTarget;
  createColDate = col.dataset.date;
  createStartY = e.clientY;
  createStartX = e.clientX;
  activePointerId = e.pointerId;

  if (e.pointerType === "touch") {
    // Long-press model on touch so normal scrolls aren't hijacked
    pendingCreate = false;
    creatingEvent = false;

    clearTimeout(holdTimer);
    holdTimer = setTimeout(() => {
      holdTimer = null;
      _beginTouchCreate();
    }, 450);

    // Short-press cancellers — if the finger moves or lifts before
    // the timeout, treat it as a scroll/tap and abort.
    document.addEventListener("pointermove", _preHoldMove, { passive: true });
    document.addEventListener("pointerup", _preHoldEnd, { passive: true });
    document.addEventListener("pointercancel", _preHoldEnd, { passive: true });
  } else {
    // Mouse/pen — original immediate-drag behavior
    pendingCreate = true;
    creatingEvent = false;
    document.addEventListener("pointermove", onCreatePointerMove);
    document.addEventListener("pointerup", onCreatePointerUp);
    document.addEventListener("pointercancel", cancelCreate);
  }
}

function _preHoldMove(e) {
  if (e.pointerId !== activePointerId) return;
  const dX = Math.abs(e.clientX - createStartX);
  const dY = Math.abs(e.clientY - createStartY);
  // Any meaningful movement before hold fires = user scrolling, abort
  if (dX > 10 || dY > 10) {
    _clearPreHoldListeners();
    clearTimeout(holdTimer); holdTimer = null;
  }
}

function _preHoldEnd() {
  _clearPreHoldListeners();
  clearTimeout(holdTimer); holdTimer = null;
}

function _clearPreHoldListeners() {
  document.removeEventListener("pointermove", _preHoldMove);
  document.removeEventListener("pointerup", _preHoldEnd);
  document.removeEventListener("pointercancel", _preHoldEnd);
}

function _beginTouchCreate() {
  _clearPreHoldListeners();

  const col = document.querySelector(`.gcal-day-col[data-date="${createColDate}"]`);
  if (!col) return;

  // Haptic cue where supported
  if (navigator.vibrate) { try { navigator.vibrate(25); } catch {} }

  // Create the ghost at the pressed position.
  // getBoundingClientRect() already accounts for the scroll container's
  // scrollTop — do NOT add it again. The column-local y is simply
  // pointerClientY − col.rect.top.
  const rect = col.getBoundingClientRect();
  const y = _clampColY(createStartY - rect.top);
  const minutesFromTop = (y / HOUR_HEIGHT) * 60;
  const snapped = _clampMinutes(Math.round(minutesFromTop / SNAP) * SNAP);
  const top = (snapped / 60) * HOUR_HEIGHT;

  ghostEvent = document.createElement("div");
  ghostEvent.className = "event-chip ghost-event";
  ghostEvent.style.top = top + "px";
  ghostEvent.style.height = (HOUR_HEIGHT / 2) + "px"; // default 30-min preview
  ghostEvent.style.left = "2px";
  ghostEvent.style.width = "calc(100% - 4px)";
  col.appendChild(ghostEvent);

  creatingEvent = true;
  pendingCreate = false;

  // Block scroll + attach resize handlers
  document.addEventListener("touchmove", _touchCreateMove, { passive: false });
  document.addEventListener("touchend", _touchCreateEnd, { passive: true });
  document.addEventListener("touchcancel", _touchCreateCancel, { passive: true });
}

function _touchCreateMove(e) {
  if (!creatingEvent || !ghostEvent) return;
  e.preventDefault(); // stop the scroll

  const t = e.touches[0];
  if (!t) return;

  const col = document.querySelector(`.gcal-day-col[data-date="${createColDate}"]`);
  if (!col) return;

  const rect = col.getBoundingClientRect();
  const startY = _clampColY(createStartY - rect.top);
  const currentY = _clampColY(t.clientY - rect.top);
  const delta = currentY - startY;

  if (delta < 0) return;

  const mins = (delta / HOUR_HEIGHT) * 60;
  const snapped = Math.round(mins / SNAP) * SNAP;
  const height = (snapped / 60) * HOUR_HEIGHT;
  ghostEvent.style.height = Math.max(height, HOUR_HEIGHT / 4) + "px";

  // Live time badge
  const startMinutes = _clampMinutes(Math.round(((startY / HOUR_HEIGHT) * 60) / SNAP) * SNAP);
  const endMinutes = _clampMinutes(startMinutes + Math.max(snapped, SNAP));
  _showDragBadge(
    `${_fmtTimeLabel(startMinutes)} – ${_fmtTimeLabel(endMinutes)} · ${_fmtDurLabel(endMinutes - startMinutes)}`,
    t.clientX,
    t.clientY
  );
}

function _touchCreateEnd(e) {
  if (!creatingEvent) return;

  const col = document.querySelector(`.gcal-day-col[data-date="${createColDate}"]`);
  if (!col) { _touchCreateCancel(); return; }

  // Compute from current ghost height (more reliable than the touch end coord)
  const ghostTop = parseFloat(ghostEvent.style.top || "0");
  const ghostH = parseFloat(ghostEvent.style.height || "0");
  const startMinutes = Math.round(((ghostTop / HOUR_HEIGHT) * 60) / SNAP) * SNAP;
  const endMinutes = Math.round((((ghostTop + ghostH) / HOUR_HEIGHT) * 60) / SNAP) * SNAP;

  _touchCreateCleanup();

  // Default to a 30-min event if the finger never moved
  const finalEnd = endMinutes > startMinutes ? endMinutes : startMinutes + 30;
  currentDate = createColDate;
  openCreateModal(createColDate, toTime(startMinutes), toTime(finalEnd));
}

function _touchCreateCancel() {
  _touchCreateCleanup();
}

function _touchCreateCleanup() {
  _hideDragBadge();
  if (ghostEvent) { ghostEvent.remove(); ghostEvent = null; }
  creatingEvent = false;
  pendingCreate = false;
  document.removeEventListener("touchmove", _touchCreateMove);
  document.removeEventListener("touchend", _touchCreateEnd);
  document.removeEventListener("touchcancel", _touchCreateCancel);
}

function onCreatePointerMove(e) {
  if (!pendingCreate && !creatingEvent) return;
  if (e.pointerId !== activePointerId) return;

  const dY = e.clientY - createStartY;
  const dX = Math.abs(e.clientX - createStartX);

  if (!creatingEvent) {
    // Cancel if horizontal movement dominates (scroll)
    if (dX > Math.abs(dY) && dX > 8) {
      cancelCreate();
      return;
    }

    if (Math.abs(dY) < 8) return;

    // Commit to creating
    creatingEvent = true;
    pendingCreate = false;

    const col = document.querySelector(`.gcal-day-col[data-date="${createColDate}"]`);
    if (!col) return;

    const rect = col.getBoundingClientRect();
    const y = _clampColY(createStartY - rect.top);
    const minutesFromTop = (y / HOUR_HEIGHT) * 60;
    const snapped = _clampMinutes(Math.round(minutesFromTop / SNAP) * SNAP);
    const top = (snapped / 60) * HOUR_HEIGHT;

    ghostEvent = document.createElement("div");
    ghostEvent.className = "event-chip ghost-event";
    ghostEvent.style.top = top + "px";
    ghostEvent.style.height = "5px";
    ghostEvent.style.left = "2px";
    ghostEvent.style.width = "calc(100% - 4px)";
    col.appendChild(ghostEvent);
  }

  if (!ghostEvent) return;

  const col = document.querySelector(`.gcal-day-col[data-date="${createColDate}"]`);
  if (!col) return;

  const rect = col.getBoundingClientRect();
  const startY = _clampColY(createStartY - rect.top);
  const currentY = _clampColY(e.clientY - rect.top);
  const delta = currentY - startY;

  if (delta < 0) return;

  const mins = (delta / HOUR_HEIGHT) * 60;
  const snapped = Math.round(mins / SNAP) * SNAP;
  const height = (snapped / 60) * HOUR_HEIGHT;
  ghostEvent.style.height = Math.max(height, 5) + "px";

  // Live time badge: show the snapped [start – end] range + duration.
  const startMinutes = _clampMinutes(Math.round(((startY / HOUR_HEIGHT) * 60) / SNAP) * SNAP);
  const endMinutes = _clampMinutes(startMinutes + (snapped || SNAP));
  _showDragBadge(
    `${_fmtTimeLabel(startMinutes)} – ${_fmtTimeLabel(endMinutes)} · ${_fmtDurLabel(endMinutes - startMinutes)}`,
    e.clientX,
    e.clientY
  );
}

function onCreatePointerUp(e) {
  if (!pendingCreate && !creatingEvent) return;

  const wasCreating = creatingEvent;

  _hideDragBadge();
  if (ghostEvent) { ghostEvent.remove(); ghostEvent = null; }
  pendingCreate = false;
  creatingEvent = false;

  document.removeEventListener("pointermove", onCreatePointerMove);
  document.removeEventListener("pointerup", onCreatePointerUp);
  document.removeEventListener("pointercancel", cancelCreate);

  if (!wasCreating) return;

  const col = document.querySelector(`.gcal-day-col[data-date="${createColDate}"]`);
  if (!col) return;

  // getBoundingClientRect().top already includes the scroll container's
  // scrollTop offset — don't add it a second time (classic double-counting
  // bug that produced startMinutes > 1440 and an invalid time string).
  const rect = col.getBoundingClientRect();
  const startY = _clampColY(createStartY - rect.top);
  const endY   = _clampColY(e.clientY - rect.top);

  const startMinutes = _clampMinutes(Math.round(((startY / HOUR_HEIGHT) * 60) / SNAP) * SNAP);
  const rawEnd       = Math.round(((endY / HOUR_HEIGHT) * 60) / SNAP) * SNAP;
  // If the pointer barely moved, treat it as a click → default 30-min event.
  const endMinutes   = rawEnd > startMinutes
    ? _clampMinutes(rawEnd)
    : _clampMinutes(startMinutes + 30);

  const startTime = toTime(startMinutes);
  const endTime   = toTime(endMinutes);

  // Set currentDate to the column's date for new event creation
  currentDate = createColDate;

  openCreateModal(createColDate, startTime, endTime);
}

function cancelCreate() {
  _hideDragBadge();
  if (ghostEvent) { ghostEvent.remove(); ghostEvent = null; }
  pendingCreate = false;
  creatingEvent = false;
  document.removeEventListener("pointermove", onCreatePointerMove);
  document.removeEventListener("pointerup", onCreatePointerUp);
  document.removeEventListener("pointercancel", cancelCreate);
}

/* ══════════════════════════════════════════════════════════════
   17. TOUCH DRAG — Event chips (mobile)
   ══════════════════════════════════════════════════════════════ */

function attachChipTouchDrag(chipEl, ev, dateStr) {
  let clone = null;
  let dragging = false;
  let holdFired = false;
  let holdTimer = null;
  let startX, startY;
  const HOLD_MS = 400;
  const CANCEL_THRESHOLD = 10;

  chipEl.addEventListener("touchstart", (e) => {
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    dragging = false;
    holdFired = false;
    holdTimer = setTimeout(() => {
      holdFired = true;
      chipEl.style.opacity = "0.5";
      if (navigator.vibrate) navigator.vibrate(30);
    }, HOLD_MS);
  }, { passive: true });

  chipEl.addEventListener("touchmove", (e) => {
    const dx = Math.abs(e.touches[0].clientX - startX);
    const dy = Math.abs(e.touches[0].clientY - startY);

    // If long-press hasn't fired yet, cancel on movement (user is scrolling)
    if (!holdFired && (dx > CANCEL_THRESHOLD || dy > CANCEL_THRESHOLD)) {
      clearTimeout(holdTimer);
      holdTimer = null;
      return;                // let the browser scroll normally
    }

    if (!holdFired) return;  // still waiting for long-press

    // Long-press fired — activate drag on first move
    if (!dragging) {
      dragging = true;
      draggedTask = { ...ev, _sourceDate: dateStr };

      clone = chipEl.cloneNode(true);
      clone.style.cssText = `
        position: fixed;
        opacity: 0.75;
        pointer-events: none;
        z-index: 9999;
        width: ${chipEl.offsetWidth}px;
        height: ${chipEl.offsetHeight}px;
        transform: scale(1.04);
        box-shadow: 0 8px 24px rgba(0,0,0,.3);
      `;
      document.body.appendChild(clone);
    }

    e.preventDefault();
    e.stopPropagation();

    const x = e.touches[0].clientX;
    const y = e.touches[0].clientY;

    clone.style.left = (x - chipEl.offsetWidth / 2) + "px";
    clone.style.top = (y - chipEl.offsetHeight / 2) + "px";

    // Show snap line + time badge on the column under the touch point
    showTouchSnapLine(x, y, ev);
  }, { passive: false });

  chipEl.addEventListener("touchend", async (e) => {
    clearTimeout(holdTimer);
    holdTimer = null;
    chipEl.style.opacity = "";
    if (clone) { clone.remove(); clone = null; }
    clearTouchSnapLines();
    _hideDragBadge();

    if (!dragging || !draggedTask) {
      dragging = false;
      holdFired = false;
      return;
    }

    const x = e.changedTouches[0].clientX;
    const y = e.changedTouches[0].clientY;

    await handleTouchDrop(x, y, ev);
    draggedTask = null;
    dragging = false;
    holdFired = false;
  });
}

/* ══════════════════════════════════════════════════════════════
   18. TOUCH DRAG — Floating tasks (mobile)
   ══════════════════════════════════════════════════════════════ */

function attachFloatingTouchDrag(div, task) {
  let clone = null;
  let dragging = false;
  let holdFired = false;
  let holdTimer = null;
  let startX, startY;
  const HOLD_MS = 400;
  const CANCEL_THRESHOLD = 10;

  div.addEventListener("touchstart", (e) => {
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    dragging = false;
    holdFired = false;
    holdTimer = setTimeout(() => {
      holdFired = true;
      div.style.opacity = "0.5";
      if (navigator.vibrate) navigator.vibrate(30);
    }, HOLD_MS);
  }, { passive: true });

  div.addEventListener("touchmove", (e) => {
    const dx = Math.abs(e.touches[0].clientX - startX);
    const dy = Math.abs(e.touches[0].clientY - startY);

    // If long-press hasn't fired yet, cancel on movement (user is scrolling)
    if (!holdFired && (dx > CANCEL_THRESHOLD || dy > CANCEL_THRESHOLD)) {
      clearTimeout(holdTimer);
      holdTimer = null;
      return;
    }

    if (!holdFired) return;

    if (!dragging) {
      dragging = true;
      draggedTask = { ...task, type: "project" };

      clone = div.cloneNode(true);
      clone.style.cssText = `
        position: fixed;
        opacity: 0.8;
        pointer-events: none;
        z-index: 9999;
        width: ${div.offsetWidth}px;
        transform: scale(1.05);
        box-shadow: 0 8px 24px rgba(0,0,0,.3);
      `;
      document.body.appendChild(clone);
    }

    e.preventDefault();

    const x = e.touches[0].clientX;
    const y = e.touches[0].clientY;

    clone.style.left = (x - div.offsetWidth / 2) + "px";
    clone.style.top = (y - 30) + "px";

    showTouchSnapLine(x, y, task);
  }, { passive: false });

  div.addEventListener("touchend", async (e) => {
    clearTimeout(holdTimer);
    holdTimer = null;
    div.style.opacity = "";
    if (clone) { clone.remove(); clone = null; }
    clearTouchSnapLines();
    _hideDragBadge();

    if (!dragging || !draggedTask) {
      dragging = false;
      holdFired = false;
      return;
    }

    const x = e.changedTouches[0].clientX;
    const y = e.changedTouches[0].clientY;

    // Find column under touch
    const col = getColumnUnderPoint(x, y);
    if (col) {
      const rect = col.getBoundingClientRect();
      const relY = _clampColY(y - rect.top);
      const minutesFromTop = (relY / HOUR_HEIGHT) * 60;
      const snapped = _clampMinutes(Math.round(minutesFromTop / SNAP) * SNAP);
      const start = toTime(snapped);
      const end = calculateEndTime(start, 30);
      const targetDate = col.dataset.date;

      await fetch(`/api/v2/project-tasks/${draggedTask.task_id}/schedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_date: targetDate, start_time: start, end_time: end })
      });

      showToast("Task scheduled", "success");
      loadAllEvents();
    }

    draggedTask = null;
    dragging = false;
    holdFired = false;
  });
}

/* ── Shared touch helpers ── */

function getColumnUnderPoint(x, y) {
  const cols = document.querySelectorAll(".gcal-day-col");
  for (const col of cols) {
    const rect = col.getBoundingClientRect();
    if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
      return col;
    }
  }
  return null;
}

function showTouchSnapLine(x, y, ev) {
  clearTouchSnapLines();
  const col = getColumnUnderPoint(x, y);
  if (!col) { _hideDragBadge(); return; }

  const rect = col.getBoundingClientRect();
  const relY = _clampColY(y - rect.top);
  const minutesFromTop = (relY / HOUR_HEIGHT) * 60;
  const snapped = _clampMinutes(Math.round(minutesFromTop / SNAP) * SNAP);
  const top = (snapped / 60) * HOUR_HEIGHT;

  // Live badge next to the finger
  let durMin = 30;
  if (ev?.start_time && ev?.end_time) {
    durMin = Math.max(SNAP, minutes(ev.end_time) - minutes(ev.start_time));
  }
  const endM = _clampMinutes(snapped + durMin);
  _showDragBadge(
    `${_fmtTimeLabel(snapped)} – ${_fmtTimeLabel(endM)} · ${_fmtDurLabel(endM - snapped)}`,
    x,
    y
  );

  const line = document.createElement("div");
  line.className = "snap-line";
  line.style.top = top + "px";
  col.appendChild(line);
}

function clearTouchSnapLines() {
  document.querySelectorAll(".snap-line").forEach(l => l.remove());
}

async function handleTouchDrop(x, y, ev) {
  const col = getColumnUnderPoint(x, y);
  if (!col) return;

  const targetDate = col.dataset.date;
  const rect = col.getBoundingClientRect();
  const relY = _clampColY(y - rect.top);
  const minutesFromTop = (relY / HOUR_HEIGHT) * 60;
  const snapped = _clampMinutes(Math.round(minutesFromTop / SNAP) * SNAP);

  const duration = minutes(ev.end_time) - minutes(ev.start_time);
  const newStart = toTime(snapped);
  const newEnd = toTime(snapped + duration);

  if (ev.type === "project") {
    await fetch(`/api/v2/project-tasks/${ev.task_id}/schedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_date: targetDate, start_time: newStart, end_time: newEnd })
    });
  } else {
    await fetch(`/api/v2/events/${ev.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan_date: targetDate,
        start_time: newStart,
        end_time: newEnd,
        title: ev.title
      })
    });
  }

  showToast("Event moved", "success");
  loadAllEvents();
}

/* ══════════════════════════════════════════════════════════════
   19. SMART PLANNER
   ══════════════════════════════════════════════════════════════ */

async function runSmartPlanner() {
  const input = document.getElementById("smart-input");
  const text = input.value.trim();
  if (!text) return;

  try {
    const res = await fetch("/api/v2/smart-create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: currentDate, text })
    });

    if (!res.ok) {
      showToast("Smart planner failed", "error");
      return;
    }

    input.value = "";
    showToast("Events created", "success");
    loadAllEvents();
  } catch (err) {
    showToast("Smart planner failed", "error");
  }
}

async function runAISmartPlanner() {
  const input = document.getElementById("smart-input");
  const text = input.value.trim();
  if (!text) return;

  showToast("AI is parsing your input…", "info");

  try {
    const res = await fetch("/api/v2/ai-parse-events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: currentDate, text })
    });

    if (!res.ok) {
      showToast("AI parsing failed", "error");
      return;
    }

    const data = await res.json();
    if (data.created_count > 0) {
      input.value = "";
      showToast(`Created ${data.created_count} event${data.created_count > 1 ? "s" : ""}`, "success");
      loadAllEvents();
    } else {
      showToast("AI couldn't parse any events. Try being more specific.", "error");
    }
  } catch {
    showToast("AI parsing failed", "error");
  }
}

/* ══════════════════════════════════════════════════════════════
   20. NUMBER CONTROL (scroll wheel on task fields)
   ══════════════════════════════════════════════════════════════ */

document.addEventListener("wheel", function (e) {
  const wrapper = e.target.closest(".number-control");
  if (!wrapper) return;

  e.preventDefault();
  const input = wrapper.querySelector("input");
  const step = parseFloat(input.step || 1);
  let value = parseFloat(input.value || 0);

  if (e.deltaY < 0) value += step;
  else value -= step;

  if (value < 0) value = 0;
  if (value > 999) value = 999;

  input.value = parseFloat(value.toFixed(2));
}, { passive: false });

/* ══════════════════════════════════════════════════════════════
   21. CLOSE POPOVER ON OUTSIDE CLICK
   ══════════════════════════════════════════════════════════════ */

document.addEventListener("click", (e) => {
  const popover = document.getElementById("event-popover");
  if (!popover || popover.classList.contains("hidden")) return;
  if (popover.contains(e.target)) return;
  if (e.target.closest(".event-chip")) return;
  closePopover();
});

/* ══════════════════════════════════════════════════════════════
   22. KEYBOARD SHORTCUTS
   ══════════════════════════════════════════════════════════════ */

document.addEventListener("keydown", (e) => {
  // Escape closes modals / popovers
  if (e.key === "Escape") {
    closePopover();
    if (!document.getElementById("modal").classList.contains("hidden")) {
      closeModal();
    }
    if (document.getElementById("task-card-modal").classList.contains("show")) {
      closeTaskCard();
    }
  }

  // T = go to today
  if (e.key === "t" && !e.ctrlKey && !e.metaKey && !isInputFocused()) {
    goToday();
  }

  // D / 3 / W = switch view
  if (!isInputFocused()) {
    if (e.key === "d") setView("day");
    if (e.key === "3") setView("3day");
    if (e.key === "w") setView("week");
  }
});

function isInputFocused() {
  const tag = document.activeElement?.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/* ══════════════════════════════════════════════════════════════
   23. INITIALIZATION
   ══════════════════════════════════════════════════════════════ */

document.addEventListener("DOMContentLoaded", () => {
  // Set initial view
  document.body.dataset.view = currentView;

  // Build the grid and load data
  buildGrid();
  loadAllEvents();

  // Bind modal form listeners — start/end time sync
  document.getElementById("start-time")?.addEventListener("change", updateEndFromStart);
  document.getElementById("end-time")?.addEventListener("change", updateDurationFromEnd);
  document.getElementById("reminder-select")?.addEventListener("change", handleReminderSelect);

  // Auto-scroll to current time (or 7 AM if not today)
  setTimeout(() => {
    const today = getISTDate();
    const dates = getVisibleDates();
    if (dates.includes(today)) {
      scrollToNow();
    } else {
      scrollTo7AM();
    }
  }, 400);

  // Start current-time-line updater
  startTimeLineUpdater();

  // Render feather icons
  if (window.feather) feather.replace();
});


// Plain text with its http(s) links made tappable (study-plan blocks carry
// links to recall cards and guides). Built with DOM nodes, never innerHTML,
// so a description can't inject markup. Same-site links open in this tab.
function renderLinkedText(el, text) {
  el.textContent = "";
  const re = /https?:\/\/[^\s)<>"']+/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    let url = m[0].replace(/[.,;:]+$/, "");
    if (m.index > last) el.appendChild(document.createTextNode(text.slice(last, m.index)));
    const a = document.createElement("a");
    let label = url, href = url;
    try {
      const u = new URL(url);
      if (u.host === location.host || /dailyplanner-[a-z0-9]+\.onrender\.com$/.test(u.host)) {
        href = u.pathname + u.search;
        const slugs = (u.searchParams.get("slugs") || "").split(",").filter(Boolean);
        label = u.pathname.replace(/^\/interview-prep\//, "").replace(/\/$/, "")
          + (slugs.length > 3 ? " (" + slugs.length + " cards)" : slugs.length ? " (" + slugs.join(", ") + ")" : "");
      } else {
        a.target = "_blank"; a.rel = "noopener";
      }
    } catch (e) { /* keep the raw url */ }
    a.href = href; a.textContent = label;
    a.style.wordBreak = "break-word";
    el.appendChild(a);
    last = m.index + url.length;
    re.lastIndex = last;
  }
  if (last < text.length) el.appendChild(document.createTextNode(text.slice(last)));
}
