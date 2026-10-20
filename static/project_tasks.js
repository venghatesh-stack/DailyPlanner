/* =========================================================
   PROJECT TASKS  --  Microsoft Project-style task planner
   ========================================================= */

/* ---------------------------------------------------------
   Helpers
   --------------------------------------------------------- */
const _q  = (sel, ctx = document) => ctx.querySelector(sel);
const _qa = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];
const _id = id => document.getElementById(id);

function _post(url, body) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function _put(url, body) {
  return fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/* Currently open task id in the bottom sheet */
let _sheetTaskId = null;

/* Scheduled reminder timeouts (keyed by taskId) */
const _reminders = {};

/* Selected priority in the add-task picker */
let _addPriority = "medium";

/* ---------------------------------------------------------
   Priority Picker
   --------------------------------------------------------- */
function initPrioPicker() {
  const picker = _id("prio-picker");
  if (!picker) return;

  _qa(".pp-btn", picker).forEach(btn => {
    btn.addEventListener("click", () => {
      _qa(".pp-btn", picker).forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      _addPriority = btn.dataset.p;
    });
  });
}

/* ---------------------------------------------------------
   Add Task
   --------------------------------------------------------- */
function initAddTask() {
  const input = _id("add-task-input");
  const btn   = _id("add-task-btn");
  const initSel = _id("add-task-initiative");
  if (!input) return;

  input.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); addTask(); }
  });
  if (btn) btn.addEventListener("click", addTask);

  // Keep data-current in sync with the active option so the CSS tint
  // (see .add-task-initiative:not([data-current=""]) in project_tasks.css)
  // reflects the user's choice the moment they pick, not after save.
  if (initSel) {
    initSel.addEventListener("change", () => {
      initSel.dataset.current = initSel.value || "";
    });
  }
}

/* Put a freshly-added row into the table without a reload.

   `groupName` is the section the SERVER decided this task belongs in,
   using the same grouper the page used to draw the sections. Guessing
   client-side is how a task sits under "Today" until you refresh and
   discover it was "Later" all along.

   Returns false when it cannot place the row — no matching section on
   screen (the group is empty and so was never rendered), or no HTML —
   and the caller falls back to a reload. */
function insertTaskRow(html, groupName) {
  if (!html) return false;
  const tpl = document.createElement("template");
  tpl.innerHTML = html.trim();
  const row = tpl.content.querySelector("tr.task-row");
  if (!row) return false;

  // The last row already in that group, so the new one lands at the
  // bottom of its own section rather than at the top of the table.
  const peers = document.querySelectorAll(
    `tr.task-row[data-group="${(groupName || "").replace(/"/g, '\\"')}"]`);
  const anchorRow = peers[peers.length - 1];
  if (!anchorRow || !anchorRow.parentNode) return false;
  anchorRow.parentNode.insertBefore(row, anchorRow.nextSibling);

  if (window.feather) feather.replace();
  // A row that appears silently in a long table is a row you do not see.
  row.style.transition = "background-color .9s ease";
  row.style.backgroundColor = "rgba(37,99,235,.12)";
  setTimeout(() => { row.style.backgroundColor = ""; }, 900);
  // Guarded: scrollIntoView is a nicety, and a missing implementation
  // must not cost the row that was just added.
  try { row.scrollIntoView?.({ block: "nearest", behavior: "smooth" }); } catch (_) {}
  return true;
}

async function addTask() {
  const input = _id("add-task-input");
  const dateInput = _id("add-task-date");
  const initSel = _id("add-task-initiative");
  const epicSel = _id("add-task-epic");
  const sprintSel = _id("add-task-sprint");
  // iOS Safari hasn't always committed pending autocorrect / IME text
  // into .value by the time the user taps the + button — mousedown
  // steals focus before the keystroke flushes. Blur to force the
  // commit, then read .value. No-op on desktop.
  try { input?.blur(); } catch (_) {}
  const text = (input?.value || "").trim();
  if (!text) {
    // Empty-text returns used to be silent, which read as "the button
    // did nothing" on mobile. Give a visible nudge instead.
    if (window.showToast) showToast("Type a task first", "warning", 1800);
    input?.focus();
    return;
  }

  // Empty string → leave the task tied to the project only (no initiative/epic/sprint).
  const initiativeId = (initSel?.value || "").trim() || null;
  const epicId       = (epicSel?.value || "").trim() || null;
  const sprintId     = (sprintSel?.value || "").trim() || null;
  const goalSel      = _id("add-task-goal");
  const objectiveId  = (goalSel?.value || "").trim() || null;

  try {
    const res = await _post(`/projects/${PROJECT_ID}/tasks/add-ajax`, {
      task_text: text,
      priority: _addPriority,
      start_date: dateInput?.value || "",
      objective_id: objectiveId,
      initiative_id: initiativeId,
      epic_id: epicId,
      sprint_id: sprintId,
    });

    if (!res.ok) throw new Error("Add failed");
    const data = await res.json().catch(() => ({}));

    input.value = "";
    // Remember the initiative + epic + sprint picks so rapid adds inherit them.
    // Remember the goal too, so a run of tasks for one goal is typed
    // once rather than re-picked every time.
    if (goalSel)   goalSel.dataset.current   = objectiveId   || "";
    if (initSel)   initSel.dataset.current   = initiativeId || "";
    if (epicSel)   epicSel.dataset.current   = epicId       || "";
    if (sprintSel) sprintSel.dataset.current = sprintId     || "";
    showToast(
      sprintId ? "Task added to sprint"
        : epicId ? "Task added to epic"
          : initiativeId ? "Task added to initiative"
            : "Task added",
      "success",
    );

    /* ── NO RELOAD ────────────────────────────────────────────────
       This used to end with location.reload(), so adding five tasks
       meant five full page loads of a page that issues a dozen queries.
       The server already renders the row — the SAME partial the list
       renders (_project_task_row.html) — and tells us which group it
       belongs in, so the row can simply be placed.

       Falls back to the reload if anything is missing: a row that never
       appears is worse than a slow page. */
    const placed = insertTaskRow(data.html, data.group);
    if (!placed) { location.reload(); return; }
    // Focus stays in the box: adding tasks is something people do in
    // runs of five, not once.
    try { input.focus(); } catch (_) {}
  } catch (err) {
    console.error(err);
    showToast("Failed to add task", "error");
  }
}

/* ---------------------------------------------------------
   Toggle Task Done (checkbox)
   --------------------------------------------------------- */
function toggleTaskDone(checkbox, taskId, date) {
  const status = checkbox.checked ? "done" : "open";
  const row = checkbox.closest(".task-row");

  _post("/projects/tasks/status", { task_id: taskId, status, date })
    .then(r => {
      if (!r.ok) throw new Error();

      if (row) {
        row.classList.toggle("done", status === "done");
        row.dataset.status = status;
        // update the status select in the same row
        const sel = _q(".status-select", row);
        if (sel) sel.value = status;
        // Celebrate completions with a brief pulse (batch-A polish)
        if (status === "done" && window.ptPulse) ptPulse(row);
      }

      // If hide-done filter is active, fade out
      const hiding = new URL(location.href).searchParams.get("hide_completed") === "1";
      if (hiding && status === "done" && row) {
        row.style.transition = "opacity .4s, transform .4s";
        row.style.opacity = "0";
        row.style.transform = "translateX(20px)";
        setTimeout(() => row.remove(), 420);
      }

      updateProjectStats();
      showToast(status === "done" ? "Marked complete" : "Reopened", "success");
    })
    .catch(() => {
      checkbox.checked = !checkbox.checked;
      showToast("Failed to update status", "error");
    });
}

/* ---------------------------------------------------------
   Status Select
   --------------------------------------------------------- */
function updateStatus(taskId, value, date) {
  const row = document.querySelector(`.task-row[data-id="${taskId}"]`);

  _post("/projects/tasks/status", { task_id: taskId, status: value, date })
    .then(r => {
      if (!r.ok) throw new Error();
      if (row) {
        const isDone = value === "done";
        row.classList.toggle("done", isDone);
        row.dataset.status = value;
        const cb = _q(".task-check", row);
        if (cb) cb.checked = isDone;
        // Update select styling
        const sel = _q(".status-select", row);
        if (sel) {
          sel.className = "status-select status-" + value;
        }
      }
      updateProjectStats();
      showToast("Status updated", "success");
    })
    .catch(() => showToast("Status update failed", "error"));
}

/* ---------------------------------------------------------
   Generic Field Update (inline editing in table)
   --------------------------------------------------------- */
function updateField(taskId, field, value) {
  // Planning fields (start_date, duration_days) need the planning endpoint
  if (field === "start_date" || field === "duration_days") {
    const row = document.querySelector(`.task-row[data-id="${taskId}"]`);
    const startInput = _q('input[type="date"].cell-date', _q(".col-start", row));
    const durInput   = _q('input[type="number"].cell-num', _q(".col-dur", row));

    _post("/projects/tasks/update-planning", {
      task_id: taskId,
      start_date: startInput?.value || "",
      duration_days: durInput?.value || 1,
    })
      .then(r => r.json())
      .then(data => {
        if (data.due_date && row) {
          const dueInput = _q(".col-due input.cell-date", row);
          if (dueInput) dueInput.value = data.due_date;
          updateDueLabel(row, data.due_date);
        }
        updateProjectStats();
      })
      .catch(console.error);
    return;
  }

  // Due date has its own endpoint
  if (field === "due_date") {
    _post("/projects/tasks/update-date", { task_id: taskId, due_date: value })
      .then(() => {
        const row = document.querySelector(`.task-row[data-id="${taskId}"]`);
        if (row) updateDueLabel(row, value);
        updateProjectStats();
      })
      .catch(console.error);
    return;
  }

  // All other fields
  _post(`/projects/tasks/${taskId}/update`, { [field]: value })
    .catch(console.error);
}

/* Helper: refresh the due-label text in a row */
function updateDueLabel(row, dueDateStr) {
  const label = _q(".due-label", row);
  if (!dueDateStr) {
    if (label) label.textContent = "";
    row.classList.remove("overdue");
    return;
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const [y, m, d] = dueDateStr.split("-").map(Number);
  const due = new Date(y, m - 1, d);
  const diff = Math.round((due - today) / 86400000);

  if (!label) return;
  label.classList.remove("overdue-label");
  row.classList.remove("overdue");

  if (diff < 0) {
    label.textContent = `${Math.abs(diff)}d overdue`;
    label.classList.add("overdue-label");
    row.classList.add("overdue");
  } else if (diff === 0) {
    label.textContent = "Today";
  } else if (diff === 1) {
    label.textContent = "Tomorrow";
  } else {
    label.textContent = `In ${diff}d`;
  }
}

/* ---------------------------------------------------------
   Priority Cycling  (dot click in table)
   --------------------------------------------------------- */
const PRIO_ORDER = ["high", "medium", "low"];

function cyclePriority(taskId, el) {
  const current = el.className.replace("prio-dot prio-", "").trim();
  const idx = PRIO_ORDER.indexOf(current);
  const next = PRIO_ORDER[(idx + 1) % PRIO_ORDER.length];

  el.className = `prio-dot prio-${next}`;
  el.title = next;

  const row = el.closest(".task-row");
  if (row) row.dataset.priority = next;

  _post("/projects/tasks/update-priority", { task_id: taskId, priority: next })
    .then(() => showToast(`Priority: ${next}`, "success"))
    .catch(() => showToast("Priority update failed", "error"));
}

/* ---------------------------------------------------------
   Group Toggle  (collapse/expand)
   --------------------------------------------------------- */
function toggleGroup(el) {
  el.classList.toggle("collapsed");
  const row = el.closest(".group-row");
  if (!row) return;

  const groupName = row.dataset.group;
  const collapsed = el.classList.contains("collapsed");

  _qa(`.task-row[data-group="${groupName}"]`).forEach(tr => {
    tr.classList.toggle("hidden-group", collapsed);
  });

  // Rotate chevron
  const chevron = _q(".group-chevron", el);
  if (chevron) {
    chevron.style.transform = collapsed ? "rotate(-90deg)" : "";
  }
}

/* ---------------------------------------------------------
   View Switching  (table / board)
   --------------------------------------------------------- */
function setTaskView(view) {
  const tableView = _id("table-view");
  const boardView = _id("board-view");
  if (!tableView || !boardView) return;

  // Legacy "compact" users fall back to the new default minimal list.
  if (view === "compact") view = "table";

  const showTable = (view === "table");
  tableView.classList.toggle("hidden", !showTable);
  boardView.classList.toggle("hidden", view !== "board");

  // Ensure the retired compact styles never bleed in.
  document.body.classList.remove("pt-view-compact");

  _qa(".vt-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.view === view);
  });

  try { localStorage.setItem("pt_view", view); } catch {}

  if (view === "board") populateBoard();
}

