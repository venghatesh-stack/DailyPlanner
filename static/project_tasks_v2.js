/* DailyPlanner — project tasks page v2 shell.

   Responsibilities (only the new bits — row-level interactions like
   open-detail, toggle done, edit etc. all stay in project_tasks.js):

     1. Tab switching: Focus / All / Tree / Done.
        - URL hash mirror so `#tree` etc. deep-links and survives reload.
        - Body data-active-tab attribute so CSS can hide the standalone
          table/board on the wrong tab without JS toggling each one.
     2. Focus tab: read every <tr.task-row> in the table, group into
        Overdue / Today / Upcoming (7 days), render lightweight cards
        that delegate to the existing openTaskDetail / toggleTaskDone.
     3. Done tab: same idea, filter for rows with data-status="done".
     4. Tree tab: render OKR > Init > Epic columns inline (instead of
        as a modal). Reuses the /api/projects/<id>/hierarchy endpoint
        already wired by okr_cascade.js. Selecting a node filters the
        Tree-tasks list below.
     5. Sticky add bar expander: tap chevron toggles the detail row.
     6. ⋯ menu open/close + density cycling.
     7. Stat bar (header progress) from the same source as Focus.

   This file is purely a presentation layer over the existing data —
   it never mutates state directly; everything goes through the
   pre-existing handlers in project_tasks.js. */

