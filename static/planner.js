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

/* =========================================================
   SMART SAVE
========================================================= */
function handleSmartSave(e) {
  e?.preventDefault?.();

  const form = document.getElementById("planner-form");
  const smartText = document
    .querySelector('textarea[name="smart_plan"]')
    .value
    .trim();

  if (!smartText || !/@|\bfrom\b/i.test(smartText)) {
    form.submit();
    return;
  }

  fetch("/smart/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plan_date: PLAN_DATE,
      text: smartText
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
