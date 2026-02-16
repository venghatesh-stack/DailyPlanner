async function loadHealth(date) {
  const res = await fetch(`/api/v2/daily-health?date=${date}`);
  const data = await res.json();

  document.getElementById("weight").value = data.weight || "";
  document.getElementById("sleep").value = data.sleep_hours || "";
  document.getElementById("energy").value = data.energy_level || 5;
  document.getElementById("mood").value = data.mood || "😊 Happy";
  document.getElementById("health-notes").value = data.notes || "";

  // 🔥 Update habit checkboxes
  document.querySelectorAll('[data-habit]').forEach(cb => {
    cb.checked = data.habits ? !!data.habits[cb.dataset.habit] : false;
  });

  // 🔥 Update habit circle %
  if (data.habit_percent !== undefined) {
    updateHabitCircle(data.habit_percent);
  } else {
    updateHabitCircle(0);
  }

  // 🔥 Update streak badge
  const badge = document.getElementById("streak-badge");
  if (badge) {
    badge.innerText = `🔥 ${data.streak || 0} day streak`;
  }

  // 🔥 Update chart safely (no infinite push)
 if (
  window.healthChart &&
  window.healthChart.data &&
  window.healthChart.data.datasets &&
  window.healthChart.data.datasets.length > 2 &&
  data.habit_percent !== undefined
) {
  window.healthChart.data.datasets[2].data.push(data.habit_percent);
  window.healthChart.update();
}

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
  btn.classList.add("saved");
  btn.innerText = "Saved ✓";
  showSavedFeedback();
}

function wireHabitListeners() {
  document.querySelectorAll('[data-habit]').forEach(cb => {
    cb.addEventListener('change', async () => {

      const date = document.getElementById("health-date").value;

      await fetch('/api/save-habit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          habit: cb.dataset.habit,
          completed: cb.checked,
          plan_date: date
        })
      });

      await loadHealth(date);
    });
  });
}

function showSavedFeedback() {
  const btn = document.querySelector(".save-btn");
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

  // ✅ Default to today
  const today = new Date().toLocaleDateString("en-CA", {
    timeZone: "Asia/Kolkata"
  });
  dateInput.value = today;

  await loadHealth(today);

  dateInput.addEventListener("change", async () => {
    await loadHealth(dateInput.value);
  });

  wireHabitListeners();
});