// Restore last-used view on load
(function restoreTaskView() {
  try {
    const saved = localStorage.getItem("pt_view");
    if (saved && saved !== "table") {
      document.addEventListener("DOMContentLoaded", () => setTaskView(saved), { once: true });
    }
  } catch {}
})();

/* ---------------------------------------------------------
   Mobile row tap-anywhere: whole row opens the detail panel
   (except for clicks on the checkbox or status <select>).
   Matches Todoist's "tap anywhere on the row to open" pattern.
   --------------------------------------------------------- */
(function wireRowTapToOpen() {
  document.addEventListener("click", (ev) => {
    // Only engage on mobile widths
    if (window.matchMedia("(min-width: 769px)").matches) return;
    // Skip when in select mode — selection handler owns clicks
    if (window.PT_SEL && PT_SEL.active) return;

    const row = ev.target.closest(".task-row");
    if (!row) return;

    // Don't hijack clicks on interactive controls inside the row
    const interactive = ev.target.closest(
      ".task-check, .status-select, select, input, button, a, .inline-subtask"
    );
    if (interactive) return;

    const taskId = row.dataset.id;
    if (!taskId) return;
    ev.preventDefault();
    if (typeof openTaskDetail === "function") openTaskDetail(taskId);
  }, true);
})();

/* ---------------------------------------------------------
   Board View (Kanban)
   --------------------------------------------------------- */
function populateBoard() {
  // Clear columns
  ["backlog", "open", "in_progress", "done"].forEach(status => {
    const col = _id(`board-${status}`);
    if (col) col.innerHTML = "";
  });

  // Closed-but-not-"done" statuses live in the Done column visually.
  // Legacy "not_required" maps to "done" as well (treated as a deleted alias).
  const CLOSED_ALIAS = { skipped: "done", deleted: "done", not_required: "done" };
  const hideClosed = document.body.classList.contains("pt-hide-closed");
  const HIDDEN_STATUSES = new Set(["skipped", "deleted", "not_required"]);

  _qa(".task-row").forEach(row => {
    if (row.classList.contains("okr-hidden")) return;
    const rawStatus = row.dataset.status || "open";
    if (hideClosed && HIDDEN_STATUSES.has(rawStatus)) return;
    const status = CLOSED_ALIAS[rawStatus] || rawStatus;
    const col = _id(`board-${status}`);
    if (!col) return;

    const id   = row.dataset.id;
    const text = _q(".task-text", row)?.textContent.trim() || "";
    const prio = row.dataset.priority || "medium";
    const dueInput = _q(".col-due input.cell-date", row);
    const due  = dueInput?.value || "";

    const card = document.createElement("div");
    card.className = `board-card prio-border-${prio}`;
    card.dataset.id = id;
    // Only wire the click-to-open handler when NOT in select mode.
    // In select mode, the document-level capture handler below intercepts
    // clicks and toggles selection instead.
    if (!PT_SEL || !PT_SEL.active) {
      card.onclick = () => openTaskDetail(id);
    }
    if (PT_SEL && PT_SEL.ids.has(id)) {
      card.classList.add("pt-selected");
    }

    card.innerHTML = `
      <div class="board-card-title">${_escHtml(text)}</div>
      ${due ? `<div class="board-card-due">${due}</div>` : ""}
    `;
    col.appendChild(card);
  });
}

function _escHtml(str) {
  const el = document.createElement("span");
  el.textContent = str;
  return el.innerHTML;
}

/* ---------------------------------------------------------
   Filters
   --------------------------------------------------------- */
function initFilters() {
  const hideDone = _id("filter-hide-done");
  const overdue  = _id("filter-overdue");
  const hideClosed = _id("filter-hide-closed");

  if (hideDone) {
    hideDone.addEventListener("change", () => {
      const url = new URL(location.href);
      url.searchParams.set("hide_completed", hideDone.checked ? "1" : "0");
      location.href = url.toString();
    });
  }

  if (overdue) {
    overdue.addEventListener("change", () => {
      const url = new URL(location.href);
      url.searchParams.set("overdue_only", overdue.checked ? "1" : "0");
      location.href = url.toString();
    });
  }

  if (hideClosed) {
    // Client-side filter — toggles a body class, persisted in localStorage.
    // Deleted rows are already filtered server-side (is_eliminated=false),
    // so this really gates skipped rows, but the class also covers any
    // deleted rows that might slip through future server changes.
    const KEY = "pt_hide_closed";
    const stored = localStorage.getItem(KEY);
    const on = stored === null ? true : stored === "1";
    hideClosed.checked = on;
    applyHideClosed(on);

    hideClosed.addEventListener("change", () => {
      localStorage.setItem(KEY, hideClosed.checked ? "1" : "0");
      applyHideClosed(hideClosed.checked);
    });
  }
}

function applyHideClosed(on) {
  document.body.classList.toggle("pt-hide-closed", on);
  // Also refresh the board if it's currently visible, so rows hidden/shown
  // in the table mirror correctly into the kanban.
  if (typeof populateBoard === "function" &&
      !_id("board-view")?.classList.contains("hidden")) {
    populateBoard();
  }
}

/* ---------------------------------------------------------
   Sort
   --------------------------------------------------------- */
function initSort() {
  const sel = _id("sort-select");
  if (!sel) return;

  sel.addEventListener("change", async () => {
    await _post(`/projects/${PROJECT_ID}/set-sort`, { sort: sel.value });
    const url = new URL(location.href);
    url.searchParams.set("sort", sel.value);
    location.href = url.toString();
  });
}

/* ---------------------------------------------------------
   Project Stats
   --------------------------------------------------------- */
function updateProjectStats() {
  const rows    = _qa(".task-row");
  const total   = rows.length;
  const done    = rows.filter(r => r.classList.contains("done")).length;
  const overdue = rows.filter(r => r.classList.contains("overdue")).length;

  const elTotal   = _id("stat-total");
  const elDone    = _id("stat-done");
  const elOverdue = _id("stat-overdue");
  const elFill    = _id("proj-progress-fill");

  if (elTotal)   elTotal.textContent   = `${total} task${total !== 1 ? "s" : ""}`;
  if (elDone)    elDone.textContent    = `${done} done`;
  if (elOverdue) elOverdue.textContent = `${overdue} overdue`;

  if (elFill) {
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    elFill.style.width = pct + "%";
  }
}

/* ---------------------------------------------------------
   Task Detail Side Panel
   --------------------------------------------------------- */
async function openTaskDetail(taskId) {
  _sheetTaskId = taskId;

  try {
    const res = await fetch(`/api/v2/project-tasks/${taskId}`);
    if (!res.ok) throw new Error();
    const t = await res.json();

    // Populate fields
    _val("sheet-name",      t.task_text || "");
    _val("sheet-status",    t.status || "open");
    _val("sheet-priority",  t.priority || "medium");
    _val("sheet-start",     t.start_date || "");
    _val("sheet-due",       t.due_date || "");
    _val("sheet-duration",  t.duration_days ?? "");
    _val("sheet-due-time",  t.due_time || "");
    // Highlight the matching Due-Time preset chip, if any
    _qa(".time-preset-chip").forEach(c => {
      const onClick = c.getAttribute("onclick") || "";
      const normalized = (t.due_time || "").slice(0, 5);
      c.classList.toggle("active", !!normalized && onClick.includes(`'${normalized}'`));
    });
    _val("sheet-planned",   t.planned_hours ?? "");
    _val("sheet-actual",    t.actual_hours ?? "");
    _val("sheet-delegate",  t.delegated_to || "");
    _val("sheet-notes",     t.notes || "");
    renderSheetLinks(t.notes || "");
    _val("sheet-reminder",  "");
    _val("sheet-quadrant",  t.quadrant || "");

    // Hours progress bar
    updateHoursProgress();

    // Recurrence — use the UI-only initializer so loading the panel
    // doesn't fire a spurious save.
    const recType = t.is_recurring ? (t.recurrence_type || "daily") : "none";
    _val("sheet-recurrence", recType);
    _initRecurrenceUI();

    if (recType === "weekly" && Array.isArray(t.recurrence_days)) {
      _qa("#recurrence-days .day-chip").forEach(chip => {
        chip.classList.toggle("active", t.recurrence_days.includes(parseInt(chip.dataset.day)));
      });
    }

    loadSubtasks(taskId);

    // Open panel with animation
    const panel = _id("task-panel");
    const overlay = _id("task-panel-overlay");
    if (panel) {
      panel.classList.remove("hidden");
      requestAnimationFrame(() => panel.classList.add("open"));
    }
    if (overlay) overlay.classList.remove("hidden");

    feather.replace();
  } catch (err) {
    console.error(err);
    showToast("Failed to load task details", "error");
  }
}

function _val(id, value) {
  const el = _id(id);
  if (el) el.value = value;
}

/* Set the Due Time via a preset chip (or clear it with ""). Updates
   the input and fires the same autoSaveField path as a manual change. */
function quickSetTime(hhmm) {
  const el = _id("sheet-due-time");
  if (!el) return;
  el.value = hhmm || "";
  // Mark the matching preset as active so the user can see their choice
  _qa(".time-preset-chip").forEach(c => {
    const onClick = c.getAttribute("onclick") || "";
    const matches = hhmm && onClick.includes(`'${hhmm}'`);
    c.classList.toggle("active", !!matches);
  });
  autoSaveField("due_time", el.value);
}

/* (Retired) openDatePicker + capture-phase stopPropagation
   ------------------------------------------------------------------
   The .panel-date-wrap used to be a <div onclick="openDatePicker()">
   containing an <input type="date">. That made two independent paths
   to open the native picker:
     1. The wrapper onclick calling HTMLInputElement.showPicker()
     2. The browser's native "click opens picker" on the input itself
   Any click that hit the input fired both — causing NotAllowedError
   on some browsers and a stuck-picker loop on Chrome desktop when
   the ::-webkit-calendar-picker-indicator pseudo-element reported an
   unexpected event.target.

   The definitive fix is structural: the wrapper is now a
   <label for="..."> which forwards clicks to the associated input
   natively, exactly once, with no JS. So the helpers here are dead
   code and intentionally removed. Don't reintroduce them — a single
   code path is the whole point of the fix. */

function closeTaskSheet() {
  const panel = _id("task-panel");
  const overlay = _id("task-panel-overlay");

  // Release focus from whatever's inside the panel before we start the
  // close animation. Without this, a focused date/time input will keep
  // the native picker alive across the 250ms fade-out, and the next
  // tap on the still-present .panel-date-wrap will re-open it — the
  // "stuck picker" loop users reported.
  if (panel && document.activeElement && panel.contains(document.activeElement)
      && typeof document.activeElement.blur === "function") {
    document.activeElement.blur();
  }

  if (panel) {
    panel.classList.remove("open");
    setTimeout(() => panel.classList.add("hidden"), 250);
  }
  if (overlay) overlay.classList.add("hidden");
  _sheetTaskId = null;
}

/* ---------------------------------------------------------
   Auto-save a single field from the task detail panel.
   • Routes to the correct endpoint per field.
   • Verifies the HTTP response is OK and parses Supabase's own error.
   • Updates the background task row visually on success, so closing
     the panel immediately shows the new value.
   • Surfaces errors via a toast and the inline "Save failed" indicator.
   --------------------------------------------------------- */
let _saveTimer = null;

