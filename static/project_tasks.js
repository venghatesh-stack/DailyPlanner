/* =========================================================
   PROJECT TASKS — SINGLE ENTRY FILE
   ========================================================= */

/* -------------------------
   Utilities
------------------------- */
function $(id) {
  return document.getElementById(id);
}

/* -------------------------
   Sorting
------------------------- */
document.addEventListener("DOMContentLoaded", () => {
  const sortSelect = $("sortSelect");
  if (!sortSelect) return;

  sortSelect.addEventListener("change", async e => {
    await fetch(`/projects/${sortSelect.dataset.projectId}/set-sort`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sort: e.target.value })
    });
    location.reload();
  });
});

/* -------------------------
   Drag & Drop Reorder
------------------------- */
let draggedId = null;

window.dragStart = e => {
  draggedId = e.target.closest(".task")?.dataset.id || null;
};

window.dragOver = e => e.preventDefault();

window.dropTask = e => {
  e.preventDefault();
  const target = e.target.closest(".task");
  if (!draggedId || !target) return;

  const targetId = target.dataset.id;
  if (draggedId === targetId) return;

  fetch("/projects/tasks/reorder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dragged_id: draggedId, target_id: targetId })
  })
    .then(r => r.ok && location.reload())
    .catch(console.error);
};

/* -------------------------
   Task Expand / Collapse
------------------------- */
window.toggleTask = taskId => {
  const el = $(`task-${taskId}`);
  if (el) el.classList.toggle("open");
};

/* -------------------------
   Pin Task
------------------------- */
window.togglePin = btn => {
  const task = btn.closest(".task");
  if (!task) return;

  const isPinned = task.dataset.pinned === "1";

  fetch("/projects/tasks/pin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task_id: task.dataset.id,
      is_pinned: !isPinned
    })
  }).then(() => {
    task.dataset.pinned = isPinned ? "0" : "1";
    btn.classList.toggle("pinned", !isPinned);
  });
};

/* -------------------------
   Status Update
------------------------- */
window.updateStatus = (taskId, status) => {
  const task = $(`task-${taskId}`);
  if (!task) return;

  const prev = task.dataset.status;
  task.dataset.status = status;

  fetch("/projects/tasks/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId, status })
  })
    .then(r => {
      if (!r.ok) throw Error();
      calculateProjectHealth();
      applyTaskFilters();
    })
    .catch(() => {
      task.dataset.status = prev;
      alert("Failed to update status");
    });
};

/* -------------------------
   Filters
------------------------- */
window.applyTaskFilters = () => {
  const hideClosed = $("hideClosed")?.checked;
  const overdueOnly = $("showOverdueOnly")?.checked;

  document.querySelectorAll(".task").forEach(task => {
    const closed = task.dataset.status === "done";
    const overdue = task.querySelector(".due-badge.overdue");

    let show = true;
    if (hideClosed && closed) show = false;
    if (overdueOnly && !overdue) show = false;

    task.style.display = show ? "" : "none";
  });
};

/* -------------------------
   Due Badge Formatting
------------------------- */
function formatDueBadges() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  document.querySelectorAll(".due-badge").forEach(badge => {
    const dueStr = badge.dataset.due;
    if (!dueStr) return;

    const due = new Date(dueStr);
    due.setHours(0, 0, 0, 0);

    const diff = Math.round((due - today) / 86400000);
    badge.classList.remove("today", "soon", "overdue");

    if (diff === 0) {
      badge.textContent = "⏰ Today";
      badge.classList.add("today");
    } else if (diff === 1) {
      badge.textContent = "⏰ Tomorrow";
      badge.classList.add("soon");
    } else if (diff > 1) {
      badge.textContent = `⏰ In ${diff} days`;
      badge.classList.add("soon");
    } else {
      badge.textContent = `⚠ ${Math.abs(diff)} days overdue`;
      badge.classList.add("overdue");
    }
  });
}

/* -------------------------
   Project Health
------------------------- */
function calculateProjectHealth() {
  const tasks = document.querySelectorAll(".task");
  if (!tasks.length) return;

  let total = 0, done = 0, progress = 0, overdue = 0;
  let planned = 0, actual = 0;
  const today = new Date().toISOString().slice(0, 10);

  tasks.forEach(t => {
    total++;
    if (t.dataset.status === "done") done++;
    if (t.dataset.status === "in_progress") progress++;

    const due = t.querySelector(".due-date")?.textContent;
    if (due && due < today && t.dataset.status !== "done") overdue++;

    planned += parseFloat(t.querySelector('[onchange*="updatePlanned"]')?.value || 0);
    actual  += parseFloat(t.querySelector('[onchange*="updateActual"]')?.value || 0);
  });

  const completion = total ? (done / total) * 100 : 0;
  const accuracy = planned
    ? Math.max(0, 100 - Math.abs(actual - planned) / planned * 100)
    : 100;

  const score =
    completion * 0.35 +
    accuracy * 0.25 +
    (100 - (overdue / total) * 100) * 0.25 +
    Math.min(100, (progress / total) * 100) * 0.15;

  $("health-score").textContent = Math.round(score);
  $("metric-complete").textContent = Math.round(completion) + "%";
  $("metric-overdue").textContent = overdue;
  $("metric-accuracy").textContent = Math.round(accuracy) + "%";
  $("metric-progress").textContent = progress;
}

/* -------------------------
   Notes → Bulk Tasks
------------------------- */
function extractTasksFromNotes(text) {
  return text
    .split("\n")
    .map(l => l.trim())
    .filter(Boolean)
    .map(l => l.replace(/^[-•]\s*/, ""));
}

document.addEventListener("DOMContentLoaded", () => {
  $("addTasksFromNotes")?.addEventListener("click", async () => {
    const notes = $("projectNotes");
    const tasks = extractTasksFromNotes(notes.value);
    if (!tasks.length) return alert("No tasks found");

    await fetch("/projects/tasks/bulk-add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: notes.dataset.projectId,
        tasks
      })
    });

    location.reload();
  });
});

/* -------------------------
   Init
------------------------- */
document.addEventListener("DOMContentLoaded", () => {
  formatDueBadges();
  applyTaskFilters();
  calculateProjectHealth();
});
