let lastHealthPayload = "";
async function loadHealth(date) {

  const res = await fetch(`/api/v2/daily-health?date=${date}`);
  const data = await res.json();

  // ------------------------
  // Basic health fields
  // ------------------------
  document.getElementById("weight").value = data.weight || "";
  document.getElementById("height").value = data.height || "";
  document.getElementById("energy").value = data.energy_level || 5;
  document.getElementById("mood").value = data.mood || "😊 Happy";
  document.getElementById("health-notes").value = data.notes || "";

  // ------------------------
  // Habits
  // ------------------------
  if (data.habits) {
    renderHabits(data.habits);
  }

  updateHabitCircle(data.habit_percent || 0);
  updateHealthScore(data);

  // ------------------------
  // Streak
  // ------------------------
  const badge = document.getElementById("streak-badge");
  if (badge) {
    badge.innerText = `🔥 ${data.streak || 0} day streak`;
  }
  // ------------------------
  // Weight Trend Graph
  // ------------------------
  if (data.weight_trend) {
    renderWeightTrend(data.weight_trend);
    renderWeightSparkline(data.weight_trend);
  }
  // ------------------------
  // Chart update
  // ------------------------
  if (
    window.healthChart &&
    window.healthChart.data &&
    window.healthChart.data.datasets &&
    window.healthChart.data.datasets.length > 2
  ) {
    window.healthChart.data.datasets[2].data = [data.habit_percent || 0];
    window.healthChart.update();
  }

  // ------------------------
  // Weekly + Monthly analytics (parallel)
  // ------------------------


}
function renderHabits(habits) {

  const container = document.getElementById("habitContainer");
  if (!container) return;

  container.innerHTML = "";

  habits.forEach(h => {

    const value = h.value ?? "";
    const goal  = h.goal ?? 0;
    const percent = goal > 0 ? Math.min(100, Math.round((value / goal) * 100)) : 0;

    container.innerHTML += `
      <div class="habit-item" data-id="${h.id}">

        <div class="habit-header habit-tap" data-id="${h.id}">
        <div class="habit-drag">☰</div>
          <div>
            <div class="habit-title">${h.name}</div>
            <div class="habit-sub">
              Goal: ${goal} ${h.unit}
            </div>
          </div>

          <div class="habit-actions">
            <button onclick="toggleEdit('${h.id}')">✏️</button>
            <button onclick="showHabitChart('${h.id}')">📈</button>
            <button onclick="deleteHabit('${h.id}')">🗑</button>
          </div>
        </div>

       <div class="habit-entry-block">
          <div class="entry-label">
            Today
            <span class="goal-label">
              (Goal: ${goal || "⚠ Set"} ${h.unit || ""})
            </span>
          </div>

          <input type="number"
                step="0.1"
                value="${value}"
                data-id="${h.id}"
                class="habit-input"
                placeholder="Enter value">
        </div>
        <div class="habit-save-indicator"></div>
        <div class="habit-progress">
          <div class="habit-progress-fill"
               style="width: ${percent}%"></div>
        </div>

        <div class="habit-edit-panel" id="edit-${h.id}">
          <input value="${h.name}" class="habit-name-edit" data-id="${h.id}">
          <input value="${h.unit}" class="habit-unit-edit" data-id="${h.id}">
          <input value="${goal}" class="habit-goal-edit" data-id="${h.id}">
        </div>

      </div>
    `;
  });

  wireHabitInputs();
  wireQuickTapHabits();
}
function updateHabitCircle(percent) {
  const circle = document.querySelector(".habit-circle circle:nth-child(2)");
  const text = document.querySelector(".circle-text");

  if (!circle) return;

  const radius = 50;
  const circumference = 2 * Math.PI * radius;

  circle.style.strokeDasharray = circumference;
  circle.style.strokeDashoffset =
    circumference - (percent / 100) * circumference;

  if (text) text.innerText = percent + "%";
}
function openHabitModal() {
  const modal = document.getElementById("habitModal");
  modal.classList.add("active");

  setTimeout(() => {
    document.getElementById("modalHabitName").focus();
  }, 100);
}

function closeHabitModal() {
  document.getElementById("habitModal").classList.remove("active");
}

