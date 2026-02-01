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
window.enableEdit = function (el, taskId) {
  if (!el || !taskId) return;

  el.contentEditable = "true";
  el.focus();

  // Move cursor to end
  document.execCommand("selectAll", false, null);
  document.getSelection().collapseToEnd();

  el.onblur = () => saveEdit(el, taskId);

  el.onkeydown = e => {
    if (e.key === "Enter") {
      e.preventDefault();
      el.blur();
    }
  };
};

function saveEdit(el, taskId) {
  el.contentEditable = "false";

  fetch(`/projects/tasks/${taskId}/update-text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_text: el.textContent.trim() })
  }).catch(console.error);
}
window.updateDelegation = function (taskId, value) {
  if (!taskId) return;

  fetch("/projects/tasks/update-delegation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: taskId,
      delegated_to: value || null
    })
  }).catch(console.error);
};
window.updatePlanning = function (taskId) {
  if (!taskId) return;

  const taskEl = document.getElementById(`task-${taskId}`);
  if (!taskEl) return;

  const startInput = taskEl.querySelector(".start-date");
  const durationInput = taskEl.querySelector(".duration-days");

  if (!startInput || !durationInput) return;

  fetch("/projects/tasks/update-planning", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task_id: taskId,
      start_date: startInput.value,
      duration_days: durationInput.value
    })
  })
    .then(r => r.json())
    .then(res => {
      // Optional soft refresh if due date changed
      if (res?.due_date) {
        const dueBadge = taskEl.querySelector(".due-badge");
        if (dueBadge) dueBadge.textContent = `📅 ${res.due_date}`;
      }
      calculateProjectHealth();
    })
    .catch(console.error);
};
window.eliminateTask = function (taskId) {
  if (!taskId) return;

  const reason = prompt("Why are you eliminating this task? (optional)");

  fetch("/projects/tasks/eliminate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: taskId,
      reason: reason || null
    })
  })
    .then(r => {
      if (!r.ok) throw new Error("Eliminate failed");
      // Hard refresh to re-group tasks safely
      location.reload();
    })
    .catch(err => {
      console.error(err);
      alert("Failed to delete task");
    });
};
function serializeTask(taskEl) {
  return {
    task_text: taskEl.querySelector(".task-title")?.textContent.trim() || null,
    priority: taskEl.querySelector(".priority-icon")?.dataset.priority || null,
    status: taskEl.dataset.status || null,
    start_date: taskEl.querySelector(".start-date")?.value || null,
    duration_days: taskEl.querySelector(".duration-days")?.value || 0,
    planned_hours: taskEl.querySelector('[onchange*="updatePlanned"]')?.value || 0,
    actual_hours: taskEl.querySelector('[onchange*="updateActual"]')?.value || 0,
    due_time: taskEl.querySelector('select[onchange*="updateDueTime"]')?.value || null,
    delegated_to: taskEl.querySelector('input[maxlength="25"]')?.value || null
  };
}

document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".save-task-btn");
  if (!btn) return;

  const taskEl = btn.closest(".task");
  if (!taskEl) return;

  const taskId = taskEl.dataset.id;
  if (!taskId) {
    console.error("Save clicked but taskId missing");
    return;
  }

  const payload = serializeTask(taskEl);

  if (!payload.task_text) {
    alert("Task text cannot be empty");
    return;
  }

  // 🔒 Lock button
  btn.disabled = true;
  const originalText = btn.textContent;
  btn.textContent = "Saving…";

  try {
    const res = await fetch(`/projects/tasks/${taskId}/update`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error("Save failed");

    // ✅ Success feedback
    btn.textContent = "Saved ✓";

    setTimeout(() => {
      btn.textContent = originalText || "💾 Save";
      btn.disabled = false;
    }, 1000);

  } catch (err) {
    console.error(err);
    btn.textContent = "Retry";
    btn.disabled = false;
  }
});
