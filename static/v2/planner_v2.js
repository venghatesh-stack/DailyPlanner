const HOUR_HEIGHT = 100;
const SNAP = 5;

let events = [];
let selected = null;
let currentDate = new Date().toISOString().split("T")[0];
let draggedTask = null;
let snapLine = null;

/* =========================
   TIME HELPERS
========================= */
function formatTime(t) {
  if (!t) return "";
  return t.slice(0, 5); // removes seconds safely
}

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

  // All project tasks stay in floating section
  const floatingTasks = taskData;

  // Only those with start_time go to calendar
  const timedTasks = taskData.filter(t => t.start_time);


  events = [
    ...eventData.map(e => ({
      ...e,
      type: "event"
    })),
    ...timedTasks.map(t => ({
      ...t,
      task_id: t.task_id,                  // 🔥 critical
      title: t.task_text,
      end_time: calculateEndTime(t.start_time, 30),
      type: "project"
    }))
  ];

  render();
  renderFloatingTasks(floatingTasks);
  renderSummary();
}

function normalizeProjectTask(t) {
  return {
    task_id: t.task_id,
    title: t.task_text,
    start_time: t.start_time,
    end_time: calculateEndTime(t.start_time, 30),
    type: "project",
    raw: t
  };
}

function hasConflict(ev, list) {
  return list.some(other =>
    other !== ev &&
    !(minutes(ev.end_time) <= minutes(other.start_time) ||
      minutes(ev.start_time) >= minutes(other.end_time))
  );
}
function getConflicts(event, allEvents) {
  return allEvents.filter(ev => {
    if (ev === event) return false;

    return (
      minutes(ev.start_time) < minutes(event.end_time) &&
      minutes(ev.end_time) > minutes(event.start_time)
    );
  });
}

