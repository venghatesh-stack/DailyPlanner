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
window.updateStatus = (taskId, status,date=null) => {
  const task = $(`task-${taskId}`);
  if (!task) return;

  const prev = task.dataset.status;
  task.dataset.status = status;

  fetch("/projects/tasks/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId, status:status,date:date })
  })
    .then(r => {
      if (!r.ok) throw Error();
       location.reload();   // ✅ backend decides visibility
    })
    .catch(() => {
      task.dataset.status = prev;
      alert("Failed to update status");
    });
};

/* -------------------------
   Filters
------------------------- */
function toggleHideCompleted(checked) {
  const url = new URL(window.location.href);
  url.searchParams.set("hide_completed", checked ? "1" : "0");
  window.location.href = url.toString();
}

function toggleFilter(key, checked) {
  const url = new URL(window.location.href);
  url.searchParams.set(key, checked ? "1" : "0");
  window.location.href = url.toString();
}


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

  fetch(`/projects/tasks/${taskId}/update`, {
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
async function updateRecurrence(taskId, type) {
  const taskEl = document.getElementById(`task-${taskId}`);
  if (!taskEl) return;

  // 1️⃣ Save to backend
  await fetch(`/projects/tasks/${taskId}/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      is_recurring: type !== "none",
      recurrence_type: type
    })
  });

  // 2️⃣ Toggle weekly day UI immediately
  const weeklyBox = taskEl.querySelector(".recurrence-days");
  if (!weeklyBox) return;

  if (type === "weekly") {
    weeklyBox.style.display = "flex";   // use flex to match your layout
  } else {
    weeklyBox.style.display = "none";
  }
// 3️⃣ 🔥 UPDATE RECURRENCE BADGE HERE
  const badge = taskEl.querySelector(".repeat-badge");

  if (type === "none") {
    // Remove badge completely
    if (badge) badge.remove();
  } else {
    // If badge doesn't exist, create it
    if (!badge) {
      const newBadge = document.createElement("span");
      newBadge.className = "repeat-badge";
      taskEl.querySelector(".task-header")?.appendChild(newBadge);
    }

    const finalBadge = taskEl.querySelector(".repeat-badge");
    if (finalBadge) {
      finalBadge.textContent = `🔁 ${type}`;
    }
  }

}

function updateRecurrenceDays(taskId) {
  const box = document.querySelector(`#task-${taskId}`);
  const days = [...box.querySelectorAll('.recurrence-days input:checked')]
    .map(cb => parseInt(cb.value));

  fetch(`/projects/tasks/${taskId}/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      recurrence_days: days
    })
  });
}
function editToday(taskId) {
  const title = prompt("New title for today");

  fetch("/tasks/occurrence/update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task_id: taskId,
      date: getSelectedDate(),
      title: title
    })
  });
}
function toggleAutoAdvance(taskId, enabled) {
  fetch(`/projects/tasks/${taskId}/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      auto_advance: enabled
    })
  });
}
function attachLongPress(el, onLongPress) {
  let timer = null;
  let moved = false;

  // Desktop mouse
  el.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return; // left click only
    moved = false;

    timer = setTimeout(() => {
      if (!moved) onLongPress(e);
    }, 500);
  });

  el.addEventListener("mousemove", () => {
    moved = true;
    clearTimeout(timer);
  });

  el.addEventListener("mouseup", () => clearTimeout(timer));
  el.addEventListener("mouseleave", () => clearTimeout(timer));

  // Mobile touch
  el.addEventListener("touchstart", () => {
    timer = setTimeout(onLongPress, 500);
  });

  el.addEventListener("touchend", () => clearTimeout(timer));

  // Right-click fallback (desktop)
  el.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    onLongPress(e);
  });
}
document.querySelectorAll(".task").forEach(el => {
  attachLongPress(el, () => {
    openTaskSheet({
      taskId: el.dataset.id,
      date: el.dataset.date,
      text: el.querySelector(".task-title").innerText,
      autoAdvance: el.dataset.autoAdvance === "true"
    });
  });
});
let currentSheetTask = {};

function openTaskSheet(task) {
  currentSheetTask = task;

  document.getElementById("sheet-title").innerText = task.text;
  document.getElementById("autoAdvanceToggle").checked = !!task.autoAdvance;

  document.getElementById("task-action-sheet").classList.remove("hidden");
}

function closeTaskSheet() {
  document.getElementById("task-action-sheet").classList.add("hidden");
  currentSheetTask = {};
}
function sheetCompleteToday() {
  fetch("/projects/tasks/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task_id: currentSheetTask.taskId,
      status: "done",
      date: currentSheetTask.date
    })
  });
  closeTaskSheet();
}
function sheetEditToday() {
  const title = prompt("Edit task for today only", currentSheetTask.text);
  if (!title) return;

  fetch("/tasks/occurrence/update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task_id: currentSheetTask.taskId,
      date: currentSheetTask.date,
      title: title
    })
  });

  closeTaskSheet();
}
function sheetEditAll() {
  const title = prompt("Edit task for all future occurrences", currentSheetTask.text);
  if (!title) return;

  fetch(`/projects/tasks/${currentSheetTask.taskId}/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task_text: title
    })
  });

  closeTaskSheet();
}
function sheetToggleAutoAdvance(enabled) {
  fetch(`/projects/tasks/${currentSheetTask.taskId}/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      auto_advance: enabled
    })
  });
}
function attachScrollNumbers() {
  document.querySelectorAll(".scroll-number").forEach(el => {

    el.addEventListener("wheel", function (e) {
      e.preventDefault();

      let value = parseInt(this.value || 0);

      if (e.deltaY < 0) {
        value++;
      } else {
        value--;
      }

      if (value < 0) value = 0;
      if (value > 100) value = 100;

      this.value = value;

      // trigger change so your existing logic runs
      this.dispatchEvent(new Event("change"));
    });

  });
}

document.addEventListener("DOMContentLoaded", attachScrollNumbers);
function adjustInlineNumber(btn, direction, type, taskId, date=null) {
  const wrapper = btn.closest(".number-control");
  const input = wrapper.querySelector("input");

  const step = parseFloat(wrapper.dataset.step || 1);
  let value = parseFloat(input.value || 0);

  value += direction * step;

  if (value < 0) value = 0;
  if (value > 100) value = 100;

  input.value = value;

  // Trigger backend update
  if (type === "planned") {
    updatePlanned(taskId, value);
  }
  if (type === "actual") {
    updateActual(taskId, value);
  }
  if (type === "duration") {
    updatePlanning(taskId, date);
  }
}

function validateInlineNumber(input) {
  let value = parseFloat(input.value);

  if (isNaN(value)) value = 0;
  if (value < 0) value = 0;
  if (value > 100) value = 100;

  input.value = value;
}
document.addEventListener("wheel", function(e) {
  const wrapper = e.target.closest(".inline-number");
  if (!wrapper) return;

  e.preventDefault();

  const input = wrapper.querySelector("input");
  const step = parseFloat(wrapper.dataset.step || 1);

  let value = parseFloat(input.value || 0);

  if (e.deltaY < 0) value += step;
  else value -= step;

  if (value < 0) value = 0;
  if (value > 100) value = 100;

  input.value = value;
}, { passive: false });