async function autoSaveField(field, value) {
  if (!_sheetTaskId) return;

  const indicator = _id("saved-indicator");
  const taskId = _sheetTaskId;

  if (indicator) {
    indicator.textContent = "Saving…";
    indicator.classList.remove("error");
    indicator.classList.add("show");
  }

  // Decide endpoint + payload per field
  let url, body;
  switch (field) {
    case "due_date":
      url = "/projects/tasks/update-date";
      body = { task_id: taskId, due_date: value };
      break;
    case "start_date":
    case "duration_days":
      url = "/projects/tasks/update-planning";
      body = {
        task_id: taskId,
        start_date: _id("sheet-start")?.value || null,
        duration_days: _id("sheet-duration")?.value || null,
      };
      break;
    case "planned_hours":
      url = "/projects/tasks/update-planned";
      body = { task_id: taskId, planned_hours: value };
      break;
    case "actual_hours":
      url = "/projects/tasks/update-actual";
      body = { task_id: taskId, actual_hours: value };
      break;
    case "due_time":
      url = "/projects/tasks/update-time";
      body = { id: taskId, due_time: value };
      break;
    case "delegated_to":
      url = `/projects/tasks/${taskId}/update`;
      body = { delegated_to: value };
      break;
    case "status":
      url = "/projects/tasks/status";
      body = { task_id: taskId, status: value };
      break;
    case "priority":
      url = "/projects/tasks/update-priority";
      body = { task_id: taskId, priority: value };
      break;
    default:
      url = `/projects/tasks/${taskId}/update`;
      body = { [field]: value };
  }

  try {
    const res = await _post(url, body);
    if (!res.ok) {
      // Try to extract a server-provided error message
      let msg = `Save failed (${res.status})`;
      try {
        const payload = await res.json();
        if (payload && (payload.error || payload.message)) {
          msg = payload.error || payload.message;
        }
      } catch {}
      throw new Error(msg);
    }

    // Success — sync background row, panel internals, and stats
    _syncBackgroundRow(taskId, field, value);
    if (field === "planned_hours" || field === "actual_hours") updateHoursProgress();
    if (field === "status" || field === "task_text" || field === "due_date") updateProjectStats();

    if (indicator) {
      indicator.textContent = "Saved";
      indicator.classList.remove("error");
      indicator.classList.add("show");
      clearTimeout(_saveTimer);
      _saveTimer = setTimeout(() => indicator.classList.remove("show"), 1800);
    }
  } catch (err) {
    console.error("autoSaveField failed:", field, "→", err);
    if (indicator) {
      indicator.textContent = "Save failed";
      indicator.classList.add("show", "error");
    }
    showToast(err.message || "Failed to save", "error");
  }
}

/* Update the task row in the table behind the panel so closing the
   panel immediately reflects the panel's edits. */
function _syncBackgroundRow(taskId, field, value) {
  const row = document.querySelector(`.task-row[data-id="${taskId}"]`);
  if (!row) return;

  if (field === "status") {
    const isDone = value === "done";
    row.classList.toggle("done", isDone);
    row.dataset.status = value;
    const cb = _q(".task-check", row);
    if (cb) cb.checked = isDone;
    const sel = _q(".status-select", row);
    if (sel) {
      sel.value = value;
      sel.className = "status-select status-" + value;
    }
    // If soft-deleted from the panel, drop the row (matches the toast/close flow)
    if (value === "deleted") {
      row.style.transition = "opacity .3s, transform .3s";
      row.style.opacity = "0";
      row.style.transform = "translateX(20px)";
      setTimeout(() => row.remove(), 320);
    }
  } else if (field === "priority") {
    row.dataset.priority = value;
    const dot = _q(".prio-dot", row);
    if (dot) {
      dot.classList.remove("prio-high", "prio-medium", "prio-low");
      dot.classList.add("prio-" + value);
      dot.setAttribute("title", value);
    }
  } else if (field === "task_text") {
    const textEl = _q(".task-text", row);
    if (textEl) {
      textEl.textContent = value;
      textEl.setAttribute("title", value);
    }
  } else if (field === "due_date") {
    const dateInput = _q(".col-due input.cell-date", row);
    if (dateInput) dateInput.value = value || "";
    if (typeof updateDueLabel === "function") updateDueLabel(row, value);
  } else if (field === "start_date") {
    const dateInput = _q(".col-start input.cell-date", row);
    if (dateInput) dateInput.value = value || "";
  } else if (field === "duration_days") {
    const numInput = _q(".col-dur input.cell-num", row);
    if (numInput) numInput.value = value || 0;
  } else if (field === "planned_hours" || field === "actual_hours") {
    // Mini progress bar lives in .col-progress — recompute from the
    // hidden cells we can reach. Planned/actual aren't rendered in the
    // table row's visible cells, so the bar will refresh on next page
    // load. Not strictly necessary to re-draw it here.
  } else if (field === "initiative_id") {
    row.dataset.initiativeId = value || "";
  } else if (field === "notes" || field === "delegated_to" || field === "due_time") {
    // These aren't shown in the compact row; nothing to update.
  }
}

function stepField(fieldId, delta) {
  const el = _id(fieldId);
  if (!el) return;
  const step = parseFloat(el.step) || 1;
  const current = parseFloat(el.value) || 0;
  el.value = Math.max(0, current + delta);
  el.dispatchEvent(new Event("change"));
}

function updateHoursProgress() {
  const planned = parseFloat(_id("sheet-planned")?.value) || 0;
  const actual = parseFloat(_id("sheet-actual")?.value) || 0;
  const container = _id("hours-progress");
  if (!container) return;

  if (planned > 0) {
    const pct = Math.min(100, Math.round((actual / planned) * 100));
    container.innerHTML = `<div class="hours-progress-fill" style="width:${pct}%"></div>`;
    container.title = `${actual}h / ${planned}h (${pct}%)`;
  } else {
    container.innerHTML = "";
  }
}

/* Legacy save function — still used by recurrence save */
async function saveTaskSheet() {
  if (!_sheetTaskId) return;

  try {
    const recurrence = _id("sheet-recurrence")?.value || "none";
    const isRecurring = recurrence !== "none";
    const recurrenceDays = isRecurring && recurrence === "weekly"
      ? Array.from(_qa("#recurrence-days .day-chip.active")).map(c => parseInt(c.dataset.day))
      : [];

    await _post(`/projects/tasks/${_sheetTaskId}/update`, {
      is_recurring: isRecurring,
      recurrence_type: isRecurring ? recurrence : null,
      recurrence_days: recurrenceDays.length ? recurrenceDays : null,
    });

    const reminderMin = _id("sheet-reminder")?.value;
    const due = _id("sheet-due")?.value;
    const dueTime = _id("sheet-due-time")?.value;
    if (reminderMin !== "" && due && dueTime) {
      scheduleReminder(_sheetTaskId, _id("sheet-name")?.value, due, dueTime, parseInt(reminderMin));
    }

    showToast("Saved", "success");
  } catch (err) {
    console.error(err);
    showToast("Failed to save", "error");
  }
}

/* ---------------------------------------------------------
   Google Calendar Integration
   --------------------------------------------------------- */
function addTaskToGCal(taskId) {
  const row = document.querySelector(`.task-row[data-id="${taskId}"]`);
  if (!row) return;

  const title   = _q(".task-text", row)?.textContent.trim() || "Task";
  const dueInput = _q(".col-due input.cell-date", row);
  const dueDate = dueInput?.value || "";

  _openGCalUrl(title, dueDate, "", "");
}

function addSheetTaskToGCal() {
  const title   = _id("sheet-name")?.value.trim() || "Task";
  const dueDate = _id("sheet-due")?.value || "";
  const dueTime = _id("sheet-due-time")?.value || "";
  const notes   = _id("sheet-notes")?.value || "";

  _openGCalUrl(title, dueDate, dueTime, notes);
}

function _openGCalUrl(title, dueDate, dueTime, notes) {
  if (!dueDate) {
    showToast("Set a due date first", "error");
    return;
  }

  const dateClean = dueDate.replace(/-/g, "");
  let startStr, endStr;

  if (dueTime) {
    const timeClean = dueTime.replace(/:/g, "") + "00";
    startStr = `${dateClean}T${timeClean}`;
    // Default 1-hour event
    const startDt = new Date(`${dueDate}T${dueTime}`);
    const endDt   = new Date(startDt.getTime() + 3600000);
    const pad2 = n => String(n).padStart(2, "0");
    endStr = `${endDt.getFullYear()}${pad2(endDt.getMonth()+1)}${pad2(endDt.getDate())}` +
             `T${pad2(endDt.getHours())}${pad2(endDt.getMinutes())}00`;
  } else {
    // All-day event
    startStr = dateClean;
    const next = new Date(`${dueDate}T00:00:00`);
    next.setDate(next.getDate() + 1);
    const pad2 = n => String(n).padStart(2, "0");
    endStr = `${next.getFullYear()}${pad2(next.getMonth()+1)}${pad2(next.getDate())}`;
  }

  const url = `https://calendar.google.com/calendar/r/eventedit?` +
    `text=${encodeURIComponent(title)}` +
    `&dates=${startStr}/${endStr}` +
    (notes ? `&details=${encodeURIComponent(notes)}` : "");

  window.open(url, "_blank");
}

/* ---------------------------------------------------------
   Browser Notification Reminders
   --------------------------------------------------------- */
function scheduleReminder(taskId, title, dueDate, dueTime, reminderMinutes) {
  if (!dueDate || !dueTime) return;

  // Clear existing reminder for this task
  if (_reminders[taskId]) {
    clearTimeout(_reminders[taskId]);
    delete _reminders[taskId];
  }

  const dueMs = new Date(`${dueDate}T${dueTime}`).getTime();
  const reminderMs = dueMs - (reminderMinutes * 60 * 1000);
  const now = Date.now();

  if (reminderMs <= now) return; // already passed

  // Request permission
  if (Notification.permission === "default") {
    Notification.requestPermission();
  }

  _reminders[taskId] = setTimeout(() => {
    if (Notification.permission === "granted") {
      new Notification("Task Reminder", {
        body: title,
        icon: "/static/favicon.png",
      });
    }
    delete _reminders[taskId];
  }, reminderMs - now);
}

function schedulePageReminders() {
  if (!("Notification" in window)) return;

  _qa(".task-row").forEach(row => {
    const id = row.dataset.id;
    const dueInput = _q(".col-due input.cell-date", row);
    const dueDate = dueInput?.value || "";
    if (dueDate !== TODAY) return;

    const title = _q(".task-text", row)?.textContent.trim() || "";
    // Default: remind 15 min before noon if no due time
    scheduleReminder(id, title, dueDate, "12:00", 15);
  });
}

/* ---------------------------------------------------------
   Subtasks
   --------------------------------------------------------- */
async function loadSubtasks(taskId) {
  const list = _id("subtask-list");
  if (!list) return;
  list.innerHTML = "";

  try {
    const res = await fetch(`/subtask/list/${taskId}`);
    if (!res.ok) return;
    const subtasks = await res.json();
    subtasks.forEach(st => _renderSubtask(list, st));
  } catch (e) {
    console.debug("No subtasks loaded", e);
  }
}

function _renderSubtask(container, st) {
  const item = document.createElement("div");
  item.className = "subtask-item";
  item.dataset.id = st.id;
  item.innerHTML = `
    <label class="subtask-item-label">
      <input type="checkbox" ${st.is_done ? "checked" : ""}
             onchange="toggleSubtask('${st.id}', this.checked, this)">
      <span class="${st.is_done ? "st-done" : ""}">${_escHtml(st.title)}</span>
    </label>
    <button type="button" class="subtask-del-btn" title="Delete subtask"
            onclick="deleteSubtask('${st.id}', this)" aria-label="Delete subtask">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
           stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M6 6l12 12M18 6L6 18"/>
      </svg>
    </button>
  `;
  container.appendChild(item);
}

// Delete confirmation is inline now — clicking × swaps the row into
// a "Delete ?" banner with Yes/Cancel buttons. No browser confirm().
function deleteSubtask(subId, btn) {
  if (!subId) return;
  const row = btn?.closest(".subtask-item");
  if (!row) return;

  // If already in confirm mode, ignore repeat clicks
  if (row.classList.contains("confirming-delete")) return;

  const title = row.querySelector(".subtask-item-label span")?.textContent?.trim() || "this subtask";
  const originalHTML = row.innerHTML;

  // Swap the row to an inline confirm banner
  row.classList.add("confirming-delete");
  row.innerHTML = `
    <div class="subtask-confirm">
      <svg class="subtask-confirm-icon" viewBox="0 0 24 24" width="16" height="16"
           fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/>
        <line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      <span class="subtask-confirm-text">Delete <b>${_escHtml(title)}</b>?</span>
      <div class="subtask-confirm-actions">
        <button type="button" class="subtask-confirm-no">Cancel</button>
        <button type="button" class="subtask-confirm-yes">Delete</button>
      </div>
    </div>
  `;

  const cleanup = () => {
    row.classList.remove("confirming-delete");
    row.innerHTML = originalHTML;
  };

  row.querySelector(".subtask-confirm-no").onclick = cleanup;

  row.querySelector(".subtask-confirm-yes").onclick = async () => {
    // Optimistic fade on confirmed deletion
    row.style.transition = "opacity .2s, transform .2s, max-height .2s, margin .2s, padding .2s";
    row.style.opacity = "0";
    row.style.transform = "translateX(12px)";
    row.style.maxHeight = "0";
    row.style.marginTop = "0";
    row.style.marginBottom = "0";
    row.style.paddingTop = "0";
    row.style.paddingBottom = "0";

    try {
      const res = await _post("/subtask/delete", { id: subId });
      if (!res.ok) {
        let msg = `Delete failed (${res.status})`;
        try { const p = await res.json(); if (p.error) msg = p.error; } catch {}
        throw new Error(msg);
      }
      setTimeout(() => row.remove(), 220);

      // Update the subtask count badge in the panel
      const list = _id("subtask-list");
      const countEl = _id("subtask-count");
      if (countEl && list) {
        const remaining = Math.max(0, list.querySelectorAll(".subtask-item").length - 1);
        countEl.textContent = remaining || "";
      }
      if (_sheetTaskId && typeof updateSubtaskBadges === "function") updateSubtaskBadges();
      showToast("Subtask deleted", "success");
    } catch (err) {
      console.error("deleteSubtask:", err);
      // Roll back the fade and restore the original row
      row.style.cssText = "";
      cleanup();
      showToast(err.message || "Failed to delete subtask", "error");
    }
  };
}