function renderSummary() {
  const tbody = document.querySelector("#summary-table tbody");
  if (!tbody) return;

  tbody.innerHTML = "";

  if (!events.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="2" style="opacity:.6;">No events for this day</td>
      </tr>
    `;
    return;
  }

  const sorted = [...events].sort(
    (a, b) => minutes(a.start_time) - minutes(b.start_time)
  );

  sorted.forEach(ev => {
    const row = document.createElement("tr");
    row.classList.add("summary-row");

    const conflicts = getConflicts(ev, sorted);

    if (conflicts.length) {
      row.classList.add("summary-conflict");
    }

    row.innerHTML = `
      <td>
        ${formatTime(ev.start_time)} – ${formatTime(ev.end_time)}
        ${conflicts.length ? `<span class="conflict-pill">Conflict</span>` : ""}
      </td>
      <td>
        ${ev.task_text || ev.title}
        ${
          conflicts.length
            ? `<div class="conflict-detail">
                 ⚠ Conflicts with:
                 ${conflicts
                   .map(c => `${formatTime(c.start_time)} (${c.task_text || c.title})`)
                   .join(", ")}
               </div>`
            : ""
        }
      </td>
    `;

    tbody.appendChild(row);
  });
}


/* =========================
   RENDER TIMELINE
========================= */
function render() {
  const root = document.getElementById("timeline");
  root.innerHTML = "";

  // Hour lines
  renderTimeGrid();

  renderCurrentTimeLine(root);

  const positioned = computeLayout(events);

  positioned.forEach(ev => {
    const div = document.createElement("div");
    div.className = "event";
    div.style.top = ev.top + "px";
    div.style.height = ev.height + "px";
    const horizontalGap = 40; // px

    div.style.left = `calc(${ev.left}% + ${horizontalGap}px)`;
    div.style.width = `calc(${ev.width}% - ${horizontalGap * 2}px)`;

    div.dataset.id = ev.id;

    if (ev.type === "project") div.classList.add("project-event");
    div.classList.add(`p-${ev.priority || "medium"}`);
 div.innerHTML = `
  <div class="event-header">
    <span class="event-time-text">
      ${formatTime(ev.start_time)} – ${formatTime(ev.end_time)}
    </span>
    <span class="event-title-inline">
      ${ev.task_text || ev.title}
    </span>
  </div>

  <div class="event-description">
    ${ev.description || ""}
  </div>
`;


    // OPEN MODAL
   div.addEventListener("click", (e) => {
  if (e.target.classList.contains("resize-handle")) return;

  if (ev.type === "project") {
    console.log("➡ Opening project card");
    openTaskCard(ev.task_id);
  } else {

    openModal(ev);
  }
});



    // DRAG TO MOVE
    div.draggable = true;
    div.ondragstart = () => {
      draggedTask = ev;
    };

    // RESIZE HANDLE
    const resizeHandle = document.createElement("div");
    resizeHandle.className = "resize-handle";
    div.appendChild(resizeHandle);

    resizeHandle.addEventListener("mousedown", e => {
      e.stopPropagation();
      startResize(e, ev);
    });

    root.appendChild(div);
  });
}
document.addEventListener("click", (e) => {
  console.log("GLOBAL CLICK:", e.target);
});

async function openTaskCard(taskId) {
  selected = { task_id: taskId };   // 🔥 CRITICAL
  const res = await fetch(`/api/v2/project-tasks/${taskId}`);
  const task = await res.json();

  // populate your full project task modal fields

  document.getElementById("task-title").value = task.task_text;
  document.getElementById("task-description").value = task.notes || "";
  document.getElementById("task-planned-hours").value = task.planned_hours || 0;
  document.getElementById("task-actual-hours").value = task.actual_hours || 0;
  document.getElementById("task-status").value = task.status;
  document.getElementById("task-priority").value = task.priority;
  document.getElementById("task-duration").value = task.duration_days || 0;
  document.getElementById("task-due-date").value = task.due_date || "";
  document.getElementById("task-start-time").value = task.start_time || "";

  document.getElementById("task-card-modal")
  .classList.add("show");


}
function getISTNow() {
  return new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" })
  );
}
function getISTDate() {
  return new Date().toLocaleDateString('en-CA', {
    timeZone: 'Asia/Kolkata'
  });
}

function renderCurrentTimeLine(root) {
  const now = getISTNow();
  const today = getISTDate();

  if (currentDate !== today) return;

  const minutesNow = now.getHours() * 60 + now.getMinutes();
  const top = (minutesNow / 60) * HOUR_HEIGHT;

  const line = document.createElement("div");
  line.className = "current-time-line";
  line.style.top = top + "px";

  root.appendChild(line);
}

/* =========================
   LAYOUT ENGINE
========================= */
function computeLayout(events) {
  const enriched = events.map(ev => {
    const start = minutes(ev.start_time);
    const end = minutes(ev.end_time);

    return {
      ...ev,
      start,
      end,
      top: (start / 60) * HOUR_HEIGHT,
      height: ((end - start) / 60) * HOUR_HEIGHT
    };
  });

  enriched.sort((a, b) => a.start - b.start);

  const clusters = [];

  enriched.forEach(ev => {
    let placed = false;

    for (let cluster of clusters) {
      if (cluster.some(e => !(ev.end <= e.start || ev.start >= e.end))) {
        cluster.push(ev);
        placed = true;
        break;
      }
    }

    if (!placed) clusters.push([ev]);
  });

  clusters.forEach(cluster => {
    const columns = [];

    cluster.forEach(ev => {
      let placed = false;

      for (let i = 0; i < columns.length; i++) {
        const last = columns[i][columns[i].length - 1];
        if (ev.start >= last.end) {
          columns[i].push(ev);
          ev.col = i;
          placed = true;
          break;
        }
      }

      if (!placed) {
        columns.push([ev]);
        ev.col = columns.length - 1;
      }
    });

    const totalCols = columns.length;

    cluster.forEach(ev => {
      ev.width = 100 / totalCols;
      ev.left = ev.col * ev.width;
    });
  });

  return enriched;
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
function openProjectTaskModal(task) {
  selected = { ...task, type: "project" };

  document.getElementById("modal-title").innerText = "Project Task";

  document.getElementById("start-time").value = task.start_time || "";
  document.getElementById("duration").value = 30;

  document.getElementById("event-title").value = task.task_text || "";
  document.getElementById("event-desc").value = task.description || "";

  document.getElementById("modal").classList.remove("hidden");
}

/* =========================
   FLOATING TASKS
========================= */
function renderFloatingTasks(tasks) {
  const container = document.getElementById("floating-tasks");
  container.innerHTML = "";

  if (!tasks || !tasks.length) return;

  const priorityOrder = { high: 1, medium: 2, low: 3 };
  const todayStr = new Date().toISOString().split("T")[0];
  const now = new Date();
  const currentMinutes = now.getHours() * 60 + now.getMinutes();

  // 🔥 Sort by priority
  tasks.sort((a, b) => {
    const pa = priorityOrder[a.priority || "medium"];
    const pb = priorityOrder[b.priority || "medium"];
    return pa - pb;
  });

  // 🧠 Group by due date
  const grouped = {};

  tasks.forEach(task => {
    const date = task.due_date || "No Date";
    if (!grouped[date]) grouped[date] = [];
    grouped[date].push(task);
  });

  // 🔥 Sort groups chronologically
  const sortedDates = Object.keys(grouped).sort((a, b) => {
    if (a === "No Date") return 1;
    if (b === "No Date") return -1;
    return new Date(a) - new Date(b);
  });

  sortedDates.forEach(dateKey => {

    let label = dateKey;

    if (dateKey === todayStr) {
      label = `
        <span class="today-badge">🟡 Today</span>
        <span class="real-date">${dateKey}</span>
      `;
    }

    const groupHeader = document.createElement("div");
    groupHeader.className = "floating-group-header";
    groupHeader.innerHTML = `<div class="group-title">${label}</div>`;
    container.appendChild(groupHeader);

    grouped[dateKey].forEach(task => {

      const div = document.createElement("div");
      div.className = "floating-task";
      div.draggable = true;

      const due = task.due_date || null;
      const time = task.start_time ? task.start_time.slice(0, 5) : null;
      const priority = task.priority || "medium";

      // 🔴 Overdue
      if (due && new Date(due) < new Date(todayStr)) {
        div.classList.add("overdue-floating");
      }

      // ⏰ Elapsed today
      if (due === todayStr && time) {
        const [h, m] = time.split(":").map(Number);
        const taskMinutes = h * 60 + m;

        if (taskMinutes < currentMinutes) {
          div.classList.add("elapsed-floating");
        }
      }

      // 📅 Scheduled indicator
      if (task.plan_date) {
        div.classList.add("scheduled-floating");
      }

      div.innerHTML = `
        <div class="floating-title">
          ${task.task_text}
          ${task.plan_date ? `<span class="scheduled-icon">📅</span>` : ""}
        </div>

        <div class="floating-meta">
          <div class="meta-left">
            ${time ? `<span class="floating-time">🕒 ${time}</span>` : ""}
          </div>

          <span class="floating-priority p-${priority}">
            ${priority.toUpperCase()}
          </span>
        </div>
      `;

      div.onclick = (e) => {
        e.stopPropagation();
        openTaskCard(task.task_id);
      };

      div.ondragstart = () => {
        draggedTask = { ...task, type: "project" };
      };

      container.appendChild(div);
    });
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
  hideConflict();
  selected = null;

  document.getElementById("start-time").value = "";
  document.getElementById("duration").value = 30;
  document.getElementById("event-title").value = "";

  document.getElementById("modal").classList.add("show");

}

/* =========================
   MODAL
========================= */

function openModal(ev) {
  hideConflict();
  selected = ev;

  document.getElementById("start-time").value = ev.start_time;

  const duration = minutes(ev.end_time) - minutes(ev.start_time);
  document.getElementById("duration").value = duration;

  document.getElementById("event-title").value = ev.task_text || ev.title;

  document.getElementById("modal").classList.add("show");


}
function closeTaskCard() {
  document.getElementById("task-card-modal")
    .classList.remove("show");
}


async function saveTaskCard() {

  const taskId = selected?.task_id;

  const payload = {
    task_text: document.getElementById("task-title").value,
    notes: document.getElementById("task-description").value,
    status: document.getElementById("task-status").value,
    priority: document.getElementById("task-priority").value,
    planned_hours: document.getElementById("task-planned-hours").value,
    actual_hours: document.getElementById("task-actual-hours").value,
    duration_days: document.getElementById("task-duration").value,
    due_date: document.getElementById("task-due-date").value,
    start_time: document.getElementById("task-start-time").value
  };

  await fetch(`/api/v2/project-tasks/${taskId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  closeTaskCard();
  loadEvents();
}

function attachScrollNumber(id) {
  const el = document.getElementById(id);

  el.addEventListener("wheel", (e) => {
    e.preventDefault();

    let value = parseInt(el.value || 0);

    if (e.deltaY < 0) {
      value++;
    } else {
      value--;
    }

    if (value < 0) value = 0;
    if (value > 100) value = 100;

    el.value = value;
  });
}

attachScrollNumber("task-planned-hours");
attachScrollNumber("task-actual-hours");
attachScrollNumber("task-duration");


function closeModal() {
  document.getElementById("modal").classList.remove("show");
}
async function saveEvent() {
  const start = document.getElementById("start-time").value;
  const duration = document.getElementById("duration").value;

  const payload = {
    plan_date: currentDate,
    start_time: start,
    end_time: calculateEndTime(start, duration),
    title: document.getElementById("event-title").value,
    priority: document.getElementById("event-priority").value
  };

  let url;
  let method = "POST";

  if (selected) {
    if (selected.type === "project") {
      url = `/api/v2/project-tasks/${selected.task_id}`;
      method = "PUT";
    } else {
      url = `/api/v2/events/${selected.id}`;
      method = "PUT";
    }
  } else {
    url = `/api/v2/events`;
  }

  try {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    // 🔥 HANDLE CONFLICT
    if (!res.ok) {
    let data = {};
    try {
      data = await res.json();
    } catch {}

    if (data.conflict) {
      showConflictDialog(data.conflicting_events, payload);
      return;
    }

    alert("Save failed");
    return;
  }


    closeModal();
    loadEvents();

  } catch (err) {
    console.error("Save error:", err);
  }
}
function hideConflict() {
  const section = document.getElementById("conflict-section");
  if (section) section.style.display = "none";
}
function showConflictDialog(conflicts, payload) {

  const list = document.getElementById("conflict-list");
  const section = document.getElementById("conflict-section");

  list.innerHTML = conflicts.map(c =>
    `<div style="margin:6px 0;">
       ${c.start_time} – ${c.end_time} : ${c.title}
     </div>`
  ).join("");

  section.style.display = "block";

  document.getElementById("accept-conflict").onclick = async () => {
    payload.force = true;

    await fetch(`/api/v2/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    hideConflict();
    closeModal();
    loadEvents();
  };
}

async function deleteEvent() {
  if (!selected) return;

  // 🔥 Only allow deleting real calendar events
  if (selected.type !== "event") {
    alert("Only calendar events can be deleted here.");
    return;
  }

  const confirmed = confirm("Delete this event?");
  if (!confirmed) return;

  await fetch(`/api/v2/events/${selected.id}`, {
    method: "DELETE"
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
  document.getElementById("new-event-btn")
  .addEventListener("click", openCreateModal);

  const timeline = document.getElementById("timeline");



  timeline.addEventListener("drop", async e => {
  e.preventDefault();

  if (!draggedTask) return;

  const rect = timeline.getBoundingClientRect();
  const y = e.clientY - rect.top;

  const minutesFromTop = Math.floor((y / HOUR_HEIGHT) * 60);
  const snapped = Math.round(minutesFromTop / SNAP) * SNAP;

  // PROJECT TASK DROP
  if (draggedTask.type === "project") {
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
  }

  // EVENT MOVE
  else {
    const duration = draggedTask.end - draggedTask.start;

    const newStart = toTime(snapped);
    const newEnd = toTime(snapped + duration);

    await fetch(`/api/v2/events/${draggedTask.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan_date: currentDate,
        start_time: newStart,
        end_time: newEnd,
        title: draggedTask.title
      })
    });
  }

  draggedTask = null;

  if (snapLine) {
    snapLine.remove();
    snapLine = null;
  }

loadEvents();
// ✅ SAFE ADDITION
  renderTimeGutter();
});

