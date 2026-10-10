/* ============================================================
   Health Dashboard — Modern SaaS Habit Tracker
   ============================================================ */

// Route writes through dpFetch (sync-queue.js) so offline saves
// queue + replay automatically. GETs pass through unchanged.
//
// NOTE: this MUST not be named `fetch`. Top-level `const` in a classic
// script lands in the global lexical environment, which shadows
// `window.fetch` for every other script that does an unqualified
// `fetch(...)` call. sync-queue.js's dpFetch internally calls
// `fetch(url, opts)` — bind it to our wrapper and you get an infinite
// recursion (RangeError: Maximum call stack size exceeded). Use the
// `_fetch` convention the rest of the codebase uses.
const _fetch = (window.dpFetch && ((u, o) => window.dpFetch(u, o))) || window.fetch.bind(window);

// --------------- State ---------------
let currentDate = "";
let saveHealthTimer = null;
let habitSaveTimers = {};

// --------------- IST Timezone ---------------
function getISTDate() {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

function getISTDateObj() {
  const str = new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" });
  return new Date(str);
}

// --------------- Initialization ---------------
document.addEventListener("DOMContentLoaded", () => {
  currentDate = getISTDate();
  renderDateStrip();
  loadHealth(currentDate);
  loadWeeklyStats();
  loadHeatmap();
  if (typeof feather !== "undefined") feather.replace();

  // Close habit sheet on overlay click
  const sheet = document.getElementById("habit-sheet");
  if (sheet) {
    sheet.addEventListener("click", (e) => {
      if (e.target === sheet) closeHabitSheet();
    });
  }
});

// ============================================================
//  DATE STRIP — 30-day scrollable window with nav arrows and
//  optional "jump to any date" picker.
// ============================================================
const STRIP_DAYS = 30;           // how many days to render at once
const STRIP_STEP = 14;           // how many days each ◀ / ▶ shifts
let stripOffsetDays = 0;         // 0 = window ends today; positive = older window

function _stripEndDate() {
  // The latest date visible in the strip (right edge). Offset 0 = today.
  const today = getISTDateObj();
  today.setDate(today.getDate() - stripOffsetDays);
  return today;
}

function renderDateStrip() {
  const strip = document.getElementById("date-strip");
  if (!strip) return;

  const endDate = _stripEndDate();
  const todayStr = getISTDate();
  const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // Wrapper with nav arrows + scroller inside. Rebuild on every call so
  // shifting the offset redraws cleanly.
  strip.innerHTML = `
    <button type="button" class="date-nav-btn" id="date-nav-prev"
            aria-label="Earlier dates" title="Earlier (${STRIP_STEP} days back)">‹</button>
    <div class="date-strip-scroll" id="date-strip-scroll"></div>
    <button type="button" class="date-nav-btn" id="date-nav-next"
            aria-label="Later dates" title="Later (${STRIP_STEP} days forward)"
            ${stripOffsetDays === 0 ? "disabled" : ""}>›</button>
    <button type="button" class="date-today-btn" id="date-today-btn"
            title="Jump to today">Today</button>
  `;

  const scroll = document.getElementById("date-strip-scroll");

  // Render STRIP_DAYS pills ending at endDate
  for (let i = STRIP_DAYS - 1; i >= 0; i--) {
    const d = new Date(endDate);
    d.setDate(d.getDate() - i);
    const dateStr = d.toLocaleDateString("en-CA");
    const dayName = dayNames[d.getDay()];
    const dayNum = d.getDate();
    const monthName = monthNames[d.getMonth()];
    const isFirstOfMonth = d.getDate() === 1 || i === STRIP_DAYS - 1;

    const pill = document.createElement("button");
    pill.type = "button";
    pill.className = "date-pill";
    if (dateStr === todayStr) pill.classList.add("today");
    if (dateStr === currentDate) pill.classList.add("active");
    pill.dataset.date = dateStr;

    pill.innerHTML = `
      <span class="dp-day">${dayName}</span>
      <span class="dp-num">${dayNum}</span>
      ${isFirstOfMonth ? `<span class="dp-month">${monthName}</span>` : ""}
      <span class="dp-dot"></span>
    `;

    pill.addEventListener("click", () => {
      currentDate = dateStr;
      document.querySelectorAll(".date-pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      loadHealth(currentDate);
      loadHeatmap();
    });

    scroll.appendChild(pill);
  }

  // Nav button wiring
  document.getElementById("date-nav-prev")?.addEventListener("click", () => {
    stripOffsetDays += STRIP_STEP;
    renderDateStrip();
    loadHeatmap();
  });
  document.getElementById("date-nav-next")?.addEventListener("click", () => {
    stripOffsetDays = Math.max(0, stripOffsetDays - STRIP_STEP);
    renderDateStrip();
    loadHeatmap();
  });
  document.getElementById("date-today-btn")?.addEventListener("click", () => {
    stripOffsetDays = 0;
    currentDate = getISTDate();
    renderDateStrip();
    loadHealth(currentDate);
    loadHeatmap();
  });

  // After render, ensure the current-date pill is visible. For the default
  // window (offset=0), scroll all the way to the right so "today" sits
  // at the visible edge.
  requestAnimationFrame(() => {
    const active = scroll.querySelector(".date-pill.active");
    if (active) {
      active.scrollIntoView({ block: "nearest", inline: "center", behavior: "auto" });
    } else if (stripOffsetDays === 0) {
      scroll.scrollLeft = scroll.scrollWidth;
    }
  });
}

// Mark dots for dates that have data (called after heatmap loads)
function markDateStripDots(heatmapData) {
  document.querySelectorAll(".date-pill").forEach(pill => {
    const d = pill.dataset.date;
    const dot = pill.querySelector(".dp-dot");
    if (dot) {
      if (heatmapData[d] && heatmapData[d] > 0) {
        dot.classList.add("has-data");
      } else {
        dot.classList.remove("has-data");
      }
    }
  });
}

// ============================================================
//  MAIN DATA LOADER
// ============================================================
async function loadHealth(date) {
  try {
    const res = await _fetch(`/api/v2/daily-health?date=${date}`);
    if (!res.ok) {
      // Surface the actual failure mode in the toast so the next bug
      // report tells us whether it's auth (401/302), a 500, etc.
      const snippet = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} — ${snippet.slice(0, 120) || res.statusText}`);
    }
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    if (!ct.includes("application/json")) {
      // Logged-out users get an HTML redirect to /login here. Saying so
      // is far more useful than the generic "failed to load" toast.
      throw new Error("Got HTML, not JSON — likely logged out. Reload and sign in.");
    }
    const data = await res.json();

    // --- Health metric fields ---
    const weightEl = document.getElementById("health-weight");
    const heightEl = document.getElementById("health-height");
    const moodEl = document.getElementById("health-mood");
    const energyEl = document.getElementById("health-energy");
    const notesEl = document.getElementById("health-notes");

    if (weightEl) weightEl.value = data.weight || "";
    if (heightEl) heightEl.value = data.height || "";
    if (moodEl) moodEl.value = data.mood || "neutral";
    if (energyEl) energyEl.value = data.energy_level || 5;
    if (notesEl) notesEl.value = data.notes || "";

    updateEnergyLabel();
    calculateBMI();

    // --- Habits ---
    if (data.habits) {
      renderHabits(data.habits);
    }

    // --- Overview cards ---
    updateRing(data.habit_percent || 0);
    updateHealthScore(data);

    const streakEl = document.getElementById("streak-value");
    if (streakEl) streakEl.textContent = data.streak || 0;

    if (typeof feather !== "undefined") feather.replace();
  } catch (err) {
    console.error("loadHealth error:", err);
    const msg = (err && err.message) ? err.message : String(err);
    if (typeof showToast === "function") showToast("Health: " + msg, "error");
  }
}

// ============================================================
//  COMPLETION RING
// ============================================================
const RING_CIRCUMFERENCE = 2 * Math.PI * 52; // ~326.73

function updateRing(percent) {
  const fill = document.getElementById("ring-fill");
  const pctEl = document.getElementById("ring-percent");
  if (!fill) return;

  const offset = RING_CIRCUMFERENCE * (1 - percent / 100);
  fill.style.transition = "stroke-dashoffset 0.8s ease";
  fill.setAttribute("stroke-dasharray", RING_CIRCUMFERENCE);
  fill.setAttribute("stroke-dashoffset", offset);

  if (pctEl) pctEl.textContent = `${Math.round(percent)}%`;
}

// ============================================================
//  HEALTH SCORE
// ============================================================
function updateHealthScore(data) {
  const el = document.getElementById("health-score");
  if (!el) return;

  const habitPercent = data.habit_percent || 0;
  const energy = data.energy_level || 0;
  const mood = data.mood || "neutral";
  const streak = data.streak || 0;

  // habitScore: 0-50
  const habitScore = habitPercent * 0.5;

  // energyScore: 0-15
  const energyScore = (energy / 10) * 15;

  // moodScore: 0-10
  const moodMap = { great: 10, good: 8, neutral: 6, low: 3, bad: 1 };
  const moodScore = moodMap[mood] || 6;

  // streakScore: 0-15
  const streakScore = Math.min(streak * 1.5, 15);

  // weightScore: 0-10, earned by having a weight on record. It used to be
  // a constant 10, which meant a blank day still scored 10 and the score
  // could never reach 0 — it rewarded nothing.
  const weightScore = data.weight ? 10 : 0;

  const total = Math.round(habitScore + energyScore + moodScore + streakScore + weightScore);
  el.textContent = total;
}

// ============================================================
//  WEEKLY STATS
// ============================================================
async function loadWeeklyStats() {
  try {
    const res = await _fetch("/api/v2/weekly-health");
    if (!res.ok) return;
    const data = await res.json();

    const avgEl = document.getElementById("weekly-avg");
    if (avgEl) avgEl.textContent = `${Math.round(data.weekly_avg || 0)}%`;
  } catch (err) {
    console.error("loadWeeklyStats error:", err);
  }
}

// ============================================================
//  HEATMAP
// ============================================================
async function loadHeatmap() {
  try {
    // Pass the current strip window so dots populate for the visible range
    // (including when the user has shifted back in time with the nav arrows).
    const end = _stripEndDate();
    const endStr = end.toLocaleDateString("en-CA");
    const start = new Date(end);
    start.setDate(start.getDate() - (STRIP_DAYS - 1));
    const startStr = start.toLocaleDateString("en-CA");

    const res = await _fetch(`/api/v2/heatmap?start=${startStr}&end=${endStr}`);
    if (!res.ok) return;
    const data = await res.json();
    renderHeatmap(data, startStr, endStr);
    markDateStripDots(data);
  } catch (err) {
    console.error("loadHeatmap error:", err);
  }
}

function renderHeatmap(data, startStr, endStr) {
  const container = document.getElementById("heatmap");
  if (!container) return;
  container.innerHTML = "";

  // If the caller didn't supply a range, fall back to "last 30 days from
  // today" — matches the original behaviour on older code paths.
  let end, start;
  if (endStr && startStr) {
    end = new Date(endStr + "T00:00:00");
    start = new Date(startStr + "T00:00:00");
  } else {
    end = getISTDateObj();
    start = new Date(end);
    start.setDate(start.getDate() - 29);
  }

  const days = Math.round((end - start) / (1000 * 60 * 60 * 24)) + 1;
  for (let i = 0; i < days; i++) {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    const dateStr = d.toLocaleDateString("en-CA");
    const pct = data[dateStr] || 0;

    const cell = document.createElement("div");
    cell.className = "heatmap-cell";
    cell.title = `${dateStr}: ${Math.round(pct)}%`;

    if (pct === 0) {
      cell.classList.add("level-0");
    } else if (pct <= 25) {
      cell.classList.add("level-1");
    } else if (pct <= 50) {
      cell.classList.add("level-2");
    } else if (pct <= 75) {
      cell.classList.add("level-3");
    } else {
      cell.classList.add("level-4");
    }

    container.appendChild(cell);
  }
}

// ============================================================
//  HABIT GRID
// ============================================================
function renderHabits(habits) {
  const grid = document.getElementById("habit-grid");
  if (!grid) return;
  grid.innerHTML = "";

  habits.forEach(habit => {
    const card = createHabitCard(habit);
    grid.appendChild(card);
  });

  if (typeof feather !== "undefined") feather.replace();
}

function createHabitCard(habit) {
  const card = document.createElement("div");
  card.className = "habit-card";
  card.dataset.habitId = habit.id;
  card.dataset.goal = habit.goal || 1;

  const value = parseFloat(habit.value) || 0;
  const goal = parseFloat(habit.goal) || 1;
  const pct = Math.min(Math.round((value / goal) * 100), 100);
  const isBoolean = habit.habit_type === "boolean" || (habit.unit || "").toUpperCase() === "BOOLEAN";
  const isComplete = value >= goal;
  const step = getStepForUnit(habit.unit);

  if (isComplete) card.classList.add("completed");

  const goalText = isBoolean ? "Yes / No" : `Goal: ${goal} ${habit.unit || ""}`;

  card.innerHTML = `
    <div class="habit-card-header">
      <div class="habit-card-info">
        <span class="habit-card-name">${escapeHtml(habit.name)}</span>
        <span class="habit-card-goal">${escapeHtml(goalText)}</span>
      </div>
      <div class="habit-card-actions">
        <button class="habit-action-btn" onclick="editHabit('${habit.id}')" title="Edit">&#9999;&#65039;</button>
        <button class="habit-action-btn habit-delete-btn" onclick="deleteHabit('${habit.id}')" title="Delete">&#128465;</button>
      </div>
    </div>

    ${isBoolean ? buildBooleanInput(habit) : buildNumericInput(habit, step)}

    <div class="habit-progress-row">
      <div class="habit-progress-bar">
        <div class="habit-progress-fill" style="width:${pct}%"></div>
      </div>
      <span class="habit-progress-pct">${pct}%</span>
    </div>

    <!-- Shown only when the card has the .completed class (CSS driven).
         Gives a strong visual signal that the day's goal was reached. -->
    <div class="habit-complete-badge" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
           stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="20 6 9 17 4 12"/>
      </svg>
      <span>Goal reached</span>
    </div>

    <div class="habit-weekly-dots" data-habit-id="${habit.id}"></div>
  `;

  loadWeeklyDots(habit.id);
  return card;
}

function buildNumericInput(habit, step) {
  const value = parseFloat(habit.value) || 0;
  const goal = parseFloat(habit.goal) || 1;
  // NOTE: every habit.id interpolation is wrapped in single quotes so
  // UUID IDs like "abc12345-6789-def" don't get parsed as JavaScript
  // subtraction by the inline onclick/onchange handlers.
  return `
    <div class="habit-input-row">
      <button class="habit-adjust-btn" onclick="stepHabit('${habit.id}', -${step})">&#8722;</button>
      <div class="habit-value-wrap">
        <input type="number" class="habit-value-input" id="habit-val-${habit.id}"
               value="${value}" min="0" step="${step}"
               data-habit-id="${habit.id}"
               inputmode="decimal"
               onchange="onHabitValueChange('${habit.id}')"
               onfocus="this.select()">
        <span class="habit-value-unit">${escapeHtml((habit.unit || "").toLowerCase())}</span>
      </div>
      <button class="habit-adjust-btn" onclick="stepHabit('${habit.id}', ${step})">&#43;</button>
    </div>
    <div class="habit-slider-row">
      <input type="range" class="habit-slider" min="0" max="${goal * 1.5}" step="${step}" value="${value}"
             oninput="onSliderChange('${habit.id}', this.value)">
    </div>
  `;
}

function buildBooleanInput(habit) {
  const value = parseFloat(habit.value) || 0;
  const isOn = value >= 1;
  return `
    <div class="habit-toggle-row">
      <button class="habit-toggle ${isOn ? "on" : ""}"
              id="habit-val-${habit.id}"
              data-habit-id="${habit.id}"
              onclick="toggleBooleanHabit('${habit.id}')">
      </button>
      <span class="habit-toggle-label">${isOn ? "Done" : "Not yet"}</span>
    </div>
  `;
}

function getStepForUnit(unit) {
  if (!unit) return 1;
  const u = unit.toLowerCase();
  if (u === "steps") return 500;
  if (u === "ml" || u === "l") return 250;
  if (u === "mins" || u === "minutes" || u === "min") return 5;
  if (u === "km") return 0.5;
  if (u === "hours" || u === "hrs") return 0.5;
  if (u === "pages") return 5;
  if (u === "reps") return 5;
  return 1;
}

function onSliderChange(habitId, val) {
  const input = document.getElementById(`habit-val-${habitId}`);
  if (input) input.value = val;
  updateHabitCardProgress(habitId, parseFloat(val));
  debouncedSaveHabit(habitId, parseFloat(val));
}

// ============================================================
//  HABIT VALUE CHANGES
// ============================================================
function onHabitValueChange(habitId) {
  const input = document.getElementById(`habit-val-${habitId}`);
  if (!input) return;

  let val = parseFloat(input.value) || 0;
  if (val < 0) val = 0;
  input.value = val;

  updateHabitCardProgress(habitId, val);
  debouncedSaveHabit(habitId, val);
}

function stepHabit(habitId, delta) {
  const input = document.getElementById(`habit-val-${habitId}`);
  if (!input) return;

  let val = parseFloat(input.value) || 0;
  val = Math.max(0, val + delta);
  input.value = val;

  updateHabitCardProgress(habitId, val);
  debouncedSaveHabit(habitId, val);
}

function toggleBooleanHabit(habitId) {
  const btn = document.getElementById(`habit-val-${habitId}`);
  if (!btn) return;

  const isOn = btn.classList.toggle("on");
  const val = isOn ? 1 : 0;

  // Update label next to toggle
  const label = btn.parentElement?.querySelector(".habit-toggle-label");
  if (label) label.textContent = isOn ? "Done" : "Not yet";

  updateHabitCardProgress(habitId, val);
  debouncedSaveHabit(habitId, val);
}

function updateHabitCardProgress(habitId, value) {
  const card = document.querySelector(`.habit-card[data-habit-id="${habitId}"]`);
  if (!card) return;

  const fill = card.querySelector(".habit-progress-fill");
  const pctEl = card.querySelector(".habit-progress-pct");
  const slider = card.querySelector(".habit-slider");

  const goal = parseFloat(card.dataset.goal) || 1;
  const pct = Math.min(Math.round((value / goal) * 100), 100);

  if (fill) fill.style.width = `${pct}%`;
  if (pctEl) pctEl.textContent = `${pct}%`;
  if (slider) slider.value = value;

  if (value >= goal) {
    card.classList.add("completed");
  } else {
    card.classList.remove("completed");
  }

  // Update completion ring after any habit change
  recalcCompletionRing();
}

function recalcCompletionRing() {
  const cards = document.querySelectorAll(".habit-card");
  if (!cards.length) return;
  const completed = document.querySelectorAll(".habit-card.completed").length;
  const pct = Math.round((completed / cards.length) * 100);
  updateRing(pct);
  document.getElementById("ring-percent").textContent = pct + "%";
}

// ============================================================
//  DEBOUNCED HABIT SAVE
// ============================================================
function debouncedSaveHabit(habitId, value) {
  if (habitSaveTimers[habitId]) clearTimeout(habitSaveTimers[habitId]);

  habitSaveTimers[habitId] = setTimeout(async () => {
    try {
      const res = await _fetch("/api/save-habit-value", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          habit_id: habitId,
          plan_date: currentDate,
          value: value
        })
      });

      if (!res.ok) throw new Error("Save failed");
      if (typeof showToast === "function") showToast("Habit saved", "success");

      // Refresh completion ring
      const healthRes = await _fetch(`/api/v2/daily-health?date=${currentDate}`);
      if (healthRes.ok) {
        const healthData = await healthRes.json();
        updateRing(healthData.habit_percent || 0);
        updateHealthScore(healthData);
      }
    } catch (err) {
      console.error("saveHabitValue error:", err);
      if (typeof showToast === "function") showToast("Failed to save habit", "error");
    }
  }, 500);
}

// ============================================================
//  WEEKLY DOTS
// ============================================================
async function loadWeeklyDots(habitId) {
  try {
    const res = await _fetch(`/api/v2/habit-weekly/${habitId}`);
    if (!res.ok) return;
    const values = await res.json();

    const container = document.querySelector(`.habit-weekly-dots[data-habit-id="${habitId}"]`);
    if (!container) return;
    container.innerHTML = "";

    const dayLabels = ["M", "T", "W", "T", "F", "S", "S"];
    values.forEach((val, i) => {
      const dot = document.createElement("span");
      dot.className = "weekly-dot";
      dot.title = dayLabels[i] || "";

      if (val >= 100) {
        dot.classList.add("dot-full");
      } else if (val > 0) {
        dot.classList.add("dot-partial");
      } else {
        dot.classList.add("dot-empty");
      }

      container.appendChild(dot);
    });
  } catch (err) {
    console.error("loadWeeklyDots error:", err);
  }
}

// ============================================================
//  HEALTH METRICS SAVE
// ============================================================
function autoSaveHealth() {
  if (saveHealthTimer) clearTimeout(saveHealthTimer);
  saveHealthTimer = setTimeout(() => saveHealth(), 1500);
}

async function saveHealth() {
  const weightEl = document.getElementById("health-weight");
  const heightEl = document.getElementById("health-height");
  const moodEl = document.getElementById("health-mood");
  const energyEl = document.getElementById("health-energy");
  const notesEl = document.getElementById("health-notes");

  const payload = {
    plan_date: currentDate,
    weight: weightEl ? parseFloat(weightEl.value) || null : null,
    height: heightEl ? parseFloat(heightEl.value) || null : null,
    mood: moodEl ? moodEl.value : "neutral",
    energy_level: energyEl ? parseInt(energyEl.value) || 5 : 5,
    notes: notesEl ? notesEl.value : ""
  };

  try {
    const res = await _fetch("/api/v2/daily-health", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error("Save failed");
    if (typeof showToast === "function") showToast("Health data saved", "success");

    calculateBMI();

    // Refresh score
    const healthRes = await _fetch(`/api/v2/daily-health?date=${currentDate}`);
    if (healthRes.ok) {
      const data = await healthRes.json();
      updateHealthScore(data);
    }
  } catch (err) {
    console.error("saveHealth error:", err);
    if (typeof showToast === "function") showToast("Failed to save health data", "error");
  }
}

// ============================================================
//  BMI CALCULATION
// ============================================================
function calculateBMI() {
  const weightEl = document.getElementById("health-weight");
  const heightEl = document.getElementById("health-height");
  const bmiEl = document.getElementById("bmi-display");
  if (!bmiEl) return;

  const weight = weightEl ? parseFloat(weightEl.value) : 0;
  const height = heightEl ? parseFloat(heightEl.value) : 0;

  if (!weight || !height || height === 0) {
    bmiEl.textContent = "--";
    bmiEl.className = "bmi-display";
    return;
  }

  const heightM = height / 100;
  const bmi = weight / (heightM * heightM);
  const rounded = bmi.toFixed(1);

  bmiEl.textContent = rounded;
  bmiEl.className = "bmi-display";

  if (bmi < 18.5) {
    bmiEl.classList.add("bmi-under");
  } else if (bmi < 25) {
    bmiEl.classList.add("bmi-normal");
  } else if (bmi < 30) {
    bmiEl.classList.add("bmi-over");
  } else {
    bmiEl.classList.add("bmi-obese");
  }
}

// ============================================================
//  ENERGY LABEL
// ============================================================
function updateEnergyLabel() {
  const energyEl = document.getElementById("health-energy");
  const labelEl = document.getElementById("energy-label");
  if (!energyEl || !labelEl) return;

  const val = parseInt(energyEl.value) || 5;
  const labels = {
    1: "Exhausted", 2: "Very Low", 3: "Low", 4: "Below Avg",
    5: "Average", 6: "Above Avg", 7: "Good", 8: "High",
    9: "Very High", 10: "Peak"
  };
  labelEl.textContent = labels[val] || `${val}/10`;
}

// ============================================================
//  HABIT SHEET (ADD / EDIT MODAL)
// ============================================================
function openHabitSheet() {
  const sheet = document.getElementById("habit-sheet");
  if (!sheet) return;

  sheet.classList.remove("hidden");
  sheet.dataset.editId = "";

  // Clear fields
  const nameEl = document.getElementById("sheet-name");
  const unitEl = document.getElementById("sheet-unit");
  const goalEl = document.getElementById("sheet-goal");
  const startEl = document.getElementById("sheet-start");
  const titleEl = document.getElementById("sheet-title");

  if (nameEl) nameEl.value = "";
  if (unitEl) unitEl.value = "";
  if (goalEl) goalEl.value = "";
  if (startEl) startEl.value = getISTDate();
  if (titleEl) titleEl.textContent = "Add Habit";

  setHabitType("number");
}

function closeHabitSheet() {
  const sheet = document.getElementById("habit-sheet");
  if (sheet) sheet.classList.add("hidden");
}

function setHabitType(type) {
  const sheet = document.getElementById("habit-sheet");
  if (!sheet) return;

  sheet.dataset.habitType = type;

  // Toggle active state on type buttons
  document.querySelectorAll(".type-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.type === type);
  });

  // Show/hide unit+goal row for boolean habits
  const unitGoalRow = document.getElementById("sheet-unit")?.closest(".sheet-row");

  if (type === "boolean") {
    if (unitGoalRow) unitGoalRow.style.display = "none";
  } else {
    if (unitGoalRow) unitGoalRow.style.display = "";
  }
}

async function submitHabitSheet() {
  const sheet = document.getElementById("habit-sheet");
  if (!sheet) return;

  const editId = sheet.dataset.editId;
  const habitType = sheet.dataset.habitType || "number";

  const name = document.getElementById("sheet-name")?.value?.trim();
  const unit = document.getElementById("sheet-unit")?.value?.trim() || "";
  const goal = parseFloat(document.getElementById("sheet-goal")?.value) || (habitType === "boolean" ? 1 : 0);
  const startDate = document.getElementById("sheet-start")?.value || getISTDate();

  if (!name) {
    if (typeof showToast === "function") showToast("Habit name is required", "error");
    return;
  }

  try {
    let res;
    if (editId) {
      // Edit existing habit
      res = await _fetch(`/api/habits/${editId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, unit, goal })
      });
    } else {
      // Add new habit
      res = await _fetch("/api/habits/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          unit: habitType === "boolean" ? "boolean" : unit,
          goal: habitType === "boolean" ? 1 : goal,
          start_date: startDate,
          habit_type: habitType
        })
      });
    }

    if (!res.ok) throw new Error("Save failed");

    closeHabitSheet();
    if (typeof showToast === "function") showToast(editId ? "Habit updated" : "Habit added", "success");
    loadHealth(currentDate);
  } catch (err) {
    console.error("submitHabitSheet error:", err);
    if (typeof showToast === "function") showToast("Failed to save habit", "error");
  }
}

