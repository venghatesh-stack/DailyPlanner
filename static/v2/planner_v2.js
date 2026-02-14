const HOUR_HEIGHT = 60;
const SNAP = 5;
let events = [];
let selected = null;
let currentDate = new Date().toISOString().split("T")[0];

function snap(mins) {
  return Math.round(mins / SNAP) * SNAP;
}

function minutes(t) {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

function toTime(mins) {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}`;
}

async function loadEvents() {
  const res = await fetch(`/api/v2/events?date=${currentDate}`);
  events = await res.json();
  render();
}

function render() {
  const root = document.getElementById("timeline");
  root.innerHTML = "";

  for (let h=0; h<24; h++) {
    const top = h * HOUR_HEIGHT;
    root.innerHTML += `<div class="hour-line" style="top:${top}px"></div>
                       <div class="hour-label" style="top:${top}px">${h}:00</div>`;
  }

  const positioned = computeLayout(events);

  positioned.forEach(ev => {
    const div = document.createElement("div");
    div.className = "event";
    div.style.top = ev.top + "px";
    div.style.height = ev.height + "px";
    div.style.left = ev.left + "%";
    div.style.width = ev.width + "%";
    div.innerHTML = `
  <div class="event-time">
    ${ev.start_time} – ${ev.end_time}
  </div>
  <div class="event-title">
    ${ev.title}
  </div>
  `;

    div.onclick = () => openModal(ev);
    root.appendChild(div);
  });
}

function computeLayout(events) {
  const enriched = events.map(ev => {
    const start = minutes(ev.start_time);
    const end = minutes(ev.end_time);
    return {
      ...ev,
      start,
      end,
      top: (start/60)*HOUR_HEIGHT,
      height: ((end-start)/60)*HOUR_HEIGHT
    };
  });

  enriched.sort((a,b)=>a.start-b.start);

  for (let i=0;i<enriched.length;i++) {
    let overlaps = enriched.filter(e =>
      !(e.end <= enriched[i].start || e.start >= enriched[i].end)
    );
    const index = overlaps.indexOf(enriched[i]);
    const total = overlaps.length;

    enriched[i].width = 100/total;
    enriched[i].left = index * (100/total);
  }

  return enriched;
}

function openCreateModal() {
  selected = null;
  document.getElementById("modal").classList.remove("hidden");
  document.getElementById("modal").classList.add("show");
}

function openModal(ev) {
  selected = ev;
  document.getElementById("start-time").value = ev.start_time;
  document.getElementById("end-time").value = ev.end_time;
  document.getElementById("event-title").value = ev.title;
  document.getElementById("event-desc").value = ev.description || "";
  document.getElementById("modal").classList.remove("hidden");
}

function closeModal() {
   const modal = document.getElementById("modal");
   modal.classList.remove("show");
   modal.classList.add("hidden");
}

async function saveEvent() {
  const payload = {
    plan_date: currentDate,
    start_time: document.getElementById("start-time").value,
    end_time: document.getElementById("end-time").value,
    title: document.getElementById("event-title").value,
    description: document.getElementById("event-desc").value
  };

  try {
    let res;

    if (selected) {
      res = await fetch(`/api/v2/events/${selected.id}`, {
        method: "PUT",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(payload)
      });
    } else {
      res = await fetch(`/api/v2/events`, {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(payload)
      });
    }

    if (!res.ok) {
      const errorText = await res.text();
      alert(errorText || "Save failed");
      return;
    }

    // 🔥 RESET STATE BEFORE RENDER
    selected = null;

    // 🔥 CLOSE MODAL
    closeModal();

    // 🔥 RELOAD EVENTS
    await loadEvents();

  } catch (err) {
    console.error("Save error:", err);
    alert("Unexpected error");
  }
}


async function deleteEvent() {
  if (!selected) return;

  await fetch(`/api/v2/events/${selected.id}`, {
    method:"DELETE"
  });

  selected = null;
  closeModal();
  await loadEvents();
}