async function addSubtask() {
  const input = _id("subtask-input");
  const title = (input?.value || "").trim();
  if (!title || !_sheetTaskId) return;

  try {
    const res = await fetch("/subtask/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: PROJECT_ID, task_id: _sheetTaskId, title }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast(err.error || "Failed to add subtask", "error");
      return;
    }

    const st = await res.json();
    const list = _id("subtask-list");
    if (list) {
      _renderSubtask(list, { id: st.id || Date.now(), title: st.title || title, is_done: false });
    }
    input.value = "";

    // Update subtask count
    const countEl = _id("subtask-count");
    if (countEl && list) {
      countEl.textContent = list.children.length;
    }
  } catch {
    showToast("Failed to add subtask", "error");
  }
}

function toggleSubtask(id, isDone, cb) {
  // Optimistic strike-through on the label text
  if (cb) {
    const span = cb.parentElement?.querySelector("span");
    if (span) span.classList.toggle("st-done", isDone);
  }
  _post("/subtask/toggle", { id, is_done: isDone }).catch(console.error);

  // Update badge count if visible
  updateSubtaskBadges();
}

/* Toggle inline subtask list visibility */
function toggleSubtasks(btn) {
  btn.classList.toggle("expanded");
  const row = btn.closest("td");
  const subtaskDiv = row?.querySelector(".inline-subtasks");
  if (subtaskDiv) subtaskDiv.classList.toggle("collapsed");
}

/* Add subtask inline (from the table row, not the side panel) */
async function addInlineSubtask(input) {
  const title = (input.value || "").trim();
  const taskId = input.dataset.taskId;
  if (!title || !taskId) return;

  try {
    const res = await fetch("/subtask/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: PROJECT_ID, task_id: taskId, title }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast(err.error || "Failed to add subtask", "error");
      return;
    }

    const st = await res.json();

    // Insert new subtask before the add input
    const container = input.closest(".inline-subtasks");
    const addRow = input.closest(".inline-add-subtask");
    if (container && addRow) {
      const label = document.createElement("label");
      label.className = "inline-subtask";
      label.innerHTML = `
        <input type="checkbox" onchange="toggleSubtask('${st.id}', this.checked); this.parentElement.classList.toggle('st-done')">
        <span>${_escHtml(st.title || title)}</span>
      `;
      container.insertBefore(label, addRow);
    }

    input.value = "";
    updateSubtaskBadges();
    showToast("Subtask added", "success");
  } catch {
    showToast("Failed to add subtask", "error");
  }
}

/* Update all subtask badges (done/total count) */
function updateSubtaskBadges() {
  _qa(".inline-subtasks").forEach(container => {
    const taskId = container.dataset.taskId;
    const row = container.closest("tr");
    if (!row) return;

    const checks = container.querySelectorAll("input[type=checkbox]");
    const done = Array.from(checks).filter(c => c.checked).length;
    const total = checks.length;

    const badge = row.querySelector(".subtask-badge");
    if (badge) badge.textContent = `${done}/${total}`;
  });
}

/* ---------------------------------------------------------
   Recurrence Change
   --------------------------------------------------------- */
// Visibility + chip bindings only — safe to call on panel open (no save).
function _initRecurrenceUI() {
  const sel = _id("sheet-recurrence");
  const daysEl = _id("recurrence-days");
  if (!sel || !daysEl) return;

  daysEl.classList.toggle("hidden", sel.value !== "weekly");

  _qa(".day-chip", daysEl).forEach(chip => {
    chip.onclick = () => {
      chip.classList.toggle("active");
      _saveRecurrence();     // save on every day-chip toggle
    };
  });
}

// Fired only by the select's onchange (user action) — updates UI then persists.
function onRecurrenceChange() {
  _initRecurrenceUI();
  _saveRecurrence();
}

async function _saveRecurrence() {
  if (!_sheetTaskId) {
    console.warn("_saveRecurrence: no _sheetTaskId");
    return;
  }
  const recurrence = _id("sheet-recurrence")?.value || "none";
  const isRecurring = recurrence !== "none";
  const recurrenceDays = isRecurring && recurrence === "weekly"
    ? Array.from(_qa("#recurrence-days .day-chip.active")).map(c => parseInt(c.dataset.day))
    : [];

  const payload = {
    is_recurring: isRecurring,
    recurrence_type: isRecurring ? recurrence : null,
    recurrence_days: recurrenceDays.length ? recurrenceDays : null,
  };
  console.log("[recurrence] saving", _sheetTaskId, payload);

  const indicator = _id("saved-indicator");
  if (indicator) {
    indicator.textContent = "Saving…";
    indicator.classList.remove("error");
    indicator.classList.add("show");
  }

  try {
    const res = await _post(`/projects/tasks/${_sheetTaskId}/update`, payload);
    if (!res.ok) {
      let msg = `Save failed (${res.status})`;
      try {
        const p = await res.json();
        if (p.error || p.message) msg = p.error || p.message;
      } catch {}
      throw new Error(msg);
    }
    console.log("[recurrence] saved ✓");
    // Keep the background row's data in sync
    const row = document.querySelector(`.task-row[data-id="${_sheetTaskId}"]`);
    if (row) {
      row.dataset.isRecurring = isRecurring ? "1" : "0";
      row.dataset.recurrenceType = isRecurring ? recurrence : "";
    }
    if (indicator) {
      indicator.textContent = "Saved";
      indicator.classList.remove("error");
      indicator.classList.add("show");
      clearTimeout(_saveTimer);
      _saveTimer = setTimeout(() => indicator.classList.remove("show"), 1800);
    }
  } catch (err) {
    console.error("[recurrence] _saveRecurrence failed:", err);
    if (indicator) {
      indicator.textContent = "Save failed";
      indicator.classList.add("show", "error");
    }
    showToast(err.message || "Failed to save recurrence", "error");
  }
}

/* ---------------------------------------------------------
   Pin Task (from sheet)
   --------------------------------------------------------- */
function pinTask() {
  if (!_sheetTaskId) return;

  const row = document.querySelector(`.task-row[data-id="${_sheetTaskId}"]`);
  const isPinned = row?.dataset.pinned === "1";

  _post("/projects/tasks/pin", { task_id: _sheetTaskId, is_pinned: !isPinned })
    .then(r => {
      if (!r.ok) throw new Error();
      if (row) row.dataset.pinned = isPinned ? "0" : "1";
      showToast(isPinned ? "Unpinned" : "Pinned", "success");
    })
    .catch(() => showToast("Failed to update pin", "error"));
}

/* ---------------------------------------------------------
   Eliminate Task (from sheet)
   --------------------------------------------------------- */
function eliminateTask() {
  if (!_sheetTaskId) return;
  if (!confirm("Delete this task? This cannot be undone.")) return;

  _post("/projects/tasks/eliminate", { id: _sheetTaskId })
    .then(r => {
      if (!r.ok) throw new Error();
      closeTaskSheet();
      showToast("Task deleted", "success");
      location.reload();
    })
    .catch(() => showToast("Failed to delete task", "error"));
}

/* ---------------------------------------------------------
   CSV Import
   --------------------------------------------------------- */
/* ---------------------------------------------------------
   Bulk Add + Voice
   --------------------------------------------------------- */
function toggleBulkPanel() {
  const panel = _id("bulk-panel");
  if (!panel) return;
  panel.style.display = panel.style.display === "none" ? "block" : "none";
  if (panel.style.display === "block") {
    _id("bulk-textarea")?.focus();
  }
}

async function bulkAddTasks() {
  const textarea = _id("bulk-textarea");
  const text = (textarea?.value || "").trim();
  if (!text) { showToast("Enter tasks first", "error"); return; }

  // Split by newlines, clean bullet markers
  const lines = text.split("\n")
    .map(l => l.trim().replace(/^[-•*]\s*/, "").trim())
    .filter(l => l.length > 0);

  if (!lines.length) { showToast("No valid tasks found", "error"); return; }

  try {
    const res = await fetch("/projects/tasks/bulk-add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: PROJECT_ID, tasks: lines }),
    });

    if (!res.ok) throw new Error();
    const d = await res.json();

    textarea.value = "";
    showToast(`Added ${d.count} tasks`, "success");
    setTimeout(() => location.reload(), 500);
  } catch {
    showToast("Bulk add failed", "error");
  }
}

/* ---------------------------------------------------------
   CSV Export / Import
   --------------------------------------------------------- */
function exportCSV() {
  window.location.href = `/projects/${PROJECT_ID}/export-csv`;
}

let _importRows = [];

function openImportModal() {
  _importRows = [];
  _id("import-preview").style.display = "none";
  _id("csv-file").value = "";
  _id("drop-zone")?.classList.remove("dragover");
  _id("import-modal").classList.remove("hidden");
  if (typeof feather !== "undefined") feather.replace();
}

function closeImportModal() {
  _id("import-modal").classList.add("hidden");
}

function downloadTemplate() {
  const header = "task,parent,priority,status,start_date,due_date,duration,planned_hours,notes";
  const example = [
    '"Design homepage",,high,open,2026-04-10,2026-04-15,5,8,"Main landing page"',
    '"Create mockup","Design homepage",medium,open,,,,2,"Figma mockup"',
    '"Get feedback","Design homepage",low,open,,,,1,""',
    '"Build API",,medium,open,2026-04-12,2026-04-20,8,16,"REST endpoints"',
    '"Auth endpoints","Build API",high,open,,,,4,""',
    '"Database schema","Build API",high,open,,,,3,""',
  ];
  const csv = header + "\n" + example.join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "task_import_template.csv";
  a.click();
}

function handleFileDrop(e) {
  e.preventDefault();
  _id("drop-zone")?.classList.remove("dragover");
  const file = e.dataTransfer.files[0];
  if (file) parseCSVFile(file);
}

function handleFileSelect(e) {
  const file = e.target.files[0];
  if (file) parseCSVFile(file);
}

function parseCSVFile(file) {
  if (!file.name.endsWith(".csv")) {
    showToast("Please upload a .csv file", "error");
    return;
  }

  const reader = new FileReader();
  reader.onload = function(e) {
    const text = e.target.result;
    const lines = text.split("\n").map(l => l.trim()).filter(l => l);
    if (lines.length < 2) {
      showToast("CSV file is empty or has no data rows", "error");
      return;
    }

    const headers = parseCSVLine(lines[0]).map(h => h.toLowerCase().trim());
    const taskIdx = headers.indexOf("task");
    if (taskIdx === -1) {
      showToast('CSV must have a "task" column', "error");
      return;
    }

    _importRows = [];
    for (let i = 1; i < lines.length; i++) {
      const cols = parseCSVLine(lines[i]);
      if (!cols[taskIdx]?.trim()) continue;

      const row = {};
      headers.forEach((h, idx) => {
        row[h] = (cols[idx] || "").trim();
      });
      _importRows.push(row);
    }

    showImportPreview();
  };
  reader.readAsText(file);
}

function parseCSVLine(line) {
  const result = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') { current += '"'; i++; }
      else { inQuotes = !inQuotes; }
    } else if (ch === "," && !inQuotes) {
      result.push(current);
      current = "";
    } else {
      current += ch;
    }
  }
  result.push(current);
  return result;
}

