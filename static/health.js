async function loadHealth(date) {
  const res = await fetch(`/api/v2/daily-health?date=${date}`);
  const data = await res.json();

  document.getElementById("weight").value = data.weight || "";
  document.getElementById("sleep").value = data.sleep_hours || "";
  document.getElementById("energy").value = data.energy_level || 5;
  document.getElementById("mood").value = data.mood || "😊 Happy";
  document.getElementById("health-notes").value = data.notes || "";
}

async function saveHealth() {
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

  alert("Saved!");
}
