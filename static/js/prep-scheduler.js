/* prep-scheduler.js — put a prep topic on a day, from any bank page.
 *
 * Three pages carry a bank of study topics (/ai-sde, /java,
 * /interview-prep) and all three want the same thing: pick a topic, pick
 * a day, and have it land in that bank's project, on the calendar, and in
 * the Quick Bucket. This is that, once, rather than three copies that
 * drift the first time one of them is fixed.
 *
 * The pages do NOT share a card structure — the title lives in .q-text on
 * one and .t on another — so nothing here reads the DOM to find out what
 * it is scheduling. The button carries its own bank and title in data
 * attributes, and the panel is injected next to it. All a host page has
 * to do is put PrepScheduler.button(bank, title) in its card header and
 * call PrepScheduler.attach(listEl) once.
 *
 * CAPTURE PHASE, deliberately. Every host page has its own click handler
 * on the same container that opens and closes cards, and this button sits
 * inside the header that toggles them. Listening in the capture phase and
 * stopping propagation there means a press on Plan cannot also fold the
 * card shut, whichever listener was registered first.
 */
(function () {
  "use strict";

  var STYLE_ID = "prep-scheduler-css";

  var CSS = [
    /* The button. Drawn as a filled pill, not a bare glyph: it sits on a
       row that already carries several coloured chips, and a transparent
       icon among them reads as decoration rather than a control. */
    ".prep-plan-btn{flex:none;display:inline-flex;align-items:center;gap:5px;",
    "font:inherit;font-size:11.5px;font-weight:800;line-height:1;color:var(--color-on-primary,#fff);",
    "background:var(--color-primary,#2563eb);border:1px solid var(--color-primary,#2563eb);",
    "border-radius:999px;padding:7px 11px;cursor:pointer;white-space:nowrap;",
    "box-shadow:0 1px 2px rgba(0,0,0,.12)}",
    ".prep-plan-btn:hover{background:var(--color-primary-hover,#1d4ed8);",
    "border-color:var(--color-primary-hover,#1d4ed8)}",
    ".prep-plan-btn:active{transform:translateY(1px)}",
    ".prep-plan-btn:focus-visible{outline:3px solid var(--color-primary-ring,rgba(37,99,235,.18));outline-offset:1px}",
    ".prep-plan-btn.on{background:var(--color-surface,#fff);color:var(--color-primary-ink,#2563eb);",
    "border-color:var(--color-border,#e5e7eb);box-shadow:none}",

    /* The panel, injected under the card header on first press. */
    ".prep-panel{display:flex;flex-wrap:wrap;gap:8px;align-items:center;",
    "margin:0 13px 11px;padding:10px;border:1px dashed var(--color-border,#e5e7eb);",
    "border-radius:10px;background:var(--color-bg,#f9fafb)}",
    ".prep-panel[hidden]{display:none}",
    ".prep-panel label{display:flex;align-items:center;gap:6px;font-size:12px;",
    "font-weight:700;color:var(--color-text-secondary,#6b7280)}",
    ".prep-panel input{font:inherit;font-size:13px;padding:6px 8px;min-width:0;",
    "border:1px solid var(--color-border,#e5e7eb);border-radius:8px;",
    "background:var(--color-surface,#fff);color:var(--color-text,#111827)}",
    ".prep-panel .prep-go{font:inherit;font-size:12.5px;font-weight:800;color:#fff;",
    "background:var(--color-primary,#2563eb);border:1px solid var(--color-primary,#2563eb);",
    "border-radius:10px;padding:7px 12px;cursor:pointer}",
    ".prep-panel .prep-go[disabled]{opacity:.6;cursor:default}",
    ".prep-msg{flex-basis:100%;font-size:11.5px;color:var(--color-text-secondary,#6b7280)}",
    ".prep-msg.ok{color:#047857;font-weight:700}",
    ".prep-msg.err{color:#b91c1c;font-weight:700}",
    "html.dark .prep-msg.ok{color:#6ee7b7}html.dark .prep-msg.err{color:#fca5a5}",

    /* ── Bulk select ──
       The topics are already selectable one at a time; this is for planning
       a SESSION. Off until pressed, because the everyday use of these pages
       is reading one card. */
    ".prep-bulkbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 10px}",
    ".prep-bulkbtn{font:inherit;font-size:12.5px;font-weight:700;padding:5px 12px;",
    "border-radius:999px;border:1px solid var(--color-border,#e5e7eb);",
    "background:var(--color-surface,#fff);color:var(--color-text,#111827);cursor:pointer}",
    ".prep-bulkbtn:hover{background:var(--color-bg,#f9fafb)}",
    ".prep-bulkbtn.on{background:var(--color-primary,#2563eb);color:#fff;",
    "border-color:var(--color-primary,#2563eb)}",
    ".prep-bulkbtn--go{background:#4338ca;border-color:#4338ca;color:#fff}",
    ".prep-bulkbtn--go[disabled]{opacity:.45;cursor:default}",
    ".prep-bulkcount{font-size:12.5px;font-weight:700;color:var(--color-text-secondary,#6b7280)}",
    ".prep-pickbox{flex:none;width:17px;height:17px;cursor:pointer;accent-color:#4338ca}",
    ".q-card.prep-picked{outline:2px solid #4338ca;outline-offset:-2px}",

    /* Her own notes, at the foot of an opened card. Visually separate from
       the written material above it — this is the one part of the card that
       is hers, and it should not read as more of the bank's prose. */
    ".prep-note{margin:12px 13px 13px;padding:10px 11px;border-radius:10px;",
    "border:1px dashed var(--color-border,#e5e7eb);",
    "background:var(--color-bg,#f9fafb)}",
    ".prep-note-head{display:flex;justify-content:space-between;align-items:center;",
    "gap:8px;font-size:11.5px;font-weight:800;margin-bottom:6px;",
    "color:var(--color-text-secondary,#6b7280)}",
    ".prep-note-state{font-weight:700;font-size:11px}",
    ".prep-note-state.ok{color:#047857}",
    ".prep-note-state.err{color:#b91c1c}",
    ".prep-note-box{width:100%;box-sizing:border-box;font:inherit;font-size:13.5px;",
    "line-height:1.5;padding:8px 9px;border-radius:8px;resize:vertical;",
    "border:1px solid var(--color-border,#e5e7eb);",
    "background:var(--color-surface,#fff);color:var(--color-text,#111827)}",
    ".prep-note-box:focus{outline:none;border-color:var(--color-primary,#2563eb)}",
    "html.dark .prep-note-state.ok{color:#6ee7b7}",
    "html.dark .prep-note-state.err{color:#fca5a5}",

    /* "(Planned 22 Aug, 19:00)". Green while it is still ahead of you, red
       once the moment has passed without the topic being marked done, grey
       when it has.

       INLINE TEXT, NOT A PILL, because it now sits inside the title: a
       bordered chip mid-sentence would break the line it is part of. It
       stays slightly smaller and lighter than the title so the topic still
       reads first and the schedule reads as an aside about it. */
    ".prep-when{font-size:.86em;font-weight:700;white-space:nowrap}",
    ".prep-when.soon{color:#047857}",
    ".prep-when.late{color:#b91c1c}",
    ".prep-when.done{color:var(--color-text-secondary,#6b7280);font-weight:600}",
    "html.dark .prep-when.soon{color:#6ee7b7}",
    "html.dark .prep-when.late{color:#fca5a5}",
    "html.dark .prep-when.done{color:#9ca3af}",
    /* A struck-out title must not strike the schedule with it — the date is
       still true after the topic is done. */
    ".q-card.done .prep-when, .q-card .done .prep-when{text-decoration:none}",
    /* The card you arrived on. Flashes, then stops — a permanent ring
       would read as a state the card is in. */
    ".q-card.prep-landed{outline:3px solid #6366f1;outline-offset:2px;",
    "border-radius:12px;scroll-margin:90px;animation:prep-land 2.6s ease-out 1}",
    "@keyframes prep-land{0%,22%{background:rgba(99,102,241,.20)}",
    "100%{background:transparent}}",
    "@media (prefers-reduced-motion:reduce){.q-card.prep-landed{animation:none}}",

    /* The session panel. Same shape as the single-topic one so the two
       do not look like different features. */
    ".prep-bulkpanel{display:flex;flex-wrap:wrap;gap:8px;align-items:center;",
    "margin:0 0 12px;padding:11px;border:1px dashed var(--color-border,#e5e7eb);",
    "border-radius:10px;background:var(--color-bg,#f9fafb)}",
    ".prep-bulkpanel[hidden]{display:none}",
    ".prep-bulkpanel label{display:flex;align-items:center;gap:6px;font-size:12px;",
    "font-weight:700;color:var(--color-text-secondary,#6b7280)}",
    ".prep-bulkpanel input{font:inherit;font-size:13px;padding:6px 8px;min-width:0;",
    "border:1px solid var(--color-border,#e5e7eb);border-radius:8px;",
    "background:var(--color-surface,#fff);color:var(--color-text,#111827)}",
    ".prep-bulkpanel .prep-bulkgo{font:inherit;font-size:12.5px;font-weight:800;color:#fff;",
    "background:#4338ca;border:1px solid #4338ca;border-radius:10px;padding:7px 12px;cursor:pointer}",
    ".prep-bulkpanel .prep-bulkgo[disabled]{opacity:.6;cursor:default}",
    ".prep-bulkmsg{flex-basis:100%;font-size:11.5px;color:var(--color-text-secondary,#6b7280)}",
    ".prep-bulkmsg.ok{color:#047857;font-weight:700}",
    ".prep-bulkmsg.err{color:#b91c1c;font-weight:700}",
    "html.dark .prep-bulkmsg.ok{color:#6ee7b7}html.dark .prep-bulkmsg.err{color:#fca5a5}",
    "@media (max-width:640px){.prep-bulkpanel label{flex-basis:100%}",
    ".prep-bulkpanel label input{flex:1}.prep-bulkpanel .prep-bulkgo{width:100%}}",

    /* Each field on its own line on a phone — a date picker squeezed
       beside a time picker at 360px leaves neither one tappable. */
    "@media (max-width:640px){.prep-panel label{flex-basis:100%}",
    ".prep-panel label input{flex:1}.prep-panel .prep-go{width:100%}}",
  ].join("");

  var SHARE_CSS =
    ".prep-share-btn{font:inherit;font-size:11.5px;font-weight:700;cursor:pointer;" +
    "display:inline-flex;align-items:center;gap:4px;margin-left:6px;padding:3px 9px;" +
    "border-radius:999px;border:1px solid var(--color-border,#e5e7eb);" +
    "background:var(--color-surface,#fff);color:var(--color-text-secondary,#6b7280);}" +
    ".prep-share-btn:hover{border-color:var(--color-primary,#2563eb);" +
    "color:var(--color-primary,#2563eb);}" +
    ".prep-share-btn.is-on{border-color:var(--color-primary,#2563eb);" +
    "color:var(--color-primary,#2563eb);font-weight:800;}" +
    ".prep-share-people{display:flex;flex-wrap:wrap;gap:4px 14px;width:100%;" +
    "font-size:13px;margin-bottom:2px;}" +
    ".prep-person{display:inline-flex;align-items:center;gap:6px;cursor:pointer;}";

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var el = document.createElement("style");
    el.id = STYLE_ID;
    el.textContent = CSS + SHARE_CSS;
    document.head.appendChild(el);
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /* LOCAL date, not toISOString(). toISOString() converts to UTC first, so
     the picker opens on the wrong day at opposite ends of the day
     depending on the sign of the offset: WEST of Greenwich it returns
     TOMORROW through the evening (20:00 in New York is already the next
     day in UTC), and EAST of Greenwich it returns YESTERDAY through the
     early morning (03:00 at +05:30 is still the previous day in UTC).
     This household is +05:30, so the failing window is 00:00-05:29. */
  function todayISO() {
    var d = new Date(), p = function (n) { return String(n).padStart(2, "0"); };
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
  }

  function csrf() {
    var m = document.querySelector('meta[name=csrf-token]');
    return (m && m.content) || "";
  }

  function panelHTML() {
    return '<div class="prep-panel" hidden>' +
      '<label>Day <input type="date" class="prep-date" value="' + todayISO() + '"></label>' +
      '<label>Time <input type="time" class="prep-time"></label>' +
      '<button class="prep-go" type="button" data-prep-go>Put it on the calendar</button>' +
      '<span class="prep-msg">Leave the time blank and it sits at 12:00 AM, the top of that day. ' +
      'It lands in the prep project, the calendar and the Quick Bucket.</span>' +
      '</div>';
  }

  function sharePanelHTML() {
    return '<div class="prep-panel prep-share-panel" hidden>' +
      '<div class="prep-share-people">Loading people…</div>' +
      '<label>Day <input type="date" class="prep-date"></label>' +
      '<label>Time <input type="time" class="prep-time"></label>' +
      '<button class="prep-go" type="button" data-prep-share-go>Share it</button>' +
      '<span class="prep-msg">They see it in the chat Calendar with the day ' +
      'and time, and can tick it off there.</span>' +
      '</div>';
  }

  /* The panel goes directly after the card header, so it is the first
     thing under the title rather than below however much body the card
     turns out to have — on /ai-sde that body is a ten-section deep dive
     and a dozen worked examples, which is several screens of scrolling. */
  function panelFor(btn) {
    var card = btn.closest(".q-card") || btn.parentElement;
    if (!card) return null;
    var existing = card.querySelector(":scope > .prep-panel");
    if (existing) return existing;
    var head = card.querySelector(":scope > .q-head");
    var tmp = document.createElement("div");
    tmp.innerHTML = panelHTML();
    var panel = tmp.firstChild;
    if (head && head.nextSibling) card.insertBefore(panel, head.nextSibling);
    else card.appendChild(panel);
    return panel;
  }

  /* People are fetched once per page: the list changes when an account
     is added, which is not during a study session. */
  var peopleCache = null;
  async function loadPeople() {
    if (peopleCache) return peopleCache;
    try {
      var r = await fetch("/api/people", { credentials: "same-origin" });
      peopleCache = (await r.json()).people || [];
    } catch (_) { peopleCache = []; }
    return peopleCache;
  }

  function sharePanelFor(btn) {
    var card = btn.closest(".q-card") || btn.parentElement;
    if (!card) return null;
    var existing = card.querySelector(":scope > .prep-share-panel");
    if (existing) return existing;
    var head = card.querySelector(":scope > .q-head");
    var tmp = document.createElement("div");
    tmp.innerHTML = sharePanelHTML();
    var panel = tmp.firstChild;
    if (head && head.nextSibling) card.insertBefore(panel, head.nextSibling);
    else card.appendChild(panel);
    return panel;
  }

  async function fillSharePanel(btn, panel) {
    var box = panel.querySelector(".prep-share-people");
    var people = await loadPeople();
    if (!people.length) {
      box.textContent = "Nobody else has an account on this planner yet.";
      return;
    }
    var title = btn.getAttribute("data-title") || "";
    var picked = [];
    try {
      var r = await fetch("/api/shared/grants?kind=prep&item_ref=" +
                          encodeURIComponent(title), { credentials: "same-origin" });
      var g = await r.json();
      picked = (g.grants || []).map(function (x) { return x.shared_with; });
      // Somebody already finished it — say so rather than showing an
      // empty tick box next to their name.
      var done = (g.grants || []).filter(function (x) { return x.completed_at; });
      if (done.length) {
        panel.querySelector(".prep-msg").textContent =
          done.map(function (x) {
            return x.name + " finished it on " + String(x.completed_at).slice(0, 10);
          }).join(" · ");
      }
    } catch (_) {}
    box.innerHTML = people.map(function (p) {
      return '<label class="prep-person"><input type="checkbox" value="' +
        esc(p.user_id) + '"' + (picked.indexOf(p.user_id) >= 0 ? " checked" : "") +
        '> ' + esc(p.name) + '</label>';
    }).join("");
  }

  async function submitShare(btn, panel) {
    var msg = panel.querySelector(".prep-msg");
    var go = panel.querySelector("[data-prep-share-go]");
    var ids = [].slice.call(panel.querySelectorAll(".prep-share-people input:checked"))
                .map(function (i) { return i.value; });
    go.disabled = true;
    msg.textContent = "Sharing…";
    try {
      var r = await fetch("/api/shared/share", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({
          kind: "prep",
          item_ref: btn.getAttribute("data-title") || "",
          title: btn.getAttribute("data-title") || "",
          bank: btn.getAttribute("data-bank") || "",
          user_ids: ids,
          due_date: panel.querySelector(".prep-date").value,
          due_time: panel.querySelector(".prep-time").value,
        }),
      });
      var data = await r.json();
      if (!r.ok) throw new Error(data.error || "could not share");
      msg.textContent = data.count
        ? "Shared with " + data.count + (data.count === 1 ? " person" : " people") +
          " — it is in their chat Calendar."
        : "Not shared with anyone now.";
      btn.classList.toggle("is-on", data.count > 0);
    } catch (e) {
      msg.textContent = e.message || "Could not share it.";
    } finally {
      go.disabled = false;
    }
  }

  async function submit(btn, panel) {
    var msg = panel.querySelector(".prep-msg");
    var go = panel.querySelector("[data-prep-go]");
    var day = panel.querySelector(".prep-date").value;
    var time = panel.querySelector(".prep-time").value;
    if (!day) { msg.className = "prep-msg err"; msg.textContent = "Pick a day first."; return; }

    go.disabled = true;
    msg.className = "prep-msg";
    msg.textContent = "Adding…";
    try {
      var r = await fetch("/api/prep/schedule", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        // The title is what identifies the topic. Ids in every one of
        // these banks are POSITIONS (ai42, j7, q19) and shift the moment
        // an entry is added or deduped, so a tab left open across an edit
        // would otherwise schedule whatever moved into that slot. The id
        // rides along as a hint; the server lets the title decide.
        body: JSON.stringify({
          bank: btn.dataset.bank,
          id: btn.dataset.entryId || null,
          title: btn.dataset.title,
          plan_date: day,
          start_time: time,
        }),
      });
      var out = {};
      try { out = await r.json(); } catch (_) { }
      if (!r.ok) throw new Error(out.error || ("HTTP " + r.status));
      msg.className = "prep-msg ok";
      // "sending", not "sent": the Google mirror runs on a background
      // thread that outlives this response, so claiming it has arrived
      // would be a claim the server never made.
      msg.textContent = (out.status === "already-scheduled" ? "Already there — " : "Added — ") +
        (out.message || day) +
        (out.project ? " In " + out.project + "." : "") +
        (out.gcal_syncing ? " Sending it to Google Calendar too." : "");
      if (window.showToast) showToast(out.message || "Scheduled", "success");
    } catch (e) {
      msg.className = "prep-msg err";
      msg.textContent = "Could not schedule it: " + e.message;
    } finally {
      go.disabled = false;
    }
  }

  function show(btn, panel, open) {
    if (open) panel.removeAttribute("hidden"); else panel.setAttribute("hidden", "");
    btn.classList.toggle("on", open);
    if (open) {
      panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
      var d = panel.querySelector(".prep-date");
      if (d) d.focus();
    }
  }

  /* ══════════════════════════════════════════════════════════════════
     BULK: several topics into ONE study block

     Asked for: "bulk add items from Interview prep pages AI SDE, JAVA,
     SQL etc to calendar".

     THIS READS NO PAGE-SPECIFIC MARKUP. The pages disagree about their
     card structure — the title is .q-text on one and .t on another — but
     every schedulable card already carries a Plan button holding its own
     bank and title in data attributes. Selecting off THOSE buttons means
     bulk works on all four pages without touching any of their templates,
     which is the same principle the single-topic path was built on.

     ONE CALENDAR EVENT, NOT ONE PER TOPIC. Six topics on Saturday morning
     is one block whose description lists them, not six stacked entries.
     The project still gets one task per topic, because that is where
     progress is tracked and a single "study block" cannot be half done.
     ══════════════════════════════════════════════════════════════════ */

  var bulk = { on: false, picked: null, root: null, bar: null, panel: null };

  /* EVERY ONE OF THESE PAGES CALLS attach() BEFORE ITS LIST EXISTS.
     The bank is fetched over the network and rendered in a .then(), while
     attach() runs synchronously further down the same script — so at the
     moment it runs there is not a single card in the container.

     Anything that needs to SEE a card therefore cannot do its work
     immediately, and must not give up either. Both of the features that did
     — the bulk bar and the "Planned on" pill — silently never appeared,
     because each opened with a "no cards? then there is nothing to do"
     guard that was true every single time.

     This waits for the first card and then runs once. The deadline exists
     so a page with a genuinely empty bank stops observing rather than
     watching forever. */
  function whenCardsReady(root, cb) {
    if (!root) { inert("no container"); return; }
    if (root.querySelector("[data-prep-plan]")) { cb(); return; }
    if (!window.MutationObserver) { inert("no MutationObserver"); return; }
    var fired = false;
    var observer = new MutationObserver(function () {
      if (!root.querySelector("[data-prep-plan]")) return;
      fired = true;
      observer.disconnect();
      cb();
    });
    observer.observe(root, { childList: true, subtree: true });
    setTimeout(function () {
      observer.disconnect();
      // Waited the full window and no schedulable card ever appeared. On a
      // page that has topics, this means the bulk bar and the "Planned on"
      // marks are simply not running — the exact failure that went
      // unnoticed for a week because nothing threw.
      if (!fired) inert("no schedulable card appeared within 15s");
    }, 15000);
  }

  function inert(why) {
    if (window.dpInert) window.dpInert("prep-scheduler", why);
  }

  function bulkButtons(root) {
    return Array.prototype.slice.call(root.querySelectorAll("[data-prep-plan]"));
  }

  function bulkBank(root) {
    var first = root.querySelector("[data-prep-plan]");
    return first ? first.getAttribute("data-bank") : null;
  }

  /* Sum the prep time of what is selected, when the page has told us.
     Returns null when no card carries a minutes hint, so the panel can
     leave the field empty and let the server decide rather than showing a
     confident zero. */
  function pickedMinutes() {
    var total = 0, seen = false;
    bulk.picked.forEach(function (title) {
      var btn = bulk.root.querySelector('[data-prep-plan][data-title="' + cssEsc(title) + '"]');
      var m = btn && parseInt(btn.getAttribute("data-minutes") || "", 10);
      if (m > 0) { total += m; seen = true; }
    });
    return seen ? total : null;
  }

  function cssEsc(v) {
    return String(v).replace(/["\\]/g, "\\$&");
  }

  function bulkPanelHTML() {
    return '<div class="prep-bulkpanel" hidden>' +
      '<label>Day <input type="date" class="prep-bulkdate" value="' + todayISO() + '"></label>' +
      '<label>Start <input type="time" class="prep-bulktime"></label>' +
      '<label>Minutes <input type="number" class="prep-bulkdur" min="5" max="720" step="5" ' +
             'placeholder="auto"></label>' +
      '<button class="prep-bulkgo" type="button">Create the study block</button>' +
      '<span class="prep-bulkmsg">One calendar block, with the topics as its description. ' +
      'Leave minutes blank and it uses the topics\u2019 own prep time. ' +
      'Each topic also becomes a task in the prep project.</span>' +
      '</div>';
  }

  function paintBulk() {
    if (!bulk.bar) return;
    var toggle = bulk.bar.querySelector(".prep-bulk-toggle");
    var count  = bulk.bar.querySelector(".prep-bulkcount");
    var go     = bulk.bar.querySelector(".prep-bulk-open");
    var all    = bulk.bar.querySelector(".prep-bulk-all");
    var none   = bulk.bar.querySelector(".prep-bulk-none");

    toggle.classList.toggle("on", bulk.on);
    toggle.textContent = bulk.on ? "Done selecting" : "Select several";
    [count, go, all, none].forEach(function (el) { if (el) el.hidden = !bulk.on; });
    if (!bulk.on) return;

    var n = bulk.picked.size;
    count.textContent = n === 1 ? "1 topic" : n + " topics";
    var mins = pickedMinutes();
    if (n && mins) {
      var h = Math.floor(mins / 60), r = mins % 60;
      count.textContent += " · " + (h ? h + "h" + (r ? " " + r + "m" : "") : r + "m");
    }
    go.disabled = n === 0;
  }

  /* The checkbox is injected beside the Plan button, sharing its parent —
     so no page's header layout is rearranged, and removing it restores the
     card exactly. */
  function paintBoxes() {
    bulkButtons(bulk.root).forEach(function (btn) {
      var title = btn.getAttribute("data-title") || "";
      var card = btn.closest(".q-card");
      var box = btn.parentElement.querySelector(".prep-pickbox");
      if (!bulk.on) {
        if (box) box.remove();
        if (card) card.classList.remove("prep-picked");
        return;
      }
      if (!box) {
        box = document.createElement("input");
        box.type = "checkbox";
        box.className = "prep-pickbox";
        box.setAttribute("aria-label", "Select this topic");
        btn.parentElement.insertBefore(box, btn);
      }
      box.checked = bulk.picked.has(title);
      if (card) card.classList.toggle("prep-picked", box.checked);
    });
  }

  async function submitBulk() {
    var bank = bulkBank(bulk.root);
    var titles = Array.prototype.slice.call(bulk.picked);
    if (!bank || !titles.length) return;

    var dateEl = bulk.panel.querySelector(".prep-bulkdate");
    var timeEl = bulk.panel.querySelector(".prep-bulktime");
    var durEl  = bulk.panel.querySelector(".prep-bulkdur");
    var msg    = bulk.panel.querySelector(".prep-bulkmsg");
    var go     = bulk.panel.querySelector(".prep-bulkgo");

    if (!dateEl.value) {
      msg.className = "prep-bulkmsg err";
      msg.textContent = "Pick a day first.";
      return;
    }

    go.disabled = true;
    msg.className = "prep-bulkmsg";
    msg.textContent = "Creating…";
    try {
      var r = await fetch("/api/prep/schedule-bulk", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({
          bank: bank,
          topics: titles.map(function (t) { return { title: t }; }),
          plan_date: dateEl.value,
          start_time: timeEl.value || "",
          duration_min: parseInt(durEl.value, 10) || 0,
        }),
      });
      var j = await r.json().catch(function () { return {}; });
      if (!r.ok) {
        msg.className = "prep-bulkmsg err";
        msg.textContent = j.error || "Could not create the block.";
        return;
      }
      msg.className = "prep-bulkmsg ok";
      var extra = (j.already_there && j.already_there.length)
        ? " (" + j.already_there.length + " already on that day)" : "";
      msg.textContent = j.count + " topic" + (j.count === 1 ? "" : "s") +
        " → " + j.plan_date + " " + j.start_time + "–" + j.end_time + extra;
      if (window.toast) window.toast("Study block created for " + j.plan_date, "success");
      bulk.picked.clear();
      paintBoxes();
      paintBulk();
    } catch (_) {
      msg.className = "prep-bulkmsg err";
      msg.textContent = "Network error — nothing was scheduled.";
    } finally {
      go.disabled = false;
    }
  }

  function setBulk(on) {
    bulk.on = on;
    if (!on) {
      bulk.picked.clear();
      bulk.panel.setAttribute("hidden", "");
    }
    paintBoxes();
    paintBulk();
  }

  function mountBulk(root) {
    if (!root || root.dataset.prepBulkBound) return;
    if (!root.querySelector("[data-prep-plan]")) return;   // nothing to select
    root.dataset.prepBulkBound = "1";

    bulk.root = root;
    bulk.picked = new Set();

    var wrap = document.createElement("div");
    wrap.innerHTML =
      '<div class="prep-bulkbar">' +
        '<button class="prep-bulkbtn prep-bulk-toggle" type="button">Select several</button>' +
        '<span class="prep-bulkcount" hidden></span>' +
        '<button class="prep-bulkbtn prep-bulk-all" type="button" hidden>All shown</button>' +
        '<button class="prep-bulkbtn prep-bulk-none" type="button" hidden>None</button>' +
        '<button class="prep-bulkbtn prep-bulkbtn--go prep-bulk-open" type="button" hidden disabled>' +
          'Add to calendar →</button>' +
      '</div>' + bulkPanelHTML();
    bulk.bar = wrap.firstChild;
    bulk.panel = wrap.lastChild;
    root.parentNode.insertBefore(bulk.panel, root);
    root.parentNode.insertBefore(bulk.bar, bulk.panel);

    bulk.bar.querySelector(".prep-bulk-toggle").addEventListener("click", function () {
      setBulk(!bulk.on);
    });
    bulk.bar.querySelector(".prep-bulk-all").addEventListener("click", function () {
      bulkButtons(bulk.root).forEach(function (b) {
        bulk.picked.add(b.getAttribute("data-title") || "");
      });
      paintBoxes(); paintBulk();
    });
    bulk.bar.querySelector(".prep-bulk-none").addEventListener("click", function () {
      bulk.picked.clear(); paintBoxes(); paintBulk();
    });
    bulk.bar.querySelector(".prep-bulk-open").addEventListener("click", function () {
      bulk.panel.toggleAttribute("hidden");
      if (!bulk.panel.hasAttribute("hidden")) {
        bulk.panel.querySelector(".prep-bulkdate").focus();
      }
    });
    bulk.panel.querySelector(".prep-bulkgo").addEventListener("click", submitBulk);
    // Typing in the panel must not reach the host page's card toggle.
    bulk.panel.addEventListener("click", function (ev) { ev.stopPropagation(); });

    paintBulk();
  }

  /* ══════════════════════════════════════════════════════════════════
     ARRIVING FROM THE DAY BOARD ON A SPECIFIC TOPIC (?topic=)

     Reported: "if an AI SDE prep question is displayed on the day board and
     I click it, it should go to that specific line item on that page."

     Before this, a scheduled prep topic on the board linked to the DAY
     view, which showed the same one-line title you had just clicked — a
     round trip to no new information.

     MATCHED BY TITLE, NOT BY ID. Every one of these banks numbers its
     entries by POSITION (ai42, j7, sq3) and a position shifts the moment an
     entry is added or deduped, so a link made last week would open whatever
     moved into that slot since. The Plan button on each card already
     carries its own title, and that is what is matched — which also means
     this reads no page-specific markup, exactly like the bulk selector.

     IT CLICKS THE CARD RATHER THAN SETTING .open. Some of these pages fill
     the card body LAZILY on first open (/ai-sde fetches the ten-section
     deep dive), so forcing the class would reveal an empty card. Clicking
     runs whatever the host page does, including the fetch.
     ══════════════════════════════════════════════════════════════════ */

  function landOnTopic(root) {
    var wanted;
    try {
      wanted = new URLSearchParams(window.location.search).get("topic");
    } catch (_) {
      return;
    }
    if (!wanted) return;

    var DEADLINE = 8000;              // these lists are fetched, not inline
    var started = Date.now();
    var observer = null;
    var done = false;

    function attempt() {
      if (done) return true;
      var btns = root.querySelectorAll("[data-prep-plan]");
      for (var i = 0; i < btns.length; i++) {
        if ((btns[i].getAttribute("data-title") || "") !== wanted) continue;
        var card = btns[i].closest(".q-card");
        if (!card) continue;
        done = true;
        if (observer) { observer.disconnect(); observer = null; }
        open(card);
        return true;
      }
      if (Date.now() - started > DEADLINE && observer) {
        observer.disconnect();
        observer = null;
      }
      return false;
    }

    function open(card) {
      if (!card.classList.contains("open")) {
        // Click the HEADER, not the card: on some pages the card-level
        // handler would also catch the studied checkbox sitting inside it.
        var head = card.querySelector(".q-head") || card;
        try { head.click(); } catch (_) { card.classList.add("open"); }
      }
      try {
        card.scrollIntoView({ behavior: "smooth", block: "center" });
      } catch (_) {
        card.scrollIntoView();
      }
      card.classList.add("prep-landed");
      // Removed rather than left: a permanent ring reads as a state the
      // card is in, not as "this is the one you came for".
      setTimeout(function () { card.classList.remove("prep-landed"); }, 2800);
    }

    if (attempt()) return;
    if (!window.MutationObserver) return;
    observer = new MutationObserver(attempt);
    observer.observe(root, { childList: true, subtree: true });
    setTimeout(function () {
      if (observer) { observer.disconnect(); observer = null; }
      // Not found: stay silent. The topic may have been filtered out or
      // renamed, and the page is still the right page — a failure message
      // for something the user can see is worse than nothing.
    }, DEADLINE);
  }

  /* ══════════════════════════════════════════════════════════════════
     "PLANNED ON …" ON EACH CARD

     Asked for: a scheduled topic should say when it is planned for, RED if
     that moment has passed and GREEN if it has not.

     Until now the only way to find out whether you had already scheduled
     something was to open the calendar — the wrong place to answer a
     question you are asking while looking at the topic.

     THE COMPARISON IS MADE HERE, NOT ON THE SERVER, because "has it
     elapsed" needs the READER's clock and the server is a different
     machine. The API sends the raw date and time; the colour is decided
     against the local Date.

     A DATE WITH NO TIME ELAPSES AT THE END OF ITS DAY, not at midnight when
     it begins. The scheduler stores 00:00 for "no time given", so treating
     that literally would paint today's untimed plan red all day — which is
     the opposite of what it means.
     ══════════════════════════════════════════════════════════════════ */

  var MONTHS = ["Jan","Feb","Mar","Apr","May","Jun",
                "Jul","Aug","Sep","Oct","Nov","Dec"];

  function fmtWhen(iso, hhmm) {
    var p = iso.split("-");
    if (p.length !== 3) return iso;
    var d = new Date(+p[0], +p[1] - 1, +p[2]);
    var txt = d.getDate() + " " + MONTHS[d.getMonth()];
    var now = new Date();
    if (d.getFullYear() !== now.getFullYear()) txt += " " + d.getFullYear();
    return hhmm ? txt + ", " + hhmm : txt;
  }

  /* The instant a plan stops being "upcoming".
     With a time, that is the time. Without one, it is the END of the day —
     an untimed plan for today has not been missed at 00:01. */
  function deadlineOf(iso, hhmm) {
    var p = iso.split("-");
    if (p.length !== 3) return null;
    if (hhmm) {
      var t = hhmm.split(":");
      return new Date(+p[0], +p[1] - 1, +p[2], +t[0] || 0, +t[1] || 0, 0, 0);
    }
    return new Date(+p[0], +p[1] - 1, +p[2], 23, 59, 59, 999);
  }

  /* The title element, whichever of the four pages this is. They disagree:
     /ai-sde and /interview-prep use .q-text, /java and /sql use .t. Scoped
     to the card's HEADER so a .t elsewhere in the body cannot be picked up
     by accident. */
  function titleElOf(card) {
    var head = card.querySelector(".q-head") || card;
    return head.querySelector(".q-text, .t");
  }

  function paintScheduled(root, scheduled) {
    var now = new Date();
    bulkButtons(root).forEach(function (btn) {
      var title = btn.getAttribute("data-title") || "";
      var info = scheduled[title];
      var card = btn.closest(".q-card");
      var titleEl = card ? titleElOf(card) : null;

      // Clear any previous mark, wherever it ended up.
      [titleEl, btn.parentElement].forEach(function (host) {
        if (!host) return;
        var prev = host.querySelector(".prep-when");
        if (prev) prev.remove();
      });
      if (!info || !info.plan_date) return;

      var mark = document.createElement("span");
      var done = (info.status || "").toLowerCase() === "done";
      var due = deadlineOf(info.plan_date, info.start_time);
      var late = !done && due && due.getTime() < now.getTime();

      mark.className = "prep-when " + (done ? "done" : (late ? "late" : "soon"));
      /* ON THE TITLE, IN PARENTHESES — which is how it was asked for, and it
         reads better than a separate chip: the schedule is a fact ABOUT this
         topic, so it belongs in the sentence naming it rather than in the
         row of category chips beside it. */
      mark.textContent = " (" + (done ? "Studied " : "Planned ") +
                         fmtWhen(info.plan_date, info.start_time) + ")";
      mark.title = done
        ? "Marked done in the prep project"
        : (late ? "This was planned for " + fmtWhen(info.plan_date, info.start_time)
                  + " and has not been marked done"
                : "Scheduled — not due yet");

      // Beside the Plan button only if the page has a title shape we do not
      // recognise, so a new page never silently loses the mark.
      if (titleEl) titleEl.appendChild(mark);
      else btn.parentElement.insertBefore(mark, btn);
    });
  }

  function loadScheduled(root) {
    var bank = bulkBank(root);
    if (!bank) {
      // Called via whenCardsReady, so a card DOES exist — a missing bank
      // therefore means the Plan button lost its data-bank attribute, which
      // would silently disable scheduling everywhere on this page.
      inert("cards exist but no data-bank on the Plan button");
      return;
    }
    fetch("/api/prep/scheduled?bank=" + encodeURIComponent(bank),
          { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.scheduled) return;
        schedCache = j.scheduled;
        paintScheduled(root, schedCache);
        reconcileChecked(root, schedCache);
        /* The pages rebuild their list on every filter change, which wipes
           the pills. Repaint from the cache rather than refetching — the
           answer cannot have changed because a filter moved. */
        if (window.MutationObserver && !root.dataset.prepWhenBound) {
          root.dataset.prepWhenBound = "1";
          new MutationObserver(function () {
            paintScheduled(root, schedCache);
            reconcileChecked(root, schedCache);
          }).observe(root, { childList: true });
        }
      })
      .catch(function () { /* offline: the cards are still usable */ });
  }

  var schedCache = {};

  /* ══════════════════════════════════════════════════════════════════
     TICKING A TOPIC AS STUDIED COMPLETES WHAT IT SCHEDULED

     Reported: ticking the checkbox on a prep page did not mark the item
     complete on the Day Board or in the Quick Bucket.

     It never could. The tick updated the STUDY record only — ai_sde_progress
     on /ai-sde, localStorage on /java and /sql — while scheduling a topic
     writes three OTHER rows: a project task, a calendar event and a bucket
     line. None of them heard about it, so the topic read done in one place
     and outstanding in three.

     WHICH CHECKBOX. The pages disagree about the studied box's class
     (.q-prac on /ai-sde, a bare input elsewhere), so this matches any
     checkbox inside a card that also carries a Plan button — which is how
     the bank and title are known — and explicitly excludes the bulk-select
     box this module adds itself.

     FIRE AND FORGET, and deliberately so. The tick's own handler on each
     page already does its work; this is a second effect that must not slow
     the first down or fail it. If the network is gone, the study record is
     still correct and the schedule catches up on the next tick.
     ══════════════════════════════════════════════════════════════════ */

  /* Set while the checkbox is being brought into line with the server, so
     the change we dispatch to make the page persist it does not come
     straight back here as a fresh completion. */
  var reconciling = false;

  /* THE OTHER DIRECTION. Ticking a row in the Quick Bucket closes the topic
     server-side, but /java and /sql keep their studied state in
     localStorage where nothing server-side can reach it — so on load the
     checkbox has to be brought into line with what the schedule says.

     ONLY FOR TOPICS THAT ARE ACTUALLY SCHEDULED. An unscheduled topic has
     no task to disagree with, and forcing its box either way would be
     overwriting a study record with silence.

     The change event IS dispatched, because each page persists its own
     progress in its own handler and simply setting .checked would leave the
     tick undone on the next reload. */
  function reconcileChecked(root, scheduled) {
    reconciling = true;
    try {
      bulkButtons(root).forEach(function (btn) {
        var info = scheduled[btn.getAttribute("data-title") || ""];
        if (!info) return;
        var card = btn.closest(".q-card");
        if (!card) return;
        var box = card.querySelector('input[type="checkbox"]:not(.prep-pickbox)');
        if (!box) return;
        var want = (info.status || "").toLowerCase() === "done";
        if (box.checked === want) return;
        box.checked = want;
        try {
          box.dispatchEvent(new Event("change", { bubbles: true }));
        } catch (_) {
          box.dispatchEvent(document.createEvent("HTMLEvents"));
        }
      });
    } finally {
      reconciling = false;
    }
  }

  function syncCompletion(card, isDone) {
    if (reconciling) return;            // we set that box, not the user
    var btn = card.querySelector("[data-prep-plan]");
    if (!btn) return;                       // not a schedulable card
    var bank = btn.getAttribute("data-bank");
    var title = btn.getAttribute("data-title");
    if (!bank || !title) return;

    fetch("/api/prep/complete", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({ bank: bank, title: title, done: !!isDone }),
    }).then(function () {
      // The pill's wording depends on it ("Studied 22 Aug" rather than
      // "Planned"), so refresh what we know rather than leaving it stale.
      var info = schedCache[title];
      if (info) {
        info.status = isDone ? "done" : "open";
        paintScheduled(bulk.root || card.closest("#list") || document, schedCache);
      }
    }).catch(function () { /* the study record is still right */ });
  }

  /* ══════════════════════════════════════════════════════════════════
     HER OWN NOTES ON A QUESTION

     A bank entry is written material — an answer, a walkthrough, worked
     examples. What it never had is somewhere for the READER's thinking:
     what she got wrong the first time, the sentence that finally made it
     click, the follow-up an interviewer actually asked. That is the note
     most worth keeping and it had nowhere to live.

     INJECTED INTO THE CARD BODY WHEN IT OPENS, not at render time. Two
     reasons: a bank page draws over a thousand cards and a textarea in
     every one is waste, and /ai-sde fills its body lazily on first open, so
     anything added earlier is thrown away by that fetch.

     SAVED ON A DEBOUNCE AND ON BLUR. Auto-save because a note you have to
     remember to save is a note you lose; on blur as well because the
     debounce has not fired yet when you close the card or the tab.
     ══════════════════════════════════════════════════════════════════ */

  var notesCache = {};
  var notesReady = false;
  var NOTE_DEBOUNCE = 900;

  function loadNotes(root) {
    var bank = bulkBank(root);
    if (!bank) return;
    fetch("/api/prep/notes?bank=" + encodeURIComponent(bank),
          { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j) return;
        if (j.available === false) {
          // The table is not there yet. Say so once rather than offering a
          // box that silently throws away everything typed into it.
          inert("notes table missing — run " + (j.migration || "the migration"));
          return;
        }
        notesCache = j.notes || {};
        notesReady = true;
        // Any card already open gets its note filled in now.
        Array.prototype.forEach.call(
          root.querySelectorAll(".q-card.open"), function (c) { ensureNote(c); });
      })
      .catch(function () { /* offline: the cards still work */ });
  }

  function noteHostFor(card) {
    return card.querySelector(".q-body") || card;
  }

  function ensureNote(card) {
    if (!notesReady) return;
    var btn = card.querySelector("[data-prep-plan]");
    if (!btn) return;                       // not a bank entry
    var bank = btn.getAttribute("data-bank");
    var title = btn.getAttribute("data-title");
    if (!bank || !title) return;

    var host = noteHostFor(card);
    if (!host || host.querySelector(".prep-note")) return;

    var existing = notesCache[title];
    var wrap = document.createElement("div");
    wrap.className = "prep-note";
    wrap.innerHTML =
      '<div class="prep-note-head">' +
        '<span>📝 My notes</span>' +
        '<span class="prep-note-state"></span>' +
      '</div>' +
      '<textarea class="prep-note-box" rows="3" ' +
        'placeholder="What tripped you up, what finally made it click, ' +
        'what they actually asked…"></textarea>';
    var box = wrap.querySelector(".prep-note-box");
    box.value = existing ? (existing.note || "") : "";
    host.appendChild(wrap);
    autoGrow(box);

    var timer = null;
    var state = wrap.querySelector(".prep-note-state");

    function save() {
      if (timer) { clearTimeout(timer); timer = null; }
      var text = box.value;
      // Nothing changed since the last save — do not spend a request on it.
      if ((notesCache[title] && notesCache[title].note) === text) return;
      state.textContent = "saving…";
      state.className = "prep-note-state";
      fetch("/api/prep/notes", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ bank: bank, title: title, note: text }),
      }).then(function (r) {
        if (!r.ok) throw new Error("save failed");
        notesCache[title] = { note: text };
        state.textContent = text ? "saved" : "cleared";
        state.className = "prep-note-state ok";
        setTimeout(function () { if (state) state.textContent = ""; }, 2200);
      }).catch(function () {
        state.textContent = "not saved — will retry when you type again";
        state.className = "prep-note-state err";
      });
    }

    box.addEventListener("input", function () {
      autoGrow(box);
      if (timer) clearTimeout(timer);
      timer = setTimeout(save, NOTE_DEBOUNCE);
    });
    // The debounce has not fired when you click away or close the card.
    box.addEventListener("blur", save);
    // Typing must not reach the host page's card toggle, which would fold
    // the card shut mid-sentence.
    ["click", "keydown", "keyup"].forEach(function (evt) {
      box.addEventListener(evt, function (e) { e.stopPropagation(); });
    });
  }

  function autoGrow(box) {
    try {
      box.style.height = "auto";
      box.style.height = Math.min(box.scrollHeight + 2, 420) + "px";
    } catch (_) {}
  }

  var PrepScheduler = {
    /* HTML for the header button. `title` is the topic text and is what
       actually identifies it to the server; `entryId` is optional and is
       only ever a hint. */
    button: function (bank, title, entryId, prepMinutes) {
      // `prepMinutes` is optional and only ever a DISPLAY hint — it lets
      // the bulk bar total up a session before you commit to it. The server
      // recomputes from the bank either way, so a page that does not pass
      // it loses nothing but the running total.
      return '<button class="prep-plan-btn" type="button" data-prep-plan' +
        ' data-bank="' + esc(bank) + '"' +
        ' data-title="' + esc(title) + '"' +
        (prepMinutes > 0 ? ' data-minutes="' + esc(prepMinutes) + '"' : "") +
        (entryId ? ' data-entry-id="' + esc(entryId) + '"' : "") +
        ' title="Put this topic on a day" aria-label="Schedule this topic">' +
        '📅<span>Plan</span></button>' +
        /* SHARE SITS BESIDE PLAN and comes from the same factory, so all
           four bank pages get it without touching four templates — the
           reason this module exists at all. Same data attributes: the
           TITLE identifies the topic, because bank entry ids are
           positional and shift whenever a bank is edited. */
        '<button class="prep-share-btn" type="button" data-prep-share' +
        ' data-bank="' + esc(bank) + '"' +
        ' data-title="' + esc(title) + '"' +
        ' title="Share this topic with someone" aria-label="Share this topic">' +
        '↗<span>Share</span></button>';
    },

    /* Wire one list container. Safe to call more than once — a second
       call on the same element is ignored rather than doubling every
       click, which would fire two inserts per press. */
    attach: function (root) {
      if (!root || root.dataset.prepSchedulerBound) return;
      root.dataset.prepSchedulerBound = "1";
      injectStyles();

      /* The studied checkbox, on CHANGE rather than click, so a keyboard
         toggle counts too. Not in the capture-phase click handler below,
         because that one stops propagation and would prevent the host
         page's own tick handler from ever running. */
      root.addEventListener("change", function (ev) {
        var box = ev.target;
        if (!box || box.type !== "checkbox") return;
        if (box.classList.contains("prep-pickbox")) return;   // ours, not theirs
        var card = box.closest(".q-card");
        if (!card || !root.contains(card)) return;
        syncCompletion(card, box.checked);
      });

      root.addEventListener("click", function (ev) {
        // The bulk checkbox, before anything else. It sits inside the card
        // header, which every host page has wired to open and close the
        // card — so this must stop here or ticking a box also folds the
        // card, which reads as the tick having done nothing.
        var box = ev.target.closest(".prep-pickbox");
        if (box && root.contains(box)) {
          ev.stopPropagation();
          var owner = box.parentElement.querySelector("[data-prep-plan]");
          var t = owner ? (owner.getAttribute("data-title") || "") : "";
          if (box.checked) bulk.picked.add(t); else bulk.picked.delete(t);
          var card = box.closest(".q-card");
          if (card) card.classList.toggle("prep-picked", box.checked);
          paintBulk();
          return;
        }

        var btn = ev.target.closest("[data-prep-plan]");
        if (btn && root.contains(btn)) {
          ev.stopPropagation();
          ev.preventDefault();
          var panel = panelFor(btn);
          if (panel) show(btn, panel, panel.hasAttribute("hidden"));
          return;
        }

        /* Share, in the same capture-phase handler and for the same
           reason as Plan: the button lives in the card header, which
           every host page has wired to fold the card. */
        var sbtn = ev.target.closest("[data-prep-share]");
        if (sbtn && root.contains(sbtn)) {
          ev.stopPropagation();
          ev.preventDefault();
          var spanel = sharePanelFor(sbtn);
          if (spanel) {
            var opening = spanel.hasAttribute("hidden");
            show(sbtn, spanel, opening);
            if (opening) fillSharePanel(sbtn, spanel);
          }
          return;
        }
        var sgo = ev.target.closest("[data-prep-share-go]");
        if (sgo && root.contains(sgo)) {
          ev.stopPropagation();
          ev.preventDefault();
          var sp = sgo.closest(".prep-share-panel");
          var owner2 = sp && sp.parentElement
            ? sp.parentElement.querySelector("[data-prep-share]") : null;
          if (sp && owner2) submitShare(owner2, sp);
          return;
        }
        var go = ev.target.closest("[data-prep-go]");
        if (go && root.contains(go)) {
          ev.stopPropagation();
          ev.preventDefault();
          var p = go.closest(".prep-panel");
          var owner = p.parentElement.querySelector("[data-prep-plan]");
          submit(owner, p);
          return;
        }
        // Typing in the date or time field must not reach the host page's
        // card toggle, which would fold the card shut mid-edit.
        if (ev.target.closest(".prep-panel") && root.contains(ev.target)) {
          ev.stopPropagation();
        }
      }, true);   // capture — see the header comment

      // The bulk bar and the "Planned on" pills both need a card to exist
      // before they can do anything, and at this point none do — see
      // whenCardsReady. landOnTopic does its own waiting.
      whenCardsReady(root, function () {
        mountBulk(root);
        loadScheduled(root);
        loadNotes(root);
      });

      /* A card's body is filled when it OPENS, and on /ai-sde that means a
         fetch that replaces the body wholesale. So watch for the open class
         appearing rather than hooking any one page's toggle, and re-add the
         box if a lazy render has just wiped it. */
      if (window.MutationObserver) {
        new MutationObserver(function (records) {
          for (var i = 0; i < records.length; i++) {
            var card = records[i].target.closest
              ? records[i].target.closest(".q-card")
              : null;
            if (card && card.classList.contains("open")) ensureNote(card);
          }
        }).observe(root, {
          subtree: true, childList: true,
          attributes: true, attributeFilter: ["class"],
        });
      }

      // ?topic= — arriving from the Day Board on one specific line item.
      landOnTopic(root);

      // The pages re-render their list on every filter change, which wipes
      // the injected checkboxes. Re-draw them when the children change —
      // childList only, since paintBoxes() itself mutates inside the cards
      // and observing the subtree would re-enter forever.
      if (window.MutationObserver) {
        var mo = new MutationObserver(function () {
          if (bulk.on && bulk.root === root) paintBoxes();
        });
        mo.observe(root, { childList: true });
      }
    },

    /* Expose the bulk state for tests and for a host page that wants to
       drive it. Deliberately read-only-ish: the module owns the set. */
    _bulk: bulk,
    _fmtWhen: fmtWhen,
    _deadlineOf: deadlineOf,
    _paintScheduled: paintScheduled,
    _ensureNote: ensureNote,
    _notes: function (n) { notesCache = n || {}; notesReady = true; },
  };

  window.PrepScheduler = PrepScheduler;
})();