function showImportPreview() {
  const tasks = _importRows.filter(r => !r.parent);
  const subtasks = _importRows.filter(r => r.parent);

  _id("preview-stats").textContent =
    `${tasks.length} task${tasks.length !== 1 ? "s" : ""}, ${subtasks.length} subtask${subtasks.length !== 1 ? "s" : ""}`;

  let html = '<table style="width:100%;border-collapse:collapse;font-size:12px;">';
  html += '<thead><tr style="background:var(--pt-bg);">';
  html += '<th style="padding:6px 8px;text-align:left;font-weight:600;color:var(--pt-text3);">Task</th>';
  html += '<th style="padding:6px 8px;text-align:left;">Parent</th>';
  html += '<th style="padding:6px 8px;text-align:left;">Priority</th>';
  html += '<th style="padding:6px 8px;text-align:left;">Due</th>';
  html += '</tr></thead><tbody>';

  _importRows.forEach(r => {
    const isSubtask = !!r.parent;
    html += `<tr style="border-bottom:1px solid var(--pt-border-light);">
      <td style="padding:5px 8px;${isSubtask ? 'padding-left:24px;color:var(--pt-text2);' : 'font-weight:500;'}">
        ${isSubtask ? '↳ ' : ''}${_escHtml(r.task)}
      </td>
      <td style="padding:5px 8px;color:var(--pt-text3);font-size:11px;">${_escHtml(r.parent || '')}</td>
      <td style="padding:5px 8px;">${r.priority || 'medium'}</td>
      <td style="padding:5px 8px;font-size:11px;">${r.due_date || ''}</td>
    </tr>`;
  });

  html += '</tbody></table>';
  _id("preview-table").innerHTML = html;
  _id("import-preview").style.display = "block";
}

async function executeImport() {
  if (!_importRows.length) return;

  try {
    const res = await fetch("/projects/tasks/import-csv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: PROJECT_ID, rows: _importRows }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast(err.error || "Import failed", "error");
      return;
    }

    const result = await res.json();
    closeImportModal();
    showToast(`Imported ${result.tasks_created} tasks, ${result.subtasks_created} subtasks`, "success");
    setTimeout(() => location.reload(), 500);
  } catch {
    showToast("Import failed", "error");
  }
}

/* ---------------------------------------------------------
   DOMContentLoaded
   --------------------------------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
  initPrioPicker();
  initAddTask();
  initFilters();
  initSort();
  updateProjectStats();
  schedulePageReminders();

  // Close panel on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeTaskSheet();
  });

  feather.replace();
});

/* =========================================================
   BULK SELECTION MODE (Project Tasks)
   ========================================================= */

const PT_SEL = {
  active: false,
  ids: new Set(),
};

function ptEnterSelectMode(prefillId = null) {
  if (PT_SEL.active) return;
  PT_SEL.active = true;
  PT_SEL.ids.clear();
  document.body.classList.add("pt-select-mode");
  if (prefillId) ptToggleSelection(prefillId);
  ptUpdateSelCount();
  if (window.feather) feather.replace();
  if (navigator.vibrate) { try { navigator.vibrate(15); } catch {} }
  // Re-render the board so cards lose their click-to-open handlers
  if (!_id("board-view")?.classList.contains("hidden")) populateBoard();
}

function ptExitSelectMode() {
  PT_SEL.active = false;
  PT_SEL.ids.clear();
  document.body.classList.remove("pt-select-mode");
  _qa(".task-row.pt-selected").forEach(r => r.classList.remove("pt-selected"));
  _qa(".board-card.pt-selected").forEach(c => c.classList.remove("pt-selected"));
  ptCloseAllPopovers();
  // Re-render board to restore click-to-open handlers
  if (!_id("board-view")?.classList.contains("hidden")) populateBoard();
}

function ptClearSelection() {
  PT_SEL.ids.clear();
  _qa(".task-row.pt-selected").forEach(r => r.classList.remove("pt-selected"));
  _qa(".board-card.pt-selected").forEach(c => c.classList.remove("pt-selected"));
  ptUpdateSelCount();
}

function ptToggleSelection(id) {
  if (PT_SEL.ids.has(id)) {
    PT_SEL.ids.delete(id);
  } else {
    PT_SEL.ids.add(id);
  }
  // Sync the visual state in both table and board views
  const row = document.querySelector(`.task-row[data-id="${id}"]`);
  if (row) row.classList.toggle("pt-selected", PT_SEL.ids.has(id));
  const card = document.querySelector(`.board-card[data-id="${id}"]`);
  if (card) card.classList.toggle("pt-selected", PT_SEL.ids.has(id));
  ptUpdateSelCount();
}

function ptUpdateSelCount() {
  const el = _id("pt-sel-count");
  if (el) el.textContent = `${PT_SEL.ids.size} selected`;
}

function ptSelectAllVisible() {
  _qa(".task-row").forEach(row => {
    const style = getComputedStyle(row);
    if (style.display === "none") return;
    const id = row.dataset.id;
    if (!id) return;
    if (!PT_SEL.ids.has(id)) {
      PT_SEL.ids.add(id);
      row.classList.add("pt-selected");
      const card = document.querySelector(`.board-card[data-id="${id}"]`);
      if (card) card.classList.add("pt-selected");
    }
  });
  ptUpdateSelCount();
}

// ── Click handler: in select mode, taps anywhere on a row/card toggle selection ──
// Registered in capture phase on document so it fires BEFORE any onclick
// handlers on target elements (like the board card's openTaskDetail).
document.addEventListener("click", (e) => {
  if (!PT_SEL.active) return;
  const row = e.target.closest(".task-row");
  const card = e.target.closest(".board-card");
  const hit = row || card;
  if (!hit) return;
  e.preventDefault();
  e.stopPropagation();
  const id = hit.dataset.id;
  if (id) ptToggleSelection(id);
}, true);

// ── Long-press to enter select mode ──
let _ptLpTimer = null;
let _ptLpStart = null;
document.addEventListener("pointerdown", (e) => {
  if (PT_SEL.active) return;
  const hit = e.target.closest(".task-row, .board-card");
  if (!hit) return;
  // Skip long-press when pressing inside a form control
  if (e.target.closest("select, input, button, a")) return;
  _ptLpStart = { x: e.clientX, y: e.clientY, id: hit.dataset.id };
  clearTimeout(_ptLpTimer);
  _ptLpTimer = setTimeout(() => {
    _ptLpTimer = null;
    if (_ptLpStart) ptEnterSelectMode(_ptLpStart.id);
  }, 500);
});
document.addEventListener("pointermove", (e) => {
  if (!_ptLpStart || !_ptLpTimer) return;
  if (Math.abs(e.clientX - _ptLpStart.x) > 10 || Math.abs(e.clientY - _ptLpStart.y) > 10) {
    clearTimeout(_ptLpTimer); _ptLpTimer = null;
  }
});
["pointerup", "pointercancel", "pointerleave"].forEach(ev => {
  document.addEventListener(ev, () => {
    clearTimeout(_ptLpTimer); _ptLpTimer = null; _ptLpStart = null;
  });
});

// Escape exits select mode (only when nothing else higher priority is open)
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && PT_SEL.active) {
    // Don't double-handle when the task sheet is open — sheet handler runs first
    const sheet = _id("task-sheet-panel");
    if (sheet && !sheet.classList.contains("hidden")) return;
    ptExitSelectMode();
  }
});

// ── Action popovers ──
function ptCloseAllPopovers() {
  _qa(".pt-action-popover.open").forEach(p => p.classList.remove("open"));
}

function ptOpenBulkPopover(kind, anchorBtn) {
  ptCloseAllPopovers();
  if (PT_SEL.ids.size === 0) {
    showToast("Select at least one task first", "error");
    return;
  }
  const pop = _id(kind === "status" ? "pt-status-popover" : "pt-priority-popover");
  if (!pop) return;
  if (window.innerWidth > 640) {
    const rect = anchorBtn.getBoundingClientRect();
    pop.style.bottom = (window.innerHeight - rect.top + 8) + "px";
    pop.style.top = "auto";
  } else {
    pop.style.bottom = "86px";
    pop.style.top = "auto";
  }
  pop.classList.add("open");
}

// Dismiss popovers on outside click
document.addEventListener("click", (e) => {
  if (e.target.closest(".pt-action-popover") || e.target.closest(".pt-action-dock")) return;
  ptCloseAllPopovers();
});

// ── Bulk apply helpers ──
async function _ptBulkApply(patch, optimistic) {
  const ids = Array.from(PT_SEL.ids);
  if (!ids.length) return;

  // Snapshot each row's current state for rollback
  const snapshot = ids.map(id => {
    const row = document.querySelector(`.task-row[data-id="${id}"]`);
    if (!row) return null;
    return {
      id,
      row,
      status: row.dataset.status,
      priority: row.dataset.priority,
      done: row.classList.contains("done"),
    };
  }).filter(Boolean);

  // Optimistic apply
  snapshot.forEach(s => optimistic(s.row, s));

  // Keep the board view in sync with table row data changes
  if (!_id("board-view")?.classList.contains("hidden")) populateBoard();

  ptCloseAllPopovers();

  try {
    const r = await fetch("/projects/tasks/bulk-update", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content || "",
      },
      body: JSON.stringify({ ids, patch }),
    });
    const res = await r.json();
    if (res.status !== "ok") throw new Error(res.error || "Update failed");
    const n = res.updated || snapshot.length;
    // Offer Undo for destructive or closed-state bulk changes
    const isDestructive = patch && ["deleted", "skipped", "done"].includes(patch.status);
    if (isDestructive && typeof window.ptShowUndo === "function") {
      const verb = patch.status === "deleted" ? "Deleted"
                 : patch.status === "skipped" ? "Skipped"
                 : "Completed";
      ptShowUndo(`${verb} ${n} task${n === 1 ? "" : "s"}`, () => {
        // Restore to each row's prior status in one bulk call per distinct status
        const byStatus = new Map();
        snapshot.forEach(s => {
          const k = s.status || "open";
          if (!byStatus.has(k)) byStatus.set(k, []);
          byStatus.get(k).push(s);
        });
        byStatus.forEach((snaps, st) => {
          fetch("/projects/tasks/bulk-update", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content || "",
            },
            body: JSON.stringify({ ids: snaps.map(s => s.id), patch: { status: st } }),
          }).then(() => {
            snaps.forEach(s => {
              s.row.dataset.status = s.status;
              s.row.classList.toggle("done", s.done);
              const cb = _q(".task-check", s.row);
              if (cb) cb.checked = s.done;
              const sel = _q(".status-select", s.row);
              if (sel) sel.value = s.status || "open";
            });
            if (!_id("board-view")?.classList.contains("hidden")) populateBoard();
          }).catch(e => console.error("bulk undo failed:", e));
        });
      });
    } else {
      showToast(`Updated ${n} task${n === 1 ? "" : "s"}`, "success");
    }
    ptClearSelection();
  } catch (err) {
    console.error(err);
    // Roll back
    snapshot.forEach(s => {
      s.row.dataset.status = s.status;
      s.row.dataset.priority = s.priority;
      s.row.classList.toggle("done", s.done);
      // Restore the priority dot class
      const dot = _q(".prio-dot", s.row);
      if (dot) {
        dot.className = `prio-dot prio-${s.priority}`;
      }
      // Restore the status select value
      const sel = _q(".status-select", s.row);
      if (sel) sel.value = s.status;
    });
    if (!_id("board-view")?.classList.contains("hidden")) populateBoard();
    showToast("Bulk update failed — reverted", "error");
  }
}

function ptBulkApplyStatus(status) {
  const CLOSED = new Set(["done", "skipped", "deleted"]);
  const isDone = CLOSED.has(status);

  _ptBulkApply({ status }, (row, snap) => {
    row.classList.toggle("done", isDone);
    row.dataset.status = status;
    // Sync the visible status-select element inside the row
    const sel = _q(".status-select", row);
    if (sel) {
      sel.value = status;
      // Re-apply the status-* class so coloring updates
      sel.className = `status-select status-${status}`;
    }
    // Sync the native done-checkbox too (hidden in select mode but
    // visible once the user exits)
    const cb = _q(".task-check", row);
    if (cb) cb.checked = isDone;
  });
}

function ptBulkApplyPriority(priority) {
  _ptBulkApply({ priority }, (row, snap) => {
    row.dataset.priority = priority;
    const dot = _q(".prio-dot", row);
    if (dot) {
      dot.className = `prio-dot prio-${priority}`;
      dot.setAttribute("title", priority);
    }
  });
}

function ptBulkDelete() {
  // Soft delete — reversible via the status dropdown or Eisenhower resolve menu.
  // No confirmation prompt, consistent with the Eisenhower bulk delete pattern.
  ptBulkApplyStatus("deleted");
}

/* =========================================================
   GOAL / KR picker integration
   Populates every .kr-picker <select> on the page with the
   user's active goals → objectives → key results.
   ========================================================= */

