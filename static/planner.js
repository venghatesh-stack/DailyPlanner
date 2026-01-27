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

const summaryModal = document.getElementById("summary-modal");
const summaryContent = document.getElementById("summary-content");

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
function editEvent(startSlot, endSlot) {
  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");

  fetch(`/slot/get?date=${PLAN_DATE}&slot=${startSlot}`)
    .then(r => r.json())
    .then(data => {
      content.innerHTML = `
        <h3>✏️ Edit Event</h3>
        <textarea id="editText" style="width:100%;min-height:140px;">${data.text}</textarea>
        <br><br>
        <button onclick="modal.style.display='none'">Cancel</button>
        <button onclick="saveEvent(${startSlot},${endSlot})">Save</button>
      `;
      modal.style.display = "flex";
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

/* =========================================================
   DAY STRIP AUTO-SCROLL
========================================================= */
document.addEventListener("DOMContentLoaded", () => {
  const selected = document.getElementById("selected-day");
  if (!selected) return;

  requestAnimationFrame(() => {
    selected.scrollIntoView({
      behavior: "smooth",
      inline: "center",
      block: "nearest"
    });
  });
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
  const text = document
    .querySelector('textarea[name="smart_plan"]')
    .value
    .trim();

  if (!text) {
    form.submit();
    return;
  }

  const timeRange = parseTimeRange(text);

  // No time detected → safe submit
  if (!timeRange) {
    form.submit();
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
        form.submit();
        return;
      }

      openSmartPreview(result);
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
    <button onclick="document.getElementById('planner-form').submit()">
      Overwrite & Save
    </button>
  `;

  modal.style.display = "flex";
}
function normalizeSmartTime(line) {
  // already has am/pm → leave it
  if (/\b(am|pm)\b/i.test(line)) return line;

  const match = line.match(/^(\d{1,2})([:.](\d{2}))?\s+(.*)$/);
  if (!match) return line;

  let hour = parseInt(match[1], 10);
  const minute = match[3] || "00";
  const text = match[4];

  let period = "am";

  if (hour === 12) period = "pm";
  else if (hour >= 5 && hour <= 11) period = "am";
  else period = "pm";

  return `${hour}:${minute} ${period} ${text}`;
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
