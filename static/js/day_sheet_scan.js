/* Day Sheet — "Scan paper sheet" (v356).
 *
 * Turns a photo (or pasted text) of a handwritten planner page into Day
 * Sheet items. NO AI API: the photo is read on the phone by Tesseract.js
 * (self-hosted in static/js/vendor/tesseract-7.0.0), or the user pastes
 * text copied from Google Lens. Nothing is added until the user has
 * reviewed every line.
 *
 * parse(text, ctx) is pure and tested in tests/js/day_sheet_scan.test.js.
 *   ctx.method: the Day Sheet planning method (top3, 135, eisenhower,
 *               ivylee, timeblock, bujo, manager)
 * Returns [{text, done, dest, kind?}] where dest is one of
 *   "top3" | "todo" | "notes" | "bucket" | "hour:HH" | "list:<key>" | "skip"
 */
(function (root) {
  'use strict';

  // Section headings people write on a paper planner -> where lines under
  // them go. A heading is a short line (no more than 5 words).
  const HEADINGS = [
    [/^(top\s*(3|three)|priorit(y|ies)|outcomes?|mits?|most important( tasks?)?|big\s*3)\b/, 'top3'],
    [/^(to[\s-]?dos?|tasks?|to do list|action items?)\b/, 'todo'],
    [/^(notes?|ideas?|remember|brain\s*dump)\b/, 'notes'],
    [/^(went well|grateful|gratitude|reflection|end of day|tomorrow|lessons?)\b/, 'notes'],
    [/^(schedule|time\s*blocks?|calendar|timeline|hourly)\b/, 'schedule'],
    [/^1\s*big\b/, 'list:big'], [/^3\s*medium\b/, 'list:medium'], [/^5\s*small\b/, 'list:small'],
    [/^(do( now| first| it)?|urgent\s*(&|and)\s*important)$/, 'list:q_do'],
    [/^(delegate|hand\s*off)\b/, 'list:q_delegate'],
    [/^(drop|delete|eliminate|don'?t do)\b/, 'list:q_drop'],
    [/^(people|1\s*[:-]?\s*1s?|one[\s-]on[\s-]ones?|follow[\s-]?ups?)\b/, 'list:people'],
    [/^quick( wins?)?\b/, 'list:quick'],
    [/^(rapid\s*log|log)\b/, 'list:log'],
    [/^(ivy\s*lee|six|6 tasks)\b/, 'list:ivy'],
  ];

  // How many lines each fixed slot takes before the rest spill to To-do,
  // when the page has no headings at all.
  const NO_HEADING_PLAN = {
    top3: [['top3', 3]], timeblock: [['top3', 3]], manager: [['top3', 3]],
    '135': [['list:big', 1], ['list:medium', 3], ['list:small', 5]],
    ivylee: [['list:ivy', 6]],
  };

  // Only longer words: a 5-letter heading like "tasks" is one edit from
  // real tasks ("masks"), so those must be read exactly.
  const FUZZY = ['schedule', 'priorities', 'to-do', 'delegate', 'people',
    'gratitude', 'grateful', 'reflection', 'timeline', 'calendar', 'outcomes'].map(w => [w]);
  function edits(a, b) {           // Levenshtein distance, small strings only
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    return d[a.length][b.length];
  }

  const DONE_MARK = /^\s*(\[\s*[xX✓✔✗]\s*\]?|\(\s*[xX✓✔]\s*\)|[☑✅✔✓☒]|[xX](?=\s))\s*/;
  // A drawn box is often misread: "[ ]", "[]", "[7", "[1", "(_)", "LI".
  const OPEN_MARK = /^\s*([\[(]\s*[^\s\])a-wyzA-WYZ]{0,2}\s*[\])|]?(?=\s)|\[\s*\]|\(\s*\)|[☐□▢○◯•·*>»→]|[-–—](?=\s)|[oO0](?=\s)|\|(?=\s)|\d{1,2}\s*[.)](?=\s))\s*/;
  const TIME = /^(\d{1,2})(?:\s*[:.]\s*(\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?)?\s*(?:[-–—:.)|]\s*)?(.*)$/i;

  function clean(s) {
    return String(s || '').replace(/[​﻿]/g, '').replace(/\s+/g, ' ').trim();
  }
  function letters(s) { return (s.match(/[A-Za-zऀ-෿]/g) || []).length; }

  function heading(line, method) {
    let t = line.toLowerCase().replace(/[:\-–—_=*#.?!]+$/, '').trim();
    if (!t || t.split(/\s+/).length > 5) return null;
    // The WHOLE line must be the heading ("Top 3 priorities", "Today's
    // schedule"), so a task like "1:1 prep" or "Do taxes" stays a task.
    t = t.replace(/^(today'?s|my|daily|what|the)\s+/, '')
         .replace(/(\s+(list|today|for today|for|tasks|items|section|priorities|to do))+$/, '').trim();
    const whole = re => { const m = t.match(re); return m && m[0].length === t.length; };
    // OCR often gets one or two letters of a heading wrong ("Sehedule",
    // "To-cdo"): one-word headings of 5+ letters match within 1-2 edits.
    const fuzzy = FUZZY.find(([w]) => t.length >= 5 && Math.abs(t.length - w.length) <= 2
      && edits(t.replace(/[\s-]/g, ''), w.replace(/[\s-]/g, '')) <= (w.length >= 8 ? 2 : 1));
    if (fuzzy) t = fuzzy[0];
    // On an Eisenhower page "Schedule" is the second quadrant.
    if (method === 'eisenhower' && whole(/^(schedule|plan|decide)/)) return 'list:q_plan';
    for (const [re, dest] of HEADINGS) if (whole(re)) return dest;
    return null;
  }

  // "9 am Standup", "14:30 review", "9.30 - gym". A bare "1." or "3)" is a
  // numbered list, not a time, unless we are under a Schedule heading.
  function timeOf(line, inSchedule) {
    const m = line.match(TIME);
    if (!m) return null;
    let h = parseInt(m[1], 10);
    const min = m[2], ap = (m[3] || '').toLowerCase().replace(/[.\s]/g, ''), rest = clean(m[4]);
    if (!rest || letters(rest) < 2) return null;
    if (!min && !ap && !inSchedule) return null;
    if (min && parseInt(min, 10) > 59) return null;
    if (ap === 'pm' && h < 12) h += 12;
    if (ap === 'am' && h === 12) h = 0;
    if (!ap && h >= 1 && h <= 6) h += 12;      // "3 call" on a day page means 3 pm
    if (h < 0 || h > 23) return null;
    return { hour: String(h).padStart(2, '0'), text: (min && min !== '00' ? `${m[1]}:${min} ` : '') + rest };
  }

  function parse(text, ctx) {
    const method = (ctx && ctx.method) || 'top3';
    const lines = String(text || '').split(/\r?\n/).map(clean).filter(Boolean);
    const out = [];
    let section = null;
    let sawHeading = false;
    for (const raw of lines) {
      const h = heading(raw, method);
      if (h) { section = h; sawHeading = true; continue; }
      if (letters(raw) < 2) continue;               // OCR noise: "|", "—", "0 )"

      let line = raw, done = false, kind;
      if (DONE_MARK.test(line)) { done = true; line = line.replace(DONE_MARK, ''); }
      else if (OPEN_MARK.test(line)) {
        const mark = line.match(OPEN_MARK)[1];
        if (/^[oO○◯]$/.test(mark)) kind = 'event';
        else if (/^[-–—]$/.test(mark)) kind = 'note';
        line = line.replace(OPEN_MARK, '');
      }
      line = clean(line);
      if (letters(line) < 2) continue;

      const t = section === 'notes' ? null : timeOf(line, section === 'schedule');
      if (t) { out.push({ text: t.text, done, dest: 'hour:' + t.hour }); continue; }

      let dest = section && section !== 'schedule' ? section : null;
      if (!dest && method === 'bujo') dest = 'list:log';
      const item = { text: line.slice(0, 300), done, dest };
      if (dest === 'list:log') item.kind = kind || 'task';
      out.push(item);
    }

    // No headings on the page: fill the method's slots in order, then To-do.
    const plan = !sawHeading && NO_HEADING_PLAN[method];
    let slot = 0, used = 0;
    for (const it of out) {
      if (it.dest) continue;
      if (plan) {
        while (plan[slot] && used >= plan[slot][1]) { slot++; used = 0; }
        if (plan[slot]) { it.dest = plan[slot][0]; used++; continue; }
      }
      it.dest = 'todo';
    }
    return out;
  }

  const api = { parse, timeOf, heading };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.DSScan = Object.assign(root.DSScan || {}, api);
})(typeof window !== 'undefined' ? window : this);

/* ── Browser part: OCR and image handling ─────────────────────────────── */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  const BASE = '/static/js/vendor/tesseract-7.0.0';

  function loadScript(src) {
    return new Promise((ok, bad) => {
      if (window.Tesseract) return ok();
      const s = document.createElement('script');
      s.src = src; s.onload = ok; s.onerror = () => bad(new Error('Could not load the reader'));
      document.head.appendChild(s);
    });
  }

  function loadImage(file) {
    return new Promise((ok, bad) => {
      const url = URL.createObjectURL(file), img = new Image();
      img.onload = () => { URL.revokeObjectURL(url); ok(img); };
      img.onerror = () => { URL.revokeObjectURL(url); bad(new Error('That file is not an image this browser can open')); };
      img.src = url;
    });
  }

  function draw(img, maxSide, gray) {
    const scale = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
    const c = document.createElement('canvas');
    c.width = Math.round(img.naturalWidth * scale); c.height = Math.round(img.naturalHeight * scale);
    const g = c.getContext('2d');
    g.drawImage(img, 0, 0, c.width, c.height);
    if (gray) {
      // Grey + stretched contrast: pen strokes darker, paper and shadows
      // lighter. Helps Tesseract a lot on phone photos.
      const d = g.getImageData(0, 0, c.width, c.height), p = d.data;
      let lo = 255, hi = 0;
      const lum = new Uint8ClampedArray(p.length / 4);
      for (let i = 0, j = 0; i < p.length; i += 4, j++) {
        const v = 0.299 * p[i] + 0.587 * p[i + 1] + 0.114 * p[i + 2];
        lum[j] = v; if (v < lo) lo = v; if (v > hi) hi = v;
      }
      const span = Math.max(1, hi - lo);
      for (let i = 0, j = 0; i < p.length; i += 4, j++) {
        let v = (lum[j] - lo) * 255 / span;
        v = v > 170 ? 255 : v < 90 ? 0 : (v - 90) * 255 / 80;
        p[i] = p[i + 1] = p[i + 2] = v;
      }
      g.putImageData(d, 0, 0);
    }
    return c;
  }

  // Read the photo on this device. onProgress(fraction, label).
  async function ocr(file, onProgress) {
    const img = await loadImage(file);
    await loadScript(BASE + '/tesseract.min.js');
    const prog = onProgress || (() => {});
    prog(0, 'Starting the reader');
    const worker = await window.Tesseract.createWorker('eng', 1, {
      workerPath: BASE + '/worker.min.js',
      corePath: BASE + '/core',
      langPath: BASE + '/lang',
      workerBlobURL: false,           // CSP: workers only from this site
      logger: m => {
        const label = m.status === 'recognizing text' ? 'Reading your handwriting'
          : /load|initializ/.test(m.status || '') ? 'Getting the reader ready (first time only downloads ~7 MB)' : m.status;
        prog(typeof m.progress === 'number' ? m.progress : 0, label);
      },
    });
    try {
      await worker.setParameters({ tessedit_pageseg_mode: '6', preserve_interword_spaces: '1' });
      const { data } = await worker.recognize(draw(img, 2200, true));
      return { text: data.text || '', confidence: data.confidence || 0 };
    } finally {
      worker.terminate();
    }
  }

  // A smaller JPEG to keep with the day (well under the 5 MB limit).
  async function photoBlob(file) {
    const img = await loadImage(file);
    const c = draw(img, 1600, false);
    return new Promise(ok => c.toBlob(b => ok(b), 'image/jpeg', 0.82));
  }

  window.DSScan = Object.assign(window.DSScan || {}, { ocr, photoBlob });
})();
