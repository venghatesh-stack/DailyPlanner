/* DailyPlanner — PWA UX glue.
   Two responsibilities, both small:
     1. Capture beforeinstallprompt and expose a custom "Install app"
        button instead of relying on the browser's hidden menu item.
     2. Detect when a new service worker has installed and is waiting,
        and surface a "Reload to update" toast so users don't see stale
        UI for days.

   push.js is the file that actually registers the SW; we only attach
   listeners to the existing registration. */

(function () {
  "use strict";

  /* ───── install prompt ──────────────────────────────────────── */

  let deferredPrompt = null;

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    showInstallButton();
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    hideInstallButton();
    if (window.showToast) showToast("Installed — find DailyPlanner on your home screen", "success", 4000);
  });

  function showInstallButton() {
    if (document.getElementById("pwa-install-btn")) return;
    // Hide on iOS Safari (no install prompt event, install is via Share
    // sheet) and inside an already-installed PWA.
    if (window.matchMedia("(display-mode: standalone)").matches) return;
    if (navigator.standalone) return;

    const btn = document.createElement("button");
    btn.id = "pwa-install-btn";
    btn.type = "button";
    btn.textContent = "Install app";
    Object.assign(btn.style, {
      position: "fixed",
      right: "16px",
      bottom: "calc(16px + env(safe-area-inset-bottom))",
      zIndex: "9000",
      background: "#6366f1",
      color: "#fff",
      border: "0",
      borderRadius: "999px",
      padding: "10px 18px",
      fontSize: "14px",
      fontWeight: "600",
      fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
      boxShadow: "0 8px 24px rgba(99,102,241,0.35)",
      cursor: "pointer",
    });
    btn.addEventListener("click", async () => {
      if (!deferredPrompt) return;
      btn.disabled = true;
      deferredPrompt.prompt();
      try { await deferredPrompt.userChoice; } catch (_) {}
      deferredPrompt = null;
      hideInstallButton();
    });
    document.body.appendChild(btn);
  }

  function hideInstallButton() {
    const btn = document.getElementById("pwa-install-btn");
    if (btn) btn.remove();
  }

  /* ───── SW update toast ─────────────────────────────────────── */

  if (!("serviceWorker" in navigator)) return;

  // push.js already calls register() on the load event. We just wait
  // for whatever registration exists and watch its update lifecycle.
  navigator.serviceWorker.ready.then((reg) => {
    if (!reg) return;

    // Periodic Background Sync — Chrome installed-PWA only. We can't
    // prompt for the permission directly (Chrome only grants it to
    // sites the user has "installed AND engaged with"), but we can
    // probe whether it's already granted and register if so.
    if ("periodicSync" in reg) {
      navigator.permissions
        .query({ name: "periodic-background-sync" })
        .then((status) => {
          if (status.state === "granted") {
            reg.periodicSync.register("dp-prefetch", {
              minInterval: 12 * 60 * 60 * 1000,  // 12h; browser may delay
            }).catch(() => { /* may fail on first install — silent */ });
          }
        })
        .catch(() => {});
    }

    // A waiting worker was present before this page loaded — prompt now.
    if (reg.waiting && navigator.serviceWorker.controller) {
      promptReload(reg.waiting);
    }

    reg.addEventListener("updatefound", () => {
      const sw = reg.installing;
      if (!sw) return;
      sw.addEventListener("statechange", () => {
        if (sw.state === "installed" && navigator.serviceWorker.controller) {
          promptReload(sw);
        }
      });
    });
  }).catch(() => { /* SW unsupported or registration failed — silent */ });

  // Once the new SW takes control, reload exactly once.
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloading) return;
    reloading = true;
    location.reload();
  });

  function promptReload(sw) {
    if (!window.showToast) {
      // Toast not loaded yet (race) — try again shortly.
      setTimeout(() => promptReload(sw), 500);
      return;
    }
    showToast("New version available", "info", 8000, {
      label: "Reload",
      onClick: () => sw.postMessage({ type: "SKIP_WAITING" }),
    });
  }

  /* ───── iOS install banner ──────────────────────────────────── */

  // iOS Safari can't fire beforeinstallprompt, so the Install FAB above
  // never appears on iPhone/iPad. Without a hint, users have no idea
  // they can install. Show a one-time banner with the Share→Add steps.
  // Stored in localStorage so we don't nag — user can also dismiss
  // explicitly to suppress forever.
  const IOS_HINT_KEY = "dp-ios-install-hint-v1";
  function isIOS() {
    if (window.MSStream) return false;
    if (/iPad|iPhone|iPod/.test(navigator.userAgent)) return true;
    // iPadOS 13+ reports itself as "Macintosh" and is otherwise
    // indistinguishable from a desktop Mac — except that a desktop Mac has
    // no touch points. Without this an iPad never saw the install hint at
    // all, because the only way to install there is the one this explains.
    return navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
  }
  function isInStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  }
  function showIOSInstallHint() {
    if (!isIOS() || isInStandalone()) return;
    try {
      const stored = localStorage.getItem(IOS_HINT_KEY);
      if (stored === "dismissed") return;
      const lastShown = parseInt(stored || "0", 10);
      // Don't re-show inside 30 days even if not explicitly dismissed.
      if (Date.now() - lastShown < 30 * 24 * 3600 * 1000) return;
    } catch (_) {}

    const bar = document.createElement("div");
    bar.id = "dp-ios-install-hint";
    Object.assign(bar.style, {
      position: "fixed",
      left: "12px",
      right: "12px",
      bottom: "calc(12px + env(safe-area-inset-bottom))",
      zIndex: "9001",
      background: "#1f2330",
      color: "#fff",
      padding: "14px 16px",
      borderRadius: "14px",
      fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
      fontSize: "14px",
      lineHeight: "1.4",
      display: "flex",
      gap: "12px",
      alignItems: "center",
      boxShadow: "0 10px 30px rgba(0,0,0,0.35)",
    });
    bar.innerHTML = `
      <img src="/static/icons/icon-192.png" alt="" style="width:36px;height:36px;border-radius:8px;flex:0 0 36px">
      <div style="flex:1">
        <div style="font-weight:600;margin-bottom:2px">Install DailyPlanner</div>
        <div style="opacity:0.85">Tap <b>Share</b> ⬆︎, then <b>Add to Home Screen</b>.</div>
      </div>
      <button type="button" id="dp-ios-hint-dismiss"
        style="background:transparent;border:0;color:#9ca3af;font-size:22px;cursor:pointer;padding:4px 8px;line-height:1">×</button>
    `;
    document.body.appendChild(bar);
    document.getElementById("dp-ios-hint-dismiss").addEventListener("click", () => {
      try { localStorage.setItem(IOS_HINT_KEY, "dismissed"); } catch (_) {}
      bar.remove();
    });
    try { localStorage.setItem(IOS_HINT_KEY, String(Date.now())); } catch (_) {}
  }
  // Delay slightly so it doesn't compete with first paint.
  setTimeout(showIOSInstallHint, 2500);

  /* ON DEMAND. The banner above shows once and then not for thirty days,
     which is right for a hint and wrong as the ONLY route to it: dismiss it
     once, or install on one device and later get another, and the
     instructions are unreachable. Settings can call this. */
  window.dpShowInstallHelp = function () {
    try { localStorage.removeItem(IOS_HINT_KEY); } catch (_) {}
    var old = document.getElementById("dp-ios-install-hint");
    if (old) old.remove();
    if (isInStandalone()) {
      alert("DailyPlanner is already installed — you are running it now.");
      return;
    }
    if (isIOS()) { showIOSInstallHint(); return; }
    alert("On Android/Chrome use the Install button, or the browser menu's " +
          "\"Install app\" / \"Add to Home screen\".");
  };

  /* ───── offline-queue status pill ───────────────────────────── */

  // Tiny indicator that appears in the bottom-left whenever there are
  // queued writes. Clicking it pokes the SW to retry. Hidden when the
  // queue is empty. Uses a fixed-position element so it doesn't require
  // any page-specific markup — works on every screen.
  function ensurePill() {
    let pill = document.getElementById("dp-queue-pill");
    if (pill) return pill;
    pill = document.createElement("button");
    pill.id = "dp-queue-pill";
    pill.type = "button";
    pill.title = "Click to retry now";
    Object.assign(pill.style, {
      position: "fixed",
      left: "16px",
      bottom: "calc(16px + env(safe-area-inset-bottom))",
      zIndex: "9000",
      background: "#f59e0b",
      color: "#fff",
      border: "0",
      borderRadius: "999px",
      padding: "8px 14px",
      fontSize: "13px",
      fontWeight: "600",
      fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
      boxShadow: "0 6px 18px rgba(245,158,11,0.35)",
      cursor: "pointer",
      display: "none",
    });
    pill.addEventListener("click", () => {
      if (window.dpSync) window.dpSync.replay();
      if (window.showToast) showToast("Retrying queued writes…", "info", 2000);
    });
    document.body.appendChild(pill);
    return pill;
  }

  async function refreshPill() {
    if (!window.dpSync) return;
    const n = await window.dpSync.pendingCount();
    const pill = ensurePill();
    if (n > 0) {
      pill.textContent = n === 1
        ? "1 change pending"
        : `${n} changes pending`;
      pill.style.display = "";
      // Green-ish once we're back online — visual hint that a retry
      // is imminent (Background Sync) or possible (click the pill).
      pill.style.background = navigator.onLine ? "#22c55e" : "#f59e0b";
      pill.style.boxShadow  = navigator.onLine
        ? "0 6px 18px rgba(34,197,94,0.35)"
        : "0 6px 18px rgba(245,158,11,0.35)";
    } else {
      pill.style.display = "none";
    }
  }

  if (window.dpSync) {
    window.dpSync.onQueued(refreshPill);
    window.dpSync.onResult((r) => {
      refreshPill();
      refreshBadge();
      if (!window.showToast) return;
      if (r.ok) {
        showToast("Synced", "success", 1800);
      } else if (r.conflict) {
        // Server says the row was touched elsewhere. Keep it simple:
        // surface a toast with a link to /pending where the user can
        // see what was queued and decide. A full inline chooser would
        // need to know which UI surface owns the row.
        showToast("Sync conflict — open Pending to resolve", "warning", 6000, {
          label: "Open", onClick: () => { location.href = "/pending"; },
        });
      } else {
        showToast(`Sync failed (${r.status})`, "error", 3500);
      }
    });
  }
  window.addEventListener("online",  refreshPill);
  window.addEventListener("offline", refreshPill);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { refreshPill(); refreshBadge(); }
  });
  refreshPill();

  /* ───── App Badging — unread count on dock/launcher icon ─────
     Chrome 81+/Edge desktop, Safari 16.4+ macOS. No-ops elsewhere
     (we still poll the endpoint, just don't set anything). */
  async function refreshBadge() {
    if (!("setAppBadge" in navigator) && !("clearAppBadge" in navigator)) return;
    try {
      const r = await fetch("/api/badge", { credentials: "same-origin" });
      if (!r.ok) return;
      const { count } = await r.json();
      if (count > 0 && navigator.setAppBadge) {
        navigator.setAppBadge(count).catch(() => {});
      } else if (navigator.clearAppBadge) {
        navigator.clearAppBadge().catch(() => {});
      }
    } catch (_) { /* ignore — best effort */ }
  }
  // Refresh every 5 min while page is in foreground; also on focus.
  setInterval(() => { if (!document.hidden) refreshBadge(); }, 5 * 60 * 1000);
  refreshBadge();
})();
