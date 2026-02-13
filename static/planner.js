
const USE_TIMELINE_VIEW = false; // Set to true to enable timeline view
const summaryModal = document.getElementById("summary-modal");
const summaryContent = document.getElementById("summary-content");


/* =========================================================
   CLOCK (IST)
========================================================= */
function updateClock() {
  const el = document.getElementById("clock");
  if (!el) return;

  const ist = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" })
  );
  el.textContent = ist.toLocaleTimeString();
}
setInterval(updateClock, 1000);
updateClock();

/* =========================================================
   MOBILE PULL-DOWN TO CLOSE SUMMARY
========================================================= */
let touchStartY = null;
let isAtTop = false;

if (summaryModal && summaryContent) {
  summaryModal.addEventListener("touchstart", e => {
    if (e.touches.length !== 1) return;
    touchStartY = e.touches[0].clientY;
    isAtTop = summaryContent.scrollTop === 0;
  });

  summaryModal.addEventListener("touchmove", e => {
    if (!touchStartY || !isAtTop) return;
    const deltaY = e.touches[0].clientY - touchStartY;
    if (deltaY > 80) {
      closeSummary();
      touchStartY = null;
    }
  });

  summaryModal.addEventListener("touchend", () => {
    touchStartY = null;
  });
}



/* =========================================================
   ESC KEY
========================================================= */
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    const modal = document.getElementById("summary-modal");
    if (modal && modal.style.display === "flex") {
      closeSummary();
    }
  }
});

/* =========================================================
   HABITS / REFLECTION SYNC
========================================================= */
function syncHabit(cb) {
  const main = document.querySelector(
    `input[name="habits"][value="${cb.dataset.habit}"]`
  );
  if (main) main.checked = cb.checked;
}

function syncReflection(el) {
  const main = document.querySelector('textarea[name="reflection"]');
  if (main) main.value = el.value;
}

/* =========================================================
   EVENT EDITING
========================================================= */



function saveEvent(startSlot, endSlot) {
  fetch("/slot/update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plan_date: PLAN_DATE,
      start_slot: startSlot,
      end_slot: endSlot,
      text: document.getElementById("editText").value
    })
  }).then(() => location.reload());
}

/* =========================================================
   DAY STRIP AUTO-SCROLL
========================================================= */


document.addEventListener("DOMContentLoaded", () => {
  if (USE_TIMELINE_VIEW) {
    document.body.classList.add("timeline-mode");

    const root = document.getElementById("timeline-root");
    if (root) {
      renderTimeline(window.TIMELINE_TASKS || [], root);
    }
  }
});




/* =========================================================
   SUBTASK TOGGLE
========================================================= */
function toggleSubtask(id, isDone) {
  fetch("/subtask/toggle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, is_done: isDone })
  });
}

window.addEventListener("focusin", () =>
  document.body.classList.add("keyboard-open")
);

window.addEventListener("focusout", () =>
  document.body.classList.remove("keyboard-open")
);

function handleSmartSave(e) {
  e?.preventDefault?.();

  const form = document.getElementById("planner-form");
  let text = document
  .querySelector('textarea[name="smart_plan"]')
  .value
  .trim();

  text = normalizeSmartTime(text);

  if (!text) {
    form.submit();
    return;
  }

  const timeRange = parseTimeRange(text);

  // No time detected → safe submit
  if (!timeRange) {
    smartAdd(text);
    return;
  }

  // Ask backend to preview slot conflicts
  fetch("/smart/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plan_date: PLAN_DATE,
      text
    })
  })
    .then(r => r.json())
    .then(result => {
      if (!result.conflicts || !result.conflicts.length) {
        smartAdd(text);
        return;
      }

      openSmartPreview(result);
    });
}
function smartAdd(text) {
  return fetch("/smart/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plan_date: PLAN_DATE,
      text: text
    })
  }).then(() => {
    window.location.reload();
  });
}

function openSmartPreview(result) {
  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");

  const html = result.conflicts.map(c => `
    <div style="margin-bottom:10px">
      <strong>${c.time}</strong>
      <pre>${c.existing}</pre>
      <hr>
      <pre>${c.incoming}</pre>
    </div>
  `).join("");

  content.innerHTML = `
    <h3>⚠️ Slot conflicts</h3>
    ${html}
    <button onclick="modal.style.display='none'">Cancel</button>
    <button onclick="smartAdd(document.querySelector('textarea[name=smart_plan]').value)">
        Overwrite & Save
    </button>

  `;

  modal.style.display = "flex";
}
function normalizeSmartTime(line) {
  // Only normalize whitespace, do NOT infer time
  return line.trim().replace(/\s+/g, " ");
}

function parseTimeRange(text) {
  // Matches: 9-10 | 9.30-10.30 | 9:30-10:30
  const m = text.match(
    /(\d{1,2})(?:[.:](\d{2}))?\s*-\s*(\d{1,2})(?:[.:](\d{2}))?/
  );

  if (!m) return null;

  const sh = parseInt(m[1], 10);
  const sm = parseInt(m[2] || "0", 10);
  const eh = parseInt(m[3], 10);
  const em = parseInt(m[4] || "0", 10);

  if (
    sh > 23 || eh > 23 ||
    sm > 59 || em > 59
  ) return null;

  return {
    startMinutes: sh * 60 + sm,
    endMinutes: eh * 60 + em
  };
}
function parseTimeToMinutes(timeStr) {
  // supports: 2.15, 2:15, 14.15, 14:15
  const [h, m = "00"] = timeStr.replace(".", ":").split(":");
  return parseInt(h, 10) * 60 + parseInt(m, 10);
}

