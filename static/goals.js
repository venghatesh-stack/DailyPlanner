/* ═══════════════════════════════════════════════════════════════
   OKRs PAGE  (Project → Objective → Key Result → Initiative → Task)
   ═══════════════════════════════════════════════════════════════ */

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[c]));

const state = {
  objectives: [],
  projects: [],                 // [[id, name], ...]
  editingObjectiveId: null,     // null = creating new
  editingKrId: null,
  editingInitiativeId: null,
  pendingKrObjectiveId: null,
  pendingInitiativeKrId: null,
  selectedColor: "#2563eb",
};

function csrfHeader() {
  return { "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content || "" };
}

// Route mutating requests through dpFetch so they queue offline.
const _fetch = (window.dpFetch) || ((u, o) => fetch(u, o));
async function api(method, path, body) {
  const res = await _fetch(path, {
    method,
    headers: { "Content-Type": "application/json", ...csrfHeader() },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || "Request failed");
  if (res._queued) data.queued = true;
  return data;
}

// ═══════════════════════════════════════════════════════════════
// LOAD + RENDER
// ═══════════════════════════════════════════════════════════════

async function loadGoals() {
  const includeArchived = $("include-archived")?.checked ? "1" : "0";
  const projectId = $("project-filter")?.value || "";
  const qs = new URLSearchParams({ include_archived: includeArchived });
  if (projectId) {
    qs.set("project_id", projectId);
    qs.set("include_unassigned", "0");
  }
  try {
    const data = await api("GET", `/api/goals?${qs.toString()}`);
    state.objectives = data.objectives || [];
    state.projects = data.projects || [];
    populateProjectSelectors();
    renderObjectives();
    populateCategorySuggest();
  } catch (err) {
    console.error(err);
    showToast("Failed to load OKRs", "error");
  }
}

function populateProjectSelectors() {
  const filter = $("project-filter");
  const omProject = $("om-project");

  const currentFilter = filter?.value || "";
  if (filter) {
    filter.innerHTML =
      `<option value="">All projects</option>` +
      state.projects.map(([id, name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join("");
    filter.value = currentFilter;
  }

  if (omProject) {
    const current = omProject.value;
    omProject.innerHTML =
      `<option value="">— Unassigned —</option>` +
      state.projects.map(([id, name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join("");
    omProject.value = current;
  }
}

/* ═══════════════════════════════════════════════════════════════
   THE LIST

   Rebuilt 2026-10-04: "UX is very cumbersome for OKR."

   It was. One objective carrying two key results with two initiatives
   each put EIGHTEEN controls on a single card — three icon buttons on the
   objective, a number input and two more buttons per key result, two per
   initiative, plus an Add button at every level. And creating one goal
   meant a modal with nine fields when only the title is required.

   The reason that was all ceremony is in the live data, which is why
   SIMPLE_GOALS exists in config.py: key results whose current_value had
   ever moved was 0 of 28, and tasks linked to a key result 3 of 120. The
   measurement layer was never used. Worse, /api/goals derived objective
   progress ONLY from key results — so every goal without one showed 0%,
   and the progress bar on this page was permanently empty.

   So: a goal is a sentence, a date and a percentage you can drag. Key
   results still exist and nothing was deleted; they are folded away
   behind a disclosure and the Add action moved into the row's menu,
   exactly as SIMPLE_GOALS already treats the Epic and Initiative pickers
   on the project tasks page.
   ═══════════════════════════════════════════════════════════════ */

/* Which goals are showing. Counts in the summary double as the filter,
   because "1 overdue" is the thing you then want to look at. */
state.filter = "all";

function daysUntil(o) {
  const iso = objectiveDeadlineIso(o);
  if (!iso) return null;
  const ms = new Date(iso) - new Date();
  return Math.floor(ms / 86400000);
}

function goalBucket(o) {
  const d = daysUntil(o);
  if (d === null) return "undated";
  if (d < 0) return "overdue";
  if (d <= 30) return "soon";
  return "later";
}

function setFilter(which) {
  state.filter = which;
  renderObjectives();
}

function renderObjectives() {
  const container = $("goals-list");
  const empty = $("goals-empty");
  const summary = $("goals-summary");

  if (!state.objectives.length) {
    container.innerHTML = "";
    if (summary) summary.hidden = true;
    empty.style.display = "block";
    if (window.feather) feather.replace();
    return;
  }
  empty.style.display = "none";

  // ── Counts first, then the filter they drive.
  const counts = { all: state.objectives.length, overdue: 0, soon: 0, undated: 0 };
  for (const o of state.objectives) {
    const b = goalBucket(o);
    if (counts[b] !== undefined) counts[b]++;
  }
  if (summary) {
    const chip = (key, label, cls) =>
      counts[key]
        ? `<button type="button" class="goal-chip ${cls} ${state.filter === key ? "is-on" : ""}"
             onclick="setFilter('${key}')">${counts[key]} ${label}</button>`
        : "";
    summary.innerHTML =
      `<button type="button" class="goal-chip is-all ${state.filter === "all" ? "is-on" : ""}"
         onclick="setFilter('all')">All ${counts.all}</button>` +
      chip("overdue", "overdue", "is-overdue") +
      chip("soon", "due within a month", "is-soon") +
      chip("undated", "no date", "is-undated");
    summary.hidden = false;
  }

  const shown = state.filter === "all"
    ? state.objectives
    : state.objectives.filter(o => goalBucket(o) === state.filter);

  if (!shown.length) {
    container.innerHTML =
      `<div class="goal-none">Nothing in this group.
         <button type="button" class="goal-link" onclick="setFilter('all')">Show all goals</button>
       </div>`;
    if (window.feather) feather.replace();
    return;
  }

  // Group by project, but only when there is more than one to tell apart.
  const byProject = new Map();
  for (const o of shown) {
    const key = o.project_id || "__unassigned__";
    if (!byProject.has(key)) byProject.set(key, []);
    byProject.get(key).push(o);
  }

  const projectNameMap = new Map(state.projects);
  const keys = [...byProject.keys()].sort((a, b) => {
    if (a === "__unassigned__") return 1;
    if (b === "__unassigned__") return -1;
    return (projectNameMap.get(a) || "").toLowerCase()
      .localeCompare((projectNameMap.get(b) || "").toLowerCase());
  });

  const singleProjectView = keys.length === 1;
  const sections = [];
  for (const key of keys) {
    const objs = byProject.get(key);
    const label = key === "__unassigned__"
      ? "Personal · no project"
      : (projectNameMap.get(key) || "Unknown project");
    if (!singleProjectView) {
      sections.push(`<div class="project-group-header">${esc(label)}</div>`);
    }
    sections.push(objs.map(o => renderObjectiveCard(o, singleProjectView)).join(""));
  }

  container.innerHTML = sections.join("");
  // Re-mount the tickers: the previous nodes are detached now and would keep
  // ticking against DOM nobody can see.
  if (typeof Countdown !== "undefined") { Countdown.clear(); Countdown.mountAll(container); }
  if (window.feather) feather.replace();
}

function renderObjectiveCard(o, hideProjectBadge) {
  const color = o.color || "#4447e5";
  const progress = Math.round(o._progress || 0);
  const statusClass = o.status && o.status !== "active" ? o.status : "";
  const bucket = goalBucket(o);
  const krs = o.key_results || [];
  const source = o._progress_source || "none";
  const rolled = Math.round(o._rolled_up || 0);

  const meta = [];
  if (!hideProjectBadge && o.project_name) {
    meta.push(`<span class="goal-meta-item">${esc(o.project_name)}</span>`);
  }
  if (o.category) meta.push(`<span class="goal-meta-item">${esc(o.category)}</span>`);
  if (o.time_horizon) meta.push(`<span class="goal-meta-item">${esc(o.time_horizon)}</span>`);

  /* WHERE THE NUMBER CAME FROM.
     Progress that counts itself is only trustworthy if you can see what it
     counted, so a task-derived figure says so: "3 of 8 tasks done". And if
     you have dragged the bar over an automatic number, the disagreement is
     SHOWN with a one-tap way back, rather than the page silently preferring
     one of the two. */
  const taskTotal = o._task_total || 0;
  const taskDone = o._task_done || 0;
  const fromTasks = (o._from_tasks === 0 || o._from_tasks) ? o._from_tasks : null;

  let note = "";
  if (source === "tasks") {
    note = `<span class="goal-source">${taskDone} of ${taskTotal} task${taskTotal === 1 ? "" : "s"} done</span>`;
  } else if (source === "key_results") {
    note = `<span class="goal-source">from ${krs.length} key result${krs.length === 1 ? "" : "s"}</span>`;
  } else if (source === "manual") {
    // Offer whichever automatic source actually exists, tasks first.
    const auto = fromTasks !== null
      ? { pct: fromTasks, what: `${taskDone} of ${taskTotal} tasks done` }
      : (krs.length ? { pct: rolled, what: "key results" } : null);
    note = auto
      ? `<button type="button" class="goal-rollup" onclick="clearGoalProgress('${o.id}')"
           title="Clear the typed percentage and let this goal count itself again">
           ${esc(auto.what)} = ${auto.pct}% — use that
         </button>`
      : `<span class="goal-source">set by hand</span>`;
  }
  const override = note;

  return `
    <div class="goal-card ${statusClass} bucket-${bucket}" data-objective-id="${o.id}">
      <div class="goal-color-bar" style="background:${esc(color)}"></div>

      <div class="goal-main">
        <div class="goal-title-row">
          <h3 class="goal-title">${esc(o.title)}</h3>
          ${o.status && o.status !== "active"
            ? `<span class="goal-status-pill">${esc(o.status)}</span>` : ""}
        </div>

        <div class="goal-meta">
          ${meta.join('<span class="goal-meta-dot">·</span>')}
          ${renderDueBlock(o)}
        </div>

        ${o.description ? `<p class="goal-description">${esc(o.description)}</p>` : ""}

        <div class="goal-progress-row">
          <label class="goal-slider-wrap">
            <span class="visually-hidden">Progress for ${esc(o.title)}</span>
            <input type="range" class="goal-slider" min="0" max="100" step="5"
                   value="${progress}"
                   style="--pct:${progress}%; --accent:${esc(color)}"
                   oninput="previewGoalProgress(this, '${o.id}')"
                   onchange="setGoalProgress('${o.id}', this.value)">
          </label>
          <output class="goal-pct" data-pct-for="${o.id}">${progress}%</output>
        </div>
        ${override}

        ${krs.length ? `
          <details class="kr-fold" ${state.openKrFolds?.has(o.id) ? "open" : ""}
                   ontoggle="rememberKrFold('${o.id}', this.open)">
            <summary>${krs.length} key result${krs.length === 1 ? "" : "s"}</summary>
            <div class="objective-list">
              ${krs.map(kr => renderKr(o, kr)).join("")}
              <button class="add-inline" onclick="openNewKrModal('${o.id}')"><i data-feather="plus"></i> Add key result</button>
            </div>
          </details>` : ""}
      </div>

      <div class="goal-menu-wrap">
        <button class="icon-btn goal-menu-btn" aria-label="More actions for ${esc(o.title)}"
                aria-haspopup="true" onclick="toggleGoalMenu(event, '${o.id}')">
          <i data-feather="more-horizontal"></i>
        </button>
        <div class="goal-menu" id="goal-menu-${o.id}" hidden>
          <button type="button" onclick="openEditObjectiveModal('${o.id}')">
            <i data-feather="edit-2"></i> Edit details
          </button>
          <button type="button" onclick="openNewKrModal('${o.id}')">
            <i data-feather="target"></i> Add key result
          </button>
          <button type="button" onclick="toggleObjectiveArchived('${o.id}')">
            <i data-feather="${o.status === "active" ? "archive" : "rotate-ccw"}"></i>
            ${o.status === "active" ? "Archive" : "Unarchive"}
          </button>
          <button type="button" class="danger" onclick="deleteObjective('${o.id}')">
            <i data-feather="trash-2"></i> Delete
          </button>
        </div>
      </div>
    </div>
  `;
}

/* Which folds the user had open, so a re-render does not close them. */
state.openKrFolds = new Set();
function rememberKrFold(id, open) {
  if (open) state.openKrFolds.add(id); else state.openKrFolds.delete(id);
}

/* ── The row menu. One button instead of three, which is most of what
      made a list of goals feel like a control panel. ── */
function toggleGoalMenu(ev, id) {
  ev.stopPropagation();
  const menu = $(`goal-menu-${id}`);
  const wasOpen = menu && !menu.hidden;
  closeAllGoalMenus();
  if (menu && !wasOpen) menu.hidden = false;
}

function closeAllGoalMenus() {
  document.querySelectorAll(".goal-menu").forEach(m => { m.hidden = true; });
}

document.addEventListener("click", closeAllGoalMenus);
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeAllGoalMenus();
});

/* ── Progress ──────────────────────────────────────────────────────────
   Dragging writes `manual_progress`, the same field /goal-planner has
   always written — so a percentage set in either place now shows in both.
   The slider is the bar: no second control to find, and a range input is
   draggable, tappable and keyboard-operable without any work. */

function previewGoalProgress(input, id) {
  input.style.setProperty("--pct", input.value + "%");
  const out = document.querySelector(`[data-pct-for="${id}"]`);
  if (out) out.textContent = input.value + "%";
}

async function setGoalProgress(id, value) {
  const pct = Math.max(0, Math.min(100, parseInt(value, 10) || 0));
  const obj = state.objectives.find(o => o.id === id);
  const before = obj ? obj.manual_progress : null;
  if (obj) { obj.manual_progress = pct; obj._progress = pct; obj._progress_source = "manual"; }
  try {
    await api("PATCH", `/api/goals/${id}`, { manual_progress: pct });
    renderObjectives();
  } catch (err) {
    console.error(err);
    // Put the number back. A slider that stays where you dragged it while
    // the server still holds the old value is worse than one that snaps.
    if (obj) { obj.manual_progress = before; }
    showToast("Could not save that progress", "error");
    await loadGoals();
  }
}

async function clearGoalProgress(id) {
  try {
    await api("PATCH", `/api/goals/${id}`, { manual_progress: "" });
    showToast("Back to the key-result roll-up");
    await loadGoals();
  } catch (err) {
    console.error(err);
    showToast("Could not clear that", "error");
  }
}

/* ── Adding a goal ─────────────────────────────────────────────────────
   One field. The nine-field modal is still there behind "More options",
   but it is no longer the price of writing down a goal: eight of those
   nine fields are optional and the endpoint has only ever required the
   title. */
async function addGoalInline() {
  const input = $("goal-quick-title");
  const date = $("goal-quick-date");
  const title = (input?.value || "").trim();
  if (!title) { input?.focus(); return; }

  const btn = $("goal-quick-add");
  if (btn) btn.disabled = true;
  try {
    await api("POST", "/api/goals", {
      title,
      target_date: date?.value || null,
      project_id: $("project-filter")?.value || null,
      time_horizon: "quarterly",
    });
    input.value = "";
    if (date) date.value = "";
    showToast("Goal added");
    await loadGoals();
    input.focus();
  } catch (err) {
    console.error(err);
    showToast("Could not add that goal", "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function quickAddKeydown(e) {
  if (e.key === "Enter") { e.preventDefault(); addGoalInline(); }
}

/* ── Key results and initiatives, unchanged ────────────────────────────
   Nothing here was deleted. SIMPLE_GOALS folds this layer away because
   the live data says it went unused — 0 of 28 key results had ever had
   their current_value moved — but a goal that genuinely IS a number still
   measures itself this way, and flipping the flag brings the inline
   buttons back. The only change is where it is rendered: inside a
   <details> on the row rather than always open underneath it. */

/* "· updated 9 days ago" after a key result's targets, from
   key_results.last_checked_at (MIGRATION_KR_CHECKINS.sql). Empty when the
   column is missing or the value is filled in from tasks. A hand-kept
   number that has not moved in a week is marked, because that is the
   signal the weekly check-in exists to act on. */
function krSince(kr) {
  if (!kr.last_checked_at || kr.auto_progress) return "";
  const days = Math.floor((Date.now() - new Date(kr.last_checked_at).getTime()) / 86400000);
  if (Number.isNaN(days) || days < 0) return "";
  const txt = days === 0 ? "updated today" : days === 1 ? "updated yesterday" : `updated ${days} days ago`;
  return days >= 7
    ? ` · <a class="kr-stale" href="/goals/check-in" title="Update it in the weekly check-in">${txt}</a>`
    : ` · ${txt}`;
}

function renderKr(o, kr) {
  const progress = Math.round(kr._progress || 0);
  const unit = kr.unit || "";
  const color = o.color || "#4447e5";
  const initiatives = kr.initiatives || [];

  return `
    <div class="kr-block" data-kr-id="${kr.id}">
      <div class="kr-row">
        <div>
          <div class="kr-title">${esc(kr.title)}</div>
          <div class="kr-meta">
            Start ${fmtNum(kr.start_value)}${esc(unit)} · Target ${fmtNum(kr.target_value)}${esc(unit)}${krSince(kr)}
          </div>
        </div>
        <div class="kr-progress-group">
          <input type="number" step="any" class="kr-current-edit"
                 value="${kr.current_value ?? 0}"
                 title="Update current value"
                 onchange="updateKrCurrent('${kr.id}', this.value)">
          <div class="kr-progress-bar"><div class="kr-progress-bar-fill" style="width:${progress}%;background:${esc(color)}"></div></div>
          <div class="progress-label">${progress}%</div>
        </div>
        <div class="objective-actions">
          <button class="icon-btn" title="Edit" onclick="openEditKrModal('${kr.id}')"><i data-feather="edit-2"></i></button>
          <button class="icon-btn danger" title="Delete" onclick="deleteKr('${kr.id}')"><i data-feather="trash-2"></i></button>
        </div>
      </div>
      <div class="initiative-list">
        ${initiatives.map(i => renderInitiative(i)).join("")}
        <button class="add-inline add-inline-sub" onclick="openNewInitiativeModal('${kr.id}')"><i data-feather="plus"></i> Add initiative</button>
      </div>
    </div>
  `;
}

function renderInitiative(i) {
  return `
    <div class="initiative-row" data-initiative-id="${i.id}">
      <div class="initiative-icon">⚙</div>
      <div class="initiative-body">
        <div class="initiative-title">${esc(i.title)}</div>
        ${i.description ? `<div class="initiative-desc">${esc(i.description)}</div>` : ""}
      </div>
      <div class="objective-actions">
        <button class="icon-btn" title="Edit" onclick="openEditInitiativeModal('${i.id}')"><i data-feather="edit-2"></i></button>
        <button class="icon-btn danger" title="Delete" onclick="deleteInitiative('${i.id}')"><i data-feather="trash-2"></i></button>
      </div>
    </div>
  `;
}

function fmtNum(n) {
  if (n === null || n === undefined || n === "") return "0";
  const num = Number(n);
  if (Number.isNaN(num)) return String(n);
  if (Math.abs(num) >= 10000) return num.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return (num % 1 === 0) ? num.toString() : num.toFixed(2).replace(/\.?0+$/, "");
}

function formatDueLabel(dateStr) {
  if (!dateStr) return null;
  const target = new Date(dateStr);
  const now = new Date();
  const days = Math.round((target - now) / (1000 * 60 * 60 * 24));
  if (days < 0) return { text: `Overdue by ${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"}`, cls: "overdue" };
  if (days === 0) return { text: "Due today", cls: "soon" };
  if (days <= 14) return { text: `Due in ${days} day${days === 1 ? "" : "s"}`, cls: "soon" };
  return { text: `Due ${target.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}`, cls: "" };
}

/* The deadline as an ISO moment, from whichever field the objective has.
   `target_at` only exists once MIGRATION_GOAL_COUNTDOWN.sql has been run, so
   a bare `target_date` is resolved to the END of that day — treating it as
   midnight would quietly drop the last 24 hours of every objective. */
function objectiveDeadlineIso(o) {
  if (o.target_at) return o.target_at;
  if (o.target_date) return `${String(o.target_date).slice(0, 10)}T23:59:59`;
  return null;
}

/* The live ticker, when countdown.js is present. Falls back to the static
   label above so an objective still shows its deadline if the script is
   missing — the OKR page must not depend on an enhancement. */
function renderDueBlock(o) {
  const iso = objectiveDeadlineIso(o);
  if (!iso) return "";
  const fallback = formatDueLabel(o.target_date || iso);
  if (typeof Countdown === "undefined") {
    return fallback ? `<div class="goal-due ${fallback.cls}">${fallback.text}</div>` : "";
  }
  /* No flash here: /goals is a planning surface, not the urgency surface.
     The pulsing hero lives on /goal-planner, and one loud place is enough. */
  /* One line, all three units: "44d 06h 12m". Three separate boxes per card
     would be noise in a list this dense — the planner hero is where the big
     segmented clock belongs. */
  return `<div class="goal-due goal-countdown" data-countdown="${esc(iso)}" data-flash="false">
            <b data-cd-compact></b><i data-cd-detail></i>
          </div>`;
}

function populateCategorySuggest() {
  const datalist = $("cat-suggest");
  if (!datalist) return;
  const cats = new Set(state.objectives.map(o => o.category).filter(Boolean));
  datalist.innerHTML = [...cats].map(c => `<option value="${esc(c)}">`).join("");
}

// ═══════════════════════════════════════════════════════════════
// OBJECTIVE MODAL
// ═══════════════════════════════════════════════════════════════

function openNewObjectiveModal() {
  state.editingObjectiveId = null;
  state.selectedColor = "#2563eb";
  $("objective-modal-title").textContent = "New Objective";
  $("om-project").value = $("project-filter")?.value || "";
  $("om-title").value = "";
  $("om-description").value = "";
  $("om-category").value = "";
  $("om-horizon").value = "quarterly";
  $("om-start").value = "";
  $("om-target").value = "";
  highlightColor(state.selectedColor);
  $("objective-modal").classList.remove("hidden");
  setTimeout(() => $("om-title").focus(), 50);
}

function openEditObjectiveModal(objectiveId) {
  const o = state.objectives.find(x => x.id === objectiveId);
  if (!o) return;
  state.editingObjectiveId = objectiveId;
  state.selectedColor = o.color || "#2563eb";
  $("objective-modal-title").textContent = "Edit Objective";
  $("om-project").value = o.project_id || "";
  $("om-title").value = o.title || "";
  $("om-description").value = o.description || "";
  $("om-category").value = o.category || "";
  $("om-horizon").value = o.time_horizon || "quarterly";
  $("om-start").value = o.start_date || "";
  $("om-target").value = o.target_date || "";
  highlightColor(state.selectedColor);
  $("objective-modal").classList.remove("hidden");
}

function closeObjectiveModal() {
  $("objective-modal").classList.add("hidden");
  state.editingObjectiveId = null;
}

function highlightColor(color) {
  document.querySelectorAll("#om-color button").forEach(btn => {
    btn.classList.toggle("selected", btn.dataset.color === color);
  });
}

async function saveObjectiveModal() {
  const payload = {
    project_id: $("om-project").value || null,
    title: $("om-title").value.trim(),
    description: $("om-description").value.trim(),
    category: $("om-category").value.trim(),
    time_horizon: $("om-horizon").value,
    start_date: $("om-start").value || null,
    target_date: $("om-target").value || null,
    color: state.selectedColor,
  };
  if (!payload.title) { showToast("Title is required", "error"); return; }

  try {
    if (state.editingObjectiveId) {
      await api("PATCH", `/api/goals/${state.editingObjectiveId}`, payload);
      showToast("Objective updated", "success");
    } else {
      await api("POST", "/api/goals", payload);
      showToast("Objective created", "success");
    }
    closeObjectiveModal();
    await loadGoals();
  } catch (err) {
    showToast(err.message || "Save failed", "error");
  }
}

async function deleteObjective(objectiveId) {
  const o = state.objectives.find(x => x.id === objectiveId);
  if (!o) return;
  if (!confirm(`Delete "${o.title}" and ALL its key results and initiatives? This cannot be undone.`)) return;
  try {
    await api("DELETE", `/api/goals/${objectiveId}`);
    showToast("Objective deleted", "success");
    await loadGoals();
  } catch (err) {
    showToast(err.message || "Delete failed", "error");
  }
}

async function toggleObjectiveArchived(objectiveId) {
  const o = state.objectives.find(x => x.id === objectiveId);
  if (!o) return;
  const newStatus = o.status === "active" ? "paused" : "active";
  try {
    await api("PATCH", `/api/goals/${objectiveId}`, { status: newStatus });
    showToast(newStatus === "paused" ? "Objective archived" : "Objective reactivated", "success");
    await loadGoals();
  } catch (err) {
    showToast(err.message || "Update failed", "error");
  }
}

// ═══════════════════════════════════════════════════════════════
// KEY RESULT MODAL
// ═══════════════════════════════════════════════════════════════

function openNewKrModal(objectiveId) {
  state.editingKrId = null;
  state.pendingKrObjectiveId = objectiveId;
  $("kr-modal-title").textContent = "New Key Result";
  $("km-title").value = "";
  $("km-start").value = 0;
  $("km-current").value = 0;
  $("km-target").value = "";
  $("km-unit").value = "";
  $("km-direction").value = "up";
  const auto = $("km-auto-progress");
  if (auto) auto.checked = false;
  $("kr-modal").classList.remove("hidden");
  setTimeout(() => $("km-title").focus(), 50);
}

function openEditKrModal(krId) {
  let kr = null, parentObj = null;
  for (const o of state.objectives) {
    const k = (o.key_results || []).find(x => x.id === krId);
    if (k) { kr = k; parentObj = o; break; }
  }
  if (!kr) return;
  state.editingKrId = krId;
  state.pendingKrObjectiveId = parentObj.id;
  $("kr-modal-title").textContent = "Edit Key Result";
  $("km-title").value = kr.title || "";
  $("km-start").value = kr.start_value ?? 0;
  $("km-current").value = kr.current_value ?? 0;
  $("km-target").value = kr.target_value ?? "";
  $("km-unit").value = kr.unit || "";
  $("km-direction").value = kr.direction || "up";
  const auto = $("km-auto-progress");
  if (auto) auto.checked = !!kr.auto_progress;
  $("kr-modal").classList.remove("hidden");
}

function closeKrModal() {
  $("kr-modal").classList.add("hidden");
  state.editingKrId = null;
  state.pendingKrObjectiveId = null;
}

async function saveKrModal() {
  const target = parseFloat($("km-target").value);
  if (Number.isNaN(target)) { showToast("Target is required", "error"); return; }

  const payload = {
    title: $("km-title").value.trim(),
    start_value: parseFloat($("km-start").value) || 0,
    current_value: parseFloat($("km-current").value) || 0,
    target_value: target,
    unit: $("km-unit").value.trim() || null,
    direction: $("km-direction").value,
    auto_progress: !!($("km-auto-progress") && $("km-auto-progress").checked),
  };
  if (!payload.title) { showToast("Title is required", "error"); return; }

  try {
    if (state.editingKrId) {
      await api("PATCH", `/api/key-results/${state.editingKrId}`, payload);
      showToast("Key result updated", "success");
    } else {
      payload.objective_id = state.pendingKrObjectiveId;
      await api("POST", "/api/key-results", payload);
      showToast("Key result created", "success");
    }
    closeKrModal();
    await loadGoals();
  } catch (err) {
    showToast(err.message || "Save failed", "error");
  }
}

async function deleteKr(krId) {
  if (!confirm("Delete this key result and all its initiatives?")) return;
  try {
    await api("DELETE", `/api/key-results/${krId}`);
    showToast("Key result deleted", "success");
    await loadGoals();
  } catch (err) {
    showToast(err.message || "Delete failed", "error");
  }
}

async function updateKrCurrent(krId, value) {
  const num = parseFloat(value);
  if (Number.isNaN(num)) return;
  try {
    await api("PATCH", `/api/key-results/${krId}`, { current_value: num });
    await loadGoals();
  } catch (err) {
    showToast(err.message || "Update failed", "error");
  }
}

// ═══════════════════════════════════════════════════════════════
// INITIATIVE MODAL
// ═══════════════════════════════════════════════════════════════

function openNewInitiativeModal(krId) {
  state.editingInitiativeId = null;
  state.pendingInitiativeKrId = krId;
  $("initiative-modal-title").textContent = "New Initiative";
  $("im-title").value = "";
  $("im-description").value = "";
  $("initiative-modal").classList.remove("hidden");
  setTimeout(() => $("im-title").focus(), 50);
}

function openEditInitiativeModal(initiativeId) {
  let init = null, parentKr = null;
  for (const o of state.objectives) {
    for (const k of (o.key_results || [])) {
      const i = (k.initiatives || []).find(x => x.id === initiativeId);
      if (i) { init = i; parentKr = k; break; }
    }
    if (init) break;
  }
  if (!init) return;
  state.editingInitiativeId = initiativeId;
  state.pendingInitiativeKrId = parentKr.id;
  $("initiative-modal-title").textContent = "Edit Initiative";
  $("im-title").value = init.title || "";
  $("im-description").value = init.description || "";
  $("initiative-modal").classList.remove("hidden");
}

function closeInitiativeModal() {
  $("initiative-modal").classList.add("hidden");
  state.editingInitiativeId = null;
  state.pendingInitiativeKrId = null;
}

async function saveInitiativeModal() {
  const payload = {
    title: $("im-title").value.trim(),
    description: $("im-description").value.trim(),
  };
  if (!payload.title) { showToast("Title is required", "error"); return; }

  try {
    if (state.editingInitiativeId) {
      await api("PATCH", `/api/initiatives/${state.editingInitiativeId}`, payload);
      showToast("Initiative updated", "success");
    } else {
      payload.key_result_id = state.pendingInitiativeKrId;
      await api("POST", "/api/initiatives", payload);
      showToast("Initiative created", "success");
    }
    closeInitiativeModal();
    await loadGoals();
  } catch (err) {
    showToast(err.message || "Save failed", "error");
  }
}

async function deleteInitiative(initiativeId) {
  if (!confirm("Delete this initiative? Tasks linked to it will lose their initiative link but remain in the project.")) return;
  try {
    await api("DELETE", `/api/initiatives/${initiativeId}`);
    showToast("Initiative deleted", "success");
    await loadGoals();
  } catch (err) {
    showToast(err.message || "Delete failed", "error");
  }
}

// ═══════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("#om-color button").forEach(btn => {
    btn.addEventListener("click", () => {
      state.selectedColor = btn.dataset.color;
      highlightColor(state.selectedColor);
    });
  });

  $("include-archived")?.addEventListener("change", loadGoals);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeObjectiveModal();
      closeKrModal();
      closeInitiativeModal();
    }
  });

  loadGoals();
});