async function submitHabitModal() {

  const name = document.getElementById("modalHabitName").value.trim();
  const unit = document.getElementById("modalHabitUnit").value.trim();
  const goal = parseFloat(document.getElementById("modalHabitGoal").value);

  if (!name || !unit || !goal) {
    showToast("All fields are required", "error");
    return;
  }

  const res = await fetch("/api/habits/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, unit, goal })
  });

  if (!res.ok) {
    showToast("Failed to add habit", "error");
    return;
  }

  const newHabit = await res.json();

  appendHabitToDOM(newHabit);

  showToast("Habit added", "success");

  // Clear inputs
  document.getElementById("modalHabitName").value = "";
  document.getElementById("modalHabitUnit").value = "";
  document.getElementById("modalHabitGoal").value = "";

  closeHabitModal();
}
function wireQuickTapHabits() {

  document.querySelectorAll(".habit-tap").forEach(header => {

    if (header.dataset.tapbound) return;
    header.dataset.tapbound = "1";

    header.addEventListener("click", async () => {

      const item = header.closest(".habit-item");
      const input = item.querySelector(".habit-input");

      if (!input) return;

      let current = parseFloat(input.value || 0);

      // increment amount
      const step = parseFloat(input.step || 1);

      current = Math.round((current + step) * 100) / 100;

      input.value = current;

      // trigger save
      input.dispatchEvent(new Event("input"));

      // visual pulse
      item.classList.add("tap-flash");
      setTimeout(() => item.classList.remove("tap-flash"), 300);

    });

  });

}
function appendHabitToDOM(h) {

  const container = document.getElementById("habitContainer");
  if (!container) return;

  const goal = h.goal ?? 0;
  const value = h.value ?? "";
  const percent = goal > 0
    ? Math.min(100, Math.round((value / goal) * 100))
    : 0;

  const div = document.createElement("div");
  div.className = "habit-item";
  div.dataset.id = h.id;

  div.innerHTML = `
    <div class="habit-header habit-tap" data-id="${h.id}">
      <div class="habit-drag">☰</div>
      <div>
        <div class="habit-title">${h.name}</div>
        <div class="habit-sub">
          ${goal > 0 ? `Goal: ${goal} ${h.unit}` : "⚠ Goal required"}
        </div>
      </div>

      <div class="habit-actions">
        <button onclick="toggleEdit('${h.id}')">✏️</button>
        <button onclick="showHabitChart('${h.id}')">📈</button>
        <button onclick="deleteHabit('${h.id}')">🗑</button>
      </div>
    </div>

      <div class="habit-entry-block">
      <div class="entry-label">Today</div>

      <input type="number"
            step="0.1"
            value="${value}"
            data-id="${h.id}"
            class="habit-input"
            placeholder="Enter value">
    </div>
    <div class="habit-save-indicator"></div>
    <div class="habit-progress">
      <div class="habit-progress-fill"
           style="width: ${percent}%"></div>
    </div>

    <div class="habit-edit-panel" id="edit-${h.id}">
      <input value="${h.name}" class="habit-name-edit" data-id="${h.id}">
      <input value="${h.unit}" class="habit-unit-edit" data-id="${h.id}">
      <input value="${goal}" class="habit-goal-edit" data-id="${h.id}">
    </div>
  `;

  container.appendChild(div);

  // 🔥 Attach input listener
  wireHabitInputs();
  wireQuickTapHabits();
  const goalInput = div.querySelector(".habit-goal-edit");

  if(goalInput){
      toggleEdit(h.id);
      goalInput.focus();
      goalInput.select();
    }
}
async function saveHealth() {

  const payload = {
    plan_date: document.getElementById("health-date").value,
    weight: document.getElementById("weight").value,
    height: document.getElementById("height").value,
    mood: document.getElementById("mood").value,
    energy_level: document.getElementById("energy").value,
    notes: document.getElementById("health-notes").value
  };

  const payloadString = JSON.stringify(payload);

  // 🚀 Prevent duplicate saves
  if (payloadString === lastHealthPayload) return;

  lastHealthPayload = payloadString;

  await fetch("/api/v2/daily-health", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: payloadString
  });

  showSaveToast();
}
function wireHabitInputs() {

  document.querySelectorAll(".habit-input").forEach(input => {

    if (input.dataset.bound) return;
    input.dataset.bound = "1";

    let timeout;

    input.addEventListener("input", () => {

      clearTimeout(timeout);

      timeout = setTimeout(async () => {

        const date = document.getElementById("health-date").value;
        const value = parseFloat(input.value) || 0;

        await fetch("/api/save-habit-value", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            habit_id: input.dataset.id,
            plan_date: date,
            value: value
          })
        });
        showSaveToast();
        recalcHabitPercent();

      }, 500);

    });

  });

}
function recalcHabitPercent() {

  const items = document.querySelectorAll(".habit-item");

  let total = items.length;
  let completed = 0;

  items.forEach(item => {

    const valueInput = item.querySelector(".habit-input");
    const goalInput  = item.querySelector(".habit-goal-edit");

    const value = parseFloat(valueInput?.value || 0);
    const goal  = parseFloat(goalInput?.value || 0);

    if (goal > 0 && value >= goal) {
      completed++;
    }

  });

  const percent = total ? Math.round((completed / total) * 100) : 0;

  updateHabitCircle(percent);

}
function showSavedFeedback() {
  const btn = document.getElementById("saveBtn");
  if (!btn) return;

  btn.innerText = "✓ Saved";
  btn.style.background = "#16a34a";

  setTimeout(() => {
    btn.innerText = "Save";
    btn.style.background = "#2563eb";
  }, 1500);
}

