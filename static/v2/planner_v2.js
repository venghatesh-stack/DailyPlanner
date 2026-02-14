const HOUR_HEIGHT = 60;
const SNAP = 5;

let events = [];
let selected = null;
let currentDate = new Date().toISOString().split("T")[0];
let draggedTask = null;

/* =========================
   TIME HELPERS
========================= */

function minutes(t) {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

function toTime(mins) {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function calculateEndTime(start, duration) {
  return toTime(minutes(start) + parseInt(duration));
}

/* =========================
   LOAD DATA
========================= */

async function loadEvents() {
  const eventRes = await fetch(`/api/v2/events?date=${currentDate}`);
  const taskRes = await fetch(`/api/v2/project-tasks?date=${currentDate}`);

  const eventData = await eventRes.json();
  const taskData = await taskRes.json();

  const timedTasks = taskData.filter(t => t.start_time);
  const floatingTasks = taskData.filter(t => !t.start_time);

  events = [
    ...eventData.map(e => ({ ...e, type: "event" })),
    ...timedTasks.map(t => ({ ...t, type: "project" }))
  ];

  render();
  renderFloatingTasks(floatingTasks);
}

/* =========================
   RENDER TIMELINE
========================= */

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

    if (ev.type === "project") {
      div.classList.add("project-event");
    }

    if (ev.isConflict) {
      div.classList.add("conflict");
    }

    div.style.top = ev.top + "px";
    div.style.minHeight = ev.baseHeight + "px";
    div.style.height = "auto";
    div.style.left = `calc(${ev.left}% + ${ev.gapOffset}px)`;
    div.style.width = `calc(${ev.width}% - 4px)`;


    div.innerHTML = `
      <div class="event-time">${ev.start_time} – ${ev.end_time}</div>
      <div class="event-title">
        <input type="checkbox" onclick="toggleComplete(event,'${ev.task_id || ev.id}')"/>
        ${ev.task_text || ev.title}
      </div>
      ${ev.projects?.name ? `<div class="project-badge">${ev.projects.name}</div>` : ""}

      ${ev.priority ? `<div class="priority p-${ev.priority}"></div>` : ""}
    `;

    div.onclick = () => openModal(ev);
    root.appendChild(div);
     // 🔥 Allow content to expand but prevent breaking layout
  requestAnimationFrame(() => {
    const expandedHeight = div.scrollHeight;

    if (expandedHeight > ev.baseHeight) {
      div.style.height = expandedHeight + "px";
    } else {
      div.style.height = ev.baseHeight + "px";
    }
  });
  });
}

/* =========================
   LAYOUT ENGINE
========================= */
function computeLayout(events) {
  const enriched = events.map(ev => {
    const start = minutes(ev.start_time);
    const end = minutes(ev.end_time);

    const baseHeight = Math.max(((end - start) / 60) * HOUR_HEIGHT, 40);

    return {
      ...ev,
      start,
      end,
      top: (start / 60) * HOUR_HEIGHT,
      height: baseHeight
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
async function deleteEvent() {
  if (!selected) return;

  let url;
  let method = "DELETE";

  if (selected.type === "project") {
    url = `/api/v2/project-tasks/${selected.task_id}`;
  } else {
    url = `/api/v2/events/${selected.id}`;
  }

  await fetch(url, { method });

  closeModal();
  loadEvents();
}


function changeDate(offset) {
  const date = new Date(currentDate);
  date.setDate(date.getDate() + offset);

  currentDate = date.toISOString().split("T")[0];

  updateDateHeader();
  loadEvents();
}
function updateDateHeader() {
  const el = document.getElementById("current-date");
  if (!el) return;

  const d = new Date(currentDate);
  el.textContent = d.toDateString();
}

/* =========================
   FLOATING TASKS
========================= */

function renderFloatingTasks(tasks) {
  const container = document.getElementById("floating-tasks");
  container.innerHTML = "";

  tasks.forEach(task => {
    const div = document.createElement("div");
    div.className = "floating-task";
    div.draggable = true;
    div.innerText = task.task_text;

    div.dataset.task = JSON.stringify(task);

    div.ondragstart = e => {
      draggedTask = task;
    };

    container.appendChild(div);
  });
}

/* =========================
   DRAG INTO CALENDAR
========================= */


/* =========================
   CHECKBOX
========================= */

function toggleComplete(e, id) {
  e.stopPropagation();

  fetch(`/api/v2/project-tasks/${id}/complete`, {
    method: "POST"
  });

  loadEvents();
}
function openCreateModal() {
  selected = null;

  document.getElementById("start-time").value = "";
  document.getElementById("duration").value = 30;
  document.getElementById("event-title").value = "";

  document.getElementById("modal").classList.remove("hidden");
}

/* =========================
   MODAL
========================= */

function openModal(ev) {
  selected = ev;

  document.getElementById("start-time").value = ev.start_time;

  const duration = minutes(ev.end_time) - minutes(ev.start_time);
  document.getElementById("duration").value = duration;

  document.getElementById("event-title").value = ev.task_text || ev.title;

  document.getElementById("modal").classList.remove("hidden");
}

function closeModal() {
  document.getElementById("modal").classList.add("hidden");
}
async function saveEvent() {
  const start = document.getElementById("start-time").value;
  const duration = document.getElementById("duration").value;

  const payload = {
    plan_date: currentDate,
    start_time: start,
    end_time: calculateEndTime(start, duration),
    title: document.getElementById("event-title").value
  };

  let url;
  let method = "POST";

  if (selected) {
    if (selected.type === "project") {
      url = `/api/v2/project-tasks/${selected.task_id}/schedule`;
      method = "POST";
    } else {
      url = `/api/v2/events/${selected.id}`;
      method = "PUT";
    }
  } else {
    url = `/api/v2/events`;
  }

  await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  closeModal();
  loadEvents();
}

/* =========================
   INIT
========================= */

document.addEventListener("DOMContentLoaded", () => {
  updateDateHeader();
  loadEvents();

  const timeline = document.getElementById("timeline");

  timeline.addEventListener("dragover", e => {
    e.preventDefault();
  });

  timeline.addEventListener("drop", async e => {
    e.preventDefault();

    if (!draggedTask) return;

    const rect = timeline.getBoundingClientRect();
    const y = e.clientY - rect.top;

    const minutesFromTop = Math.floor((y / HOUR_HEIGHT) * 60);
    const snapped = Math.round(minutesFromTop / SNAP) * SNAP;

    const start = toTime(snapped);
    const end = calculateEndTime(start, 30);

    await fetch(`/api/v2/project-tasks/${draggedTask.task_id}/schedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan_date: currentDate,
        start_time: start,
        end_time: end
      })
    });

    draggedTask = null;
    loadEvents();
  });
});
