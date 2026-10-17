/* prep_deep.js — System design deep dives, inside the hub's System design tab.
 *
 * Three views on one tab:
 *   Deep dives  — 70 designs (the Beyz question bank's 55 prompts plus
 *                 classics from the wider canon, Uber as the flagship).
 *                 Each opens as a reader: overview and cheat sheet, the
 *                 Clarify -> Design -> Defend walkthrough, BRD, PRD, HLD,
 *                 LLD, edge cases, tech stack, every distributed-systems
 *                 concept with Q&A, trade-offs, failure modes, follow-ups,
 *                 a choose-the-best-answer quiz, and references.
 *   Concepts    — every concept across all designs, so "consistent
 *                 hashing" can be studied once and seen in each design.
 *   Quick ref   — the original 128-entry bank (prep_hub.js).
 *
 * A design has its own URL (/interview-prep/design/<slug>) so it can be
 * bookmarked and the back button works. Studied = ticked, or 80%+ on its
 * quiz; the best score is kept server-side (prep_progress, bank sddeep).
 */
(function () {
  "use strict";
  var H = function () { return window.PrepHub; };
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) { return H().esc(s); };

  var LIST = null, prog = null, started = false, mode = "deep";
  var cache = {};                      // slug -> full design
  var groupLabel = {};
  var filters = { q: "", group: "", todo: false };
  var reader = null;                   // slug being read
  var quickLoaded = false;

  /* ── Loading and routing ─────────────────────────────────────────── */
  function load() {
    if (started) { route(); return; }
    started = true;
    $("dd-view").innerHTML = '<div class="card"><div class="empty">Loading the deep dives…</div></div>';
    prog = H().makeProgress("sddeep", "sd_deep_done", null);
    Promise.all([H().api("/api/sd-deep"), prog.load()]).then(function (r) {
      LIST = r[0];
      (LIST.groups || []).forEach(function (g) { groupLabel[g.key] = g.label; });
      $("dd-n").textContent = LIST.total;
      $("sq-n").textContent = "128";
      $("dc-n").textContent = conceptIndex().length;
      // ?topic= from the Day Board names a design by title.
      var t = H().topicFromUrl();
      var hit = t && LIST.designs.find(function (d) { return d.title === t; });
      if (hit) { try { history.replaceState({ tab: "design" }, "", "/interview-prep/design/" + hit.slug); } catch (_) {} }
      route();
      // One attach for the whole view: Plan / Share / notes work on the
      // list cards and on the open design alike.
      PrepScheduler.attach($("dd-view"));
    }).catch(function () {
      $("dd-view").innerHTML = '<div class="card"><div class="empty">Couldn\'t load the deep dives.</div></div>';
    });
  }

  function slugFromPath() {
    var m = location.pathname.match(/^\/interview-prep\/design\/([a-z0-9-]+)\/?$/);
    return m ? m[1] : "";
  }

  function route() {
    if (!LIST) return;
    var slug = slugFromPath();
    if (slug) { setMode("deep", true); openReader(slug, false); }
    else { reader = null; if (mode === "deep") renderList(); }
  }

  // Lets the CSS hide the deep-dive "Select several" bar in the reader and
  // in the other two views.
  function panelState() {
    var sec = document.querySelector("[data-panel=design]");
    sec.dataset.sdmode = mode;
    sec.classList.toggle("dd-reading", !!reader);
  }

  function setMode(m, silent) {
    mode = m;
    panelState();
    document.querySelectorAll("[data-sdmode]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.dataset.sdmode === m ? "true" : "false");
    });
    $("dd-view").hidden = m !== "deep";
    $("dc-view").hidden = m !== "concepts";
    $("sd-quick").hidden = m !== "quick";
    if (silent) return;
    if (m === "quick" && !quickLoaded) { quickLoaded = true; H().loadQuick(); }
    if (m === "concepts") renderConcepts();
    if (m === "deep") {
      if (slugFromPath()) { try { history.pushState({ tab: "design" }, "", "/interview-prep/design"); } catch (_) {} }
      reader = null; renderList();
    }
  }

  document.querySelector("[data-panel=design] .seg").addEventListener("click", function (e) {
    var b = e.target.closest("[data-sdmode]");
    if (b) setMode(b.dataset.sdmode);
  });

  /* ── List ────────────────────────────────────────────────────────── */
  function badgeFor(d) {
    var best = prog.quiz && prog.quiz[d.id];
    return best != null ? '<span class="badge ' + (best >= 80 ? "mock" : "P1") + '" title="Best quiz score">quiz ' + best + "%</span>" : "";
  }

  function renderList() {
    var fw = (LIST.framework || []).map(function (s) {
      return '<div class="fw-col"><b>' + esc(s.step) + "</b><ul>" + s.points.map(function (p) {
        return "<li>" + esc(p) + "</li>"; }).join("") + "</ul></div>";
    }).join("");
    var q = filters.q.toLowerCase();
    var list = LIST.designs.filter(function (d) {
      return (!filters.group || d.group === filters.group) && (!filters.todo || !prog.done.has(d.id)) &&
        (!q || (d.title + " " + d.prompt + " " + d.summary + " " + d.concepts.join(" ")).toLowerCase().indexOf(q) >= 0);
    });
    var done = LIST.designs.filter(function (d) { return prog.done.has(d.id); }).length;
    var groups = {};
    list.forEach(function (d) { (groups[d.group] = groups[d.group] || []).push(d); });
    var html =
      '<details class="fold fw-fold"><summary>How to answer any of these: Clarify → Design → Defend</summary>' +
      '<div class="fold-body"><div class="fw-grid">' + fw + '</div><p class="mini-lbl" style="margin:10px 0 0">' +
      "Practise: pick a prompt, do a timed spoken walkthrough, then rewrite only your weakest part — the APIs, the bottleneck, or reliability.</p></div></details>" +
      '<div class="toolbar" style="margin-top:12px">' +
      '<input type="search" id="dd-search" placeholder="Search — uber, kafka, consistent hashing…" aria-label="Search deep dives" value="' + esc(filters.q) + '">' +
      '<select id="dd-group" aria-label="Group"><option value="">All groups</option>' + (LIST.groups || []).map(function (g) {
        return '<option value="' + g.key + '"' + (filters.group === g.key ? " selected" : "") + ">" + esc(g.label) + "</option>"; }).join("") + "</select>" +
      '<label class="toggle"><input type="checkbox" id="dd-todo"' + (filters.todo ? " checked" : "") + "> Not studied</label></div>" +
      '<div class="sync-note" id="dd-sync"' + (prog.available === false ? "" : " hidden") + '>Progress is saved on this device only until MIGRATION_PREP_PROGRESS.sql is run.</div>' +
      '<div class="progress-line"><span><b>' + done + "</b> of " + LIST.total + ' studied</span><span class="mini-lbl">a design counts as studied at 80%+ on its quiz, or when ticked</span>' +
      '<span class="bar"><i style="width:' + Math.round(done / LIST.total * 100) + '%"></i></span></div>' +
      '<div id="dd-list">' +
      (LIST.groups || []).filter(function (g) { return groups[g.key]; }).map(function (g) {
        return '<div class="sec-h">' + esc(g.label) + ' <span class="aside">' + groups[g.key].length + "</span></div>" +
          groups[g.key].map(card).join("");
      }).join("") + "</div>" +
      (list.length ? "" : '<div class="card"><div class="empty">No designs match.</div></div>');
    $("dd-view").innerHTML = html;
    panelState();
    if (window.feather) window.feather.replace();
  }

  function card(d) {
    var done = prog.done.has(d.id);
    return '<div class="q-card dd-card ' + (done ? "done" : "") + '" data-slug="' + d.slug + '" data-id="' + d.id + '">' +
      '<div class="q-head"><input type="checkbox" class="q-prac" ' + (done ? "checked" : "") + ' aria-label="Studied">' +
      '<a class="q-text dd-link" href="/interview-prep/design/' + d.slug + '">' + esc(d.title) + "</a>" +
      '<span class="q-meta">' + (d.slug === "uber" ? '<span class="badge P0">Flagship</span>' : "") +
      '<span class="badge">' + esc(d.difficulty) + '</span><span class="badge">' + H().hrs(d.minutes) + "</span>" + badgeFor(d) +
      PrepScheduler.button("sddeep", d.title, d.id, d.minutes) + "</span>" +
      '<p class="q-sum">' + esc(d.summary) + "</p>" +
      '<div class="dd-chips">' + d.concepts.slice(0, 5).map(function (c) {
        return '<span class="dd-chip">' + esc(c.replace(/\s*\(.*\)\s*$/, "")) + "</span>"; }).join("") +
      (d.concepts.length > 5 ? '<span class="dd-chip more">+' + (d.concepts.length - 5) + "</span>" : "") + "</div>" +
      (d.has_summary ? '<div class="dd-sum-links"><a class="btn sm" href="/interview-prep/design/' + d.slug + '/summary">📄 5-page summary</a>' +
        '<a class="btn sm ghost" href="/interview-prep/design/' + d.slug + '/summary.pdf" target="_blank" rel="noopener">PDF</a></div>' : "") +
      "</div>" +
      '<div class="q-body"></div></div>';
  }

  $("dd-view").addEventListener("input", function (e) {
    if (e.target.id === "dd-search") {
      filters.q = e.target.value;
      var pos = e.target.selectionStart;
      renderList();
      var s = $("dd-search"); s.focus(); try { s.setSelectionRange(pos, pos); } catch (_) {}
    }
  });
  $("dd-view").addEventListener("change", async function (e) {
    if (e.target.id === "dd-group") { filters.group = e.target.value; renderList(); return; }
    if (e.target.id === "dd-todo") { filters.todo = e.target.checked; renderList(); return; }
    if (e.target.classList.contains("q-prac")) {
      var c = e.target.closest(".q-card"); var on = e.target.checked;
      c.classList.toggle("done", on);
      if (!(await prog.set(c.dataset.id, on))) { e.target.checked = !on; c.classList.toggle("done", !on); }
      if (on && window.Gamify) window.Gamify.studied("ipdd:" + c.dataset.id, 60, {});
    }
  });
  $("dd-view").addEventListener("click", function (e) {
    var a = e.target.closest(".dd-link");
    var c = e.target.closest(".dd-card");
    if (a || (c && !e.target.closest("button,input,a,.prep-panel,.prep-share-panel"))) {
      if (e.metaKey || e.ctrlKey) return;
      e.preventDefault();
      openReader((a || c).closest(".dd-card").dataset.slug, true);
    }
  });

  /* ── Reader ──────────────────────────────────────────────────────── */
  var SECTIONS = [
    ["ov", "Overview"], ["fw", "Clarify · Design · Defend"], ["brd", "BRD"], ["prd", "PRD"],
    ["hld", "HLD"], ["lld", "LLD"], ["edge", "Edge cases"], ["stack", "Tech stack"],
    ["concepts", "Concepts"], ["trade", "Trade-offs"], ["fail", "Failure & metrics"],
    ["fu", "Follow-ups"], ["quiz", "Quiz"], ["refs", "References"],
  ];

  async function openReader(slug, push) {
    var meta = LIST.designs.find(function (d) { return d.slug === slug; });
    if (!meta) { renderList(); return; }
    reader = slug;
    if (push) { try { history.pushState({ tab: "design" }, "", "/interview-prep/design/" + slug); } catch (_) {} }
    $("dd-view").innerHTML = '<div class="card"><div class="empty">Opening ' + esc(meta.title) + "…</div></div>";
    window.scrollTo({ top: 0 });
    var d = cache[slug];
    if (!d) {
      try { d = cache[slug] = await H().api("/api/sd-deep/" + slug); }
      catch (e) { $("dd-view").innerHTML = '<div class="card"><div class="empty">Couldn\'t load that design.</div></div>'; return; }
    }
    if (reader !== slug) return;     // navigated away while loading
    renderReader(d, meta);
  }

  /* Text from the bank is plain, with "\n" and "  * " / "1. " list lines. */
  function para(t) { return '<div class="dd-text">' + esc(t) + "</div>"; }
  function ul(items, cls) {
    return '<ul class="dd-ul ' + (cls || "") + '">' + (items || []).map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul>";
  }
  function rows(items, a, b, la, lb) {
    return '<div class="dd-rows">' + (items || []).map(function (x) {
      return '<div class="dd-row"><div class="k">' + esc(x[a]) + '</div><div class="v">' + esc(x[b]) + "</div></div>";
    }).join("") + "</div>";
  }
  function pre(t) { return t ? '<pre class="sd-arch">' + esc(t) + "</pre>" : ""; }
  function h(id, title, inner, extra) {
    return '<section class="dd-sec" id="dd-' + id + '"><h3>' + title + (extra || "") + "</h3>" + inner + "</section>";
  }
  function qa(list, open) {
    return (list || []).map(function (x) {
      return '<details class="dd-qa"' + (open ? " open" : "") + "><summary>" + esc(x.q) + '</summary><div class="a">' + esc(x.a) + "</div></details>";
    }).join("");
  }

  function renderReader(d, meta) {
    var done = prog.done.has(meta.id);
    var best = prog.quiz && prog.quiz[meta.id];
    var fw = d.framework, brd = d.brd, prd = d.prd, hld = d.hld, lld = d.lld;
    var body = [
      h("ov", "Overview",
        '<p class="dd-prompt">' + esc(d.prompt) + "</p>" + para(d.summary) +
        '<div class="dd-keybox"><b>Say this out loud</b>' + ul(d.key_points, "kp") + "</div>"),
      h("fw", "Clarify → Design → Defend",
        '<div class="fw-grid"><div class="fw-col"><b>Clarify</b>' + ul(fw.clarify) + '</div><div class="fw-col"><b>Design</b>' + ul(fw.design) +
        '</div><div class="fw-col"><b>Defend</b>' + ul(fw.defend) + "</div></div>" +
        '<div class="dd-script"><b>Your 60–90 second opener</b>' + para(fw.script) + "</div>"),
      h("brd", "BRD — business requirements",
        '<h4>Problem</h4>' + para(brd.problem) + '<div class="dd-2"><div><h4>Goals</h4>' + ul(brd.goals) + "</div><div><h4>Non-goals</h4>" + ul(brd.non_goals) + "</div></div>" +
        "<h4>Stakeholders</h4>" + rows(brd.stakeholders, "who", "needs") +
        "<h4>Success metrics</h4>" + rows(brd.success_metrics, "metric", "target") +
        "<h4>Constraints</h4>" + ul(brd.constraints) + "<h4>Risks</h4>" + rows(brd.risks, "risk", "mitigation")),
      h("prd", "PRD — product requirements",
        "<h4>Personas</h4>" + rows(prd.personas, "name", "needs") + "<h4>User stories</h4>" + ul(prd.user_stories) +
        "<h4>Functional requirements</h4>" + ul(prd.functional) + "<h4>Non-functional requirements</h4>" + rows(prd.non_functional, "name", "target") +
        '<h4>Capacity — back of the envelope</h4><div class="dd-2"><div><b class="mini-lbl">Assumptions</b>' + ul(prd.capacity.assumptions) +
        '</div><div><b class="mini-lbl">Math</b>' + ul(prd.capacity.math, "mono") + "</div></div>" +
        '<div class="dd-callout">' + esc(prd.capacity.summary) + "</div><h4>Out of scope</h4>" + ul(prd.out_of_scope)),
      h("hld", "HLD — high-level design",
        para(hld.overview) + pre(hld.diagram) + "<h4>Components</h4>" + rows(hld.components, "name", "responsibility") +
        hld.flows.map(function (f) { return "<h4>Flow: " + esc(f.name) + '</h4><ol class="dd-ul">' + f.steps.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") + "</ol>"; }).join("") +
        "<h4>Data flow</h4>" + para(hld.data_flow)),
      h("lld", "LLD — low-level design",
        "<h4>APIs</h4>" + lld.apis.map(function (a) {
          return '<div class="dd-api"><div class="sig"><span class="m">' + esc(a.method) + "</span> " + esc(a.path) + "</div>" +
            '<div class="dd-rows"><div class="dd-row"><div class="k">Request</div><div class="v mono">' + esc(a.request) + "</div></div>" +
            '<div class="dd-row"><div class="k">Response</div><div class="v mono">' + esc(a.response) + "</div></div>" +
            (a.notes ? '<div class="dd-row"><div class="k">Notes</div><div class="v">' + esc(a.notes) + "</div></div>" : "") + "</div></div>";
        }).join("") +
        "<h4>Data model</h4>" + lld.data_model.map(function (m) {
          return '<div class="dd-api"><div class="sig">' + esc(m.entity) + ' <span class="badge">' + esc(m.store) + "</span></div>" +
            ul(m.fields, "mono") + '<div class="mini-lbl"><b>Keys:</b> ' + esc(m.keys) + "</div>" + (m.notes ? para(m.notes) : "") + "</div>";
        }).join("") +
        "<h4>Classes</h4>" + lld.classes.map(function (c) {
          return '<div class="dd-api"><div class="sig">' + esc(c.name) + "</div>" + para(c.responsibility) + ul(c.methods, "mono") + "</div>";
        }).join("") +
        "<h4>Algorithms</h4>" + lld.algorithms.map(function (a) {
          return '<div class="dd-api"><div class="sig">' + esc(a.name) + "</div>" + para(a.explain) + pre(a.pseudocode) + "</div>";
        }).join("") +
        "<h4>Sequence — the critical path</h4>" + pre(lld.sequence)),
      h("edge", "Edge cases", rows(d.edge_cases, "case", "handling"), ' <span class="n">' + d.edge_cases.length + "</span>"),
      h("stack", "Tech stack", d.tech_stack.map(function (t) {
        return '<div class="dd-api"><div class="sig">' + esc(t.name) + ' <span class="badge">' + esc(t.layer) + "</span></div>" + para(t.overview) +
          '<div class="dd-rows"><div class="dd-row"><div class="k">Why here</div><div class="v">' + esc(t.why) + '</div></div>' +
          '<div class="dd-row"><div class="k">Alternatives</div><div class="v">' + esc(t.alternatives) + "</div></div></div></div>";
      }).join("")),
      h("concepts", "Distributed-systems concepts", d.concepts.map(function (c, i) {
        return '<article class="dd-concept" id="dd-c' + i + '"><h4>' + (i + 1) + ". " + esc(c.name) + "</h4>" + para(c.explain) +
          '<div class="dd-here"><b>In this design</b>' + para(c.in_this_design) + "</div>" +
          '<div class="dd-keybox slim"><b>Key points</b>' + ul(c.key_points, "kp") + "</div>" +
          '<div class="mini-lbl" style="margin:10px 0 4px">Interview Q&amp;A — answer out loud, then open</div>' + qa(c.qa) + "</article>";
      }).join(""), ' <span class="n">' + d.concepts.length + "</span>"),
      h("trade", "Trade-offs", d.tradeoffs.map(function (t) {
        return '<div class="dd-api"><div class="sig">' + esc(t.decision) + "</div>" +
          '<div class="dd-rows"><div class="dd-row"><div class="k">Options</div><div class="v">' + esc(t.options) + "</div></div>" +
          '<div class="dd-row"><div class="k">Choice</div><div class="v"><b>' + esc(t.choice) + "</b></div></div>" +
          '<div class="dd-row"><div class="k">Why</div><div class="v">' + esc(t.why) + "</div></div></div></div>";
      }).join("")),
      h("fail", "Failure modes &amp; what to measure", rows(d.failure_modes, "failure", "behavior") + "<h4>Measure and alert on</h4>" + ul(d.metrics)),
      h("fu", "Interviewer follow-ups", '<div class="mini-lbl" style="margin-bottom:6px">Answer before you open each one.</div>' + qa(d.follow_ups)),
      h("quiz", "Quiz — choose the best answer", '<div id="dd-quiz"></div>', ' <span class="n">' + d.quiz.length + "</span>"),
      h("refs", "References &amp; further reading", '<ul class="dd-ul">' + d.references.map(function (r) {
        return '<li><a href="' + esc(r.url) + '" target="_blank" rel="noopener">' + esc(r.title) + "</a></li>"; }).join("") + "</ul>"),
    ].join("");

    $("dd-view").innerHTML =
      '<a class="dd-back" href="/interview-prep/design">← All designs</a>' +
      '<div class="q-card open dd-doc" data-id="' + meta.id + '">' +
      '<div class="q-head dd-head"><input type="checkbox" class="q-prac" ' + (done ? "checked" : "") + ' aria-label="Studied">' +
      '<h2 class="q-text">' + esc(d.title) + '</h2><span class="q-meta"><span class="badge">' + esc(groupLabel[d.group] || d.group) + "</span>" +
      '<span class="badge">' + esc(d.difficulty) + '</span><span class="badge">' + H().hrs(d.minutes) + "</span>" +
      (best != null ? '<span class="badge ' + (best >= 80 ? "mock" : "P1") + '" id="dd-best">quiz best ' + best + "%</span>" : '<span id="dd-best"></span>') +
      PrepScheduler.button("sddeep", d.title, meta.id, d.minutes) + "</span></div>" +
      '<nav class="dd-nav" aria-label="Sections">' + SECTIONS.map(function (s) {
        return '<a href="#dd-' + s[0] + '" data-sec="' + s[0] + '">' + s[1] + "</a>"; }).join("") +
      (meta.has_summary ? '<a class="dl" href="/interview-prep/design/' + d.slug + '/summary">📄 5-page summary</a>' : "") +
      '<a class="dl" href="/interview-prep/design/' + d.slug + '/pdf" target="_blank" rel="noopener">PDF</a></nav>' +
      '<div class="q-body">' + body + "</div></div>";
    panelState();
    // The notes box is injected when a card OPENS; this one is born open.
    if (PrepScheduler._ensureNote) PrepScheduler._ensureNote(document.querySelector(".dd-doc"));
    quizIntro(d, meta);
    spy();
    var hash = location.hash;
    if (hash && document.querySelector(hash)) jumpTo(document.querySelector(hash), false);
  }

  $("dd-view").addEventListener("click", function (e) {
    var back = e.target.closest(".dd-back");
    if (back) { e.preventDefault(); try { history.pushState({ tab: "design" }, "", "/interview-prep/design"); } catch (_) {} reader = null; renderList(); window.scrollTo({ top: 0 }); return; }
    var nav = e.target.closest(".dd-nav a[data-sec]");
    if (nav) {
      e.preventDefault();
      jumpTo($("dd-" + nav.dataset.sec), true);
    }
  }, true);

  /* Sections far from view are skipped (content-visibility in the CSS), so
     their heights are estimates until drawn: aim, let the target render,
     then land exactly. */
  function jumpTo(el, smooth) {
    if (!el) return;
    var at = function () { return el.getBoundingClientRect().top + window.scrollY - 110; };
    window.scrollTo({ top: at(), behavior: smooth ? "smooth" : "auto" });
    setTimeout(function () { if (Math.abs(el.getBoundingClientRect().top - 110) > 4) window.scrollTo({ top: at() }); }, smooth ? 700 : 60);
  }

  // Highlight the section in view.
  var observer = null;
  function spy() {
    if (observer) observer.disconnect();
    if (!window.IntersectionObserver) return;
    observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var id = en.target.id.replace("dd-", "");
        document.querySelectorAll(".dd-nav a[data-sec]").forEach(function (a) {
          var on = a.dataset.sec === id;
          a.classList.toggle("on", on);
          if (on && a.scrollIntoView) { var n = a.parentNode; n.scrollLeft = a.offsetLeft - n.clientWidth / 2 + a.clientWidth / 2; }
        });
      });
    }, { rootMargin: "-120px 0px -70% 0px" });
    document.querySelectorAll(".dd-sec").forEach(function (s) { observer.observe(s); });
  }

  /* ── Quiz ────────────────────────────────────────────────────────── */
  function shuffle(a) {
    a = a.slice();
    for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t; }
    return a;
  }

  var Q = null;    // {d, meta, order, i, right, missed:[], answered}

  function quizIntro(d, meta, last) {
    var best = prog.quiz && prog.quiz[meta.id];
    var missed = last && last.missed.length;
    $("dd-quiz").innerHTML = '<div class="quiz-intro">' +
      (last ? '<div class="quiz-score ' + (last.pct >= 80 ? "good" : "") + '"><b>' + last.pct + "%</b><span>" + last.right + " of " + last.total +
        (last.pct >= 80 ? " — studied ✓" : " — 80% marks it studied") + "</span></div>" : "") +
      '<p class="mini-lbl">' + d.quiz.length + " questions. Pick the best answer; each one explains why the right option is right and the tempting one is wrong." +
      (best != null ? " Your best: " + best + "%." : "") + "</p>" +
      '<div class="q-actions"><button class="btn primary" data-q="all" type="button">' + (last ? "Retake all" : "Start the quiz") + "</button>" +
      '<button class="btn" data-q="ten" type="button">10 random</button>' +
      (missed ? '<button class="btn" data-q="missed" type="button">Retry the ' + missed + " I missed</button>" : "") + "</div></div>";
    Q = { d: d, meta: meta, lastMissed: last ? last.missed : [] };
  }

  function quizStart(kind) {
    var all = Q.d.quiz.map(function (_, i) { return i; });
    var order = kind === "missed" ? Q.lastMissed.slice() : kind === "ten" ? shuffle(all).slice(0, 10) : shuffle(all);
    Object.assign(Q, { order: order, i: 0, right: 0, missed: [], answered: false, full: kind === "all" });
    quizShow();
  }

  function quizShow() {
    var qi = Q.order[Q.i], q = Q.d.quiz[qi];
    $("dd-quiz").innerHTML = '<div class="quiz-q"><div class="mini-lbl">Question ' + (Q.i + 1) + " of " + Q.order.length +
      ' · <span class="ok">' + Q.right + " right</span></div>" +
      '<div class="quiz-bar"><i style="width:' + Math.round(Q.i / Q.order.length * 100) + '%"></i></div>' +
      '<p class="quiz-stem">' + esc(q.q) + "</p>" +
      '<div class="quiz-opts">' + q.options.map(function (o, j) {
        return '<button class="quiz-opt" type="button" data-opt="' + j + '"><span class="l">' + "ABCD"[j] + "</span><span>" + esc(o) + "</span></button>";
      }).join("") + '</div><div id="quiz-why"></div></div>';
    Q.answered = false;
    var top = $("dd-quiz").getBoundingClientRect().top;
    if (top < 90 || top > window.innerHeight * 0.6) window.scrollTo({ top: top + window.scrollY - 120, behavior: "smooth" });
  }

  function quizAnswer(j) {
    if (Q.answered) return;
    Q.answered = true;
    var qi = Q.order[Q.i], q = Q.d.quiz[qi], ok = j === q.answer;
    if (ok) Q.right++; else Q.missed.push(qi);
    document.querySelectorAll(".quiz-opt").forEach(function (b) {
      var k = +b.dataset.opt;
      b.disabled = true;
      if (k === q.answer) b.classList.add("right");
      else if (k === j) b.classList.add("wrong");
    });
    var last = Q.i === Q.order.length - 1;
    $("quiz-why").innerHTML = '<div class="quiz-why ' + (ok ? "good" : "bad") + '"><b>' + (ok ? "Right." : "Not quite — it's " + "ABCD"[q.answer] + ".") +
      "</b> " + esc(q.why) + '</div><div class="q-actions"><button class="btn primary" data-q="next" type="button">' +
      (last ? "See my score" : "Next question") + "</button></div>";
  }

  async function quizFinish() {
    var total = Q.order.length, pct = Math.round(Q.right / total * 100);
    var res = { pct: pct, right: Q.right, total: total, missed: Q.missed };
    // Only a full run is a score for the design; a 10-question or retry
    // round is practice.
    if (Q.full) {
      try {
        if (prog.available) {
          var was = prog.done.has(Q.meta.id);
          var r = await prog.quizScore(Q.meta.id, pct);
          if (r.done && !was) {
            var box = document.querySelector(".dd-doc .q-prac"); if (box) box.checked = true;
            if (window.Gamify) window.Gamify.studied("ipdd:" + Q.meta.id, Q.meta.minutes, {});
          }
          var b = $("dd-best");
          if (b) { b.className = "badge " + (r.best >= 80 ? "mock" : "P1"); b.textContent = "quiz best " + r.best + "%"; }
        }
      } catch (e) { H().say("Couldn't save the score — " + e.message, "error"); }
    }
    quizIntro(Q.d, Q.meta, res);
  }

  $("dd-view").addEventListener("click", function (e) {
    var o = e.target.closest(".quiz-opt");
    if (o) { quizAnswer(+o.dataset.opt); return; }
    var b = e.target.closest("[data-q]");
    if (!b) return;
    var k = b.dataset.q;
    if (k === "next") { if (Q.i === Q.order.length - 1) quizFinish(); else { Q.i++; quizShow(); } return; }
    quizStart(k);
  });
  document.addEventListener("keydown", function (e) {
    if (!Q || !Q.order || mode !== "deep" || !reader || /input|textarea|select/i.test((e.target.tagName || ""))) return;
    var k = e.key.toUpperCase();
    if (!Q.answered && "ABCD1234".indexOf(k) >= 0 && document.querySelector(".quiz-opt")) {
      quizAnswer("ABCD".indexOf(k) >= 0 ? "ABCD".indexOf(k) : +k - 1);
    } else if (Q.answered && e.key === "Enter") {
      var n = document.querySelector('[data-q="next"]'); if (n) n.click();
    }
  });

  /* ── Concept index ───────────────────────────────────────────────── */
  var CI = null;
  function conceptIndex() {
    if (CI) return CI;
    var map = {};
    LIST.designs.forEach(function (d) {
      d.concepts.forEach(function (name, i) {
        var key = name.toLowerCase().replace(/\(.*?\)/g, "").replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
        var m = map[key] || (map[key] = { name: name.replace(/\s*\(.*\)\s*$/, ""), uses: [] });
        m.uses.push({ slug: d.slug, title: d.title, i: i, full: name });
      });
    });
    CI = Object.keys(map).map(function (k) { return map[k]; })
      .sort(function (a, b) { return b.uses.length - a.uses.length || a.name.localeCompare(b.name); });
    return CI;
  }

  function renderConcepts(term) {
    var t = (term || "").toLowerCase();
    var list = conceptIndex().filter(function (c) {
      return !t || c.name.toLowerCase().indexOf(t) >= 0 || c.uses.some(function (u) { return u.full.toLowerCase().indexOf(t) >= 0; });
    });
    var box = $("dc-view");
    if (!box.querySelector("#dc-search")) {
      box.innerHTML = '<p class="mini-lbl" style="margin:2px 2px 10px">Every distributed-systems concept taught across the deep dives. Open one inside a design to read it with that design as the worked example.</p>' +
        '<div class="toolbar"><input type="search" id="dc-search" placeholder="Search — quorum, saga, backpressure…" aria-label="Search concepts"></div><div id="dc-list"></div>';
      $("dc-search").addEventListener("input", function (e) { renderConcepts(e.target.value); });
    }
    $("dc-list").innerHTML = list.map(function (c) {
      return '<div class="dc-item"><div class="dc-name">' + esc(c.name) + ' <span class="n">' + c.uses.length + "</span></div>" +
        '<div class="dc-uses">' + c.uses.map(function (u) {
          return '<a href="/interview-prep/design/' + u.slug + "#dd-c" + u.i + '" data-slug="' + u.slug + '" data-c="' + u.i + '">' + esc(u.title.replace(/^Design (a |an )?/i, "")) + "</a>";
        }).join("") + "</div></div>";
    }).join("") || '<div class="empty">No concepts match.</div>';
  }

  $("dc-view").addEventListener("click", async function (e) {
    var a = e.target.closest("a[data-slug]");
    if (!a || e.metaKey || e.ctrlKey) return;
    e.preventDefault();
    setMode("deep", true);
    await openReader(a.dataset.slug, true);
    var el = $("dd-c" + a.dataset.c);
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 110 });
  });

  window.PrepDeep = { load: load, route: route };
})();