timeline.addEventListener("dragover", e => {
  e.preventDefault();

  const rect = timeline.getBoundingClientRect();
  const y = e.clientY - rect.top;

  const minutesFromTop = Math.floor((y / HOUR_HEIGHT) * 60);
  const snapped = Math.round(minutesFromTop / SNAP) * SNAP;
  const top = (snapped / 60) * HOUR_HEIGHT;

  if (!snapLine) {
    snapLine = document.createElement("div");
    snapLine.className = "snap-line";
    timeline.appendChild(snapLine);
  }

  snapLine.style.top = top + "px";
});
function startResize(e, ev) {
  const startY = e.clientY;
  const originalEnd = ev.end;

  function onMouseMove(moveEvent) {
    const delta = moveEvent.clientY - startY;
    const minutesDelta = (delta / HOUR_HEIGHT) * 60;
    const snapped = Math.round(minutesDelta / SNAP) * SNAP;

    const newEnd = originalEnd + snapped;
    if (newEnd <= ev.start) return;
    const el = document.querySelector(`[data-id='${ev.id}']`);
    if (el) {
      const newHeight = ((newEnd - ev.start) / 60) * HOUR_HEIGHT;
      el.style.height = newHeight + "px";
    }
  }

  async function onMouseUp(upEvent) {
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseup", onMouseUp);

    const delta = upEvent.clientY - startY;
    const minutesDelta = (delta / HOUR_HEIGHT) * 60;
    const snapped = Math.round(minutesDelta / SNAP) * SNAP;

    const newEnd = toTime(originalEnd + snapped);

    await fetch(`/api/v2/events/${ev.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan_date: currentDate,
        start_time: ev.start_time,
        end_time: newEnd,
        title: ev.title
      })
    });

    loadEvents();
  }

  document.addEventListener("mousemove", onMouseMove);
  document.addEventListener("mouseup", onMouseUp);
}

timeline.addEventListener("dragleave", () => {
  if (snapLine) {
    snapLine.remove();
    snapLine = null;
  }
});

// ✅ update current time every minute
setInterval(() => {
  render();
}, 60000);

});   // ← closes DOMContentLoaded
function renderTimeGrid() {
  const timeline = document.getElementById("timeline");
  const gutter = document.getElementById("time-gutter");

  if (!timeline || !gutter) return;

  timeline.innerHTML = "";
  gutter.innerHTML = "";

  for (let hour = 0; hour < 24; hour++) {
    const hourTop = hour * HOUR_HEIGHT;

    // ========================
    // HOUR LINE (grid)
    // ========================
    const hourLine = document.createElement("div");
    hourLine.className = "hour-line";
    hourLine.style.top = hourTop + "px";
    timeline.appendChild(hourLine);

    // ========================
    // HOUR LABEL (gutter)
    // ========================
    const label = document.createElement("div");
    label.className = "hour-label";
    label.style.top = hourTop + "px";
    label.innerText = `${hour}:00`;
    gutter.appendChild(label);

    // ========================
    // 15 / 30 / 45 lines
    // ========================
    for (let q = 1; q <= 3; q++) {
      const minuteTop = hourTop + (HOUR_HEIGHT / 4) * q;

      const line = document.createElement("div");
      line.style.top = minuteTop + "px";

      if (q === 2) {
        line.className = "half-line";
      } else {
        line.className = "micro-line";
      }

      timeline.appendChild(line);
    }
  }
}


function formatHour(hour) {
  const h = hour % 12 || 12;
  const ampm = hour < 12 ? "AM" : "PM";
  return `${h} ${ampm}`;
}


function adjustTaskNumber(btn, direction) {
  const wrapper = btn.closest(".number-control");
  const input = wrapper.querySelector("input");

  const step = parseFloat(wrapper.dataset.step || 1);
  let value = parseFloat(input.value || 0);

  value += direction * step;

  if (value < 0) value = 0;
  if (value > 100) value = 100;

  input.value = parseFloat(value.toFixed(2));
}

function validateTaskNumber(input) {
  let value = parseFloat(input.value);

  if (isNaN(value)) value = 0;
  if (value < 0) value = 0;
  if (value > 100) value = 100;

  input.value = value;
}
document.addEventListener("wheel", function(e) {
  const wrapper = e.target.closest(".number-control");
  if (!wrapper) return;

  e.preventDefault();

  const input = wrapper.querySelector("input");
  const step = parseFloat(wrapper.dataset.step || 1);

  let value = parseFloat(input.value || 0);

  if (e.deltaY < 0) value += step;
  else value -= step;

  if (value < 0) value = 0;
  if (value > 100) value = 100;

  input.value = parseFloat(value.toFixed(2));
}, { passive: false });
async function deleteEvent() {
  if (!selected) return;

  const id = selected.id;

  await fetch(`/api/v2/events/${id}`, {
    method: "DELETE"
  });

  closeModal();
  loadEvents();

  showUndoToast(id);
}
function showUndoToast(eventId) {
  const toast = document.createElement("div");
  toast.className = "undo-toast";
  toast.innerHTML = `
    Event deleted
    <button onclick="undoDelete('${eventId}')">Undo</button>
  `;

  document.body.appendChild(toast);

  setTimeout(() => {
    toast.remove();
  }, 5000);
}
async function undoDelete(id) {
  await fetch(`/api/v2/events/${id}/restore`, {
    method: "POST"
  });

  loadEvents();
}
async function runSmartPlanner() {

  const text = document.getElementById("smart-input").value;

  if (!text.trim()) return;

  const res = await fetch("/api/v2/smart-create", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      date: currentDate,
      text
    })
  });

  if (!res.ok) {
    alert("Smart planner failed");
    return;
  }

  document.getElementById("smart-input").value = "";

  loadEvents();
}