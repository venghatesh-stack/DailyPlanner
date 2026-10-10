/* time-announcer.js — say the time out loud on the quarter hour.
 *
 * Asked for: "announce time every 15 mins (should be able to pause or
 * stop)".
 *
 * ALIGNED TO THE CLOCK, NOT TO WHEN YOU STARTED. "Every 15 minutes" for a
 * TIME announcement means :00, :15, :30, :45 — an announcement at 3:07 and
 * again at 3:22 would be technically every fifteen minutes and useless for
 * telling you where you are in the hour.
 *
 * IT NEVER ANNOUNCES A TIME THAT HAS PASSED. A laptop that slept through
 * 14:15 and woke at 14:41 must not then say "quarter past two" — that is
 * worse than silence, because you would believe it. Anything more than
 * GRACE_MS past a boundary is skipped, not queued.
 *
 * STATE SURVIVES NAVIGATION. This app is many separate pages, so the
 * setting lives in localStorage and every page picks it up. The caveat is
 * the browser's, not ours: speech synthesis needs a user gesture on each
 * new document, so after a navigation the first announcement may be
 * refused until you touch the page. The control says so rather than
 * pretending, and re-arms itself on the first interaction.
 *
 * DOES IT RUN WHEN THE WINDOW IS MINIMISED? Partly, and the honest answer
 * has three parts.
 *
 *   1. THROTTLING — survivable, and measured. A hidden tab has its timers
 *      clamped, in Chrome to once per MINUTE after about five minutes.
 *      Simulated against this logic: a 60s tick still catches all 96
 *      quarter-hours in a day, because GRACE_MS is 90s. At a 120s clamp it
 *      would start missing half, which is why the grace window is not
 *      tightened.
 *   2. FREEZING — fatal, and the reason KEEPALIVE exists below. Chrome may
 *      FREEZE an eligible background tab, at which point timers do not run
 *      at all. Tabs that are playing audio are exempt, so the opt-in
 *      keep-alive holds a near-silent Web Audio node open. It costs a
 *      little battery and makes the tab show an "playing audio" indicator,
 *      which is why it is opt-in rather than always on.
 *   3. A CLOSED PAGE, OR A BACKGROUNDED PHONE BROWSER — nothing works, and
 *      nothing here can make it. Script only runs while the document is
 *      alive, and mobile browsers suspend background pages almost at once.
 *      That is a limit of the platform, not a setting.
 *
 * Whatever happens, a missed announcement is SKIPPED rather than replayed,
 * so waking up never produces a burst of stale times.
 */
