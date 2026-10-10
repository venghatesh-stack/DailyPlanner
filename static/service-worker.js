/* DailyPlanner — service worker.
   Responsibilities:
     1. Receive Web Push events and display a notification.
     2. On notification click, focus an existing window or open a new
        one at the payload URL.
     3. Offline caching: serve a usable shell when the network is down.

   Cache strategy:
     - /static/* and /manifest.json + /service-worker.js  → SWR
       (return cache instantly, refresh in background).
     - Same-origin HTML navigations → network-first with cache fallback,
       and /offline as the last resort.
     - Cross-origin, non-GET, /api/*, /admin/* → pass through, no cache.

   Bump CACHE_VERSION on every deploy so stale chunks get evicted. The
   route at /service-worker.js is served with no-cache (app.py), so a
   new version is picked up on the next page load. */

const CACHE_VERSION = "v281-2026-10-11-roadmap-colour"
const STATIC_CACHE = `dp-static-${CACHE_VERSION}`;
const PAGES_CACHE  = `dp-pages-${CACHE_VERSION}`;
const OFFLINE_URL  = "/offline";

// LRU caps per cache so the SW doesn't grow unbounded for users who
// hop around 50+ pages. We trim oldest entries (insertion order) when
// the cache exceeds the cap. Static assets get more headroom because
// they're small and cache hits are valuable.
const CACHE_LIMITS = {
  [STATIC_CACHE]: 120,
  [PAGES_CACHE]:  50,
};

// Files we want available immediately on first install so the very
// first offline open works. Keep this list short — anything missed
// is still cached lazily on first fetch.
const PRECACHE_URLS = [
  OFFLINE_URL,
  "/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/apple-touch-icon.png",
  // The keep-alive track. Precached because it is what holds the app alive
  // when the screen is off, and fetching it at that moment is exactly when
  // the network is least likely to be there.
  "/static/audio-keepalive.wav",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(STATIC_CACHE);
    // Use addAll so a single 404 doesn't fail the whole install —
    // wrap each so missing files don't block activation.
    await Promise.all(PRECACHE_URLS.map(async (url) => {
      try { await cache.add(new Request(url, { cache: "reload" })); }
      catch (_) { /* tolerate — lazy cache will pick it up later */ }
    }));
    self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    // Evict caches from prior versions.
    const names = await caches.keys();
    await Promise.all(
      names
        .filter((n) => n.startsWith("dp-") && n !== STATIC_CACHE && n !== PAGES_CACHE)
        .map((n) => caches.delete(n))
    );
    await self.clients.claim();
  })());
});

// Page → SW messages:
//   SKIP_WAITING  — activate the freshly installed SW right now
//   DP_REPLAY     — drain the offline write queue immediately
//                   (used by browsers without Background Sync)
self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type === "SKIP_WAITING") self.skipWaiting();
  if (data.type === "DP_REPLAY")    event.waitUntil(replayQueue());
});

// Background Sync — Chrome/Edge fire this when connectivity returns,
// even when no tab is open. Tag must match sync-queue.js SYNC_TAG.
self.addEventListener("sync", (event) => {
  if (event.tag === "dp-replay") event.waitUntil(replayQueue());
});

// Periodic Background Sync — Chrome/Edge only, requires the site to
// be installed AND the user to have granted the 'periodic-background-
// sync' permission. We register from pwa.js with a 12h interval; the
// browser fires this no more often than its own heuristics allow,
// which is usually closer to once per day. Best-effort prefetch of
// today's checklist + inbox so opening the app feels instant.
self.addEventListener("periodicsync", (event) => {
  if (event.tag === "dp-prefetch") event.waitUntil(prefetchToday());
});

async function prefetchToday() {
  const cache = await caches.open(PAGES_CACHE);
  const urls = ["/checklist", "/inbox", "/quick-bucket"];
  await Promise.all(urls.map(async (url) => {
    try {
      const res = await fetch(url, { credentials: "include" });
      if (res && res.ok && res.type === "basic") await cache.put(url, res.clone());
    } catch (_) { /* offline at sync time — skip */ }
  }));
}

/* ───── offline write queue (replay side) ─────────────────────────
   The page (sync-queue.js) writes records into IndexedDB when a
   mutating request fails for network reasons. We replay them oldest-
   first as soon as we get a chance, post the result back to every
   open client, and delete the record on a definitive outcome.
   "Definitive" = any HTTP response (2xx, or 4xx/5xx — re-sending a
   400 won't suddenly succeed); network-level failures keep the record
   for the next sync event. */

const QUEUE_DB    = "dp-queue";
const QUEUE_STORE = "writes";

function openQueueDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(QUEUE_DB, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(QUEUE_STORE)) {
        db.createObjectStore(QUEUE_STORE, { keyPath: "id", autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror   = () => reject(req.error);
  });
}

function queueAll(db) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(QUEUE_STORE, "readonly");
    const req = tx.objectStore(QUEUE_STORE).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror   = () => reject(req.error);
  });
}

function queueDelete(db, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(QUEUE_STORE, "readwrite");
    const req = tx.objectStore(QUEUE_STORE).delete(id);
    req.onsuccess = () => resolve();
    req.onerror   = () => reject(req.error);
  });
}

function queueUpdate(db, record) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(QUEUE_STORE, "readwrite");
    const req = tx.objectStore(QUEUE_STORE).put(record);
    req.onsuccess = () => resolve();
    req.onerror   = () => reject(req.error);
  });
}

function rehydrateBody(body) {
  if (!body || body.kind === "none") return undefined;
  if (body.kind === "text")          return body.value;
  if (body.kind === "urlencoded")    return body.value;
  if (body.kind === "buffer")        return body.value;
  if (body.kind === "blob")          return new Blob([body.value], { type: body.type });
  return undefined;
}

async function notifyClients(payload) {
  const clients = await self.clients.matchAll({ includeUncontrolled: true });
  for (const c of clients) {
    try { c.postMessage(Object.assign({ type: "DP_SYNC_RESULT" }, payload)); }
    catch (_) { /* client gone */ }
  }
}

let replayInFlight = null;

function replayQueue() {
  // Coalesce concurrent triggers (sync event + page message racing).
  if (replayInFlight) return replayInFlight;
  replayInFlight = (async () => {
    try {
      const db = await openQueueDB();
      const records = await queueAll(db);
      // Oldest first so causally-related writes (create then update)
      // replay in the order the user made them.
      records.sort((a, b) => a.queuedAt - b.queuedAt);

      for (const rec of records) {
        const headers = Object.assign({}, rec.headers || {});
        // For Content-Type, leave whatever the page sent (usually JSON).
        let res;
        try {
          res = await fetch(rec.url, {
            method:  rec.method,
            headers,
            body:    rehydrateBody(rec.body),
            credentials: "include",
          });
        } catch (netErr) {
          // Still offline — bump attempt counter and stop. Next sync
          // event (or 'online' postMessage) will pick up where we left.
          rec.attempts = (rec.attempts || 0) + 1;
          rec.lastError = String(netErr);
          await queueUpdate(db, rec);
          // Abort the whole drain: if this one failed, the next likely
          // will too. Re-throwing would also cancel the sync retry; we
          // want it to come back, so resolve cleanly.
          return;
        }

        // Read body for the page to consume. Tolerate non-JSON responses.
        let bodyText = "";
        try { bodyText = await res.text(); } catch (_) {}
        let bodyJson = null;
        if ((res.headers.get("content-type") || "").includes("application/json")) {
          try { bodyJson = JSON.parse(bodyText); } catch (_) {}
        }

        await queueDelete(db, rec.id);
        await notifyClients({
          clientId: rec.clientId,
          ok:       res.ok,
          status:   res.status,
          // 409 from a queued write is a real conflict: the same row
          // was changed on another device while this one was offline.
          // The page can distinguish via .conflict and show a chooser
          // instead of treating it as a generic failure.
          conflict: res.status === 409,
          url:      rec.url,
          method:   rec.method,
          body:     bodyJson != null ? bodyJson : bodyText,
        });
      }
    } finally {
      replayInFlight = null;
    }
  })();
  return replayInFlight;
}

/* ───── fetch routing ─────────────────────────────────────────── */

