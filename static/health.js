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
    const safeValue =
      h.value !== null && h.value !== undefined ? h.value : "";

    container.innerHTML += `
      <div class="habit-item">
        <label>${h.name} (${h.unit})</label>
        <input type="number"
               step="0.1"
               value="${safeValue}"
               data-id="${h.id}"
               class="habit-input"/>
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
  const inputs = document.querySelectorAll(".habit-input");

  let total = inputs.length;
  let completed = 0;

  inputs.forEach(input => {
    const value = parseFloat(input.value);
    if (value && value > 0) completed++;
  });

  const percent = total ? Math.round((completed / total) * 100) : 0;

  updateHabitCircle(percent);

  // Update chart safely
  if (
    window.healthChart &&
    window.healthChart.data &&
    window.healthChart.data.datasets &&
    window.healthChart.data.datasets.length > 2
  ) {
    window.healthChart.data.datasets[2].data = [percent];
    window.healthChart.update();
  }
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

  // 🔥 Load heatmap ONCE
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

});