(function () {
  "use strict";
  if (window.TimeAnnouncer) return;

  //: The build this file came from. Shown in the Device tab so "is the
  //: phone even running the new code" stops being a guess — an installed
  //: PWA can serve a cached script for a long time, and every diagnosis
  //: after that is worthless if the answer is "no".
  //: Kept equal to CACHE_VERSION's leading token by a test.
  var BUILD = "v278";

  var KEY = "dp-time-announcer";
  var GRACE_MS = 90 * 1000;      // how late an announcement may still be true
  /* HOW LATE A NAMED ANNOUNCEMENT IS STILL WORTH SAYING.

     Reported: a 7:14pm daily reminder never fired, on a phone that was
     checking every 15 seconds when looked at afterwards. It was asleep at
     7:14. Android freezes a backgrounded page, and by the time it thawed
     the 90-second grace had passed, so the slot was discarded in silence.

     "Tell slokas" is worth hearing at 7:25. "It's 7:14 PM" is not, so this
     applies to the NAMED announcements only — the repeating clock keeps
     the 90-second rule, because a stale time is just wrong. */
  var LATE_MS = 30 * 60 * 1000;
  var TICK_MS = 15 * 1000;       // cheap: the work is one Date comparison
  var INTERVALS = [15, 30, 45, 60];   // 45 was simply missing before
  var MAX_EVERY = 720;                // 12h; beyond that use exact times
  var SILENT_MS = 1500;               // no onstart by now => it did not speak

  var state = load();
  var timer = null;
  var armed = false;             // has this document had a user gesture?
  var keepCtx = null;            // Web Audio node held open, see KEEPALIVE
  var voicesReady = false;
  var health = { at: null, ok: null, why: "", said: "" };   // see NOISY FAILURE

  function load() {
    // KEEP-ALIVE DEFAULTS ON.
    //
    // Asked for, and the reason it "sometimes gets cleared" is worth
    // recording: this flag is device-local by design, and a browser is
    // entitled to evict site data — Android under storage pressure, iOS
    // after a stretch of not opening the app. The ANNOUNCEMENTS survive
    // that now, because they moved to the server; the device flags do not.
    // So an eviction used to silently turn this off and leave everything
    // else looking correct. Defaulting it ON means an eviction restores
    // the useful state rather than the useless one.
    //
    // It only actually holds audio open while mode is "on" (see
    // applyKeepalive), so a device that is not announcing pays nothing
    // for this default.
    var d = { mode: "off", every: 15, at: [], label: "",
              items: [], said: {}, lastSlot: null,
              keepalive: true, keepaliveSet: false, chime: true };
    try {
      var raw = JSON.parse(localStorage.getItem(KEY));
      if (raw && typeof raw === "object") {
        if (raw.mode === "on" || raw.mode === "paused") d.mode = raw.mode;
        // ANY whole number of minutes, not just the presets. The old code
        // tested `INTERVALS.indexOf(raw.every)` and SILENTLY reset anything
        // else to 15 — so a custom value could never have stuck even if the
        // UI had offered one.
        var e = parseInt(raw.every, 10);
        if (e >= 0 && e <= MAX_EVERY) d.every = e;
        if (Array.isArray(raw.at)) d.at = raw.at.filter(isHHMM);
        if (typeof raw.label === "string") d.label = raw.label.slice(0, 60);
        if (typeof raw.lastSlot === "string") d.lastSlot = raw.lastSlot;
        if (raw.said && typeof raw.said === "object") d.said = raw.said;
        if (Array.isArray(raw.items)) {
          d.items = raw.items.filter(function (it) {
            return it && isHHMM(it.at);
          }).map(function (it) {
            var rep = REPEATS.indexOf(it.repeat) === -1 ? null : it.repeat;
            var start = isYMD(it.start) ? it.start : null;
            // MIGRATION from the date-only shape: a fixed date became a
            // one-off, and no date became a daily repeat.
            if (!rep) {
              rep = isYMD(it.date) ? "once" : "daily";
              start = isYMD(it.date) ? it.date : todayYMD();
            }
            return {
              id: String(it.id || ""),
              at: it.at,
              until: isHHMM(it.until) ? it.until : null,
              mins: parseInt(it.mins, 10) > 0
                ? Math.min(720, parseInt(it.mins, 10)) : 0,
              repeat: rep,
              days: Array.isArray(it.days)
                ? it.days.filter(function (d) { return d >= 0 && d <= 6; })
                : [],
              start: start || todayYMD(),
              end: isYMD(it.end) ? it.end : null,
              text: String(it.text || "").slice(0, 120),
              on: it.on !== false,
            };
          });
        }
        // Only honour a STORED value once the user has actually chosen
        // one. Without this flag, everybody who is currently off — which
        // is everybody, since it used to default off — would stay off and
        // the new default would reach nobody.
        if (raw.keepaliveSet && typeof raw.keepalive === "boolean") {
          d.keepalive = raw.keepalive;
          d.keepaliveSet = true;
        }
        if (typeof raw.chime === "boolean") d.chime = raw.chime;
      }
    } catch (_) {}

    // MIGRATION. The previous shape was one shared label plus a bare list of
    // times. Each of those becomes an announcement carrying that label, so
    // nobody loses a setting by upgrading.
    if (!d.items.length && d.at.length) {
      d.items = d.at.map(function (t, i) {
        return { id: "m" + i + t, at: t, until: null, mins: 0,
                 repeat: "daily", days: [], start: todayYMD(), end: null,
                 text: d.label, on: true };
      });
      d.at = [];
    }
    return d;
  }

  function isYMD(v) {
    return typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v);
  }

  function todayYMD(d) {
    d = d || new Date();
    var m = d.getMonth() + 1, day = d.getDate();
    return d.getFullYear() + "-" + (m < 10 ? "0" + m : m) + "-" +
           (day < 10 ? "0" + day : day);
  }

  function newId() {
    // No Math.random needed and no collision risk in practice: an id only has
    // to be unique within one person's list.
    idSeq += 1;
    return "i" + idSeq + "-" + (new Date()).getTime();
  }
  var idSeq = 0;

  /* ── RECURRENCE ─────────────────────────────────────────────────────
     Each announcement repeats on a rule, inside an optional window.

     `start` is the first day it may fire (defaults to the day it was
     created) and `end` is the last (null means forever). The rule then
     decides which days inside that window count.

     THE TWO AWKWARD CASES, both decided in favour of firing rather than
     silently skipping. A monthly reminder on the 31st CLAMPS to the last day
     of a short month, so February gets it on the 28th rather than not at
     all; a yearly one on 29 February clamps to the 28th in common years.
     Skipping would be defensible and it is not what a person setting a
     reminder wants. */
  var REPEATS = ["once", "daily", "weekly", "monthly", "yearly", "custom"];
  var DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  function ymdToParts(v) {
    var p = String(v).split("-");
    return { y: +p[0], m: +p[1], d: +p[2] };
  }

  function daysInMonth(y, m) {           // m is 1-based
    return new Date(y, m, 0).getDate();
  }

  function weekdayOf(ymd) {
    var p = ymdToParts(ymd);
    return new Date(p.y, p.m - 1, p.d).getDay();
  }

  function matchesOn(it, ymd) {
    var start = isYMD(it.start) ? it.start : null;
    if (start && ymd < start) return false;
    if (isYMD(it.end) && ymd > it.end) return false;

    var rep = REPEATS.indexOf(it.repeat) === -1 ? "daily" : it.repeat;
    if (rep === "daily") return true;
    if (rep === "once") return !!start && ymd === start;
    if (rep === "custom") {
      var days = Array.isArray(it.days) ? it.days : [];
      return days.indexOf(weekdayOf(ymd)) !== -1;
    }
    if (!start) return true;             // no anchor to repeat from
    var s = ymdToParts(start), t = ymdToParts(ymd);
    if (rep === "weekly") return weekdayOf(ymd) === weekdayOf(start);
    if (rep === "monthly") {
      var dm = Math.min(s.d, daysInMonth(t.y, t.m));   // clamp, see above
      return t.d === dm;
    }
    if (rep === "yearly") {
      var dy = Math.min(s.d, daysInMonth(t.y, s.m));
      return t.m === s.m && t.d === dy;
    }
    return false;
  }

  /* The rule in words, for the row and for the read-back. */
  function repeatWords(it) {
    var rep = REPEATS.indexOf(it.repeat) === -1 ? "daily" : it.repeat;
    var base;
    if (rep === "once") base = it.start || "once";
    else if (rep === "daily") base = "every day";
    else if (rep === "weekly") base = "every " +
      (it.start ? DAY_NAMES[weekdayOf(it.start)] : "week");
    else if (rep === "monthly") base = "monthly on the " +
      (it.start ? ordinal(ymdToParts(it.start).d) : "same day");
    else if (rep === "yearly") base = "yearly on " +
      (it.start ? shortDate(it.start) : "the same date");
    else base = (it.days || []).length
      ? (it.days.slice().sort().map(function (d) { return DAY_NAMES[d]; }).join(" "))
      : "no days chosen";
    if (rep !== "once" && isYMD(it.end)) base += ", until " + shortDate(it.end);
    return base;
  }

  /* "5:00 AM", or "8:00 AM–8:00 PM every 60m" when it repeats in a window. */
  function timeWords(it) {
    if (!(it.mins > 0) || !isHHMM(it.until)) return friendly(it.at);
    return friendly(it.at) + "\u2013" + friendly(it.until) +
           " \u00b7 " + it.mins + "m";
  }

  function ordinal(n) {
    var s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }

  function shortDate(ymd) {
    var p = ymdToParts(ymd);
    return p.d + " " + ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
                        "Aug", "Sep", "Oct", "Nov", "Dec"][p.m - 1] +
           " " + p.y;
  }

  /* Has this announcement finished for good? A `once` in the past, or any
     rule whose end date has gone. Shown as expired rather than kept looking
     armed. */
  function isExpired(it, today) {
    if (isYMD(it.end) && it.end < today) return true;
    if (it.repeat === "once" && isYMD(it.start) && it.start < today) return true;
    return false;
  }

  function isHHMM(v) {
    return typeof v === "string" && /^([01]?\d|2[0-3]):[0-5]\d$/.test(v);
  }

  /* "9, 9:30, 13:45 18:00" -> ["09:00","09:30","13:45","18:00"].
     Deliberately forgiving about separators and about a bare hour, because
     this is a text field someone types into once and should not have to
     get exactly right. Anything unparseable is dropped, and the caller
     shows what survived so nothing is silently ignored. */
  /* `defaultMer` is the AM/PM chosen with the buttons. It applies ONLY when
     the typed text does not settle the question itself:

       "5"      + PM  ->  17:00     (the chooser decides)
       "5pm"    + AM  ->  17:00     (what you typed wins)
       "17:00"  + AM  ->  17:00     (already unambiguous, chooser ignored)
       "0:30"   + PM  ->  00:30     (hour 0 is 24-hour by construction)

     Typing beats clicking, because someone who wrote "pm" meant it. */
  function parseTimes(text, defaultMer) {
    var out = [];
    // A FULL STOP IS A TIME SEPARATOR. "5.00" is how most of the world writes
    // five o'clock, and the previous version split on any non-digit — so it
    // read that as TWO times, 05:00 and 00:00, and quietly announced midnight
    // every night. Dots and dashes between the hour and minute are joined
    // back up before anything is split.
    var t = String(text || "")
      .toLowerCase()
      .replace(/(\d)\s*[.\-]\s*(\d)/g, "$1:$2");

    // Split on commas, semicolons, "and", or runs of spaces — but NOT on
    // letters, because am/pm has to survive to the next step.
    t.split(/\s*(?:,|;|\band\b|\s{2,})\s*|\s+(?=\d)/).forEach(function (tok) {
      tok = (tok || "").trim();
      if (!tok) return;
      var m = /^(\d{1,2})(?::(\d{1,2}))?\s*(am|pm|a\.m\.|p\.m\.)?$/.exec(tok);
      if (!m) return;
      var h = parseInt(m[1], 10), mi = parseInt(m[2] || "0", 10);
      var mer = (m[3] || "").replace(/\./g, "");
      if (mi > 59) return;
      // Only a bare 1-12 is ambiguous. 0 and 13-23 can only be 24-hour.
      if (!mer && (defaultMer === "am" || defaultMer === "pm") &&
          h >= 1 && h <= 12) {
        mer = defaultMer;
      }
      // 12-HOUR INPUT, because "5pm" is what people type. Without a meridiem
      // the number is taken as-is, so 17:00 still works and 5 means 05:00.
      if (mer === "pm" && h < 12) h += 12;
      else if (mer === "am" && h === 12) h = 0;
      if (h > 23) return;
      var v = (h < 10 ? "0" + h : h) + ":" + (mi < 10 ? "0" + mi : mi);
      if (out.indexOf(v) === -1) out.push(v);
    });
    return out.sort();
  }

  /* 24h -> "5:00 AM", so the echo is unambiguous about what was understood.
     "Is 5.00 five in the morning?" is only a question because nothing ever
     read the answer back. */
  function friendly(hhmm) {
    var p = hhmm.split(":");
    var h = parseInt(p[0], 10);
    var suffix = h < 12 ? "AM" : "PM";
    var h12 = h % 12 === 0 ? 12 : h % 12;
    return h12 + ":" + p[1] + " " + suffix;
  }

  /* The schedule in words. Used by the lock-screen metadata and the panel. */
  function scheduleWords() {
    var bits = [];
    if (state.every > 0) bits.push("every " + state.every + " min");
    var live = state.items.filter(function (it) {
      return it.on && !isExpired(it, todayYMD());
    });
    if (live.length) {
      bits.push(live.length + (live.length === 1 ? " announcement"
                                                 : " announcements"));
    }
    return bits.length ? bits.join(", plus ") : "nothing scheduled";
  }

  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) {}
  }

  function supported() {
    return typeof window.speechSynthesis !== "undefined" &&
           typeof window.SpeechSynthesisUtterance !== "undefined";
  }

  /* The boundary this moment belongs to, as a stable key. Shared through
     localStorage so two open tabs do not both announce — whichever gets
     there first writes the slot and the other sees it already done. */
  function slotFor(d, slotMins) {
    return d.toDateString() + "|" + slotMins;
  }

  /* WHICH BOUNDARY, IF ANY, THIS MOMENT BELONGS TO.
     Returns the boundary in minutes-since-midnight, or null.

     Two sources, either of which can fire: the repeating interval, and the
     list of exact times. An exact time WINS when both land together, so
     that "09:00" is announced once rather than twice.

     A 45-minute interval does not divide the hour, and that is fine — it
     steps from midnight (00:00, 00:45, 01:30, ...) rather than resetting
     each hour, which is the only definition of "every 45 minutes" that is
     actually every 45 minutes. */
  /* THE TIMES ONE ANNOUNCEMENT SPEAKS ON A DAY IT IS ACTIVE.
     Returns minutes-since-midnight, ascending.

     `at` is when it starts. `until` is when it stops, and `mins` is how often
     it repeats in between — so "drink water, every day, 08:00 to 20:00, every
     60 minutes" is one announcement rather than thirteen.

     Leave `until` and `mins` empty and it speaks ONCE at `at`, which is what
     every existing announcement does and why nothing had to be migrated. */
  function slotsFor(it) {
    var from = hhmmToMins(it.at);
    if (from === null) return [];
    var step = parseInt(it.mins, 10);
    var to = isHHMM(it.until) ? hhmmToMins(it.until) : null;
    if (!(step > 0) || to === null || to < from) return [from];

    var out = [];
    // A guard rather than a while(true): a step of 1 across a full day is
    // 1440 slots, and anything past that is a bug, not a schedule.
    for (var m = from; m <= to && out.length < 1441; m += step) out.push(m);
    return out;
  }

  function hhmmToMins(v) {
    if (!isHHMM(v)) return null;
    var p = v.split(":");
    return parseInt(p[0], 10) * 60 + parseInt(p[1], 10);
  }

  function minsToHHMM(m) {
    var h = Math.floor(m / 60), mm = m % 60;
    return (h < 10 ? "0" + h : h) + ":" + (mm < 10 ? "0" + mm : mm);
  }

  /* WHICH NAMED ANNOUNCEMENTS ARE DUE RIGHT NOW.
     Returns the items, not just a flag, because several can land on the same
     minute and all of them must be said.

     THE DATE RULE, as asked for: no date means EVERY day from now on; a date
     means that day only. A date in the past never fires again, and the panel
     shows it as expired rather than silently ignoring it. */
  function dueItems(now) {
    var mins = now.getHours() * 60 + now.getMinutes();
    var today = todayYMD(now);
    var out = [];
    for (var i = 0; i < state.items.length; i++) {
      var it = state.items[i];
      if (!it.on) continue;                       // stopped individually
      if (!matchesOn(it, today)) continue;        // not a day this rule fires

      // A windowed announcement has many slots in a day, and each settles on
      // its own — so the key carries the SLOT, not the item's start time.
      var slots = slotsFor(it);
      for (var k = 0; k < slots.length; k++) {
        var late = (mins - slots[k]) * 60000 + now.getSeconds() * 1000;
        // Catch-up is for a once-a-day reminder that the device slept
        // through. An item that repeats THROUGH the day does not need it:
        // the next slot is minutes away, and firing the previous one late
        // would announce 9:00 at 9:30 with 10:00 about to arrive.
        var limit = (it.mins > 0) ? GRACE_MS : LATE_MS;
        if (late < 0 || late > limit) continue;      // not yet, or long gone
        var key = today + "|" + minsToHHMM(slots[k]);
        if (state.said[it.id] === key) continue;     // already said this slot
        out.push({ item: it, slot: slots[k], key: key, lateBy: late,
                   id: it.id, text: it.text, at: it.at, on: it.on });
        break;                                       // one slot per tick
      }
    }
    return out;
  }

  function dueSlot(now) {
    var mins = now.getHours() * 60 + now.getMinutes();
    var lateBy = function (boundary) {
      return (mins - boundary) * 60000 + now.getSeconds() * 1000;
    };

    if (state.every > 0) {
      var boundary = Math.floor(mins / state.every) * state.every;
      if (lateBy(boundary) <= GRACE_MS) return boundary;
    }
    return null;
  }

  function phrase(d) {
    var h = d.getHours();
    var m = d.getMinutes();
    var suffix = h < 12 ? "A M" : "P M";
    var h12 = h % 12 === 0 ? 12 : h % 12;
    // "3 o'clock" reads better than "3:00", and the engines say the rest
    // correctly from digits.
    var body = m === 0 ? h12 + " o'clock" : h12 + ":" + (m < 10 ? "0" + m : m);
    var said = "It's " + body + " " + suffix;
    // THE SHARED HEADING still applies to the repeating interval. Named
    // announcements carry their own text and are prepended by check().
    if (state.label) said = state.label.replace(/[.!?]*$/, "") + ". " + said;
    return said;
  }

  /* ── NOISY FAILURE ──────────────────────────────────────────────────
     The old speak() returned true if speechSynthesis.speak() did not
     THROW. It almost never throws. It just does nothing, and there was no
     onerror handler, no watchdog and nothing on screen — so "the
     announcements are not working" had no evidence anywhere, which is
     precisely the report that arrived.

     Every attempt now lands in `health`, and the panel shows it. */
  function note(ok, why, said) {
    if (ok === null) { health = { at: null, ok: null, why: "", said: "" }; paint(); return; }
    health = { at: new Date(), ok: ok, why: why || "", said: said || "" };
    try {
      if (window.dpInert && !ok) window.dpInert("time announcer", why);
    } catch (_) {}
    paint();
  }

  /* Voices arrive ASYNCHRONOUSLY. On Android especially, getVoices() is
     empty for the first moments after load and speaking into that gap is
     dropped without a sound or an error. */
  function primeVoices() {
    if (!supported()) return;
    try {
      voicesReady = (window.speechSynthesis.getVoices() || []).length > 0;
      if (voicesReady) return;
      window.speechSynthesis.addEventListener("voiceschanged", function () {
        voicesReady = (window.speechSynthesis.getVoices() || []).length > 0;
      });
    } catch (_) {}
  }

  /* ── THE CHIME ──────────────────────────────────────────────────────
     Speech does not work on a locked phone — browsers suspend the Web
     Speech API when the screen is off, and no setting changes that.
     MEDIA PLAYBACK is the one thing that IS permitted there, which is the
     same fact the keep-alive relies on.

     So an announcement also plays a short real audio file. That is the
     only sound this app can make with the screen off, and it is why
     "I hear nothing" was true even once the notification arrived: a push
     notification's sound is the operating system's to choose, and a web
     app cannot supply one.

     When you are at the desk you get the chime AND the spoken sentence,
     which is the right pairing: the chime takes your attention and the
     speech carries the content. */
  /* ── ONE ELEMENT FOR BOTH SOUNDS ────────────────────────────────────
     Reported from a locked Android: "chime played, speech: audio blocked".

     Both are <audio> elements, so why does one play and the other not?
     Because Android unlocks an audio element the first time it is played
     DURING A USER GESTURE — and it unlocks that ELEMENT, not the page.
     The chime element gets played when you tick its checkbox or press
     Test, so it is unlocked from then on. The speech element was created
     fresh, had never been played during a gesture, and was refused every
     time — on a locked screen, where no gesture is ever coming.

     So there is now ONE element. The chime unlocks it, and the words ride
     on that same unlocked element immediately afterwards.

     In SEQUENCE rather than together, which is better anyway: the chime
     takes your attention and the words arrive once it has. */
  var soundEl = null;
  var sayCache = {}, sayPending = {};

  //: Held so the utterance is not garbage-collected mid-sentence, which is
  //: a real Chrome bug.
  var speaking = null;
  //: Set after a failure, so the retry asks for no particular voice.
  var noVoice = false;

  function sound() {
    if (soundEl) return soundEl;
    soundEl = document.getElementById("ta-sound");
    if (!soundEl) {
      soundEl = document.createElement("audio");
      soundEl.id = "ta-sound";
      soundEl.preload = "auto";
      soundEl.setAttribute("playsinline", "");
      document.body.appendChild(soundEl);
    }
    return soundEl;
  }

  /* ── A SECOND ELEMENT, FOR THE WORDS ────────────────────────────────
     Measured on a locked Android, 2026-08-23:

       chime: played, speech: audio blocked, rendered audio: cached

     So the audio was there and the element was allowed to play — the
     CHIME went out through it. What failed was the second play(): the
     chime ends, its handler assigns a new src to the same element and
     calls play() again, and that call is refused mid-load.

     One element was itself a fix for an earlier bug — Android unlocks a
     media element on the gesture that first plays IT, so a speech element
     nobody ever tapped was refused forever. The answer is not one element,
     it is two elements that are BOTH unlocked by the same gesture. Then
     neither ever has to swap a source out from under a playing stream. */
  var speechEl = null;

  function speechSound() {
    if (speechEl) return speechEl;
    speechEl = document.getElementById("ta-speech");
    if (!speechEl) {
      speechEl = document.createElement("audio");
      speechEl.id = "ta-speech";
      speechEl.preload = "auto";
      speechEl.setAttribute("playsinline", "");
      document.body.appendChild(speechEl);
    }
    return speechEl;
  }

  /* Unlock BOTH elements on a real gesture.

     SILENCED WITH volume, NOT WITH muted, and the difference is the whole
     point. Muted playback is permitted by the autoplay policy anyway, so a
     muted play grants nothing — the permission it would have bought is the
     one it never needed. A volume-0 play is real unmuted playback, which is
     what actually flips the bit.

     (The keep-alive track has the same rule for a related reason: a muted
     track does not hold the audio session on a locked phone.)

     Paused again immediately, so this is inaudible either way. What it buys
     is that from here on EITHER element may start without a gesture, which
     is the whole requirement for speaking from a pocket. */
  function unlockAudio() {
    [sound(), speechSound()].forEach(function (el) {
      try {
        if (el.dataset.unlocked === "1") return;
        var was = el.src;
        el.volume = 0;
        if (!el.src) el.src = "/static/audio-keepalive.wav";
        var p = el.play();
        var settle = function () {
          try {
            el.pause();
            el.volume = 1;
            el.dataset.unlocked = "1";
            // The unlock plays two OTHER elements, which can take audio
            // focus from the keep-alive that applyKeepalive() just started
            // on this very gesture.
            nudgeKeepalive();
            // Put back whatever was queued; the unlock must not throw away
            // a rendered announcement already loaded into the element.
            if (was && el.src !== was) el.src = was;
          } catch (e) {}
        };
        if (p && p.then) p.then(settle).catch(function () { el.volume = 1; });
        else settle();
      } catch (e) {}
    });
  }

  /* Play one source on the shared element. onDone fires when it finishes,
     onFail when the browser refuses to start it — play() is asynchronous,
     so starting is not the same as being heard. */
  function playThrough(src, onDone, onFail, el) {
    el = el || sound();
    try {
      el.onended = null;
      el.src = src;
      el.volume = 1;
      var p = el.play();
      el.onended = function () { el.onended = null; if (onDone) onDone(); };
      if (p && p.then) {
        p.catch(function (err) {
          el.onended = null;
          if (onFail) onFail(err);
        });
      }
      return true;
    } catch (e) {
      if (onFail) onFail(e);
      return false;
    }
  }

  function playChime(onDone) {
    if (!state.chime) { if (onDone) onDone(); return; }

    /* ── THE WORDS MUST NOT DEPEND ON AN EVENT THAT MAY NOT ARRIVE ────
       The announcement is chained to the chime's `ended`, and if that
       event never fires the words never start — which is exactly the
       shape of "in android only get the chime sound, not the text when
       the phone is locked". `ended` is genuinely unreliable here: a
       stalled element, an interrupted stream, or the OS pausing playback
       part-way all leave it pending forever.

       The chime is 1.34 seconds. If nothing has happened after four, stop
       waiting and say the words. Guarded so the two paths cannot both
       run — hearing the announcement twice is its own bug. */
    var went = false;
    var go = function () {
      if (went) return;
      went = true;
      if (onDone) onDone();
    };
    setTimeout(go, 4000);

    playThrough("/static/audio-chime.wav", function () {
      if (lastFire) { lastFire.chime = "played"; paint(); }
      nudgeKeepalive();
      go();
    }, function (err) {
      if (lastFire) { lastFire.chime = "blocked"; paint(); }
      nudgeKeepalive();
      note(false, "the chime was blocked (" +
                  ((err && err.name) || "autoplay policy") + ")");
      go();
    });
  }

  /* ── SPOKEN AUDIO, FOR WHEN THE BROWSER WILL NOT SPEAK ──────────────
     Android Chrome refuses speechSynthesis while the page is hidden.
     Media playback is allowed there, so the words are fetched as audio
     and played through the element above.

     PREFETCHED, so the sound does not wait on a network round trip at the
     moment it is due, and a phone that dropped offline still speaks. */
  function sayUrl(text) {
    return "/api/announcer/say?text=" + encodeURIComponent(text);
  }

  //: Why the last render failed, if it did. Swallowing this is how the
  //: words could be unavailable for hours with nothing anywhere saying so.
  var sayState = "none";

  function fetchSpeech(text) {
    return fetch(sayUrl(text), { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) {
          sayState = "server said " + r.status;
          throw new Error(sayState);
        }
        /* AND IT HAS TO BE AUDIO. The endpoint is behind @login_required,
           which redirects an unauthenticated request to the login PAGE;
           fetch() follows that, so a failed session arrives here as a
           cheerful 200 of text/html. Treating it as ready is how the
           announcement came to be "cached" and unplayable. */
        var type = (r.headers && r.headers.get("content-type")) || "";
        if (!/^audio\//i.test(type)) {
          sayState = "not signed in (server sent " + (type || "no type") + ")";
          throw new Error(sayState);
        }
        return r.blob();
      })
      .then(function (b) {
        /* ── A data: URL, NOT A blob: URL ────────────────────────────
           Measured on a locked Android, 2026-08-23:

             "(page hidden) Chime: Played. Speech audio refused
              (not supported error), rendered audio: cached"

           NotSupportedError means the element could not decode its
           source — and the source was a blob: URL that this page had
           created before Android froze it. A frozen or discarded page
           has its object URLs released, while the JavaScript string
           naming them survives in the cache. So the announcement looked
           cached, right up until the moment it was needed, and then
           pointed at nothing.

           A data: URL cannot be invalidated: it IS the audio. About a
           third larger as base64, which for a handful of short phrases
           is nothing next to being silent. */
        return new Promise(function (resolve) {
          try {
            var fr = new FileReader();
            fr.onload = function () { resolve(String(fr.result)); };
            fr.onerror = function () { resolve(URL.createObjectURL(b)); };
            fr.readAsDataURL(b);
          } catch (e) {
            resolve(URL.createObjectURL(b));
          }
        }).then(function (url) {
          // Kept as the warmed-and-decodable marker: what the element is
          // actually given is the HTTP URL above. Holding the bytes still
          // proves the render succeeded and the response was audio.
          sayCache[text] = url;
          sayState = "ready";
          if (text === nextWords) preloadSpeech(text);
          paint();
          return url;
        });
      });
  }

  function prefetchSpeech(text) {
    if (!text || sayCache[text] || sayPending[text]) return;
    sayPending[text] = true;
    fetchSpeech(text)
      .catch(function (e) {
        if (sayState === "none") sayState = "unreachable";
        paint();
      })
      .then(function () { delete sayPending[text]; });
  }

  /* Returns false when there is nothing cached to play. Whether it was
     HEARD is reported through onFail.

     ── IT PLAYS THE PLAIN HTTP URL, NOT THE CACHED BYTES ──────────────
     Measured on a locked Android, 2026-08-24: the words were refused with
     NotSupportedError from a blob: URL, then from a data: URL, and then —
     decisively — from the SAME element that had played the chime one
     second earlier. Same element, same instant, same locked screen: one
     source worked and the other did not. The difference was never the
     element or the autoplay permission. It was the URL scheme.

     Android Chrome will not decode a blob:/data: source on a media
     element. The chime works because it is an ordinary HTTP URL, so the
     words use one too. The fetch is still worth doing — it warms the HTTP
     and service-worker caches, so the source is local by the time it is
     needed, which was the whole point of prefetching. What changes is
     only what gets handed to the element. */
  function playSpeech(text, onFail) {
    if (!sayCache[text]) return false;      // not warmed yet
    var url = sayUrl(text);
    return playThrough(url, function () {
      if (lastFire) { lastFire.spoke = "played (audio)"; paint(); }
      nudgeKeepalive();
    }, function (err) {
      nudgeKeepalive();
      // NAME THE ERROR. "audio blocked" covered two completely different
      // faults — NotAllowedError is the autoplay policy, AbortError is a
      // play() cut short by a new load — and they have opposite fixes.
      // Guessing between them cost a day.
      if (lastFire && !lastFire.spoke) {
        lastFire.spoke = "audio refused (" +
                         ((err && err.name) || "unknown") + ")";
        paint();
      }
      if (onFail) onFail();
    }, speechSound());
  }

  /* Load the next announcement's audio into the element BEFORE it is due.

     A play() issued against a src assigned microseconds earlier can be
     rejected while the new source is still loading — which looks exactly
     like an autoplay block and is not one. Loading it in advance means the
     only thing left to do at fire time is press play. */
  function preloadSpeech(text) {
    if (!text || !sayCache[text]) return;
    try {
      var el = speechSound();
      if (el.dataset.queued === text) return;
      el.dataset.queued = text;
      el.src = sayUrl(text);
      el.load();
    } catch (e) {}
  }

  /* ── IF IT CANNOT BE SAID, IT MUST STILL BE DELIVERED ───────────────
     Every path above can fail on a locked phone, and the failure is
     silence — which is indistinguishable from the announcement never
     having been scheduled. The page can raise its own notification
     through the service worker, and a notification is the one thing that
     definitely reaches a locked Android: it buzzes, it stays on screen,
     and it does not care whether audio was permitted.

     The server sends one too, but only if that device has a live push
     subscription, and that is exactly what had been broken for months.
     This one needs nothing but the page being alive at the time — which,
     with the keep-alive holding, is the case being rescued. */
  function notifyInstead(words) {
    try {
      if (typeof Notification === "undefined" ||
          Notification.permission !== "granted") return;
      if (!navigator.serviceWorker || !navigator.serviceWorker.ready) return;
      navigator.serviceWorker.ready.then(function (reg) {
        reg.showNotification("\uD83D\uDD14 " + friendly(hhmmNow()), {
          body: words,
          tag: "ta-said-" + hhmmNow(),
          requireInteraction: true,
          vibrate: [200, 100, 200],
          silent: false,
          icon: "/static/icons/icon-192.png",
          badge: "/static/icons/icon-192.png",
          data: { url: "/day-board" },
        });
        if (lastFire) { lastFire.notified = true; paint(); }
      }).catch(function () {});
    } catch (e) {}
  }

  function hhmmNow() {
    var d = new Date();
    return ("0" + d.getHours()).slice(-2) + ":" +
           ("0" + d.getMinutes()).slice(-2);
  }

  function speak(text, isRetry) {
    if (!supported()) {
      note(false, "this browser has no speech synthesis");
      notifyInstead(text);
      return false;
    }
    var synth = window.speechSynthesis;

    function fire() {
      try {
        var u = new SpeechSynthesisUtterance(text);
        u.rate = 0.95;
        u.volume = 1;
        u.lang = (document.documentElement.lang || navigator.language ||
                  "en-US");

        // ── VOICE SELECTION, AND WHY IT IS SO CAUTIOUS ────────────────
        // This is where announcements stopped working on a locked phone.
        //
        // The original code set NO voice, so the platform used its own
        // default — on Android a LOCAL, offline-capable engine. Then I
        // added "pick the first voice matching the language", which on
        // Android is frequently a NETWORK voice. A network voice needs a
        // live request at the moment of speaking, and a backgrounded page
        // on a locked screen does not get one. It worked at the desk and
        // silently stopped in a pocket, which is the worst shape a
        // regression can have.
        //
        // So: prefer a LOCAL voice, and if there is no local voice, set
        // NONE and let the platform choose — which is exactly the
        // behaviour that used to work.
        try {
          var vs = synth.getVoices() || [];
          var want = u.lang.slice(0, 2).toLowerCase();
          var local = vs.filter(function (x) { return x.localService; });
          var v = local.filter(function (x) {
            return (x.lang || "").slice(0, 2).toLowerCase() === want;
          })[0] || local.filter(function (x) { return x.default; })[0];
          if (v && !noVoice) u.voice = v;
        } catch (_) {}

        var started = false, errored = false;
        u.onstart = function () {
          started = true;
          noVoice = false;              // whatever we chose, it worked
          if (lastFire) { lastFire.spoke = "spoke"; paint(); }
          nudgeKeepalive();
          note(true, "", text);
        };
        u.onend = function () { speaking = null; };
        u.onerror = function (ev) {
          errored = true;
          speaking = null;
          if (lastFire && !lastFire.spoke) {
            lastFire.spoke = "refused: " + ((ev && ev.error) || "error");
            nudgeKeepalive();
            // Nothing was heard. Buzz instead of failing silently.
            notifyInstead(text);
            paint();
          }
          note(false, (ev && ev.error) || "the browser refused to speak");
          // RETRY WITHOUT A VOICE. The commonest cause of a refusal is a
          // voice that cannot be reached right now — a network voice on a
          // locked phone. The platform default nearly always can be.
          if (!isRetry && !noVoice) {
            noVoice = true;
            setTimeout(function () { speak(text, true); }, 200);
          }
        };
        speaking = u;
        synth.speak(u);

        // CHROME LEAVES THE QUEUE PAUSED after some page lifecycle events,
        // and a paused queue accepts utterances forever without saying one.
        try { if (synth.paused) synth.resume(); } catch (_) {}

        // WATCHDOG. If onstart has not fired, nothing was said — and with
        // no error either, this is the silent case that had no evidence.
        setTimeout(function () {
          if (!started && !errored) {
            if (lastFire && !lastFire.spoke) {
              lastFire.spoke = "accepted but silent";
              notifyInstead(text);
              paint();
            }
            note(false, armed
              ? "the browser accepted it but said nothing"
              : "blocked until you tap the page once");
            // Accepted and silent is the other symptom of an unreachable
            // voice, so it gets the same one retry.
            if (!isRetry && !noVoice) {
              noVoice = true;
              speak(text, true);
            }
          }
        }, SILENT_MS);
        return true;
      } catch (e) {
        note(false, "speak() threw: " + (e && e.message));
        return false;
      }
    }

    // CANCEL-THEN-SPEAK IN THE SAME TASK IS A CHROME BUG: the new utterance
    // is swallowed. The old code did exactly that on every announcement, on
    // desktop and Android alike. Only cancel when something is actually in
    // flight, and let the cancel settle first.
    if (synth.speaking || synth.pending) {
      try { synth.cancel(); } catch (_) {}
      setTimeout(fire, 150);
      return true;
    }
    return fire();
  }

  //: Prefetching runs from the tick, so the audio for the NEXT slot is
  //: already downloaded before that slot arrives.
  /* THE SPOKEN STRING FOR A MOMENT, BUILT IN EXACTLY ONE PLACE.

     This used to be built twice — once by the prefetch and once by
     check() — and the two disagreed. The prefetch cached the words for
     90 seconds AHEAD while the fire looked up the words for NOW, so on
     any minute the two differed the cache missed and the announcement
     fell through to speechSynthesis. That is invisible while the app is
     on screen (an earlier tick had already cached the right minute) and
     fatal the moment Android freezes a hidden page, because then the
     only tick that runs is the one at fire time. */
  function wordsFor(when, items) {
    var parts = (items || []).map(function (it) {
      return (it.text || "").replace(/[.!?]*$/, "") || "Reminder";
    });
    parts.push(phrase(when));
    return parts.join(". ");
  }

  /* FETCH THE WORDS WHILE THE PAGE IS STILL ALLOWED TO.

     A hidden Android page gets its timers frozen and its network starved,
     so the fetch at fire time is the one least likely to succeed. This
     walks the upcoming fire minutes and renders them AHEAD of time — the
     work happens while the app is on screen, and the frozen page that
     wakes up to announce finds the audio already in memory. */
  //: The words of the SOONEST upcoming announcement. Only this one can be
  //: sitting in the element, so it is tracked rather than guessed.
  var nextWords = null;

  function prefetchWindow(now, minutes) {
    if (state.mode !== "on") return;
    nextWords = null;
    var base = new Date(now.getTime());
    base.setSeconds(0, 0);
    var budget = 12;                      // ~12 small MP3s, not a whole day
    for (var i = 0; i <= minutes && budget > 0; i++) {
      var t = new Date(base.getTime() + i * 60000);
      var mins = t.getHours() * 60 + t.getMinutes();
      // Only the EXACT fire minute — dueSlot/dueItems also accept a late
      // arrival inside the grace window, and rendering those would spend
      // the budget on phrases that are never asked for.
      var boundary = dueSlot(t);
      var due = dueItems(t).filter(function (d) { return d.slot === mins; });
      if (!due.length && boundary !== mins) continue;
      var words = wordsFor(t, due);
      if (nextWords === null) {
        nextWords = words;
        preloadSpeech(words);     // no-op until the blob exists
      }
      prefetchSpeech(words);
      budget--;
    }
  }

  function prefetchNext(now) {
    prefetchWindow(now, 30);
  }

  function check(now) {
    lastTick = Date.now();
    if (state.mode !== "on") return;
    try { prefetchNext(now || new Date()); } catch (e) {}
    now = now || new Date();
    var today = todayYMD(now);

    // Re-read from storage so a sibling tab that already announced wins.
    var fresh = load();

    // ── the named announcements ──────────────────────────────────────
    var items = dueItems(now).filter(function (d) {
      return fresh.said[d.id] !== d.key;
    });

    // ── the repeating interval ───────────────────────────────────────
    var boundary = dueSlot(now);
    var intervalDue = boundary !== null &&
                      fresh.lastSlot !== slotFor(now, boundary);

    if (!items.length && !intervalDue) return;

    // ONE UTTERANCE, not several. Two announcements landing on the same
    // minute must not talk over each other, and queueing them would let a
    // backlog build up — which is the failure people remember.
    /* BUILT FROM THE SLOT, NOT FROM NOW.

       The grace window is 90 seconds, so a fire may legitimately happen in
       the minute AFTER the one it belongs to — the page was busy, or the
       tick landed late. phrase() is minute-precise, so building the words
       from `now` then produced "It's 7:15 PM" for the 7:14 slot, which is
       not the string the prefetch cached under. The audio missed, and the
       announcement fell through to speechSynthesis, which a hidden Android
       refuses. Intermittent, and only on the fires that ran late.

       Taking the time from the slot also makes a LATE announcement say
       what it was always going to say, rather than a time that has since
       moved on. */
    var slotMins = intervalDue ? boundary
                 : (items.length ? items[0].slot : null);
    var slotAt = new Date(now.getTime());
    if (slotMins !== null) {
      slotAt.setHours(Math.floor(slotMins / 60), slotMins % 60, 0, 0);
    }
    var words = wordsFor(slotAt, items);
    //: One re-render per fire. Without this a source that never decodes
    //: would loop fetching and failing until the slot passed.
    var retried = false;
    //: And one attempt on the chime's element, for the same reason.
    var triedChimeEl = false;

    /* ── A LATE ANNOUNCEMENT MUST SAY THAT IT IS LATE ─────────────────
       Reported as "strange. In android, when i open the app, then a
       announcement which was past the time gets fired and i hear the
       sound." It is deliberate — a reminder the phone slept through is
       worth hearing — but it was reading out the time of the SLOT, so at
       8:10 it announced "It's 7:45 PM", which is simply untrue and is
       most of why it felt wrong.

       Said plainly instead. This deliberately does not reuse the cached
       audio: a late fire happens the moment the app is opened, when the
       page is awake, on screen and able to speak or fetch — the one
       situation where the cache was never the thing keeping it working. */
    var lateBy = 0;
    items.forEach(function (d) {
      if ((d.lateBy || 0) > lateBy) lateBy = d.lateBy || 0;
    });
    if (items.length && lateBy > GRACE_MS) {
      words = items.map(function (it) {
        return (it.text || "").replace(/[.!?]*$/, "") || "Reminder";
      }).join(". ") + ". This was due at " + friendly(minsToHHMM(items[0].slot)) + ".";
    }

    items.forEach(function (d) {
      state.said[d.id] = d.key;
    });
    if (intervalDue) state.lastSlot = slotFor(now, boundary);

    // Keep `said` from growing forever: yesterday's marks cannot matter.
    Object.keys(state.said).forEach(function (k) {
      if (String(state.said[k]).slice(0, 10) !== today) delete state.said[k];
    });

    save();

    // ── WHAT ACTUALLY HAPPENED, RECORDED PER FIRE ────────────────────
    // Android speaks only while the app is visible; iPhone speaks while
    // locked. Two causes produce that and they need opposite fixes:
    //
    //   (a) the PAGE is frozen when hidden — then nothing runs, and even
    //       the chime is silent. The fix is the keep-alive.
    //   (b) the page runs but SPEECH is gated on visibility — then the
    //       chime plays and only the words are missing. The fix is
    //       pre-rendered audio, because no amount of work on the browser
    //       API will make it speak.
    //
    // The difference is invisible from the outside and decisive, so it is
    // recorded rather than guessed at.
    lastFire = {
      at: new Date(),
      hidden: (typeof document.visibilityState === "string")
        ? document.visibilityState !== "visible" : null,
      chime: null,
      spoke: null,
      //: What the RENDERED-audio attempt did. speak() overwrites .spoke
      //: with its own outcome, so without this the log said only
      //: "refused: synthesis-failed" and hid the reason the audio path —
      //: the only one that works on a locked Android — was skipped.
      audio: null,
      //: THE TWO FACTS I KEPT HAVING TO GUESS AT.
      //: Whether the keep-alive was actually holding at the moment this
      //: fired separates "the page was asleep" from "the page was awake
      //: and something refused it"; whether the speech element had ever
      //: been unlocked decides whether the rendered-audio path could have
      //: played at all. Both were invisible, and every wrong diagnosis in
      //: this saga came from assuming one of them.
      keep: !!keepCtx,
      unlocked: (function () {
        try { return speechSound().dataset.unlocked === "1"; }
        catch (e) { return null; }
      })(),
    };
    var spokeYet = false;
    var sayIt = function () {
      if (spokeYet) return;
      spokeYet = true;
      speak(words);
    };
    // The chime plays FIRST and the words follow when it ENDS, on the same
    // element — which is what makes them audible at all on a locked
    // Android. If the rendered audio is missing or refused, fall back to
    // the speech API, which still works on iOS in that state.
    playChime(function () {
      /* ── VISIBILITY IS NOT A RELIABLE TEST, AND THIS IS THE BUG ──────
         Measured on a locked Android, 2026-08-23:

           "Last fired 21.00 while visible. Chime: played,
            speech: refused, synthesis failed" — phone locked throughout.

         A locked screen does NOT make the page hidden. Chrome keeps
         visibilityState at "visible" when the display merely switches off,
         so this branch chose speechSynthesis — which a locked Android
         refuses — while the rendered audio that WOULD have played sat in
         the cache untouched. That is also why an earlier reading said
         "rendered audio: cached" next to a speech failure: it was there
         and never reached.

         So the rendered audio goes FIRST, always. It works in both states,
         needs no network, and its refusal path still falls through to
         speechSynthesis for anything it cannot cover. Guessing which state
         the device is in was never necessary — trying the thing that works
         everywhere is. `hidden` is still recorded, because it turned out
         to be the diagnosis, but it no longer decides anything. */
      /* A CACHED ENTRY THAT WILL NOT PLAY IS WORSE THAN NO CACHE, because
         it stops us fetching one that would. So a refusal re-renders the
         audio once and tries again, and only then gives up to the speech
         API — which, on the locked phone this whole path exists for, is
         refused anyway. */
      var recover = function () {
        /* ── FALL BACK TO THE ELEMENT THAT JUST WORKED ─────────────────
           The chime had played a second earlier through the OTHER audio
           element, on the same locked phone, in the same instant. That is
           not a theory about what Android permits — it is a demonstration.
           So before re-rendering anything, try the words on the element
           that has just proved itself.

           Two elements exist because swapping a source out from under a
           playing stream failed; that is only a problem while the chime is
           still going, and by here it has finished. */
        if (!triedChimeEl && sayCache[words]) {
          triedChimeEl = true;
          lastFire.audio = "retrying on the chime's element";
          paint();
          if (playThrough(sayUrl(words), function () {
                lastFire.spoke = "played (audio, chime element)";
                nudgeKeepalive();
                paint();
              }, recover, sound())) return;
        }
        if (retried) { sayIt(); return; }
        retried = true;
        delete sayCache[words];
        lastFire.audio = "cached copy would not play, re-fetching";
        paint();
        fetchSpeech(words)
          .then(function () { if (!playSpeech(words, recover)) sayIt(); })
          .catch(function () { sayIt(); });
      };
      if (playSpeech(words, recover)) { lastFire.audio = "cached"; return; }
      lastFire.audio = "not cached, fetching";

      // NOT CACHED. Fetch it NOW rather than giving up. A second late and
      // heard beats on time and silent — and on a hidden Android page
      // speechSynthesis is refused, so the fallback below is nothing at
      // all. This is the path that runs when the prefetch missed, which
      // it does whenever the announcement was created less than a tick
      // ago or the network was down at the time.
      fetchSpeech(words)
        .then(function () {
          if (!playSpeech(words, sayIt)) {
            lastFire.audio = "fetched, nothing to play";
            sayIt();
          }
        })
        .catch(function () {
          lastFire.audio = "fetch failed (" + sayState + ")";
          paint();
          sayIt();
        });
    });
    paint();
  }

  //: When check() last ran. A page the OS has frozen stops ticking, and
  //: nothing else in this panel can tell you that — the settings still
  //: look right, the schedule is still there, and the clock simply is not
  //: being read. "Last checked 14 minutes ago" is the whole diagnosis.
  var lastTick = 0;
  //: The last announcement attempt and what each half of it did. This is
  //: the evidence that separates "the page was asleep" from "the page was
  //: awake and the browser refused to speak".
  var lastFire = null;

  function start() {
    // Cheap: unlockAudio() returns immediately once it has succeeded, and
    // before that every extra attempt is another chance to succeed.
    try { unlockAudio(); } catch (e) {}
    stopTimer();
    timer = setInterval(function () { check(); }, TICK_MS);
    check();
  }

  function stopTimer() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  /* ── KEEPALIVE ──────────────────────────────────────────────────────
     Two different problems, one mechanism.

     ON A DESKTOP the risk is FREEZING: Chrome may freeze an eligible
     background window, and a frozen page runs no timers at all — the
     difference between "announcements are late" and "announcements stop".

     ON A LOCKED PHONE the page is suspended outright and nothing in an
     ordinary web page survives it. The one exception is MEDIA: a page with
     an active media session keeps running with the screen off, which is
     exactly how a music PWA keeps playing in your pocket. So the keep-alive
     is a real <audio> element on loop, registered with the Media Session
     API — NOT a Web Audio oscillator, which the OS does not treat as
     playback, and which is what the first version of this used.

     The track is one second of 8 kHz PCM at an amplitude of ONE least
     significant bit: genuinely audio, inaudible in practice. Not digital
     silence, on purpose — silence is what a platform may optimise away, and
     an optimised-away stream stops counting as playback, quietly undoing
     the whole point.

     THE LOCK SCREEN WILL SHOW A MEDIA NOTIFICATION for it, and that is a
     feature rather than a leak. It is honest about what is running, and its
     pause button really does stop the announcements — a control that looks
     like it stops something must stop it.

     BEST-EFFORT, AND SAID SO. Whether a locked Android keeps the page
     scheduled well enough to speak is a device-and-version question that
     cannot be settled from here. iOS is stricter and is not expected to
     work at all. */
  /* Running as an INSTALLED PWA rather than a tab. It changes nothing about
     what the platform allows — an installed app is still a document, and a
     minimised window is still hidden — but it does change the ADVICE: someone
     who installed the app is far more likely to leave it minimised or pocket
     the phone and expect it to keep working, which is exactly the case the
     keep-alive exists for. So the recommendation is surfaced, not buried. */
  function isInstalled() {
    try {
      return (window.matchMedia &&
              (window.matchMedia("(display-mode: standalone)").matches ||
               window.matchMedia("(display-mode: window-controls-overlay)").matches ||
               window.matchMedia("(display-mode: minimal-ui)").matches)) ||
             window.navigator.standalone === true;
    } catch (_) {
      return false;
    }
  }

  /* ── HOLDING THE PAGE ALIVE ─────────────────────────────────────────
     This is what decides whether you hear a VOICE with the screen off.
     A page playing audio is not frozen by the OS; a page that is not,
     is — and a frozen page runs no timers and speaks nothing.

     THE BUG THIS REPLACES: keepCtx was set whether or not play()
     succeeded, and keepaliveOn() returns early when keepCtx is set. So on
     a fresh page load — where autoplay is ALWAYS blocked until the user
     touches something — the first attempt failed, the flag said "held",
     and it never tried again. The checkbox was ticked, the panel said it
     was on, and the page had no audio focus whatsoever.

     Now the flag is only set when the element reports PLAYING, the first
     user gesture retries, and a watchdog restarts it if the OS or another
     app pauses it later. */
  var keepWant = false;

  function keepEl() {
    var el = document.getElementById("ta-keepalive");
    if (!el) {
      el = document.createElement("audio");
      el.id = "ta-keepalive";
      el.src = "/static/audio-keepalive.wav";
      el.loop = true;
      el.preload = "auto";
      // NOT muted: a muted element does not hold audio focus, and without
      // audio focus the OS will not keep the page alive for it.
      el.volume = 0.02;
      el.setAttribute("playsinline", "");
      // The flag follows REALITY, not intent.
      el.addEventListener("playing", function () {
        keepCtx = { el: el };
        /* THIS ELEMENT PLAYING IS PROOF THAT AUDIO IS PERMITTED, so the
           announcement's elements can be unlocked now.

           Measured on a locked Android at v265: "keep-alive: holding,
           speech audio: NEVER UNLOCKED". unlockAudio() was wired to the
           first pointerdown only, and the app had been opened and locked
           without the screen being touched — while the keep-alive started
           anyway, because Chrome permits autoplay on a site it considers
           engaged. So the page was wide awake, holding audio focus, with
           the one element the words needed still locked. */
        try { unlockAudio(); } catch (e) {}
        setMediaSession();
        // Clear the "blocked until you tap the page" warning: it is true
        // on every fresh load and stops being true the moment this fires,
        // and a warning left standing after it is fixed is read as the
        // feature still being broken.
        note(null, "");
        paint();
      });
      el.addEventListener("pause", function () {
        keepCtx = null;
        paint();
      });
      document.body.appendChild(el);
    }
    return el;
  }

  function keepaliveOn() {
    keepWant = true;
    var el = keepEl();
    if (!el.paused) return true;
    var p = el.play();
    if (p && p.catch) {
      p.catch(function (err) {
        // Blocked until a gesture, which on a fresh page load is normal
        // rather than exceptional. The gesture listener below retries.
        keepCtx = null;
        note(false, "keep-alive audio is blocked until you tap the page " +
                    "once (" + ((err && err.name) || "autoplay policy") + ")");
        paint();
      });
    }
    return true;
  }

  /* Retried on the first real interaction, and then watched. Android will
     pause this element for its own reasons — another app taking audio
     focus, a call, the media notification's pause button — and a paused
     element means the page is freezable again. Checking every 20 seconds
     costs nothing and is the difference between working all day and
     working until something else played a sound. */
  function keepaliveWatch() {
    if (!keepWant || state.mode !== "on" || !state.keepalive) return;
    var el = document.getElementById("ta-keepalive");
    if (el && el.paused) keepaliveOn();
  }
  setInterval(keepaliveWatch, 20000);

  /* ── PUT IT BACK NOW, NOT IN TWENTY SECONDS ────────────────────────
     The watchdog above is a setInterval, and a frozen page has no
     intervals — so it can only ever repair a keep-alive that stopped
     while the page was still awake. Once Android has frozen the tab it is
     already too late, and the twenty-second gap is exactly when freezing
     happens: right after playback ended and the screen went dark.

     Every announcement plays on OTHER elements, and starting them can
     take audio focus from this one. So the keep-alive is put back the
     instant an announcement finishes rather than at the next tick. The
     repeats cover a pause that arrives slightly after the sound stops,
     which is the common shape — the element goes quiet, then the OS
     tidies up behind it.

     Reported as "it used to work even when android phone was kept
     locked", with the announcement finally arriving the moment the app
     was opened — the signature of a page that had been frozen since the
     last thing it played. */
  function nudgeKeepalive() {
    try { keepaliveWatch(); } catch (e) {}
    [400, 1500, 4000].forEach(function (ms) {
      setTimeout(function () { try { keepaliveWatch(); } catch (e) {} }, ms);
    });
  }

  /* Naming the session is what makes the lock-screen entry legible, and
     wiring its buttons is what makes it honest.

     WHY THE LOCK SCREEN SHOWED NOTHING once: the keep-alive track was ONE
     SECOND long, and Chrome does not create a media notification for media
     shorter than about five seconds — it classifies short clips as sound
     effects rather than playback. */
  function setMediaSession() {
    if (!("mediaSession" in navigator)) return;
    try {
      if (window.MediaMetadata) {
        navigator.mediaSession.metadata = new window.MediaMetadata({
          title: "Announcing the time",
          artist: scheduleWords(),
          album: "DailyPlanner",
        });
      }
      navigator.mediaSession.playbackState = "playing";
      navigator.mediaSession.setActionHandler("pause", function () {
        state.mode = "paused";
        applyMode();
      });
      navigator.mediaSession.setActionHandler("play", function () {
        state.mode = "on";
        applyMode();
      });
      navigator.mediaSession.setActionHandler("stop", function () {
        state.mode = "off";
        state.lastSlot = null;
        applyMode();
      });
    } catch (_) {}
  }

  function keepaliveOff() {
    keepWant = false;
    var el = document.getElementById("ta-keepalive");
    if (el) { try { el.pause(); } catch (_) {} }
    if (!keepCtx) return;
    try {
      if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "none";
    } catch (_) {}
    keepCtx = null;
  }


  function applyKeepalive() {
    // Only worth holding while announcements are actually due to happen.
    if (state.mode === "on" && state.keepalive) keepaliveOn();
    else keepaliveOff();
  }

  function applyMode() {
    if (state.mode === "on") start();
    else {
      stopTimer();
      if (supported()) { try { window.speechSynthesis.cancel(); } catch (_) {} }
    }
    applyKeepalive();
    save();
    paint();
  }

  /* ── the control ────────────────────────────────────────────────── */

  function inject() {
    if (document.getElementById("ta-style")) return;
    var css = [
      ".ta-btn{position:relative}",
      ".ta-btn.is-on{color:#4338ca}",
      ".ta-btn.is-paused{color:#b45309}",
      ".ta-dot{position:absolute;top:2px;right:2px;width:7px;height:7px;border-radius:50%;",
      "background:#4338ca}",
      ".ta-btn.is-paused .ta-dot{background:#f59e0b}",
      ".ta-backdrop{position:fixed;inset:0;z-index:10059;",
      "background:rgba(15,18,28,.45);backdrop-filter:blur(1.5px)}",
      ".ta-backdrop[hidden]{display:none}",
      "html.ta-locked, html.ta-locked body{overflow:hidden}",
      /* CENTRED, not anchored to the button. It is a dialog with several
         fields, a day picker and a list — dragging inside it must not be
         able to land outside it. */
      ".ta-pop{position:fixed;z-index:10060;top:50%;left:50%;",
      "transform:translate(-50%,-50%);width:min(420px,calc(100vw - 24px));",
      "max-height:min(86vh,720px);overflow-y:auto;overscroll-behavior:contain;",
      "padding:14px 16px 16px;",
      "border-radius:14px;border:1px solid var(--color-border,#e5e7eb);",
      "background:var(--color-surface,#fff);color:var(--color-text,#111827);",
      "box-shadow:0 24px 64px rgba(0,0,0,.28);font-size:13px}",
      ".ta-pop[hidden]{display:none}",
      "@media (max-width:520px){.ta-pop{width:calc(100vw - 16px);",
      "max-height:92vh}}",
      ".ta-pop h4{margin:0 0 3px;font-size:13.5px;font-weight:800;padding-right:22px}",
      /* THE WAY OUT OF A MODAL HAS TO LOOK LIKE ONE.
         This was a bare grey glyph on no background in the corner, about
         24px square — "not very visible for the user", and on a phone it
         was also barely tappable. It is a real button now: its own
         surface, its own border, and a 44px target where the pointer is
         a finger. The panel is modal, so nothing outside it closes it and
         this control is the only exit besides Escape. */
      ".ta-x{position:absolute;top:8px;right:9px;",
      "display:inline-flex;align-items:center;justify-content:center;",
      "width:30px;height:30px;padding:0;",
      "border:1px solid var(--color-border,#d1d5db);",
      "background:var(--color-bg,#f3f4f6);",
      "cursor:pointer;font-size:20px;line-height:1;border-radius:999px;",
      "color:var(--color-text,#111827);font-weight:700}",
      ".ta-x:hover{background:#ef4444;border-color:#ef4444;color:#fff}",
      ".ta-x:focus-visible{outline:2px solid var(--color-primary,#4f46e5);",
      "outline-offset:2px}",
      "@media (pointer:coarse){.ta-x{width:44px;height:44px;font-size:24px;",
      "top:6px;right:6px}}",
      ".ta-pop p{margin:0 0 10px;font-size:11.5px;line-height:1.45;",
      "color:var(--color-text-secondary,#6b7280)}",
      ".ta-row{display:flex;gap:6px;margin-bottom:8px}",
      // .ta-int is listed everywhere .ta-row is. The interval buttons live in
      // .ta-int and these rules were scoped to .ta-row only, so 15/30/45/60
      // never highlighted the selected one — and never even got a border or a
      // background. paint() was setting .on correctly the whole time; there
      // was simply nothing for the class to do.
      ".ta-row button,.ta-int button{font:inherit;font-size:12.5px;font-weight:700;",
      "padding:6px 8px;border-radius:9px;border:1px solid var(--color-border,#e5e7eb);",
      "background:var(--color-bg,#f9fafb);color:var(--color-text,#111827);cursor:pointer}",
      ".ta-row button{flex:1}",
      ".ta-row button.on,.ta-int button.on{background:#4338ca;border-color:#4338ca;",
      "color:#fff;box-shadow:0 0 0 2px color-mix(in srgb,#4338ca 30%,transparent)}",
      ".ta-int{display:flex;gap:6px;align-items:center;font-size:11.5px;font-weight:700;",
      "color:var(--color-text-secondary,#6b7280)}",
      ".ta-int{flex-wrap:wrap}",
      ".ta-int button{flex:0 0 auto;padding:5px 10px;border-radius:999px;font-size:11.5px}",
      ".ta-warn{margin-top:9px;font-size:11px;line-height:1.45;color:#b45309}",
      ".ta-keep{display:flex;align-items:center;gap:7px;margin-top:11px;",
      "font-size:12px;font-weight:700;cursor:pointer}",
      ".ta-keep input{width:15px;height:15px;accent-color:#4338ca;cursor:pointer}",
      ".ta-note{margin-top:7px !important;font-size:10.5px !important;line-height:1.45}",
      ".ta-tip{margin-top:6px !important;font-size:11px !important;line-height:1.45;",
      "color:#4338ca;font-weight:700}",
      ".ta-tip[hidden]{display:none}",
      ".ta-fld{margin-top:9px}",
      ".ta-fld[hidden]{display:none}",
      ".ta-fld label{display:block;font-size:11.5px;font-weight:700;",
      "color:var(--color-text-secondary,#6b7280)}",
      ".ta-fld input{width:100%;box-sizing:border-box;margin-top:4px;font:inherit;",
      "font-size:13px;padding:6px 8px;border-radius:8px;",
      "border:1px solid var(--color-border,#e5e7eb);",
      "background:var(--color-bg,#f9fafb);color:var(--color-text,#111827)}",
      ".ta-fld small{display:block;margin-top:3px;font-size:10.5px;line-height:1.4;",
      "color:var(--color-text-secondary,#6b7280)}",
      ".ta-health{margin:9px 0 0 !important;font-size:11px !important;",
      "line-height:1.45;font-weight:700}",
      ".ta-health.good{color:#047857}",
      ".ta-health.bad{color:#b91c1c}",
      ".ta-idle{margin:8px 0 0 !important;font-size:11px !important;",
      "line-height:1.45;font-weight:700;padding:8px 10px;border-radius:8px;",
      "background:#fdf1e3;color:#8a4b09 !important;",
      "border:1px solid #f0c98a}",
      ".ta-idle[hidden]{display:none}",
      ".ta-perm{margin:0 0 10px !important;font-size:11px !important;",
      "line-height:1.45;font-weight:700;padding:8px 10px;border-radius:8px}",
      ".ta-perm.granted{background:#e6f4ef;color:#065f46 !important;",
      "border:1px solid #a7d7c5}",
      ".ta-perm.default,.ta-perm.denied{background:#fdf1e3;",
      "color:#8a4b09 !important;border:1px solid #f0c98a}",
      ".ta-build{margin:8px 0 0 !important;font-size:10.5px !important;",
      "font-family:ui-monospace,Menlo,monospace;",
      "color:var(--color-text-secondary,#6b7280) !important}",
      ".ta-perm button{display:block;margin-top:7px;font:inherit;",
      "font-size:11.5px;font-weight:800;padding:6px 12px;border-radius:8px;",
      "border:0;background:#4338ca;color:#fff;cursor:pointer}",
      /* Collapsed settings. Each row states its VALUE on the right, which
         is the thing tabs could not do — a tab hides its contents
         entirely, so you had to open all four to see what was set. */
      ".ta-fold{margin-top:8px;border:1px solid var(--color-border,#e5e7eb);",
      "border-radius:10px;overflow:hidden}",
      ".ta-fold > summary{list-style:none;cursor:pointer;display:flex;",
      "align-items:baseline;gap:8px;padding:9px 11px;font-size:12px;",
      "font-weight:700;background:var(--color-bg,#f9fafb)}",
      ".ta-fold > summary::-webkit-details-marker{display:none}",
      ".ta-fold > summary::before{content:'\\25B8';font-size:10px;",
      "color:var(--color-text-secondary,#9ca3af);transition:transform .12s}",
      ".ta-fold[open] > summary::before{transform:rotate(90deg)}",
      ".ta-fold > summary b{margin-left:auto;font-weight:600;font-size:11px;",
      "color:var(--color-text-secondary,#6b7280);font-variant-numeric:tabular-nums}",
      ".ta-fold > *:not(summary){padding:0 11px}",
      ".ta-fold > *:last-child{padding-bottom:11px}",
      ".ta-fold p{margin:9px 0;font-size:11.5px;line-height:1.5;",
      "color:var(--color-text-secondary,#6b7280)}",
      /* The section heading and its one action. */
      ".ta-sec-row{display:flex;align-items:center;gap:8px;margin:14px 0 6px}",
      ".ta-sec-row .ta-sec{margin:0;flex:1}",
      ".ta-new{font:inherit;font-size:11.5px;font-weight:800;padding:5px 11px;",
      "border-radius:999px;border:1px solid #4338ca;background:#fff;",
      "color:#4338ca;cursor:pointer}",
      ".ta-new:hover{background:#4338ca;color:#fff}",
      ".ta-new[hidden]{display:none}",
      ".ta-add[hidden]{display:none}",
      ".ta-actions{margin-top:9px}",
      "[data-ta-cancel]{flex:0 0 auto}",
      ".ta-tabs{display:flex;gap:2px;margin:12px 0 0;",
      "border-bottom:1px solid var(--color-border,#e5e7eb)}",
      ".ta-tabs button{flex:1;font:inherit;font-size:11.5px;font-weight:700;",
      "padding:7px 4px;border:0;border-bottom:2px solid transparent;",
      "background:none;cursor:pointer;color:var(--color-text-secondary,#6b7280);",
      "margin-bottom:-1px;white-space:nowrap}",
      ".ta-tabs button.on{color:#4338ca;border-bottom-color:#4338ca}",
      ".ta-tabs button:hover{color:#4338ca}",
      ".ta-pane{padding-top:11px}",
      ".ta-pane[hidden]{display:none}",
      ".ta-pane > p{margin:0 0 10px;font-size:11.5px;line-height:1.5;",
      "color:var(--color-text-secondary,#6b7280)}",
      ".ta-more{display:block;width:100%;margin-top:8px;font:inherit;",
      "font-size:11px;font-weight:700;padding:6px;border-radius:8px;cursor:pointer;",
      "border:1px dashed var(--color-border,#d1d5db);background:none;",
      "color:var(--color-text-secondary,#6b7280);text-align:left}",
      ".ta-more:hover{border-color:#4338ca;color:#4338ca}",
      ".ta-more::before{content:'+ ';font-weight:800}",
      "[data-ta-advanced][hidden]{display:none}",
      ".ta-sec{margin:12px 0 5px;font-size:11px;font-weight:800;",
      "letter-spacing:.05em;text-transform:uppercase;",
      "color:var(--color-text-secondary,#6b7280)}",
      ".ta-list{list-style:none;margin:0;padding:0;max-height:260px;",
      "overflow:auto;border:1px solid var(--color-border,#e5e7eb);",
      "border-radius:9px}",
      ".ta-list:empty{display:none}",
      ".ta-empty{padding:9px 10px;font-size:11px;line-height:1.45;",
      "color:var(--color-text-secondary,#6b7280)}",
      ".ta-item{display:flex;align-items:center;gap:7px;padding:6px 8px;",
      "border-bottom:1px solid var(--color-border,#e5e7eb);font-size:12px}",
      ".ta-item:last-child{border-bottom:0}",
      ".ta-item.off{opacity:.5}",
      ".ta-item.expired .ta-when i{color:#b91c1c}",
      ".ta-tog{flex:0 0 auto;border:0;background:none;cursor:pointer;",
      "font-size:13px;line-height:1;padding:2px;color:#4338ca}",
      ".ta-item.off .ta-tog{color:var(--color-text-secondary,#9ca3af)}",
      ".ta-when{flex:0 0 auto;display:flex;flex-direction:column;",
      "min-width:70px;line-height:1.25}",
      ".ta-when b{font-size:12px;font-variant-numeric:tabular-nums}",
      ".ta-when i{font-style:normal;font-size:9.5px;",
      "color:var(--color-text-secondary,#6b7280)}",
      ".ta-what{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;",
      "white-space:nowrap}",
      ".ta-mute-in{flex:1 1 auto;min-width:0;font:inherit;font-size:12px;",
      "padding:3px 6px;border-radius:6px;",
      "border:1px solid var(--color-border,#e5e7eb);",
      "background:var(--color-surface,#fff);color:var(--color-text,#111827)}",
      ".ta-edit{flex:0 0 auto;border:0;background:none;cursor:pointer;",
      "font-size:12px;line-height:1;padding:2px 4px;",
      "color:var(--color-text-secondary,#9ca3af)}",
      ".ta-edit:hover{color:#4338ca}",
      ".ta-item.editing{background:color-mix(in srgb,#4338ca 10%,transparent)}",
      "[data-ta-cancel]{flex:0 0 auto;font:inherit;font-size:12px;",
      "font-weight:700;padding:5px 10px;border-radius:8px;cursor:pointer;",
      "border:1px solid var(--color-border,#e5e7eb);background:#fff;color:#374151}",
      "[data-ta-cancel][hidden]{display:none}",
      ".ta-del{flex:0 0 auto;border:0;background:none;cursor:pointer;",
      "font-size:15px;line-height:1;padding:2px 4px;",
      "color:var(--color-text-secondary,#9ca3af)}",
      ".ta-del:hover{color:#b91c1c}",
      ".ta-add{display:flex;flex-direction:column;gap:5px;margin-top:7px}",
      ".ta-add-row{display:flex;flex-wrap:wrap;gap:5px;align-items:flex-end}",
      ".ta-add select{font:inherit;font-size:12px;padding:5px 7px;",
      "border-radius:8px;border:1px solid var(--color-border,#e5e7eb);",
      "background:var(--color-bg,#f9fafb);color:var(--color-text,#111827);",
      "flex:1 1 120px;min-width:0}",
      ".ta-dt{flex:1 1 120px;display:flex;flex-direction:column;gap:2px;",
      "font-size:10px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;",
      "color:var(--color-text-secondary,#6b7280);min-width:0}",
      ".ta-dt i{font-style:normal;font-weight:500;text-transform:none;",
      "letter-spacing:0}",
      ".ta-dt input{width:100%}",
      ".ta-dt .ta-timefld{width:100%}",
      ".ta-dt .ta-timefld input{flex:1 1 auto;min-width:0}",
      ".ta-days{display:flex;flex-wrap:wrap;gap:4px}",
      ".ta-days[hidden]{display:none}",
      ".ta-days button{font:inherit;font-size:11px;font-weight:700;",
      "padding:4px 8px;border-radius:999px;cursor:pointer;",
      "border:1px solid var(--color-border,#e5e7eb);",
      "background:#fff;color:#374151}",
      ".ta-days button.on{background:#4338ca;border-color:#4338ca;color:#fff}",
      "[data-ta-new-end][aria-invalid],[data-ta-new-until][aria-invalid]",
      "{border-color:#b91c1c}",
      ".ta-add input{font:inherit;font-size:12px;padding:5px 7px;",
      "border-radius:8px;border:1px solid var(--color-border,#e5e7eb);",
      "background:var(--color-bg,#f9fafb);color:var(--color-text,#111827);",
      "min-width:0}",
      ".ta-timefld{display:flex;align-items:stretch;gap:4px;flex:0 0 auto;min-width:0}",
      ".ta-ampm{display:flex;border:1px solid var(--color-border,#e5e7eb);",
      "border-radius:8px;overflow:hidden;flex:0 0 auto}",
      /* HARDCODED #fff HERE PAINTED A WHITE STRIP ACROSS A DARK PANEL,
         and the unselected button was then near-white on near-white — the
         pair read as "nothing is selected" whichever one was. Both states
         come from tokens now, and the selected one carries weight and a
         ring as well as colour so it does not depend on hue alone. */
      ".ta-ampm button{font:inherit;font-size:10.5px;font-weight:700;",
      "letter-spacing:.03em;padding:0 8px;border:0;cursor:pointer;",
      "background:var(--color-bg,#f3f4f6);",
      "color:var(--color-text-secondary,#6b7280);",
      "transition:background .12s,color .12s}",
      ".ta-ampm button:hover{background:color-mix(in srgb,#4338ca 14%,transparent);",
      "color:var(--color-text,#111827)}",
      ".ta-ampm button + button{border-left:1px solid var(--color-border,#e5e7eb)}",
      ".ta-ampm button.on{background:#4338ca;color:#fff;font-weight:800;",
      "box-shadow:inset 0 0 0 1px #4338ca}",
      /* Dimmed when the typed text already settles it — clicking would do
         nothing, and a control that does nothing should look like it. */
      ".ta-ampm button.moot{opacity:.4}",
      ".ta-preview{display:block;margin-top:4px;font-size:11px;font-weight:700;",
      "color:#4338ca;min-height:14px;font-variant-numeric:tabular-nums}",
      "[data-ta-new-at]{flex:0 0 78px}",
      "[data-ta-new-text]{flex:1 1 140px}",
      "[data-ta-new-at][aria-invalid]{border-color:#b91c1c}",
      /* SCOPED TO THE ADD BUTTON ITSELF, not every button inside the add
         form. Written as `.ta-add button` it sat LATER in this sheet than
         `.ta-ampm button` and `.ta-days button` at the SAME specificity, so
         it won — and painted the AM/PM pair and the weekday chips solid
         indigo. Every one of them looked selected, permanently. */
      "[data-ta-add]{flex:0 0 auto;font:inherit;font-size:12px;",
      "font-weight:700;padding:5px 12px;border-radius:8px;border:0;",
      "background:#4338ca;color:#fff;cursor:pointer}",
      ".ta-hint{display:block;margin-top:5px;font-size:10.5px;line-height:1.45;",
      "color:var(--color-text-secondary,#6b7280)}",
      ".ta-hint code{font-size:10px;padding:1px 3px;border-radius:3px;",
      "background:var(--color-bg,#f3f4f6)}",
      ".ta-saved{float:right;font-size:11px;font-weight:800;color:#047857;",
      "background:color-mix(in srgb,#047857 14%,transparent);",
      "border:1px solid color-mix(in srgb,#047857 35%,transparent);",
      "border-radius:999px;padding:2px 8px;line-height:1.5;",
      "opacity:0;transform:translateY(-2px);transition:opacity .12s,transform .12s}",
      ".ta-saved.show{opacity:1;transform:none}",
      ".ta-auto{margin:10px 0 0 !important;font-size:10.5px !important;",
      "line-height:1.45;font-style:italic}",
      ".ta-now{margin:8px 0 0 !important;font-size:11.5px !important;",
      "line-height:1.45;font-weight:700;padding:7px 9px;border-radius:8px;",
      "background:var(--color-bg,#f3f4f6);",
      "color:var(--color-text,#111827) !important}",
    ].join("");
    var el = document.createElement("style");
    el.id = "ta-style";
    el.textContent = css;
    document.head.appendChild(el);
  }

  var btn = null, pop = null, backdrop = null;

  function paint() {
    if (!btn) return;
    btn.classList.toggle("is-on", state.mode === "on");
    btn.classList.toggle("is-paused", state.mode === "paused");
    btn.title = state.mode === "on"
      ? "Announcing the time every " + state.every + " minutes"
      : state.mode === "paused" ? "Time announcements paused"
      : "Announce the time out loud";
    var dot = btn.querySelector(".ta-dot");
    if (state.mode === "off") { if (dot) dot.remove(); }
    else if (!dot) {
      var d = document.createElement("span");
      d.className = "ta-dot";
      btn.appendChild(d);
    }
    if (!pop) return;
    pop.querySelectorAll("[data-ta-mode]").forEach(function (b) {
      b.classList.toggle("on", b.getAttribute("data-ta-mode") === state.mode);
    });
    pop.querySelectorAll("[data-ta-every]").forEach(function (b) {
      b.classList.toggle("on", parseInt(b.getAttribute("data-ta-every"), 10) === state.every);
    });
    var keep = pop.querySelector("[data-ta-keep]");
    if (keep) keep.checked = !!state.keepalive;
    var chk = pop.querySelector("[data-ta-chime]");
    if (chk) chk.checked = !!state.chime;
    var tip = pop.querySelector(".ta-tip");
    if (tip) tip.hidden = !(isInstalled() && !state.keepalive);
    var warn = pop.querySelector(".ta-warn");
    if (warn) warn.hidden = !(state.mode === "on" && !armed);

    // The one form does both jobs, so it must SAY which job it is doing.
    var addBtn = pop.querySelector("[data-ta-add]");
    var cancelBtn = pop.querySelector("[data-ta-cancel]");
    if (addBtn) addBtn.textContent = editingId ? "Save" : "Add";
    if (cancelBtn) cancelBtn.hidden = !editingId;

    var sc = pop.querySelector("[data-ta-sum-clock]");
    if (sc) sc.textContent = state.every > 0
      ? "every " + state.every + " min" : "off";
    var sn = pop.querySelector("[data-ta-sum-notify]");
    if (sn) {
      var muted = (mutes || []).filter(function (m) { return m.muted; }).length;
      sn.textContent = !mutes ? "" :
        muted ? muted + " muted of " + mutes.length : String(mutes.length);
    }
    var sd = pop.querySelector("[data-ta-sum-device]");
    if (sd) {
      var kel0 = document.getElementById("ta-keepalive");
      sd.textContent = (state.chime ? "chime on" : "chime off") +
        (state.keepalive ? (kel0 && !kel0.paused ? " · holding" : " · not holding")
                         : "");
    }
    var sb = pop.querySelector("[data-ta-build-sum]");
    if (sb) sb.textContent = BUILD;

    var custom = INTERVALS.indexOf(state.every) === -1;
    var cbtn = pop.querySelector("[data-ta-custom]");
    if (cbtn) {
      cbtn.classList.toggle("on", custom);
      cbtn.textContent = custom ? state.every + "m" : "Custom";
    }
    var crow = pop.querySelector("[data-ta-customrow]");
    if (crow && custom) crow.hidden = false;
    var cin = pop.querySelector("[data-ta-every-in]");
    if (cin && document.activeElement !== cin) cin.value = state.every;
    var lbl = pop.querySelector("[data-ta-label]");
    if (lbl && document.activeElement !== lbl) lbl.value = state.label;
    var sEl = pop.querySelector("[data-ta-new-start]");
    if (sEl && !sEl.value) sEl.value = todayYMD();
    paintDayChips();
    paintMer();
    paintAtEcho();
    paintMutes();

    /* WHAT IS CURRENTLY SAVED, in words. Read back from the same state the
       announcer schedules from, so if this line is wrong the feature is
       wrong — it cannot drift into reassuring you about a setting that is
       not the one in effect. */
    var nowEl = pop.querySelector("[data-ta-now]");
    if (nowEl) {
      var what = scheduleWords();
      if (state.label) what += " \u2014 saying \u201c" + state.label + "\u201d first";
      nowEl.textContent = (state.mode === "on" ? "Saved & running: "
                           : state.mode === "paused" ? "Saved, paused: "
                           : "Saved, stopped: ") + what;
    }

    /* CAN THE WORDS BE PLAYED AT ALL?
       On a locked Android the only way to hear them is rendered audio, so
       whether that audio is reachable IS the feature working or not. It
       was being fetched silently and failing silently. */
    var say = pop.querySelector("[data-ta-say]");
    if (say) {
      var n = Object.keys(sayCache).length;
      if (sayState === "ready" || n) {
        say.className = "ta-health good";
        say.textContent = "\u2713 Spoken audio ready (" + n + " cached)";
      } else if (sayState === "none") {
        say.className = "ta-health";
        say.textContent = "Spoken audio: nothing fetched yet.";
      } else {
        say.className = "ta-health bad";
        say.textContent = "\u26a0 Spoken audio unavailable \u2014 " +
          sayState + ". On a locked Android the words cannot play without " +
          "it; the chime and the notification still will.";
      }
    }

    /* THE LAST ANNOUNCEMENT, AND WHAT EACH HALF OF IT DID. */
    var fire = pop.querySelector("[data-ta-fire]");
    if (fire) {
      if (!lastFire) {
        fire.className = "ta-health";
        fire.textContent = "No announcement has fired on this device yet.";
      } else {
        var when = lastFire.at.toTimeString().slice(0, 5);
        // "while visible" read as "the screen was on", and it does not mean
        // that: a locked phone keeps the page visible. Saying which flag
        // this is stops the next reading being misdiagnosed the way the
        // last one was.
        var where = lastFire.hidden === null ? "" :
          lastFire.hidden ? " (page hidden)"
                          : " (page not hidden \u2014 a locked screen counts " +
                            "as not hidden)";
        var ch = lastFire.chime || "no result";
        var sp = lastFire.spoke || "no result";
        var ok = lastFire.spoke === "spoke" ||
                 lastFire.spoke === "played (audio)";
        fire.className = "ta-health " + (ok ? "good" : "bad");
        fire.textContent = "Last fired " + when + where +
          " \u2014 chime: " + ch + ", speech: " + sp +
          (lastFire.audio ? ", rendered audio: " + lastFire.audio : "") +
          ", keep-alive: " + (lastFire.keep ? "holding" : "NOT holding") +
          ", speech audio: " +
          (lastFire.unlocked === null ? "unknown"
           : lastFire.unlocked ? "unlocked" : "NEVER UNLOCKED") +
          (lastFire.notified ? ", fell back to a notification" : "");
      }
    }

    /* THE TWO FACTS THAT MAKE EVERY OTHER DIAGNOSIS MEANINGFUL:
       which build this device is running, and when the clock was last
       actually read. A frozen page keeps its settings and stops ticking,
       so a stale "last checked" is the difference between "the feature is
       broken" and "this page was asleep". */
    var build = pop.querySelector("[data-ta-build]");
    if (build) {
      var ago = lastTick ? Math.round((Date.now() - lastTick) / 1000) : null;
      var agoTxt = ago === null ? "never (not started on this device)"
        : ago < 60 ? ago + "s ago"
        : Math.round(ago / 60) + " min ago \u2014 this page was asleep";
      build.textContent = "Build " + BUILD + " \u00b7 checks every " +
        (TICK_MS / 1000) + "s \u00b7 last check " + agoTxt;
    }

    /* IS THE PAGE ACTUALLY BEING HELD ALIVE?
       The checkbox says what you asked for. This says what is TRUE, which
       are different things whenever autoplay has blocked the audio — and
       on a fresh page load autoplay always has. Without this line there
       was no way to tell a working keep-alive from a ticked box. */
    var hold = pop.querySelector("[data-ta-hold]");
    if (hold) {
      var kel = document.getElementById("ta-keepalive");
      if (!state.keepalive) {
        hold.className = "ta-health";
        hold.textContent = "Keep-alive off — this device will be frozen "
          + "shortly after the screen locks.";
      } else if (kel && !kel.paused) {
        hold.className = "ta-health good";
        hold.textContent = "\u2713 Holding audio — the page keeps running "
          + "with the screen off.";
      } else {
        hold.className = "ta-health bad";
        hold.textContent = "\u26a0 Not holding yet — tap anywhere on this "
          + "page once. Browsers refuse to start audio until you do, and "
          + "until it starts the phone will freeze this page when it locks.";
      }
    }

    /* NOTIFICATION PERMISSION, STATED PLAINLY.
       The self-heal deliberately never prompts, so on a device where
       permission was never granted it does nothing — correctly, and
       SILENTLY. That silence is why a phone kept receiving nothing while
       everything else looked configured. The panel now says which of the
       three states this device is in, and offers the one action that
       changes it. */
    var perm = pop.querySelector("[data-ta-perm]");
    if (perm) {
      var st = (typeof Notification === "undefined")
        ? "unsupported" : Notification.permission;
      perm.className = "ta-perm " + st;
      if (st === "granted") {
        // THE BROWSER SAYING YES IS NOT THE SERVER SAYING IT CAN REACH YOU.
        // A device sits at "granted" while its row on the server is
        // is_active=false — one 404/410 from the push service retires it —
        // and every screen still reads "notifications are on". That gap is
        // the entire explanation for a phone that gets nothing with the app
        // closed, and it was visible nowhere.
        if (pushReach === "dead") {
          perm.className = "ta-perm denied";
          perm.innerHTML = "\u26a0 This browser allows notifications, but " +
            "the <b>server cannot reach this device</b> \u2014 its " +
            "registration was rejected and retired. Nothing arrives while " +
            "the app is closed until it is registered again. " +
            "<button type=\"button\" data-ta-perm-on>Re-register</button>";
        } else if (pushReach === "missing") {
          perm.className = "ta-perm denied";
          perm.innerHTML = "\u26a0 This browser allows notifications but " +
            "this device is <b>not registered</b> with the server, so " +
            "nothing can arrive while the app is closed. " +
            "<button type=\"button\" data-ta-perm-on>Register</button>";
        } else if (pushReach === "ok") {
          perm.innerHTML = "\u2713 Notifications are on for this device, so " +
            "announcements reach you with the screen off. The server has " +
            "it registered.";
        } else {
          // NOT "on" YET — nobody has answered. Saying "notifications
          // are on" here and flipping to the orange warning a second later,
          // when /api/push/status replies, reads as the setting switching
          // itself off. It never was on; this panel had not asked.
          perm.className = "ta-perm";
          perm.innerHTML = "The browser allows notifications. Checking " +
            "whether the server can still reach this device\u2026";
        }
      } else if (st === "denied") {
        perm.innerHTML = "\u26a0 Notifications are <b>blocked</b> for this " +
          "site in your browser. Nothing can reach a locked screen until " +
          "you unblock them in the browser\u2019s site settings \u2014 " +
          "this app cannot ask again once blocked.";
      } else if (st === "unsupported") {
        perm.innerHTML = "This browser does not support notifications.";
      } else {
        perm.innerHTML = "\u26a0 Notifications are <b>off</b> on this " +
          "device, so nothing reaches you with the screen off. " +
          "<button type=\"button\" data-ta-perm-on>Turn them on</button>";
      }
    }

    /* NOT ANNOUNCING ON THIS DEVICE.
       Start/Pause/Stop is deliberately per-device — pausing on your phone
       must not silence the laptop you are sitting at. The cost of that
       choice is this trap: an announcement created on the phone SYNCS
       everywhere and then says nothing there, because Start was never
       pressed on the phone. The schedule looks right and the device is
       silent, so it reads as a broken feature rather than a switch. */
    var idle = pop.querySelector("[data-ta-idle]");
    if (idle) {
      var live = state.items.filter(function (it) {
        return it.on && !isExpired(it, todayYMD());
      }).length;
      var willSpeak = state.mode === "on";
      idle.hidden = !(live > 0 && !willSpeak);
      if (!idle.hidden) {
        idle.textContent = live + (live === 1 ? " announcement is" :
                                                " announcements are") +
          " scheduled, but this device is " +
          (state.mode === "paused" ? "PAUSED" : "STOPPED") +
          " — press Start above, on this device. Start/Pause/Stop is per " +
          "device on purpose, so pausing on your phone does not silence " +
          "your laptop.";
      }
    }

    /* THE HEALTH LINE. The whole reason this feature could fail unnoticed
       was that nothing on screen ever said whether it had worked. */
    var h = pop.querySelector("[data-ta-health]");
    if (h) {
      if (!health.at) {
        h.textContent = state.mode === "on"
          ? "Nothing announced yet this session."
          : "";
        h.className = "ta-health";
      } else {
        var t = health.at.toTimeString().slice(0, 5);
        h.className = "ta-health " + (health.ok ? "good" : "bad");
        h.textContent = health.ok
          ? "\u2713 Spoke at " + t + " \u2014 \u201c" + health.said + "\u201d"
          : "\u26a0 " + t + " \u2014 " + health.why;
      }
    }
  }

  /* AUTOSAVE, SAID OUT LOUD.
     There is no Save button and there should not be — this writes to
     localStorage, and a setting that needs saving is a setting people forget
     to save. But silent persistence is indistinguishable from no persistence,
     which is exactly the doubt it caused. So it now says "Saved" for a beat
     after every keystroke settles. */
  var savedTimer = null;
  function savedFlash() {
    var el = pop && pop.querySelector("[data-ta-saved]");
    if (!el) return;
    el.textContent = "\u2713 Saved";
    el.classList.add("show");
    if (savedTimer) clearTimeout(savedTimer);
    // Long enough to notice and read. The first version held it 1.4s at
    // 10.5px, which is the same as not showing it.
    savedTimer = setTimeout(function () { el.classList.remove("show"); }, 2600);
  }

  function paintAtEcho() {
    if (!pop) return;
    var ul = pop.querySelector("[data-ta-list]");
    if (!ul) return;
    if (!state.items.length) {
      ul.innerHTML = '<li class="ta-empty">Nothing scheduled yet. Add one ' +
                     'below &mdash; 5.00, 5:00 and 5am all mean five in the ' +
                     'morning; use 5pm or 17:00 for the evening.</li>';
      return;
    }
    var today = todayYMD();
    var rows = state.items.slice().sort(function (a, b) {
      return (a.date || "") === (b.date || "")
        ? a.at.localeCompare(b.at)
        : (a.date || "0").localeCompare(b.date || "0");
    });
    ul.innerHTML = rows.map(function (it) {
      // EXPIRED IS SHOWN, NOT HIDDEN. A one-off whose day has passed will
      // never speak again, and silently keeping it in the list looks like a
      // setting that is still armed.
      var expired = isExpired(it, today);
      var when = expired ? "finished \u00b7 " + repeatWords(it)
                         : repeatWords(it);
      return '<li class="ta-item' + (it.on ? "" : " off") +
             (expired ? " expired" : "") +
             (it.id === editingId ? " editing" : "") +
             '" data-id="' + esc(it.id) + '">' +
             '<button type="button" class="ta-tog" data-ta-toggle ' +
               'aria-pressed="' + (it.on ? "true" : "false") + '" ' +
               'title="' + (it.on ? "Stop this one" : "Start this one") + '">' +
               (it.on ? "\u25CF" : "\u25CB") + '</button>' +
             '<span class="ta-when"><b>' + esc(timeWords(it)) + '</b>' +
               '<i>' + esc(when) + '</i></span>' +
             '<span class="ta-what">' + esc(it.text || "(just the time)") +
             '</span>' +
             '<button type="button" class="ta-edit" data-ta-edit ' +
               'title="Edit">\u270E</button>' +
             '<button type="button" class="ta-del" data-ta-del ' +
               'title="Delete">&times;</button>' +
             '</li>';
    }).join("");
  }

  //: Days selected in the ADD form, before the announcement exists.
  var newDays = [];
  //: The announcement being edited, or null when adding a new one. The form
  //: is one form doing both jobs — a separate edit dialog would duplicate
  //: every field and every validation rule, and they would drift.
  var editingId = null;
  //: AM/PM chosen for each time field in the ADD form. Defaults to morning,
  //: which is what a bare "5" nearly always means when someone is setting a
  //: wake-up or a start-of-day reminder.
  var newMer = { at: "am", until: "am" };

  /* Is the chooser actually deciding anything for this text? It is not, when
     the text already carries am/pm or is unambiguously 24-hour. Shown by
     dimming the buttons, so nobody wonders why clicking them does nothing. */
  function merApplies(text) {
    var t = String(text || "").trim().toLowerCase();
    if (!t) return true;
    if (/(am|pm)/.test(t)) return false;
    var m = /^(\d{1,2})/.exec(t.replace(/[.\-]/, ":"));
    if (!m) return true;
    var h = parseInt(m[1], 10);
    return h >= 1 && h <= 12;
  }

  function paintMer() {
    if (!pop) return;
    ["at", "until"].forEach(function (which) {
      var input = pop.querySelector(which === "at"
        ? "[data-ta-new-at]" : "[data-ta-new-until]");
      var live = merApplies(input && input.value);
      pop.querySelectorAll('[data-ta-mer="' + which + '"]').forEach(function (b) {
        var on = b.getAttribute("data-v") === newMer[which];
        b.classList.toggle("on", on && live);
        b.classList.toggle("moot", !live);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
    });
    paintPreview();
  }

  /* The whole point of the chooser is that nothing is left to guess, so the
     resolved time is shown as it is typed rather than after adding. */
  function paintPreview() {
    var el = pop && pop.querySelector("[data-ta-preview]");
    if (!el) return;
    var atEl = pop.querySelector("[data-ta-new-at]");
    var uEl = pop.querySelector("[data-ta-new-until]");
    var mEl = pop.querySelector("[data-ta-new-mins]");
    var a = parseTimes(atEl && atEl.value, newMer.at);
    if (!a.length) { el.textContent = ""; return; }
    var txt = "\u2192 " + a.map(friendly).join(", ");
    var u = parseTimes(uEl && uEl.value, newMer.until);
    var step = parseInt(mEl && mEl.value, 10);
    if (u.length) {
      txt += " until " + friendly(u[0]);
      if (step > 0) {
        var n = TA_countSlots(a[0], u[0], step);
        txt += ", every " + step + " min" +
               (n ? " \u00b7 " + n + " time" + (n === 1 ? "" : "s") + " a day" : "");
      }
    }
    el.textContent = txt;
  }

  function TA_countSlots(from, to, step) {
    var f = hhmmToMins(from), t = hhmmToMins(to);
    if (f === null || t === null || t < f || !(step > 0)) return 0;
    return Math.floor((t - f) / step) + 1;
  }

  function paintDayChips() {
    if (!pop) return;
    var wrap = pop.querySelector("[data-ta-days]");
    var sel = pop.querySelector("[data-ta-new-repeat]");
    if (!wrap || !sel) return;
    wrap.hidden = sel.value !== "custom";
    wrap.querySelectorAll("[data-ta-day]").forEach(function (b) {
      var d = parseInt(b.getAttribute("data-ta-day"), 10);
      b.classList.toggle("on", newDays.indexOf(d) !== -1);
      b.setAttribute("aria-pressed", newDays.indexOf(d) !== -1 ? "true" : "false");
    });
  }

  /* ── SERVER SYNC ────────────────────────────────────────────────────
     The announcements, the interval and the label live on the server so
     they follow you between devices. localStorage stays as the CACHE, not
     as the record: it is what makes the announcer work offline, before the
     first response arrives, and on a page where the fetch fails.

     Mode, keep-alive and the `said` marks stay purely local. Pausing on
     your phone must not silence the laptop you are sitting at.

     PULL ONCE PER PAGE, then push on every change. There is one person
     editing at a time in practice, and per-item upserts mean two devices
     adding different announcements merge rather than clobber. */
  var synced = false;

  function pullState() {
    if (synced) return;
    synced = true;
    fetch("/api/announcer/state", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.ok) return;

        // FIRST RUN ON A NEW ACCOUNT: the server has nothing and this
        // browser has a schedule someone built before the sync existed.
        // Push it up rather than wiping it — losing their work to an
        // upgrade is the one outcome that must not happen.
        if (!j.items.length && state.items.length) {
          pushItems(state.items);
          pushSettings();
          return;
        }

        state.items = j.items.map(function (it) {
          return {
            id: it.id, at: it.at, until: it.until || null,
            mins: it.mins || 0, repeat: it.repeat || "daily",
            days: it.days || [],
            start: it.start || todayYMD(), end: it.end || null,
            text: it.text || "", on: it.on !== false,
          };
        });
        state.every = j.every;
        state.label = j.label || "";
        save();
        paint();
      })
      .catch(function () { /* offline: the cache is already loaded */ });
  }

  /* RETURNS THE PARSED BODY. It used to return nothing at all, which was
     harmless for the saves it was written for — they only care whether the
     request succeeded — and silently broke both of the callers added later
     that ASK the server something:

       * /api/push/status always resolved undefined, so pushReach stayed
         "unknown" and the "the server cannot reach this device" warning
         could never appear. The whole check was inert.
       * /api/push/diagnose always took the failure branch and printed
         "Could not run the check" no matter what came back.

     Both looked like server problems and were this. A response with no
     body is not an error, so it resolves to an empty object rather than
     rejecting. */
  function apiPost(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(body),
    }).then(function (r) {
      if (!r.ok) throw new Error("save failed");
      return r.json().catch(function () { return {}; });
    });
  }

  function pushItems(items) {
    return apiPost("/api/announcer/items", { items: items })
      .catch(function () {
        // The local copy is already saved, so nothing is lost — but a
        // schedule that exists on one device only is exactly the problem
        // this feature was built to remove, so say so.
        note(false, "saved on this device, but could not reach the server");
      });
  }

  //: These two fire on every keystroke, so the write is debounced. The
  //: LOCAL save is not — losing a character to a dropped connection would
  //: be absurd.
  var settingsTimer = null;
  function pushSettingsSoon() {
    if (settingsTimer) clearTimeout(settingsTimer);
    settingsTimer = setTimeout(pushSettings, 800);
  }

  function pushSettings() {
    return apiPost("/api/announcer/settings",
                   { every: state.every, label: state.label })
      .catch(function () {});
  }

  function pushDelete(id) {
    return fetch("/api/announcer/items/" + encodeURIComponent(id), {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken() },
    }).catch(function () {
      note(false, "deleted here, but could not reach the server");
    });
  }

  /* Whether the SERVER can reach this browser: "unknown" until asked,
     then "ok" | "dead" (registered and retired) | "missing" (never
     registered). Asked once per panel open — it is a cheap lookup and the
     answer changes only when a send fails. */
  var pushReach = "unknown";
  var pushRepairTried = false;

  function checkPushReach() {
    try {
      if (!navigator.serviceWorker || !navigator.serviceWorker.ready) return;
      navigator.serviceWorker.ready.then(function (reg) {
        return reg.pushManager.getSubscription();
      }).then(function (sub) {
        if (!sub) return null;          // null = the browser holds nothing
        return apiPost("/api/push/status", { endpoint: sub.endpoint });
      }).then(function (r) {
        pushReach = r === null ? "missing"
                  : !r ? "unknown"
                  : r.active ? "ok"
                  : r.known ? "dead" : "missing";
        paint();
        if (pushReach !== "ok" && pushReach !== "unknown") repairPush();
      }).catch(function () { /* leave it unknown rather than guess */ });
    } catch (e) { /* no service worker here */ }
  }

  /* A STALE REGISTRATION NOW REPAIRS ITSELF INSTEAD OF ACCUSING THE DEVICE.
     The browser can replace or revoke a push subscription whenever it
     likes, and until the service worker learned to say so
     (`pushsubscriptionchange`) the server only found out on the next full
     page LOAD. An app left open for a day therefore drifted into "this
     device is not registered" and stayed there, with a button as the only
     way out — for something the page can simply fix.

     Never prompts: healSubscription() acts only on an already granted
     permission, so on a device that has not been asked this does nothing,
     and the panel keeps offering the button that does ask. Once per page,
     because if the repair itself does not take, repeating it every time
     the panel opens just hides the failure. */
  function repairPush() {
    if (pushRepairTried) return;
    pushRepairTried = true;
    if (typeof Notification === "undefined" ||
        Notification.permission !== "granted") return;
    if (!window.ClPush || !window.ClPush.healSubscription) return;
    try {
      var h = window.ClPush.healSubscription();
      if (h && h.then) h.then(function () { checkPushReach(); })
                        .catch(function () {});
    } catch (e) { /* nothing to lose: the button is still there */ }
  }

  /* ── REMINDER NOTIFICATIONS ─────────────────────────────────────────
     Separate from the spoken announcements above: these are push
     notifications that arrive with the app closed, and until now they had
     one switch for all of them, in Settings. Silencing a single item meant
     deleting its reminder times — a delete dressed up as a mute, because
     the times themselves were gone.

     Loaded only when the dialog opens. This file runs on every page and
     must not add a request to every page load. */
  var mutes = null, mutesState = "idle", editingMuteId = null;

  function loadMutes() {
    if (mutesState === "loading" || mutesState === "done") return;
    mutesState = "loading";
    paintMutes();
    fetch("/api/checklist/mutes", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        mutes = (j && j.items) || [];
        mutesState = "done";
        paintMutes();
      })
      .catch(function () {
        mutesState = "failed";
        paintMutes();
      });
  }

  function paintMutes() {
    var ul = pop && pop.querySelector("[data-ta-mutes]");
    if (!ul) return;
    if (mutesState === "loading") {
      ul.innerHTML = '<li class="ta-empty">Loading your reminders\u2026</li>';
      return;
    }
    if (mutesState === "failed") {
      ul.innerHTML = '<li class="ta-empty">Could not load your reminders.</li>';
      return;
    }
    if (!mutes || !mutes.length) {
      ul.innerHTML = '<li class="ta-empty">No checklist items have reminder ' +
                     'times yet. Add one on the Checklist page and it will ' +
                     'appear here.</li>';
      return;
    }
    ul.innerHTML = mutes.map(function (m) {
      if (m.id === editingMuteId) {
        // EDITING THE TIMES. A text field rather than a time picker,
        // because an item can have several and the same forgiving parser
        // already handles "8, 11.30, 6pm".
        return '<li class="ta-item editing" data-mute-id="' + esc(m.id) + '">' +
               '<span class="ta-what" style="flex:0 0 auto;max-width:38%">' +
                 esc(m.name) + '</span>' +
               '<input type="text" class="ta-mute-in" data-ta-mute-times ' +
                 'value="' + esc(m.times.join(", ")) + '" ' +
                 'aria-label="Reminder times for ' + esc(m.name) + '">' +
               '<button type="button" class="ta-edit" data-ta-mute-save ' +
                 'title="Save">\u2713</button>' +
               '<button type="button" class="ta-del" data-ta-mute-cancel ' +
                 'title="Cancel">&times;</button>' +
               '</li>';
      }
      return '<li class="ta-item' + (m.muted ? " off" : "") +
             '" data-mute-id="' + esc(m.id) + '">' +
             '<button type="button" class="ta-tog" data-ta-mute ' +
               'aria-pressed="' + (m.muted ? "false" : "true") + '" ' +
               'title="' + (m.muted ? "Unmute this reminder"
                                    : "Mute this reminder") + '">' +
               (m.muted ? "\u25CB" : "\u25CF") + '</button>' +
             '<span class="ta-when"><b>' +
               esc(m.times.map(friendly).join(", ")) + '</b>' +
               '<i>' + (m.muted ? "muted" : "notifying") + '</i></span>' +
             '<span class="ta-what">' + esc(m.name) + '</span>' +
             '<button type="button" class="ta-edit" data-ta-mute-edit ' +
               'title="Edit the times">\u270E</button>' +
             '</li>';
    }).join("");
  }

  /* Save new reminder times for one checklist item.

     Goes through the EXISTING PATCH /api/checklist/items/<id>, which already
     diffs the desired times against the stored rows, preserves ticks for
     times that survive, and keeps the legacy single-time column in step.
     Reimplementing any of that here would be a second source of truth for
     the same data, and the two would drift. */
  function saveMuteTimes(id, raw) {
    var row = null;
    for (var i = 0; i < (mutes || []).length; i++) {
      if (mutes[i].id === id) { row = mutes[i]; break; }
    }
    if (!row) return;

    var times = parseTimes(raw);
    if (!times.length) {
      note(false, "I could not read \u201c" + raw + "\u201d as any times");
      return;
    }
    var before = row.times.slice();
    row.times = times;
    editingMuteId = null;
    paintMutes();
    savedFlash();

    fetch("/api/checklist/items/" + encodeURIComponent(id), {
      method: "PATCH",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify({ reminder_times: times }),
    }).then(function (r) {
      if (r.ok) return;
      throw new Error("save failed");
    }).catch(function () {
      row.times = before;          // put it back rather than lie
      paintMutes();
      note(false, "could not save those reminder times");
    });
  }

  function toggleMute(id) {
    var row = null;
    for (var i = 0; i < (mutes || []).length; i++) {
      if (mutes[i].id === id) { row = mutes[i]; break; }
    }
    if (!row) return;
    var want = !row.muted;
    row.muted = want;              // optimistic, so the switch feels instant
    paintMutes();
    savedFlash();
    fetch("/api/checklist/mutes/" + encodeURIComponent(id), {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify({ muted: want }),
    }).then(function (r) {
      if (r.ok) return null;
      return r.json().catch(function () { return {}; });
    }).then(function (err) {
      if (!err) return;
      // PUT IT BACK. A switch that looks saved and is not is worse than one
      // that visibly fails.
      row.muted = !want;
      paintMutes();
      note(false, err.error || "could not save that mute");
    }).catch(function () {
      row.muted = !want;
      paintMutes();
      note(false, "could not reach the server to save that mute");
    });
  }

  function csrfToken() {
    var m = document.querySelector('meta[name=csrf-token]');
    return m ? m.getAttribute("content") : "";
  }

  function byId(id) {
    for (var i = 0; i < state.items.length; i++) {
      if (state.items[i].id === id) return state.items[i];
    }
    return null;
  }

  /* Load an existing announcement back into the form. */
  function startEdit(id) {
    var it = byId(id);
    if (!it) return;
    editingId = id;
    newDays = (it.days || []).slice();
    newMer = { at: "am", until: "am" };   // the stored times are 24-hour
    pop.querySelector("[data-ta-new-at]").value = it.at;
    pop.querySelector("[data-ta-new-until]").value = it.until || "";
    pop.querySelector("[data-ta-new-mins]").value = it.mins || "";
    pop.querySelector("[data-ta-new-repeat]").value = it.repeat || "daily";
    pop.querySelector("[data-ta-new-start]").value = it.start || todayYMD();
    pop.querySelector("[data-ta-new-end]").value = it.end || "";
    pop.querySelector("[data-ta-new-text]").value = it.text || "";
    // OPEN THE ADVANCED BLOCK if this announcement uses any of it —
    // otherwise editing shows a form whose visible fields do not account
    // for what the row displays, which reads as a bug.
    var usesAdvanced = !!(it.until || it.mins || it.end ||
                          (it.repeat !== "daily" && it.repeat !== "once"));
    var adv = pop.querySelector("[data-ta-advanced]");
    var mb = pop.querySelector("[data-ta-more]");
    if (adv && usesAdvanced) {
      adv.hidden = false;
      if (mb) mb.setAttribute("aria-expanded", "true");
    }
    openForm();
    paint();
    var f = pop.querySelector("[data-ta-new-at]");
    if (f) { f.focus(); f.select(); }
  }

  function cancelEdit() {
    editingId = null;
    newDays = [];
    newMer = { at: "am", until: "am" };
    ["at", "until", "mins", "text", "end"].forEach(function (k) {
      var el = pop.querySelector("[data-ta-new-" + k + "]");
      if (el) el.value = "";
    });
    var st = pop.querySelector("[data-ta-new-start]");
    if (st) st.value = todayYMD();
    var rp = pop.querySelector("[data-ta-new-repeat]");
    if (rp) rp.value = "daily";
    paint();
  }

  function addItem() {
    var atEl = pop.querySelector("[data-ta-new-at]");
    var uEl = pop.querySelector("[data-ta-new-until]");
    var mEl = pop.querySelector("[data-ta-new-mins]");
    var rEl = pop.querySelector("[data-ta-new-repeat]");
    var sEl = pop.querySelector("[data-ta-new-start]");
    var eEl = pop.querySelector("[data-ta-new-end]");
    var tEl = pop.querySelector("[data-ta-new-text]");
    // Reuse the forgiving parser, so "5.00" and "6.45pm" work here too.
    var times = parseTimes(atEl.value, newMer.at);
    if (!times.length) {
      atEl.setAttribute("aria-invalid", "true");
      atEl.focus();
      note(false, "I could not read \u201c" + atEl.value + "\u201d as a time");
      return;
    }
    atEl.removeAttribute("aria-invalid");

    // The daily window. Same forgiving parser, so "8pm" works here too.
    var until = null;
    if ((uEl.value || "").trim()) {
      var u = parseTimes(uEl.value, newMer.until);
      if (!u.length) {
        uEl.setAttribute("aria-invalid", "true");
        note(false, "I could not read \u201c" + uEl.value + "\u201d as a time");
        return;
      }
      until = u[0];
      if (hhmmToMins(until) < hhmmToMins(times[0])) {
        uEl.setAttribute("aria-invalid", "true");
        note(false, "the end time is before the start time");
        return;
      }
    }
    uEl.removeAttribute("aria-invalid");

    var stepMins = parseInt(mEl.value, 10);
    stepMins = stepMins > 0 ? Math.min(720, stepMins) : 0;
    // A window with no interval would speak once and ignore the window, and
    // an interval with no window would run to midnight. Neither is what
    // anyone means, so ask rather than guess.
    if (until && !stepMins) {
      note(false, "add how often to repeat between those times");
      return;
    }
    if (stepMins && !until) {
      note(false, "add a time to repeat until");
      return;
    }

    var repeat = REPEATS.indexOf(rEl.value) === -1 ? "daily" : rEl.value;
    var start = isYMD(sEl.value) ? sEl.value : todayYMD();
    /* A ONE-OFF IN THE PAST CAN NEVER FIRE. Belt and braces for the field
       above: a stale value, a page open across midnight, or a date typed by
       hand all produce a row that looks armed and is not — the same trap
       the end-date check below exists to prevent. A repeating rule is left
       alone: "every week since March" is a legitimate thing to say. */
    if (repeat === "once" && start < todayYMD()) start = todayYMD();
    var end = isYMD(eEl.value) ? eEl.value : null;
    // AN END BEFORE THE START would never fire, so refuse it rather than
    // creating a row that looks armed and is not.
    if (end && end < start) {
      eEl.setAttribute("aria-invalid", "true");
      note(false, "the end date is before the start date");
      return;
    }
    eEl.removeAttribute("aria-invalid");
    // "Chosen days" with nothing chosen is the same trap.
    if (repeat === "custom" && !newDays.length) {
      note(false, "pick at least one day");
      return;
    }
    var text = (tEl.value || "").slice(0, 120);
    // A field accepting several times adds several announcements rather than
    // quietly keeping the first — the parser already returns a list.
    if (editingId) {
      // EDITING replaces one announcement in place, keeping its id so the
      // server sees an update rather than a delete plus an insert — and
      // keeping its on/off state, which is not part of this form.
      var was = byId(editingId);
      var updated = {
        id: editingId, at: times[0], until: until, mins: stepMins,
        repeat: repeat, days: newDays.slice(),
        start: start, end: end, text: text,
        on: was ? was.on : true,
      };
      state.items = state.items.map(function (x) {
        return x.id === editingId ? updated : x;
      });
      // Its slots have moved, so yesterday's "already said" marks are about
      // times that may no longer exist.
      delete state.said[editingId];
      editingId = null;
      state.lastSlot = null;
      save(); paint(); savedFlash();
      closeForm();
      pushItems([updated]);
      atEl.value = ""; uEl.value = ""; mEl.value = ""; tEl.value = "";
      newDays = [];
      newMer = { at: "am", until: "am" };
      paint();
      return;
    }

    times.forEach(function (t) {
      state.items.push({
        id: newId(), at: t, until: until, mins: stepMins,
        repeat: repeat, days: newDays.slice(),
        start: start, end: end, text: text, on: true,
      });
    });
    atEl.value = ""; uEl.value = ""; mEl.value = ""; tEl.value = "";
    newMer = { at: "am", until: "am" };
    state.lastSlot = null;
    save(); paint(); savedFlash();
    closeForm();
    pushItems(state.items.slice(-times.length));
    atEl.focus();
  }

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;",
               '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function buildPop() {
    backdrop = document.createElement("div");
    backdrop.className = "ta-backdrop";
    backdrop.hidden = true;
    document.body.appendChild(backdrop);

    pop = document.createElement("div");
    pop.className = "ta-pop";
    pop.hidden = true;
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-modal", "true");
    pop.setAttribute("aria-label", "Announce the time");
    /* ── LAYOUT ────────────────────────────────────────────────────
       This panel grew one control at a time until it was a single
       scroll of eleven unrelated things, which is what "the UX is not
       friendly" meant. It is now four TABS, because the four groups are
       used at completely different frequencies:

         Announcements — the thing you actually came here to do
         Clock         — set once, changed rarely
         Reminders     — the push notifications, occasionally muted
         Device        — keep-alive and diagnostics, touched almost never

       What stays OUTSIDE the tabs is what must always be reachable and
       always visible: the master Start/Pause/Stop, and one line stating
       what is currently saved and running. Those are the two things you
       open this panel to check. */
    /* ── LAYOUT, REBUILT ───────────────────────────────────────────
       This panel accumulated one control at a time across a day and
       ended up showing everything at once: three status lines, four
       tabs, a seven-field form and eight paragraphs of explanation.

       The rebuild follows one rule — SHOW THE LIST, HIDE EVERYTHING
       ELSE. Opening this panel is almost always about seeing or changing
       an announcement, so that is the only thing visible by default.

         * The add form is behind "+ New", so the resting state is a list
           rather than a form you did not ask for.
         * Settings become collapsed rows that state their VALUE on the
           right, so you can read the setting without opening it. That is
           what tabs could not do: a tab hides its contents completely,
           so you had to open all four to see what was configured.
         * Diagnostics move out of settings entirely. They answer "why did
           nothing happen", which is a different question from "what
           should happen", and mixing them is most of why this felt
           cluttered.
         * Prose is cut to labels. What survives sits inside the section
           it explains, not above it. */
    pop.innerHTML =
      '<button type="button" class="ta-x" data-ta-close ' +
        'aria-label="Close">&times;</button>' +
      '<h4>Announce the time <span class="ta-saved" data-ta-saved></span></h4>' +

      '<div class="ta-row">' +
        '<button type="button" data-ta-mode="on">Start</button>' +
        '<button type="button" data-ta-mode="paused">Pause</button>' +
        '<button type="button" data-ta-mode="off">Stop</button>' +
      '</div>' +
      '<p class="ta-now" data-ta-now></p>' +
      '<p class="ta-idle" data-ta-idle hidden></p>' +
      '<p class="ta-warn" hidden>This browser needs one tap on the page ' +
        'before it will speak.</p>' +

      /* ── the list, always visible ─────────────────────────────── */
      '<div class="ta-pane" data-ta-pane="items">' +
        '<div class="ta-sec-row">' +
          '<span class="ta-sec">Your announcements</span>' +
          '<button type="button" class="ta-new" data-ta-new>+ New</button>' +
        '</div>' +
        '<ul class="ta-list" data-ta-list></ul>' +

        '<div class="ta-add" data-ta-form hidden>' +
          '<div class="ta-add-row">' +
            /* LABELLED "Start", because it is the same value "Until" is
               measured from. Unlabelled it read as the only time on the
               form, so the window in the advanced pane looked like an end
               with no beginning — reported as "like until, user should be
               allowed to enter start". There is deliberately NOT a second
               start field down there: one value with two inputs is how
               the recurrence rule ended up in two places. */
            /* A <span>, NOT a <label>. A label must not contain
               interactive content, and when it does the browser hands the
               click to the labelled input instead of to the button — so
               AM/PM took the tap and never lit up. The input keeps its own
               aria-label, so nothing is lost by not being a real label. */
            '<span class="ta-dt">Start' +
              '<span class="ta-timefld">' +
                '<input type="text" data-ta-new-at placeholder="5.00" ' +
                  'aria-label="Start time">' +
                '<span class="ta-ampm" role="group" aria-label="Morning or afternoon">' +
                  '<button type="button" data-ta-mer="at" data-v="am">AM</button>' +
                  '<button type="button" data-ta-mer="at" data-v="pm">PM</button>' +
                '</span>' +
              '</span>' +
            '</span>' +
            '<select data-ta-new-repeat aria-label="How often">' +
              '<option value="daily">Every day</option>' +
              '<option value="once">Once</option>' +
              '<option value="weekly">Every week</option>' +
              '<option value="monthly">Every month</option>' +
              '<option value="yearly">Every year</option>' +
              '<option value="custom">Chosen days</option>' +
            '</select>' +
          '</div>' +
          '<div class="ta-days" data-ta-days hidden>' +
            [0, 1, 2, 3, 4, 5, 6].map(function (d) {
              return '<button type="button" data-ta-day="' + d + '">' +
                     DAY_NAMES[d] + '</button>';
            }).join("") +
          '</div>' +
          '<div class="ta-add-row">' +
            '<input type="text" data-ta-new-text maxlength="120" ' +
              'placeholder="What to say" aria-label="What to say">' +
          '</div>' +
          '<small class="ta-preview" data-ta-preview></small>' +
          '<button type="button" class="ta-more" data-ta-more ' +
            'aria-expanded="false">Repeat through the day, or set dates</button>' +
          '<div data-ta-advanced hidden>' +
            '<div class="ta-add-row">' +
              '<span class="ta-dt">Until (from Start, above)' +
                '<span class="ta-timefld">' +
                  '<input type="text" data-ta-new-until placeholder="8.00" ' +
                    'aria-label="Repeat until">' +
                  '<span class="ta-ampm" role="group" aria-label="Morning or afternoon">' +
                    '<button type="button" data-ta-mer="until" data-v="am">AM</button>' +
                    '<button type="button" data-ta-mer="until" data-v="pm">PM</button>' +
                  '</span>' +
                '</span></span>' +
              '<label class="ta-dt">Every' +
                '<input type="number" min="0" max="720" step="5" ' +
                'data-ta-new-mins placeholder="60 min"></label>' +
            '</div>' +
            '<div class="ta-add-row">' +
              '<label class="ta-dt">First date' +
                '<input type="date" data-ta-new-start></label>' +
              '<label class="ta-dt">Last date' +
                '<input type="date" data-ta-new-end></label>' +
            '</div>' +
          '</div>' +
          '<div class="ta-add-row ta-actions">' +
            '<button type="button" data-ta-add>Add</button>' +
            '<button type="button" data-ta-cancel>Cancel</button>' +
          '</div>' +
        '</div>' +
      '</div>' +

      /* ── collapsed settings, each showing its value ───────────── */
      '<details class="ta-fold" data-ta-pane="clock">' +
        '<summary>Repeating clock<b data-ta-sum-clock></b></summary>' +
        '<p>Says the time on the clock &mdash; :00, :15, :30 &mdash; not ' +
        'from when you pressed Start.</p>' +
        '<div class="ta-int"><span>Every</span>' +
          INTERVALS.map(function (n) {
            return '<button type="button" data-ta-every="' + n + '">' + n + 'm</button>';
          }).join("") +
          '<button type="button" data-ta-custom>Custom</button>' +
        '</div>' +
        '<div class="ta-fld" data-ta-customrow hidden>' +
          '<label>Minutes between announcements' +
          '<input type="number" min="0" max="' + MAX_EVERY + '" step="1" ' +
          'data-ta-every-in placeholder="e.g. 20"></label>' +
          '<small>0 turns the repeating clock off.</small>' +
        '</div>' +
        '<div class="ta-fld">' +
          '<label>Say this first' +
          '<input type="text" maxlength="60" data-ta-label ' +
          'placeholder="e.g. Stand up and stretch"></label>' +
        '</div>' +
      '</details>' +

      '<details class="ta-fold" data-ta-pane="notify">' +
        '<summary>Reminder notifications<b data-ta-sum-notify></b></summary>' +
        '<p>Your checklist reminders. Muting one keeps its times.</p>' +
        '<ul class="ta-list" data-ta-mutes></ul>' +
      '</details>' +

      '<details class="ta-fold" data-ta-pane="device">' +
        '<summary>Sound &amp; this device<b data-ta-sum-device></b></summary>' +
        '<p class="ta-perm" data-ta-perm></p>' +
        '<label class="ta-keep"><input type="checkbox" data-ta-chime> ' +
          'Play a chime with every announcement</label>' +
        '<label class="ta-keep"><input type="checkbox" data-ta-keep> ' +
          'Keep going when minimised or locked</label>' +
        '<p class="ta-note">The chime is the only sound that reaches a ' +
        'locked screen on some phones. Keeping the app going is what lets ' +
        'anything happen at all once the screen is off; it only holds while ' +
        'announcements are running, and costs a little battery while it ' +
        'does. Nothing is spoken once the app is fully closed &mdash; ' +
        'notifications still arrive.</p>' +
        '<p class="ta-tip" hidden>You are running the installed app &mdash; ' +
        'leave the second box ticked or the system will freeze it.</p>' +
        '<div class="ta-row"><button type="button" data-ta-test>Test the sound</button></div>' +
      '</details>' +

      '<details class="ta-fold" data-ta-pane="diag">' +
        '<summary>Diagnostics<b data-ta-build-sum></b></summary>' +
        '<p class="ta-health" data-ta-health></p>' +
        '<p class="ta-health" data-ta-hold></p>' +
        '<p class="ta-health" data-ta-say></p>' +
        '<p class="ta-health" data-ta-fire></p>' +
        '<div class="ta-row"><button type="button" data-ta-diag>' +
          'Why is a device not receiving?</button></div>' +
        '<p class="ta-health" data-ta-diagout hidden></p>' +
        '<p class="ta-build" data-ta-build></p>' +
        '<p class="ta-auto">Everything saves as you type.</p>' +
      '</details>';

    document.body.appendChild(pop);

    pop.addEventListener("click", function (ev) {
      // Anything handled in here is by definition an inside click. Saying so
      // explicitly means the outside-click handler above never has to reason
      // about a node this function may be about to remove.
      if (ev.target.closest("button, input, label")) ev.stopPropagation();

      if (ev.target.closest("[data-ta-close]")) { closePanel(); return; }
      var m = ev.target.closest("[data-ta-mode]");
      if (m) {
        state.mode = m.getAttribute("data-ta-mode");
        // Starting IS the gesture, so speak a confirmation — it also proves
        // to the user that sound works before they walk away from the desk.
        if (state.mode === "on") {
          armed = true;
          try { unlockAudio(); } catch (e) {}
          speak(phrase(new Date()));
        }
        applyMode();
        savedFlash();
        return;
      }
      if (ev.target.closest("[data-ta-perm-on]")) {
        // Goes through the app's own push module, so the subscription is
        // registered exactly the way Settings does it.
        try {
          if (window.ClPush && window.ClPush.subscribe) {
            window.ClPush.subscribe()
              .then(function () {
                pushReach = "unknown";
                checkPushReach();
                paint(); savedFlash();
              })
              .catch(function (e) {
                // "permission denied" on its own is unhelpful and, when the
                // browser has actually BLOCKED the site, actively wrong —
                // there is nothing to press again. Re-read the permission
                // so the panel switches to the state it is really in, which
                // carries the unblock instructions.
                var msg = (e && e.message) || "could not turn on notifications";
                if (typeof Notification !== "undefined" &&
                    Notification.permission === "denied") {
                  msg = "your browser has BLOCKED notifications for this " +
                        "site \u2014 unblock them in the browser\u2019s site " +
                        "settings; this app cannot ask again once blocked";
                } else if (/denied/i.test(msg)) {
                  msg = "the permission prompt was dismissed \u2014 press " +
                        "again and choose Allow";
                }
                note(false, msg);
                pushReach = "unknown";
                paint();
              });
          } else {
            note(false, "the notifications module has not loaded");
          }
        } catch (e) { note(false, "could not turn on notifications"); }
        return;
      }
      var ch = ev.target.closest("[data-ta-chime]");
      if (ch) {
        state.chime = !!ch.checked;
        save(); paint(); savedFlash();
        // Playing it here is not only a confirmation: this is the GESTURE
        // that unlocks the shared audio element, without which a locked
        // phone can never play anything through it.
        if (state.chime) { armed = true; try { unlockAudio(); } catch (e) {} playChime(); }
        return;
      }
      var k = ev.target.closest("[data-ta-keep]");
      if (k) {
        state.keepalive = !!k.checked;
        // From here on this device, the choice is the user's and the
        // default no longer applies.
        state.keepaliveSet = true;
        applyKeepalive();
        save();
        paint();
        savedFlash();
        return;
      }
      var e = ev.target.closest("[data-ta-every]");
      if (e) {
        state.every = parseInt(e.getAttribute("data-ta-every"), 10) || 15;
        state.lastSlot = null;
        applyMode();
        savedFlash();
        pushSettings();
        return;
      }
      if (ev.target.closest("[data-ta-custom]")) {
        var row = pop.querySelector("[data-ta-customrow]");
        if (row) row.hidden = false;
        var inp = pop.querySelector("[data-ta-every-in]");
        if (inp) { inp.value = state.every; inp.focus(); inp.select(); }
        return;
      }
      var tog = ev.target.closest("[data-ta-toggle]");
      if (tog) {
        var li = tog.closest("[data-id]");
        var it = byId(li && li.getAttribute("data-id"));
        if (it) {
          it.on = !it.on;
          save(); paint(); savedFlash();
          pushItems([it]);
        }
        return;
      }
      var edt = ev.target.closest("[data-ta-edit]");
      if (edt) {
        var erow = edt.closest("[data-id]");
        if (erow) startEdit(erow.getAttribute("data-id"));
        return;
      }
      if (ev.target.closest("[data-ta-cancel]")) {
        cancelEdit(); closeForm(); return;
      }
      var del = ev.target.closest("[data-ta-del]");
      if (del) {
        var li2 = del.closest("[data-id]");
        var id = li2 && li2.getAttribute("data-id");
        state.items = state.items.filter(function (x) { return x.id !== id; });
        delete state.said[id];
        save(); paint(); savedFlash();
        if (id) pushDelete(id);
        return;
      }
      var me = ev.target.closest("[data-ta-mute-edit]");
      if (me) {
        var mer0 = me.closest("[data-mute-id]");
        editingMuteId = mer0 ? mer0.getAttribute("data-mute-id") : null;
        paintMutes();
        var f = pop.querySelector("[data-ta-mute-times]");
        if (f) { f.focus(); f.select(); }
        return;
      }
      if (ev.target.closest("[data-ta-mute-cancel]")) {
        editingMuteId = null;
        paintMutes();
        return;
      }
      var ms = ev.target.closest("[data-ta-mute-save]");
      if (ms) {
        var msr = ms.closest("[data-mute-id]");
        var fld = pop.querySelector("[data-ta-mute-times]");
        if (msr && fld) saveMuteTimes(msr.getAttribute("data-mute-id"), fld.value);
        return;
      }
      if (ev.target.closest("[data-ta-new]")) { openForm(); return; }
      if (ev.target.closest("[data-ta-more]")) {
        var adv = pop.querySelector("[data-ta-advanced]");
        var mb = pop.querySelector("[data-ta-more]");
        adv.hidden = !adv.hidden;
        mb.setAttribute("aria-expanded", adv.hidden ? "false" : "true");
        return;
      }
      var mu = ev.target.closest("[data-ta-mute]");
      if (mu) {
        var mrow = mu.closest("[data-mute-id]");
        if (mrow) toggleMute(mrow.getAttribute("data-mute-id"));
        return;
      }
      var mer = ev.target.closest("[data-ta-mer]");
      if (mer) {
        newMer[mer.getAttribute("data-ta-mer")] = mer.getAttribute("data-v");
        paintMer();
        return;
      }
      var day = ev.target.closest("[data-ta-day]");
      if (day) {
        var d = parseInt(day.getAttribute("data-ta-day"), 10);
        var at = newDays.indexOf(d);
        if (at === -1) newDays.push(d); else newDays.splice(at, 1);
        paintDayChips();
        return;
      }
      if (ev.target.closest("[data-ta-add]")) { addItem(); return; }
      if (ev.target.closest("[data-ta-diag]")) {
        var outEl = pop.querySelector("[data-ta-diagout]");
        outEl.hidden = false;
        outEl.className = "ta-health";
        outEl.textContent = "Asking the push service\u2026";
        apiPost("/api/push/diagnose", {}).then(function (r) {
          if (!r || !r.ok) {
            outEl.className = "ta-health bad";
            outEl.textContent = (r && r.note) || "Could not run the check.";
            return;
          }
          if (!r.results.length) {
            outEl.className = "ta-health bad";
            outEl.textContent = r.note || "No devices are registered.";
            return;
          }
          // One line per registration, worst first — the reason a phone is
          // silent is the line that failed, and it must not be buried under
          // the ones that worked.
          var rows = r.results.slice().sort(function (a, b) {
            return (a.status === 201 ? 1 : 0) - (b.status === 201 ? 1 : 0);
          });
          var ok = rows.filter(function (x) { return x.status === 201; }).length;
          outEl.className = "ta-health " + (ok === rows.length ? "good" : "bad");
          outEl.innerHTML = rows.map(function (x) {
            return "<b>" + x.device + "</b> \u2026" + x.tail +
                   (x.was_active ? "" : " (retired)") + " \u2014 " +
                   (x.status === 201 ? "\u2713 " : "\u26a0 ") +
                   x.outcome + (x.status ? " [" + x.status + "]" : "") +
                   (x.detail ? "<br><small>" + x.detail + "</small>" : "");
          }).join("<br>");
        }).catch(function () {
          outEl.className = "ta-health bad";
          outEl.textContent = "Could not reach the server.";
        });
        return;
      }
      if (ev.target.closest("[data-ta-test]")) {
        // Pressing it IS the gesture, so this is also the way to re-arm a
        // page that has not been touched yet.
        armed = true;
        try { unlockAudio(); } catch (e) {}
        note(null, "");
        playChime();
        speak(phrase(new Date()));
        return;
      }
    });

    /* The three text fields. Committed on input rather than on a Save
       button — there is nothing here worth a round trip to confirm, and a
       setting that needs saving is a setting people forget to save. */
    pop.addEventListener("keydown", function (ev) {
      if (ev.key !== "Enter") return;
      if (ev.target.closest("[data-ta-mute-times]")) {
        ev.preventDefault();
        var mr = ev.target.closest("[data-mute-id]");
        if (mr) saveMuteTimes(mr.getAttribute("data-mute-id"), ev.target.value);
        return;
      }
      if (ev.target.closest("[data-ta-new-at],[data-ta-new-until]," +
                            "[data-ta-new-mins],[data-ta-new-text]")) {
        ev.preventDefault();
        addItem();
      }
    });

    pop.addEventListener("change", function (ev) {
      if (ev.target.matches("[data-ta-new-repeat]")) paintDayChips();
    });

    pop.addEventListener("input", function (ev) {
      var n = ev.target;
      if (n.matches("[data-ta-new-at],[data-ta-new-until],[data-ta-new-mins]")) {
        paintMer();
        return;
      }
      if (n.matches("[data-ta-every-in],[data-ta-label]")) savedFlash();
      if (n.matches("[data-ta-every-in]")) {
        var v = parseInt(n.value, 10);
        if (!(v >= 0)) return;
        state.every = Math.min(MAX_EVERY, v);
        state.lastSlot = null;
        save();
        paint();
        pushSettingsSoon();
        return;
      }
      if (n.matches("[data-ta-label]")) {
        state.label = n.value.slice(0, 60);
        save();
        pushSettingsSoon();
      }
    });
  }

  /* A modal is CENTRED, so there is no anchoring arithmetic left — the old
     place() positioned it under the button, which is a popover's job. */
  //: Which tab is showing. Not persisted: opening this panel is nearly
  //: always about the announcements, so that is where it should start
  //: however you left it last time.
  var tab = "items";

  /* The form is hidden until asked for, so the resting state of this
     panel is a LIST rather than a form nobody requested. */
  function openForm() {
    var f = pop.querySelector("[data-ta-form]");
    var nb = pop.querySelector("[data-ta-new]");
    if (f) f.hidden = false;
    if (nb) nb.hidden = true;
    /* ── THE DATE MUST BE TODAY'S TODAY, NOT THE PAGE'S ────────────────
       This filled the field only when it was EMPTY, so it was stamped once
       per page load and kept forever. Leave the app open across midnight —
       which is exactly what an announcements page left open on a bedside
       phone does — and every new one-off is dated YESTERDAY.

       A "once" announcement matches only its start date, so those never
       fire, on any device, for any reason the user can see. Measured
       2026-08-24: two one-offs set at 00:48 and 00:52 both carried
       start=2026-08-23 and were skipped in silence. */
    var st = pop.querySelector("[data-ta-new-start]");
    if (st && (!st.value || st.value < todayYMD())) st.value = todayYMD();
    paint();
    var first = pop.querySelector("[data-ta-new-at]");
    if (first) { try { first.focus(); } catch (e) {} }
  }

  function closeForm() {
    var f = pop.querySelector("[data-ta-form]");
    var nb = pop.querySelector("[data-ta-new]");
    if (f) f.hidden = true;
    if (nb) nb.hidden = false;
  }

  function showTab(name) {           // kept: openPanel and startEdit call it
    if (!pop) return;
    if (name === "items") closeForm();
  }

  function openPanel() {
    backdrop.hidden = false;
    pop.hidden = false;
    document.documentElement.classList.add("ta-locked");
    try { prefetchNext(new Date()); } catch (e) {}
    try { checkPushReach(); } catch (e) {}
    showTab("items");
    paint();
    loadMutes();
    // Focus goes into the dialog, not left on the button behind it.
    var first = pop.querySelector("[data-ta-new-at]");
    if (first) { try { first.focus(); } catch (e) {} }
  }

  function closePanel() {
    pop.hidden = true;
    backdrop.hidden = true;
    document.documentElement.classList.remove("ta-locked");
    if (btn) { try { btn.focus(); } catch (e) {} }
  }

  /* Tab must not escape into the page underneath. Small enough to do by
     hand: wrap from the last focusable element back to the first. */
  function trapTab(ev) {
    if (ev.key !== "Tab" || pop.hidden) return;
    var f = pop.querySelectorAll(
      'button, input, select, textarea, [tabindex]:not([tabindex="-1"])');
    f = Array.prototype.filter.call(f, function (el) {
      return !el.disabled && el.offsetParent !== null;
    });
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (ev.shiftKey && document.activeElement === first) {
      ev.preventDefault(); last.focus();
    } else if (!ev.shiftKey && document.activeElement === last) {
      ev.preventDefault(); first.focus();
    }
  }

  function mount() {
    var host = document.querySelector(".top-context");
    if (!host || document.querySelector(".ta-btn")) return;
    inject();

    btn = document.createElement("button");
    btn.type = "button";
    btn.className = "help-btn ta-btn";
    btn.setAttribute("aria-label", "Announce the time");
    btn.innerHTML = '<i data-feather="volume-2"></i>';
    // Next to the other utility buttons, not in the page body: this is an
    // ambient setting and belongs where it is reachable from anywhere.
    var anchor = host.querySelector(".help-btn");
    if (anchor) host.insertBefore(btn, anchor);
    else host.appendChild(btn);

    buildPop();
    btn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      if (pop.hidden) openPanel(); else closePanel();
    });
    /* IT IS A MODAL, so nothing outside it closes it.
       The previous popover shut on any click that was not inside it, which
       meant a DRAG — selecting a time, dragging a number field — ended
       outside and registered as a click, closing the panel mid-edit. There
       is real editing in here now: several fields, a day picker and a list.
       That is a dialog, not a popover.

       (The detached-node guard that used to be needed here is gone with the
       listener itself; deleting a row can no longer reach anything that
       would close the panel.) */
    backdrop.addEventListener("mousedown", function (ev) {
      // Only a deliberate press ON the backdrop, not a drag that happens to
      // finish there. Kept as a convenience; the × and Escape are the real
      // ways out.
      if (ev.target === backdrop) closePanel();
    });

    // Escape closes it, which is what every panel should do and what people
    // try first.
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && !pop.hidden) closePanel();
      trapTab(ev);
    });

    if (window.feather) { try { window.feather.replace(); } catch (_) {} }
    paint();
  }

  /* The first real interaction on this document unblocks speech. Recorded
     so the control can stop warning about it. */
  ["pointerdown", "keydown"].forEach(function (evt) {
    document.addEventListener(evt, function () {
      if (armed) return;
      armed = true;
      // The page now has a gesture, so audio that was blocked can start.
      // Without this the keep-alive stays dead for the whole page load and
      // the phone hears nothing once it locks.
      try { applyKeepalive(); } catch (e) {}
      // BOTH audio elements, not just the one the chime uses. Android
      // grants the permission per ELEMENT, so the words' element has to be
      // unlocked by this same gesture or it is refused forever.
      try { unlockAudio(); } catch (e) {}
      paint();
    }, { once: true, capture: true });
  });

  /* ── STOCK UP BEFORE THE PAGE IS FROZEN ────────────────────────────
     This is the fix for "chime played, speech refused" on a locked
     Android. Going to the background is the LAST moment this page is
     reliably allowed to use the network — after that Chrome freezes its
     timers and starves its fetches, so a page that waits until the
     announcement is due to render the words will not get them. Rendering
     the next half hour here means the wake-up only has to press play on
     audio it already holds. */
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") return;
    try { prefetchWindow(new Date(), 30); } catch (e) {}
  });

  // Another tab changed the setting — follow it rather than disagreeing.
  window.addEventListener("storage", function (ev) {
    if (ev.key !== KEY) return;
    state = load();
    applyMode();
  });

  window.TimeAnnouncer = {
    start: function () { state.mode = "on"; applyMode(); },
    pause: function () { state.mode = "paused"; applyMode(); },
    stop:  function () { state.mode = "off"; state.lastSlot = null; applyMode(); },
    state: function () { return JSON.parse(JSON.stringify(state)); },
    keepalive: function (on) { state.keepalive = !!on; applyKeepalive(); save(); paint(); },
    _keptAlive: function () { return !!keepCtx; },
    _phrase: phrase,
    _slotFor: slotFor,
    _dueSlot: dueSlot,
    _dueItems: dueItems,
    _matchesOn: matchesOn,
    _slotsFor: slotsFor,
    _playChime: playChime,
    _prefetchSpeech: prefetchSpeech,
    _prefetchWindow: prefetchWindow,
    _wordsFor: wordsFor,
    _sayUrl: sayUrl,
    _timeWords: timeWords,
    _repeatWords: repeatWords,
    _isExpired: isExpired,
    _todayYMD: todayYMD,
    _parseTimes: parseTimes,
    _merApplies: merApplies,
    _load: load,
    _pullState: pullState,
    _friendly: friendly,
    _scheduleWords: scheduleWords,
    _build: function () { return BUILD; },
    _health: function () { return health; },
    _voiceFor: function (voices, lang) {
      // Exposed so the selection rule can be tested without a speech engine.
      var want = String(lang || "en").slice(0, 2).toLowerCase();
      var local = (voices || []).filter(function (x) { return x.localService; });
      return local.filter(function (x) {
        return (x.lang || "").slice(0, 2).toLowerCase() === want;
      })[0] || local.filter(function (x) { return x.default; })[0] || null;
    },
    _set: function (patch) { Object.keys(patch).forEach(function (k) {
      state[k] = patch[k]; }); },
    _check: check,
    _supported: supported,
    _isInstalled: isInstalled,
  };

  primeVoices();
  pullState();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { mount(); applyMode(); });
  } else {
    mount();
    applyMode();
  }
})();