function minutesToTime(mins) {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${h}:${m.toString().padStart(2, "0")}`;
}
function snapDown(mins) {
  return Math.floor(mins / 30) * 30;
}

function snapUp(mins) {
  return Math.ceil(mins / 30) * 30;
}
document.addEventListener("change", async (e) => {
  if (!e.target.classList.contains("slot-checkbox")) return;

  const slot = e.target.dataset.slot;
  const checked = e.target.checked;

  await fetch("/slot/toggle-status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plan_date: document.body.dataset.planDate,
      slot: slot,
      status: checked ? "done" : "open"
    })
  });
});
function getHourLabel(timeStr) {
  const [h, m] = timeStr.split(":").map(Number);
  const hour12 = h % 12 || 12;
  const ampm = h >= 12 ? "PM" : "AM";
  return `${hour12} ${ampm}`;
}

function calculateDuration(start, end) {
  if (!end) return "";
  const [sh, sm] = start.split(":").map(Number);
  const [eh, em] = end.split(":").map(Number);
  const mins = (eh * 60 + em) - (sh * 60 + sm);
  const hrs = mins / 60;
  return hrs % 1 === 0 ? `${hrs} hr` : `${hrs.toFixed(1)} hrs`;
}
function renderTimeline(tasks, root) {
  if (!root) return;

  root.innerHTML = "";
  root.id = "timeline"; // optional, for CSS

  if (!Array.isArray(tasks) || tasks.length === 0) {
    root.innerHTML = "<div style='opacity:.6'>No scheduled tasks</div>";
    return;
  }

  // Normalize + filter
  const normalized = tasks
    .filter(t => t.start_time) // timeline needs time
    .map(t => ({
      ...t,
      text: t.text || t.plan || ""
    }))
    .sort((a, b) => a.start_time.localeCompare(b.start_time));

  let lastHour = null;

  normalized.forEach(task => {
    const hour = task.start_time.split(":")[0];

    if (hour !== lastHour) {
      root.appendChild(renderHourMarker(task.start_time));
      lastHour = hour;
    }

    root.appendChild(renderTaskCard(task));
  });
}


function renderHourMarker(startTime) {
  const div = document.createElement("div");
  div.className = "hour-marker";
  div.innerHTML = `
    <div class="hour-label">
      ${getHourLabel(startTime)}
    </div>
  `;
  return div;
}
function renderTaskCard(task) {
  const div = document.createElement("div");
  div.className = "task-card";

  const duration = calculateDuration(task.start_time, task.end_time);

  div.innerHTML = `
    <div class="task-main">
      <input type="checkbox" class="task-check" />
      <div class="task-content">
        <div class="task-title">${task.task_text}</div>
        ${duration ? `<div class="task-meta">${duration}</div>` : ""}
      </div>
    </div>
  `;

  return div;
}
/* =========================================================
   EVENT EDITING
========================================================= */

function editEvent(startSlot, endSlot) {
  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");

  fetch(`/slot/get?date=${PLAN_DATE}&slot=${startSlot}`)
    .then(r => r.json())
    .then(data => {
      content.innerHTML = `
        <h3>✏️ Edit Event</h3>
        <textarea id="editText" style="width:100%;min-height:140px;">
${(data.text || "").replace(/</g, "&lt;")}
        </textarea>
        <br><br>
        <button onclick="document.getElementById('modal').style.display='none'">
          Cancel
        </button>
        <button onclick="saveEvent(${startSlot}, ${endSlot})">
          Save
        </button>
      `;
      modal.style.display = "flex";
    })
    .catch(err => {
      console.error("Edit fetch failed:", err);
    });
}

function saveEvent(startSlot, endSlot) {
  fetch("/slot/update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plan_date: PLAN_DATE,
      start_slot: startSlot,
      end_slot: endSlot,
      text: document.getElementById("editText").value
    })
  }).then(() => location.reload());
}

function renderDailySummaryTable() {
  const rows = [];

  document.querySelectorAll(".time-row").forEach(row => {
    const label = row.querySelector(".time-column")?.innerText?.trim();
    const checkbox = row.querySelector(".slot-checkbox");
    if (!label || !checkbox) return;

    rows.push({
      time: label,
      done: checkbox.checked
    });
  });

  return `
    <table style="width:100%; border-collapse:collapse">
      <tr>
        <th align="left">Time</th>
        <th align="left">Status</th>
      </tr>
      ${rows.map(r => `
        <tr>
          <td>${r.time}</td>
          <td>${r.done ? "✅ Done" : "⬜ Open"}</td>
        </tr>
      `).join("")}
    </table>
  `;
}

function promoteUntimed(btn) {
  const id = btn.dataset.id;

  fetch("/task/promote", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id,
      plan_date: document.body.dataset.planDate
    })
  }).then(() => window.location.reload());
}
function scheduleUntimed(taskId) {
  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");

  content.innerHTML = `
    <h3>🕒 Schedule task</h3>
    <p>Select a start slot:</p>
    <input type="number" id="schedule-slot" min="1" max="48" value="1">
    <br><br>
    <button onclick="modal.style.display='none'">Cancel</button>
    <button onclick="confirmSchedule('${taskId}')">Schedule</button>
  `;

  modal.style.display = "flex";
}

function confirmSchedule(taskId) {
  const slot = document.getElementById("schedule-slot").value;

  fetch("/task/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: taskId,
      plan_date: document.body.dataset.planDate,
      slot: Number(slot)
    })
  }).then(() => window.location.reload());
}