let _krPickerOptionsHtml = null;
let _okrPickerData = null;   // raw {objectives: [...]} from /api/goals/picker

/* ── THE GOAL PICKER ───────────────────────────────────────────────
   "I want to attach just goals to tasks."

   /api/goals/simple returns the objectives and nothing else — the
   Objective › Key Result › Initiative labels the old picker built are
   the shape being hidden, so this does not build them. Absent when
   config.SIMPLE_GOALS is off, in which case none of this runs. */
async function loadGoalPickerOptions() {
  const sel = document.querySelectorAll(".goal-picker");
  if (!sel.length) return;
  try {
    const projectId = (typeof PROJECT_ID !== "undefined" && PROJECT_ID) ? PROJECT_ID : "";
    const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
    const res = await fetch(`/api/goals/simple${qs}`);
    const goals = (await res.json()).goals || [];
    const html = goals.length
      ? `<option value="">— No goal —</option>` + goals.map(
          g => `<option value="${g.id}">${_escHtml(g.title)}</option>`).join("")
      : `<option value="">🎯 No goals yet — add one on the Goals page</option>`;
    sel.forEach(el => {
      const keep = el.dataset.current || el.value || "";
      el.innerHTML = html;
      if (keep) el.value = keep;
    });
  } catch (err) {
    console.warn("Goal picker fetch failed:", err);
  }
}

async function loadKrPickerOptions() {
  try {
    // Scope to the current project — tasks can only link to initiatives
    // under objectives that belong to their own project. include_unassigned=1
    // also surfaces personal/ungrouped objectives so you can link a project
    // task to a cross-cutting objective (e.g. "Learning").
    const projectId = (typeof PROJECT_ID !== "undefined" && PROJECT_ID) ? PROJECT_ID : "";
    const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}&include_unassigned=1` : "";
    const res = await fetch(`/api/goals/picker${qs}`);
    if (!res.ok) throw new Error();
    const data = await res.json();
    _okrPickerData = data;
    const objectives = data.objectives || [];

    // Build Objective › KR › Initiative option groups. Tasks link to
    // initiatives (the innermost grouping); the objective + KR context
    // is shown in the label so users can navigate visually.
    if (!objectives.length) {
      _krPickerOptionsHtml = `<option value="">🎯 No initiative (define one on the OKRs page)</option>`;
    } else {
      let html = `<option value="">— Not linked —</option>`;
      let anyInitiative = false;
      for (const o of objectives) {
        for (const kr of (o.key_results || [])) {
          for (const init of (kr.initiatives || [])) {
            const label = `${o.title} › ${kr.title} › ${init.title}`;
            html += `<option value="${init.id}">${_escHtml(label)}</option>`;
            anyInitiative = true;
          }
        }
      }
      if (!anyInitiative) {
        _krPickerOptionsHtml =
          `<option value="">🎯 No initiative yet — add one on the OKRs page under a Key Result</option>`;
      } else {
        _krPickerOptionsHtml = html;
      }
    }
    // Paint all existing pickers
    document.querySelectorAll(".kr-picker").forEach(paintKrPicker);
    // Populate the OKR filter dropdowns now that data is ready
    populateOkrFilters();
  } catch (err) {
    console.warn("Initiative picker fetch failed:", err);
  }
}

/* ---------------------------------------------------------
   OKR filter — multi-select bottom sheet
   State holds Sets of selected ids per dimension; tasks pass
   the filter iff their parent ids intersect each non-empty set.
   --------------------------------------------------------- */
const _ptFilter = {
  objectiveIds:  new Set(),
  krIds:         new Set(),
  initiativeIds: new Set(),
};

function populateOkrFilters() {
  // Kept for backward compatibility. The filter now lives in the sheet.
  renderPtFilterSheet();
  applyOkrFilter();
}

function _ptLabelFor(kind, id) {
  const objs = _okrPickerData?.objectives || [];
  if (kind === "objective") return objs.find(o => o.id === id)?.title;
  if (kind === "kr") {
    for (const o of objs) {
      const k = (o.key_results || []).find(k => k.id === id);
      if (k) return k.title;
    }
  }
  if (kind === "initiative") {
    for (const o of objs) for (const k of (o.key_results || [])) {
      const i = (k.initiatives || []).find(i => i.id === id);
      if (i) return i.title;
    }
  }
  return null;
}

function _ptActiveCount() {
  return _ptFilter.objectiveIds.size
       + _ptFilter.krIds.size
       + _ptFilter.initiativeIds.size;
}

function renderPtFilterSheet() {
  if (!_okrPickerData) return;
  const objectives = _okrPickerData.objectives || [];

  const objWrap  = _id("pt-fs-objectives");
  const krWrap   = _id("pt-fs-krs");
  const initWrap = _id("pt-fs-initiatives");
  if (!objWrap || !krWrap || !initWrap) return;

  // ── Objectives (always the full list) ──
  if (!objectives.length) {
    objWrap.innerHTML = `<div class="pt-fs-empty">No objectives yet. Create one on the OKRs page.</div>`;
  } else {
    objWrap.innerHTML = objectives.map(o => {
      const count = (o.key_results || []).reduce(
        (n, k) => n + (k.initiatives || []).length, 0
      );
      const sel = _ptFilter.objectiveIds.has(o.id) ? " selected" : "";
      return `<button type="button" class="pt-fs-chip${sel}"
                      data-kind="objective" data-id="${o.id}">
        <span class="pt-fs-chip-check" aria-hidden="true"></span>
        <span class="pt-fs-chip-text">${_escHtml(o.title)}</span>
        ${count ? `<span class="pt-fs-chip-meta">${count}</span>` : ""}
      </button>`;
    }).join("");
  }
  _updatePtSectionHint("pt-fs-obj-count", _ptFilter.objectiveIds.size, objectives.length);

  // ── Key Results (scoped to selected objectives, or all) ──
  const scopedObjs = _ptFilter.objectiveIds.size
    ? objectives.filter(o => _ptFilter.objectiveIds.has(o.id))
    : objectives;
  const krs = scopedObjs.flatMap(o => (o.key_results || []).map(k => ({
    ...k, _objTitle: o.title
  })));

  if (!krs.length) {
    krWrap.innerHTML = `<div class="pt-fs-empty">${_ptFilter.objectiveIds.size
      ? "Selected objectives have no key results."
      : "No key results yet."}</div>`;
  } else {
    krWrap.innerHTML = krs.map(k => {
      const sel = _ptFilter.krIds.has(k.id) ? " selected" : "";
      const count = (k.initiatives || []).length;
      return `<button type="button" class="pt-fs-chip${sel}"
                      data-kind="kr" data-id="${k.id}"
                      title="${_escHtml(k._objTitle)} › ${_escHtml(k.title)}">
        <span class="pt-fs-chip-check" aria-hidden="true"></span>
        <span class="pt-fs-chip-text">${_escHtml(k.title)}</span>
        ${count ? `<span class="pt-fs-chip-meta">${count}</span>` : ""}
      </button>`;
    }).join("");
  }
  _updatePtSectionHint("pt-fs-kr-count", _ptFilter.krIds.size, krs.length);

  // ── Initiatives (scoped to selected KRs, or all in-scope) ──
  const scopedKrs = _ptFilter.krIds.size
    ? krs.filter(k => _ptFilter.krIds.has(k.id))
    : krs;
  const inits = scopedKrs.flatMap(k => (k.initiatives || []).map(i => ({
    ...i, _krTitle: k.title
  })));

  if (!inits.length) {
    initWrap.innerHTML = `<div class="pt-fs-empty">${_ptFilter.krIds.size
      ? "Selected key results have no initiatives."
      : "No initiatives in scope."}</div>`;
  } else {
    initWrap.innerHTML = inits.map(i => {
      const sel = _ptFilter.initiativeIds.has(i.id) ? " selected" : "";
      return `<button type="button" class="pt-fs-chip${sel}"
                      data-kind="initiative" data-id="${i.id}"
                      title="${_escHtml(i._krTitle)} › ${_escHtml(i.title)}">
        <span class="pt-fs-chip-check" aria-hidden="true"></span>
        <span class="pt-fs-chip-text">${_escHtml(i.title)}</span>
      </button>`;
    }).join("");
  }
  _updatePtSectionHint("pt-fs-init-count", _ptFilter.initiativeIds.size, inits.length);

  // Footer apply label
  const n = _ptActiveCount();
  const lbl = _id("pt-fs-apply-label");
  if (lbl) lbl.textContent = n ? `Apply ${n} filter${n > 1 ? "s" : ""}` : "Show all tasks";
}

function _updatePtSectionHint(hintId, selected, total) {
  const el = _id(hintId);
  if (!el) return;
  if (selected > 0) {
    el.textContent = `${selected} of ${total} selected`;
    el.classList.add("active");
  } else {
    el.textContent = `${total} available`;
    el.classList.remove("active");
  }
}

// Chip click handler — delegated on document
document.addEventListener("click", (ev) => {
  const chip = ev.target.closest(".pt-fs-chip");
  if (!chip) return;
  const kind = chip.dataset.kind;
  const id = chip.dataset.id;
  const set = kind === "objective"  ? _ptFilter.objectiveIds
            : kind === "kr"         ? _ptFilter.krIds
            : kind === "initiative" ? _ptFilter.initiativeIds
            : null;
  if (!set) return;

  if (set.has(id)) set.delete(id);
  else             set.add(id);

  // Cascade cleanup: if an objective is deselected, drop any KRs/initiatives
  // that no longer have a live parent in scope. (Applies only if the user
  // has narrowed at that level.)
  if (kind === "objective") _ptCleanupDownstream();
  if (kind === "kr")        _ptCleanupInitiatives();

  renderPtFilterSheet();
  applyOkrFilter();
});

function _ptCleanupDownstream() {
  if (!_okrPickerData) return;
  const objectives = _okrPickerData.objectives || [];
  const liveObjSet = _ptFilter.objectiveIds;
  if (!liveObjSet.size) return;  // no scope → nothing to clean

  const liveKrIds = new Set(
    objectives
      .filter(o => liveObjSet.has(o.id))
      .flatMap(o => (o.key_results || []).map(k => k.id))
  );
  // Remove any selected KR that is no longer in scope
  for (const krId of Array.from(_ptFilter.krIds)) {
    if (!liveKrIds.has(krId)) _ptFilter.krIds.delete(krId);
  }
  _ptCleanupInitiatives();
}

function _ptCleanupInitiatives() {
  if (!_okrPickerData) return;
  const objectives = _okrPickerData.objectives || [];
  const liveObjSet = _ptFilter.objectiveIds;
  const liveKrSet  = _ptFilter.krIds;

  // Build the set of initiative ids that are currently in scope
  const scopedObjs = liveObjSet.size
    ? objectives.filter(o => liveObjSet.has(o.id))
    : objectives;
  const scopedKrs = scopedObjs.flatMap(o => o.key_results || []);
  const filteredKrs = liveKrSet.size
    ? scopedKrs.filter(k => liveKrSet.has(k.id))
    : scopedKrs;
  const liveInitIds = new Set(
    filteredKrs.flatMap(k => (k.initiatives || []).map(i => i.id))
  );

  for (const initId of Array.from(_ptFilter.initiativeIds)) {
    if (!liveInitIds.has(initId)) _ptFilter.initiativeIds.delete(initId);
  }
}

function applyOkrFilter() {
  const { objectiveIds, krIds, initiativeIds } = _ptFilter;
  const active = _ptActiveCount() > 0;

  document.querySelectorAll(".task-row").forEach(row => {
    let show = true;
    if (active) {
      // Tasks with no OKR linkage at all are hidden as soon as any filter is active
      const hasAny = row.dataset.objectiveId || row.dataset.krId || row.dataset.initiativeId;
      if (!hasAny) {
        show = false;
      } else {
        if (objectiveIds.size  && !objectiveIds.has(row.dataset.objectiveId))   show = false;
        if (show && krIds.size && !krIds.has(row.dataset.krId))                 show = false;
        if (show && initiativeIds.size && !initiativeIds.has(row.dataset.initiativeId)) show = false;
      }
    }
    row.classList.toggle("okr-hidden", !show);
  });

  // Hide group headers whose tasks are all filtered out
  document.querySelectorAll(".group-row").forEach(gr => {
    const group = gr.dataset.group;
    const anyVisible = !!document.querySelector(
      `.task-row[data-group="${group}"]:not(.okr-hidden)`
    );
    gr.classList.toggle("okr-hidden", !anyVisible);
  });

  // Filter button badge
  const btn = _id("pt-filter-btn");
  const badge = _id("pt-filter-badge");
  const n = _ptActiveCount();
  if (btn) btn.classList.toggle("has-filters", n > 0);
  if (badge) {
    if (n > 0) { badge.textContent = n; badge.style.display = ""; }
    else { badge.style.display = "none"; }
  }

  renderPtFilterChips();

  // Refresh kanban view if it's currently showing
  if (typeof populateBoard === "function" &&
      !_id("board-view")?.classList.contains("hidden")) {
    populateBoard();
  }
}

function renderPtFilterChips() {
  const bar = _id("pt-filter-chips");
  if (!bar) return;
  if (_ptActiveCount() === 0) {
    bar.style.display = "none";
    bar.innerHTML = "";
    return;
  }

  const chips = [];
  for (const id of _ptFilter.objectiveIds) {
    chips.push({ kind: "objective", label: "Objective",
                 text: _ptLabelFor("objective", id) || "—", id });
  }
  for (const id of _ptFilter.krIds) {
    chips.push({ kind: "kr", label: "Key Result",
                 text: _ptLabelFor("kr", id) || "—", id });
  }
  for (const id of _ptFilter.initiativeIds) {
    chips.push({ kind: "initiative", label: "Initiative",
                 text: _ptLabelFor("initiative", id) || "—", id });
  }

  bar.innerHTML = chips.map(c => `
    <span class="pt-chip">
      <span class="pt-chip-label">${c.label}</span>
      <span class="pt-chip-text" title="${_escHtml(c.text)}">${_escHtml(c.text)}</span>
      <button type="button" onclick="removePtFilterChip('${c.kind}','${c.id}')" aria-label="Remove">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="3" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
      </button>
    </span>
  `).join("") + `<button type="button" class="pt-chip-clear-all" onclick="clearOkrFilter()">Clear all</button>`;
  bar.style.display = "flex";
}

function removePtFilterChip(kind, id) {
  const set = kind === "objective"  ? _ptFilter.objectiveIds
            : kind === "kr"         ? _ptFilter.krIds
            : kind === "initiative" ? _ptFilter.initiativeIds
            : null;
  if (!set) return;
  set.delete(id);
  if (kind === "objective") _ptCleanupDownstream();
  if (kind === "kr")        _ptCleanupInitiatives();
  renderPtFilterSheet();
  applyOkrFilter();
}

function clearOkrFilter() {
  _ptFilter.objectiveIds.clear();
  _ptFilter.krIds.clear();
  _ptFilter.initiativeIds.clear();
  renderPtFilterSheet();
  applyOkrFilter();
}

function openPtFilterSheet() {
  const sheet = _id("pt-filter-sheet");
  const overlay = _id("pt-filter-overlay");
  if (!sheet || !overlay) return;
  renderPtFilterSheet();
  sheet.classList.add("open");
  overlay.classList.add("open");
  document.body.style.overflow = "hidden";
}

function closePtFilterSheet() {
  const sheet = _id("pt-filter-sheet");
  const overlay = _id("pt-filter-overlay");
  sheet?.classList.remove("open");
  overlay?.classList.remove("open");
  document.body.style.overflow = "";
}

// Close sheet on Escape
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const sheet = _id("pt-filter-sheet");
    if (sheet?.classList.contains("open")) closePtFilterSheet();
  }
});

function paintKrPicker(selectEl) {
  if (!_krPickerOptionsHtml) return;
  const currentValue = selectEl.dataset.current || selectEl.value || "";
  selectEl.innerHTML = _krPickerOptionsHtml;
  if (currentValue) selectEl.value = currentValue;
}

// Inline card initiative picker — called from _project_task_card.html onchange
function updateTaskInitiative(taskId, initiativeId, el) {
  const fb = el?.parentElement?.querySelector(".field-fb");
  _post(`/projects/tasks/${taskId}/update`, { initiative_id: initiativeId || null })
    .then(() => {
      if (fb) { fb.textContent = "✓ saved"; setTimeout(() => fb.textContent = "", 1500); }
      if (el) el.dataset.current = initiativeId || "";
    })
    .catch(() => {
      if (fb) fb.textContent = "save failed";
    });
}

// Hook picker population into openTaskDetail flow:
// ensure the sheet's dropdown is painted AND preselected whenever the sheet opens.
(function hookSheetKrPicker() {
  const origOpen = typeof openTaskDetail === "function" ? openTaskDetail : null;
  if (!origOpen) return;
  window.openTaskDetail = async function (taskId) {
    await origOpen(taskId);
    try {
      const res = await fetch(`/api/v2/project-tasks/${taskId}`);
      if (!res.ok) return;
      const t = await res.json();
      const sel = _id("sheet-key-result");
      if (sel) {
        if (!_krPickerOptionsHtml) await loadKrPickerOptions();
        sel.innerHTML = _krPickerOptionsHtml || `<option value="">🎯 No initiative</option>`;
        sel.value = t.initiative_id || "";
      }
    } catch {}
  };
})();

// Initial load once the DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  loadKrPickerOptions();
  loadGoalPickerOptions();
});

/* ═══════════════════════════════════════════════════════════
   OKR MANAGER — create Objectives / Key Results / Initiatives
   scoped to the current project, without leaving this page.
   Uses the existing /api/goals, /api/key-results, /api/initiatives
   endpoints plus the picker API for the live tree.
   ═══════════════════════════════════════════════════════════ */

// Current form target — holds what we're creating and its parent id
let _ptOkrFormMode = null; // "objective" | "kr" | "initiative"
let _ptOkrFormParent = null; // parent id (objective id for kr, kr id for initiative)

async function openPtOkrManager() {
  const sheet = _id("pt-okr-sheet");
  const overlay = _id("pt-okr-overlay");
  if (!sheet || !overlay) return;
  sheet.classList.add("open");
  overlay.classList.add("open");
  document.body.style.overflow = "hidden";
  await renderPtOkrTree();
  if (window.feather) feather.replace();
}

function closePtOkrManager() {
  _id("pt-okr-sheet")?.classList.remove("open");
  _id("pt-okr-overlay")?.classList.remove("open");
  document.body.style.overflow = "";
}

async function renderPtOkrTree() {
  const host = _id("pt-okr-tree");
  if (!host) return;
  host.innerHTML = `<div class="pt-okr-loading">Loading…</div>`;

  try {
    // Fetch fresh OKR tree scoped to this project (include unassigned too
    // so a personal objective the user might want to scope here is visible).
    const qs = new URLSearchParams({
      project_id: PROJECT_ID,
      include_unassigned: "0",
    });
    const res = await fetch(`/api/goals/picker?${qs.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    // Keep the PT-level cache in sync so the filter sheet reflects new OKRs
    _okrPickerData = data;
    populateOkrFilters();

    const objs = data.objectives || [];
    if (!objs.length) {
      host.innerHTML = `
        <div class="pt-okr-empty">
          <i data-feather="target"></i>
          <h4>No objectives yet</h4>
          <p>Create your first objective to start grouping tasks into measurable outcomes.</p>
          <button type="button" class="pt-fs-btn pt-fs-btn-primary" onclick="openPtNewObjectiveForm()">
            <i data-feather="plus" style="width:16px;height:16px"></i> New Objective
          </button>
        </div>`;
      if (window.feather) feather.replace();
      return;
    }

    host.innerHTML = objs.map(o => _ptRenderObjective(o)).join("");
    if (window.feather) feather.replace();
  } catch (err) {
    console.error("OKR tree load failed:", err);
    host.innerHTML = `<div class="pt-okr-empty"><p>Failed to load OKRs: ${err.message}</p></div>`;
  }
}

