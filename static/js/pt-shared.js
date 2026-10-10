/* ════════════════════════════════════════════════════════════════
   DAILYPLANNER — SHARED UI UTILITIES
   Drop-in, no-dependency helpers used across project tasks, the
   Eisenhower matrix, and the daily summary. Each block is guarded so
   loading this twice is a no-op and consumers can safely feature-
   detect (window.ptShowUndo, etc.) before calling.
   ════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";
  if (window.__ptSharedLoaded__) return;
  window.__ptSharedLoaded__ = true;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  };

  /* ── 1. Undo toast ────────────────────────────────────────────
     Usage: ptShowUndo("Task deleted", () => restoreApi(id))
     Shows a toast with an "Undo" button. Fires onUndo if clicked
     within the timeout. Stacks above the normal toast container. */
  window.ptShowUndo = function (message, onUndo, duration = 5500) {
    const toast = document.createElement("div");
    toast.className = "toast toast-undo";
    Object.assign(toast.style, {
      position: "fixed", bottom: "24px", left: "50%",
      transform: "translateX(-50%) translateY(12px)",
      background: "rgba(17,24,39,.94)", color: "#fff",
      padding: "10px 14px 10px 18px", borderRadius: "12px",
      fontSize: "13.5px", fontWeight: "500",
      fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
      boxShadow: "0 12px 32px rgba(0,0,0,.22)",
      zIndex: "10050", display: "flex", alignItems: "center", gap: "10px",
      opacity: "0", transition: "opacity .2s, transform .2s",
      backdropFilter: "blur(8px)",
    });
    toast.innerHTML =
      '<span>' + esc(message) + '</span>' +
      '<button class="toast-undo-btn" type="button">Undo</button>';
    document.body.appendChild(toast);

    requestAnimationFrame(() => {
      toast.style.opacity = "1";
      toast.style.transform = "translateX(-50%) translateY(0)";
    });

    let done = false;
    const dismiss = () => {
      if (done) return;
      done = true;
      toast.style.opacity = "0";
      toast.style.transform = "translateX(-50%) translateY(12px)";
      setTimeout(() => toast.remove(), 220);
    };

    toast.querySelector(".toast-undo-btn").addEventListener("click", () => {
      if (done) return;
      done = true;
      try { onUndo && onUndo(); } catch (e) { console.error("undo failed:", e); }
      toast.remove();
      if (window.showToast) showToast("Undone", "info", 1600);
    });

    setTimeout(dismiss, duration);
  };

  /* ── 2. Global saved indicator ─────────────────────────────────
     Usage: ptSavePing("saving"|"saved"|"error", optionalText)
     Persists a small floating badge top-right. State transitions
     auto-fade after a short window. */
  function ensureSavedEl() {
    let el = $("pt-global-saved");
    if (el) return el;
    el = document.createElement("div");
    el.id = "pt-global-saved";
    document.body.appendChild(el);
    return el;
  }
  let _saveFadeTimer = null;
  window.ptSavePing = function (state, text) {
    const el = ensureSavedEl();
    el.classList.remove("saving", "error", "show");
    const label =
      state === "saving" ? (text || "Saving…") :
      state === "error"  ? (text || "Save failed") :
                           (text || "Saved");
    el.textContent = "✓ " + label;
    if (state === "saving") { el.textContent = "⟳ " + label; el.classList.add("saving"); }
    if (state === "error")  { el.textContent = "! " + label; el.classList.add("error"); }
    el.classList.add("show");
    clearTimeout(_saveFadeTimer);
    if (state !== "saving") {
      _saveFadeTimer = setTimeout(() => el.classList.remove("show"), 1600);
    }
  };

  /* ── 3. Celebration pulse hook ─────────────────────────────────
     Usage: ptPulse(rowElement). Adds .pt-pulse for 420ms, then clean.
     Scoped so it only fires on newly-checked tasks (not on load). */
  window.ptPulse = function (el) {
    if (!el) return;
    el.classList.add("pt-pulse");
    setTimeout(() => el.classList.remove("pt-pulse"), 500);
  };

  /* ── 4. Keyboard shortcuts + cheatsheet ────────────────────────
     Registered at the document level. Guards against typing inside
     inputs/textareas/contenteditable so shortcuts don't clash with
     composition. Each page registers its own handlers via
     ptRegisterShortcut(key, fn, label) — the cheatsheet renders
     dynamically from the registry. */
  const _shortcuts = new Map();
  window.ptRegisterShortcut = function (key, fn, label) {
    _shortcuts.set(key, { fn, label });
  };

  function isTypingTarget(t) {
    if (!t) return false;
    const tag = (t.tagName || "").toLowerCase();
    if (t.isContentEditable) return true;
    return tag === "input" || tag === "textarea" || tag === "select";
  }

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (isTypingTarget(e.target)) {
      // Allow Escape through even from inputs (so it can close modals/blur)
      return;
    }
    const key = e.key;
    // Shift+? → cheatsheet
    if (key === "?" && e.shiftKey) {
      e.preventDefault();
      ptToggleCheatsheet(true);
      return;
    }
    const hit = _shortcuts.get(key);
    if (hit) {
      e.preventDefault();
      try { hit.fn(e); } catch (err) { console.error("shortcut failed:", err); }
    }
  });

  function ensureCheatsheetEl() {
    let el = $("pt-kbd-cheatsheet");
    if (el) return el;
    el = document.createElement("div");
    el.id = "pt-kbd-cheatsheet";
    el.innerHTML = '<div class="pt-kbd-sheet"><h3>Keyboard shortcuts</h3><dl id="pt-kbd-list"></dl></div>';
    el.addEventListener("click", (ev) => { if (ev.target === el) ptToggleCheatsheet(false); });
    document.body.appendChild(el);
    return el;
  }

  window.ptToggleCheatsheet = function (show) {
    const el = ensureCheatsheetEl();
    const list = $("pt-kbd-list");
    list.innerHTML = "";
    _shortcuts.forEach((v, k) => {
      const dt = document.createElement("dt");
      dt.innerHTML = "<kbd>" + esc(k) + "</kbd>";
      const dd = document.createElement("dd");
      dd.textContent = v.label || "";
      list.appendChild(dt); list.appendChild(dd);
    });
    if (_shortcuts.size === 0) {
      list.innerHTML = '<dd style="grid-column:1/-1;color:var(--pt-text3);">No shortcuts registered on this page.</dd>';
    }
    el.classList.toggle("show", !!show);
  };

  // Escape closes the cheatsheet from anywhere
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const el = $("pt-kbd-cheatsheet");
      if (el && el.classList.contains("show")) { ptToggleCheatsheet(false); e.stopPropagation(); }
    }
  });

  /* ── 5. Density toggle (body class + localStorage) ────────────
     Reads pt_density on load. Updates body class + picker UI. */
  const DENSITY_KEY = "pt_density";
  const DENSITY_VALUES = ["comfortable", "cozy", "compact"];
  function applyDensity(value) {
    if (!DENSITY_VALUES.includes(value)) value = "cozy";
    DENSITY_VALUES.forEach(v => document.body.classList.toggle("pt-density-" + v, v === value));
    try { localStorage.setItem(DENSITY_KEY, value); } catch {}
    document.querySelectorAll(".pt-density-picker button").forEach(b => {
      b.classList.toggle("active", b.dataset.density === value);
    });
  }
  window.ptSetDensity = applyDensity;
  // Delegated click handler — any page with a .pt-density-picker benefits.
  document.addEventListener("click", (e) => {
    const btn = e.target && e.target.closest && e.target.closest(".pt-density-picker button");
    if (!btn) return;
    applyDensity(btn.dataset.density);
  });
  // Restore saved density on load.
  try { applyDensity(localStorage.getItem(DENSITY_KEY) || "cozy"); } catch { applyDensity("cozy"); }

  /* ── 6. Global new-task FAB + `n` shortcut ─────────────────────
     A floating + button on mobile and the `n` keystroke on desktop
     both invoke window.ptNewTask() which each page overrides to
     focus its own quick-add or open a modal. */
  window.ptNewTask = window.ptNewTask || function () {
    // Default: navigate to /todo which has the universal quick-add.
    window.location.href = "/todo";
  };

  /* True when the element's stylesheet is on this page. Both the FAB and
     the bottom bar are position:fixed in project_tasks.css (the bar is
     display:none on desktop, which still reports position:fixed). */
  function ptStyled(el) {
    try { return getComputedStyle(el).position === "fixed"; }
    catch (e) { return true; }
  }

  function ensureFab() {
    let el = $("pt-new-fab");
    if (el) return el;
    el = document.createElement("button");
    el.id = "pt-new-fab";
    el.type = "button";
    el.setAttribute("aria-label", "New task");
    el.title = "New task";
    el.textContent = "+";
    el.addEventListener("click", () => window.ptNewTask && window.ptNewTask());
    document.body.appendChild(el);
    // Its styles live in project_tasks.css. A page that loads this script
    // without that sheet got a bare "+" glyph at the bottom of the page.
    if (!ptStyled(el)) { el.remove(); return null; }
    return el;
  }
  document.addEventListener("DOMContentLoaded", ensureFab, { once: true });
  if (document.readyState !== "loading") ensureFab();

  ptRegisterShortcut("n", () => window.ptNewTask && window.ptNewTask(), "New task");

  /* ── 7. Bottom nav bar (mobile only via CSS) ───────────────────
     Rendered once on every page; CSS controls visibility (≤560px). */
  function ensureBottomNav() {
    if ($("pt-bottom-nav")) return;
    const tabs = [
      { href: "/summary?view=daily", label: "Today",    icon: "sun" },
      { href: "/todo",               label: "Tasks",    icon: "check-square" },
      { href: "/projects",           label: "Projects", icon: "folder" },
      { href: "/health",             label: "Health",   icon: "heart" },
    ];
    const bar = document.createElement("nav");
    bar.id = "pt-bottom-nav";
    bar.setAttribute("aria-label", "Primary navigation");
    const path = window.location.pathname;
    bar.innerHTML = tabs.map(t => {
      const active =
        (t.href.startsWith("/summary") && path.startsWith("/summary")) ||
        (t.href === "/todo" && path === "/todo") ||
        (t.href === "/projects" && path.startsWith("/projects")) ||
        (t.href === "/health" && path.startsWith("/health"));
      return '<a href="' + t.href + '"' + (active ? ' class="active"' : '') + '>'
        + '<i data-feather="' + t.icon + '"></i><span>' + t.label + '</span></a>';
    }).join("");
    document.body.appendChild(bar);
    // Same guard as the FAB: unstyled, this rendered as a raw row of links
    // ("TodayTasksProjectsHealth") under the Review page on desktop.
    if (!ptStyled(bar)) { bar.remove(); return; }
    if (window.feather) feather.replace();
  }
  document.addEventListener("DOMContentLoaded", ensureBottomNav, { once: true });
  if (document.readyState !== "loading") ensureBottomNav();

  /* ── 8. Bottom-sheet drag-down-to-dismiss (mobile detail panel)
     Any element matching .task-panel gets a drag handle via CSS
     pseudo-element. Here we wire the pointer drag logic. */
  let _dragState = null;
  function attachSheetDrag(panel) {
    if (!panel || panel.__ptSheetWired__) return;
    panel.__ptSheetWired__ = true;

    panel.addEventListener("pointerdown", (e) => {
      if (window.matchMedia("(min-width: 561px)").matches) return;
      const rect = panel.getBoundingClientRect();
      // Only start drag if touch begins near the top 40px of the panel
      // (the drag handle area — we don't want to hijack form scrolls)
      if (e.clientY - rect.top > 32) return;
      _dragState = { startY: e.clientY, dy: 0, panel };
      panel.classList.add("pt-sheet-dragging");
      panel.setPointerCapture?.(e.pointerId);
    }, { passive: true });

    panel.addEventListener("pointermove", (e) => {
      if (!_dragState || _dragState.panel !== panel) return;
      _dragState.dy = Math.max(0, e.clientY - _dragState.startY);
      panel.style.transform = "translateY(" + _dragState.dy + "px)";
    }, { passive: true });

    const finish = (e) => {
      if (!_dragState || _dragState.panel !== panel) return;
      const dy = _dragState.dy;
      panel.classList.remove("pt-sheet-dragging");
      panel.style.transform = "";
      _dragState = null;
      if (dy > 120) {
        // Close via each page's known handler
        if (typeof window.closeTaskSheet === "function") window.closeTaskSheet();
        else if (typeof window.closeTaskDetails === "function") window.closeTaskDetails();
      }
    };
    panel.addEventListener("pointerup", finish);
    panel.addEventListener("pointercancel", finish);
  }

  // Scan on load and MutationObserver for dynamically-inserted sheets.
  function scanSheets() {
    document.querySelectorAll(".task-panel").forEach(attachSheetDrag);
  }
  document.addEventListener("DOMContentLoaded", scanSheets, { once: true });
  if (document.readyState !== "loading") scanSheets();

  /* ── 9. Swipe gestures on task rows (mobile) ───────────────────
     Scoped to body.pt-touch-swipe (to avoid affecting desktop).
     Right-swipe → toggle checkbox (done). Left-swipe → delete.
     Threshold: 80px horizontal, 20° angle tolerance. */
  const SWIPE_THRESHOLD = 80;
  const SWIPE_CANCEL_Y = 30;

  function isMobileViewport() {
    return window.matchMedia("(max-width: 560px)").matches;
  }

  let _swipe = null;
  document.addEventListener("pointerdown", (e) => {
    if (!isMobileViewport()) return;
    const row = e.target.closest && e.target.closest(".task-row");
    if (!row) return;
    // Skip if the pointer is on an interactive child (checkbox, button, input)
    if (e.target.closest("input, button, select, a, .row-details-btn")) return;
    _swipe = { row, x0: e.clientX, y0: e.clientY, dx: 0 };
  }, { passive: true });

  document.addEventListener("pointermove", (e) => {
    if (!_swipe) return;
    const dx = e.clientX - _swipe.x0;
    const dy = Math.abs(e.clientY - _swipe.y0);
    if (dy > SWIPE_CANCEL_Y && Math.abs(dx) < 10) { _swipe = null; return; }
    _swipe.dx = dx;
    const row = _swipe.row;
    row.classList.add("pt-swiping");
    row.classList.toggle("pt-swiping-done", dx > 20);
    row.classList.toggle("pt-swiping-delete", dx < -20);
    row.style.transform = "translateX(" + dx + "px)";
  }, { passive: true });

  const finishSwipe = () => {
    if (!_swipe) return;
    const { row, dx } = _swipe;
    _swipe = null;
    row.classList.remove("pt-swiping", "pt-swiping-done", "pt-swiping-delete");
    row.style.transform = "";

    if (dx >= SWIPE_THRESHOLD) {
      // Mark done via the row's native checkbox
      const cb = row.querySelector('input[type="checkbox"].task-check, input[type="checkbox"]');
      if (cb) {
        cb.checked = !cb.checked;
        cb.dispatchEvent(new Event("change", { bubbles: true }));
      }
    } else if (dx <= -SWIPE_THRESHOLD) {
      // Fire a generic "delete" intent — each page wires its own.
      const detail = { id: row.dataset.id };
      row.dispatchEvent(new CustomEvent("pt-swipe-delete", { bubbles: true, detail }));
    }
  };
  document.addEventListener("pointerup", finishSwipe, { passive: true });
  document.addEventListener("pointercancel", finishSwipe, { passive: true });

  /* ── 10. Escape-to-close helper ────────────────────────────────
     Pages can call ptOnEscape(() => close()) to register a handler.
     Registered callbacks are LIFO — last-opened modal closes first. */
  const _escStack = [];
  window.ptOnEscape = function (fn) {
    _escStack.push(fn);
    return () => {
      const idx = _escStack.indexOf(fn);
      if (idx >= 0) _escStack.splice(idx, 1);
    };
  };
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || _escStack.length === 0) return;
    const fn = _escStack[_escStack.length - 1];
    try { fn(e); } catch (err) { console.error("escape handler failed:", err); }
  });
})();
