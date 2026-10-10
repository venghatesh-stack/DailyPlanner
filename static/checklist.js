/* Checklist page — renders grouped items, handles tick/edit, talks to
   /api/checklist/* endpoints. Web Push UI is driven by push.js (loaded
   before this file) which exposes window.ClPush. */

(function () {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const TIME_BUCKETS = [
    { key: "morning",   label: "Morning"   },
    { key: "afternoon", label: "Afternoon" },
    { key: "evening",   label: "Evening"   },
    { key: "anytime",   label: "Anytime"   },
  ];
  const TIME_ORDER = { morning: 0, afternoon: 1, evening: 2, anytime: 3 };

  const state = {
    items: [],
    knownGroups: [],
    // Working list of HH:MM strings while the edit modal is open. Saved
    // to the server as `reminder_times` on submit.
    modalTimes: [],
  };

  // ── Sorting ───────────────────────────────────────
  // Order rule (inside any bucket we render):
  //   1. time_of_day: morning → afternoon → evening → anytime
  //   2. reminder_time ascending (items without a time go last)
  //   3. position (drag-reorder respected)
  //   4. name (stable tiebreak)
  function _itemSortKey(it) {
    const tod = TIME_ORDER[it.time_of_day] ?? 9;
    const rt = it.reminder_time ? it.reminder_time : "zz:zz"; // pushes blanks to end
    const pos = it.position ?? 9999;
    return [tod, rt, pos, (it.name || "").toLowerCase()];
  }
  function sortItems(arr) {
    return [...arr].sort((a, b) => {
      const ka = _itemSortKey(a);
      const kb = _itemSortKey(b);
      for (let i = 0; i < ka.length; i++) {
        if (ka[i] < kb[i]) return -1;
        if (ka[i] > kb[i]) return 1;
      }
      return 0;
    });
  }

  // ── API helpers ───────────────────────────────────
  // Route through dpFetch so mutating requests queue offline and the
  // SW replays them on reconnect. Falls back to plain fetch when
  // sync-queue.js hasn't loaded yet (early page hydration).
  const _fetch = (window.dpFetch) || ((u, o) => fetch(u, o));
  async function api(path, opts = {}) {
    const res = await _fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || `HTTP ${res.status}`);
    }
    // Surface queued status so callers can show "saved offline" UX.
    const body = await res.json().catch(() => ({}));
    if (res._queued) body.queued = true;
    return body;
  }

  // ── Render ────────────────────────────────────────
  function render() {
    const container = $("#cl-groups");
    container.innerHTML = "";

    if (!state.items.length) {
      container.innerHTML = `<div class="cl-empty">No items yet. Tap + to add one.</div>`;
      return;
    }

    // If ANY item has a user-defined group, primary-group by that.
    // Otherwise fall back to time-of-day buckets (the old layout).
    const anyGroup = state.items.some((it) => (it.group_name || "").trim());

    if (anyGroup) {
      renderByGroup(container);
    } else {
      renderByTimeOfDay(container);
    }
  }

  function renderByGroup(container) {
    const buckets = new Map();
    for (const it of state.items) {
      const key = (it.group_name || "").trim() || "__ungrouped";
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(it);
    }
    // Sort group names alphabetically, ungrouped last.
    const keys = [...buckets.keys()].sort((a, b) => {
      if (a === "__ungrouped") return 1;
      if (b === "__ungrouped") return -1;
      return a.localeCompare(b);
    });

    for (const key of keys) {
      const label = key === "__ungrouped" ? "Ungrouped" : key;
      const section = document.createElement("div");
      section.innerHTML = `<div class="cl-group-title">${label}</div>
                           <div class="cl-list" data-group="${label}"></div>`;
      const list = section.querySelector(".cl-list");
      for (const it of sortItems(buckets.get(key))) list.appendChild(itemEl(it));
      container.appendChild(section);
    }
  }

  function renderByTimeOfDay(container) {
    const byTime = {};
    for (const b of TIME_BUCKETS) byTime[b.key] = [];
    for (const it of state.items) {
      const k = byTime[it.time_of_day] ? it.time_of_day : "anytime";
      byTime[k].push(it);
    }
    for (const b of TIME_BUCKETS) {
      const items = byTime[b.key];
      if (!items.length) continue;
      const section = document.createElement("div");
      section.innerHTML = `<div class="cl-group-title">${b.label}</div>
                           <div class="cl-list" data-group="${b.key}"></div>`;
      const list = section.querySelector(".cl-list");
      for (const it of sortItems(items)) list.appendChild(itemEl(it));
      container.appendChild(section);
    }
  }

  function itemEl(it) {
    const row = document.createElement("div");
    row.className = "cl-item" + (it.ticked ? " is-ticked" : "");
    row.dataset.id = it.id;

    const times = Array.isArray(it.reminder_times) ? it.reminder_times : [];
    const hasMulti = times.length > 1;

    const meta = [];
    // Show the single-time badge only when there's exactly one reminder
    // — multi-reminder items show their times as individual tick pills below.
    if (!hasMulti && it.reminder_time) {
      meta.push(`<span class="cl-meta-badge">⏰ ${it.reminder_time}</span>`);
    }
    if (it.time_of_day && it.time_of_day !== "anytime") {
      const tod = it.time_of_day.charAt(0).toUpperCase() + it.time_of_day.slice(1);
      meta.push(`<span class="cl-meta-badge">${tod}</span>`);
    }
    if (it.schedule && it.schedule !== "daily") {
      meta.push(`<span class="cl-meta-badge">${scheduleLabel(it)}</span>`);
    }
    if (it.recurrence_end) {
      meta.push(`<span class="cl-meta-badge">until ${it.recurrence_end}</span>`);
    }

    let timesHtml = "";
    if (hasMulti) {
      const pills = times.map((t) => {
        const safe = (t.time || "").replace(/[^0-9:]/g, "");
        const cls = "cl-time-tick" + (t.ticked ? " is-ticked" : "");
        return `<button type="button" class="${cls}" data-time="${safe}">⏰ ${safe}${t.ticked ? " ✓" : ""}</button>`;
      }).join("");
      timesHtml = `<div class="cl-times">${pills}</div>`;
    }

    row.innerHTML = `
      <button type="button" class="cl-check" aria-label="Toggle">✓</button>
      <div class="cl-main">
        <div class="cl-name"></div>
        ${meta.length ? `<div class="cl-meta">${meta.join("")}</div>` : ""}
        ${timesHtml}
      </div>
      <button type="button" class="cl-pomo" title="Start Pomodoro 25 min" aria-label="Start Pomodoro">▶</button>
      <button type="button" class="cl-edit" title="Edit" aria-label="Edit">
        <span class="cl-edit-glyph" aria-hidden="true">✏️</span>
      </button>
    `;
    row.querySelector(".cl-name").textContent = it.name;
    row.querySelector(".cl-check").addEventListener("click", (e) => {
      e.stopPropagation();
      toggleTick(it);
    });
    row.querySelector(".cl-edit").addEventListener("click", (e) => {
      e.stopPropagation();
      openModal(it, "edit");
    });
    row.querySelector(".cl-pomo").addEventListener("click", (e) => {
      e.stopPropagation();
      startChecklistPomo(it);
    });
    // Per-fire pills toggle just that one reminder; the main checkbox
    // toggles all of them at once.
    row.querySelectorAll(".cl-time-tick").forEach((pill) => {
      pill.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleTimeTick(it, pill.dataset.time);
      });
    });
    // Row body opens the details panel in *view* mode — no accidental ticking,
    // and the user can read everything before deciding to Edit. The ✓ button
    // (above) is the only thing that toggles completion.
    row.addEventListener("click", () => openModal(it, "view"));
    return row;
  }

  // Start a Pomodoro on a checklist item. Duration is read from the
  // top-of-page Pomodoro bar (which mirrors localStorage so the peek
  // sheet on /summary stays in sync).
  async function startChecklistPomo(it) {
    if (!window.gpomoStart) return;
    const mins = readPomoMinutes();
    await window.gpomoStart({
      source: "adhoc",
      label: it.name,
      mode: "pomodoro",
      target_seconds: mins * 60,
      _title: it.name,
    });
  }

  // ── Pomodoro duration bar ────────────────────────
  function readPomoMinutes() {
    const input = document.getElementById("cl-pomo-mins");
    let mins = 25;
    if (input) {
      mins = Math.max(1, Math.min(180, parseInt(input.value, 10) || 25));
    } else {
      try {
        const saved = parseInt(localStorage.getItem("pomo_default_minutes") || "25", 10);
        if (saved >= 1 && saved <= 180) mins = saved;
      } catch {}
    }
    return mins;
  }
  function setPomoMinutes(mins) {
    const safe = Math.max(1, Math.min(180, parseInt(mins, 10) || 25));
    const input = document.getElementById("cl-pomo-mins");
    if (input) input.value = safe;
    try { localStorage.setItem("pomo_default_minutes", String(safe)); } catch {}
    // Highlight the matching preset chip if any.
    document.querySelectorAll(".cl-pomo-chip").forEach(c => {
      c.classList.toggle("is-active", parseInt(c.dataset.mins, 10) === safe);
    });
  }
  function initPomoBar() {
    const input = document.getElementById("cl-pomo-mins");
    if (!input) return;
    let saved = 25;
    try {
      const v = parseInt(localStorage.getItem("pomo_default_minutes") || "25", 10);
      if (v >= 1 && v <= 180) saved = v;
    } catch {}
    setPomoMinutes(saved);

    input.addEventListener("change", () => setPomoMinutes(input.value));
    input.addEventListener("input", () => setPomoMinutes(input.value));
    document.getElementById("cl-pomo-minus")?.addEventListener("click", () => {
      setPomoMinutes(readPomoMinutes() - 5);
    });
    document.getElementById("cl-pomo-plus")?.addEventListener("click", () => {
      setPomoMinutes(readPomoMinutes() + 5);
    });
    document.querySelectorAll(".cl-pomo-chip").forEach(chip => {
      chip.addEventListener("click", () => setPomoMinutes(chip.dataset.mins));
    });
  }

  function scheduleLabel(it) {
    if (it.schedule === "weekdays") return "Weekdays";
    if (it.schedule === "weekends") return "Weekends";
    if (it.schedule === "custom") {
      const names = ["S", "M", "T", "W", "T", "F", "S"];
      const days = (it.schedule_days || "").split(",").filter(Boolean).map(Number);
      return days.map((d) => names[d]).join(" ");
    }
    if (it.schedule === "monthly_dow") {
      const [wkS, dayS] = (it.schedule_days || "").split(":");
      const wk = parseInt(wkS, 10);
      const day = parseInt(dayS, 10);
      const wkLabel = wk === -1 ? "Last" :
                      ({1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"})[wk] || "?";
      const dayLabel = (["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"])[day] || "?";
      return `Monthly · ${wkLabel} ${dayLabel}`;
    }
    if (it.schedule === "monthly_dom") {
      const n = parseInt((it.schedule_days || "").trim(), 10);
      if (n === -1) return "Monthly · last day";
      if (n >= 1 && n <= 31) return `Monthly · day ${n}`;
      return "Monthly";
    }
    if (it.schedule === "once") {
      const d = (it.schedule_days || "").trim();
      return d ? `On ${d}` : "One-time";
    }
    return "Daily";
  }

  // ── Tick / untick ─────────────────────────────────
  // Main checkbox: toggles every reminder for the item (or the single
  // legacy tick if no reminder times exist).
  async function toggleTick(it) {
    const wasTicked = it.ticked;
    const times = Array.isArray(it.reminder_times) ? it.reminder_times : [];
    it.ticked = !wasTicked;
    if (times.length) {
      for (const t of times) t.ticked = !wasTicked;
    }
    render();

    // Ticking is the achievement; unticking is a correction.
    if (!wasTicked && window.dpParty) {
      window.dpParty(document.querySelector(`[data-id="${it.id}"] .cl-check`),
                     it.name);
    }

    const endpoint = wasTicked ? "untick" : "tick";
    const body = times.length ? { all: true } : {};
    try {
      await api(`/api/checklist/items/${it.id}/${endpoint}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
    } catch (err) {
      it.ticked = wasTicked;
      if (times.length) for (const t of times) t.ticked = wasTicked;
      render();
      alert("Couldn't update: " + err.message);
    }
  }

  // Per-fire pill: toggles a single (item, reminder_time) tick. Updates
  // the parent "all done" state to match the new child set.
  async function toggleTimeTick(it, hhmm) {
    const times = Array.isArray(it.reminder_times) ? it.reminder_times : [];
    const t = times.find((x) => x.time === hhmm);
    if (!t) return;
    const wasTicked = t.ticked;
    t.ticked = !wasTicked;
    it.ticked = times.every((x) => x.ticked);
    render();

    const endpoint = wasTicked ? "untick" : "tick";
    try {
      await api(`/api/checklist/items/${it.id}/${endpoint}`, {
        method: "POST",
        body: JSON.stringify({ reminder_time: hhmm }),
      });
    } catch (err) {
      t.ticked = wasTicked;
      it.ticked = times.every((x) => x.ticked);
      render();
      alert("Couldn't update: " + err.message);
    }
  }

  // ── Modal ─────────────────────────────────────────
  // mode: "view" → read-only details (Close + Edit buttons)
  //       "edit" → editable form (Delete + Cancel + Save)
  // New items always force "edit" since there is nothing to view.
  function openModal(item, mode) {
    const editing = Boolean(item);
    if (!editing) mode = "edit";
    if (mode !== "view" && mode !== "edit") mode = "edit";
    $("#cl-item-id").value = item?.id || "";
    $("#cl-name").value = item?.name || "";
    $("#cl-notes").value = item?.notes || "";
    $("#cl-time-of-day").value = item?.time_of_day || "anytime";
    $("#cl-schedule").value = item?.schedule || "daily";
    // Seed the modal's working list from the item's reminder_times, or
    // fall back to the legacy single value for very old items.
    const seedTimes = (item?.reminder_times || []).map((t) => t.time).filter(Boolean);
    if (!seedTimes.length && item?.reminder_time) seedTimes.push(item.reminder_time);
    state.modalTimes = sortTimes(uniqueTimes(seedTimes));
    renderModalTimes();
    $("#cl-time-new").value = "";
    $("#cl-recurrence-end").value = item?.recurrence_end || "";
    // Refresh the group options (from items loaded so far). If the current
    // item has a group not yet in the list (rare — races), include it.
    const currentGroup = item?.group_name || "";
    if (currentGroup && !state.knownGroups.includes(currentGroup)) {
      state.knownGroups.push(currentGroup);
      state.knownGroups.sort();
    }
    refreshGroupList(currentGroup);

    const sched = item?.schedule || "daily";
    const sdays = item?.schedule_days || "";
    // Custom weekday picker
    const customDays = sched === "custom" ? sdays.split(",").filter(Boolean) : [];
    $$("#cl-weekdays input[type=checkbox]").forEach((cb) => {
      cb.checked = customDays.includes(cb.value);
    });
    // Monthly — nth weekday: "WEEK:DAY"
    if (sched === "monthly_dow") {
      const [wk, dy] = sdays.split(":");
      $("#cl-monthly-week").value = wk || "1";
      $("#cl-monthly-weekday").value = dy || "0";
    } else {
      $("#cl-monthly-week").value = "1";
      $("#cl-monthly-weekday").value = "0";
    }
    // Monthly — day of month: "N" or "-1"
    if (sched === "monthly_dom") {
      $("#cl-monthly-day").value = sdays.trim() || "1";
    } else {
      $("#cl-monthly-day").value = "1";
    }
    // One-time: schedule_days is a YYYY-MM-DD date string. Default to
    // today on a new item so the picker isn't blank.
    if (sched === "once") {
      $("#cl-once-date").value = sdays.trim();
    } else {
      $("#cl-once-date").value = editing ? "" : new Date().toISOString().slice(0, 10);
    }
    toggleSchedulePickers();

    setModalMode(mode, editing);
    $("#cl-modal").hidden = false;
    // Auto-focus the Name input is nice on desktop (start typing
    // immediately), but on phones it pops the soft keyboard the
    // instant the modal opens — which hides half the form and is
    // jarring when the user just wanted to configure the schedule
    // first. Only steal focus when we're confident it's not a touch
    // device.
    if (mode === "edit" && !_isTouchDevice()) {
      setTimeout(() => $("#cl-name").focus(), 50);
    }
  }

  // Heuristic — both checks are required because some hybrid laptops
  // report `ontouchstart` but the user is on a keyboard, and some
  // mobile browsers don't expose maxTouchPoints reliably. The narrow
  // viewport breaker catches anything that slipped through.
  function _isTouchDevice() {
    return (
      ("ontouchstart" in window) ||
      (navigator.maxTouchPoints || 0) > 0 ||
      (window.matchMedia && window.matchMedia("(max-width: 768px)").matches)
    );
  }
  function closeModal() { $("#cl-modal").hidden = true; }

  // Toggle the modal between view/edit. In view mode every input goes
  // disabled (so the user can read but not accidentally type), the title
  // says "Item details", and we show only Close + Edit. In edit mode the
  // inputs are live, the title says "Edit item" / "New checklist item",
  // and we show Delete (existing items only) + Cancel + Save.
  function setModalMode(mode, editing) {
    const modal = document.querySelector("#cl-modal .cl-modal");
    if (modal) modal.dataset.mode = mode;

    const fields = $$("#cl-form input, #cl-form select, #cl-form textarea");
    fields.forEach(el => {
      // hidden item-id stays as-is; everything else mirrors the mode
      if (el.id === "cl-item-id") return;
      el.disabled = (mode === "view");
    });

    if (mode === "view") {
      $("#cl-modal-title").textContent = "Item details";
      $("#cl-delete-btn").hidden = true;
      $("#cl-save-btn").hidden = true;
      $("#cl-edit-mode-btn").hidden = false;
      $("#cl-cancel-btn").textContent = "Close";
    } else {
      $("#cl-modal-title").textContent = editing ? "Edit item" : "New checklist item";
      $("#cl-delete-btn").hidden = !editing;
      $("#cl-save-btn").hidden = false;
      $("#cl-edit-mode-btn").hidden = true;
      $("#cl-cancel-btn").textContent = "Cancel";
    }
  }

  function toggleSchedulePickers() {
    const v = $("#cl-schedule").value;
    $("#cl-weekdays").hidden     = v !== "custom";
    $("#cl-monthly-dow").hidden  = v !== "monthly_dow";
    $("#cl-monthly-dom").hidden  = v !== "monthly_dom";
    $("#cl-once").hidden         = v !== "once";
  }
  // Back-compat alias: the listener below was registered against the
  // old name; keep both pointing at the new combined function.
  const toggleWeekdayPicker = toggleSchedulePickers;

  // ── Reminder times editor (modal) ─────────────────
  function uniqueTimes(arr) {
    return [...new Set(arr.map((t) => (t || "").trim()).filter(Boolean))];
  }
  function sortTimes(arr) {
    return [...arr].sort();
  }
  function renderModalTimes() {
    const list = $("#cl-times-list");
    if (!list) return;
    list.innerHTML = state.modalTimes.map((t) => {
      const safe = t.replace(/[^0-9:]/g, "");
      return `<span class="cl-time-chip">⏰ ${safe}
                <button type="button" aria-label="Remove ${safe}" data-time="${safe}">×</button>
              </span>`;
    }).join("");
    list.querySelectorAll(".cl-time-chip button").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.modalTimes = state.modalTimes.filter((t) => t !== btn.dataset.time);
        renderModalTimes();
      });
    });
  }
  function addModalTime() {
    const input = $("#cl-time-new");
    const v = (input?.value || "").trim();
    if (!v) return;
    if (state.modalTimes.includes(v)) {
      input.value = "";
      return;
    }
    state.modalTimes = sortTimes(uniqueTimes([...state.modalTimes, v]));
    renderModalTimes();
    if (input) input.value = "";
  }

  let saving = false;
  async function saveItem(e) {
    e.preventDefault();
    if (saving) return;               // guard against double-tap
    const id = $("#cl-item-id").value;
    // If the user typed a time into the "Add time" input but didn't
    // hit the + button, fold it into the save so they don't lose it.
    const pendingTime = $("#cl-time-new").value;
    if (pendingTime && !state.modalTimes.includes(pendingTime)) {
      state.modalTimes = sortTimes(uniqueTimes([...state.modalTimes, pendingTime]));
    }
    const schedule = $("#cl-schedule").value;
    // Each schedule kind encodes its parameters into schedule_days
    // differently. The server is intentionally permissive (just a
    // text column) — the encoding lives here and in scheduleLabel.
    let scheduleDays = "";
    if (schedule === "custom") {
      scheduleDays = $$("#cl-weekdays input:checked").map((cb) => cb.value).join(",");
    } else if (schedule === "monthly_dow") {
      scheduleDays = `${$("#cl-monthly-week").value}:${$("#cl-monthly-weekday").value}`;
    } else if (schedule === "monthly_dom") {
      scheduleDays = $("#cl-monthly-day").value;
    } else if (schedule === "once") {
      scheduleDays = $("#cl-once-date").value;
      if (!scheduleDays) {
        alert("Pick a date for this one-time item.");
        return;
      }
    }
    const payload = {
      name: $("#cl-name").value.trim(),
      notes: $("#cl-notes").value.trim(),
      time_of_day: $("#cl-time-of-day").value,
      schedule: schedule,
      reminder_times: state.modalTimes,
      recurrence_end: $("#cl-recurrence-end").value || null,
      group_name: (() => {
        const v = $("#cl-group").value.trim();
        return (!v || v === "__new__") ? null : v;
      })(),
      schedule_days: scheduleDays,
    };
    if (!payload.name) return;

    saving = true;
    const submitBtn = e.target.querySelector('button[type="submit"]');
    const prevLabel = submitBtn?.textContent;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Saving…";
    }

    try {
      if (id) {
        await api(`/api/checklist/items/${id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        await api(`/api/checklist/items`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      closeModal();
      await load();
    } catch (err) {
      alert("Couldn't save: " + err.message);
    } finally {
      saving = false;
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = prevLabel;
      }
    }
  }

  async function deleteItem(e) {
    const id = $("#cl-item-id").value;
    if (!id) return;
    if (!confirm("Delete this item?")) return;
    const btn = e?.currentTarget;
    if (btn) { btn.disabled = true; btn.textContent = "Deleting…"; }
    try {
      await api(`/api/checklist/items/${id}`, { method: "DELETE" });
      closeModal();
      await load();
    } catch (err) {
      alert("Couldn't delete: " + err.message);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "Delete"; }
    }
  }

  // ── Load ──────────────────────────────────────────
  async function load() {
    try {
      // Carry the day being viewed through to the API, so the ticks that
      // come back belong to it. Absent = today, which is the normal case.
      const _d = new URLSearchParams(location.search).get("date") || "";
      const data = await api("/api/checklist/items" + (_d ? "?date=" + encodeURIComponent(_d) : ""));
      state.items = data.items || [];
      // Derive known groups from the loaded items — avoids a second
      // round-trip to /api/checklist/groups on every page load.
      state.knownGroups = [
        ...new Set(state.items.map((it) => (it.group_name || "").trim()).filter(Boolean)),
      ].sort();
      refreshGroupList();
      render();
    } catch (err) {
      $("#cl-groups").innerHTML =
        `<div class="cl-empty">Failed to load: ${err.message}</div>`;
    }
  }

  function refreshGroupList(preserveSelected) {
    const sel = $("#cl-group");
    if (!sel) return;
    const current = preserveSelected !== undefined ? preserveSelected : sel.value;
    const options = ['<option value="">(none)</option>'];
    for (const g of state.knownGroups) {
      const safe = g.replace(/"/g, "&quot;").replace(/</g, "&lt;");
      options.push(`<option value="${safe}">${safe}</option>`);
    }
    options.push('<option value="__new__">+ New group…</option>');
    sel.innerHTML = options.join("");
    // Restore selection if the value still exists; else reset.
    if (current && (current === "" || state.knownGroups.includes(current))) {
      sel.value = current;
    } else {
      sel.value = "";
    }
  }

  // Called from the HTML onchange handler.
  window.onGroupSelectChange = function () {
    const sel = $("#cl-group");
    if (sel.value !== "__new__") return;
    const raw = (prompt("New group name:") || "").trim();
    if (!raw) { sel.value = ""; return; }
    // Title Case locally so the dropdown shows the same form that'll be saved.
    const titled = raw.toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
    if (!state.knownGroups.includes(titled)) {
      state.knownGroups.push(titled);
      state.knownGroups.sort();
    }
    refreshGroupList(titled);
  };

  // ── Wire up ───────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    $("#cl-add-btn").addEventListener("click", () => openModal(null, "edit"));
    $("#cl-modal-close").addEventListener("click", closeModal);
    $("#cl-cancel-btn").addEventListener("click", closeModal);
    $("#cl-delete-btn").addEventListener("click", deleteItem);
    $("#cl-edit-mode-btn").addEventListener("click", () => {
      // Switch the already-open view modal into edit mode in place —
      // no reload, all fields keep their current values.
      setModalMode("edit", true);
      setTimeout(() => $("#cl-name").focus(), 30);
    });
    $("#cl-form").addEventListener("submit", saveItem);

    // ── TOUCHING A FIELD IN VIEW MODE STARTS EDITING ────────────────
    // Reported as "checklist not able to edit time", on desktop and phone
    // alike. Tapping a row opens the modal READ-ONLY, and a disabled
    // <input type="time"> is the worst possible thing to meet there: it
    // takes the tap, does nothing, shows no cursor and says nothing. The
    // Edit button was right there, but the field is what you reach for.
    //
    // A disabled control fires no click of its own; the event still
    // reaches this ancestor, which is what makes one listener here enough
    // for every field in the form.
    $("#cl-form").addEventListener("click", (e) => {
      const modal = document.querySelector("#cl-modal .cl-modal");
      if (!modal || modal.dataset.mode !== "view") return;
      if (e.target.closest("button")) return;   // Close/Edit speak for themselves
      setModalMode("edit", Boolean($("#cl-item-id").value));
      // Hand the tap on to the field that was actually aimed at, now that
      // it can accept it — otherwise the first tap is still swallowed and
      // it only looks half-fixed.
      const f = e.target.closest("input, select, textarea");
      if (f && !f.disabled) { try { f.focus(); } catch (_) {} }
    });
    $("#cl-schedule").addEventListener("change", toggleWeekdayPicker);
    $("#cl-time-add-btn")?.addEventListener("click", addModalTime);
    $("#cl-time-new")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addModalTime();
      }
    });
    $("#cl-modal").addEventListener("click", (e) => {
      if (e.target.id === "cl-modal") closeModal();
    });

    $("#cl-sync-calendar")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      const label = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Syncing…";
      try {
        const r = await api("/api/checklist/sync-calendar", { method: "POST" });
        const parts = [];
        if (r.synced)  parts.push(`${r.synced} synced`);
        if (r.skipped) parts.push(`${r.skipped} skipped (no Google link?)`);
        if (r.failed)  parts.push(`${r.failed} failed`);
        alert(parts.length ? parts.join(", ") : "Nothing to sync.");
      } catch (err) {
        alert("Sync failed: " + err.message);
      } finally {
        btn.disabled = false;
        btn.textContent = label;
      }
    });

    initPomoBar();

    // Push UI wiring (push.js is loaded first)
    if (window.ClPush) {
      window.ClPush.init({
        statusEl:    $("#cl-push-status"),
        statusOkEl:  $("#cl-push-status-ok"),
        enableBtn:   $("#cl-push-enable"),
        disableBtn:  $("#cl-push-disable"),
        testBtn:     $("#cl-push-test"),
        notNowBtn:   $("#cl-push-notnow"),
        snoozedEl:   $("#cl-push-snoozed"),
        unsnoozeBtn: $("#cl-push-unsnooze"),
      });
    }

    load();
  });
})();
