/* DailyPlanner — Web Push client helpers (exported as window.ClPush).
   Handles service-worker registration, subscribe / unsubscribe, and
   syncing the subscription to the server. */
(function () {
  const SW_PATH = "/service-worker.js";

  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; ++i) out[i] = raw.charCodeAt(i);
    return out;
  }

  async function getRegistration() {
    if (!("serviceWorker" in navigator)) return null;
    const reg = await navigator.serviceWorker.getRegistration();
    if (reg) return reg;
    return navigator.serviceWorker.register(SW_PATH, { scope: "/" });
  }

  async function currentSubscription() {
    const reg = await getRegistration();
    if (!reg) return null;
    return reg.pushManager.getSubscription();
  }

  async function fetchVapidKey() {
    const res = await fetch("/api/push/vapid-public-key", { credentials: "same-origin" });
    if (!res.ok) throw new Error("Could not fetch VAPID key");
    const { key } = await res.json();
    return key;
  }

  async function subscribe() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      throw new Error("This browser does not support Web Push.");
    }
    const perm = await Notification.requestPermission();
    if (perm !== "granted") throw new Error("Notifications permission denied.");

    const reg = await getRegistration();
    const vapid = await fetchVapidKey();

    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapid),
      });
    }

    await fetch("/api/push/subscribe", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subscription: sub.toJSON(), user_agent: navigator.userAgent }),
    });
    return sub;
  }

  async function unsubscribe() {
    const sub = await currentSubscription();
    if (!sub) return;
    await fetch("/api/push/unsubscribe", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: sub.endpoint }),
    });
    await sub.unsubscribe();
  }

  async function sendTest() {
    const res = await fetch("/api/push/test", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) throw new Error("Test failed: HTTP " + res.status);
    return res.json();
  }

  // ── UI wiring used by the checklist page ─────────
  /* "Not now" on the reminders prompt is remembered per device (push is
     per device too) for SNOOZE_DAYS, so the card stops reappearing on
     every visit. localStorage can be unavailable (private mode); then the
     prompt simply shows as before. */
  const SNOOZE_KEY = "dp.pushPrompt.snoozedUntil";
  const SNOOZE_DAYS = 14;
  function snoozed() {
    try { return Number(localStorage.getItem(SNOOZE_KEY) || 0) > Date.now(); }
    catch (_) { return false; }
  }
  function setSnooze(on) {
    try {
      if (on) localStorage.setItem(SNOOZE_KEY, String(Date.now() + SNOOZE_DAYS * 86400000));
      else localStorage.removeItem(SNOOZE_KEY);
    } catch (_) { /* storage blocked: nothing to remember */ }
  }

  async function init({ statusEl, statusOkEl, enableBtn, disableBtn, testBtn,
                        notNowBtn, snoozedEl, unsnoozeBtn }) {
    const supported = "serviceWorker" in navigator && "PushManager" in window;

    async function refresh() {
      if (!supported) {
        statusEl.hidden = false;
        statusEl.querySelector(".cl-push-text strong").textContent =
          "This browser does not support Web Push.";
        enableBtn.hidden = true;
        return;
      }
      const sub = await currentSubscription();
      const on = Boolean(sub) && Notification.permission === "granted";
      const quiet = !on && snoozed();
      statusEl.hidden = on || quiet;
      statusOkEl.hidden = !on;
      if (snoozedEl) snoozedEl.hidden = !quiet;

      /* SELF-HEAL THE SERVER'S COPY.
         This used to check only whether the BROWSER holds a subscription,
         and reported "notifications are on" whenever it did. But the server
         marks a row is_active=false the moment a send comes back 404/410,
         and the browser is not told — so the two drift apart and the UI
         confidently says on while nothing will ever be delivered.

         Found in live data: six subscriptions for the same Android phone,
         every one inactive, the newest already a month old. Checklist
         reminders had not been arriving at all, which is the likeliest
         reason nothing on that checklist had been ticked in four months.

         Re-registering is idempotent — /api/push/subscribe upserts on the
         endpoint and sets is_active=true — so doing it on every load is
         cheap and repairs the drift without the user knowing there was any. */
      if (on) {
        try {
          await fetch("/api/push/subscribe", {
            method: "POST",
            credentials: "same-origin",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": document.querySelector('meta[name=csrf-token]')?.content || "",
            },
            // Same shape subscribe() sends — the server reads
            // data["subscription"], so a flat body is a 400.
            body: JSON.stringify({
              subscription: sub.toJSON(),
              user_agent: navigator.userAgent,
            }),
          });
        } catch (_) {
          /* Offline, or the endpoint is unhappy. The next load tries again;
             there is nothing useful to tell the user here. */
        }
      }
    }

    enableBtn?.addEventListener("click", async () => {
      enableBtn.disabled = true;
      try {
        await subscribe();
        setSnooze(false);
        await refresh();
      } catch (err) {
        alert(err.message || "Could not enable notifications.");
      } finally {
        enableBtn.disabled = false;
      }
    });

    notNowBtn?.addEventListener("click", async () => {
      setSnooze(true);
      await refresh();
    });

    unsnoozeBtn?.addEventListener("click", async () => {
      setSnooze(false);
      await refresh();
      enableBtn?.focus();
    });

    disableBtn?.addEventListener("click", async () => {
      try { await unsubscribe(); } catch (_) { /* noop */ }
      await refresh();
    });

    testBtn?.addEventListener("click", async () => {
      testBtn.disabled = true;
      try {
        const r = await sendTest();
        if (!r.sent) alert("No active device subscriptions were reachable.");
      } catch (err) {
        alert(err.message);
      } finally {
        testBtn.disabled = false;
      }
    });

    await refresh();
  }

  /* ── SELF-HEAL ───────────────────────────────────────────────────────
     A push subscription dies on its own. The browser rotates it, an OS
     update invalidates it, or the push service returns 410 and the server
     correctly marks the row inactive. Nothing then ever brings it back:
     the browser still HAS a working subscription, the server believes it
     has none, and the interface goes on showing notifications as enabled.

     That is why this household's reminders stopped. Six of seven
     subscriptions were inactive, every one of them the phone, and nobody
     could have known — the switch said on.

     So on every load, if permission is already granted, we re-register
     whatever the browser has. It reactivates the row and costs one small
     POST a day.

     IT NEVER PROMPTS. The permission check comes first, so a page load can
     never produce a permission dialog nobody asked for. */
  const HEAL_KEY = "dp-push-heal";
  const HEAL_EVERY_MS = 12 * 3600 * 1000;

  async function healSubscription() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
    // Only ever act on an ALREADY GRANTED permission — never ask.
    if (typeof Notification === "undefined" ||
        Notification.permission !== "granted") return;

    let throttled = false;
    try {
      const last = parseInt(localStorage.getItem(HEAL_KEY) || "0", 10);
      throttled = Date.now() - last < HEAL_EVERY_MS;
    } catch (_) { /* private mode: heal every load, which is harmless */ }

    try {
      const reg = await navigator.serviceWorker.ready;
      let sub = await reg.pushManager.getSubscription();

      /* ── A REVOKED SUBSCRIPTION MUST BE REPLACED, NOT RE-SENT ────────
         Diagnosed 2026-08-23: one phone reported 410 — "the subscription
         was revoked by the browser or device" — while the other two
         devices delivered normally. Seven of that phone's registrations
         had accumulated and died the same way.

         This is why. getSubscription() keeps handing back a subscription
         the push service has already revoked, so the heal below re-posted
         it, the server marked it active again, the next send got another
         410 and retired it again. Round and round, and every so often a
         genuinely new endpoint would appear and join the pile.

         Only unsubscribe() followed by subscribe() produces a fresh
         endpoint. The server is the one that knows the old one is dead —
         it is the only party that ever sees the 410 — so it is asked.

         Deliberately NOT throttled: this is the case where waiting up to
         twelve hours to try again means twelve hours of silence, and it
         costs one small request per load. */
      if (sub) {
        try {
          const r = await fetch("/api/push/status", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ endpoint: sub.endpoint }),
          });
          const st = r.ok ? await r.json() : null;
          if (st && st.known && !st.active) {
            try { await sub.unsubscribe(); } catch (_) { /* already gone */ }
            sub = null;                 // fall through and make a new one
            throttled = false;          // and send it up straight away
          }
        } catch (_) { /* offline — leave it for the next load */ }
      }

      if (throttled && sub) return;

      if (!sub) {
        // Permission granted but no subscription: the browser dropped it.
        // Re-creating one shows no dialog, because permission is granted.
        const vapid = await fetchVapidKey();
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(vapid),
        });
      }
      await fetch("/api/push/subscribe", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        // NESTED under `subscription` — the server reads data["subscription"]
        // and a flat body 400s every time.
        body: JSON.stringify({
          subscription: sub.toJSON(),
          user_agent: navigator.userAgent,
        }),
      });
      try { localStorage.setItem(HEAL_KEY, String(Date.now())); } catch (_) {}
    } catch (_) {
      // Offline, or the browser refused. Try again next load.
    }
  }

  // Registers the SW on every page load (so offline/push infra is warm).
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register(SW_PATH, { scope: "/" })
        .then(healSubscription)
        .catch(() => {});
    });
  }

  window.ClPush = { init, subscribe, unsubscribe, currentSubscription, sendTest,
                    healSubscription };
})();
