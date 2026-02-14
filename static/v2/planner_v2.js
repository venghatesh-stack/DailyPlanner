const HOUR_HEIGHT = 60;
const SNAP = 5;
let events = [];
let selected = null;
let currentDate = new Date().toISOString().split("T")[0];
let pendingForcePayload = null;

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
  renderSummary();   // 🔥 add this
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
    div.style.minHeight = ev.minHeight + "px";
    div.style.height = ev.height + "px";

    requestAnimationFrame(() => {
      if (div.scrollHeight > div.offsetHeight) {
        div.style.height = div.scrollHeight + "px";
      }
    });

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
      top: (start / 60) * HOUR_HEIGHT,
      height: Math.max(((end - start) / 60) * HOUR_HEIGHT, 40)
    };
  });

  enriched.sort((a, b) => a.start - b.start);

  const groups = [];

  enriched.forEach(ev => {
    let placed = false;

    for (let group of groups) {
      if (group.some(e => !(ev.end <= e.start || ev.start >= e.end))) {
        group.push(ev);
        placed = true;
        break;
      }
    }

    if (!placed) groups.push([ev]);
  });

  groups.forEach(group => {
    const width = 100 / group.length;
    group.forEach((ev, index) => {
      ev.width = width;
      ev.left = width * index;
    });
  });

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
      const data = await res.json();

      if (data.conflict) {
        showConflictDialog(data.conflicting_events, payload);
        return;
      }

      alert("Save failed");
      return;
    }

    selected = null;
    closeModal();
    await loadEvents();

  } catch (err) {
    console.error("Save error:", err);
    alert("Unexpected error");
  }
}


function showConflictDialog(conflicts, payload) {
  pendingForcePayload = payload;

  const conflictHtml = conflicts.map(c =>
    `<div style="margin:6px 0;">
       ${c.start_time} – ${c.end_time} : ${c.title}
     </div>`
  ).join("");

  document.querySelector(".modal-card").innerHTML = `
    <h3>Time Conflict</h3>
    <p>This overlaps with:</p>
    ${conflictHtml}
    <div style="margin-top:10px;">
      <button id="accept-conflict">Accept Anyway</button>
      <button onclick="closeModal()">Reject</button>
    </div>
  `;

  document.getElementById("accept-conflict").onclick = () => {
    forceSave(pendingForcePayload);
  };
}

async function forceSave(payload) {
  payload.force = true;

  await fetch(`/api/v2/events`, {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(payload)
  });

  selected = null;
  closeModal();
  await loadEvents();
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
function renderDate() {
  const d = new Date(currentDate);
  document.getElementById("current-date").innerText =
    d.toLocaleDateString("en-IN", {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric"
    });
}

function changeDate(offset) {
  const d = new Date(currentDate);
  d.setDate(d.getDate() + offset);
  currentDate = d.toISOString().split("T")[0];
  renderDate();
  loadEvents();
}

function renderSummary() {
  const tbody = document.querySelector("#summary-table tbody");
  tbody.innerHTML = "";

  const sorted = [...events].sort(
    (a,b)=> minutes(a.start_time) - minutes(b.start_time)
  );

  sorted.forEach(ev => {
    const row = document.createElement("tr");

    row.innerHTML = `
      <td>${ev.start_time} – ${ev.end_time}</td>
      <td>${ev.title}</td>
    `;

    tbody.appendChild(row);
  });
}
