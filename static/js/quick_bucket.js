/* Quick Bucket — minimal Tasks Bucket front-end */
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const csrf = () => (document.querySelector('meta[name="csrf-token"]')?.content) || "";

  const BUCKETS = window.QB_BUCKETS || [
    "now",
    "5m","15m","30m","45m",
    "1h","2h","3h","4h","5h","6h","7h","8h",
    "future",
  ];
  const BUCKET_LABEL = {
    now: "Now",
    "5m": "5M", "15m": "15M", "30m": "30M", "45m": "45M",
    "1h": "1H", "2h": "2H", "3h": "3H", "4h": "4H",
    "5h": "5H", "6h": "6H", "7h": "7H", "8h": "8H",
    future: "Future",
  };
  // Minute + hour buckets all live in one display group so the page
  // doesn't sprout 12+ headers; the pill on each row still shows the
  // precise bucket and a live countdown. Done items get their own
  // group at the bottom so closed work stays visible without polluting
  // the active list.
  const VISIBLE_GROUPS = ["now", "today", "future", "done"];
  const VISIBLE_GROUP_LABEL = { now: "Now", today: "Today", future: "Future", done: "Done" };
  const COUNTED_DOWN = new Set([
    "5m","15m","30m","45m",
    "1h","2h","3h","4h","5h","6h","7h","8h",
    "at",  // pinned absolute time (from an "@1pm today" token)
  ]);
  // Tighter cadence — with 5/15/30/45m options, a 30s tick is too slow
  // to feel "live". 10s keeps the label moving without burning power.
  const TICK_MS = 10_000;

  let items = [];

  /* ── Bulk select -> one calendar slot ──
     `selectMode` is off by default: the everyday use of this page is typing
     a line and cycling a bucket, and a permanent row of checkboxes would tax
     that to serve an occasional planning session. `selected` holds ids as
     STRINGS, because they arrive from data-id attributes as strings and
     comparing those to numeric ids silently never matches. */
  let selectMode = false;
  const selected = new Set();

  /* Which group is being shown. "" means all of them, which is the
     everyday view and stays the default — this exists so the FUTURE
     bucket can be looked at on its own, as a backlog, without the
     nine things due now sitting on top of it.

     Persisted, because a backlog review is a mode you stay in for a
     few minutes and losing it on every render would be maddening. */
  const GROUP_FILTER_KEY = "qb-group-filter-v1";
  let groupFilter = "";
  try {
    const saved = localStorage.getItem(GROUP_FILTER_KEY) || "";
    if (["now", "today", "future", "done"].includes(saved)) groupFilter = saved;
  } catch (_) {}
  // Tracks rows we've already alerted on so the toast / row pulse only
  // fires once when a deadline trips, not every 30s after.
  const alerted = new Set();
  let tickTimer = null;
  // Tracks which open-count band the bucket sits in so the lazy-boy
  // warning / appreciation toast only fires when the band changes,
  // not on every micro re-render (edit / pin / tick).
  //   open >  10 → "over"
  //   open <=  5 → "under" (and > 0)
  //   else       → "between"
  let _lastBucketBand = null;
  // Server-stamped "today" — keeps client/server in sync across midnight
  // and timezone edge cases. Defaults to local today until first load.
  let todayIso = new Date().toISOString().slice(0, 10);
  let top5Limit = 5;
  // Last time we toasted "Top 5 is full" — used to debounce so the
  // warning fires at most once per 3 s even if the user drops several
  // times in a row.
  let _lastTop5FullWarnAt = 0;

  // Motivational quotes for the stats bar — one per day, deterministic
  // so a refresh doesn't shuffle. Date-of-year picks the index.
  const QUOTES = [
    "Small steps every day beat big leaps once in a while.",
    "Done is better than perfect.",
    "Focus is saying no to a thousand good things.",
    "Discipline equals freedom.",
    "Action expresses priorities.",
    "Slow is smooth, smooth is fast.",
    "The best way to get started is to quit talking and begin doing.",
    "Energy and persistence conquer all things.",
    "Inch by inch life's a cinch; yard by yard it's hard.",
    "What gets scheduled gets done.",
    "Make it work, make it right, make it fast — in that order.",
    "You don't have to be great to start, but you have to start to be great.",
    "Compound interest is the eighth wonder — even on habits.",
    "The chains of habit are too light to be felt until they are too heavy to be broken.",
    "Motivation gets you going; habit keeps you going.",
    "If it's not on the list, it didn't happen.",
    "Done lists tell better stories than to-do lists.",
    "Progress, not perfection.",
    "One task at a time, and that one task fully.",
    "The successful warrior is the average person, with laser-like focus.",
    "Consistency is more important than intensity.",
    "Tomorrow becomes never. Do it now.",
    "Direction is more important than speed.",
    "You'll never find time for anything. If you want time, you must make it.",
    "When in doubt, take the smallest possible next step.",
    "First do what's necessary, then what's possible — soon you're doing the impossible.",
    "Plans are nothing; planning is everything.",
    "Focus on being productive instead of busy.",
    "The way to get started is to quit talking and begin doing.",
    "Success is the sum of small efforts, repeated.",
  ];
  const quoteOfTheDay = () => {
    const d = new Date();
    const dayIdx = Math.floor((d - new Date(d.getFullYear(), 0, 0)) / 86_400_000);
    return QUOTES[dayIdx % QUOTES.length];
  };
  const isSameLocalDay = (iso) => {
    if (!iso) return false;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return false;
    const now = new Date();
    return d.getFullYear() === now.getFullYear()
        && d.getMonth() === now.getMonth()
        && d.getDate() === now.getDate();
  };
  // Nudge the user when the open list goes over 10 (too much WIP) or
  // drops to a healthy 1..5 (a quick "well done"). Fires only on band
  // transitions so the toast doesn't spam on every render. The first
  // call after page-load only warns about an "over 10" state — we
  // don't congratulate someone who just opened the page.
  const checkBucketLoad = () => {
    const open = items.filter(it => !it.is_done).length;
    let band;
    if (open > 10)              band = "over";
    else if (open > 0 && open <= 5) band = "under";
    else                        band = "between";
    const first = _lastBucketBand === null;
    if (band !== _lastBucketBand) {
      if (band === "over") {
        toast(`Lazy boy, your bucket list has gone beyond 10 (${open} open) — close some tasks.`, "error");
      } else if (band === "under" && !first) {
        toast(`Nice work — only ${open} open. Keep it under 5!`, "success");
      }
    }
    _lastBucketBand = band;
  };

  const renderStatBar = () => {
    const open = items.filter(it => !it.is_done).length;
    const doneToday = items.filter(it => it.is_done && isSameLocalDay(it.done_at)).length;
    const openEl = document.getElementById("qb-stat-open");
    const doneEl = document.getElementById("qb-stat-done");
    const quoteEl = document.getElementById("qb-quote");
    if (openEl) openEl.textContent = open;
    if (doneEl) doneEl.textContent = doneToday;
    if (quoteEl) quoteEl.textContent = `"${quoteOfTheDay()}"`;

    // Fancy bucket: water-rect height/y based on done / (done +
    // open). Inner bucket is roughly y=29..96 → 67 px of vertical
    // space. The wave path rides on the water surface.
    const total = open + doneToday;
    const ratio = total > 0 ? Math.min(1, doneToday / total) : 0;
    const TOP = 29, BOTTOM = 96;
    const fillH = (BOTTOM - TOP) * ratio;
    const fillY = BOTTOM - fillH;
    const water = document.getElementById("qb-water-fill");
    const wave  = document.getElementById("qb-wave");
    if (water) {
      water.setAttribute("y", fillY);
      water.setAttribute("height", fillH);
    }
    if (wave) {
      // Wide wavy path so the CSS-translated drift never shows seams.
      // Crest height ~1.5 px above the rect's y; the wave is a
      // smooth sine-like curve.
      const y = fillY;
      const d = `M -10 ${y}
                 Q 5 ${y - 1.5} 20 ${y}
                 T 50 ${y} T 80 ${y} T 110 ${y}
                 L 110 ${y + 4} L -10 ${y + 4} Z`;
      wave.setAttribute("d", d);
      // Hide the wave (and bubbles) when the bucket is empty.
      const visible = ratio > 0.02 ? "" : "0";
      wave.style.opacity = visible;
      document.querySelectorAll(".qb-bucket-fancy .qb-bubble").forEach(b => {
        b.style.opacity = visible;
        // Move bubble origin up so they animate from the water level.
        b.setAttribute("cy", fillY + fillH * 0.5);
      });
    }
  };

  // ─────────── helpers ───────────────────────────────────────

  // Routes writes through dpFetch when available so they queue
  // offline and replay via the service worker on reconnect. GETs and
  // environments without dpFetch fall back to plain fetch.
  const _fetch = (window.dpFetch) || ((u, o) => fetch(u, o));
  const apiFetch = async (path, opts = {}) => {
    const headers = Object.assign(
      { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      opts.headers || {}
    );
    const res = await _fetch(path, Object.assign({ credentials: "same-origin" }, opts, { headers }));
    let body = {};
    try { body = await res.json(); } catch (_) { body = {}; }
    if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
    // Surface queued status (synthetic 202 from sync-queue) so callers
    // that need to know — e.g. addItem for optimistic insert — can.
    if (res._queued) body.queued = true;
    return body;
  };

  const toast = (msg, kind = "info") => {
    if (window.toast?.show) return window.toast.show(msg, kind);
    if (window.showToast) return window.showToast(msg, kind);
    console.log(`[${kind}]`, msg);
  };

  const refreshFeather = () => { if (window.feather?.replace) window.feather.replace(); };

  const escapeHTML = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  // Returns minutes remaining (negative when overdue), or null if the
  // item has no deadline (now / future buckets).
  const minutesUntil = (dueAtISO) => {
    if (!dueAtISO) return null;
    const due = new Date(dueAtISO);
    if (Number.isNaN(due.getTime())) return null;
    return Math.round((due - new Date()) / 60000);
  };

  const isCountedDown = (it) => COUNTED_DOWN.has(it.time_bucket);

  // Toggle pill text — static for now/future, live countdown for 4h/8h.
  const toggleLabel = (it) => {
    if (it.time_bucket === "now")    return BUCKET_LABEL.now;
    if (it.time_bucket === "future") return BUCKET_LABEL.future;
    // Pinned absolute time: show the clock time (e.g. "1:00 PM"), or
    // OVERDUE once it's passed.
    if (it.time_bucket === "at") {
      const m = minutesUntil(it.due_at);
      if (m != null && m <= 0) return "OVERDUE";
      const d = new Date(it.due_at);
      if (Number.isNaN(d.getTime())) return "⏰";
      return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    }
    const mins = minutesUntil(it.due_at);
    if (mins == null) return BUCKET_LABEL[it.time_bucket] || "?";
    if (mins <= 0) return "OVERDUE";
    if (mins < 60) return `${mins}m`;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return m === 0 ? `${h}h` : `${h}h ${m}m`;
  };

  const isOverdue = (it) => isCountedDown(it) && minutesUntil(it.due_at) <= 0;

  // ─────────── data load ─────────────────────────────────────

  const loadItems = async () => {
    try {
      const r = await apiFetch("/api/quick-bucket");
      items = r.items || [];
      if (r.today) todayIso = r.today;
      if (r.top5_limit) top5Limit = r.top5_limit;
      render();
      loadEffortSummary();
    } catch (err) {
      toast(err.message || "Could not load", "error");
      // Don't leave the loading skeleton up forever on a failed load.
      const wrap = $("#qb-groups");
      if (wrap && wrap.getAttribute("aria-busy") === "true") {
        wrap.removeAttribute("aria-busy");
        wrap.innerHTML = '<div class="qb-empty">Couldn’t load your bucket. Pull to refresh or try again in a moment.</div>';
      }
    }
  };

  // ─────────── Daily effort summary (planned vs actual) ──────

  // Display minutes as hours + minutes, e.g. 90 → "1h 30m", 60 → "1h",
  // 45 → "45m". Storage stays in whole minutes.
  const fmtMins = (m) => {
    const n = Math.max(0, Math.round(Number(m) || 0));
    if (n < 60) return `${n}m`;
    const h = Math.floor(n / 60), r = n % 60;
    return r ? `${h}h ${r}m` : `${h}h`;
  };

  const renderEffortSummary = (r) => {
    const planned = Number(r.planned) || 0;
    const actual = Number(r.actual) || 0;
    const max = Math.max(planned, actual, 0.01);
    const pBar = $("#qb-eff-planned-bar"), aBar = $("#qb-eff-actual-bar");
    if (pBar) pBar.style.width = Math.round((planned / max) * 100) + "%";
    if (aBar) aBar.style.width = Math.round((actual / max) * 100) + "%";
    const pVal = $("#qb-eff-planned-val"), aVal = $("#qb-eff-actual-val");
    if (pVal) pVal.textContent = fmtMins(planned);
    if (aVal) aVal.textContent = fmtMins(actual);

    // Peek shown next to the title when the card is collapsed.
    const peek = $("#qb-eff-peek");
    if (peek) peek.textContent = (r.count || 0) ? `${fmtMins(actual)} / ${fmtMins(planned)} planned` : "";

    const note = $("#qb-eff-note");
    if (note) {
      const count = r.count || 0;
      const plural = count === 1 ? "" : "s";
      if (r.migration_pending) {
        note.textContent = "Run MIGRATION_QUICK_BUCKET_EFFORT.sql to enable effort tracking.";
      } else if (count === 0) {
        note.textContent = "No effort logged for this day yet. Tap a task → Effort to add minutes.";
      } else {
        const diff = Math.round(actual - planned);
        if (diff === 0) {
          note.innerHTML = `<b class="ontrack">On plan</b> — ${fmtMins(actual)} across ${count} task${plural}.`;
        } else if (diff > 0) {
          note.innerHTML = `${fmtMins(actual)} actual vs ${fmtMins(planned)} planned — <b class="over">▲ ${fmtMins(diff)} over</b> across ${count} task${plural}.`;
        } else {
          note.innerHTML = `${fmtMins(actual)} actual vs ${fmtMins(planned)} planned — <b class="under">▼ ${fmtMins(-diff)} under</b> across ${count} task${plural}.`;
        }
      }
    }

    const list = $("#qb-eff-tasks");
    if (list) {
      list.innerHTML = (r.tasks || []).map(t => `
        <li>
          <span class="t${t.is_done ? " done" : ""}" title="${escapeHTML(t.text)}">${escapeHTML(t.text)}</span>
          <span class="h">${fmtMins(t.actual)} actual / ${fmtMins(t.planned)} plan</span>
        </li>`).join("");
    }
  };

  const loadEffortSummary = async () => {
    const dateInput = $("#qb-eff-date");
    if (!dateInput) return;
    if (!dateInput.value) {
      dateInput.value = todayIso || new Date().toISOString().slice(0, 10);
    }
    const day = dateInput.value;
    try {
      const r = await apiFetch(`/api/quick-bucket/effort-summary?date=${encodeURIComponent(day)}`);
      renderEffortSummary(r);
    } catch (err) {
      // Best-effort — leave the previous render in place on transient errors.
    }
  };

  // ─────────── Today's Top 5 helpers ─────────────────────────

  const isInTop5 = (it) => it && it.top5_date && String(it.top5_date) === todayIso;

  // Today's panel in display order — actives the user can drag, plus
  // done-but-pinned items that stay in their slot crossed out.
  const top5Items = () => items
    .filter(isInTop5)
    .slice()
    .sort((a, b) => {
      const pa = a.top5_position == null ? 99 : a.top5_position;
      const pb = b.top5_position == null ? 99 : b.top5_position;
      return pa - pb;
    });

  const top5IdsInOrder = () => top5Items().map(it => it.id);

  const saveTop5 = async (ids) => {
    try {
      await apiFetch("/api/quick-bucket/top5", {
        method: "POST", body: JSON.stringify({ ids }),
      });
      const today = todayIso;
      const inSet = new Set(ids);
      items.forEach(it => {
        if (inSet.has(it.id)) {
          it.top5_date = today;
          it.top5_position = ids.indexOf(it.id) + 1;
        } else if (it.top5_date === today && !it.is_done) {
          it.top5_date = null;
          it.top5_position = null;
        }
      });
      render();
    } catch (err) {
      toast(err.message || "Couldn't update Top 5", "error");
      loadItems();
    }
  };

  // Given the panel <ol> and a clientY, return the index in the panel's
  // full visual list (active + done) where a drop should insert.
  const findPanelInsertIndex = (panel, clientY) => {
    const rows = $$(".qb-top5-item", panel);
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i].getBoundingClientRect();
      if (clientY < r.top + r.height / 2) return i;
    }
    return rows.length;
  };

  // ─────────── render ───────────────────────────────────────

  const groupItems = () => {
    const groups = { now: [], today: [], future: [], done: [] };
    items.forEach(it => {
      // Pinned-for-today items live in the Top-5 panel only, so they
      // don't double-render in the category groups below.
      if (isInTop5(it)) return;
      if (it.is_done)              groups.done.push(it);
      else if (it.time_bucket === "at") {
        // Pinned time → Today if it falls on the local calendar day,
        // otherwise Future.
        const d = it.due_at ? new Date(it.due_at) : null;
        const n = new Date();
        const sameDay = d && !Number.isNaN(d.getTime()) &&
          d.getFullYear() === n.getFullYear() &&
          d.getMonth() === n.getMonth() && d.getDate() === n.getDate();
        (sameDay ? groups.today : groups.future).push(it);
      }
      else if (it.time_bucket === "now")    groups.now.push(it);
      else if (it.time_bucket === "future") groups.future.push(it);
      else                                  groups.today.push(it);  // 1h..8h
    });
    // Within "today" sort by deadline ascending (closest-first), so the
    // tightest item is on top no matter which hour bucket it picked.
    groups.today.sort((a, b) => {
      const da = a.due_at ? new Date(a.due_at).getTime() : Number.POSITIVE_INFINITY;
      const db = b.due_at ? new Date(b.due_at).getTime() : Number.POSITIVE_INFINITY;
      return da - db;
    });
    // Done sorted by most-recently-closed first.
    groups.done.sort((a, b) => (b.done_at || "").localeCompare(a.done_at || ""));
    return groups;
  };

  const renderRow = (it) => {
    const tb = (it.time_bucket === "at") ? "at"
             : (BUCKETS.includes(it.time_bucket) ? it.time_bucket : "now");
    const overdue = !it.is_done && isOverdue(it);
    const cls = ["qb-row"];
    if (overdue) cls.push("is-overdue");
    if (it.is_done) cls.push("is-done");
    // Amber tint for active rows with ≤30 minutes remaining, so the
    // "close this next" tasks pop visually above the rest.
    if (!it.is_done && !overdue && isCountedDown(it)) {
      const mins = minutesUntil(it.due_at);
      if (mins != null && mins > 0 && mins <= 30) cls.push("is-urgent");
    }
    const togCls = overdue ? "qb-toggle qb-toggle--overdue" : `qb-toggle qb-toggle--${tb}`;

    // Done rows still get a Reopen icon. Active rows have no side
    // action — clicking the task text itself opens the edit popup.
    const sideAction = it.is_done
      ? `<button class="qb-row-icon-action" data-action="reopen" title="Reopen">
           <i data-feather="rotate-ccw"></i>
         </button>`
      : `<span class="qb-row-spacer" aria-hidden="true"></span>`;

    const prio = it.priority_label && it.priority_label > 0 ? it.priority_label : null;
    const prioBadge = `
      <button class="qb-prio" data-action="prio" type="button"
              data-rank="${prio || ''}"
              title="Click +1 · Shift+click or long-press -1 (floor 1, conflicts allowed)">
        ${prio == null ? '·' : (prio > 99 ? '99+' : prio)}
      </button>`;

    // Where this row went, if it has been dropped into a calendar slot.
    // Shown rather than hiding the row: it is scheduled, not finished.
    const schedPill = it.scheduled_for
      ? `<span class="qb-sched-pill" title="On the calendar">📅 ${escapeHTML(String(it.scheduled_for))}</span>`
      : "";

    // The selection box exists ONLY in select mode, so the row keeps its
    // normal geometry the rest of the time.
    const selBox = selectMode
      ? `<input type="checkbox" class="qb-selectbox" data-action="pick-select"
                aria-label="Select for scheduling" ${selected.has(String(it.id)) ? "checked" : ""}>`
      : "";
    if (selectMode && selected.has(String(it.id))) cls.push("is-picked");

    return `
      <div class="${cls.join(' ')}" data-id="${it.id}">
        ${selBox}
        <input type="checkbox" class="qb-check" data-action="done"
               aria-label="Mark done" ${it.is_done ? 'checked' : ''}>
        ${prioBadge}
        <div class="qb-text" data-action="edit" title="Click to edit"
             tabindex="0" role="button">${escapeHTML(it.text)}</div>
        ${schedPill}
        <button class="${togCls}" data-action="pick" type="button"
                title="Click to choose when: Now / 1H–8H / Future">
          ${escapeHTML(toggleLabel(it))}
        </button>
        ${sideAction}
        <button class="qb-icon-btn" data-action="archive" title="Remove">
          <i data-feather="x"></i>
        </button>
      </div>`;
  };

  const renderTop5 = () => {
    const list = $("#qb-top5-list");
    const counter = $("#qb-top5-counter");
    const hint = $("#qb-top5-hint");
    if (!list) return;

    const rows = top5Items();
    if (counter) counter.textContent = `${rows.length} / ${top5Limit}`;
    list.classList.toggle("is-empty", rows.length === 0);
    if (hint) {
      hint.textContent = rows.length >= top5Limit
        ? "Panel full. Drop one back into the list to free a slot."
        : "Drag tasks here. Reorder by dragging within. Drop back into the list to remove.";
    }

    list.innerHTML = rows.map((it, idx) => {
      const done = !!it.is_done;
      const cls = "qb-top5-item" + (done ? " is-done" : "");
      return `
        <li class="${cls}" data-id="${it.id}"${done ? "" : ' draggable="true"'}>
          <span class="qb-top5-rank">${idx + 1}</span>
          <input type="checkbox" class="qb-top5-check" aria-label="Mark done"
                 ${done ? "checked" : ""}>
          <div class="qb-top5-text" title="${escapeHTML(it.text)}">${escapeHTML(it.text)}</div>
        </li>`;
    }).join("");

    wireTop5Rows();
    wireTop5Interactions();
  };

  // Tap on text → open edit modal (same as group rows). Tick the
  // checkbox → mark done / reopen.
  const wireTop5Interactions = () => {
    $$("#qb-top5-list .qb-top5-item").forEach(row => {
      const it = items.find(x => x.id === row.dataset.id);
      if (!it) return;
      const cb = $(".qb-top5-check", row);
      if (cb) {
        cb.addEventListener("click", (e) => e.stopPropagation());
        cb.addEventListener("change", () => {
          if (cb.checked) markDone(it);
          else reopen(it);
        });
      }
      const text = $(".qb-top5-text", row);
      text?.addEventListener("click", (e) => {
        e.stopPropagation();
        if (typeof openEditModal === "function") openEditModal(it);
      });
    });
  };

  const render = () => {
    renderStatBar();
    renderTop5();
    const wrap = $("#qb-groups");
    const empty = $("#qb-empty");
    wrap.removeAttribute("aria-busy");
    if (!items.length) {
      wrap.innerHTML = "";
      empty.removeAttribute("hidden");
      refreshFeather();
      return;
    }
    empty.setAttribute("hidden", "");
    const groups = groupItems();
    // Counts come from ALL groups, so the chips can say how much is in
    // Future while you are looking at Now — the number is half the reason
    // to have the filter at all.
    paintGroupFilter(groups);
    const shown = groupFilter ? [groupFilter] : VISIBLE_GROUPS;
    const anyVisible = shown.some(g => groups[g].length > 0);
    wrap.innerHTML = shown.map(g => {
      const list = groups[g];
      if (!list.length) return "";
      return `
        <section class="qb-group qb-group--${g}">
          <div class="qb-group-head">${VISIBLE_GROUP_LABEL[g]} <span class="qb-count">${list.length}</span></div>
          <div class="qb-list">${list.map(renderRow).join("")}</div>
        </section>`;
    }).join("");
    // If every task is pinned to the panel, surface the empty hint so
    // the area under the panel doesn't look broken.
    if (!anyVisible) empty.removeAttribute("hidden");
    refreshFeather();
    wireRows();
    wireDragDrop();
    wireSwipeRight();
    checkBucketLoad();
    revealFocused();
  };

  /* ── ?focus=<id> — ARRIVING AT A ROW, NOT AT A PAGE ─────────────────
     The Day Board links here for an item you were already looking at, and
     landing at the top of a list this long is barely better than not
     linking at all. Scrolled to and marked, once — a highlight that
     survives every later render would still be lit tomorrow.

     The row may be inside a collapsed group, so the group is opened first;
     scrolling to something still hidden lands nowhere. */
  let _focusDone = false;
  const revealFocused = () => {
    if (_focusDone) return;
    let want = "";
    try { want = new URLSearchParams(location.search).get("focus") || ""; }
    catch (_) { return; }
    if (!want) { _focusDone = true; return; }

    const row = document.querySelector(`#qb-groups [data-id="${CSS.escape(want)}"]`);
    if (!row) return;                 // may not be rendered yet; try next render
    _focusDone = true;

    const group = row.closest("details");
    if (group && !group.open) group.open = true;

    requestAnimationFrame(() => {
      try { row.scrollIntoView({ block: "center", behavior: "smooth" }); }
      catch (_) { row.scrollIntoView(); }
      row.classList.add("is-focused");
      // Removed rather than left on: this marks where you just arrived,
      // not a state the row is in.
      setTimeout(() => row.classList.remove("is-focused"), 2600);
    });
  };

  // ─────────── swipe-right on a row to mark done ────────────
  const wireSwipeRight = () => {
    const TH = 90, YT = 30;
    $$("#qb-groups .qb-row").forEach(row => {
      const id = row.dataset.id;
      const it = items.find(x => x.id === id);
      if (!it || it.is_done) return;
      let sx = 0, sy = 0, active = false;
      const reset = () => {
        row.style.transition = "transform .2s ease, background .15s";
        row.style.transform = ""; row.style.background = "";
        active = false;
      };
      row.addEventListener("touchstart", (e) => {
        if (!e.touches || e.touches.length !== 1) return;
        sx = e.touches[0].clientX; sy = e.touches[0].clientY;
        active = true; row.style.transition = "background .15s";
      }, { passive: true });
      row.addEventListener("touchmove", (e) => {
        if (!active || !e.touches?.length) return;
        const dx = e.touches[0].clientX - sx;
        const dy = Math.abs(e.touches[0].clientY - sy);
        if (dy > YT) { reset(); return; }
        if (dx > 0) {
          row.style.transform = `translateX(${Math.min(dx, 200)}px)`;
          row.style.background = dx >= TH ? "#E6F4F1" : "";
        }
      }, { passive: true });
      row.addEventListener("touchend", (e) => {
        if (!active) return;
        const dx = (e.changedTouches?.[0]?.clientX ?? sx) - sx;
        if (dx >= TH) {
          row.style.transition = "transform .25s ease";
          row.style.transform = "translateX(110%)";
          markDone(it);
          setTimeout(reset, 260);
        } else { reset(); }
      }, { passive: true });
      row.addEventListener("touchcancel", reset, { passive: true });
    });
  };

  // ─────────── drag-and-drop ───────────────────────────────
  // HTML5 native — no library. Three flows:
  //   1. Group row → another group row : reorder within that group.
  //   2. Group row → Top-5 panel        : pin to today's panel.
  //   3. Top-5 panel row → anywhere out : unpin from panel.
  //   4. Top-5 panel row → Top-5 panel  : reorder within panel.
  // Cross-group time changes (e.g. Now → Future) still go through the
  // toggle pill, not drag.
  let _dragId = null;
  let _dragSource = null;  // "group" | "top5"

  const _clearDropHints = () => {
    document.querySelectorAll("#qb-groups .qb-row.is-drop-target")
      .forEach(r => r.classList.remove("is-drop-target"));
    $("#qb-top5-list")?.classList.remove("is-drop-target");
  };

  const wireTop5Rows = () => {
    const panel = $("#qb-top5-list");
    if (!panel) return;

    $$(".qb-top5-item", panel).forEach(row => {
      if (row.classList.contains("is-done")) return;
      row.addEventListener("dragstart", (e) => {
        _dragId = row.dataset.id;
        _dragSource = "top5";
        row.classList.add("is-dragging");
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", _dragId); } catch (_) {}
      });
      row.addEventListener("dragend", () => {
        row.classList.remove("is-dragging");
        _dragId = null; _dragSource = null;
        _clearDropHints();
      });
    });

    // ── BOUND ONCE, NOT ONCE PER RENDER ─────────────────────────────
    // renderTop5() replaces this panel's CHILDREN via innerHTML, so the row
    // listeners above die with the rows they were attached to. The panel
    // itself survives, and the three handlers below were being added to it
    // again on every render. After ten renders a single drop ran the drop
    // handler ten times, each one saving and re-rendering and adding ten
    // more — reported as "if i try to drag again it looks like it is going
    // in continous loop".
    //
    // The "a single drag can fire the drop handler several times in some
    // browsers" note further down was this bug seen from the outside, and
    // the toast debounce was hiding it rather than fixing it.
    if (panel.dataset.dropWired === "1") return;
    panel.dataset.dropWired = "1";

    panel.addEventListener("dragover", (e) => {
      if (!_dragId) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      panel.classList.add("is-drop-target");
    });
    panel.addEventListener("dragleave", (e) => {
      if (e.target === panel) panel.classList.remove("is-drop-target");
    });
    panel.addEventListener("drop", async (e) => {
      e.preventDefault();
      panel.classList.remove("is-drop-target");
      const id = _dragId || (e.dataTransfer && e.dataTransfer.getData("text/plain"));
      const source = _dragSource;
      _dragId = null; _dragSource = null;
      if (!id) return;
      const it = items.find(x => x.id === id);
      if (!it || it.is_done) return;

      const current = top5IdsInOrder();
      const without = current.filter(x => x !== id);
      const insertIdx = findPanelInsertIndex(panel, e.clientY);
      const next = [...without];
      next.splice(insertIdx, 0, id);

      if (next.length > top5Limit) {
        // Debounce — a single drag can fire the drop handler several
        // times in some browsers, and a frustrated user re-dropping
        // shouldn't get a stack of toasts. Once per 3 s is plenty.
        const now = Date.now();
        if (now - _lastTop5FullWarnAt > 3000) {
          toast("Top 5 is full. Drop one out first.", "error");
          _lastTop5FullWarnAt = now;
        }
        return;
      }
      await saveTop5(next);
      if (source === "group") toast("Pinned to Top 5", "success");
    });
  };

  const wireDragDrop = () => {
    $$("#qb-groups .qb-row").forEach(row => {
      row.draggable = true;
      row.addEventListener("dragstart", (e) => {
        _dragId = row.dataset.id;
        _dragSource = "group";
        row.classList.add("is-dragging");
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", _dragId); } catch (_) {}
      });
      row.addEventListener("dragend", () => {
        row.classList.remove("is-dragging");
        _dragId = null; _dragSource = null;
        _clearDropHints();
      });
      row.addEventListener("dragover", (e) => {
        if (!_dragId || _dragId === row.dataset.id) return;
        // Only allow group-internal reorder when dragging from a group;
        // panel drags don't reorder group rows.
        if (_dragSource !== "group") return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        const draggingEl = document.querySelector(`#qb-groups .qb-row[data-id="${_dragId}"]`);
        if (!draggingEl) return;
        if (draggingEl.parentElement !== row.parentElement) return;
        const rect = row.getBoundingClientRect();
        const before = (e.clientY - rect.top) < rect.height / 2;
        if (before) row.parentElement.insertBefore(draggingEl, row);
        else row.parentElement.insertBefore(draggingEl, row.nextSibling);
      });
      row.addEventListener("drop", async (e) => {
        e.preventDefault();
        if (_dragSource === "top5") {
          // Drop a panel row onto a group row → unpin from Top 5. The
          // group's own ordering doesn't change here.
          const id = _dragId;
          _dragId = null; _dragSource = null;
          if (!id) return;
          const remaining = top5IdsInOrder().filter(x => x !== id);
          await saveTop5(remaining);
          toast("Removed from Top 5", "info");
          return;
        }
        // In-group reorder.
        const groupEl = row.parentElement;
        const newOrder = Array.from(groupEl.querySelectorAll(".qb-row"))
          .map(r => r.dataset.id);
        const orderMap = new Map(newOrder.map((id, i) => [id, i]));
        const inGroup = items.filter(x => orderMap.has(x.id));
        const others  = items.filter(x => !orderMap.has(x.id));
        inGroup.sort((a, b) => orderMap.get(a.id) - orderMap.get(b.id));
        items = others.concat(inGroup);
        try {
          await apiFetch("/api/quick-bucket/reorder", {
            method: "POST",
            body: JSON.stringify({ ids: newOrder }),
          });
        } catch (err) {
          toast(err.message || "Couldn't save order", "error");
        }
      });
    });

    // Also allow dropping a panel row onto a group section (not just a
    // row) — same unpin behavior. Catches drops on empty space below
    // the last row in a group.
    $$("#qb-groups .qb-group").forEach(group => {
      group.addEventListener("dragover", (e) => {
        if (_dragSource !== "top5") return;
        e.preventDefault();
        group.classList.add("is-drop-target");
      });
      group.addEventListener("dragleave", () => group.classList.remove("is-drop-target"));
      group.addEventListener("drop", async (e) => {
        if (_dragSource !== "top5") return;
        e.preventDefault();
        group.classList.remove("is-drop-target");
        const id = _dragId;
        _dragId = null; _dragSource = null;
        if (!id) return;
        const remaining = top5IdsInOrder().filter(x => x !== id);
        await saveTop5(remaining);
        toast("Removed from Top 5", "info");
      });
    });
  };

  // ─────────── show one group at a time ─────────────────────
  // Asked for as "a filter to show only Future". Built as a focus on any
  // ONE group rather than a Future-only toggle: the same control, and it
  // also answers "what is due now" and "what did I finish today", which
  // are the other two questions this list gets asked.

  const GROUP_FILTERS = [
    ["", "All"],
    ["now", "Now"],
    ["today", "Today"],
    ["future", "Future"],
    ["done", "Done"],
  ];

  const paintGroupFilter = (groups) => {
    const bar = $("#qb-groupfilter");
    if (!bar) return;
    bar.innerHTML = GROUP_FILTERS.map(function (pair) {
      const key = pair[0], label = pair[1];
      const n = key ? (groups[key] || []).length
                    : VISIBLE_GROUPS.reduce(function (t, g) {
                        return t + (groups[g] || []).length;
                      }, 0);
      const on = groupFilter === key ? " is-on" : "";
      // An empty group is still clickable — a Future bucket with nothing in
      // it is a fact worth being able to look at, not a disabled button.
      return '<button type="button" class="qb-gf' + on + '" data-gf="' + key + '">' +
             label + ' <span class="qb-gf-n">' + n + '</span></button>';
    }).join("");
  };

  const wireGroupFilter = () => {
    const bar = $("#qb-groupfilter");
    if (!bar) return;
    bar.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-gf]");
      if (!btn) return;
      const next = btn.getAttribute("data-gf") || "";
      // Pressing the active one returns to All, so the filter is never a
      // state you have to hunt for the way out of.
      groupFilter = (groupFilter === next) ? "" : next;
      try { localStorage.setItem(GROUP_FILTER_KEY, groupFilter); } catch (_) {}
      render();
    });
  };

  // ─────────── bulk select -> calendar slot ─────────────────
  // Asked for: pick several bucket items, drop them into a slot, and have
  // them appear in that event's DESCRIPTION.
  //
  // ONE EVENT, NOT ONE PER ITEM. Five tasks become five lines in one slot,
  // not five overlapping calendar entries — which is what "move them to a
  // slot" means and the only version that stays readable on a week view.

  const selectableIds = () =>
    $$("#qb-groups .qb-row").map(r => r.dataset.id).filter(Boolean);

  const paintSelBar = () => {
    const count  = $("#qb-selcount");
    const go     = $("#qb-sel-schedule");
    const all    = $("#qb-sel-all");
    const none   = $("#qb-sel-none");
    const toggle = $("#qb-sel-toggle");
    if (!toggle) return;

    toggle.classList.toggle("is-on", selectMode);
    toggle.textContent = selectMode ? "Done selecting" : "Select";
    [count, go, all, none].forEach(el => { if (el) el.hidden = !selectMode; });
    if (!selectMode) return;

    const n = selected.size;
    if (count) count.textContent = n === 1 ? "1 selected" : n + " selected";
    if (go) go.disabled = n === 0;
  };

  const setSelectMode = (on) => {
    selectMode = on;
    if (!on) selected.clear();
    render();          // the checkbox only exists in select mode
    paintSelBar();
  };

  /* Default the picker to the next round half-hour, which is what someone
     scheduling "later today" almost always means.

     Built from LOCAL date parts, never toISOString(): that returns UTC, so
     at +05:30 it still reports YESTERDAY between 00:00 and 05:29 local.
     Verified rather than assumed — 00:30 IST on the 26th gives "2026-08-25"
     from toISOString and "2026-08-26" from the local parts. An early-morning
     planning session would silently schedule everything a day late. */
  const nextHalfHour = () => {
    const d = new Date();
    d.setSeconds(0, 0);
    d.setMinutes(d.getMinutes() + (30 - (d.getMinutes() % 30)));
    const p = (n) => String(n).padStart(2, "0");
    return {
      date: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`,
      time: `${p(d.getHours())}:${p(d.getMinutes())}`,
    };
  };

  const openScheduleModal = () => {
    if (!selected.size) return;
    const when = nextHalfHour();
    $("#qb-sched-date").value  = when.date;
    $("#qb-sched-start").value = when.time;
    $("#qb-sched-dur").value   = 30;
    $("#qb-sched-title-in").value = "";

    const picked = items.filter(i => selected.has(String(i.id)));
    const sub = $("#qb-sched-sub");
    if (sub) {
      const names = picked.slice(0, 3).map(i => i.text).join(", ");
      sub.textContent = picked.length === 1
        ? `“${picked[0].text}” will go into this slot.`
        : `${picked.length} tasks — ${names}${picked.length > 3 ? ", …" : ""}`;
    }
    const m = $("#qb-sched-modal");
    m.classList.add("is-open");
    m.setAttribute("aria-hidden", "false");
    $("#qb-sched-date").focus();
  };

  const closeScheduleModal = () => {
    const m = $("#qb-sched-modal");
    m.classList.remove("is-open");
    m.setAttribute("aria-hidden", "true");
  };

  const submitSchedule = async () => {
    const ids = selectableIds().filter(id => selected.has(String(id)));
    if (!ids.length) return;

    const body = {
      ids,
      date:     $("#qb-sched-date").value,
      start:    $("#qb-sched-start").value,
      duration: parseInt($("#qb-sched-dur").value, 10) || 30,
      title:    $("#qb-sched-title-in").value.trim(),
    };
    if (!body.date || !body.start) {
      toast("Pick a day and a start time.", "error");
      return;
    }

    const go = $("#qb-sched-go");
    go.disabled = true;
    try {
      const res = await fetch("/api/quick-bucket/schedule", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": document.querySelector('meta[name=csrf-token]')?.content || "",
        },
        body: JSON.stringify(body),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast(j.error || "Couldn't create the slot.", "error");
        return;
      }
      closeScheduleModal();
      setSelectMode(false);
      toast(`${j.count} on the calendar — ${j.date} at ${j.start}`, "success");
      // The rows now carry scheduled_for, which the pill reads.
      await loadItems();
    } catch (_) {
      toast("Network error — nothing was scheduled.", "error");
    } finally {
      go.disabled = false;
    }
  };

  const wireSelectBar = () => {
    $("#qb-sel-toggle")?.addEventListener("click", () => setSelectMode(!selectMode));
    $("#qb-sel-all")?.addEventListener("click", () => {
      selectableIds().forEach(id => selected.add(String(id)));
      render(); paintSelBar();
    });
    $("#qb-sel-none")?.addEventListener("click", () => {
      selected.clear(); render(); paintSelBar();
    });
    $("#qb-sel-schedule")?.addEventListener("click", openScheduleModal);
    $("#qb-sched-cancel")?.addEventListener("click", closeScheduleModal);
    $("#qb-sched-go")?.addEventListener("click", submitSchedule);
    $("#qb-sched-modal")?.addEventListener("click", (e) => {
      if (e.target.id === "qb-sched-modal") closeScheduleModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if ($("#qb-sched-modal")?.classList.contains("is-open")) closeScheduleModal();
      else if (selectMode) setSelectMode(false);
    });
    paintSelBar();
  };

  // ─────────── interactions ─────────────────────────────────

  const wireRows = () => {
    $$("#qb-groups .qb-row").forEach(row => {
      const id = row.dataset.id;
      const it = items.find(x => x.id === id);
      if (!it) return;

      $("input.qb-check", row)?.addEventListener("change", (e) => {
        if (e.target.checked) markDone(it);
        else reopen(it);
      });
      // The SELECTION box, distinct from the done box beside it. Repaints
      // only this row rather than the whole list, so ticking a dozen items
      // does not rebuild the groups a dozen times.
      $("input.qb-selectbox", row)?.addEventListener("change", (e) => {
        const key = String(it.id);
        if (e.target.checked) selected.add(key); else selected.delete(key);
        row.classList.toggle("is-picked", e.target.checked);
        paintSelBar();
      });
      $("button.qb-toggle", row)?.addEventListener("click", (e) => {
        e.stopPropagation();
        openPicker(e.currentTarget, it);
      });
      $("button.qb-icon-btn[data-action='archive']", row)?.addEventListener("click", () => archive(it));
      $("button.qb-row-icon-action[data-action='reopen']", row)?.addEventListener("click", () => reopen(it));
      const prioBtn = $("button.qb-prio", row);
      if (prioBtn) {
        // Plain click → +1. Shift+click → -1 (keyboard shortcut for
        // anyone on a desktop).
        prioBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          bumpPriorityLabel(it, e.shiftKey ? -1 : 1);
        });
        // Right-click → -1 (suppress the browser context menu).
        prioBtn.addEventListener("contextmenu", (e) => {
          e.preventDefault();
          e.stopPropagation();
          bumpPriorityLabel(it, -1);
        });
        // Long-press → -1 (mobile / touch). 450 ms is long enough to
        // distinguish from a tap but short enough not to feel sticky.
        let pressTimer = null;
        let didLong = false;
        const cancelPress = () => {
          if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
        };
        prioBtn.addEventListener("touchstart", () => {
          didLong = false;
          pressTimer = setTimeout(() => {
            didLong = true;
            bumpPriorityLabel(it, -1);
          }, 450);
        }, { passive: true });
        prioBtn.addEventListener("touchmove",   cancelPress, { passive: true });
        prioBtn.addEventListener("touchcancel", cancelPress, { passive: true });
        prioBtn.addEventListener("touchend", () => {
          cancelPress();
          // Swallow the synthetic click that follows a long-press so
          // the row doesn't get +1'd right after the -1.
          if (didLong) {
            const swallow = (e) => { e.stopPropagation(); e.preventDefault(); };
            prioBtn.addEventListener("click", swallow, { capture: true, once: true });
          }
        });
      }
      // Tapping the task text opens the edit-and-move popup. Done rows
      // also get the popup so the user can fix typos in past entries.
      const textEl = $(".qb-text", row);
      textEl?.addEventListener("click", () => openEditModal(it));
      textEl?.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openEditModal(it);
        }
      });
    });
  };

  // ─────────── bucket picker popover ────────────────────────

  const closePicker = () => {
    const picker = $("#qb-picker");
    if (!picker || picker.hidden) return;
    picker.hidden = true;
    picker.innerHTML = "";
  };

  const openPicker = (anchor, it) => {
    const picker = $("#qb-picker");
    if (!picker) return;

    picker.innerHTML = BUCKETS.map(b => {
      const cur = it.time_bucket === b ? "is-current" : "";
      return `<button class="qb-pick ${cur}" data-b="${b}" type="button">${BUCKET_LABEL[b] || b}</button>`;
    }).join("");

    // Position below the toggle pill, flush-left with it. If that
    // would overflow the viewport on the right edge, slide left.
    const r = anchor.getBoundingClientRect();
    picker.hidden = false;
    const pw = picker.offsetWidth;
    const top = r.bottom + window.scrollY + 4;
    let left = r.left + window.scrollX;
    if (left + pw > window.innerWidth + window.scrollX - 8) {
      left = Math.max(8, window.innerWidth + window.scrollX - pw - 8);
    }
    picker.style.top = `${top}px`;
    picker.style.left = `${left}px`;

    $$(".qb-pick", picker).forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const newBucket = btn.dataset.b;
        closePicker();
        if (newBucket === it.time_bucket) return;
        setBucket(it, newBucket);
      });
    });
  };

  // Highest priority_label across currently-open (non-done, non-archived)
  // rows. Used both to seed new items at max+1 and as the cap for the
  // visual rank ramp (1=red, 2=amber, 3=yellow, 4+ = indigo).
  const maxPriorityLabel = () => {
    let m = 0;
    for (const it of items) {
      if (it.is_done || it.archived_at) continue;
      const n = parseInt(it.priority_label, 10);
      if (Number.isFinite(n) && n > m) m = n;
    }
    return m;
  };
  const nextPriorityLabelForNew = () => maxPriorityLabel() + 1;

  // Click the round badge → bump by +1. Shift+click, right-click, or
  // long-press → -1 (floors at 1). Conflicts (two rows with the same
  // number) are allowed by design.
  const bumpPriorityLabel = async (it, delta = 1) => {
    buzz(HAPTIC.tap);
    const cur = parseInt(it.priority_label, 10);
    const base = (Number.isFinite(cur) && cur > 0) ? cur : 1;
    const next = Math.max(1, base + delta);
    if (next === base && Number.isFinite(cur) && cur > 0) return;  // no-op at floor
    // Optimistic local update so the badge ticks immediately even when
    // the network is slow (or queued offline by sync-queue.js).
    const prev = it.priority_label;
    it.priority_label = next;
    render();
    try {
      await apiFetch(`/api/quick-bucket/${it.id}/update`, {
        method: "POST", body: JSON.stringify({ priority_label: next }),
      });
    } catch (err) {
      // Roll back on hard failure so the UI stays truthful.
      it.priority_label = prev;
      render();
      toast(err.message || "Couldn't update label", "error");
    }
  };

  const setBucket = async (it, newBucket) => {
    buzz(HAPTIC.tap);
    try {
      const r = await apiFetch(`/api/quick-bucket/${it.id}/update`, {
        method: "POST", body: JSON.stringify({ time_bucket: newBucket }),
      });
      it.time_bucket = newBucket;
      // The /update endpoint echoes the patch back; it includes the
      // freshly-stamped due_at (or null for now/future).
      if (r && r.patch && "due_at" in r.patch) it.due_at = r.patch.due_at;
      else it.due_at = null;
      // Re-arm overdue alerts for this row — the deadline is new.
      alerted.delete(it.id);
      render();
    } catch (err) {
      toast(err.message || "Couldn't change", "error");
    }
  };

  // Rotating motivational quotes so closing a task feels meaningful.
  // Mix of mantras, famous quotes (attributed where short enough), and
  // punchy one-liners. Keep each line ≤ ~90 chars so toasts don't wrap.
  const CHEERS = [
    "Progress, not perfection.",
    "Done is better than perfect.",
    "Show up. Do the work. Repeat.",
    "Slow is smooth. Smooth is fast.",
    "Compounding starts with a single rep.",
    "Inch by inch, anything's a cinch.",
    "Win the morning, win the day.",
    "Small daily wins compound into big ones.",
    "Habits become character.",
    "Effort, repeated daily, becomes destiny.",
    "Hard choices, easy life. — Jerzy Gregorek",
    "Discipline equals freedom. — Jocko Willink",
    "Well done is better than well said. — Franklin",
    "Energy and persistence conquer all. — Franklin",
    "You miss 100% of the shots you don't take. — Gretzky",
    "The secret of getting ahead is getting started. — Twain",
    "What you do today improves all your tomorrows. — Marston",
    "Start where you are, use what you have. — Arthur Ashe",
    "Excellence is the gradual result of striving. — Pat Riley",
    "Action is the foundational key to all success. — Picasso",
    "Diligence is the mother of good fortune. — Cervantes",
    "A river cuts through rock by persistence, not power.",
    "Great things never came from comfort zones.",
    "Fall seven times, stand up eight. — Japanese proverb",
    "The best way out is always through. — Robert Frost",
  ];
  const cheer = () => CHEERS[Math.floor(Math.random() * CHEERS.length)];

  // Tiny haptic helper — silent no-op on browsers without support
  // (every desktop, iOS Safari). Three patterns so we can vary feel.
  const HAPTIC = { tap: [10], pop: [12, 30, 18], swoosh: [22] };
  const buzz = (pat) => { try { navigator.vibrate?.(pat); } catch (_) {} };

  const markDone = async (it) => {
    buzz(HAPTIC.pop);
    try {
      if (window.dpParty) {
        window.dpParty(document.querySelector(`[data-id="${it.id}"]`), it.text);
      }
      await apiFetch(`/api/quick-bucket/${it.id}/done`, { method: "POST", body: "{}" });
      it.is_done = true;
      it.done_at = new Date().toISOString();
      // Server also clears top5_date/top5_position on done so the row
      // falls out of today's panel automatically. Mirror that locally
      // so the next render() drops it from the Top-5 list immediately
      // (otherwise it'd sit crossed-out until the next page load).
      it.top5_date = null;
      it.top5_position = null;
      toast(cheer(), "success");
      // Closed items stay in `items` so the Done group can render them.
      render();
      loadEffortSummary();  // done/undone flips the crossed-out styling
    } catch (err) {
      toast(err.message || "Couldn't mark done", "error");
    }
  };

  const reopen = async (it) => {
    try {
      await apiFetch(`/api/quick-bucket/${it.id}/reopen`, { method: "POST", body: "{}" });
      it.is_done = false;
      it.done_at = null;
      render();
      loadEffortSummary();
    } catch (err) {
      toast(err.message || "Couldn't reopen", "error");
    }
  };

  const archive = async (it) => {
    try {
      await apiFetch(`/api/quick-bucket/${it.id}/archive`, { method: "POST", body: "{}" });
      items = items.filter(x => x.id !== it.id);
      render();
      loadEffortSummary();  // an archived task leaves the day's totals
    } catch (err) {
      toast(err.message || "Couldn't remove", "error");
    }
  };

  // ─────────── Move-to-category modal ───────────────────────
  //
  // The user clicks the → icon on a row, picks a category, fills the
  // category-specific form, and hits Save & move. The bucket row is
  // archived; a real row is created in the destination module.

  const MOVE_CATEGORIES = [
    { key: "ProjectTask", label: "Project Task" },
    { key: "Checklist",   label: "Checklist" },
    { key: "TravelReads", label: "Travel & Reads" },
    { key: "Grocery",     label: "Grocery" },
  ];
  const MOVE_FIELDS = {
    Grocery: [
      { name: "item",     label: "Item",     type: "text",     fromText: true, required: true, max: 120 },
      { name: "quantity", label: "Quantity", type: "text",     placeholder: "e.g. 2 lb", max: 40 },
      { name: "category", label: "Aisle",    type: "select",   default: "other",
        options: ["produce","dairy","staples","snacks","household","spices","frozen","beverages","meat","bakery","other"] },
      { name: "priority", label: "Priority", type: "select",   default: "medium",
        options: ["high","medium","low"] },
      { name: "notes",    label: "Notes",    type: "textarea", wide: true, max: 400 },
    ],
    Checklist: [
      { name: "name",          label: "Name",         type: "text",     fromText: true, required: true, max: 200 },
      { name: "schedule",      label: "Schedule",     type: "select",   default: "daily",
        options: ["daily","weekdays","weekends","custom"] },
      { name: "time_of_day",   label: "When",         type: "select",   default: "anytime",
        options: ["morning","afternoon","evening","anytime"] },
      { name: "reminder_time", label: "Reminder",     type: "time" },
      // Default to "Tasks Bucket" so moved items group together on the
      // checklist page; the user can still rename to anything else.
      { name: "group_name",    label: "Group",        type: "text",     default: "Tasks Bucket" },
      { name: "notes",         label: "Notes",        type: "textarea", wide: true, max: 400 },
    ],
    TravelReads: [
      { name: "title",    label: "Title",    type: "text",     fromText: true, required: true, max: 200 },
      { name: "url",      label: "URL",      type: "url",      placeholder: "https://…", wide: true },
      { name: "kind",     label: "Kind",     type: "select",   default: "article",
        options: ["article","video","book","podcast","newsletter","documentary","other"] },
      { name: "priority", label: "Priority", type: "select",   default: "medium",
        options: ["high","medium","low"] },
      { name: "notes",    label: "Notes",    type: "textarea", wide: true },
    ],
    ProjectTask: [
      { name: "task_text",  label: "Title", type: "text", fromText: true, required: true, max: 500 },
      // The project dropdown is populated on modal open via
      // /api/quick-bucket/projects. When picked, the route endpoint
      // inserts into project_tasks (visible at /projects/<id>/tasks).
      // Leave blank to fall back to a Checklist row in the
      // "Project Tasks" group.
      { name: "project_id", label: "Project", type: "select-projects" },
      { name: "start_date", label: "Start date", type: "date" },
      { name: "notes",      label: "Notes", type: "textarea", wide: true, max: 400 },
    ],
  };

  let moveItem = null;
  let moveCategory = null;
  let projectsCache = null;  // {project_id, name}[] — lazy-loaded once per session

  const ensureProjectsLoaded = async () => {
    if (projectsCache !== null) return projectsCache;
    try {
      const r = await apiFetch("/api/quick-bucket/projects");
      projectsCache = (r && r.projects) || [];
    } catch (_) {
      projectsCache = [];
    }
    return projectsCache;
  };

  const renderMoveCategoryButtons = () => {
    const grid = $("#qb-move-cats");
    grid.innerHTML = MOVE_CATEGORIES.map(c =>
      `<button class="qb-cat-btn ${moveCategory === c.key ? 'is-current' : ''}" data-cat="${c.key}" type="button">${c.label}</button>`
    ).join("");
    $$(".qb-cat-btn", grid).forEach(btn => {
      btn.addEventListener("click", () => {
        // Clicking the same category twice clears it (text-edit only).
        moveCategory = (moveCategory === btn.dataset.cat) ? null : btn.dataset.cat;
        renderMoveCategoryButtons();
        renderMoveForm();
        updateSaveLabel();
      });
    });
  };

  const updateSaveLabel = () => {
    const lbl = $("#qb-move-save-label");
    if (!lbl) return;
    if (moveCategory && MOVE_FIELDS[moveCategory]) {
      const cat = MOVE_CATEGORIES.find(c => c.key === moveCategory);
      lbl.textContent = `Save & move to ${cat ? cat.label : moveCategory}`;
    } else {
      lbl.textContent = "Save";
    }
  };

  const renderMoveForm = () => {
    const wrap  = $("#qb-move-form-wrap");
    const form  = $("#qb-move-form");
    const note  = $("#qb-move-form-note");
    const title = $("#qb-move-form-title");
    const save  = $("#qb-move-save");

    if (!moveCategory) {
      // No category picked = text-only edit. submitEdit handles that
      // path explicitly, so the Save button must stay enabled —
      // disabling it here is what made "edit text and Save" do nothing.
      wrap.setAttribute("hidden", "");
      save.disabled = false;
      return;
    }
    const defs = MOVE_FIELDS[moveCategory];
    if (!defs) {
      wrap.removeAttribute("hidden");
      title.textContent = "Details";
      form.innerHTML = "";
      note.textContent = "This category isn't routable yet.";
      note.removeAttribute("hidden");
      // Same reasoning — submitEdit treats unroutable categories as
      // text-only saves, so leave the button clickable.
      save.disabled = false;
      return;
    }
    wrap.removeAttribute("hidden");
    title.textContent = `Move to ${MOVE_CATEGORIES.find(c => c.key === moveCategory)?.label || moveCategory}`;
    note.setAttribute("hidden", "");
    form.innerHTML = defs.map(d => {
      const wide = d.wide ? "qb-form-field--wide" : "";
      const placeholder = d.placeholder ? ` placeholder="${escapeHTML(d.placeholder)}"` : "";
      const max = d.max ? ` maxlength="${d.max}"` : "";
      const req = d.required ? " required" : "";
      const initial = d.fromText ? (moveItem?.text || "") : (d.default ?? "");
      let control;
      if (d.type === "select") {
        const opts = (d.options || []).map(o =>
          `<option value="${escapeHTML(o)}" ${String(initial) === String(o) ? "selected" : ""}>${escapeHTML(o)}</option>`
        ).join("");
        control = `<select name="${d.name}"${req}>${opts}</select>`;
      } else if (d.type === "select-projects") {
        // Populated async on modal open via ensureProjectsLoaded().
        const list = projectsCache || [];
        const opts = list.map(p =>
          `<option value="${escapeHTML(p.project_id)}">${escapeHTML(p.name || "(unnamed project)")}</option>`
        ).join("");
        const placeholderOpt = list.length
          ? `<option value="" selected>— pick a project —</option>`
          : `<option value="">No active projects (creates a Checklist row instead)</option>`;
        control = `<select name="${d.name}">${placeholderOpt}${opts}</select>`;
      } else if (d.type === "textarea") {
        control = `<textarea name="${d.name}" rows="3"${placeholder}${max}${req}>${escapeHTML(initial)}</textarea>`;
      } else {
        const t = (d.type === "url" || d.type === "time" || d.type === "date") ? d.type : "text";
        control = `<input type="${t}" name="${d.name}" value="${escapeHTML(initial)}"${placeholder}${max}${req}>`;
      }
      return `
        <div class="qb-form-field ${wide}">
          <label>${escapeHTML(d.label)}</label>
          ${control}
        </div>`;
    }).join("");
    save.disabled = false;
  };

  const openEditModal = (it) => {
    moveItem = it;
    moveCategory = null;
    const textInput = $("#qb-edit-text-input");
    if (textInput) textInput.value = it.text || "";
    // Effort fields.
    const plannedIn = $("#qb-edit-planned");
    const actualIn = $("#qb-edit-actual");
    const effDateIn = $("#qb-edit-effort-date");
    if (plannedIn) plannedIn.value = (it.planned_minutes != null ? it.planned_minutes : "");
    if (actualIn) actualIn.value = (it.actual_minutes != null ? it.actual_minutes : "");
    if (effDateIn) effDateIn.value = it.effort_date || (todayIso || new Date().toISOString().slice(0, 10));
    renderMoveCategoryButtons();
    renderMoveForm();
    updateSaveLabel();
    $("#qb-move-modal").classList.add("is-open");
    $("#qb-move-modal").setAttribute("aria-hidden", "false");
    refreshFeather();
    // Focus the textarea so the user can immediately start editing.
    setTimeout(() => textInput?.focus(), 30);

    // Lazy-fetch projects so picking ProjectTask category gets a real
    // dropdown without an empty-flash on first open. If user picks
    // ProjectTask before the fetch finishes, renderMoveForm rerenders
    // once the cache is populated.
    if (projectsCache === null) {
      ensureProjectsLoaded().then(() => {
        if (moveItem === it && moveCategory === "ProjectTask") {
          renderMoveForm();
        }
      });
    }
  };

  const closeEditModal = () => {
    $("#qb-move-modal").classList.remove("is-open");
    $("#qb-move-modal").setAttribute("aria-hidden", "true");
    moveItem = null;
    moveCategory = null;
  };

  const submitEdit = async () => {
    if (!moveItem) return;
    const newText = ($("#qb-edit-text-input")?.value || "").trim();
    if (!newText) {
      toast("Task text can't be empty", "error");
      return;
    }
    const save = $("#qb-move-save");
    save.disabled = true;
    try {
      // Always persist text edits first — even if we're also routing,
      // this keeps the bucket row coherent if the route call fails.
      if (newText !== moveItem.text) {
        await apiFetch(`/api/quick-bucket/${moveItem.id}/update`, {
          method: "POST", body: JSON.stringify({ text: newText }),
        });
        moveItem.text = newText;
      }

      // Persist effort (planned / actual minutes + date) whenever any of
      // them changed, so the daily planned-vs-actual summary stays right.
      const parseMin = (v) => {
        const s = (v == null ? "" : v).toString().trim();
        if (s === "") return null;
        const n = Number(s);
        return Number.isFinite(n) && n >= 0 ? Math.round(n) : null;
      };
      const intOrNull = (v) => (v == null ? null : Math.round(Number(v)));
      const planned = parseMin($("#qb-edit-planned")?.value);
      const actual = parseMin($("#qb-edit-actual")?.value);
      const pickedDate = ($("#qb-edit-effort-date")?.value || "").trim() || null;
      const hasEffort = planned != null || actual != null;
      // No minutes → clear the date so the task drops out of every day's
      // summary. Minutes with no date → count for today.
      const effDate = hasEffort
        ? (pickedDate || todayIso || new Date().toISOString().slice(0, 10))
        : null;
      const curPlanned = intOrNull(moveItem.planned_minutes);
      const curActual = intOrNull(moveItem.actual_minutes);
      const curDate = moveItem.effort_date || null;
      if (planned !== curPlanned || actual !== curActual || effDate !== curDate) {
        await apiFetch(`/api/quick-bucket/${moveItem.id}/update`, {
          method: "POST",
          body: JSON.stringify({ planned_minutes: planned, actual_minutes: actual, effort_date: effDate }),
        });
        moveItem.planned_minutes = planned;
        moveItem.actual_minutes = actual;
        moveItem.effort_date = effDate;
      }

      // No category picked → text/effort edit only, we're done.
      if (!moveCategory || !MOVE_FIELDS[moveCategory]) {
        toast("Saved", "success");
        closeEditModal();
        render();
        loadEffortSummary();
        return;
      }

      // Category picked → also route into the destination module.
      const defs = MOVE_FIELDS[moveCategory];
      const form = $("#qb-move-form");
      const fd = new FormData(form);
      const fields = {};
      for (const [k, v] of fd.entries()) fields[k] = v;
      // Title-ish field is overridden with the latest textarea value
      // so editing the text in the textarea wins over the original
      // pre-fill in the form.
      for (const d of defs) {
        if (d.fromText) { fields[d.name] = newText; break; }
      }
      for (const d of defs) {
        if (d.required && !(fields[d.name] || "").trim()) {
          toast(`${d.label} is required`, "error");
          save.disabled = false;
          return;
        }
      }
      const r = await apiFetch(`/api/quick-bucket/${moveItem.id}/route`, {
        method: "POST",
        body: JSON.stringify({ category: moveCategory, fields }),
      });
      // Friendlier "where did it go?" message — name the actual page
      // the user can open to find it.
      let where = "";
      switch (r.destination_table) {
        case "project_tasks":
          // Find the picked project's name from the cache for context.
          const picked = (projectsCache || []).find(p => p.project_id === fields.project_id);
          where = picked
            ? `Moved to project "${picked.name}" (open Projects → ${picked.name})`
            : "Moved to project tasks";
          break;
        case "checklist_items":
          where = `Moved to Checklist (group: ${fields.group_name || "Tasks Bucket"})`;
          break;
        case "groceries":     where = "Moved to Grocery"; break;
        case "travel_reads":  where = "Moved to Travel & Reads"; break;
        default:              where = `Moved to ${(r.destination_table || "").replace("_", " ")}`;
      }
      toast(where, "success");
      items = items.filter(x => x.id !== moveItem.id);
      closeEditModal();
      render();
    } catch (err) {
      toast(err.message || "Couldn't save", "error");
    } finally {
      save.disabled = false;
    }
  };

  const wireMoveModal = () => {
    $("#qb-move-close").addEventListener("click", closeEditModal);
    $("#qb-move-cancel").addEventListener("click", closeEditModal);
    $("#qb-move-save").addEventListener("click", submitEdit);
    // Re-fetch the daily summary when the user picks a different day.
    $("#qb-eff-date")?.addEventListener("change", loadEffortSummary);

    // Collapsible "Productive time" card — state persists across loads.
    const effCard = $("#qb-effort-summary");
    const effToggle = $("#qb-eff-toggle");
    if (effCard && effToggle) {
      const KEY = "qb_eff_collapsed";
      const setCollapsed = (on) => {
        effCard.classList.toggle("is-collapsed", on);
        effToggle.setAttribute("aria-expanded", on ? "false" : "true");
      };
      let stored = false;
      try { stored = localStorage.getItem(KEY) === "1"; } catch (_) {}
      setCollapsed(stored);
      effToggle.addEventListener("click", () => {
        const on = !effCard.classList.contains("is-collapsed");
        setCollapsed(on);
        try { localStorage.setItem(KEY, on ? "1" : "0"); } catch (_) {}
      });
    }
    $("#qb-move-modal").addEventListener("click", (e) => {
      if (e.target.id === "qb-move-modal") closeEditModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeEditModal();
    });
  };

  // Natural-language time parser. Recognises phrases like:
  //   "...in 30 mins"        → bucket="30m"
  //   "...in 2 hours"        → bucket="2h"
  //   "...now"               → bucket="now"
  //   "...tomorrow"          → bucket="future"
  //   "...later" / "...soon" → bucket="now" (no change)
  // Returns { text, bucket } — text has the matched phrase stripped.
  // Anchored to end-of-string so we don't eat content out of the title.
  const _NL_PATTERNS = [
    { re: /\s+(?:in\s+)?(\d+)\s*(?:m|min|mins|minute|minutes)\s*$/i,
      pick: (m) => {
        const n = parseInt(m[1], 10);
        if (n <= 7)  return "5m";
        if (n <= 22) return "15m";
        if (n <= 37) return "30m";
        if (n <= 50) return "45m";
        return Math.min(8, Math.max(1, Math.round(n / 60))) + "h";
      } },
    { re: /\s+(?:in\s+)?(\d+)\s*(?:h|hr|hrs|hour|hours)\s*$/i,
      pick: (m) => `${Math.min(8, Math.max(1, parseInt(m[1], 10)))}h` },
    { re: /\s+(?:right\s+)?now\s*$/i,           pick: () => "now" },
    { re: /\s+(?:later|tomorrow|next\s+week)\s*$/i, pick: () => "future" },
  ];
  const parseNlBucket = (raw) => {
    const t = (raw || "").trim();
    for (const { re, pick } of _NL_PATTERNS) {
      const m = t.match(re);
      if (m) return { text: t.slice(0, m.index).trim(), bucket: pick(m) };
    }
    return { text: t, bucket: null };
  };

  // "@" duration shorthand: type "@5m" / "@1h" / "@1d" anywhere in the
  // title to set when. m/M = minutes (snaps to 5/15/30/45 m bucket),
  // h/H = hours (clamped 1h..8h), d/D = day(s) → future. The token is
  // stripped from the saved text. Examples:
  //   "Call dad @5m"   → bucket="5m", text="Call dad"
  //   "Pay bill @2H"   → bucket="2h", text="Pay bill"
  //   "@1d Read book"  → bucket="future", text="Read book"
  const _AT_RE = /(?:^|\s)@(\d+)\s*([mhd])(?![a-z])/i;
  const parseAtBucket = (raw) => {
    const t = (raw || "").trim();
    const m = t.match(_AT_RE);
    if (!m) return { text: t, bucket: null };
    const n = parseInt(m[1], 10);
    const unit = m[2].toLowerCase();
    let bucket;
    if (unit === "d") {
      bucket = "future";
    } else if (unit === "h") {
      bucket = `${Math.min(8, Math.max(1, n))}h`;
    } else {
      if (n <= 7)        bucket = "5m";
      else if (n <= 22)  bucket = "15m";
      else if (n <= 37)  bucket = "30m";
      else if (n <= 50)  bucket = "45m";
      else               bucket = `${Math.min(8, Math.max(1, Math.round(n / 60)))}h`;
    }
    const matchStart = m.index + (m[0].startsWith(" ") ? 1 : 0);
    const matchEnd   = m.index + m[0].length;
    const cleaned = (t.slice(0, matchStart) + " " + t.slice(matchEnd))
      .replace(/\s+/g, " ").trim();
    return { text: cleaned, bucket };
  };

  const addItem = async (text, opts = {}) => {
    text = (text || "").trim();
    if (!text) return;
    // A clock-time token like "@1pm today" / "@13:00" pins an ABSOLUTE
    // time and is resolved server-side (it sets due_at + an "at" bucket
    // and strips the token). Detect it here and skip the relative
    // parsers so they don't eat the day word ("tomorrow" → future) or
    // the raw text before the backend sees it.
    const hasClockAt = /@\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)\b/i.test(text) ||
                       /@\s*\d{1,2}:\d{2}\b/.test(text);
    // Parse "@5m" / "@1h" / "@1d" first so it wins over the looser NL
    // parser ("in 30 mins" etc). Caller can still pre-pick a bucket
    // (e.g. Top-5 add) — that wins over both.
    let bucket = opts.bucket || null;
    if (!bucket && !hasClockAt) {
      const at = parseAtBucket(text);
      if (at.bucket) { text = at.text; bucket = at.bucket; }
    }
    if (!bucket && !hasClockAt) {
      const parsed = parseNlBucket(text);
      if (parsed.bucket) { text = parsed.text; bucket = parsed.bucket; }
    }
    if (!bucket) bucket = "now";
    // Default the round priority badge to max+1 across currently-open
    // rows. Caller can override via opts.priority_label.
    const priorityLabel = opts.priority_label || nextPriorityLabelForNew();
    // Generate the client id up front so we can tie the optimistic row
    // to the eventual server response when the queue replays.
    const clientId = (crypto.randomUUID && crypto.randomUUID()) ||
                     String(Date.now()) + "-" + Math.random().toString(16).slice(2);
    try {
      // Extras only ever arrive from the paragraph reader's preview,
      // where the server resolved the time and the user confirmed it on
      // screen. Absent for everything typed by hand, which is why they
      // are spread in rather than always sent as nulls.
      const extra = {};
      if (opts.due_at) extra.due_at = opts.due_at;
      if (opts.backlog_due) extra.backlog_due = opts.backlog_due;
      if (opts.planned_minutes) extra.planned_minutes = opts.planned_minutes;
      const r = await apiFetch("/api/quick-bucket", {
        method: "POST",
        headers: { "X-Client-Id": clientId },
        body: JSON.stringify(Object.assign({
          text, time_bucket: bucket, client_id: clientId,
          priority_label: priorityLabel,
        }, extra)),
      });
      if (r.item) {
        items.unshift(r.item);
        render();
        // Confirm a scheduled item so the user knows the alarm is set.
        if (!opts.quiet && r.item.time_bucket === "at" && r.item.due_at) {
          const when = new Date(r.item.due_at).toLocaleString([], {
            weekday: "short", hour: "numeric", minute: "2-digit",
          });
          toast(`⏰ Scheduled for ${when} — alarm set`, "success");
        }
      } else if (r.queued) {
        // Optimistic insert: temporary row that looks real but is
        // tagged so the SW reconciler can swap it for the server row.
        items.unshift({
          id: `pending:${clientId}`,
          _pending: true,
          client_id: clientId,
          text,
          time_bucket: bucket,
          priority_label: priorityLabel,
          due_at: null,
          done_at: null,
          archived_at: null,
        });
        render();
        if (!opts.quiet && window.showToast) showToast("Saved offline — will sync", "info", 2200);
      }
    } catch (err) {
      toast(err.message || "Couldn't add", "error");
    }
  };

  /* PASTE A LAUNDRY LIST — one item per line.
     The capture field is already a textarea (Shift+Enter keeps a newline),
     but everything typed into it became ONE row, so pasting twenty things
     to get out of your head produced one item containing twenty lines.
     That is the opposite of what a bucket is for.

     Adds each line through addItem(), rather than a bulk endpoint, so every
     line still gets the full treatment: the "@1h" and "tomorrow" bucket
     parsing, the offline queue, the client-id dedupe. A separate bulk path
     would have to reimplement all of it and would drift.

     ONE line is the overwhelmingly common case and behaves exactly as
     before — no summary toast, no change at all. */
  const addLines = async (raw) => {
    const lines = String(raw || "")
      .split(/\r?\n/)
      .map(function (l) { return l.trim(); })
      .filter(Boolean);

    if (lines.length <= 1) { await addItem(raw); return; }

    let added = 0;
    for (const line of lines) {
      // Sequential on purpose: the priority badge is computed from the rows
      // already present, so firing them in parallel would hand several
      // items the same number.
      await addItem(line, { quiet: true });
      added++;
    }
    toast(`Added ${added} items`, "success");
  };

  // SW reports back when a queued write actually lands on the server.
  // Replace the optimistic placeholder with the real row, if we have
  // the canonical record; otherwise just reload from the server.
  if (window.dpSync && window.dpSync.onResult) {
    window.dpSync.onResult((r) => {
      if (!r || !r.ok) return;
      const idx = items.findIndex((it) => it && it.client_id === r.clientId);
      if (idx >= 0) {
        const serverItem = r.body && r.body.item;
        if (serverItem) items[idx] = serverItem;
        else items.splice(idx, 1);
        render();
      } else {
        // Couldn't find a placeholder — safest is a fresh fetch.
        loadItems();
      }
    });
  }

  // ─────────── Pomodoro timer ───────────────────────────────
  //
  // State machine: idle → running → (paused | ended). Reset goes back
  // to idle. Persisted to localStorage so a refresh mid-session keeps
  // ticking. We store the absolute end timestamp while running, so
  // closing the tab and re-opening it resyncs to wall-clock time.

  const POMO_KEY = "qb-pomo-v1";
  const POMO_TICK_MS = 500;
  const POMO_PRESETS = [15, 25, 50, 90];
  const POMO_DEFAULT_MIN = 25;
  const PAGE_TITLE = "Quick Bucket — DailyPlanner";

  let pomo = {
    durationMins: POMO_DEFAULT_MIN,
    state: "idle",                                    // idle | running | paused | ended
    endsAt: null,                                     // ms timestamp; only set when running
    remaining: POMO_DEFAULT_MIN * 60 * 1000,          // ms; valid when paused/idle
    label: null,                                      // what the user is focusing on
    serverLogId: null,                                // task_time_logs row id (server-side mirror)
  };
  let pomoTimer = null;

  const loadPomo = () => {
    try {
      const raw = localStorage.getItem(POMO_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (saved && typeof saved === "object") Object.assign(pomo, saved);
    } catch (_) { /* corrupt → keep defaults */ }
  };
  const savePomo = () => {
    try { localStorage.setItem(POMO_KEY, JSON.stringify(pomo)); } catch (_) {}
  };

  const pomoMsRemaining = () => {
    if (pomo.state === "running" && pomo.endsAt) {
      return Math.max(0, pomo.endsAt - Date.now());
    }
    return Math.max(0, pomo.remaining || 0);
  };

  const fmtClock = (ms) => {
    const totalSec = Math.ceil(ms / 1000);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  };

  const renderPomo = () => {
    const root = $("#qb-pomo");
    if (!root) return;
    const ms = pomoMsRemaining();
    $("#qb-pomo-time").textContent = fmtClock(ms);

    const playBtn = $("#qb-pomo-play");
    const playing = pomo.state === "running";
    playBtn.innerHTML = `<i data-feather="${playing ? "pause" : "play"}"></i>`;
    playBtn.title = playing ? "Pause" : (pomo.state === "paused" ? "Resume" : "Start");

    // Stop button stays a square always; tint red while there's an
    // in-flight session (running or paused) so it's obviously the way
    // to end. When idle/ended it acts as a quiet "clear".
    const stopBtn = $("#qb-pomo-reset");
    if (stopBtn) {
      const hasSession = playing || pomo.state === "paused";
      stopBtn.classList.toggle("is-active", hasSession);
      stopBtn.title = hasSession
        ? "Stop & save partial focus"
        : (pomo.state === "ended" ? "Clear" : "Reset");
    }

    root.classList.toggle("is-running", playing);
    root.classList.toggle("is-ended", pomo.state === "ended");

    // Trigger button on the stats card mirrors the timer state so the
    // user can see the countdown at a glance even when the popup is
    // closed.
    const trigger = $("#qb-focus-trigger");
    const triggerLbl = $("#qb-focus-trigger-label");
    if (trigger && triggerLbl) {
      trigger.classList.toggle("is-running", playing);
      trigger.classList.toggle("is-ended", pomo.state === "ended");
      if (playing) {
        triggerLbl.textContent = pomo.label
          ? `Pomodoro · ${fmtClock(ms)} · ${pomo.label}`
          : `Pomodoro · ${fmtClock(ms)}`;
      } else if (pomo.state === "paused") {
        triggerLbl.textContent = `Pomodoro · paused · ${fmtClock(ms)}`;
      } else {
        // Idle, ended, and any other non-running/non-paused state all
        // show the same neutral "Pomodoro" label — once the session is
        // over there is nothing meaningful to convey beyond "ready for
        // the next one". (Was "Pomodoro done", which felt like a stuck
        // status badge after the user had already acknowledged it.)
        triggerLbl.textContent = "Pomodoro";
      }
    }

    // Inline title field lives in the popup itself. While running or
    // paused, lock it (readonly) so the title can't drift mid-session;
    // on idle/ended, allow editing for the next session. pomoReset and
    // pomoEnd explicitly clear the input value when they fire.
    const inlineTitle = $("#qb-pomo-inline-title");
    if (inlineTitle) {
      const locked = playing || pomo.state === "paused";
      inlineTitle.readOnly = locked;
      // While locked, mirror the saved label into the input so it
      // stays visible. While editable, leave whatever the user is
      // typing alone.
      if (locked && pomo.label && inlineTitle.value !== pomo.label) {
        inlineTitle.value = pomo.label;
      }
    }

    $$(".qb-pomo-dur").forEach(b => {
      b.classList.toggle("is-current", Number(b.dataset.min) === pomo.durationMins);
    });

    // Tab title: keep the countdown visible when the page is in the
    // background. Restore on idle/paused/ended.
    if (playing) {
      const tail = pomo.label ? ` — ${pomo.label}` : " • Pomodoro";
      document.title = `${fmtClock(ms)}${tail}`;
    } else {
      document.title = PAGE_TITLE;
    }

    refreshFeather();

    // Phase ended while running → fire once.
    if (playing && ms <= 0) pomoEnd();
  };

  const startPomoTicker = () => {
    if (pomoTimer) clearInterval(pomoTimer);
    pomoTimer = setInterval(renderPomo, POMO_TICK_MS);
  };
  const stopPomoTicker = () => {
    if (pomoTimer) { clearInterval(pomoTimer); pomoTimer = null; }
  };

  // Reads the inline title input. Returns the trimmed value, or "" if
  // empty. On empty, briefly shakes/highlights the field so the user
  // sees they need to fill it in before pressing play.
  const readInlineTitle = () => {
    const input = $("#qb-pomo-inline-title");
    if (!input) return "";
    const v = (input.value || "").trim();
    if (!v) {
      input.classList.remove("is-shake");
      // Force reflow so the animation re-runs on repeated empty taps.
      void input.offsetWidth;
      input.classList.add("is-shake");
      setTimeout(() => input.classList.remove("is-shake"), 400);
      input.focus();
    }
    return v;
  };

  const pomoStart = async () => {
    if (pomo.state === "running") return;

    // First-time start → read the title from the inline input. Resuming
    // a paused session (label already set) skips this so the play/pause
    // toggle stays one-tap.
    const isResume = pomo.state === "paused" && !!pomo.label;
    if (!isResume) {
      const title = readInlineTitle();
      if (!title) return;  // empty: shake-feedback already fired
      pomo.label = title.slice(0, 200);
    }

    const ms = pomo.state === "paused"
      ? Math.max(0, pomo.remaining)
      : pomo.durationMins * 60 * 1000;
    if (ms <= 0) {
      // Resuming a finished timer → restart fresh.
      pomo.remaining = pomo.durationMins * 60 * 1000;
    }
    pomo.state = "running";
    pomo.endsAt = Date.now() + (pomo.remaining > 0 ? pomo.remaining : pomo.durationMins * 60 * 1000);
    pomo.remaining = pomo.endsAt - Date.now();

    // Open a server-side log so this session lands in the Focus Log.
    // Skipped on resume (we already have a log id from the original
    // start). Best-effort — local timer keeps working if the API fails.
    if (!pomo.serverLogId) {
      try {
        const r = await apiFetch("/api/v2/timer/start", {
          method: "POST",
          body: JSON.stringify({
            source: "adhoc",
            label: pomo.label,
            mode: "pomodoro",
            target_seconds: pomo.durationMins * 60,
          }),
        });
        pomo.serverLogId = (r && r.id) || null;
      } catch (err) {
        console.warn("pomodoro: server log start failed", err);
      }
    }

    savePomo();
    startPomoTicker();
    renderPomo();
  };

  const closeServerLog = async () => {
    if (!pomo.serverLogId) return;
    const id = pomo.serverLogId;
    pomo.serverLogId = null;
    try {
      await apiFetch("/api/v2/timer/stop", {
        method: "POST", body: JSON.stringify({ id }),
      });
    } catch (err) {
      console.warn("pomodoro: server log stop failed", err);
    }
  };

  // Compute how many ms have elapsed in the current Pomodoro session,
  // taking into account whether the timer is running (use endsAt) or
  // paused (use remaining).
  const pomoElapsedMs = () => {
    const dur = pomo.durationMins * 60 * 1000;
    if (pomo.state === "running" && pomo.endsAt) {
      return Math.max(0, dur - Math.max(0, pomo.endsAt - Date.now()));
    }
    if (pomo.state === "paused") {
      return Math.max(0, dur - Math.max(0, pomo.remaining || 0));
    }
    if (pomo.state === "ended") return dur;
    return 0;
  };

  // Drop a Done-marked entry into the Tasks Bucket so today's focus
  // sessions are visible inline. Best-effort — failures don't block
  // the rest of the Pomodoro lifecycle.
  const recordFocusInDone = async (label, elapsedMs) => {
    if (!label || elapsedMs < 30_000) return;  // ignore <30s blips
    const minutes = Math.round(elapsedMs / 60_000);
    const elapsedText = minutes >= 60
      ? `${Math.floor(minutes / 60)}h ${minutes % 60}m`
      : `${minutes}m`;
    // Cleaner format: the task title stays a normal-looking line, the
    // Pomodoro suffix is small and parenthetical so it reads like any
    // other completed task in the Done section.
    const text = `${label} (Pomodoro · ${elapsedText})`;
    try {
      const r = await apiFetch("/api/quick-bucket", {
        method: "POST",
        body: JSON.stringify({ text, time_bucket: "future", is_done: true }),
      });
      if (r && r.item) {
        items.unshift(r.item);
        render();
      }
    } catch (err) {
      console.warn("pomodoro: focus-done insert failed", err);
    }
  };

  const pomoPause = () => {
    if (pomo.state !== "running") return;
    pomo.remaining = Math.max(0, pomo.endsAt - Date.now());
    pomo.state = "paused";
    pomo.endsAt = null;
    savePomo();
    stopPomoTicker();
    renderPomo();
  };

  const pomoToggle = () => {
    if (pomo.state === "running") pomoPause();
    else pomoStart();
  };

  const pomoReset = async () => {
    // Capture state BEFORE closing the log, so a partial session can
    // also land in the Done section with the right minutes count.
    const elapsedBefore = pomoElapsedMs();
    const labelBefore = pomo.label;

    await closeServerLog();
    if (labelBefore && elapsedBefore > 30_000) {
      recordFocusInDone(labelBefore, elapsedBefore);
    }

    pomo.state = "idle";
    pomo.endsAt = null;
    pomo.remaining = pomo.durationMins * 60 * 1000;
    pomo.label = null;
    const inlineTitle = $("#qb-pomo-inline-title");
    if (inlineTitle) inlineTitle.value = "";
    savePomo();
    stopPomoTicker();
    renderPomo();
  };

  const pomoSetDuration = (mins) => {
    pomo.durationMins = mins;
    // If we're idle/ended, snap the visible clock to the new length.
    // Don't reach into a running session — it'll keep its current end.
    if (pomo.state !== "running") {
      pomo.remaining = mins * 60 * 1000;
      pomo.state = "idle";
      pomo.endsAt = null;
    }
    savePomo();
    renderPomo();
  };

  const pomoEnd = async () => {
    const finishedLabel = pomo.label;
    const fullDurationMs = pomo.durationMins * 60 * 1000;
    // Close the server log first so the focus session lands in the Focus
    // Log with the right duration. Errors here are non-fatal.
    await closeServerLog();
    if (finishedLabel) {
      recordFocusInDone(finishedLabel, fullDurationMs);
    }
    pomo.state = "ended";
    pomo.remaining = 0;
    pomo.endsAt = null;
    // Clear label so the next Start prompts for a fresh activity.
    pomo.label = null;
    const inlineTitle = $("#qb-pomo-inline-title");
    if (inlineTitle) inlineTitle.value = "";
    savePomo();
    stopPomoTicker();
    pomoBeep();
    const what = finishedLabel ? ` — ${finishedLabel}` : "";
    toast(`✅ ${pomo.durationMins}-minute focus complete${what}`, "success");
    if ("Notification" in window && Notification.permission === "granted") {
      try {
        new Notification("Pomodoro done", {
          body: `${pomo.durationMins}-minute focus complete${what}`,
        });
      } catch (_) {}
    }
    renderPomo();
  };

  // Short tone via Web Audio — no audio file dependency.
  const pomoBeep = () => {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      const beepAt = (freq, t0, dur = 0.18) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.type = "sine";
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.0001, ctx.currentTime + t0);
        gain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + t0 + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + t0 + dur);
        osc.start(ctx.currentTime + t0);
        osc.stop(ctx.currentTime + t0 + dur + 0.02);
      };
      // Two-note chime so the end is distinct from the deadline alert.
      beepAt(880, 0);
      beepAt(1320, 0.22);
      setTimeout(() => ctx.close(), 800);
    } catch (_) {}
  };

  const openPomoPopup = () => {
    const m = $("#qb-pomo-popup");
    if (!m) return;
    m.classList.add("is-open");
    m.setAttribute("aria-hidden", "false");
    refreshFeather();
    // Focus the inline title field if it's editable so the user can
    // start typing the focus title immediately.
    const input = $("#qb-pomo-inline-title");
    if (input && !input.readOnly) {
      setTimeout(() => input.focus(), 30);
    }
  };
  const closePomoPopup = () => {
    const m = $("#qb-pomo-popup");
    if (!m) return;
    m.classList.remove("is-open");
    m.setAttribute("aria-hidden", "true");
  };

  const wirePomo = () => {
    $("#qb-pomo-play").addEventListener("click", () => {
      pomoToggle();
      // First user gesture is a good moment to ask for Notification
      // permission so the end-of-Pomodoro notification can fire.
      if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission().catch(() => {});
      }
    });
    $("#qb-pomo-reset").addEventListener("click", pomoReset);
    $$(".qb-pomo-dur").forEach(b => {
      b.addEventListener("click", () => pomoSetDuration(Number(b.dataset.min)));
    });

    // Plain Enter inside the inline title triggers Start; Shift+Enter
    // inserts a newline so long activity titles can wrap.
    $("#qb-pomo-inline-title")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (pomo.state !== "running") pomoStart();
      }
    });

    // Trigger button on the stats card opens the timer popup. The
    // timer keeps ticking even when the popup is closed; the trigger
    // label mirrors the running countdown.
    $("#qb-focus-trigger")?.addEventListener("click", openPomoPopup);
    $("#qb-pomo-popup-close")?.addEventListener("click", closePomoPopup);
    $("#qb-pomo-popup")?.addEventListener("click", (e) => {
      if (e.target.id === "qb-pomo-popup") closePomoPopup();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closePomoPopup();
    });
  };

  // ─────────── countdown ticker + overdue alerts ────────────

  const fireOverdueAlert = (it) => {
    toast(`⏰ Overdue: ${it.text}`, "error");
    // Use the browser Notification API too if the user has granted
    // permission elsewhere — handy when the tab is in the background.
    if ("Notification" in window && Notification.permission === "granted") {
      try { new Notification("Quick Bucket — overdue", { body: it.text }); } catch (_) {}
    }
  };

  const tick = () => {
    let anyOverdueChanged = false;
    items.forEach(it => {
      if (!isCountedDown(it)) return;
      const overdue = isOverdue(it);
      if (overdue && !alerted.has(it.id)) {
        alerted.add(it.id);
        fireOverdueAlert(it);
        anyOverdueChanged = true;
      }
    });
    // Re-render unconditionally — countdown labels need updating each
    // tick, and re-render is cheap (no API call).
    render();
  };

  const startTicker = () => {
    if (tickTimer) clearInterval(tickTimer);
    tickTimer = setInterval(tick, TICK_MS);
    // Also re-tick when the tab regains focus, since setInterval is
    // throttled in background tabs.
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) tick();
    });
  };

  // ─────────── boot ─────────────────────────────────────────

  // Top-5 collapse state — persisted across sessions in localStorage.
  // Default: collapsed on narrow viewports (where the Top-5 panel
  // pushes the Now group well below the fold), expanded on wider
  // screens (where the panel sits side-by-side and doesn't cost
  // scroll). Once the user toggles, their choice wins on every device.
  const QB_TOP5_COLLAPSED_KEY = "qb.top5.collapsed";
  const wireTop5Collapse = () => {
    const panel = $("#qb-top5");
    const btn   = $("#qb-top5-toggle");
    if (!panel || !btn) return;
    const apply = (collapsed) => {
      panel.classList.toggle("is-collapsed", collapsed);
      btn.setAttribute("aria-expanded", String(!collapsed));
    };
    let stored;
    try { stored = localStorage.getItem(QB_TOP5_COLLAPSED_KEY); } catch (_) {}
    let collapsed;
    if (stored === "1") collapsed = true;
    else if (stored === "0") collapsed = false;
    else collapsed = window.matchMedia("(max-width: 759px)").matches;
    apply(collapsed);
    btn.addEventListener("click", () => {
      collapsed = !collapsed;
      apply(collapsed);
      try { localStorage.setItem(QB_TOP5_COLLAPSED_KEY, collapsed ? "1" : "0"); } catch (_) {}
    });
  };

  document.addEventListener("DOMContentLoaded", async () => {
    refreshFeather();

    // Pomodoro: hydrate from localStorage. If the timer was running
    // when the user closed the tab, the absolute end timestamp picks
    // up where they left off (or fires the end immediately if the
    // session has already elapsed).
    loadPomo();
    wirePomo();
    wireMoveModal();
    wireTop5Collapse();
    if (pomo.state === "running") {
      if (pomo.endsAt && pomo.endsAt > Date.now()) {
        startPomoTicker();
      } else {
        pomoEnd();
      }
    }
    renderPomo();

    const form = $("#qb-add-form");
    const input = $("#qb-add-input");

    // The capture field is now a <textarea>, so it would insert a
    // literal newline on Enter and never fire form submit. Bind Enter
    // → submit (Shift+Enter keeps the newline) and auto-grow the box
    // up to the CSS max-height so multi-line capture has room.
    const autosizeInput = () => {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 240) + "px";
    };
    input.addEventListener("input", autosizeInput);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        form.requestSubmit();
      }
    });

    // Re-focus the input on desktop so the next capture is one keystroke
    // away. On phones / tablets that would re-summon the soft keyboard
    // after every add, which is annoying — blur instead so the keyboard
    // collapses and the list stays visible.
    const wantsKeyboardRefocus = !!(window.matchMedia &&
      window.matchMedia("(hover: hover) and (pointer: fine)").matches);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = input.value;
      /* ADD SHOWS YOU WHAT IT UNDERSTOOD, unless there is nothing to
         understand. "call mum" is a task and a dialog asking you to
         confirm it is an insult; anything with a comma, a number, a
         second line or real length has been INTERPRETED, and an
         interpretation you cannot see before it is saved is the thing
         this feature exists to avoid.

         Nothing is consumed by the check: if the reader is unreachable
         or finds nothing worth confirming, the ordinary add runs on the
         same keystroke and the text is still in the box either way. */
      const t = v.trim();
      const plainOneLiner =
        !/[\n,;.]/.test(t) && !/\d/.test(t) && t.split(/\s+/).length <= 12;
      if (t && !plainOneLiner) {
        if (await offerToRead(t)) return;          // the dialog is up
      }
      input.value = "";
      autosizeInput();
      if (wantsKeyboardRefocus) input.focus();
      else input.blur();
      await addLines(v);
    });

    /* ── READ A PARAGRAPH ────────────────────────────────────────────
       "Is there a way i can type something like a paragraph. Code can
       decipher and create tasks on quickbucket."

       The server does the deciphering (/api/quick-bucket/interpret,
       utils/brain_dump.py) and writes NOTHING. What comes back is a
       preview: one editable row per task it thinks it found, each one
       carrying the words that produced its bucket and its time. Adding
       goes through the ordinary addItem path, so a confirmed row is
       indistinguishable from one typed by hand.

       This is also what makes dictation useful. Speech arrives as one
       unpunctuated paragraph, which is precisely the shape the old
       capture was worst at. */
    const READ_BUCKETS = ["now", "5m", "15m", "30m", "45m",
                          "1h", "2h", "3h", "4h", "5h", "6h", "7h", "8h",
                          "future"];
    const readPanel = $("#qb-read");
    const readList = $("#qb-read-list");
    const readBtn = $("#qb-read-btn");
    let readItems = [];

    const whenLabel = (it) => {
      if (it.due_at) {
        const d = new Date(it.due_at);
        if (!Number.isNaN(d.getTime())) {
          return "⏰ " + d.toLocaleString([], {
            weekday: "short", hour: "numeric", minute: "2-digit",
          });
        }
      }
      if (it.backlog_due) return "📅 by " + it.backlog_due;
      return "";
    };

    const readRowHTML = (it, i) => {
      const opts = READ_BUCKETS.map((b) =>
        `<option value="${b}"${b === it.time_bucket ? " selected" : ""}>${b}</option>`
      ).join("");
      const atOpt = it.due_at
        ? `<option value="at" selected>at a set time</option>` : "";
      return `
        <li class="qb-read-row${it.use ? "" : " is-off"}" data-i="${i}">
          <input type="checkbox" data-read-use ${it.use ? "checked" : ""}
                 aria-label="Add this one">
          <input class="qb-read-text" data-read-text
                 value="${escapeHTML(it.text)}" aria-label="Task">
          <span class="qb-read-controls">
            <select data-read-bucket aria-label="When">${atOpt}${opts}</select>
            <input class="qb-read-mins" data-read-mins type="number" min="0"
                   step="5" placeholder="mins" aria-label="Minutes of effort"
                   value="${it.planned_minutes || ""}">
          </span>
          <p class="qb-read-why">
            ${it.due_at || it.backlog_due
              ? `<span class="qb-read-when">${escapeHTML(whenLabel(it))}</span> · ` : ""}
            ${escapeHTML((it.why || []).join(" · "))}
          </p>
        </li>`;
    };

    const readCount = () => readItems.filter((it) => it.use).length;

    const paintReadFoot = () => {
      const n = readCount();
      const addBtn = $("#qb-read-add");
      addBtn.textContent = n ? `Add ${n} task${n === 1 ? "" : "s"}` : "Nothing ticked";
      addBtn.disabled = !n;
    };

    /* OPEN AND CLOSE AS A DIALOG.
       Closing NEVER clears the box: if the split is wrong, what you
       typed has to still be there to fix by hand. Escape and a click on
       the backdrop both close, because a modal with only an X is a trap
       on a phone. */
    // Escape is bound locally rather than through ptOnEscape: this page
    // does not load pt-shared.js, and a dialog whose only exit is a
    // 16px X in the corner is a trap.
    const onReadKey = (e) => { if (e.key === "Escape") closeRead(); };
    const openRead = () => {
      readPanel.hidden = false;
      document.body.classList.add("qb-read-open");
      document.addEventListener("keydown", onReadKey);
      const first = readPanel.querySelector("[data-read-text]");
      if (first) { try { first.focus(); } catch (_) {} }
    };
    const closeRead = () => {
      readPanel.hidden = true;
      document.body.classList.remove("qb-read-open");
      readItems = [];
      document.removeEventListener("keydown", onReadKey);
      try { input.focus(); } catch (_) {}
    };

    const renderRead = (payload) => {
      readItems = payload.items || [];
      $("#qb-read-title").textContent = readItems.length
        ? `Found ${readItems.length} task${readItems.length === 1 ? "" : "s"}`
        : "Nothing that looks like a task";
      // WHERE THE READING CAME FROM, ALWAYS. "Used AI" and "fell back to
      // the rules because the key is dead" produce the same list on a
      // good day and very different ones on a bad day.
      const bits = [];
      if (payload.used_ai) bits.push("split by AI, timings by the built-in rules");
      else bits.push("read by the built-in rules");
      if (payload.note) bits.push(payload.note);
      bits.push("nothing is saved until you press Add");
      $("#qb-read-note").textContent = bits.join(" — ");
      readList.innerHTML = readItems.map(readRowHTML).join("");
      openRead();
      paintReadFoot();
      refreshFeather();
    };

    const runRead = async () => {
      const text = input.value.trim();
      if (!text) { toast("Write or paste something first", "info"); return; }
      readBtn.disabled = true;
      const original = readBtn.innerHTML;
      readBtn.textContent = "Reading…";
      try {
        const payload = await apiFetch("/api/quick-bucket/interpret", {
          method: "POST",
          body: JSON.stringify({ text, use_ai: $("#qb-read-ai").checked }),
        });
        renderRead(payload);
      } catch (err) {
        toast(err.message || "Couldn't read that", "error");
      } finally {
        readBtn.disabled = false;
        readBtn.innerHTML = original;
        refreshFeather();
      }
    };

    /* Returns true when a preview is now on screen and the caller should
       stop. Anything that goes wrong — offline, a 500, a single task
       found — returns false, and the ordinary add runs. The text is
       never consumed by a failed read. */
    /* Is there anything on this candidate a person would want to check
       before it is saved? A renamed title, a bucket that is not the
       default, an alarm, a date, an estimate — any of those is a
       decision the parser made on your behalf. */
    const norm = (t) => (t || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    const worthConfirming = (it, raw) =>
      !!(it.due_at || it.backlog_due || it.planned_minutes ||
         (it.time_bucket && it.time_bucket !== "now") ||
         norm(it.text) !== norm(raw));

    const offerToRead = async (text) => {
      try {
        const payload = await apiFetch("/api/quick-bucket/interpret", {
          method: "POST",
          body: JSON.stringify({ text, use_ai: $("#qb-read-ai").checked }),
        });
        const items = (payload && payload.items) || [];
        if (!items.length) return false;
        // ONE item that the reader neither renamed nor timed has nothing
        // to correct, so showing a dialog for it would be ceremony. Two
        // or more, or anything with a time on it, gets confirmed.
        if (items.length === 1 && !worthConfirming(items[0], text)) return false;
        renderRead(payload);
        return true;
      } catch (_) {
        return false;
      }
    };

    // The AI toggle is a per-device preference, not a per-dump decision:
    // whoever wants the model wants it every time, and re-ticking a box
    // before every read is the kind of friction that gets a feature
    // quietly abandoned.
    const AI_KEY = "qb-read-ai-v1";
    const aiBox = $("#qb-read-ai");
    try { if (localStorage.getItem(AI_KEY) === "1") aiBox.checked = true; }
    catch (_) { /* private mode: default off, which is the safe default */ }
    aiBox?.addEventListener("change", () => {
      try { localStorage.setItem(AI_KEY, aiBox.checked ? "1" : "0"); }
      catch (_) {}
    });

    readBtn?.addEventListener("click", runRead);
    $("#qb-read-again")?.addEventListener("click", runRead);
    $("#qb-read-close")?.addEventListener("click", closeRead);
    readPanel?.addEventListener("mousedown", (e) => {
      if (e.target === readPanel) closeRead();      // the backdrop itself
    });

    // Edits go back into the model, so what is added is what is on
    // screen — not what the parser first guessed.
    readList?.addEventListener("input", (e) => {
      const row = e.target.closest("[data-i]");
      if (!row) return;
      const it = readItems[+row.dataset.i];
      if (!it) return;
      if (e.target.matches("[data-read-text]")) it.text = e.target.value;
      if (e.target.matches("[data-read-mins]")) {
        const v = parseInt(e.target.value, 10);
        it.planned_minutes = Number.isFinite(v) && v > 0 ? v : null;
      }
      if (e.target.matches("[data-read-bucket]")) {
        it.time_bucket = e.target.value;
        // Choosing a relative bucket by hand means the pinned time is no
        // longer what you want; leaving due_at set would ignore the
        // choice and ring at the old time anyway.
        if (it.time_bucket !== "at") it.due_at = null;
      }
      if (e.target.matches("[data-read-use]")) {
        it.use = e.target.checked;
        row.classList.toggle("is-off", !it.use);
        paintReadFoot();
      }
    });

    $("#qb-read-add")?.addEventListener("click", async () => {
      const chosen = readItems.filter((it) => it.use && (it.text || "").trim());
      if (!chosen.length) return;
      const btn = $("#qb-read-add");
      btn.disabled = true;
      let added = 0;
      for (const it of chosen) {
        // Sequential, like addLines: the priority badge is computed from
        // the rows already present, so a parallel burst hands several
        // items the same number.
        await addItem(it.text, {
          quiet: true,
          bucket: it.time_bucket,
          due_at: it.due_at || null,
          backlog_due: it.backlog_due || null,
          planned_minutes: it.planned_minutes || null,
        });
        added++;
      }
      closeRead();
      input.value = "";               // consumed: these are real rows now
      autosizeInput();
      toast(`Added ${added} task${added === 1 ? "" : "s"}`, "success");
    });

    // ── Mic: dictate one task at a time (Web Speech API) ──
    // Single-shot mode (continuous=false, interimResults=false) — same
    // pattern the AI Assist page uses (static/js/ai_assist.js). One
    // press, one phrase, the engine ends on its own when you stop
    // talking, the task is added. To dictate another, press again.
    //
    // Hands-free toggle below adds a wake-word listener so saying
    // "start" triggers a dictation without tapping the button, and
    // "stop" cancels an in-flight dictation early.
    const VOICE_COMMIT_TRIGGERS = new Set(["add", "save", "done", "stop", "submit"]);
    const HANDSFREE_KEY = "qb-handsfree-v1";
    const WAKE_DEBOUNCE_MS = 2_000;
    // Wake phrases — plain English words the engine transcribes
    // reliably. "hello" begins a dictation, "bye" turns hands-free
    // off. The console.log("[qb wake] heard:", t) line in onresult
    // prints the live transcript so it's easy to verify the engine
    // is hearing what you say.
    const WAKE_START_RE = /\b(?:hello|helo|hallo)\b/i;
    const WAKE_STOP_RE  = /\b(?:bye|goodbye|bye-bye|bye bye)\b/i;
    const micBtn = $("#qb-mic-btn");
    const handsfreeBtn = $("#qb-handsfree-btn");
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

    // Diagnostic logs so the user can see in the browser console
    // exactly what state the mic boot ended up in. If the listening
    // toggle "does nothing", look here first.
    console.log("[qb mic] boot",
      { hasMic: !!micBtn, hasHandsfree: !!handsfreeBtn, hasSR: !!SR });

    if (!SR) {
      micBtn.disabled = true;
      micBtn.title = "Dictation not supported in this browser";
      if (handsfreeBtn) {
        handsfreeBtn.disabled = true;
        handsfreeBtn.title = "Not supported in this browser";
      }
      // Tap-feedback even when disabled — surface why nothing happens.
      handsfreeBtn?.addEventListener("click", () => {
        toast("Speech Recognition isn't available in this browser", "error");
      });
    } else {
      let recognition = null;          // single-shot dictation recognizer
      let recognizing = false;
      let wakeRec = null;              // continuous wake-word recognizer
      let wakeRunning = false;
      let wakePending = false;         // "start" detected, awaiting onend
      let handsfreeOn = false;
      let lastWakeAt = 0;

      const stripTrigger = (text) => {
        const tokens = text.split(/\s+/).filter(Boolean);
        if (!tokens.length) return text;
        const last = tokens[tokens.length - 1].toLowerCase().replace(/[^a-z]/g, "");
        if (VOICE_COMMIT_TRIGGERS.has(last)) tokens.pop();
        return tokens.join(" ").trim();
      };

      // ── Single-shot dictation ───────────────────────────
      const startDictation = () => {
        if (recognizing) return;
        recognition = new SR();
        recognition.lang = navigator.language || "en-US";
        recognition.onresult = (e) => {
          const r = e.results && e.results[0];
          const transcript = ((r && r[0] && r[0].transcript) || "").trim();
          if (!transcript) return;
          const text = stripTrigger(transcript);
          if (!text) return;
          input.value = text;
          autosizeInput();
          // A LONG DICTATION IS A PARAGRAPH, NOT A TASK.
          // Nobody speaks in bullet points: hold the button for twenty
          // seconds and what arrives is three jobs in one unpunctuated
          // sentence, which used to become one bucket row containing all
          // three. Past a dozen words, send it to the reader instead and
          // let the preview show what it found — the text stays in the
          // box either way, so nothing is lost if the split is wrong.
          if (text.split(/\s+/).length > 12) {
            toast("Long dictation — reading it into tasks", "info");
            runRead();
            return;
          }
          addItem(text);
          toast(`Added: ${text}`, "success");
          setTimeout(() => { if (input.value === text) input.value = ""; }, 800);
        };
        recognition.onend = () => {
          recognizing = false;
          micBtn.classList.remove("is-on");
          updateHandsfreeStatus();
          // Resume wake listening so the next "start" works.
          if (handsfreeOn) startWake();
        };
        recognition.onerror = (e) => {
          recognizing = false;
          micBtn.classList.remove("is-on");
          updateHandsfreeStatus();
          if (e.error && e.error !== "no-speech" && e.error !== "aborted") {
            toast(`Mic: ${e.error}`, "error");
          }
          if (handsfreeOn) startWake();
        };
        try {
          recognition.start();
          recognizing = true;
          micBtn.classList.add("is-on");
          updateHandsfreeStatus();
        } catch (_) { /* ignore double-start */ }
      };

      micBtn.addEventListener("click", () => {
        if (recognizing) {
          try { recognition?.stop(); } catch (_) {}
          return;
        }
        // Tapping the mic manually pauses hands-free for this dictation
        // — wake will resume from the dictation onend.
        stopWake();
        startDictation();
      });

      // ── Wake-word listener (continuous; opt-in) ─────────
      // Watches transcripts for "start" → triggers dictation.
      // For "stop": single-shot dictation ends on natural silence
      // anyway, but if the wake listener hears "stop" while a dictation
      // is in flight, abort the dictation early.
      const updateHandsfreeStatus = () => {
        const el = $("#qb-handsfree-status");
        const txt = $("#qb-handsfree-status-text");
        if (!el) return;
        if (handsfreeOn && wakeRunning) {
          el.removeAttribute("hidden");
          if (txt) txt.textContent = 'Listening — say "Hello" to dictate';
        } else if (handsfreeOn && recognizing) {
          el.removeAttribute("hidden");
          if (txt) txt.textContent = "Dictating…";
        } else {
          el.setAttribute("hidden", "");
        }
      };

      const startWake = () => {
        if (!handsfreeOn || wakeRunning || recognizing) return;
        wakeRunning = true;
        updateHandsfreeStatus();
        wakeRec = new SR();
        wakeRec.continuous = true;
        wakeRec.interimResults = true;
        wakeRec.lang = navigator.language || "en-US";

        wakeRec.onresult = (e) => {
          // Look at the latest result only — interim is enough since we
          // just need to spot the wake phrase. We don't accumulate text
          // here at all; the dictation recognizer captures the actual
          // task once "Hey Renga" has triggered it.
          for (let i = e.resultIndex; i < e.results.length; i++) {
            const t = (e.results[i][0].transcript || "").toLowerCase();
            // Log the heard text so the user can see what the engine
            // is producing — useful for tuning the wake-phrase regex.
            console.log("[qb wake] heard:", t);
            // "Bye" → turn off hands-free entirely.
            if (WAKE_STOP_RE.test(t)) {
              console.log("[qb wake] WAKE_STOP matched on:", t);
              setHandsfree(false);
              toast("Hands-free off", "info");
              return;
            }
            // "Hello" → kick off a single dictation.
            if (WAKE_START_RE.test(t)) {
              console.log("[qb wake] WAKE_START matched on:", t);
              const now = Date.now();
              if (now - lastWakeAt < WAKE_DEBOUNCE_MS) return;
              lastWakeAt = now;
              wakePending = true;
              try { wakeRec.stop(); } catch (_) {}
              return;
            }
          }
        };
        wakeRec.onend = () => {
          wakeRunning = false;
          wakeRec = null;
          updateHandsfreeStatus();
          if (wakePending) {
            wakePending = false;
            startDictation();
            return;
          }
          // Engine timed out on its own — restart so the listener
          // stays effectively always-on while the toggle is enabled.
          if (handsfreeOn && !recognizing) {
            setTimeout(startWake, 250);
          }
        };
        wakeRec.onerror = (e) => {
          wakeRunning = false;
          wakeRec = null;
          updateHandsfreeStatus();
          if (e.error === "not-allowed") {
            // User denied mic permission — auto-disable hands-free.
            setHandsfree(false);
            toast("Mic permission denied", "error");
            return;
          }
          if (handsfreeOn && !recognizing && e.error !== "aborted") {
            setTimeout(startWake, 500);
          }
        };
        try {
          wakeRec.start();
          console.log("[qb wake] started");
        } catch (e) {
          wakeRunning = false;
          updateHandsfreeStatus();
          console.error("[qb wake] start failed:", e);
          // Common cause: SpeechRecognition.start() called outside a
          // user gesture, which Chrome rejects. Surface the failure
          // so the toggle isn't a green-but-dead button.
          toast("Couldn't start mic — tap the toggle again", "error");
          handsfreeOn = false;
          if (handsfreeBtn) handsfreeBtn.classList.remove("is-on");
        }
      };
      const stopWake = () => {
        wakePending = false;
        if (wakeRec) {
          try { wakeRec.stop(); } catch (_) {}
        }
        updateHandsfreeStatus();
      };

      const setHandsfree = (on) => {
        handsfreeOn = on;
        try { localStorage.setItem(HANDSFREE_KEY, on ? "1" : "0"); } catch (_) {}
        if (handsfreeBtn) {
          handsfreeBtn.classList.toggle("is-on", on);
          handsfreeBtn.title = on
            ? 'Hands-free on — say "Hello" to dictate, "Bye" to stop'
            : 'Hands-free — say "Hello" to dictate';
        }
        if (on) {
          startWake();
          toast('Listening — say "Hello" to dictate', "info");
        } else {
          stopWake();
        }
      };

      if (handsfreeBtn) {
        handsfreeBtn.addEventListener("click", () => {
          console.log("[qb mic] handsfree toggle click; was on?", handsfreeOn);
          setHandsfree(!handsfreeOn);
        });
      } else {
        console.warn("[qb mic] handsfree button not found in DOM");
      }

      // We deliberately do NOT auto-restore from localStorage. Browsers
      // require a user gesture for the first SpeechRecognition.start();
      // a setTimeout-driven auto-start fires outside that gesture and
      // Chrome silently rejects it, leaving the toggle green-but-dead.
      // Instead, mark the toggle pre-armed if it was previously on, but
      // wait for the user's tap to actually wire up the mic.
      try {
        if (localStorage.getItem(HANDSFREE_KEY) === "1" && handsfreeBtn) {
          handsfreeBtn.title = 'Hands-free was on — tap to re-enable';
        }
      } catch (_) {}
    }

    await loadItems();
    wireSelectBar();
    wireGroupFilter();
    // After the first render, prime the alerted set with currently-
    // overdue items so we don't fire a wall of toasts for tasks the
    // user has been ignoring across sessions.
    items.forEach(it => { if (isOverdue(it)) alerted.add(it.id); });
    startTicker();

    // Close the bucket picker when the user clicks anywhere outside it.
    document.addEventListener("click", (e) => {
      const picker = $("#qb-picker");
      if (!picker || picker.hidden) return;
      if (e.target.closest("#qb-picker")) return;
      if (e.target.closest("button.qb-toggle")) return;
      closePicker();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closePicker();
    });
  });
})();
