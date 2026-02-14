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
  const eventRes = await fetch(`/api/v2/events?date=${currentDate}`);
  const taskRes = await fetch(`/api/v2/project-tasks?date=${currentDate}`);

  const eventData = await eventRes.json();
  const taskData = await taskRes.json();

  events = [...eventData, ...taskData];

  render();
  renderSummary();
  renderFloatingTasks(taskData);
}


function render() {
  const root = document.getElementById("timeline");
  root.innerHTML = "";

  for (let h = 0; h < 24; h++) {
    const top = h * HOUR_HEIGHT;
    root.innerHTML += `
      <div class="hour-line" style="top:${top}px"></div>
      <div class="hour-label" style="top:${top}px">${h}:00</div>
    `;
  }

  const positioned = computeLayout(events);

  positioned.forEach(ev => {
    const div = document.createElement("div");
    div.className = "event";

    if (ev.isConflict) {
      div.classList.add("conflict");
    }

    div.style.top = ev.top + "px";
    div.style.minHeight = ev.height + "px";
    div.style.height = "auto";

    div.style.left = `calc(${ev.left}% + ${ev.gapOffset}px)`;
    div.style.width = `calc(${ev.width}% - 4px)`;

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



function calculateEndTime(start, duration) {
  const total = minutes(start) + parseInt(duration);
  return toTime(total);
}

function updateEndPreview() {
  const start = document.getElementById("start-time").value;
  const duration = document.getElementById("duration").value;

  if (!start) return;

  const end = calculateEndTime(start, duration);
  document.getElementById("end-display").innerText =
    `Ends at ${end}`;
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
    const gap = 4;

    group.forEach((ev, index) => {
      ev.width = width;
      ev.left = width * index;
      ev.gapOffset = index * gap;
      ev.isConflict = group.length > 1;
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
  const duration = minutes(ev.end_time) - minutes(ev.start_time);
  document.getElementById("duration").value = duration;
  updateEndPreview();

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
const start = document.getElementById("start-time").value;
const duration = document.getElementById("duration").value;

const payload = {
  plan_date: currentDate,
  start_time: start,
  end_time: calculateEndTime(start, duration),
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
    (a, b) => minutes(a.start_time) - minutes(b.start_time)
  );

  let totalMinutes = 0;

  sorted.forEach(ev => {
    const duration = minutes(ev.end_time) - minutes(ev.start_time);
    totalMinutes += duration;

    const row = document.createElement("tr");

    row.innerHTML = `
      <td>${ev.start_time} – ${ev.end_time}</td>
      <td>${duration} mins</td>
      <td>${ev.title}</td>
    `;

    tbody.appendChild(row);
  });

  const totalRow = document.createElement("tr");
  totalRow.innerHTML = `
    <td colspan="3" style="font-weight:600;">
      Total Meeting Time: ${(totalMinutes / 60).toFixed(1)} hrs
    </td>
  `;

  tbody.appendChild(totalRow);
}
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("start-time")?.addEventListener("change", updateEndPreview);
  document.getElementById("duration")?.addEventListener("change", updateEndPreview);
});

function renderFloatingTasks(tasks) {
  const container = document.getElementById("floating-tasks");
  container.innerHTML = "";

  const noTimeTasks = tasks.filter(t => !t.start_time);

  noTimeTasks.forEach(task => {
    const div = document.createElement("div");
    div.className = "floating-task";
    div.innerText = task.title;
    container.appendChild(div);
  });
}
