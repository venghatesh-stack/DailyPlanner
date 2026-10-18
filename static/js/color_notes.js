/* Color Notes: ColorNote-style sticky notes (text or checklist) with colours,
   pin, reminders, archive, trash and a calendar. Talks to /api/color-notes. */
(function () {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const root = $("#cn");
  const COLORS = root.dataset.colors.split(",");
  const CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  const DAY = 86400000;

  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
  };

  const state = {
    notes: store.get("cn-cache", []),
    tab: "notes",
    color: "",
    q: "",
    sort: store.get("cn-sort", "updated"),
    layout: store.get("cn-layout", "grid"),
    calMonth: null,
    calDay: null,
  };

  // ── helpers ──────────────────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function icon(name) {
    const svg = window.feather && feather.icons[name];
    return svg ? svg.toSvg() : "";
  }
  function uid() { return Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4); }
  function ymd(d) { return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }
  function hm(d) { return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); }
  function timeLabel(d) { return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }
  function whenLabel(iso) {
    const d = new Date(iso), now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const that = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diff = Math.round((that - today) / DAY);
    let day;
    if (diff === 0) day = "Today";
    else if (diff === 1) day = "Tomorrow";
    else if (diff === -1) day = "Yesterday";
    else if (diff > 1 && diff < 7) day = d.toLocaleDateString([], { weekday: "long" });
    else day = d.toLocaleDateString([], { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
    return day + ", " + timeLabel(d);
  }
  function ago(iso) {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
    if (s < 86400 * 7) return Math.floor(s / 86400) + " d ago";
    return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" });
  }
  const REPEAT_LABEL = { daily: "daily", weekly: "weekly", monthly: "monthly", yearly: "yearly" };

  async function api(path, body) {
    const opt = { credentials: "same-origin", headers: { "X-CSRFToken": CSRF } };
    if (body !== undefined) {
      opt.method = "POST";
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(body);
    }
    const r = await fetch(path, opt);
    let j = {};
    try { j = await r.json(); } catch (e) { /* empty */ }
    if (!r.ok) throw new Error(j.error || ("Request failed (" + r.status + ")"));
    return j;
  }

  function byId(id) { return state.notes.find(n => n.id === id); }
  function upsert(note) {
    const i = state.notes.findIndex(n => n.id === note.id);
    if (i >= 0) state.notes[i] = Object.assign({}, state.notes[i], note);
    else state.notes.unshift(note);
    cache();
  }
  function cache() { store.set("cn-cache", state.notes.slice(0, 400)); }

  function searchText(n) {
    return ((n.title || "") + " " + (n.body || "") + " " + (n.items || []).map(i => i.text).join(" ")).toLowerCase();
  }
  function isEmpty(n) {
    return !(n.title || "").trim() && !(n.body || "").trim() && !(n.items || []).some(i => (i.text || "").trim());
  }

  // ── list rendering ───────────────────────────────────────────────────
  function inTab(n, tab) {
    if (tab === "trash") return !!n.deleted_at;
    if (n.deleted_at) return false;
    if (tab === "archive") return !!n.is_archived;
    return !n.is_archived;
  }

  function sorted(list) {
    const k = state.sort;
    const cmp = {
      updated: (a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""),
      created: (a, b) => (b.created_at || "").localeCompare(a.created_at || ""),
      title: (a, b) => (a.title || "~").localeCompare(b.title || "~", undefined, { sensitivity: "base" }),
      color: (a, b) => COLORS.indexOf(a.color) - COLORS.indexOf(b.color) || (b.updated_at || "").localeCompare(a.updated_at || ""),
      reminder: (a, b) => (a.remind_at ? 0 : 1) - (b.remind_at ? 0 : 1) || (a.remind_at || "").localeCompare(b.remind_at || ""),
    }[k];
    return list.slice().sort(cmp);
  }

  function cardHTML(n) {
    const items = n.items || [];
    let inner = "";
    if (n.title) inner += "<h3>" + esc(n.title) + "</h3>";
    if (n.kind === "checklist") {
      const open = items.filter(i => !i.done), done = items.filter(i => i.done);
      const show = open.concat(done).slice(0, 7);
      inner += "<ul>" + show.map(i =>
        '<li class="' + (i.done ? "done" : "") + '"><button type="button" class="cn-tick" role="checkbox" aria-checked="' + !!i.done +
        '" data-tick="' + esc(i.id) + '" aria-label="' + (i.done ? "Uncheck " : "Check ") + esc(i.text || "item") + '">' + icon("check") +
        "</button><span>" + esc(i.text) + "</span></li>").join("") + "</ul>";
      if (items.length > 7) inner += '<div class="cn-more">+' + (items.length - 7) + " more</div>";
      if (items.length) inner += '<div class="cn-progress" aria-hidden="true"><i style="width:' + Math.round(100 * done.length / items.length) + '%"></i></div>';
    } else if ((n.body || "").trim()) {
      inner += '<div class="cn-text">' + esc(n.body) + "</div>";
    }
    if (!n.title && isEmpty(n)) inner += '<div class="cn-text" style="opacity:.55">Empty note</div>';
    const meta = [];
    if (n.remind_at) {
      const late = new Date(n.remind_at) < new Date();
      meta.push('<span class="cn-chip' + (late ? " late" : "") + '">' + icon("bell") + esc(whenLabel(n.remind_at)) +
        (REPEAT_LABEL[n.remind_repeat] ? " · " + REPEAT_LABEL[n.remind_repeat] : "") + "</span>");
    }
    if (n.kind === "checklist" && items.length) meta.push("<span>" + items.filter(i => i.done).length + "/" + items.length + "</span>");
    meta.push("<span>" + esc(state.tab === "trash" ? "Deleted " + ago(n.deleted_at) : ago(n.updated_at)) + "</span>");
    return '<div class="cn-card cn-c-' + esc(n.color || "yellow") + '" role="button" tabindex="0" data-id="' + esc(n.id) +
      '" aria-label="' + esc((n.title || "Untitled") + (n.is_pinned ? ", pinned" : "")) + '">' +
      (n.is_pinned ? '<span class="cn-pin" aria-hidden="true">' + icon("bookmark") + "</span>" : "") +
      inner + '<div class="cn-meta">' + meta.join("") + "</div></div>";
  }

  function render() {
    const counts = { notes: 0, archive: 0, trash: 0 };
    state.notes.forEach(n => { ["notes", "archive", "trash"].forEach(t => { if (inTab(n, t)) counts[t]++; }); });
    $("#cn-n-notes").textContent = counts.notes || "";
    $("#cn-n-archive").textContent = counts.archive || "";
    $("#cn-n-trash").textContent = counts.trash || "";
    const reminders = state.notes.filter(n => inTab(n, "notes") && n.remind_at).length;
    $("#cn-sub").textContent = counts.notes ? counts.notes + " note" + (counts.notes === 1 ? "" : "s") +
      (reminders ? " · " + reminders + " with reminders" : "") : "Sticky notes and checklists, in colour.";

    $$(".cn-tabs button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.tab === state.tab)));
    $$("#cn-colors [data-color]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.color === state.color)));
    $("#cn-trashbar").hidden = !(state.tab === "trash" && counts.trash);
    $("#cn-sort").value = state.sort;
    const grid = $("#cn-grid");
    grid.classList.toggle("list", state.layout === "list");
    $("#cn-layout").innerHTML = icon(state.layout === "list" ? "grid" : "list");

    const cal = $("#cn-calendar");
    cal.hidden = state.tab !== "calendar";
    let list;
    if (state.tab === "calendar") {
      renderCalendar();
      list = dayNotes(state.calDay);
    } else {
      list = state.notes.filter(n => inTab(n, state.tab));
    }
    if (state.color) list = list.filter(n => n.color === state.color);
    if (state.q) {
      const q = state.q.toLowerCase();
      list = list.filter(n => searchText(n).includes(q));
    }
    list = sorted(list);

    if (!list.length) {
      const msg = {
        notes: state.q || state.color ? ["Nothing matches", "Try another word or colour."] : ["No notes yet", "Tap + to write a note or start a checklist."],
        archive: ["Archive is empty", "Archived notes stay here, out of the way, until you need them."],
        trash: ["Trash is empty", "Deleted notes wait here until you delete them forever."],
        calendar: ["Nothing on this day", "Notes with a reminder, or created on this day, show here."],
      }[state.tab];
      grid.innerHTML = '<div class="cn-empty" style="column-span:all"><b>' + esc(msg[0]) + "</b>" + esc(msg[1]) + "</div>";
      return;
    }
    if (state.tab === "notes") {
      const pinned = list.filter(n => n.is_pinned), rest = list.filter(n => !n.is_pinned);
      grid.innerHTML = (pinned.length ? '<div class="cn-section-label">Pinned</div>' + pinned.map(cardHTML).join("") +
        (rest.length ? '<div class="cn-section-label">Others</div>' : "") : "") + rest.map(cardHTML).join("");
    } else {
      grid.innerHTML = list.map(cardHTML).join("");
    }
  }

  // ── calendar ─────────────────────────────────────────────────────────
  function noteDays(n) {
    const days = new Set();
    if (n.remind_at) days.add(ymd(new Date(n.remind_at)));
    if (n.created_at) days.add(ymd(new Date(n.created_at)));
    return days;
  }
  function dayNotes(day) {
    if (!day) return [];
    return state.notes.filter(n => !n.deleted_at && noteDays(n).has(day));
  }
  function renderCalendar() {
    const now = new Date();
    if (!state.calMonth) state.calMonth = new Date(now.getFullYear(), now.getMonth(), 1);
    if (!state.calDay) state.calDay = ymd(now);
    const m = state.calMonth;
    const first = new Date(m.getFullYear(), m.getMonth(), 1);
    const start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7)); // Monday start
    const byDay = {};
    state.notes.forEach(n => {
      if (n.deleted_at) return;
      noteDays(n).forEach(d => { (byDay[d] = byDay[d] || []).push(n); });
    });
    let cells = "";
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach(d => { cells += '<div class="dow">' + d + "</div>"; });
    for (let i = 0; i < 42; i++) {
      const d = new Date(start); d.setDate(start.getDate() + i);
      const key = ymd(d), ns = byDay[key] || [];
      cells += '<button type="button" class="cn-day' + (d.getMonth() !== m.getMonth() ? " out" : "") + (key === ymd(now) ? " today" : "") +
        '" data-day="' + key + '" aria-pressed="' + (key === state.calDay) + '" aria-label="' +
        d.toLocaleDateString([], { day: "numeric", month: "long" }) + (ns.length ? ", " + ns.length + " notes" : "") + '">' +
        d.getDate() + '<span class="dots">' + ns.slice(0, 6).map(n => '<i class="cn-c-' + esc(n.color) + '"></i>').join("") + "</span></button>";
    }
    const dayD = new Date(state.calDay + "T00:00:00");
    $("#cn-calendar").innerHTML = '<div class="cn-cal"><div class="cn-cal-head">' +
      '<button type="button" class="cn-btn icon" data-cal="-1" aria-label="Previous month">' + icon("chevron-left") + "</button>" +
      "<b>" + esc(m.toLocaleDateString([], { month: "long", year: "numeric" })) + "</b>" +
      '<button type="button" class="cn-btn icon" data-cal="1" aria-label="Next month">' + icon("chevron-right") + "</button></div>" +
      '<div class="cn-cal-grid">' + cells + "</div></div>" +
      '<div class="cn-day-label"><span>' + esc(dayD.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })) +
      '</span><button type="button" class="cn-btn" data-cal-new="1">' + icon("plus") + "Note with reminder</button></div>";
  }

  // ── loading ──────────────────────────────────────────────────────────
  async function load() {
    try {
      const j = await api("/api/color-notes");
      $("#cn-migrate").hidden = !j.migration_pending;
      state.notes = j.items || [];
      cache();
      render();
    } catch (e) {
      render();
      if (window.showToast) showToast("Could not load notes: " + e.message, "error");
    }
  }

  // ── quick actions from the list ──────────────────────────────────────
  async function patch(id, fields) {
    const n = byId(id);
    if (n) { Object.assign(n, fields, { updated_at: new Date().toISOString() }); cache(); }
    render();
    try {
      const j = await api("/api/color-notes/" + encodeURIComponent(id), fields);
      if (j.item) { upsert(j.item); if (!editor.note || editor.note.id !== id) render(); }
    } catch (e) {
      if (window.showToast) showToast(e.message, "error");
    }
  }

  let snackTimer = null;
  function snack(text, undo) {
    const el = $("#cn-snack");
    el.querySelector("span").textContent = text;
    const b = el.querySelector("button");
    b.hidden = !undo;
    b.onclick = () => { el.hidden = true; undo && undo(); };
    el.hidden = false;
    clearTimeout(snackTimer);
    snackTimer = setTimeout(() => { el.hidden = true; }, 6000);
  }

  async function doAction(id, action) {
    const n = byId(id);
    if (!n) return;
    const local = {
      trash: { deleted_at: new Date().toISOString(), is_pinned: false },
      restore: { deleted_at: null },
    }[action];
    if (local) { Object.assign(n, local); cache(); render(); }
    if (action === "purge") { state.notes = state.notes.filter(x => x.id !== id); cache(); render(); }
    try {
      const j = await api("/api/color-notes/" + encodeURIComponent(id) + "/" + action, {});
      if (j.item) upsert(j.item);
      render();
    } catch (e) {
      if (window.showToast) showToast(e.message, "error");
      load();
    }
    if (action === "trash") snack("Moved to Trash", () => doAction(id, "restore"));
  }

  // ── editor ───────────────────────────────────────────────────────────
  const editor = { note: null, dirty: {}, timer: null, saving: Promise.resolve(), pushed: false };
  const sheet = $("#cn-sheet");

  function openEditor(note, opts) {
    opts = opts || {};
    editor.note = note;
    editor.dirty = {};
    sheet.className = "cn-sheet cn-c-" + (note.color || "yellow");
    sheet.hidden = false;
    $("#cn-scrim").hidden = false;
    $("#cn-title").value = note.title || "";
    $("#cn-text").value = note.body || "";
    paintEditor();
    if (!editor.pushed) { history.pushState({ cnEditor: 1 }, ""); editor.pushed = true; }
    document.body.style.overflow = "hidden";
    if (opts.focus !== false) {
      setTimeout(() => {
        if (note.kind === "checklist" && !note.id && !(note.items || []).length) addItem(-1);
        else if (!note.id) $("#cn-title").focus();
      }, 30);
    }
  }

  function paintEditor() {
    const n = editor.note;
    const trashed = !!n.deleted_at;
    $("#cn-pin").setAttribute("aria-pressed", String(!!n.is_pinned));
    $("#cn-pin").hidden = trashed;
    $("#cn-bell").hidden = trashed;
    $("#cn-paint").hidden = trashed;
    $("#cn-title").readOnly = trashed;
    $("#cn-text").readOnly = trashed;
    $("#cn-text").hidden = n.kind === "checklist";
    $("#cn-list").hidden = n.kind !== "checklist";
    if (n.kind === "checklist") renderItems();
    else autosize($("#cn-text"));
    const rr = $("#cn-remind-row");
    rr.hidden = !n.remind_at || trashed;
    if (n.remind_at) rr.querySelector("span").textContent = whenLabel(n.remind_at) + (REPEAT_LABEL[n.remind_repeat] ? " · repeats " + REPEAT_LABEL[n.remind_repeat] : "");
    $("#cn-info").textContent = n.id ? "Created " + new Date(n.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) +
      " · Edited " + ago(n.updated_at) : "";
    const more = $("#cn-more-pop");
    const mi = (act, ic, label, cls) => '<button type="button" data-act="' + act + '" class="' + (cls || "") + '">' + icon(ic) + esc(label) + "</button>";
    more.innerHTML = trashed
      ? mi("restore", "rotate-ccw", "Restore") + mi("purge", "trash-2", "Delete forever", "danger")
      : mi("convert", n.kind === "checklist" ? "file-text" : "check-square", n.kind === "checklist" ? "Convert to text note" : "Convert to checklist") +
        (n.kind === "checklist" ? mi("uncheck", "square", "Uncheck all") + mi("clear-done", "x-square", "Delete checked items") : "") +
        mi("archive", "archive", n.is_archived ? "Move out of Archive" : "Archive") +
        mi("share", "share-2", "Share or copy") +
        mi("trash", "trash-2", "Move to Trash", "danger");
  }

  function autosize(ta) {
    ta.style.height = "auto";
    ta.style.height = Math.max(ta.scrollHeight, ta.classList.contains("cn-textarea") ? window.innerHeight * 0.5 : 30) + "px";
  }

  function renderItems(focusId, caretEnd) {
    const n = editor.note;
    const items = n.items || [];
    const open = items.filter(i => !i.done), done = items.filter(i => i.done);
    const row = i => '<li class="cn-item' + (i.done ? " done" : "") + '" data-iid="' + esc(i.id) + '">' +
      '<button type="button" class="cn-tick" role="checkbox" aria-checked="' + !!i.done + '" aria-label="' + (i.done ? "Uncheck" : "Check") + '">' + icon("check") + "</button>" +
      '<textarea rows="1" placeholder="List item" aria-label="List item"' + (n.deleted_at ? " readonly" : "") + ">" + esc(i.text) + "</textarea>" +
      (n.deleted_at ? "" : '<button type="button" class="cn-x" aria-label="Remove item">' + icon("x") + "</button>") + "</li>";
    $("#cn-list").innerHTML = '<ul class="cn-items">' + open.map(row).join("") + "</ul>" +
      (n.deleted_at ? "" : '<button type="button" class="cn-add-item" data-add="1">' + icon("plus") + "Add item</button>") +
      (done.length ? '<div class="cn-done-head"><span>' + done.length + " checked item" + (done.length === 1 ? "" : "s") + "</span>" +
        (n.deleted_at ? "" : '<span><button type="button" data-act="uncheck">Uncheck all</button> <button type="button" data-act="clear-done">Delete checked</button></span>') +
        '</div><ul class="cn-items">' + done.map(row).join("") + "</ul>" : "");
    $$("#cn-list textarea").forEach(autosize);
    if (focusId) {
      const ta = $('#cn-list [data-iid="' + CSS.escape(focusId) + '"] textarea');
      if (ta) { ta.focus(); const p = caretEnd === false ? 0 : ta.value.length; ta.setSelectionRange(p, p); }
    }
  }

  function addItem(afterIndex, text) {
    const n = editor.note;
    n.items = n.items || [];
    const it = { id: uid(), text: text || "", done: false };
    if (afterIndex < 0 || afterIndex >= n.items.length) n.items.push(it);
    else n.items.splice(afterIndex + 1, 0, it);
    change({ items: n.items });
    renderItems(it.id, false);
  }

  function change(fields) {
    Object.assign(editor.note, fields);
    Object.assign(editor.dirty, fields);
    $("#cn-saved").textContent = "Editing…";
    clearTimeout(editor.timer);
    editor.timer = setTimeout(flush, 700);
  }

  function flush() {
    clearTimeout(editor.timer);
    const n = editor.note;
    if (!n) return editor.saving;
    const fields = editor.dirty;
    if (!Object.keys(fields).length) return editor.saving;
    editor.dirty = {};
    editor.saving = editor.saving.then(async () => {
      try {
        let j;
        if (!n.id) {
          if (isEmpty(n)) { $("#cn-saved").textContent = ""; return; }
          j = await api("/api/color-notes", {
            kind: n.kind, title: n.title, body: n.body, items: n.items, color: n.color,
            is_pinned: !!n.is_pinned, remind_at: n.remind_at || null, remind_repeat: n.remind_repeat || "none",
          });
          n.id = j.item.id;
        } else {
          j = await api("/api/color-notes/" + encodeURIComponent(n.id), fields);
        }
        if (j.item) {
          n.created_at = j.item.created_at; n.updated_at = j.item.updated_at;
          upsert(Object.assign({}, j.item, editor.note === n ? { title: n.title, body: n.body, items: n.items } : {}));
        }
        $("#cn-saved").textContent = "Saved";
      } catch (e) {
        Object.assign(editor.dirty, fields, editor.dirty);
        $("#cn-saved").textContent = "Not saved";
        if (window.showToast) showToast("Could not save: " + e.message, "error");
      }
    });
    return editor.saving;
  }

  async function closeEditor(fromPop) {
    if (!editor.note) return;
    const n = editor.note;
    await flush();
    sheet.hidden = true;
    $("#cn-scrim").hidden = true;
    closePops();
    document.body.style.overflow = "";
    editor.note = null;
    if (editor.pushed && !fromPop) { editor.pushed = false; history.back(); }
    editor.pushed = false;
    if (n.id && isEmpty(n) && !n.deleted_at) doAction(n.id, "trash");   // a note emptied out goes to Trash
    render();
  }

  function newNote(kind, extra) {
    openEditor(Object.assign({
      kind: kind, title: "", body: "", items: [], color: store.get("cn-last-color", "yellow"),
      is_pinned: false, remind_at: null, remind_repeat: "none",
    }, extra || {}));
  }

  function closePops() {
    $$(".cn-pop").forEach(p => { p.hidden = true; });
    ["#cn-paint", "#cn-more"].forEach(s => $(s).setAttribute("aria-expanded", "false"));
  }

  async function editorAction(act) {
    const n = editor.note;
    closePops();
    if (act === "convert") {
      if (n.kind === "checklist") {
        const body = (n.items || []).map(i => (i.done ? "✓ " : "") + i.text).join("\n");
        change({ kind: "text", body: body, items: [] });
        $("#cn-text").value = body;
      } else {
        const items = (n.body || "").split("\n").map(l => l.replace(/^\s*(?:[-*•]\s*)?(?:\[[ xX]\]\s*)?/, "")).filter(l => l.trim())
          .map(t => ({ id: uid(), text: t.replace(/^✓\s*/, ""), done: /^✓/.test(t) }));
        change({ kind: "checklist", items: items, body: "" });
      }
      paintEditor();
    } else if (act === "uncheck") {
      (n.items || []).forEach(i => { i.done = false; });
      change({ items: n.items }); renderItems();
    } else if (act === "clear-done") {
      change({ items: (n.items || []).filter(i => !i.done) }); renderItems();
    } else if (act === "archive") {
      const val = !n.is_archived;
      change({ is_archived: val });
      await closeEditor();
      snack(val ? "Archived" : "Moved out of Archive", () => patch(n.id, { is_archived: !val }));
    } else if (act === "share") {
      const text = (n.title ? n.title + "\n\n" : "") + (n.kind === "checklist" ? (n.items || []).map(i => (i.done ? "☑ " : "☐ ") + i.text).join("\n") : n.body || "");
      try {
        if (navigator.share) await navigator.share({ title: n.title || "Note", text: text });
        else { await navigator.clipboard.writeText(text); window.showToast && showToast("Copied to clipboard", "success"); }
      } catch (e) { /* share cancelled */ }
    } else if (act === "trash") {
      await flush();
      const id = n.id;
      editor.note.deleted_at = new Date().toISOString();
      await closeEditor();
      if (id) doAction(id, "trash");
    } else if (act === "restore") {
      const id = n.id; await closeEditor(); doAction(id, "restore");
    } else if (act === "purge") {
      const id = n.id; await closeEditor(); doAction(id, "purge");
      snack("Deleted forever");
    }
  }

  // ── reminder dialog ──────────────────────────────────────────────────
  function openReminder() {
    const n = editor.note;
    const d = n.remind_at ? new Date(n.remind_at) : defaultTime("tomorrow");
    $("#cn-rem-date").value = ymd(d);
    $("#cn-rem-time").value = hm(d);
    $("#cn-rem-repeat").value = n.remind_repeat || "none";
    $("#cn-rem-clear").hidden = !n.remind_at;
    $("#cn-rem").hidden = false; $("#cn-rem-scrim").hidden = false;
    $("#cn-rem-date").focus();
    checkPush();
  }
  function closeReminder() { $("#cn-rem").hidden = true; $("#cn-rem-scrim").hidden = true; }
  function defaultTime(kind) {
    const d = new Date();
    if (kind === "later") { d.setHours(d.getHours() + 3, 0, 0, 0); }
    else if (kind === "evening") { d.setHours(18, 0, 0, 0); if (d < new Date()) d.setDate(d.getDate() + 1); }
    else if (kind === "week") { d.setDate(d.getDate() + 7); d.setHours(9, 0, 0, 0); }
    else { d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); }
    return d;
  }
  async function checkPush() {
    const hint = $("#cn-rem-push");
    hint.hidden = true;
    try {
      if (!("Notification" in window) || !window.ClPush) return;
      const sub = await ClPush.currentSubscription();
      hint.hidden = !!sub && Notification.permission === "granted";
    } catch (e) { /* unsupported */ }
  }
  function saveReminder() {
    const ds = $("#cn-rem-date").value, ts = $("#cn-rem-time").value || "09:00";
    if (!ds) { $("#cn-rem-date").focus(); return; }
    const when = new Date(ds + "T" + ts);
    if (isNaN(when)) return;
    const rep = $("#cn-rem-repeat").value;
    if (when < new Date() && rep === "none") {
      window.showToast && showToast("That time has passed. Pick a later time.", "warning");
      return;
    }
    change({ remind_at: when.toISOString(), remind_repeat: rep });
    flush();
    closeReminder();
    paintEditor();
  }

  // ── events ───────────────────────────────────────────────────────────
  $("#cn-grid").addEventListener("click", e => {
    const tick = e.target.closest("[data-tick]");
    const card = e.target.closest(".cn-card");
    if (!card) return;
    const n = byId(card.dataset.id);
    if (!n) return;
    if (tick && !n.deleted_at) {
      e.stopPropagation();
      const items = (n.items || []).map(i => i.id === tick.dataset.tick ? Object.assign({}, i, { done: !i.done }) : i);
      patch(n.id, { items: items });
      return;
    }
    openEditor(Object.assign({}, n, { items: (n.items || []).map(i => Object.assign({}, i)) }), { focus: false });
  });
  $("#cn-grid").addEventListener("keydown", e => {
    if ((e.key === "Enter" || e.key === " ") && e.target.classList.contains("cn-card")) { e.preventDefault(); e.target.click(); }
  });

  $$(".cn-tabs button").forEach(b => b.addEventListener("click", () => { state.tab = b.dataset.tab; render(); }));
  $("#cn-colors").addEventListener("click", e => {
    const b = e.target.closest("[data-color]");
    if (!b) return;
    state.color = state.color === b.dataset.color ? "" : b.dataset.color;
    render();
  });
  let qTimer;
  $("#cn-q").addEventListener("input", e => { clearTimeout(qTimer); qTimer = setTimeout(() => { state.q = e.target.value.trim(); render(); }, 120); });
  $("#cn-sort").addEventListener("change", e => { state.sort = e.target.value; store.set("cn-sort", state.sort); render(); });
  $("#cn-layout").addEventListener("click", () => { state.layout = state.layout === "list" ? "grid" : "list"; store.set("cn-layout", state.layout); render(); });
  $("#cn-empty-trash").addEventListener("click", async e => {
    const b = e.currentTarget;
    if (!b.dataset.armed) {
      b.dataset.armed = "1"; b.textContent = "Tap again to delete all forever";
      setTimeout(() => { delete b.dataset.armed; b.textContent = "Empty Trash"; }, 4000);
      return;
    }
    delete b.dataset.armed; b.textContent = "Empty Trash";
    state.notes = state.notes.filter(n => !n.deleted_at); cache(); render();
    try { await api("/api/color-notes/trash/empty", {}); snack("Trash emptied"); } catch (err) { showToast && showToast(err.message, "error"); load(); }
  });

  $("#cn-calendar").addEventListener("click", e => {
    const nav = e.target.closest("[data-cal]");
    if (nav) { const m = state.calMonth; state.calMonth = new Date(m.getFullYear(), m.getMonth() + Number(nav.dataset.cal), 1); render(); return; }
    const day = e.target.closest("[data-day]");
    if (day) { state.calDay = day.dataset.day; render(); return; }
    if (e.target.closest("[data-cal-new]")) {
      const at = new Date(state.calDay + "T09:00:00");
      newNote("text", at > new Date() ? { remind_at: at.toISOString() } : {});
    }
  });

  // New note button
  const fab = $("#cn-fab");
  $("#cn-fab-main").addEventListener("click", () => {
    const open = !fab.classList.contains("open");
    fab.classList.toggle("open", open);
    $("#cn-fab-main").setAttribute("aria-expanded", String(open));
  });
  $("#cn-fab-menu").addEventListener("click", e => {
    const b = e.target.closest("[data-new]");
    if (!b) return;
    fab.classList.remove("open");
    $("#cn-fab-main").setAttribute("aria-expanded", "false");
    newNote(b.dataset.new);
  });

  // Editor inputs
  $("#cn-title").addEventListener("input", e => change({ title: e.target.value }));
  $("#cn-text").addEventListener("input", e => { autosize(e.target); change({ body: e.target.value }); });
  $("#cn-back").addEventListener("click", () => closeEditor());
  $("#cn-scrim").addEventListener("click", () => closeEditor());
  $("#cn-pin").addEventListener("click", () => { change({ is_pinned: !editor.note.is_pinned }); paintEditor(); });
  $("#cn-bell").addEventListener("click", openReminder);
  $("#cn-remind-row").addEventListener("click", openReminder);
  $("#cn-paint").addEventListener("click", e => {
    const pop = $("#cn-paint-pop"), open = pop.hidden;
    closePops(); pop.hidden = !open; e.currentTarget.setAttribute("aria-expanded", String(open));
  });
  $("#cn-paint-pop").addEventListener("click", e => {
    const b = e.target.closest("[data-paint]");
    if (!b) return;
    change({ color: b.dataset.paint });
    store.set("cn-last-color", b.dataset.paint);
    sheet.className = "cn-sheet cn-c-" + b.dataset.paint;
    closePops();
  });
  $("#cn-more").addEventListener("click", e => {
    const pop = $("#cn-more-pop"), open = pop.hidden;
    closePops(); pop.hidden = !open; e.currentTarget.setAttribute("aria-expanded", String(open));
  });
  sheet.addEventListener("click", e => {
    const act = e.target.closest("[data-act]");
    if (act) { editorAction(act.dataset.act); return; }
    if (!e.target.closest(".cn-pop") && !e.target.closest("#cn-paint") && !e.target.closest("#cn-more")) closePops();
  });

  // Checklist editing
  const list = $("#cn-list");
  list.addEventListener("click", e => {
    if (e.target.closest("[data-add]")) { addItem(-1); return; }
    const li = e.target.closest(".cn-item");
    if (!li || editor.note.deleted_at) return;
    const items = editor.note.items;
    const idx = items.findIndex(i => i.id === li.dataset.iid);
    if (e.target.closest(".cn-tick")) {
      items[idx].done = !items[idx].done;
      change({ items: items }); renderItems();
    } else if (e.target.closest(".cn-x")) {
      const prev = items[idx - 1];
      items.splice(idx, 1);
      change({ items: items }); renderItems(prev && prev.id);
    }
  });
  list.addEventListener("input", e => {
    if (e.target.tagName !== "TEXTAREA") return;
    autosize(e.target);
    const li = e.target.closest(".cn-item");
    const it = editor.note.items.find(i => i.id === li.dataset.iid);
    if (!it) return;
    // A pasted list becomes one item per line.
    if (e.target.value.includes("\n")) {
      const parts = e.target.value.split("\n");
      it.text = parts.shift();
      let at = editor.note.items.indexOf(it), lastId = it.id;
      parts.filter(p => p.trim()).forEach(p => { const n = { id: uid(), text: p, done: false }; editor.note.items.splice(++at, 0, n); lastId = n.id; });
      change({ items: editor.note.items }); renderItems(lastId);
      return;
    }
    it.text = e.target.value;
    change({ items: editor.note.items });
  });
  list.addEventListener("keydown", e => {
    if (e.target.tagName !== "TEXTAREA") return;
    const li = e.target.closest(".cn-item");
    const items = editor.note.items;
    const idx = items.findIndex(i => i.id === li.dataset.iid);
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!e.target.value.trim() && idx === items.length - 1) return;
      addItem(idx);
    } else if (e.key === "Backspace" && !e.target.value) {
      e.preventDefault();
      const prev = items[idx - 1];
      items.splice(idx, 1);
      change({ items: items }); renderItems(prev && prev.id);
    }
  });

  // Reminder dialog
  $("#cn-rem-quick").addEventListener("click", e => {
    const b = e.target.closest("[data-q]");
    if (!b) return;
    const d = defaultTime(b.dataset.q);
    $("#cn-rem-date").value = ymd(d); $("#cn-rem-time").value = hm(d);
  });
  $("#cn-rem-save").addEventListener("click", saveReminder);
  $("#cn-rem-cancel").addEventListener("click", closeReminder);
  $("#cn-rem-scrim").addEventListener("click", closeReminder);
  $("#cn-rem-clear").addEventListener("click", () => { change({ remind_at: null, remind_repeat: "none" }); flush(); closeReminder(); paintEditor(); });
  $("#cn-rem-enable").addEventListener("click", async () => {
    try { await ClPush.subscribe(); window.showToast && showToast("Notifications are on", "success"); } catch (e) { window.showToast && showToast("Could not turn on notifications: " + e.message, "error"); }
    checkPush();
  });

  // Back button / Escape closes the editor
  window.addEventListener("popstate", () => {
    if (!$("#cn-rem").hidden) { closeReminder(); history.pushState({ cnEditor: 1 }, ""); return; }
    if (editor.note) { editor.pushed = false; closeEditor(true); }
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      if (!$("#cn-rem").hidden) { closeReminder(); return; }
      if ($$(".cn-pop").some(p => !p.hidden)) { closePops(); return; }
      if (editor.note) { closeEditor(); return; }
      fab.classList.remove("open");
    }
    const typing = /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || "");
    if (!typing && !editor.note && !e.metaKey && !e.ctrlKey && !e.altKey) {
      if (e.key === "n") { e.preventDefault(); newNote("text"); }
      else if (e.key === "l") { e.preventDefault(); newNote("checklist"); }
      else if (e.key === "/") { e.preventDefault(); $("#cn-q").focus(); }
    }
  });
  // Save when the app goes to the background (phone switched apps).
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") flush(); });
  window.addEventListener("pagehide", () => flush());

  // ── start ────────────────────────────────────────────────────────────
  if (window.feather) feather.replace();
  render();
  load().then(() => {
    const p = new URLSearchParams(location.search);
    const open = p.get("open"), nw = p.get("new");
    if (open || nw) history.replaceState(null, "", location.pathname);
    if (open && byId(open)) { const n = byId(open); openEditor(Object.assign({}, n, { items: (n.items || []).map(i => Object.assign({}, i)) }), { focus: false }); }
    else if (nw === "text" || nw === "checklist") newNote(nw);
  });
  window.ColorNotes = { state: state, render: render, load: load };
})();