(function () {
  "use strict";

  if (!document.querySelector(".ptv2-tabs")) return;
  document.body.dataset.ptv2 = "1";

  /* ───── PROJECT_ID + endpoints ──────────────────────────────── */

  const PROJECT_ID = (document.getElementById("add-task-input") || {}).dataset?.projectId
                  || (location.pathname.match(/\/projects\/([^/]+)\/tasks/) || [])[1];

  const _fetch = window.dpFetch || ((u, o) => fetch(u, o));

  /* ───── tab switching ───────────────────────────────────────── */

  const TABS = ["focus", "all", "tree", "done"];
  function activeTab() {
    const h = (location.hash || "").replace("#", "").split("?")[0];
    return TABS.includes(h) ? h : "focus";
  }
  function setTab(tab, opts = {}) {
    if (!TABS.includes(tab)) tab = "focus";
    document.body.dataset.activeTab = tab;
    document.querySelectorAll(".ptv2-tab").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === tab);
    });
    document.querySelectorAll(".ptv2-panel").forEach((p) => {
      p.hidden = p.dataset.tab !== tab;
    });
    if (!opts.skipHash && activeTab() !== tab) {
      history.replaceState(null, "", `#${tab}`);
    }
    // Render tab-specific content on entry.
    if (tab === "focus")   renderFocus();
    if (tab === "tree")    renderTreeIfNeeded();
    if (tab === "done")    renderDone();
    if (tab === "sprints") renderSprintsTab();
  }
  function jumpTab(tab) { setTab(tab); }

  document.addEventListener("click", (e) => {
    const tabBtn = e.target.closest(".ptv2-tab[data-tab]");
    if (tabBtn) { setTab(tabBtn.dataset.tab); return; }
    const jumpLink = e.target.closest("[data-jump-tab]");
    if (jumpLink) { e.preventDefault(); setTab(jumpLink.dataset.jumpTab); }
  });
  window.addEventListener("hashchange", () => setTab(activeTab(), { skipHash: true }));
  window.ptv2GoTab = jumpTab;

  /* ───── grab the source task data from the existing table ──── */

  function readTasks() {
    const rows = Array.from(document.querySelectorAll("#task-tbody tr.task-row"));
    return rows.map((row) => ({
      el:           row,
      id:           row.dataset.id,
      status:       row.dataset.status,
      priority:     row.dataset.priority,
      objectiveId:  row.dataset.objectiveId,
      keyResultId:  row.dataset.krId || row.dataset.keyResultId,
      initiativeId: row.dataset.initiativeId,
      epicId:       row.dataset.epicId,
      sprintId:     row.dataset.sprintId,
      group:        row.dataset.group,
      isDone:       row.dataset.status === "done" || row.classList.contains("done"),
      title:        (row.querySelector(".task-text")?.textContent || "").trim(),
      dueLabel:     (row.querySelector(".due-chip")?.textContent || "").trim(),
      dueOverdue:   !!row.querySelector(".due-chip.overdue-label"),
    }));
  }

  /* ───── render a "ptv2-row" card for a task ─────────────────── */

  function rowCard(t, opts = {}) {
    const prio = ["high", "medium", "low"].includes(t.priority) ? t.priority : "medium";
    const div = document.createElement("div");
    div.className = `ptv2-row prio-${prio}${t.isDone ? " is-done" : ""}`;
    div.dataset.id = t.id;
    div.innerHTML = `
      <span class="ptv2-row-prio"></span>
      <button type="button" class="ptv2-row-check${t.isDone ? " is-checked" : ""}"
              aria-label="Toggle done">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"
             stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
      </button>
      <div class="ptv2-row-main">
        <span class="ptv2-row-title" title="${esc(t.title)}">${esc(t.title) || "(untitled)"}</span>
        <div class="ptv2-row-meta">
          ${t.dueLabel ? `<span class="ptv2-row-due${t.dueOverdue ? " is-overdue" : ""}">${esc(t.dueLabel)}</span>` : ""}
          ${opts.crumb ? `<span class="ptv2-row-crumb">${esc(opts.crumb)}</span>` : ""}
        </div>
      </div>`;
    // Open detail when the card body is tapped — delegate to the
    // existing handler.
    div.addEventListener("click", (e) => {
      if (e.target.closest(".ptv2-row-check")) return;
      if (typeof openTaskDetail === "function") openTaskDetail(t.id);
    });
    // Toggle done — also delegate to the existing chain so server +
    // optimistic UI + recurrence all behave the same as the table.
    div.querySelector(".ptv2-row-check").addEventListener("click", (e) => {
      e.stopPropagation();
      const cb = t.el.querySelector("input.task-check");
      if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event("change", { bubbles: true })); }
      // Optimistic local class flip; the existing handler will sync the DOM.
      const becomes = !div.classList.contains("is-done");
      div.classList.toggle("is-done", becomes);
      div.querySelector(".ptv2-row-check").classList.toggle("is-checked", becomes);
      // Re-render the focus/done lists on the next tick so counts stay right.
      setTimeout(() => {
        if (document.body.dataset.activeTab === "focus") renderFocus();
        if (document.body.dataset.activeTab === "done")  renderDone();
      }, 250);
    });
    return div;
  }

  /* ───── crumb resolver: task -> "OKR ▸ Initiative" ──────────── */

  let _hierIndex = null;          // { objectivesById, initiativesById, epicsById }
  function indexHierarchy(tree) {
    const objectivesById  = new Map();
    const krsById         = new Map();
    const initiativesById = new Map();
    const epicsById       = new Map();
    for (const o of tree) {
      objectivesById.set(o.id, o);
      for (const kr of o.key_results || []) {
        krsById.set(kr.id, { ...kr, _okr: o });
        for (const it of kr.initiatives || []) {
          initiativesById.set(it.id, { ...it, _kr: kr, _okr: o });
          for (const ep of it.epics || []) {
            epicsById.set(ep.id, { ...ep, _init: it, _kr: kr, _okr: o });
          }
        }
      }
    }
    _hierIndex = { objectivesById, krsById, initiativesById, epicsById };
  }
  // Most-specific-wins crumb. Epic is the most specific bucket a task
  // can live in, so when it has one we show "Initiative ▸ Epic" — the
  // old version stopped at Initiative and the user couldn't tell which
  // epic a task belonged to from the Focus/Done/Tree-tasks lists.
  function crumbFor(t) {
    if (!_hierIndex) return "";
    const ep = t.epicId && _hierIndex.epicsById.get(t.epicId);
    if (ep) {
      // Skip the redundant initiative prefix for default catch-alls so
      // every task in an Inbox-style epic doesn't shout "Inbox ▸ Inbox".
      if (ep._init && !ep._init.is_default) return `${ep._init.title} ▸ ${ep.title}`;
      return ep.title;
    }
    const init = t.initiativeId && _hierIndex.initiativesById.get(t.initiativeId);
    if (init) return init.title;
    const obj = t.objectiveId && _hierIndex.objectivesById.get(t.objectiveId);
    if (obj) return obj.title;
    return "";
  }

  /* ───── FOCUS tab ───────────────────────────────────────────── */

  function renderFocus() {
    const tasks = readTasks().filter((t) => !t.isDone);
    const buckets = { overdue: [], today: [], upcoming: [] };
    for (const t of tasks) {
      // Tasks the server already classified into a group — we honor it,
      // but only the three Focus buckets we care about here.
      const g = (t.group || "").toLowerCase();
      const lbl = (t.dueLabel || "").toLowerCase();
      if (t.dueOverdue || g.includes("overdue") || lbl.includes("overdue")) {
        buckets.overdue.push(t);
      } else if (g.includes("today") || lbl === "today") {
        buckets.today.push(t);
      } else if (
        g.includes("this week") || g.includes("upcoming") ||
        ["tomorrow", "mon", "tue", "wed", "thu", "fri", "sat", "sun"].some((d) => lbl.startsWith(d))
      ) {
        buckets.upcoming.push(t);
      }
    }
    const lists = { overdue: "#list-overdue", today: "#list-today", upcoming: "#list-upcoming" };
    const counts = { overdue: "#ct-overdue", today: "#ct-today", upcoming: "#ct-upcoming" };
    for (const k of Object.keys(buckets)) {
      const el = document.querySelector(lists[k]);
      const cnt = document.querySelector(counts[k]);
      if (!el || !cnt) continue;
      el.innerHTML = "";
      buckets[k].forEach((t) => el.appendChild(rowCard(t, { crumb: crumbFor(t) })));
      cnt.textContent = String(buckets[k].length);
    }
    // Show / hide whole sections based on emptiness — keeps the page
    // tidy when one bucket is zero.
    ["overdue", "today", "upcoming"].forEach((k) => {
      const sec = document.getElementById(`ptv2-${k}`);
      if (sec) sec.hidden = buckets[k].length === 0;
    });
    const totalFocus = buckets.overdue.length + buckets.today.length + buckets.upcoming.length;
    const emptyEl = document.getElementById("ptv2-focus-empty");
    if (emptyEl) emptyEl.hidden = totalFocus > 0;

    // Header badges + project header counts.
    setBadge("focus", totalFocus);
  }

  /* ───── DONE tab ────────────────────────────────────────────── */

  function renderDone() {
    const tasks = readTasks().filter((t) => t.isDone);
    const list = document.getElementById("list-done");
    const cnt = document.getElementById("ct-done");
    const empty = document.getElementById("ptv2-done-empty");
    if (!list) return;
    list.innerHTML = "";
    tasks.forEach((t) => list.appendChild(rowCard(t, { crumb: crumbFor(t) })));
    if (cnt) cnt.textContent = String(tasks.length);
    if (empty) empty.hidden = tasks.length > 0;
    setBadge("done", tasks.length);
  }

  /* ───── TREE tab ────────────────────────────────────────────── */

  // Active filter for the nested tree. Default tap = replace the whole
  // selection (covers the common case in one tap). Power gesture —
  // Shift/Ctrl/⌘-click on desktop or long-press on mobile — toggles
  // a row's membership so users can build up an "OKR A + OKR B"
  // union. Empty array = no filter, show every task.
  let _treeFilter = [];   // [{ type: "okr"|"init"|"epic", id }, ...]
  let _treeData = [];
  let _sprints = [];                 // [{id,name,starts_on,ends_on,is_active,...}]
  let _sprintSel = new Set();        // checked sprint ids (multi-select filter)

  async function renderTreeIfNeeded() {
    if (_treeData.length === 0) await fetchTree();
    renderTree();
  }
  async function fetchTree() {
    if (!PROJECT_ID) return;
    try {
      const r = await fetch(`/api/projects/${PROJECT_ID}/hierarchy`, { credentials: "same-origin" });
      const j = await r.json();
      _treeData = j.tree || [];
      _sprints  = j.sprints || [];
      indexHierarchy(_treeData);
      renderSprintsBar();
      populateSprintPickers();
    } catch (e) { console.warn("[ptv2] tree fetch failed", e); }
  }

  /* ───── SPRINTS bar (v2) ────────────────────────────────────── */

  // Format the "when" label for a sprint based on dates + today.
  function _sprintWhenLabel(s, today) {
    if (s.is_active && s.ends_on) {
      const days = _daysBetween(today, s.ends_on);
      if (days < 0)  return "Ended";
      if (days === 0) return "Ends today";
      if (days === 1) return "1d left";
      return `${days}d left`;
    }
    if (s.ends_on && s.ends_on < today) return "Past";
    if (s.starts_on && s.starts_on > today) {
      const days = _daysBetween(today, s.starts_on);
      return days === 1 ? "Starts tomorrow" : `Starts in ${days}d`;
    }
    if (s.starts_on && s.ends_on) return `${_fmtShort(s.starts_on)} – ${_fmtShort(s.ends_on)}`;
    if (s.starts_on) return `From ${_fmtShort(s.starts_on)}`;
    if (s.ends_on)   return `Due ${_fmtShort(s.ends_on)}`;
    return "No dates";
  }
  function _daysBetween(aIso, bIso) {
    const a = new Date(aIso + "T00:00:00");
    const b = new Date(bIso + "T00:00:00");
    return Math.round((b - a) / 86400000);
  }
  function _fmtShort(iso) {
    // "2026-05-23" → "May 23"
    try {
      const d = new Date(iso + "T00:00:00");
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    } catch (_) { return iso; }
  }

  // Visual class: "is-running" / "is-past" / "is-upcoming" / ""
  function _sprintLifecycleClass(s, today) {
    if (s.is_active) return "is-running";
    if (s.ends_on && s.ends_on < today) return "is-past";
    if (s.starts_on && s.starts_on > today) return "is-upcoming";
    return "";
  }

  function renderSprintsBar() {
    const bar = document.getElementById("ptv2-sprints-bar");
    const list = document.getElementById("ptv2-sprints-list");
    if (!bar || !list) return;
    bar.hidden = false;
    list.innerHTML = "";
    // Keep the Sprints tab badge in sync on every render so the count
    // reflects current state even if the user never opens the tab.
    setBadge("sprints", _sprints.length);

    const today = new Date().toISOString().slice(0, 10);

    // Count tasks per sprint from the existing DOM. Track open + done
    // separately so chips can show "3/8" (done / total).
    const totals = new Map();
    const dones  = new Map();
    document.querySelectorAll("#task-tbody tr.task-row").forEach((row) => {
      const sid = row.dataset.sprintId;
      if (!sid) return;
      totals.set(sid, (totals.get(sid) || 0) + 1);
      if (row.dataset.status === "done") dones.set(sid, (dones.get(sid) || 0) + 1);
    });

    // Empty state: single CTA replaces the whole bar.
    if (!_sprints.length) {
      const cta = document.createElement("button");
      cta.type = "button";
      cta.className = "ptv2-sprints-empty-cta";
      cta.innerHTML = `<span>＋</span> Start your first sprint`;
      cta.addEventListener("click", openInlineCreate);
      list.appendChild(cta);
      return;
    }

    for (const s of _sprints) {
      const chip = document.createElement("button");
      chip.type = "button";
      const lifecycle = _sprintLifecycleClass(s, today);
      chip.className = "ptv2-sprint-chip "
        + lifecycle
        + (_sprintSel.has(s.id) ? " is-selected" : "");
      chip.dataset.sprintId = s.id;
      const total = totals.get(s.id) || 0;
      const done  = dones.get(s.id) || 0;
      const pct   = total ? Math.round((done / total) * 100) : 0;
      const countTip = total
        ? `${done} of ${total} tasks done`
        : "No tasks in this sprint yet";
      chip.innerHTML = `
        <div class="sc-top">
          <span class="sc-dot" aria-hidden="true"></span>
          <span class="sc-name" title="${esc(s.name)}">${esc(s.name)}</span>
        </div>
        <div class="sc-meta">
          <span class="sc-when">${esc(_sprintWhenLabel(s, today))}</span>
          <span class="sc-count" title="${esc(countTip)}">${done}/${total} done</span>
        </div>
        <span class="sc-bar"><span class="sc-bar-fill" style="width:${pct}%"></span></span>
        <button type="button" class="sc-menu" aria-label="Sprint options" title="Options">⋮</button>`;
      // Tap chip body = toggle filter.
      chip.addEventListener("click", (e) => {
        if (e.target.closest(".sc-menu")) return;
        if (_sprintSel.has(s.id)) _sprintSel.delete(s.id);
        else _sprintSel.add(s.id);
        renderSprintsBar();
        applySprintFilter();
      });
      chip.querySelector(".sc-menu").addEventListener("click", (e) => {
        e.stopPropagation();
        openSprintMenu(s, chip.querySelector(".sc-menu"));
      });
      list.appendChild(chip);
    }

    const add = document.createElement("button");
    add.type = "button";
    add.className = "ptv2-sprint-add";
    add.innerHTML = `＋ Sprint`;
    add.addEventListener("click", openInlineCreate);
    list.appendChild(add);
  }

  /* ───── inline create form ──────────────────────────────────── */

  // Suggest the next sprint name by continuing whatever pattern the
  // user is already using. We look at the most-recent sprint (server
  // orders active first, then newest start_date) for a trailing
  // integer — e.g. "op-sprint-1" → "op-sprint-2",
  // "Q3 sprint 4" → "Q3 sprint 5". Among sprints sharing that same
  // prefix we increment the highest number so renaming an older entry
  // doesn't collapse the sequence. Falls back to "Sprint N" when no
  // sprint name ends in a number. User can always overwrite.
  function nextSprintName() {
    const trailingInt = /^(.*?)(\d+)\s*$/;
    for (const recent of _sprints) {
      const m = (recent.name || "").match(trailingInt);
      if (!m) continue;
      const prefix = m[1];
      let max = 0;
      for (const s of _sprints) {
        const mm = (s.name || "").match(trailingInt);
        if (!mm || mm[1] !== prefix) continue;
        const n = parseInt(mm[2], 10);
        if (n > max) max = n;
      }
      return `${prefix}${max + 1}`;
    }
    return "Sprint 1";
  }

  // Compute default dates for a new sprint. If there's a previous
  // sprint with both dates, continue its cadence: same duration,
  // starts the day after the previous one ends. Otherwise default to
  // a 2-week sprint starting today.
  function nextSprintDates() {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const fmt = (d) => {
      const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
      return z.toISOString().slice(0, 10);
    };
    for (const s of _sprints) {
      if (!s.starts_on || !s.ends_on) continue;
      const ps = new Date(s.starts_on + "T00:00:00");
      const pe = new Date(s.ends_on   + "T00:00:00");
      if (isNaN(ps) || isNaN(pe) || pe < ps) continue;
      // ends_on is inclusive, so a 14-day sprint has (ends - starts) = 13.
      const spanDays = Math.round((pe - ps) / 86400000);
      const start = new Date(pe); start.setDate(start.getDate() + 1);
      const end   = new Date(start); end.setDate(end.getDate() + spanDays);
      return { start: fmt(start), end: fmt(end) };
    }
    const end = new Date(today); end.setDate(end.getDate() + 13);
    return { start: fmt(today), end: fmt(end) };
  }

  function openInlineCreate() {
    const form = document.getElementById("ptv2-sprint-new");
    if (!form) return;
    form.hidden = false;
    // Pre-fill name + dates so the typical "click + Create" path
    // produces a sensibly-named sprint with zero typing. Cycle comes
    // from the previous sprint so back-to-back sprints stay in lockstep.
    const nameEl = form.querySelector('[name="name"]');
    if (nameEl && !nameEl.value) nameEl.value = nextSprintName();
    const start = form.querySelector('[name="starts_on"]');
    const end   = form.querySelector('[name="ends_on"]');
    const dates = nextSprintDates();
    if (start && !start.value) start.value = dates.start;
    if (end && !end.value)     end.value   = dates.end;
    // Select the name so the user can immediately type to overwrite
    // (or hit Tab/Enter to accept the suggestion).
    nameEl?.select();
  }
  function closeInlineCreate() {
    const form = document.getElementById("ptv2-sprint-new");
    if (form) { form.hidden = true; form.reset(); }
  }
  document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("ptv2-sprint-new");
    if (!form) return;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      await createSprint({
        name:      (fd.get("name") || "").toString().trim(),
        starts_on: fd.get("starts_on") || null,
        ends_on:   fd.get("ends_on") || null,
      });
      closeInlineCreate();
    });
    document.getElementById("ptv2-sn-cancel")?.addEventListener("click", closeInlineCreate);
  });

  /* ───── per-chip ⋮ menu ─────────────────────────────────────── */

  // Last anchor for the open sprint menu — kept so we can reposition
  // when the menu's content changes height (e.g. switching to the
  // inline editor); otherwise the editor could render off-screen.
  let _sprintMenuAnchor = null;

  function openSprintMenu(s, anchor) {
    const menu = document.getElementById("ptv2-sprint-menu");
    if (!menu) return;
    menu.innerHTML = "";
    menu.dataset.sprintId = s.id;
    _sprintMenuAnchor = anchor;

    // Edit (toggles an inline editor row in the menu itself)
    const editBtn = makeMenuBtn("Edit name & dates", "✎");
    editBtn.addEventListener("click", () => {
      renderMenuEditor(menu, s);
      positionSprintMenu(menu, anchor);
    });
    menu.appendChild(editBtn);

    const activeBtn = makeMenuBtn(s.is_active ? "Mark as inactive" : "Mark as active",
                                  s.is_active ? "●" : "○");
    activeBtn.addEventListener("click", async () => {
      await updateSprint(s.id, { is_active: !s.is_active });
      closeSprintMenu();
    });
    menu.appendChild(activeBtn);

    menu.appendChild(Object.assign(document.createElement("div"), { className: "sep" }));

    const delBtn = makeMenuBtn(`Delete "${s.name}"`, "🗑");
    delBtn.classList.add("danger");
    delBtn.addEventListener("click", async () => {
      const ok = await ptv2Confirm({
        title: `Delete sprint "${s.name}"?`,
        body: "Tasks keep their pointer — you can restore the sprint later from Supabase.",
        okLabel: "Delete",
        danger: true,
      });
      if (!ok) return;
      await deleteSprint(s.id);
      closeSprintMenu();
    });
    menu.appendChild(delBtn);

    menu.hidden = false;
    positionSprintMenu(menu, anchor);
  }
  function positionSprintMenu(menu, anchor) {
    // Run after layout settles so offsetWidth/Height reflect new contents.
    requestAnimationFrame(() => {
      const rect = anchor.getBoundingClientRect();
      const mw = menu.offsetWidth;
      const mh = menu.offsetHeight;
      let left = rect.right - mw + window.scrollX;
      if (left < 8) left = 8;
      // Prefer below; flip above only if there's more room there.
      const spaceBelow = window.innerHeight - rect.bottom - 8;
      const spaceAbove = rect.top - 8;
      let top;
      if (mh <= spaceBelow || spaceBelow >= spaceAbove) {
        top = rect.bottom + 6 + window.scrollY;
      } else {
        top = Math.max(8 + window.scrollY, rect.top - mh - 6 + window.scrollY);
      }
      menu.style.left = `${left}px`;
      menu.style.top  = `${top}px`;
    });
  }
  function closeSprintMenu() {
    const menu = document.getElementById("ptv2-sprint-menu");
    if (menu) menu.hidden = true;
  }
  function makeMenuBtn(label, icon) {
    const b = document.createElement("button");
    b.type = "button";
    b.innerHTML = `<span style="opacity:0.6;width:16px;text-align:center">${icon}</span><span>${esc(label)}</span>`;
    return b;
  }
  function renderMenuEditor(menu, s) {
    // Replace the menu body with an inline editor for this sprint.
    menu.innerHTML = "";
    const row = document.createElement("div");
    row.className = "sm-row editor";
    row.innerHTML = `
      <input type="text" name="name" value="${esc(s.name)}" maxlength="80" placeholder="Name">
      <input type="date" name="starts_on" value="${esc(s.starts_on || '')}">
      <input type="date" name="ends_on"   value="${esc(s.ends_on   || '')}">
      <div class="sm-actions">
        <button type="button" data-action="cancel" style="background:transparent;border:1px solid var(--ptv2-border);color:var(--ptv2-text-mute);border-radius:6px;cursor:pointer">Cancel</button>
        <button type="button" data-action="save"   style="background:var(--ptv2-primary);color:#fff;border:0;border-radius:6px;cursor:pointer">Save</button>
      </div>`;
    menu.appendChild(row);
    row.querySelector('[data-action="cancel"]').addEventListener("click", closeSprintMenu);
    const saveBtn = row.querySelector('[data-action="save"]');
    saveBtn.addEventListener("click", async () => {
      const patch = {
        name:      row.querySelector('[name="name"]').value.trim(),
        starts_on: row.querySelector('[name="starts_on"]').value || null,
        ends_on:   row.querySelector('[name="ends_on"]').value || null,
      };
      if (!patch.name) { await ptv2Alert({ title: "Name required", body: "Give the sprint a short name before saving." }); return; }
      saveBtn.disabled = true;
      const ok = await updateSprint(s.id, patch);
      saveBtn.disabled = false;
      if (ok) closeSprintMenu();
    });
  }

  // Click anywhere outside the menu closes it.
  document.addEventListener("click", (e) => {
    const menu = document.getElementById("ptv2-sprint-menu");
    if (!menu || menu.hidden) return;
    if (e.target.closest("#ptv2-sprint-menu")) return;
    if (e.target.closest(".sc-menu")) return;       // own trigger handled separately
    closeSprintMenu();
  });

  // Hide / show task rows by sprint_id. Returns visible count.
  function applySprintFilter() {
    const rows = document.querySelectorAll("#task-tbody tr.task-row");
    rows.forEach((row) => {
      if (!_sprintSel.size) { row.style.removeProperty("display"); return; }
      row.style.display = _sprintSel.has(row.dataset.sprintId) ? "" : "none";
    });
    // Re-render focus/done/tree-tasks since they read from the table.
    if (document.body.dataset.activeTab === "focus") renderFocus();
    if (document.body.dataset.activeTab === "done")  renderDone();
    if (document.body.dataset.activeTab === "tree")  renderTreeTasks();
    updateHeaderCounts();
  }

  function populateSprintPickers() {
    // The add-task picker AND the detail-panel picker.
    const opts = ['<option value="">No sprint</option>']
      .concat(_sprints.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}${s.is_active ? " (active)" : ""}</option>`));
    for (const id of ["add-task-sprint", "sheet-sprint"]) {
      const sel = document.getElementById(id);
      if (!sel) continue;
      const cur = sel.value;
      sel.innerHTML = opts.join("");
      if (cur && sel.querySelector(`option[value="${cur}"]`)) sel.value = cur;
    }
  }

  /* ───── SPRINT TAB ──────────────────────────────────────────── */

  async function renderSprintsTab() {
    const board = document.getElementById("ptv2-sprints-board");
    const empty = document.getElementById("ptv2-sprints-empty");
    if (!board) return;
    if (!_sprints.length) {
      empty.hidden = false;
      board.innerHTML = "";
      setBadge("sprints", 0);
      return;
    }
    empty.hidden = true;
    board.innerHTML = "";
    // Group tasks by sprint_id from the existing DOM.
    const tasksBySprint = new Map();
    for (const s of _sprints) tasksBySprint.set(s.id, []);
    const unassigned = [];
    for (const t of readTasks()) {
      if (t.isDone) continue;
      if (t.sprintId && tasksBySprint.has(t.sprintId)) {
        tasksBySprint.get(t.sprintId).push(t);
      } else {
        unassigned.push(t);
      }
    }
    setBadge("sprints", _sprints.length);

    for (const s of _sprints) {
      board.appendChild(sprintCard(s, tasksBySprint.get(s.id) || []));
    }
    // Drop-zone for "unassigned" so users can drag tasks out of all sprints.
    board.appendChild(sprintCard({ id: null, name: "Unassigned", _virtual: true },
      unassigned, { virtual: true }));
    if (window.feather) window.feather.replace();
    // Stats are async — kick off per-sprint fetches.
    _sprints.forEach((s) => fetchAndRenderSprintStats(s.id));
  }

  function sprintCard(s, tasks, opts = {}) {
    const card = document.createElement("article");
    card.className = "ptv2-sprint-card" + (s.is_active ? " is-active" : "");
    card.dataset.sprintId = s.id || "";
    const dates = s._virtual ? "" : sprintDateLabel(s);
    const activeBadge = s.is_active ? `<span class="badge">Active</span>` : "";
    card.innerHTML = `
      <header>
        <h3>${esc(s.name)}${activeBadge}</h3>
        <span class="dates">${esc(dates)}</span>
        ${s._virtual ? "" : `<button type="button" class="rollover" data-action="rollover">Roll over →</button>`}
      </header>
      ${s._virtual ? "" : `
        <div class="ptv2-sprint-progress">
          <span class="nums" data-stats>0 / 0 · 0%</span>
          <div class="bar"><span class="fill" style="width:0%"></span></div>
          <svg class="spark" width="100" height="20" viewBox="0 0 100 20" aria-hidden="true"
               style="opacity:0.6"></svg>
        </div>`}
      <div class="ptv2-sprint-tasks" data-tasks></div>`;

    // Render tasks
    const taskWrap = card.querySelector("[data-tasks]");
    tasks.forEach((t) => {
      const tile = rowCard(t, { crumb: crumbFor(t) });
      tile.draggable = true;
      tile.addEventListener("dragstart", (e) => {
        try { e.dataTransfer.setData("text/plain", t.id); } catch (_) {}
        e.dataTransfer.effectAllowed = "move";
        card.classList.add("is-source");
      });
      tile.addEventListener("dragend", () => card.classList.remove("is-source"));
      taskWrap.appendChild(tile);
    });

    // Make whole card a drop target.
    card.addEventListener("dragover", (e) => {
      if (!e.dataTransfer.types.includes("text/plain")) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      card.classList.add("is-drop-target");
    });
    card.addEventListener("dragleave", (e) => {
      // Only clear when leaving the card itself, not children.
      if (e.target === card) card.classList.remove("is-drop-target");
    });
    card.addEventListener("drop", async (e) => {
      e.preventDefault();
      card.classList.remove("is-drop-target");
      const taskId = (e.dataTransfer.getData("text/plain") || "").trim();
      if (!taskId) return;
      const targetSprint = s.id || null;
      try {
        const r = await _fetch(`/projects/tasks/${taskId}/update`, {
          method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
          credentials: "same-origin",
          body: JSON.stringify({ sprint_id: targetSprint || "" }),
        });
        if (!r.ok) throw new Error("update failed");
        // Patch the DOM data-attr so re-render picks up the change.
        const row = document.querySelector(`#task-tbody tr.task-row[data-id="${taskId}"]`);
        if (row) row.dataset.sprintId = targetSprint || "";
        renderSprintsTab();
        renderSprintsBar();
      } catch (err) { console.error("[ptv2] sprint move failed", err); }
    });

    // Rollover handler
    card.querySelector('[data-action="rollover"]')?.addEventListener("click", () => promptRollover(s));

    return card;
  }

  function sprintDateLabel(s) {
    if (s.starts_on && s.ends_on) return `${s.starts_on} → ${s.ends_on}`;
    if (s.starts_on) return `from ${s.starts_on}`;
    if (s.ends_on)   return `due ${s.ends_on}`;
    return "no dates";
  }

  function csrf() {
    return document.querySelector('meta[name="csrf-token"]')?.content || "";
  }

  async function fetchAndRenderSprintStats(sprintId) {
    try {
      const r = await fetch(`/api/sprints/${sprintId}/stats`, { credentials: "same-origin" });
      if (!r.ok) return;
      const j = await r.json();
      const card = document.querySelector(`.ptv2-sprint-card[data-sprint-id="${sprintId}"]`);
      if (!card) return;
      const nums = card.querySelector("[data-stats]");
      const fill = card.querySelector(".ptv2-sprint-progress .fill");
      const spark = card.querySelector("svg.spark");
      const pct = Math.round((j.pct || 0) * 100);
      if (nums) nums.textContent = `${j.done} / ${j.total} · ${pct}%`;
      if (fill) fill.style.width = `${pct}%`;
      // A sprint with both dates gets a real burndown over its own days;
      // without dates there is no "ideal", so the 14-day bars remain.
      if (spark && j.burndown) renderBurndown(spark, j.burndown);
      else if (spark && j.by_day) renderSparkline(spark, j.by_day);
    } catch (_) {}
  }

  function renderBurndown(svg, bd) {
    // 100x20 viewBox. Dashed line = ideal (total → 0 on the last day);
    // solid line = tasks still open at the end of each day, up to today.
    svg.innerHTML = "";
    const NS = "http://www.w3.org/2000/svg";
    const days = bd.days || [];
    const n = Math.max(1, days.length - 1);
    const max = Math.max(1, bd.total || 0);
    const xy = (i, v) => `${(i / n * 100).toFixed(2)},${(19 - (v / max) * 18).toFixed(2)}`;
    const ideal = document.createElementNS(NS, "polyline");
    ideal.setAttribute("points", days.map((d, i) => xy(i, d.ideal)).join(" "));
    ideal.setAttribute("fill", "none");
    ideal.setAttribute("stroke", "var(--color-text-muted, #5b5e66)");
    ideal.setAttribute("stroke-width", "1");
    ideal.setAttribute("stroke-dasharray", "2 2");
    svg.appendChild(ideal);
    const actual = days.map((d, i) => d.remaining == null ? null : xy(i, d.remaining)).filter(Boolean);
    if (actual.length) {
      const line = document.createElementNS(NS, "polyline");
      line.setAttribute("points", actual.join(" "));
      line.setAttribute("fill", "none");
      line.setAttribute("stroke", "var(--ptv2-primary, currentColor)");
      line.setAttribute("stroke-width", "2");
      line.setAttribute("stroke-linejoin", "round");
      svg.appendChild(line);
    }
    const last = [...days].reverse().find((d) => d.remaining != null);
    const t = document.createElementNS(NS, "title");
    t.textContent = `Burndown ${bd.starts_on} → ${bd.ends_on}: ` +
      (last ? `${last.remaining} of ${bd.total} open on ${last.date}, ideal ${Math.round(last.ideal)}` : "sprint not started");
    svg.appendChild(t);
  }

  function renderSparkline(svg, points) {
    // 100x20 viewBox, 14 buckets -> bar width ~6, gap 1
    svg.innerHTML = "";
    const max = Math.max(1, ...points.map((p) => p.done));
    const barW = 100 / points.length - 1;
    points.forEach((p, i) => {
      const h = (p.done / max) * 18;
      const x = i * (barW + 1);
      const y = 20 - h;
      const r = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      r.setAttribute("x", x.toFixed(2));
      r.setAttribute("y", y.toFixed(2));
      r.setAttribute("width", barW.toFixed(2));
      r.setAttribute("height", Math.max(1, h).toFixed(2));
      r.setAttribute("fill", "var(--ptv2-primary)");
      r.setAttribute("rx", "1");
      r.append(document.createElementNS("http://www.w3.org/2000/svg", "title"));
      r.lastChild.textContent = `${p.date}: ${p.done} done`;
      svg.appendChild(r);
    });
  }

  async function promptRollover(s) {
    const others = _sprints.filter((x) => x.id !== s.id);
    if (!others.length) {
      const ok = await ptv2Confirm({
        title: `Roll over "${s.name}"?`,
        body: "No other sprint to move to. Unfinished tasks will be unassigned.",
        okLabel: "Unassign tasks",
        danger: true,
      });
      if (ok) await rolloverSprint(s.id, null);
      return;
    }
    const back = document.createElement("div");
    back.className = "ptv2-dlg-back";
    const card = document.createElement("div");
    card.className = "ptv2-dlg-card";
    card.innerHTML = `
      <h2 class="ptv2-dlg-title">Roll over "${esc(s.name)}"</h2>
      <div class="ptv2-dlg-body">Move unfinished tasks to:</div>
      <select class="ptv2-dlg-input" id="ptv2-rollover-target">
        <option value="">Unassign (leave as backlog)</option>
        ${others.map((x) => `<option value="${esc(x.id)}">${esc(x.name)}${x.is_active ? " · active" : ""}</option>`).join("")}
      </select>
      <div class="ptv2-dlg-actions">
        <button type="button" class="ptv2-dlg-btn" data-action="cancel">Cancel</button>
        <button type="button" class="ptv2-dlg-btn is-primary" data-action="ok">Roll over</button>
      </div>`;
    back.appendChild(card);
    document.body.appendChild(back);
    const sel = card.querySelector("#ptv2-rollover-target");
    sel.value = (others.find((x) => x.is_active) || others[0]).id;
    requestAnimationFrame(() => sel.focus());
    const cleanup = () => { document.removeEventListener("keydown", onKey, true); back.remove(); };
    const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); cleanup(); } };
    document.addEventListener("keydown", onKey, true);
    back.addEventListener("click", (e) => { if (e.target === back) cleanup(); });
    card.querySelector('[data-action="cancel"]').addEventListener("click", cleanup);
    card.querySelector('[data-action="ok"]').addEventListener("click", async () => {
      const targetId = sel.value || null;
      cleanup();
      await rolloverSprint(s.id, targetId);
    });
  }
  async function rolloverSprint(srcId, targetId) {
    const r = await _fetch(`/api/sprints/${srcId}/rollover`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ target_sprint_id: targetId }),
    });
    if (!r.ok) {
      await ptv2Alert({ title: "Rollover failed", body: `Server returned ${r.status}. Please try again.` });
      return;
    }
    // Update all matching rows' data-sprint-id so the UI reflects without a reload.
    document.querySelectorAll(`#task-tbody tr.task-row[data-sprint-id="${srcId}"]`).forEach((row) => {
      if (row.dataset.status !== "done") row.dataset.sprintId = targetId || "";
    });
    renderSprintsTab();
    renderSprintsBar();
  }

  /* ───── sprint CRUD ─────────────────────────────────────────── */

  // Accepts either a plain string (legacy callers) or {name, starts_on,
  // ends_on, is_active}. Empty name → server auto-numbers "Sprint N".
  async function createSprint(arg) {
    const body = (typeof arg === "string" || arg == null)
      ? { project_id: PROJECT_ID, name: arg || "" }
      : Object.assign({ project_id: PROJECT_ID }, arg);
    const r = await _fetch("/api/sprints", {
      method: "POST", headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    if (r.ok) await refreshSprints();
    else await ptv2Alert({ title: "Couldn't create sprint", body: `Server returned ${r.status}.` });
  }
  async function updateSprint(id, patch) {
    try {
      const r = await _fetch(`/api/sprints/${id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(patch),
      });
      if (!r.ok) {
        let body = `Server returned ${r.status}.`;
        try {
          const j = await r.json();
          if (j && j.error) body = j.error;
        } catch (_) {}
        await ptv2Alert({ title: "Sprint update failed", body });
        return false;
      }
      await refreshSprints();
      return true;
    } catch (e) {
      await ptv2Alert({ title: "Sprint update failed", body: (e && e.message) ? e.message : String(e) });
      return false;
    }
  }
  async function deleteSprint(id) {
    const r = await _fetch(`/api/sprints/${id}`, {
      method: "DELETE", credentials: "same-origin",
    });
    if (r.ok) {
      _sprintSel.delete(id);
      await refreshSprints();
    }
  }
  async function refreshSprints() {
    try {
      const r = await fetch(`/api/projects/${PROJECT_ID}/sprints`, { credentials: "same-origin" });
      const j = await r.json();
      _sprints = j.sprints || [];
      renderSprintsBar();
      populateSprintPickers();
      if (document.body.dataset.activeTab === "sprints") renderSprintsTab();
    } catch (_) {}
  }
  // Expansion state for the nested tree. We keep id Sets per level so
  // a re-render (after a filter toggle, drag-drop, or create) preserves
  // whatever the user already had open. Persisted to sessionStorage so
  // adding a task (which forces a full reload to refresh the task DOM)
  // doesn't collapse the tree back to the top level.
  const _TREE_EXPAND_KEY = "ptv2:treeExpand:" + (typeof PROJECT_ID !== "undefined" ? PROJECT_ID : "");
  const _treeExpand = loadTreeExpand();
  function loadTreeExpand() {
    try {
      const raw = sessionStorage.getItem(_TREE_EXPAND_KEY);
      if (!raw) return { okrs: new Set(), inits: new Set(), epics: new Set() };
      const parsed = JSON.parse(raw);
      return {
        okrs:  new Set(parsed.okrs  || []),
        inits: new Set(parsed.inits || []),
        epics: new Set(parsed.epics || []),
      };
    } catch (_) {
      return { okrs: new Set(), inits: new Set(), epics: new Set() };
    }
  }
  function saveTreeExpand() {
    try {
      sessionStorage.setItem(_TREE_EXPAND_KEY, JSON.stringify({
        okrs:  Array.from(_treeExpand.okrs),
        inits: Array.from(_treeExpand.inits),
        epics: Array.from(_treeExpand.epics),
      }));
    } catch (_) { /* private mode or quota — silently skip */ }
  }

  function renderTree() {
    const host = document.getElementById("ptv2-tree-nested");
    if (!host) return;
    host.innerHTML = "";

    // Top row: "+ New OKR" + active-filter chip (when present). The
    // chip's the only visible indicator that the bottom list is
    // narrowed — without it the empty-filter state would look
    // identical to the "filtered to a node" state.
    const addRow = document.createElement("div");
    addRow.className = "ptv2-tn-add-top";
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "ptv2-tn-add-btn";
    addBtn.textContent = "+ New OKR";
    addBtn.addEventListener("click", () => promptCreateOkr());
    addRow.appendChild(addBtn);
    if (_treeFilter.length) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "ptv2-tn-filter-chip";
      chip.innerHTML = `<span>Filtered: ${esc(filterChipLabel())}</span><span aria-hidden="true">×</span>`;
      chip.title = "Clear filter — show all tasks";
      chip.addEventListener("click", () => { _treeFilter = []; renderTree(); });
      addRow.appendChild(chip);
      // Tiny gesture hint — only when nothing is selected yet would be
      // ideal, but showing it next to the active chip is what surfaces
      // the multi-select capability at the moment users are most
      // likely to discover it.
      const hint = document.createElement("span");
      hint.className = "ptv2-tn-filter-hint";
      hint.textContent = "Shift+click or long-press to add";
      addRow.appendChild(hint);
    }
    host.appendChild(addRow);

    if (!_treeData.length) {
      const e = document.createElement("div");
      e.className = "ptv2-tn-empty";
      e.textContent = "No OKRs yet. Click + New OKR to get started.";
      host.appendChild(e);
      renderTreeTasks();
      return;
    }

    for (const o of _treeData) host.appendChild(buildOkrNode(o));

    renderTreeTasks();
    if (window.feather) window.feather.replace();
  }

  function buildOkrNode(o) {
    const wrap = document.createElement("div");
    wrap.className = "ptv2-tn-node";
    // Initiatives live under KRs; flatten to a single list keyed by
    // their parent KR so the user doesn't see an extra (often empty)
    // level for KRs they don't manage manually.
    const inits = [];
    for (const kr of o.key_results || [])
      for (const it of kr.initiatives || []) inits.push({ it, kr });
    const epCt = inits.reduce((n, { it }) => n + (it.epics || []).length, 0);
    const expanded = _treeExpand.okrs.has(o.id);
    // Branch nodes (OKR/Init/Epic) always show the chevron — even with
    // zero children — so users can expand to see the inline "+ Add"
    // button. Defaults are read-only catch-alls, so no chevron.
    const canExpand = !o.is_default;
    const row = buildTreeRow({
      level: 0, kind: "okr", icon: "O",
      label: o.title, isDefault: !!o.is_default,
      meta: `${inits.length} init · ${epCt} epic`,
      hasChildren: canExpand,
      expanded,
      selected: isTreeFilterTarget("okr", o.id),
      onToggleExpand: () => {
        toggleSet(_treeExpand.okrs, o.id);
        renderTree();
      },
      onRowSelect: (opts) => setTreeFilter("okr", o.id, opts),
      onEdit:   o.is_default ? null : () => editOkr(o),
      onDelete: o.is_default ? null : () => deleteOkr(o),
    });
    wrap.appendChild(row);

    if (expanded) {
      for (const { it, kr } of inits) wrap.appendChild(buildInitNode(it, kr, o));
      // Inline creator under this OKR — pre-scopes the KR picker.
      wrap.appendChild(inlineAddBtn({
        level: 1, label: "+ Initiative",
        onClick: () => promptCreateInitiativeForOkr(o),
      }));
    }
    return wrap;
  }

  function buildInitNode(it, kr, o) {
    const wrap = document.createElement("div");
    wrap.className = "ptv2-tn-node";
    const epics = it.epics || [];
    // "Loose" tasks: tagged to this initiative but either no epic_id
    // OR an epic_id that no longer exists in the tree (e.g. its epic
    // was soft-deleted). Either way they'd be invisible without this
    // bucket. Drag onto any visible epic above to reattach.
    const looseTasks = readTasks().filter((t) => {
      if (t.isDone || t.initiativeId !== it.id) return false;
      if (!t.epicId) return true;
      return !(_hierIndex && _hierIndex.epicsById && _hierIndex.epicsById.has(t.epicId));
    });
    const expanded = _treeExpand.inits.has(it.id);
    const canExpand = !it.is_default;
    const metaParts = [`${epics.length} epic`];
    if (looseTasks.length) metaParts.push(`${looseTasks.length} loose`);
    const row = buildTreeRow({
      level: 1, kind: "init", icon: "I",
      label: it.title, isDefault: !!it.is_default,
      meta: metaParts.join(" · "),
      sub: `KR: ${kr.title}`,
      hasChildren: canExpand,
      expanded,
      selected: isTreeFilterTarget("init", it.id),
      onToggleExpand: () => {
        toggleSet(_treeExpand.inits, it.id);
        renderTree();
      },
      onRowSelect: (opts) => setTreeFilter("init", it.id, opts),
      onEdit:   it.is_default ? null : () => editInitiative(it, o),
      onDelete: it.is_default ? null : () => deleteInitiative(it),
    });
    wrap.appendChild(row);

    if (expanded) {
      for (const ep of epics) wrap.appendChild(buildEpicNode(ep, it, kr, o));
      if (looseTasks.length) {
        // Tiny separator label so users can tell these aren't in an epic.
        const heading = document.createElement("div");
        heading.className = "ptv2-tn-loose-heading";
        heading.style.setProperty("--ptv2-tn-indent", `${2 * 18}px`);
        heading.textContent = `Loose tasks (drag into an epic above)`;
        wrap.appendChild(heading);
        for (const t of looseTasks) wrap.appendChild(buildTaskNode(t));
      }
      if (!it.is_default) {
        wrap.appendChild(inlineAddBtn({
          level: 2, label: "+ Epic",
          onClick: () => promptCreateEpicForInit(it),
        }));
      }
    }
    return wrap;
  }

  function buildEpicNode(ep, it, kr, o) {
    const wrap = document.createElement("div");
    wrap.className = "ptv2-tn-node";
    const tasks = readTasks().filter((t) => t.epicId === ep.id && !t.isDone);
    const expanded = _treeExpand.epics.has(ep.id);
    // Epics can always be expanded (to drop tasks in, or to see them);
    // chevron stays visible even before the first task is added.
    const row = buildTreeRow({
      level: 2, kind: "epic", icon: "E",
      label: ep.title, isDefault: !!ep.is_default,
      meta: tasks.length ? `${tasks.length} task${tasks.length === 1 ? "" : "s"}` : "",
      sub: ep.description ? ep.description.slice(0, 80) : null,
      hasChildren: true,
      expanded,
      selected: isTreeFilterTarget("epic", ep.id),
      onToggleExpand: () => {
        toggleSet(_treeExpand.epics, ep.id);
        renderTree();
      },
      onRowSelect: (opts) => setTreeFilter("epic", ep.id, opts),
      onEdit:   ep.is_default ? null : () => editEpic(ep, it),
      onDelete: ep.is_default ? null : () => deleteEpic(ep, it),
      dropTarget: { type: "epic", epic: ep },
    });
    wrap.appendChild(row);

    if (expanded) {
      for (const t of tasks) wrap.appendChild(buildTaskNode(t));
      // Inline "+ Task" under every epic (including defaults — they're
      // a valid catch-all bucket for quick adds). Drops the new task
      // straight into this epic without making the user touch the
      // bottom add-bar's epic picker.
      wrap.appendChild(inlineAddBtn({
        level: 3, label: "+ Task",
        onClick: () => promptCreateTaskForEpic(ep),
      }));
    }
    return wrap;
  }

  function buildTaskNode(t) {
    // Tasks are leaves: no chevron, no filter selection. The done
    // checkbox stays (it's a state, not a filter) — clicking it
    // mirrors the legacy task-row checkbox so server + recurrence +
    // optimistic UI all behave the same.
    const row = buildTreeRow({
      level: 3, kind: "task",
      label: t.title || "(untitled)",
      meta: t.dueLabel || "",
      hasChildren: false,
      expanded: false,
      isTask: true,
      taskDone: t.isDone,
      onToggleExpand: () => {},
      onTaskCheck: () => {
        const cb = t.el.querySelector("input.task-check");
        if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event("change", { bubbles: true })); }
        setTimeout(() => renderTree(), 60);
      },
      onRowClick: () => {
        if (typeof openTaskDetail === "function") openTaskDetail(t.id);
      },
    });
    if (t.isDone) row.classList.add("is-done");
    // Intentionally NOT calling makeTaskDraggable here. draggable=true
    // on a row interferes with normal tap behaviour on touch devices
    // (drag preview flickers, click events get swallowed by dragstart)
    // and clicking the row to open the detail panel started feeling
    // weird as a result. The bottom "Tasks in scope" list still
    // renders every visible task as a drag source, so loose-task
    // reassignment continues to work via that list.
    return row;
  }

  function buildTreeRow(opts) {
    const {
      level, kind, icon, label, sub, meta, isDefault,
      hasChildren, expanded, selected,
      onToggleExpand, onRowSelect, onRowClick,
      onTaskCheck, taskDone,
      onEdit, onDelete,
      dropTarget, isTask,
    } = opts;
    const row = document.createElement("div");
    row.className = `ptv2-tn-row is-${kind}${selected ? " is-selected" : ""}`;
    row.style.setProperty("--ptv2-tn-indent", `${level * 18}px`);

    const chev = document.createElement("button");
    chev.type = "button";
    chev.className = "ptv2-tn-chev" + (!hasChildren ? " is-leaf" : "") + (expanded ? " is-open" : "");
    chev.innerHTML = "▸";
    chev.setAttribute("aria-label", hasChildren ? (expanded ? "Collapse" : "Expand") : "");
    if (hasChildren) {
      chev.addEventListener("click", (e) => { e.stopPropagation(); onToggleExpand(); });
    }
    row.appendChild(chev);

    // Tasks keep a done-state checkbox (state, not filter). Branch
    // nodes have no checkbox — clicking the row sets the filter.
    if (isTask) {
      const check = document.createElement("input");
      check.type = "checkbox";
      check.className = "ptv2-tn-check";
      check.checked = !!taskDone;
      check.addEventListener("click", (e) => e.stopPropagation());
      check.addEventListener("change", () => onTaskCheck && onTaskCheck());
      row.appendChild(check);
    }

    if (icon) {
      const ic = document.createElement("span");
      ic.className = `ptv2-tn-icon is-${kind}` + (isTask && taskDone ? " is-done" : "");
      ic.textContent = icon;
      row.appendChild(ic);
    }

    const main = document.createElement("div");
    main.className = "ptv2-tn-main";
    const labelHtml = `<span class="ptv2-tn-label">${esc(label)}${
      isDefault ? `<span class="ptv2-tn-default-badge" title="Default catch-all">Default</span>` : ""
    }</span>${sub ? `<span class="ptv2-tn-sub">${esc(sub)}</span>` : ""}`;
    main.innerHTML = labelHtml;
    row.appendChild(main);

    if (meta) {
      const m = document.createElement("span");
      m.className = "ptv2-tn-meta";
      m.textContent = meta;
      row.appendChild(m);
    }

    if (onEdit) {
      const ed = document.createElement("button");
      ed.type = "button";
      ed.className = "ptv2-tn-edit";
      ed.title = "Edit";
      ed.setAttribute("aria-label", "Edit");
      ed.innerHTML = "✎";
      ed.addEventListener("click", (e) => { e.stopPropagation(); onEdit(); });
      row.appendChild(ed);
    }
    if (onDelete) {
      const del = document.createElement("button");
      del.type = "button";
      del.className = "ptv2-tn-del";
      del.title = "Delete";
      del.setAttribute("aria-label", "Delete");
      del.innerHTML = "×";
      del.addEventListener("click", (e) => { e.stopPropagation(); onDelete(); });
      row.appendChild(del);
    }

    // Row click semantics:
    //   - Task row → open detail panel.
    //   - Branch row, plain tap → replace the active filter with this row
    //     (or clear it if it's already the only selected scope).
    //   - Branch row, Shift/Ctrl/⌘-click OR long-press → toggle this
    //     row's membership in the existing selection (multi-scope).
    row.addEventListener("click", (e) => {
      if (e.target.closest(".ptv2-tn-chev")) return;
      if (e.target.closest(".ptv2-tn-check")) return;
      if (e.target.closest(".ptv2-tn-edit")) return;
      if (e.target.closest(".ptv2-tn-del")) return;
      if (isTask && onRowClick) { onRowClick(); return; }
      if (onRowSelect) {
        const extend = !!(e.shiftKey || e.ctrlKey || e.metaKey);
        onRowSelect({ extend });
      }
    });
    if (!isTask && onRowSelect) attachLongPressExtend(row, onRowSelect);

    if (dropTarget) attachTreeNodeDropTarget(row, dropTarget);
    return row;
  }

  function inlineAddBtn({ level, label, onClick }) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ptv2-tn-add-btn is-inline";
    b.style.setProperty("--ptv2-tn-indent", `${level * 18 + 28}px`);
    b.textContent = label;
    b.addEventListener("click", onClick);
    return b;
  }
  function toggleSet(set, id) {
    if (set.has(id)) set.delete(id); else set.add(id);
    saveTreeExpand();
  }

  // Long-press → multi-select on touch devices. Mirrors the
  // Shift/Ctrl-click gesture available with a real keyboard. 450ms
  // threshold matches the OS conventions for context-menu long-press,
  // so it doesn't accidentally fire on a normal tap. Cancels on
  // movement > ~10px so a scroll-start doesn't trigger it.
  function attachLongPressExtend(row, onRowSelect) {
    if (!("ontouchstart" in window) && !navigator.maxTouchPoints) return;
    let timer = null, startX = 0, startY = 0, fired = false;
    const cancel = () => {
      if (timer) { clearTimeout(timer); timer = null; }
    };
    row.addEventListener("touchstart", (e) => {
      if (!e.touches || e.touches.length !== 1) return;
      fired = false;
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
      timer = setTimeout(() => {
        fired = true;
        if (navigator.vibrate) { try { navigator.vibrate(8); } catch (_) {} }
        onRowSelect({ extend: true });
      }, 450);
    }, { passive: true });
    row.addEventListener("touchmove", (e) => {
      if (!timer || !e.touches || !e.touches.length) return;
      const dx = e.touches[0].clientX - startX;
      const dy = e.touches[0].clientY - startY;
      if (Math.hypot(dx, dy) > 10) cancel();
    }, { passive: true });
    row.addEventListener("touchend", () => {
      // If the long-press fired, swallow the subsequent click so we
      // don't also replace the selection.
      if (fired) {
        const swallow = (ev) => { ev.stopPropagation(); ev.preventDefault(); };
        row.addEventListener("click", swallow, { capture: true, once: true });
      }
      cancel();
    });
    row.addEventListener("touchcancel", cancel);
  }

  function attachTreeNodeDropTarget(row, dropTarget) {
    row.classList.add("is-droppable");
    row.addEventListener("dragover", (e) => {
      if (!e.dataTransfer || !e.dataTransfer.types.includes("text/plain")) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      row.classList.add("is-drop-target");
    });
    row.addEventListener("dragleave", (e) => {
      if (e.target === row) row.classList.remove("is-drop-target");
    });
    row.addEventListener("drop", async (e) => {
      e.preventDefault();
      row.classList.remove("is-drop-target");
      const taskId = (e.dataTransfer.getData("text/plain") || "").trim();
      if (!taskId) return;
      if (dropTarget.type === "epic") await moveTaskToEpic(taskId, dropTarget.epic);
    });
  }

  async function promptCreateInitiativeForOkr(o) {
    const krs = (o.key_results || []).filter((kr) => !kr.is_default);
    if (!krs.length) {
      await ptv2Alert({
        title: "No Key Results yet",
        body: `Add a Key Result to "${o.title}" before creating Initiatives. (Defaults can't have children.)`,
      });
      return;
    }
    // Default dates to the parent OKR's window so initiatives slot into
    // their OKR's timeline by default. User can edit either field.
    const result = await ptv2Dialog({
      title: "New Initiative",
      body: `Under OKR: ${o.title}`,
      fields: [
        { name: "title",       label: "Title", placeholder: "e.g. Activation funnel", required: true },
        { name: "description", label: "Description (optional)", type: "textarea",
          placeholder: "Scope, success criteria, anything worth remembering." },
        { name: "key_result_id", label: "Key Result", type: "select", value: krs[0].id,
          options: krs.map((kr) => ({ value: kr.id, label: kr.title })) },
        { name: "start_date",  label: "Start date (optional)",  type: "date", value: o.start_date  || "" },
        { name: "target_date", label: "Target date (optional)", type: "date", value: o.target_date || "" },
      ],
      okLabel: "Create",
    });
    if (!result) return;
    const title = (result.title || "").trim();
    if (!title) return;
    const r = await _fetch("/api/initiatives", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        key_result_id: result.key_result_id,
        description:   (result.description || "").trim() || null,
        start_date:    result.start_date  || null,
        target_date:   result.target_date || null,
      }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      await ptv2Alert({ title: "Couldn't create initiative", body: body.error || `Server returned ${r.status}.` });
      return;
    }
    // Auto-expand parent OKR + the brand-new initiative so the user
    // immediately sees the "+ Epic" affordance.
    _treeExpand.okrs.add(o.id);
    const j = await r.json().catch(() => ({}));
    const newId = j && j.initiative && j.initiative.id;
    if (newId) _treeExpand.inits.add(newId);
    await fetchTree(); renderTree();
  }

  /* ───── edit OKR / Initiative / Epic ───────────────────────────
     Same dialog shape as the create flows, pre-filled with the
     current values. PATCHes via the existing /api/{goals,initiatives,
     epics}/<id> endpoints. Tasks have their own existing detail
     panel — click a task row to open it. */
  async function editOkr(o) {
    const result = await ptv2Dialog({
      title: "Edit OKR",
      fields: [
        { name: "title",       label: "Title", value: o.title || "", required: true },
        { name: "description", label: "Description", type: "textarea", value: o.description || "" },
        { name: "time_horizon", label: "Time horizon", type: "select",
          value: o.time_horizon || "quarterly",
          options: [
            { value: "quarterly", label: "Quarterly" },
            { value: "monthly",   label: "Monthly" },
            { value: "annual",    label: "Annual" },
            { value: "ongoing",   label: "Ongoing" },
          ] },
        { name: "status", label: "Status", type: "select", value: o.status || "active",
          options: [
            { value: "active",    label: "Active" },
            { value: "achieved",  label: "Achieved" },
            { value: "paused",    label: "Paused" },
            { value: "abandoned", label: "Abandoned" },
          ] },
        { name: "start_date",  label: "Start date",  type: "date", value: o.start_date  || "" },
        { name: "target_date", label: "Target date", type: "date", value: o.target_date || "" },
      ],
      okLabel: "Save",
    });
    if (!result) return;
    const title = (result.title || "").trim();
    if (!title) return;
    const r = await _fetch(`/api/goals/${o.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        title,
        description:  (result.description || "").trim() || null,
        time_horizon: result.time_horizon,
        status:       result.status,
        start_date:   result.start_date  || null,
        target_date:  result.target_date || null,
      }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      await ptv2Alert({ title: "Couldn't save OKR", body: body.error || `Server returned ${r.status}.` });
      return;
    }
    await fetchTree(); renderTree();
  }
  async function editInitiative(it, o) {
    // KR re-parent isn't supported in this dialog — rare and the
    // server-side cascade rules around defaults make it surprising.
    // To move an initiative to a different KR, edit in Supabase.
    const result = await ptv2Dialog({
      title: "Edit Initiative",
      body: `Under OKR: ${o.title}`,
      fields: [
        { name: "title",       label: "Title", value: it.title || "", required: true },
        { name: "description", label: "Description", type: "textarea", value: it.description || "" },
        { name: "status", label: "Status", type: "select", value: it.status || "active",
          options: [
            { value: "active",    label: "Active" },
            { value: "achieved",  label: "Achieved" },
            { value: "paused",    label: "Paused" },
            { value: "abandoned", label: "Abandoned" },
          ] },
        { name: "start_date",  label: "Start date",  type: "date", value: it.start_date  || "" },
        { name: "target_date", label: "Target date", type: "date", value: it.target_date || "" },
      ],
      okLabel: "Save",
    });
    if (!result) return;
    const title = (result.title || "").trim();
    if (!title) return;
    const r = await _fetch(`/api/initiatives/${it.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        title,
        description: (result.description || "").trim() || null,
        status:      result.status,
        start_date:  result.start_date  || null,
        target_date: result.target_date || null,
      }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      await ptv2Alert({ title: "Couldn't save initiative", body: body.error || `Server returned ${r.status}.` });
      return;
    }
    await fetchTree(); renderTree();
  }
  async function editEpic(ep, it) {
    const result = await ptv2Dialog({
      title: "Edit Epic",
      body: `Under Initiative: ${it.title}`,
      fields: [
        { name: "title",       label: "Title", value: ep.title || "", required: true },
        { name: "description", label: "Description", type: "textarea", value: ep.description || "" },
        { name: "status", label: "Status", type: "select", value: ep.status || "active",
          options: [
            { value: "active",    label: "Active" },
            { value: "achieved",  label: "Achieved" },
            { value: "paused",    label: "Paused" },
            { value: "abandoned", label: "Abandoned" },
          ] },
        { name: "start_date",  label: "Start date",  type: "date", value: ep.start_date  || "" },
        { name: "target_date", label: "Target date", type: "date", value: ep.target_date || "" },
      ],
      okLabel: "Save",
    });
    if (!result) return;
    const title = (result.title || "").trim();
    if (!title) return;
    const r = await _fetch(`/api/epics/${ep.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        title,
        description: (result.description || "").trim() || null,
        status:      result.status,
        start_date:  result.start_date  || null,
        target_date: result.target_date || null,
      }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      await ptv2Alert({ title: "Couldn't save epic", body: body.error || `Server returned ${r.status}.` });
      return;
    }
    await fetchTree(); renderTree();
  }

  /* ───── delete OKR / Initiative / Epic ─────────────────────────
     Soft-deletes via the existing /api/{goals,initiatives,epics}
     DELETE endpoints. OKRs cascade to their KRs and initiatives in
     the server handler. Tasks keep their *_id pointers so a future
     restore relinks them automatically. */
  async function deleteOkr(o) {
    const childCount = (o.key_results || []).reduce(
      (n, kr) => n + (kr.initiatives || []).reduce((m, it) => m + 1 + (it.epics || []).length, 0), 0);
    const ok = await ptv2Confirm({
      title: `Delete OKR "${o.title}"?`,
      body: childCount
        ? `This will also remove ${childCount} initiative${childCount === 1 ? "" : "s"} + epic${childCount === 1 ? "" : "s"} underneath. Tasks keep their pointers so a restore (via Supabase) re-links them.`
        : "No children — restorable from Supabase if you change your mind.",
      okLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    const r = await _fetch(`/api/goals/${o.id}`, { method: "DELETE", credentials: "same-origin" });
    if (!r.ok) {
      await ptv2Alert({ title: "Couldn't delete OKR", body: `Server returned ${r.status}.` });
      return;
    }
    // Drop any stale filter / expansion state pointing at the deleted node.
    _treeFilter = _treeFilter.filter((s) => s.type !== "okr" || s.id !== o.id);
    _treeExpand.okrs.delete(o.id);
    saveTreeExpand();
    await fetchTree(); renderTree();
  }
  async function deleteInitiative(it) {
    const epCount = (it.epics || []).length;
    const ok = await ptv2Confirm({
      title: `Delete initiative "${it.title}"?`,
      body: epCount
        ? `Its ${epCount} epic${epCount === 1 ? "" : "s"} stay in the DB but become orphaned (restorable from Supabase). Tasks keep their pointers.`
        : "Restorable from Supabase if you change your mind.",
      okLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    const r = await _fetch(`/api/initiatives/${it.id}`, { method: "DELETE", credentials: "same-origin" });
    if (!r.ok) {
      await ptv2Alert({ title: "Couldn't delete initiative", body: `Server returned ${r.status}.` });
      return;
    }
    _treeFilter = _treeFilter.filter((s) => s.type !== "init" || s.id !== it.id);
    _treeExpand.inits.delete(it.id);
    saveTreeExpand();
    await fetchTree(); renderTree();
  }
  async function deleteEpic(ep, it) {
    const ok = await ptv2Confirm({
      title: `Delete epic "${ep.title}"?`,
      body: `Tasks under this epic keep their epic_id pointer so a restore (via Supabase) re-links them. They'll show up as "loose" under ${it.title} in the meantime.`,
      okLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    const r = await _fetch(`/api/epics/${ep.id}`, { method: "DELETE", credentials: "same-origin" });
    if (!r.ok) {
      await ptv2Alert({ title: "Couldn't delete epic", body: `Server returned ${r.status}.` });
      return;
    }
    _treeFilter = _treeFilter.filter((s) => s.type !== "epic" || s.id !== ep.id);
    _treeExpand.epics.delete(ep.id);
    saveTreeExpand();
    await fetchTree(); renderTree();
  }

  async function promptCreateTaskForEpic(ep) {
    const result = await ptv2Dialog({
      title: "New Task",
      body: `Under Epic: ${ep.title}`,
      fields: [
        { name: "title",    label: "Task", placeholder: "What needs to happen?", required: true },
        { name: "priority", label: "Priority", type: "select", value: "medium",
          options: [
            { value: "high",   label: "High" },
            { value: "medium", label: "Medium" },
            { value: "low",    label: "Low" },
          ] },
        { name: "due_date", label: "Due date (optional)", type: "date" },
      ],
      okLabel: "Add",
    });
    if (!result) return;
    const title = (result.title || "").trim();
    if (!title) return;
    try {
      const r = await _fetch(`/projects/${PROJECT_ID}/tasks/add-ajax`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        credentials: "same-origin",
        body: JSON.stringify({
          task_text: title,
          priority:  result.priority || "medium",
          due_date:  result.due_date || null,
          epic_id:   ep.id,
        }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        await ptv2Alert({ title: "Couldn't add task", body: body.error || `Server returned ${r.status}.` });
        return;
      }
      // Make sure this epic stays open after the reload so the user
      // sees the task they just added at the bottom of its slot.
      _treeExpand.epics.add(ep.id);
      saveTreeExpand();
      // The legacy add-task path reloads the page so every list (table,
      // focus, done, sprint cards) picks up the new row in one shot.
      // Match that behaviour here instead of trying to inject HTML.
      location.reload();
    } catch (err) {
      await ptv2Alert({ title: "Couldn't add task", body: (err && err.message) || String(err) });
    }
  }

  async function promptCreateEpicForInit(it) {
    const result = await ptv2Dialog({
      title: "New Epic",
      body: `Under Initiative: ${it.title}`,
      fields: [
        { name: "title",       label: "Title", placeholder: "e.g. Landing page rebuild", required: true },
        { name: "description", label: "Description (optional)", type: "textarea",
          placeholder: "What's in scope? Any constraints or dependencies?" },
        { name: "start_date",  label: "Start date (optional)",  type: "date", value: it.start_date  || "" },
        { name: "target_date", label: "Target date (optional)", type: "date", value: it.target_date || "" },
      ],
      okLabel: "Create",
    });
    if (!result) return;
    const title = (result.title || "").trim();
    if (!title) return;
    const r = await _fetch("/api/epics", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title, initiative_id: it.id,
        description: (result.description || "").trim() || null,
        start_date:  result.start_date  || null,
        target_date: result.target_date || null,
      }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      await ptv2Alert({ title: "Couldn't create epic", body: body.error || `Server returned ${r.status}.` });
      return;
    }
    _treeExpand.inits.add(it.id);
    // Auto-expand the new epic so the user sees the empty drop slot
    // (and can immediately drag a task into it, or see tasks they add
    // via the bottom add-bar appear inline).
    const j = await r.json().catch(() => ({}));
    const newId = j && j.epic && j.epic.id;
    if (newId) _treeExpand.epics.add(newId);
    await fetchTree(); renderTree();
  }
  function renderTreeTasks() {
    const list = document.getElementById("list-tree-tasks");
    const cnt = document.getElementById("ct-tree-tasks");
    const hint = document.getElementById("tree-tasks-hint");
    if (!list) return;

    const tasks = readTasks().filter((t) => !t.isDone);
    const visible = tasks.filter((t) => taskMatchesFilter(t));

    list.innerHTML = "";
    visible.forEach((t) => {
      const tile = rowCard(t, { crumb: crumbFor(t) });
      makeTaskDraggable(tile, t);
      list.appendChild(tile);
    });
    if (cnt) cnt.textContent = String(visible.length);
    if (hint) hint.textContent = _treeFilter.length ? `Filtered to ${_treeFilter.length} scope${_treeFilter.length === 1 ? "" : "s"}` : "All tasks in project";
  }

  // A task is visible if ANY selected scope matches it. No selection
  // = everything passes. Per-scope hierarchy walk for OKR-level
  // selections so deeply-linked tasks (epic/init under that OKR) also
  // count, not just tasks tagged at the OKR level.
  function taskMatchesFilter(t) {
    if (!_treeFilter.length) return true;
    return _treeFilter.some((sel) => _taskInScope(t, sel));
  }
  function _taskInScope(t, sel) {
    if (sel.type === "epic") return t.epicId === sel.id;
    if (sel.type === "init") return t.initiativeId === sel.id;
    if (sel.type === "okr") {
      if (t.objectiveId === sel.id) return true;
      const idx = _hierIndex;
      if (!idx) return false;
      const epIdx = t.epicId ? idx.epicsById.get(t.epicId) : null;
      if (epIdx && epIdx._okr && epIdx._okr.id === sel.id) return true;
      const itIdx = t.initiativeId ? idx.initiativesById.get(t.initiativeId) : null;
      if (itIdx && itIdx._okr && itIdx._okr.id === sel.id) return true;
      return false;
    }
    return true;
  }
  function setTreeFilter(type, id, opts) {
    const extend = !!(opts && opts.extend);
    const idx = _treeFilter.findIndex((s) => s.type === type && s.id === id);
    if (extend) {
      // Power gesture: toggle this row in/out of the existing set.
      if (idx >= 0) _treeFilter.splice(idx, 1);
      else          _treeFilter.push({ type, id });
    } else {
      // Default tap: if it's already the only selection, clear it.
      // Otherwise replace the entire selection with just this row.
      if (idx >= 0 && _treeFilter.length === 1) _treeFilter = [];
      else                                      _treeFilter = [{ type, id }];
    }
    renderTree();
  }
  function isTreeFilterTarget(type, id) {
    return _treeFilter.some((s) => s.type === type && s.id === id);
  }
  function filterChipLabel() {
    if (!_treeFilter.length) return "";
    if (_treeFilter.length === 1) {
      const sel = _treeFilter[0];
      const idx = _hierIndex;
      if (!idx) return sel.type;
      if (sel.type === "okr")  return idx.objectivesById.get(sel.id)?.title  || "OKR";
      if (sel.type === "init") return idx.initiativesById.get(sel.id)?.title || "Initiative";
      if (sel.type === "epic") return idx.epicsById.get(sel.id)?.title       || "Epic";
      return sel.type;
    }
    // Multi: summarise as counts per level — readable at a glance and
    // doesn't blow out the chip width with long titles.
    const counts = { okr: 0, init: 0, epic: 0 };
    for (const s of _treeFilter) counts[s.type]++;
    const parts = [];
    if (counts.okr)  parts.push(`${counts.okr} OKR${counts.okr  === 1 ? "" : "s"}`);
    if (counts.init) parts.push(`${counts.init} Init${counts.init === 1 ? "" : "s"}`);
    if (counts.epic) parts.push(`${counts.epic} Epic${counts.epic === 1 ? "" : "s"}`);
    return parts.join(" · ");
  }

  /* ───── drag-and-drop: tasks onto epics (Tree tab) ────────────
     A task tile becomes a drag source; epic rows in the right column
     become drop targets. On drop we PATCH the task's epic_id and
     also set initiative_id / key_result_id from the epic's parents
     so the hierarchy stays consistent (instead of an epic-only edit
     that leaves the task pointing at a stale initiative). */
  function makeTaskDraggable(tile, t) {
    tile.draggable = true;
    tile.addEventListener("dragstart", (e) => {
      try { e.dataTransfer.setData("text/plain", t.id); } catch (_) {}
      e.dataTransfer.effectAllowed = "move";
      tile.classList.add("is-dragging");
      document.body.classList.add("ptv2-dragging-task");
    });
    tile.addEventListener("dragend", () => {
      tile.classList.remove("is-dragging");
      document.body.classList.remove("ptv2-dragging-task");
    });
  }
  async function moveTaskToEpic(taskId, epic) {
    if (!epic || !epic.id) return;
    // Pull parent IDs from the indexed hierarchy so the row's tree
    // position is fully consistent after the move.
    const idx = _hierIndex && _hierIndex.epicsById.get(epic.id);
    const initiativeId = (idx && idx._init && idx._init.id) || epic.initiative_id || "";
    const keyResultId  = (idx && idx._kr  && idx._kr.id)  || "";
    try {
      const r = await _fetch(`/projects/tasks/${taskId}/update`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        credentials: "same-origin",
        body: JSON.stringify({
          epic_id: epic.id,
          initiative_id: initiativeId,
          key_result_id: keyResultId,
        }),
      });
      if (!r.ok) throw new Error(`status ${r.status}`);
      // Patch the source task row so subsequent renders (crumb, filter,
      // counts) reflect the new placement without a full page reload.
      const row = document.querySelector(`#task-tbody tr.task-row[data-id="${taskId}"]`);
      if (row) {
        row.dataset.epicId = epic.id;
        if (initiativeId) row.dataset.initiativeId = initiativeId;
        if (keyResultId)  row.dataset.krId         = keyResultId;
      }
      renderTreeTasks();
    } catch (err) {
      console.error("[ptv2] task → epic move failed", err);
      await ptv2Alert({ title: "Move failed", body: "Couldn't reassign this task. Please try again." });
    }
  }
  async function promptCreateOkr() {
    // Default dates = current quarter (start = today, target = end of
    // quarter) so a one-tap save still produces a bounded quarterly OKR.
    // Users can edit either field before saving.
    const today = new Date();
    const qEnd = new Date(today.getFullYear(), Math.floor(today.getMonth() / 3) * 3 + 3, 0);
    const isoDate = (d) => d.toISOString().slice(0, 10);
    const result = await ptv2Dialog({
      title: "New OKR",
      fields: [
        { name: "title",       label: "OKR title", placeholder: "e.g. Grow weekly active users", required: true },
        { name: "description", label: "Description (optional)", type: "textarea",
          placeholder: "What's the why? Who benefits? What does success look like?" },
        { name: "time_horizon", label: "Time horizon", type: "select", value: "quarterly",
          options: [
            { value: "quarterly", label: "Quarterly" },
            { value: "monthly",   label: "Monthly" },
            { value: "annual",    label: "Annual" },
            { value: "ongoing",   label: "Ongoing" },
          ] },
        { name: "start_date",  label: "Start date",  type: "date", value: isoDate(today) },
        { name: "target_date", label: "Target date", type: "date", value: isoDate(qEnd) },
        { name: "krTitle",     label: "First Key Result", required: true,
          placeholder: "e.g. WAU 12k → 18k by Mar 31" },
      ],
      okLabel: "Create",
    });
    if (!result) return;
    const title   = (result.title   || "").trim();
    const krTitle = (result.krTitle || "").trim();
    // Dialog enforces required via HTML5 validation, but guard server-
    // side too: an OKR with no KR is unmeasurable, which is the whole
    // point of the K in OKR. Belt + suspenders so a future refactor
    // can't silently slip a KR-less objective in.
    if (!title || !krTitle) return;
    try {
      const r = await _fetch("/api/goals", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title, project_id: PROJECT_ID, status: "active",
          description:  (result.description  || "").trim() || null,
          time_horizon: result.time_horizon || "quarterly",
          start_date:   result.start_date   || null,
          target_date:  result.target_date  || null,
        }),
      });
      const data = await r.json();
      const obj = data.objective || data;
      if (obj && obj.id) {
        await _fetch("/api/key-results", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: krTitle, objective_id: obj.id,
            target_value: 100, unit: "%",
          }),
        });
      }
      await fetchTree(); renderTree();
    } catch (e) {
      await ptv2Alert({ title: "Couldn't create OKR", body: "Check your connection and try again." });
    }
  }

  /* ───── ⋯ menu, density, add-bar expand, header counts ──────── */

  function ptv2CloseMenu() {
    const pop = document.getElementById("ptv2-menu-pop");
    if (pop) pop.hidden = true;
  }
  window.ptv2CloseMenu = ptv2CloseMenu;
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("#ptv2-menu");
    const pop = document.getElementById("ptv2-menu-pop");
    if (btn && pop) { pop.hidden = !pop.hidden; e.stopPropagation(); return; }
    if (pop && !pop.hidden && !e.target.closest("#ptv2-menu-pop")) pop.hidden = true;
  });

  const DENSITIES = ["comfortable", "cozy", "compact"];
  function getDensity() { return localStorage.getItem("ptv2-density") || "cozy"; }
  function applyDensity(d) {
    document.documentElement.setAttribute("data-density", d);
    const lbl = document.getElementById("ptv2-density-label");
    if (lbl) lbl.textContent = d;
  }
  window.ptv2CycleDensity = function () {
    const cur = getDensity();
    const next = DENSITIES[(DENSITIES.indexOf(cur) + 1) % DENSITIES.length];
    localStorage.setItem("ptv2-density", next);
    applyDensity(next);
  };

  const addToggle = document.getElementById("ptv2-add-toggle");
  const addMore   = document.getElementById("ptv2-add-more");
  if (addToggle && addMore) {
    addToggle.addEventListener("click", () => {
      const open = addMore.hidden;
      addMore.hidden = !open;
      addToggle.setAttribute("aria-expanded", String(open));
    });
  }

  function setBadge(name, n) {
    const el = document.getElementById(`badge-${name}`);
    if (!el) return;
    if (n > 0) { el.textContent = String(n); }
    else el.textContent = "";
  }
  function updateHeaderCounts() {
    const all = readTasks();
    const done = all.filter((t) => t.isDone).length;
    const overdue = all.filter((t) => !t.isDone && t.dueOverdue).length;
    const total = all.length;
    const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = String(v); };
    setText("stat-done", done);
    setText("stat-total", total);
    setText("stat-overdue", overdue);
    const fill = document.getElementById("proj-progress-fill");
    if (fill) fill.style.width = total ? `${Math.round((done / total) * 100)}%` : "0%";
    setBadge("all", total - done);
  }

  /* ───── in-app dialog (replaces native alert/confirm/prompt) ──
     Returns a Promise:
       - alert/confirm with no fields → resolves true (OK) or false (Cancel)
       - with fields → resolves to a {name: value, ...} object or null
     Escape cancels, Enter submits, the first input gets focus.
     Built ad-hoc here so the project_tasks page stays self-contained;
     the styling matches the rest of ptv2 via the existing CSS vars. */
  function ptv2Dialog(opts) {
    return new Promise((resolve) => {
      const {
        title = "",
        body = "",
        fields = [],
        okLabel = fields.length ? "Save" : "OK",
        cancelLabel = "Cancel",
        showCancel = true,
        danger = false,
      } = opts || {};

      const back = document.createElement("div");
      back.className = "ptv2-dlg-back";

      const card = document.createElement("div");
      card.className = "ptv2-dlg-card";
      card.setAttribute("role", "dialog");
      card.setAttribute("aria-modal", "true");

      const fieldsHtml = fields.map((f, i) => {
        const label = f.label ? `<label class="ptv2-dlg-label" for="ptv2-dlg-f-${i}">${esc(f.label)}</label>` : "";
        const type = f.type || "text";
        const val  = esc(f.value || "");
        const ph   = esc(f.placeholder || "");
        const req  = f.required ? "required" : "";
        if (type === "textarea") {
          return `${label}<textarea id="ptv2-dlg-f-${i}" name="${esc(f.name)}" placeholder="${ph}" ${req} rows="3" class="ptv2-dlg-input">${val}</textarea>`;
        }
        if (type === "select") {
          const opts = (f.options || []).map((o) =>
            `<option value="${esc(o.value)}"${String(o.value) === String(f.value || "") ? " selected" : ""}>${esc(o.label)}</option>`
          ).join("");
          return `${label}<select id="ptv2-dlg-f-${i}" name="${esc(f.name)}" class="ptv2-dlg-input">${opts}</select>`;
        }
        return `${label}<input id="ptv2-dlg-f-${i}" type="${esc(type)}" name="${esc(f.name)}" value="${val}" placeholder="${ph}" ${req} class="ptv2-dlg-input">`;
      }).join("");

      card.innerHTML = `
        ${title ? `<h2 class="ptv2-dlg-title">${esc(title)}</h2>` : ""}
        ${body  ? `<div class="ptv2-dlg-body">${esc(body)}</div>` : ""}
        ${fields.length ? `<form class="ptv2-dlg-form" novalidate>${fieldsHtml}</form>` : ""}
        <div class="ptv2-dlg-actions">
          ${showCancel ? `<button type="button" class="ptv2-dlg-btn" data-action="cancel">${esc(cancelLabel)}</button>` : ""}
          <button type="button" class="ptv2-dlg-btn ${danger ? "is-danger" : "is-primary"}" data-action="ok">${esc(okLabel)}</button>
        </div>`;

      back.appendChild(card);
      document.body.appendChild(back);

      const form = card.querySelector(".ptv2-dlg-form");
      const inputs = card.querySelectorAll(".ptv2-dlg-input");
      const okBtn  = card.querySelector('[data-action="ok"]');
      const cnBtn  = card.querySelector('[data-action="cancel"]');

      function close(result) {
        document.removeEventListener("keydown", onKey, true);
        back.remove();
        resolve(result);
      }
      function readFields() {
        const out = {};
        for (const inp of inputs) out[inp.name] = inp.value;
        return out;
      }
      function submit() {
        if (!fields.length) return close(true);
        // Native required-check so the browser shows the standard hint
        // on the first missing field instead of us reinventing it.
        if (form && !form.checkValidity()) { form.reportValidity(); return; }
        close(readFields());
      }
      function cancel() { close(fields.length ? null : false); }

      okBtn.addEventListener("click", submit);
      if (cnBtn) cnBtn.addEventListener("click", cancel);
      back.addEventListener("click", (e) => { if (e.target === back) cancel(); });
      if (form) form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });

      function onKey(e) {
        if (e.key === "Escape") { e.preventDefault(); cancel(); }
        // Enter inside single-line inputs submits; let textareas keep newlines.
        if (e.key === "Enter" && !e.shiftKey) {
          const t = e.target;
          if (!t || t.tagName !== "TEXTAREA") { e.preventDefault(); submit(); }
        }
      }
      document.addEventListener("keydown", onKey, true);

      // Focus first input or the primary button.
      requestAnimationFrame(() => {
        const first = card.querySelector(".ptv2-dlg-input");
        (first || okBtn).focus();
        if (first && first.select) first.select();
      });
    });
  }
  function ptv2Confirm({ title, body, okLabel = "Confirm", cancelLabel = "Cancel", danger = false }) {
    return ptv2Dialog({ title, body, okLabel, cancelLabel, danger });
  }
  function ptv2Alert({ title = "", body = "" }) {
    return ptv2Dialog({ title, body, okLabel: "OK", showCancel: false });
  }

  /* ───── helpers ─────────────────────────────────────────────── */

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /* ───── boot ─────────────────────────────────────────────────── */

  document.addEventListener("DOMContentLoaded", async () => {
    applyDensity(getDensity());
    updateHeaderCounts();
    await fetchTree();        // hierarchy + sprints in one round trip
    setTab(activeTab(), { skipHash: true });

    if (window.feather) window.feather.replace();
  });

  // Re-render after server-driven re-renders that the existing code
  // might trigger (e.g., status changes, bulk updates).
  const obs = new MutationObserver(() => {
    updateHeaderCounts();
    if (document.body.dataset.activeTab === "focus") renderFocus();
    if (document.body.dataset.activeTab === "done")  renderDone();
    if (document.body.dataset.activeTab === "tree")  renderTreeTasks();
  });
  const tbody = document.getElementById("task-tbody");
  if (tbody) obs.observe(tbody, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "data-status"] });
})();