async function editHabit(id) {
  try {
    const res = await _fetch(`/api/habits/${id}`);
    if (!res.ok) throw new Error("Failed to fetch habit");
    const habit = await res.json();

    const sheet = document.getElementById("habit-sheet");
    if (!sheet) return;

    sheet.classList.remove("hidden");
    sheet.dataset.editId = id;

    const titleEl = document.getElementById("sheet-title");
    const nameEl = document.getElementById("sheet-name");
    const unitEl = document.getElementById("sheet-unit");
    const goalEl = document.getElementById("sheet-goal");
    const startEl = document.getElementById("sheet-start");

    if (titleEl) titleEl.textContent = "Edit Habit";
    if (nameEl) nameEl.value = habit.name || "";
    if (unitEl) unitEl.value = habit.unit || "";
    if (goalEl) goalEl.value = habit.goal || "";
    if (startEl) startEl.value = habit.start_date || getISTDate();

    setHabitType(habit.habit_type === "boolean" ? "boolean" : "number");
  } catch (err) {
    console.error("editHabit error:", err);
    if (typeof showToast === "function") showToast("Failed to load habit", "error");
  }
}

function deleteHabit(id) {
  // Remove card from DOM immediately (optimistic)
  const card = document.querySelector(`.habit-card[data-habit-id="${id}"]`);
  if (card) card.remove();

  // Show undo toast
  let undone = false;
  if (typeof showToast === "function") {
    showToast("Habit deleted. Undo?", "success");
  }

  // Create an undo container
  const undoToast = document.createElement("div");
  undoToast.className = "undo-toast";
  undoToast.innerHTML = `
    <span>Habit deleted</span>
    <button class="undo-btn" id="undo-delete-${id}">Undo</button>
  `;
  document.body.appendChild(undoToast);
  requestAnimationFrame(() => undoToast.classList.add("show"));

  const undoBtn = document.getElementById(`undo-delete-${id}`);
  if (undoBtn) {
    undoBtn.addEventListener("click", async () => {
      undone = true;
      undoToast.classList.remove("show");
      setTimeout(() => undoToast.remove(), 300);

      try {
        await _fetch("/api/habits/restore", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ habit_id: id })
        });
        loadHealth(currentDate);
        if (typeof showToast === "function") showToast("Habit restored", "success");
      } catch (err) {
        console.error("restoreHabit error:", err);
      }
    });
  }

  // Perform delete after 4 seconds if not undone
  setTimeout(async () => {
    undoToast.classList.remove("show");
    setTimeout(() => undoToast.remove(), 300);

    if (undone) return;

    try {
      await _fetch("/api/habits/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ habit_id: id })
      });
    } catch (err) {
      console.error("deleteHabit error:", err);
      if (typeof showToast === "function") showToast("Failed to delete habit", "error");
      loadHealth(currentDate);
    }
  }, 4000);
}

// ============================================================
//  UTILITY
// ============================================================
function escapeHtml(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