document.addEventListener("DOMContentLoaded", async () => {

  const dateInput = document.getElementById("health-date");
  if (!dateInput) return;
  
  ["weight","height","mood","energy","health-notes"].forEach(id => {

    const el = document.getElementById(id);
    if (!el || el.dataset.bound) return;

    el.dataset.bound = "1";

    el.addEventListener("input", autoSaveHealth);
    el.addEventListener("blur", autoSaveHealth);

  });

  const today = new Date().toLocaleDateString("en-CA", {
    timeZone: "Asia/Kolkata"
  });

  dateInput.value = today;

  await loadHealth(today);
  loadAnalytics(); // 🔥 call once only

  dateInput.addEventListener("change", async () => {
    await loadHealth(dateInput.value);
  });

  // 🔥 Load heatmap once
  fetch("/api/v2/heatmap")
    .then(res => res.json())
    .then(data => {

      const container = document.getElementById("heatmap");
      if (!container) return;

      container.innerHTML = "";

      Object.keys(data).forEach(day => {

        const div = document.createElement("div");
        div.className = "heat-cell";

        div.style.background =
          data[day] > 75 ? "#16a34a" :
          data[day] > 40 ? "#4ade80" :
          data[day] > 10 ? "#86efac" :
          "#e5e7eb";

        container.appendChild(div);
      });
    });

  // 🔥 Enable Drag Reorder
  const container = document.getElementById("habitContainer");

  if (container) {
    new Sortable(container, {
      animation: 150,
      handle: ".habit-drag",  // 🔥 only drag via ☰
      onEnd: async function () {

        const items = document.querySelectorAll(".habit-item");

        for (let i = 0; i < items.length; i++) {

          const id = items[i].dataset.id;

          await fetch("/api/habits/reorder", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              habit_id: id,
              position: i
            })
          });
        }
      }
    });
  }

});
async function deleteHabit(id) {
  if (!confirm("Delete this habit?")) return;

  await fetch("/api/habits/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ habit_id: id })
  });

  location.reload();
}
let editTimeout;

document.addEventListener("input", function (e) {

  if (
    e.target.classList.contains("habit-name-edit") ||
    e.target.classList.contains("habit-unit-edit") ||
    e.target.classList.contains("habit-goal-edit")
  ) {

    clearTimeout(editTimeout);

    editTimeout = setTimeout(async () => {

      const id = e.target.dataset.id;

      const item = document.querySelector(`.habit-item[data-id="${id}"]`);
      if (!item) return;

      const nameInput = item.querySelector(".habit-name-edit");
      const unitInput = item.querySelector(".habit-unit-edit");
      const goalInput = item.querySelector(".habit-goal-edit");
      const valueInput = item.querySelector(".habit-input");

      const name = nameInput.value;
      const unit = unitInput.value;
      const goal = parseFloat(goalInput.value || 0);
      const value = parseFloat(valueInput.value || 0);

      // 🔥 Save to backend
      await fetch("/api/habits/update", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          habit_id: id,
          name,
          unit,
          goal
        })
      });

      // 🔥 Update header immediately
      const title = item.querySelector(".habit-title");
      const sub = item.querySelector(".habit-sub");

      if (title) title.innerText = name;
      if (sub) sub.innerText = `Goal: ${goal} ${unit}`;

      // 🔥 Update progress bar
      const percent = goal > 0
        ? Math.min(100, Math.round((value / goal) * 100))
        : 0;

      const fill = item.querySelector(".habit-progress-fill");
      if (fill) fill.style.width = percent + "%";
      // 🔥 Move focus to entry field after goal edit
      if (e.target.classList.contains("habit-goal-edit")) {
        if (valueInput) {
          valueInput.focus();
          valueInput.select();
        }
      }
      // 🔥 Visual save glow
      item.classList.add("saved");
      setTimeout(() => {
        item.classList.remove("saved");
      }, 800);

      recalcHabitPercent();

    }, 600); // Save 600ms after typing stops
  }
});
async function showHabitChart(id) {

  const res = await fetch(`/api/v2/habit-weekly/${id}`);
  const data = await res.json();

  const ctx = document.getElementById("healthChart");

  if (window.habitChartInstance) {
    window.habitChartInstance.destroy();
  }

  window.habitChartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels: ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],
      datasets: [{
        label: "Weekly Progress",
        data: data,
        tension: 0.3
      }]
    }
  });
}
function toggleEdit(id) {
  const panel = document.getElementById("edit-" + id);
  panel.style.display =
    panel.style.display === "flex" ? "none" : "flex";
}