self.addEventListener("fetch", (event) => {
  const req = event.request;

  // Bail out fast for things we never want to handle.
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  // Range requests (audio/video) are not cache-friendly.
  if (req.headers.has("range")) return;

  /* ── THE RENDERED ANNOUNCEMENT IS AN ASSET, NOT AN API CALL ────────
     /api/announcer/say?text=… returns the same audio for the same words
     forever, and it has to be playable on a phone that is locked, frozen
     and possibly off the network — which is precisely when a request is
     least likely to succeed. Cached by URL so the media element gets a
     local hit.

     It sits above the /api/ early-return deliberately: everything else
     under /api/ must stay live, and this is the one exception. */
  if (url.pathname === "/api/announcer/say") {
    event.respondWith(cacheFirst(req, STATIC_CACHE));
    return;
  }

  // API endpoints, push subscription, auth callbacks — always live.
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/admin/") ||
    url.pathname.startsWith("/auth/") ||
    url.pathname.startsWith("/oauth/") ||
    url.pathname.startsWith("/push/")
  ) {
    return;
  }

  // ── THE APP'S OWN CODE — NETWORK FIRST ────────────────────────────
  // Stale-while-revalidate serves the PREVIOUS copy and fetches the new
  // one for next time, which means every deploy is one reload behind. On
  // a phone that is invisible: the PWA is opened and killed constantly,
  // so it catches up within minutes. On a desktop tab left open for days
  // it is not — reported as "check in desktop addition, mobile seems to
  // be working", with three unrelated controls appearing broken on one
  // device because that device was simply running last week's script.
  //
  // JS and CSS are small and there is a cache fallback two lines down, so
  // there is nothing to buy by serving them stale. Images, fonts and the
  // keep-alive audio keep stale-while-revalidate: they are big, they do
  // not change, and being a version behind on an icon costs nothing.
  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.json") {
    const isCode = /\.(?:js|css)$/i.test(url.pathname) ||
                   url.pathname === "/manifest.json";
    event.respondWith(isCode ? networkFirst(req, STATIC_CACHE, true)
                             : staleWhileRevalidate(req, STATIC_CACHE));
    return;
  }

  // HTML navigations — network-first, cache fallback, /offline last.
  const isHTML =
    req.mode === "navigate" ||
    (req.headers.get("accept") || "").includes("text/html");
  if (isHTML) {
    event.respondWith(networkFirst(req, PAGES_CACHE));
    return;
  }
});

async function staleWhileRevalidate(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  const network = fetch(req)
    .then(async (res) => {
      if (res && res.ok) {
        await cache.put(req, res.clone()).catch(() => {});
        trimCache(cacheName);
      }
      return res;
    })
    .catch(() => null);
  return cached || (await network) || Response.error();
}

/* Cache first, then network — for responses that never change for a given
   URL. A miss still goes to the network and stores the result. */
async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  if (hit) return hit;
  try {
    const res = await fetch(req);
    /* ONLY CACHE IT IF IT IS ACTUALLY AUDIO.
       /api/announcer/say is behind @login_required, which answers an
       unauthenticated request with a 302 to the login PAGE — and fetch()
       follows redirects, so what arrives is a perfectly "ok" 200 of
       text/html. Storing that would put the login page in the cache under
       the announcement's URL, permanently, and every future play would
       hand HTML to a media element: NotSupportedError, for good.

       An expired session at the wrong moment is enough to trigger it, so
       the check is on the CONTENT TYPE rather than on the status. */
    const type = res && res.headers && (res.headers.get("content-type") || "");
    if (res && res.ok && res.type === "basic" && /^audio\//i.test(type)) {
      cache.put(req, res.clone()).catch(() => {});
      trimCache(cacheName);
    }
    return res;
  } catch (_) {
    return new Response("", { status: 503, statusText: "Offline" });
  }
}

async function networkFirst(req, cacheName, revalidate) {
  const cache = await caches.open(cacheName);
  try {
    /* ── "NETWORK FIRST" WAS NOT REACHING THE NETWORK ──────────────────
       Flask serves /static with SEND_FILE_MAX_AGE_DEFAULT = 30 days, so
       every script and stylesheet carries `max-age=2592000`. A plain
       fetch() consults the browser's HTTP cache before the network, finds
       a fresh entry and returns it — no request is made at all. So the
       switch to network-first changed nothing for the files it was added
       for, and a phone stayed on a build for as long as its HTTP cache
       held: reported as a device still showing v262 while the server was
       serving v265.

       `cache: "no-cache"` does not mean "do not cache". It means always
       revalidate with the server, which sends If-None-Match and usually
       gets back a 304 — the cheap request that was never being made.
       Media keeps the plain path: those are big, unchanging, and being a
       version behind on an icon costs nothing. */
    const res = await fetch(revalidate ? new Request(req, { cache: "no-cache" })
                                       : req);
    if (res && res.ok && res.type === "basic") {
      cache.put(req, res.clone()).catch(() => {});
      trimCache(cacheName);
    }
    return res;
  } catch (_) {
    const cached = await cache.match(req);
    if (cached) return cached;
    // THE OFFLINE PAGE IS HTML, and handing HTML back for a .js or .css
    // request does not degrade gracefully — it throws a syntax error at
    // the top of the file and takes the whole script with it. Only a
    // navigation can be answered with a page.
    if (req.destination === "script" || req.destination === "style") {
      return new Response("", { status: 503, statusText: "Offline" });
    }
    const offline = await caches.match(OFFLINE_URL);
    if (offline) return offline;
    return new Response("Offline", { status: 503, statusText: "Offline" });
  }
}

