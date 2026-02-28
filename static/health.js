async function loadHealth(date) {

  const res = await fetch(`/api/v2/daily-health?date=${date}`);
  const data = await res.json();

  // ------------------------
  // Basic health fields
  // ------------------------
  document.getElementById("weight").value = data.weight || "";
  document.getElementById("sleep").value = data.sleep_hours || "";
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

  // ------------------------
  // Streak
  // ------------------------
  const badge = document.getElementById("streak-badge");
  if (badge) {
    badge.innerText = `🔥 ${data.streak || 0} day streak`;
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
  // Weekly analytics
  // ------------------------
  fetch("/api/v2/weekly-health")
    .then(res => res.json())
    .then(weekly => {

      const avgEl = document.getElementById("weeklyAvg");
      if (avgEl) {
        avgEl.innerText = `7-day avg: ${weekly.weekly_avg}%`;
      }

      const bestEl = document.getElementById("bestHabit");
      if (bestEl) {
        bestEl.innerText =
          weekly.best_habit ? `🏆 Best: ${weekly.best_habit}` : "";
      }

    });

  // ------------------------
  // Monthly summary
  // ------------------------
  fetch("/api/v2/monthly-summary")
    .then(res => res.json())
    .then(month => {

      const monthlyEl = document.getElementById("monthlySummary");
      if (!monthlyEl) return;

      monthlyEl.innerHTML = `
        <p>Days tracked: ${month.days_tracked}</p>
        <p>Avg completion: ${month.avg_percent}%</p>
        <p>Total sleep: ${month.total_sleep} hrs</p>
      `;
    });

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

        <div class="habit-header">
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

        <input type="number"
               step="0.1"
               value="${value}"
               data-id="${h.id}"
               class="habit-input"
               placeholder="Enter today’s value">

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
async function addHabit() {
  const name = document.getElementById("newHabitName").value.trim();
  const unit = document.getElementById("newHabitUnit").value.trim();

  if (!name || !unit) {
    alert("Enter habit name and unit");
    return;
  }

  const res = await fetch("/api/habits/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, unit })
  });

  if (res.ok) {
    location.reload();  // refresh to show new habit
  } else {
    alert("Failed to add habit");
  }
}
async function saveHealth() {
  const btn = document.getElementById("saveBtn");

  btn.classList.add("saving");
  btn.innerText = "Saving...";

  const date = document.getElementById("health-date").value;

  await fetch("/api/v2/daily-health", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      plan_date: date,
      weight: document.getElementById("weight").value,
      sleep_hours: document.getElementById("sleep").value,
      mood: document.getElementById("mood").value,
      energy_level: document.getElementById("energy").value,
      notes: document.getElementById("health-notes").value
    })
  });
btn.classList.remove("saving");

  showSavedFeedback();
}

function wireHabitInputs() {
  document.querySelectorAll(".habit-input").forEach(input => {

    input.addEventListener("change", async () => {

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

      // 🔥 Recalculate completion locally
      recalcHabitPercent();
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

  const today = new Date().toLocaleDateString("en-CA", {
    timeZone: "Asia/Kolkata"
  });

  dateInput.value = today;

  await loadHealth(today);

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
document.addEventListener("change", async (e) => {

  if (e.target.classList.contains("habit-name-edit") ||
      e.target.classList.contains("habit-unit-edit") ||
      e.target.classList.contains("habit-goal-edit")) {

    const id = e.target.dataset.id;

    const name = document.querySelector(
      `.habit-name-edit[data-id="${id}"]`
    ).value;

    const unit = document.querySelector(
      `.habit-unit-edit[data-id="${id}"]`
    ).value;

    const goal = document.querySelector(
      `.habit-goal-edit[data-id="${id}"]`
    ).value;

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