function _ptRenderObjective(o) {
  const krs = (o.key_results || []).map(k => _ptRenderKr(k)).join("");
  const krListOrEmpty = krs
    || `<div class="pt-okr-kr" style="background:transparent;border:1px dashed var(--pt-border);text-align:center;color:var(--pt-text3);font-size:12px;">No key results yet</div>`;
  return `
    <div class="pt-okr-obj">
      <div class="pt-okr-obj-head">
        <div style="flex:1;min-width:0;">
          <div class="pt-okr-obj-title">${_escHtml(o.title)}</div>
          ${o.category ? `<div class="pt-okr-obj-desc">${_escHtml(o.category)}${o.target_date ? " · target " + _escHtml(o.target_date) : ""}</div>` : ""}
        </div>
      </div>
      <div class="pt-okr-kr-list">
        ${krListOrEmpty}
      </div>
      <button type="button" class="pt-okr-add-inline" onclick="openPtNewKrForm('${o.id}')">
        <i data-feather="plus"></i> Add Key Result
      </button>
    </div>
  `;
}

function _ptRenderKr(k) {
  const inits = (k.initiatives || []).map(i =>
    `<span class="pt-okr-init">${_escHtml(i.title)}</span>`
  ).join("");
  const progress = (k.current_value != null && k.target_value)
    ? `${k.current_value} / ${k.target_value}${k.unit ? " " + _escHtml(k.unit) : ""}`
    : "";
  return `
    <div class="pt-okr-kr">
      <div class="pt-okr-kr-head">
        <div style="flex:1;min-width:0;">
          <div class="pt-okr-kr-title">${_escHtml(k.title)}</div>
          ${progress ? `<div class="pt-okr-kr-meta">${progress}</div>` : ""}
        </div>
      </div>
      ${inits ? `<div class="pt-okr-init-list">${inits}</div>` : ""}
      <button type="button" class="pt-okr-add-inline" onclick="openPtNewInitiativeForm('${k.id}')">
        <i data-feather="plus"></i> Add Initiative
      </button>
    </div>
  `;
}

// ── Form modal: shared shell used for Objective, KR, Initiative ──
function _ptOpenOkrForm(mode, parentId) {
  _ptOkrFormMode = mode;
  _ptOkrFormParent = parentId;

  const titleEl = _id("pt-okr-form-title");
  const bodyEl = _id("pt-okr-form-body");
  const submitLbl = _id("pt-okr-form-submit");
  if (!titleEl || !bodyEl || !submitLbl) return;

  if (mode === "objective") {
    titleEl.textContent = "New Objective";
    submitLbl.textContent = "Create Objective";
    bodyEl.innerHTML = `
      <div class="pt-okr-field">
        <label>Title <span class="req">*</span></label>
        <input type="text" id="pt-f-title" maxlength="200"
               placeholder="e.g. Launch v2 with premium experience" autofocus>
      </div>
      <div class="pt-okr-field">
        <label>Description</label>
        <textarea id="pt-f-desc" rows="2"
                  placeholder="Optional — what does success look like?"></textarea>
      </div>
      <div class="pt-okr-row">
        <div class="pt-okr-field">
          <label>Category</label>
          <input type="text" id="pt-f-category"
                 placeholder="product, growth, quality…">
        </div>
        <div class="pt-okr-field">
          <label>Time horizon</label>
          <select id="pt-f-horizon">
            <option value="annual">Annual</option>
            <option value="quarterly" selected>Quarterly</option>
            <option value="monthly">Monthly</option>
            <option value="ongoing">Ongoing</option>
          </select>
        </div>
      </div>
      <div class="pt-okr-field">
        <label>Target date</label>
        <input type="date" id="pt-f-target">
      </div>
    `;
  } else if (mode === "kr") {
    titleEl.textContent = "New Key Result";
    submitLbl.textContent = "Create Key Result";
    bodyEl.innerHTML = `
      <div class="pt-okr-field">
        <label>Title <span class="req">*</span></label>
        <input type="text" id="pt-f-title" maxlength="200"
               placeholder="e.g. Save $5,000" autofocus>
      </div>
      <div class="pt-okr-row">
        <div class="pt-okr-field">
          <label>Start value</label>
          <input type="number" id="pt-f-start" step="any" value="0">
        </div>
        <div class="pt-okr-field">
          <label>Target <span class="req">*</span></label>
          <input type="number" id="pt-f-target-val" step="any" placeholder="5000">
        </div>
      </div>
      <div class="pt-okr-row">
        <div class="pt-okr-field">
          <label>Unit</label>
          <input type="text" id="pt-f-unit" maxlength="16"
                 placeholder="$, books, kg, %…">
        </div>
        <div class="pt-okr-field">
          <label>Direction</label>
          <select id="pt-f-direction">
            <option value="up" selected>Higher is better ▲</option>
            <option value="down">Lower is better ▼</option>
          </select>
        </div>
      </div>
    `;
  } else if (mode === "initiative") {
    titleEl.textContent = "New Initiative";
    submitLbl.textContent = "Create Initiative";
    bodyEl.innerHTML = `
      <div class="pt-okr-field">
        <label>Title <span class="req">*</span></label>
        <input type="text" id="pt-f-title" maxlength="200"
               placeholder="e.g. Onboarding flow redesign" autofocus>
      </div>
      <div class="pt-okr-field">
        <label>Description</label>
        <textarea id="pt-f-desc" rows="2"
                  placeholder="Optional — the workstream's approach"></textarea>
      </div>
    `;
  }

  _id("pt-okr-form-sheet")?.classList.add("open");
  _id("pt-okr-form-overlay")?.classList.add("open");
  document.body.style.overflow = "hidden";
  setTimeout(() => _id("pt-f-title")?.focus(), 60);
}