document.addEventListener("focus", function (e) {
  if (
    e.target.classList.contains("habit-input") ||
    e.target.classList.contains("habit-name-edit") ||
    e.target.classList.contains("habit-unit-edit") ||
    e.target.classList.contains("habit-goal-edit")
  ) {
    e.target.select();
  }
}, true);

let weightChart = null;

function renderWeightTrend(data) {

  if (!data || data.length === 0) return;

  const ctx = document.getElementById("weightChart");

  if (!ctx) return;

  // destroy previous chart
  if (weightChart) {
    weightChart.destroy();
  }

  weightChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.map(d => d.date.slice(5)),
    datasets: [{
        data: data.map(d => d.weight ?? null),
        tension: 0.4,
        borderColor: "#2563eb",
        borderWidth: 2,
        pointRadius: 3,
        fill: false
      }]
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        y: { display: false },
        x: { display: false }
      }
    }
  });

}
let sparklineChart = null;

function renderWeightSparkline(data) {

  if (!data || data.length === 0) return;

  const ctx = document.getElementById("weightSparkline");
  if (!ctx) return;

  if (sparklineChart) sparklineChart.destroy();

  sparklineChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.map(d => ""),
      datasets: [{
        data: data.map(d => d.weight ?? null),
        borderColor: "#16a34a",
        borderWidth: 2,
        tension: 0.4,
        pointRadius: 0,
        fill: false
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: { display: false }
      },
      animation: {
        duration: 800
      }
    }
  });
}
document.addEventListener("keydown", function(e){

  if (e.target.classList.contains("habit-goal-edit") && e.key === "Enter") {

    const item = e.target.closest(".habit-item");
    const entry = item.querySelector(".habit-input");

    if (entry) {
      entry.focus();
      entry.select();
    }

  }

});

async function quickAdd(id) {

  const item = document.querySelector(`.habit-item[data-id="${id}"]`);
  if (!item) return;

  const input = item.querySelector(".habit-input");

  let current = parseFloat(input.value || 0);
  const unitInput = item.querySelector(".habit-unit-edit");
  const unit = unitInput ? unitInput.value : "";

  const step = getStepFromUnit(unit);

  current = Math.round((current + step) * 100) / 100;

  input.value = current;

  // trigger autosave
  input.dispatchEvent(new Event("input"));

  // visual feedback
  item.classList.add("tap-flash");
  setTimeout(() => item.classList.remove("tap-flash"), 300);

}
function getStepFromUnit(unit) {

  if (!unit) return 1;

  unit = unit.toLowerCase();

  if (unit.includes("min")) return 5;
  if (unit.includes("hr")) return 0.5;
  if (unit.includes("step")) return 50;
  if (unit.includes("ml")) return 50;
  if (unit.includes("rs")) return 50;

  return 1;
}
function quickAdjust(id, direction) {

  const item = document.querySelector(`.habit-item[data-id="${id}"]`);
  if (!item) return;

  const input = item.querySelector(".habit-input");
  const unitInput = item.querySelector(".habit-unit-edit");

  const unit = unitInput ? unitInput.value : "";

  let current = parseFloat(input.value || 0);

  const step = getStepFromUnit(unit);

  current = Math.round((current + step * direction) * 100) / 100;

  if (current < 0) current = 0;

  input.value = current;

  // trigger autosave
  input.dispatchEvent(new Event("input"));

  // visual feedback
  item.classList.add("tap-flash");
  setTimeout(() => item.classList.remove("tap-flash"), 250);
}
let healthSaveTimer;

function autoSaveHealth() {

  clearTimeout(healthSaveTimer);

  healthSaveTimer = setTimeout(() => {
    saveHealth();
  }, 1500); // save after user pauses 1.5s

}
function showToast(message,type="info"){

  const container = document.getElementById("toast-container");
  if(!container) return;

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;

  container.appendChild(toast);

  requestAnimationFrame(()=>{
    toast.classList.add("show");
  });

  setTimeout(()=>{
    toast.classList.remove("show");

    setTimeout(()=>{
      toast.remove();
    },300);

  },2200);
}
function showSaveToast(){

  const toast = document.getElementById("saveToast");
  if(!toast) return;

  toast.classList.add("show");

  clearTimeout(toast.timer);

  toast.timer = setTimeout(()=>{
    toast.classList.remove("show");
  },1200);

}