// Cache.keys() returns entries in insertion order, which we treat as
// LRU since each successful fetch re-puts the request (deleting the
// old entry and appending). Fire-and-forget — no await needed in the
// response path.
function trimCache(cacheName) {
  const max = CACHE_LIMITS[cacheName];
  if (!max) return;
  caches.open(cacheName).then(async (cache) => {
    const keys = await cache.keys();
    if (keys.length <= max) return;
    const excess = keys.length - max;
    for (let i = 0; i < excess; i++) await cache.delete(keys[i]);
  }).catch(() => {});
}

/* ───── push notifications (unchanged behavior) ───────────────── */

/* ───── THE BROWSER CAN REPLACE A SUBSCRIPTION ON ITS OWN ──────────
   And when it does, the endpoint the server has stops existing. Chrome
   rotates or revokes a push subscription for its own reasons — a push
   service re-registration, a browser update, a long gap between visits —
   and fires `pushsubscriptionchange` to say so. Without a handler here
   the new endpoint reached the server only on the next full page LOAD
   (push.js::healSubscription), so an app left open — a PWA, a pinned
   tab — kept a registration the server had never heard of and quietly
   received nothing. The panel then said "this device is not registered",
   correctly, with no way to explain when it had happened.

   The old endpoint is retired explicitly too, so the dead rows stop
   piling up the way they did on the phone (seven of them by 2026-08-23). */
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil((async () => {
    const old = event.oldSubscription || null;
    try {
      let sub = event.newSubscription || null;
      if (!sub) {
        // The browser did not hand us a replacement, so make one. No
        // prompt is possible or needed: permission is already granted,
        // or this event would not have fired.
        const res = await fetch("/api/push/vapid-public-key", { credentials: "same-origin" });
        const { key } = await res.json();
        sub = await self.registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: b64ToBytes(key),
        });
      }
      await fetch("/api/push/subscribe", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        // NESTED under `subscription` — the server reads data["subscription"].
        body: JSON.stringify({ subscription: sub.toJSON() }),
      });
    } catch (_) {
      // Offline, or the subscribe was refused. The next page load runs
      // healSubscription(), which repairs the same thing.
    }
    if (old && old.endpoint) {
      try {
        await fetch("/api/push/unsubscribe", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpoint: old.endpoint }),
        });
      } catch (_) { /* it is already undeliverable; the 410 will retire it */ }
    }
  })());
});

function b64ToBytes(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; ++i) out[i] = raw.charCodeAt(i);
  return out;
}


self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (_) {
    payload = { title: "DailyPlanner", body: event.data ? event.data.text() : "" };
  }

  // Defaults are ALERT behaviour, because a reminder that does not interrupt
  // has failed. But every one of them is overridable by the payload, because
  // an AMBIENT notification — the pinned day summary — needs the exact
  // opposite: it refreshes itself and must never buzz the phone to say the
  // same thing again. Hardcoding these meant there was only one kind of
  // notification this app could ever send.
  const pick = (key, fallback) =>
    Object.prototype.hasOwnProperty.call(payload, key) ? payload[key] : fallback;

  const title = payload.title || "DailyPlanner";
  const options = {
    body: payload.body || "",
    icon: payload.icon || "/static/icons/icon-192.png",
    badge: payload.badge || "/static/icons/icon-192.png",
    tag: payload.tag || "dailyplanner",
    // renotify only means anything alongside a tag: it decides whether
    // REPLACING an existing notification alerts again. False = update in place,
    // silently, which is what a status display wants.
    renotify: pick("renotify", true),
    // Keep on screen until the user taps/dismisses — otherwise Android
    // auto-hides after a few seconds.
    requireInteraction: pick("requireInteraction", true),
    // Explicit vibration pattern so phones on the default channel
    // importance still rumble.
    vibrate: pick("vibrate", [200, 100, 200]),
    // Force non-silent so OS playback of the channel's sound triggers.
    silent: pick("silent", false),
    data: { url: payload.url || "/checklist" },
  };
  if (Array.isArray(payload.actions) && payload.actions.length) {
    options.actions = payload.actions.slice(0, 2);   // Android shows at most 2
  }

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/checklist";

  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });

    // Prefer an existing window on the same origin. If its URL already
    // matches the notification target, just focus it; otherwise navigate
    // it to the target so we don't stack up duplicate tabs.
    const sameOrigin = all.filter((c) => {
      try { return new URL(c.url).origin === self.location.origin; }
      catch (_) { return false; }
    });

    if (sameOrigin.length) {
      const exact = sameOrigin.find((c) => c.url.includes(url));
      const target = exact || sameOrigin[0];
      if ("focus" in target) {
        try {
          if (!exact && "navigate" in target) await target.navigate(url);
        } catch (_) { /* cross-origin or unsupported — focus anyway */ }
        return target.focus();
      }
    }

    if (self.clients.openWindow) return self.clients.openWindow(url);
  })());
});