function openPtNewObjectiveForm() { _ptOpenOkrForm("objective", null); }
function openPtNewKrForm(objId)  { _ptOpenOkrForm("kr", objId); }
function openPtNewInitiativeForm(krId) { _ptOpenOkrForm("initiative", krId); }

function closePtOkrForm() {
  _id("pt-okr-form-sheet")?.classList.remove("open");
  _id("pt-okr-form-overlay")?.classList.remove("open");
  // Keep overflow:hidden if the main OKR manager is still open
  if (!_id("pt-okr-sheet")?.classList.contains("open")) {
    document.body.style.overflow = "";
  }
  _ptOkrFormMode = null;
  _ptOkrFormParent = null;
}

async function submitPtOkrForm() {
  const mode = _ptOkrFormMode;
  if (!mode) return;

  const csrfHeader = {
    "Content-Type": "application/json",
    "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content || "",
  };

  try {
    if (mode === "objective") {
      const title = _id("pt-f-title")?.value.trim();
      if (!title) { showToast && showToast("Title is required", "error"); return; }
      const payload = {
        title,
        description: _id("pt-f-desc")?.value.trim() || null,
        category: _id("pt-f-category")?.value.trim() || null,
        time_horizon: _id("pt-f-horizon")?.value || "quarterly",
        target_date: _id("pt-f-target")?.value || null,
        project_id: PROJECT_ID,
      };
      const res = await fetch("/api/goals", {
        method: "POST", headers: csrfHeader, body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`);
      _toast("Objective created", "success");

    } else if (mode === "kr") {
      const title = _id("pt-f-title")?.value.trim();
      const target = _id("pt-f-target-val")?.value;
      if (!title) { _toast("Title is required", "error"); return; }
      if (target === "" || target == null) { _toast("Target value is required", "error"); return; }
      const payload = {
        title,
        objective_id: _ptOkrFormParent,
        start_value: parseFloat(_id("pt-f-start")?.value || 0),
        target_value: parseFloat(target),
        unit: _id("pt-f-unit")?.value.trim() || null,
        direction: _id("pt-f-direction")?.value || "up",
      };
      const res = await fetch("/api/key-results", {
        method: "POST", headers: csrfHeader, body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`);
      _toast("Key result created", "success");

    } else if (mode === "initiative") {
      const title = _id("pt-f-title")?.value.trim();
      if (!title) { _toast("Title is required", "error"); return; }
      const payload = {
        title,
        description: _id("pt-f-desc")?.value.trim() || null,
        key_result_id: _ptOkrFormParent,
      };
      const res = await fetch("/api/initiatives", {
        method: "POST", headers: csrfHeader, body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`);
      _toast("Initiative created", "success");
    }

    closePtOkrForm();
    await renderPtOkrTree();     // refresh the tree
    await loadKrPickerOptions(); // refresh the task sheet's initiative picker
  } catch (err) {
    console.error("OKR form submit:", err);
    _toast("Failed to create: " + err.message, "error");
  }
}

function _toast(msg, kind) {
  if (typeof showToast === "function") return showToast(msg, kind);
  console.log(`[${kind}]`, msg);
}

// Escape-to-close for the manager and form
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const form = _id("pt-okr-form-sheet");
  if (form?.classList.contains("open")) { closePtOkrForm(); return; }
  const sheet = _id("pt-okr-sheet");
  if (sheet?.classList.contains("open")) { closePtOkrManager(); }
});

/* ═══════════════════════════════════════════════════════════════
   BATCH-A WIRING (2026-04): page-specific keyboard shortcuts,
   swipe-delete fallback, ptNewTask override, natural-language
   quick-add, saved-indicator hooks.
   ═══════════════════════════════════════════════════════════════ */

// ── ptNewTask: focus the quick-add input on this page ───────────
window.ptNewTask = function () {
  const input = _id("add-task-input");
  if (input) { input.focus(); input.scrollIntoView({ block: "center", behavior: "smooth" }); }
};

// ── Keyboard shortcuts scoped to this page ─────────────────────
document.addEventListener("DOMContentLoaded", () => {
  if (typeof ptRegisterShortcut !== "function") return;

  ptRegisterShortcut("/", () => {
    _id("add-task-input")?.focus();
  }, "Focus quick-add");

  ptRegisterShortcut("e", () => {
    const row = document.querySelector(".task-row:hover, .task-row.pt-kb-active") ||
                document.querySelector(".task-row");
    if (row?.dataset?.id) openTaskDetail(row.dataset.id);
  }, "Open task details");

  ptRegisterShortcut("x", () => {
    const row = document.querySelector(".task-row.pt-kb-active") ||
                document.querySelector(".task-row:hover");
    const cb = row?.querySelector('input[type="checkbox"].task-check');
    if (cb) {
      cb.checked = !cb.checked;
      cb.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }, "Toggle done on focused row");

  ptRegisterShortcut("j", () => _ptKbMoveRow(+1), "Next row");
  ptRegisterShortcut("k", () => _ptKbMoveRow(-1), "Previous row");

  ptRegisterShortcut("Escape", () => closeTaskSheet?.(), "Close panel");
});

function _ptKbMoveRow(delta) {
  const rows = _qa(".task-row");
  if (!rows.length) return;
  const curIdx = rows.findIndex(r => r.classList.contains("pt-kb-active"));
  const nextIdx = Math.max(0, Math.min(rows.length - 1, (curIdx < 0 ? 0 : curIdx + delta)));
  rows.forEach(r => r.classList.remove("pt-kb-active"));
  rows[nextIdx].classList.add("pt-kb-active");
  rows[nextIdx].scrollIntoView({ block: "nearest" });
}

// ── Swipe-delete → soft-delete with undo ───────────────────────
document.addEventListener("pt-swipe-delete", (e) => {
  const id = e.detail?.id;
  const row = id ? document.querySelector(`.task-row[data-id="${id}"]`) : null;
  if (!row) return;
  const prevStatus = row.dataset.status || "open";
  row.dataset.status = "deleted";
  row.classList.add("done");
  row.style.transition = "opacity .3s";
  row.style.opacity = "0";
  fetch("/projects/tasks/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: id, status: "deleted" }),
  }).then(() => {
    updateProjectStats?.();
    if (typeof ptShowUndo === "function") {
      ptShowUndo("Task deleted", () => {
        row.dataset.status = prevStatus;
        row.classList.remove("done");
        row.style.opacity = "";
        fetch("/projects/tasks/status", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task_id: id, status: prevStatus }),
        });
      });
    }
  });
});

// ── Natural-language parse on Enter in quick-add ───────────────
// Uses parseTaskLine from voice.js (shared parser). Pre-fills the
// visible priority/date pickers from parsed tokens, so users see
// what the app interpreted.
document.addEventListener("DOMContentLoaded", () => {
  const input = _id("add-task-input");
  if (!input) return;
  input.addEventListener("input", () => {
    if (typeof parseTaskLine !== "function") return;
    const parsed = parseTaskLine(input.value, new Date().toISOString().slice(0, 10));
    if (parsed.due_date) {
      const dateInput = _id("add-task-date");
      if (dateInput) dateInput.value = parsed.due_date;
    }
    if (parsed.quadrant === "do") _setAddPriority("high");
  });
});

function _setAddPriority(p) {
  const picker = _id("prio-picker");
  if (!picker) return;
  _qa(".pp-btn", picker).forEach(b => b.classList.toggle("active", b.dataset.p === p));
  _addPriority = p;
}

// ── Saved indicator hook in autoSaveField ──────────────────────
// Wrap the existing autoSaveField to ping the global saved indicator.
(function wrapAutoSave() {
  if (typeof autoSaveField !== "function") return;
  const orig = autoSaveField;
  window.autoSaveField = async function (field, value) {
    if (window.ptSavePing) ptSavePing("saving");
    try {
      const ret = await orig.apply(this, arguments);
      if (window.ptSavePing) ptSavePing("saved");
      return ret;
    } catch (e) {
      if (window.ptSavePing) ptSavePing("error");
      throw e;
    }
  };
})();

// ── Escape audit — ensure every modal on this page closes on Esc ──
// Centralized so we don't sprinkle listeners throughout the file.
// LIFO-ish: the topmost/most recently opened is handled first.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;

  // 1. Import modal
  const importModal = _id("pt-import-modal") || _id("import-modal");
  if (importModal && !importModal.classList.contains("hidden") && importModal.style.display !== "none") {
    if (typeof closeImportModal === "function") { closeImportModal(); e.stopPropagation(); return; }
  }
  // 2. OKR form sheet (managed by its own handler at bottom of file; kept as fallback)
  const okrForm = _id("pt-okr-form-sheet");
  if (okrForm?.classList.contains("open")) {
    if (typeof closePtOkrForm === "function") { closePtOkrForm(); e.stopPropagation(); return; }
  }
  // 3. OKR manager sheet
  const okrMgr = _id("pt-okr-sheet");
  if (okrMgr?.classList.contains("open")) {
    if (typeof closePtOkrManager === "function") { closePtOkrManager(); e.stopPropagation(); return; }
  }
  // 4. Bulk popovers
  if (document.querySelector(".pt-action-popover.open")) {
    if (typeof ptCloseAllPopovers === "function") { ptCloseAllPopovers(); e.stopPropagation(); return; }
  }
  // 5. Select mode
  if (window.PT_SEL && PT_SEL.active) {
    if (typeof ptExitSelectMode === "function") { ptExitSelectMode(); e.stopPropagation(); return; }
  }
  // 6. Task detail panel (only if nothing else was open)
  const panel = _id("task-panel");
  if (panel && !panel.classList.contains("hidden")) {
    if (typeof closeTaskSheet === "function") { closeTaskSheet(); }
  }
});


/* Links in a task's notes, listed as tappable rows at the top of the sheet.
   The label is the text before the link on the same line ("Card: …" gives
   "Card"), else the line above it (a design's name), else the path. App
   links open in this tab; other sites in a new one. DOM nodes only, never
   innerHTML, so notes cannot inject markup. */
function renderSheetLinks(notes) {
  const box = document.getElementById("sheet-links");
  if (!box) return;
  box.textContent = "";
  const lines = String(notes || "").split("\n");
  const seen = new Set();
  let count = 0;
  lines.forEach((line, i) => {
    const re = /https?:\/\/[^\s)<>"']+/g;
    let m;
    while ((m = re.exec(line))) {
      const url = m[0].replace(/[.,;:]+$/, "");
      if (seen.has(url)) continue;
      seen.add(url);
      let before = line.slice(0, m.index).replace(/[:\-–(]+\s*$/, "").replace(/^\s*\d+\.\s*/, "").trim();
      // Nearest line above with no link: the heading these links belong to.
      let head = "";
      for (let k = i - 1; k >= 0; k--) {
        const L = lines[k].trim();
        if (!L) break;
        if (!/https?:\/\//.test(L)) { head = L.replace(/^[-\s]+/, "").replace(/:$/, ""); break; }
      }
      if (!before || before.length < 3) before = head;
      else if (before.length <= 12 && head && /^\s/.test(line)) before = head + " · " + before;
      const a = document.createElement("a");
      let href = url, path = url, external = true;
      try {
        const u = new URL(url);
        if (u.host === location.host || /dailyplanner-[a-z0-9]+\.onrender\.com$/.test(u.host)) {
          href = u.pathname + u.search; external = false;
        }
        path = u.pathname.replace(/^\/interview-prep\//, "").replace(/\/$/, "") || u.host;
        if (/\.pdf$|\/pdf$/.test(u.pathname)) path += " (PDF)";
      } catch (e) { /* keep raw */ }
      a.href = href;
      if (external) { a.target = "_blank"; a.rel = "noopener"; }
      a.textContent = (before ? before + " " : "") + "→ ";
      const s = document.createElement("span");
      s.textContent = path;
      a.appendChild(s);
      if (!count) {
        const h = document.createElement("b");
        h.textContent = "Open";
        box.appendChild(h);
      }
      box.appendChild(a);
      count++;
    }
  });
  box.hidden = count === 0;
}
