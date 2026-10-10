/* Weekly check-in — /goals/check-in.
 *
 * Reads GET /api/goals/check-in, renders one card per goal with a number
 * field for each key result kept by hand, and saves everything in one
 * POST. Key results filled in from tasks are shown read-only: their value
 * is recomputed on every task toggle, so asking for it would be a lie. */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => (n === null || n === undefined || n === "") ? "—"
    : (Number.isInteger(Number(n)) ? String(Number(n)) : String(Number(n).toFixed(2)).replace(/0+$/, "").replace(/\.$/, ""));

  function sinceText(kr) {
    if (kr.days_since === null || kr.days_since === undefined) return "";
    if (kr.days_since === 0) return "updated today";
    if (kr.days_since === 1) return "updated yesterday";
    return kr.stale ? `not updated in ${kr.days_since} days` : `updated ${kr.days_since} days ago`;
  }

  function hint(kr) {
    const better = kr.direction === "down" ? "lower is better" : "higher is better";
    const parts = [`target ${fmt(kr.target_value)}${kr.unit ? " " + esc(kr.unit) : ""}`, better];
    if (kr.auto) parts.unshift("filled in from linked tasks");
    const since = sinceText(kr);
    if (since && !kr.auto) parts.unshift(since);
    return parts.join(" · ");
  }

  function krRow(kr) {
    const id = `ci-v-${kr.id}`;
    const value = kr.auto
      ? `<span class="ci-kr-auto">${fmt(kr.current_value)} ${esc(kr.unit)} · auto</span>`
      : `<label class="ci-kr-input" for="${id}">
           <span class="visually-hidden">${esc(kr.title)}, value this week</span>
           <input id="${id}" type="number" step="any" inputmode="decimal"
                  data-kr="${esc(kr.id)}" value="${esc(kr.current_value ?? "")}" required>
           <span class="ci-kr-unit">${esc(kr.unit)}</span>
         </label>`;
    return `
      <div class="ci-kr${kr.stale ? " ci-kr--stale" : ""}">
        <div class="ci-kr-text">
          <span class="ci-kr-title">${esc(kr.title)}</span>
          <span class="ci-kr-hint">${hint(kr)}</span>
        </div>
        ${value}
        <span class="ci-kr-pct" aria-label="${kr.progress} percent">${kr.progress}%</span>
      </div>`;
  }

  function goalCard(g) {
    return `
      <section class="ci-goal" aria-labelledby="ci-g-${esc(g.id)}">
        <div class="ci-goal-head">
          <h2 id="ci-g-${esc(g.id)}">${esc(g.title)}</h2>
          <span class="ci-goal-pct">now <b>${g.progress}%</b></span>
        </div>
        ${g.key_results.map(krRow).join("")}
        <label class="ci-note">
          <span>Note for this week (optional)</span>
          <input type="text" maxlength="2000" data-note-for="${esc(g.id)}"
                 placeholder="What moved it, or what is blocking it?">
        </label>
      </section>`;
  }

  async function load() {
    let data;
    try {
      const res = await fetch("/api/goals/check-in", { credentials: "same-origin" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (err) {
      $("#ci-sub").textContent = "Couldn't load your key results. Try again in a moment.";
      return;
    }
    const goals = data.goals || [];
    if (!goals.length) {
      $("#ci-sub").textContent = "No key results to update.";
      $("#ci-empty").hidden = false;
      return;
    }
    const n = data.to_update || 0;
    $("#ci-sub").textContent =
      `${n} number${n === 1 ? "" : "s"} to update across ${goals.length} goal${goals.length === 1 ? "" : "s"}`;
    $("#ci-goals").innerHTML = goals.map(goalCard).join("");
    $("#ci-foot").hidden = n === 0;
  }

  async function save(ev) {
    ev.preventDefault();
    const entries = [];
    for (const input of document.querySelectorAll("input[data-kr]")) {
      if (input.value.trim() === "") continue;
      const value = Number(input.value);
      if (Number.isNaN(value)) { input.focus(); return; }
      entries.push({ key_result_id: input.dataset.kr, value });
    }
    const notes = {};
    for (const input of document.querySelectorAll("input[data-note-for]")) {
      if (input.value.trim()) notes[input.dataset.noteFor] = input.value.trim();
    }
    if (!entries.length) return;

    const btn = $("#ci-save");
    btn.disabled = true;
    try {
      const res = await fetch("/api/goals/check-in", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entries, notes }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
      if (typeof showToast === "function") {
        showToast(`Checked in ${body.saved} key result${body.saved === 1 ? "" : "s"}`, "success");
      }
      await load();
    } catch (err) {
      if (typeof showToast === "function") showToast(`Check-in not saved: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("#ci-form").addEventListener("submit", save);
    load();
  });
})();