function updateHealthScore(data){

  const habits = data.habit_percent || 0;
  const energy = data.energy_level || 5;
  const mood   = data.mood || "Neutral";
  const streak = data.streak || 0;

  const habitScore = habits * 0.5;

  const energyScore = (energy/10)*15;

  const moodScore =
      mood.includes("Happy") ? 10 :
      mood.includes("Neutral") ? 6 :
      3;

  const streakScore = Math.min(streak*1.5,15);

  const weightScore = 10; // optional stability logic later

  const total =
      habitScore +
      energyScore +
      moodScore +
      streakScore +
      weightScore;

  const score = Math.round(total);

  renderHealthScore(score);

}
function renderHealthScore(score){

  const number = document.getElementById("healthScoreNumber");
  const ring = document.getElementById("scoreRing");

  if(!ring || !number) return;

  number.innerText = score;

  const radius = 50;
  const circumference = 2*Math.PI*radius;

  ring.style.strokeDasharray = circumference;

  ring.style.strokeDashoffset =
        circumference - (score/100)*circumference;

}
async function loadAnalytics(){
  const [weekly, month] = await Promise.all([
    fetch("/api/v2/weekly-health").then(r => r.json()),
    fetch("/api/v2/monthly-summary").then(r => r.json())
  ]).then(([weekly, month]) => {

    const avgEl = document.getElementById("weeklyAvg");
    if (avgEl) {
      avgEl.innerText = `7-day avg: ${weekly.weekly_avg}%`;
    }

    const bestEl = document.getElementById("bestHabit");
    if (bestEl) {
      bestEl.innerText =
        weekly.best_habit ? `🏆 Best: ${weekly.best_habit}` : "";
    }

    const monthlyEl = document.getElementById("monthlySummary");
    if (monthlyEl) {
     monthlyEl.innerHTML = `
      <p>Days tracked: ${month.days_tracked}</p>
      <p>Avg completion: ${month.avg_percent}%</p>
      <p>Weight change: ${month.weight_change} kg</p>
      <p>Avg energy: ${month.avg_energy}/10</p>
    `;
    }

  }).catch(err => console.warn("Analytics load failed", err));;

  // update DOM here
}
let selectedEmoji = "";
let selectedColor = "#2563eb";

function openHabitSheet() {
  document.getElementById("habitSheet").classList.add("active");
}

function closeHabitSheet() {
  document.getElementById("habitSheet").classList.remove("active");
}
document.addEventListener("click", function(e){
  if(e.target.closest(".emoji-picker")){
    selectedEmoji = e.target.textContent;
    document.getElementById("sheetHabitName").value = selectedEmoji + " ";
    document.getElementById("sheetHabitName").focus();
  }
});
document.querySelectorAll(".color-dot").forEach(dot=>{
  dot.style.background = dot.dataset.color;

  dot.addEventListener("click", ()=>{
    document.querySelectorAll(".color-dot").forEach(d=>d.classList.remove("active"));
    dot.classList.add("active");
    selectedColor = dot.dataset.color;
  });
});

document.getElementById("sheetHabitUnit").addEventListener("input", function(){

  const unit = this.value.toLowerCase();
  const suggestions = document.getElementById("goalSuggestions");

  suggestions.innerHTML = "";

  let values = [];

  if(unit.includes("step")) values = [5000,8000,10000];
  if(unit.includes("min")) values = [15,30,45];
  if(unit.includes("ml")) values = [1500,2000,3000];
  if(unit.includes("hr")) values = [1,2,3];

  values.forEach(val=>{
    const btn = document.createElement("button");
    btn.innerText = val;
    btn.onclick = ()=> {
      document.getElementById("sheetHabitGoal").value = val;
    };
    suggestions.appendChild(btn);
  });
});
async function submitHabitSheet(){

  const name = document.getElementById("sheetHabitName").value.trim();
  const unit = document.getElementById("sheetHabitUnit").value.trim();
  const goal = parseFloat(document.getElementById("sheetHabitGoal").value);

  if(!name || !unit || !goal){
    showToast("All fields required","error");
    return;
  }

  const res = await fetch("/api/habits/add",{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({
      name,
      unit,
      goal,
      emoji:selectedEmoji,
      color:selectedColor
    })
  });

  const newHabit = await res.json();

  appendHabitToDOM(newHabit);
  closeHabitSheet();
  showToast("Habit added","success");
}
