/* =========================================================
   GLOBAL CONSTANTS
========================================================= */

 /* const PLAN_DATE = "{{ plan_date.isoformat() }}"; */

/* =========================================================
   CLOCK (IST)
========================================================= */
/* =========================================================
   SLOT → TIME (SOURCE OF TRUTH)
========================================================= */


function updateClock() {
  const ist = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" })
  );
  document.getElementById("clock").textContent = ist.toLocaleTimeString();
}
setInterval(updateClock, 1000);
updateClock();

/* =========================================================
   UNTYPED TASK PROMOTION
========================================================= */

function promoteUntimed(btn) {
  const id = btn.dataset.id;
  const item = btn.closest(".untimed-item");
  const text = item.dataset.text;

  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");
  content.innerHTML = `
      <h3>📋 Promote Task</h3>

      <div id="preview"></div>

      <div class="modal-actions">
        <button class="btn-do" onclick="confirmPromote('${id}','Q1')">🔥 Do now</button>
        <button class="btn-schedule" onclick="confirmPromote('${id}','Q2')">📅 Schedule</button>
        <button class="btn-delegate" onclick="confirmPromote('${id}','Q3')">🤝 Delegate</button>
        <button class="btn-eliminate" onclick="confirmPromote('${id}','Q4')">🗑 Eliminate</button>
      </div>

      <button class="modal-cancel" onclick="modal.style.display='none'">
        Cancel
      </button>
    `;


  content.querySelector("#preview").textContent = text;
  modal.style.display = "flex";
}

function confirmPromote(id, quadrant) {
  fetch("/untimed/promote", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, quadrant, plan_date: PLAN_DATE })
  }).then(() => location.reload());
}

/* =========================================================
   UNTYPED TASK SCHEDULING
========================================================= */

function scheduleUntimed(id) {
  const item = document.querySelector(".untimed-item[data-id='" + id + "']");
  const text = item.dataset.text;

  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");

  content.innerHTML =
    "<h3>🕒 Schedule Task</h3>" +
    "<div id='preview'></div><br>" +
    "<label>Date</label><input type='date' id='d' value='" + PLAN_DATE + "'><br><br>" +
    "<label>Start</label><input type='time' id='t'><br><br>" +
    "<label>Duration</label>" +
    "<select id='dur'><option value='1'>30m</option><option value='2'>1h</option></select><br><br>" +
    "<button onclick=\"modal.style.display='none'\">Cancel</button> " +
    "<button onclick=\"confirmSchedule('" + id + "')\">Continue</button>";

  content.querySelector("#preview").textContent = text;
  modal.style.display = "flex";
}

function confirmSchedule(id) {
  const item = document.querySelector(".untimed-item[data-id='" + id + "']");
  const newText = item.dataset.text;
  const date = document.getElementById("d").value;
  const time = document.getElementById("t").value;
  const slots = parseInt(document.getElementById("dur").value, 10);

  if (!time) {
    alert("Select time");
    return;
  }

  const [h, m] = time.split(":").map(Number);
  const start_slot = Math.floor((h * 60 + m) / 30) + 1;

  fetch("/untimed/slot-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_date: date, start_slot, slot_count: slots })
  })
    .then(r => r.json())
    .then(preview => {
      const combined = preview
        .map(p => (p.existing ? p.existing + "\n---\n" + newText : newText))
        .join("\n\n");

      const modal = document.getElementById("modal");
      const content = document.getElementById("modal-content");

      content.innerHTML =
        "<h3>✏️ Confirm</h3>" +
        "<textarea id='finalText' style='width:100%;min-height:160px;'></textarea><br><br>" +
        "<button onclick=\"modal.style.display='none'\">Cancel</button> " +
        "<button onclick=\"saveFinalSchedule('" + id + "','" + date + "'," +
        start_slot + "," + slots + ")\">Save</button>";

      document.getElementById("finalText").value = combined;
    });
}

function saveFinalSchedule(id, date, start_slot, slots) {
  fetch("/untimed/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id,
      plan_date: date,
      start_slot,
      slot_count: slots,
      final_text: document.getElementById("finalText").value
    })
  }).then(() => location.reload());
}

/* =========================================================
   CHECK-IN DRAWER
========================================================= */

function toggleCheckin() {
  const drawer = document.getElementById("checkin-drawer");
  drawer.classList.toggle("hidden");
}

function closeCheckinIfOpen() {
  const drawer = document.getElementById("checkin-drawer");
  if (drawer && !drawer.classList.contains("hidden")) {
    drawer.classList.add("hidden");
  }
}

/* =========================================================
   DAILY SUMMARY
========================================================= */

function openSummary() {
  fetch(`/summary?date=${PLAN_DATE}`)
    .then(r => r.text())
    .then(html => {
      document.getElementById("summary-content").innerHTML = html;
      document.getElementById("summary-modal").style.display = "flex";
    })
    .catch(err => {
      document.getElementById("summary-content").innerHTML =
        "<p style='color:red'>Failed to load summary</p>";
      document.getElementById("summary-modal").style.display = "flex";
      console.error(err);
    });
}

function closeSummary() {
  document.getElementById("summary-modal").style.display = "none";
}

/* ESC key */
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    const modal = document.getElementById("summary-modal");
    if (modal && modal.style.display === "flex") {
      closeSummary();
    }
  }
});

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
   HABITS / REFLECTION SYNC
========================================================= */

function syncHabit(cb) {
  const main = document.querySelector(
    'input[name="habits"][value="' + cb.dataset.habit + '"]'
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
        <textarea id="editText" style="width:100%;min-height:140px;">
${data.text}
        </textarea><br><br>
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
function handleSlotInput(slotId, newText) {
  const existingText = getExistingSlotText(slotId);

  if (!existingText || existingText.trim() === "") {
    commitSlot(slotId, newText);
    return;
  }

  openOverwritePreview({
    slotId,
    existingText,
    newText
  });
}
/* =========================================================
   GLOBAL CONSTANTS
========================================================= */

 /* const PLAN_DATE = "{{ plan_date.isoformat() }}"; */

/* =========================================================
   CLOCK (IST)
========================================================= */
/* =========================================================
   SLOT → TIME (SOURCE OF TRUTH)
========================================================= */


function updateClock() {
  const ist = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" })
  );
  document.getElementById("clock").textContent = ist.toLocaleTimeString();
}
setInterval(updateClock, 1000);
updateClock();

/* =========================================================
   UNTYPED TASK PROMOTION
========================================================= */

function promoteUntimed(btn) {
  const id = btn.dataset.id;
  const item = btn.closest(".untimed-item");
  const text = item.dataset.text;

  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");
  content.innerHTML = `
      <h3>📋 Promote Task</h3>

      <div id="preview"></div>

      <div class="modal-actions">
        <button class="btn-do" onclick="confirmPromote('${id}','Q1')">🔥 Do now</button>
        <button class="btn-schedule" onclick="confirmPromote('${id}','Q2')">📅 Schedule</button>
        <button class="btn-delegate" onclick="confirmPromote('${id}','Q3')">🤝 Delegate</button>
        <button class="btn-eliminate" onclick="confirmPromote('${id}','Q4')">🗑 Eliminate</button>
      </div>

      <button class="modal-cancel" onclick="modal.style.display='none'">
        Cancel
      </button>
    `;


  content.querySelector("#preview").textContent = text;
  modal.style.display = "flex";
}

function confirmPromote(id, quadrant) {
  fetch("/untimed/promote", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, quadrant, plan_date: PLAN_DATE })
  }).then(() => location.reload());
}

/* =========================================================
   UNTYPED TASK SCHEDULING
========================================================= */

function scheduleUntimed(id) {
  const item = document.querySelector(".untimed-item[data-id='" + id + "']");
  const text = item.dataset.text;

  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");

  content.innerHTML =
    "<h3>🕒 Schedule Task</h3>" +
    "<div id='preview'></div><br>" +
    "<label>Date</label><input type='date' id='d' value='" + PLAN_DATE + "'><br><br>" +
    "<label>Start</label><input type='time' id='t'><br><br>" +
    "<label>Duration</label>" +
    "<select id='dur'><option value='1'>30m</option><option value='2'>1h</option></select><br><br>" +
    "<button onclick=\"modal.style.display='none'\">Cancel</button> " +
    "<button onclick=\"confirmSchedule('" + id + "')\">Continue</button>";

  content.querySelector("#preview").textContent = text;
  modal.style.display = "flex";
}

function confirmSchedule(id) {
  const item = document.querySelector(".untimed-item[data-id='" + id + "']");
  const newText = item.dataset.text;
  const date = document.getElementById("d").value;
  const time = document.getElementById("t").value;
  const slots = parseInt(document.getElementById("dur").value, 10);

  if (!time) {
    alert("Select time");
    return;
  }

  const [h, m] = time.split(":").map(Number);
  const start_slot = Math.floor((h * 60 + m) / 30) + 1;

  fetch("/untimed/slot-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_date: date, start_slot, slot_count: slots })
  })
    .then(r => r.json())
    .then(preview => {
      const combined = preview
        .map(p => (p.existing ? p.existing + "\n---\n" + newText : newText))
        .join("\n\n");

      const modal = document.getElementById("modal");
      const content = document.getElementById("modal-content");

      content.innerHTML =
        "<h3>✏️ Confirm</h3>" +
        "<textarea id='finalText' style='width:100%;min-height:160px;'></textarea><br><br>" +
        "<button onclick=\"modal.style.display='none'\">Cancel</button> " +
        "<button onclick=\"saveFinalSchedule('" + id + "','" + date + "'," +
        start_slot + "," + slots + ")\">Save</button>";

      document.getElementById("finalText").value = combined;
    });
}

function saveFinalSchedule(id, date, start_slot, slots) {
  fetch("/untimed/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id,
      plan_date: date,
      start_slot,
      slot_count: slots,
      final_text: document.getElementById("finalText").value
    })
  }).then(() => location.reload());
}

/* =========================================================
   CHECK-IN DRAWER
========================================================= */

function toggleCheckin() {
  const drawer = document.getElementById("checkin-drawer");
  drawer.classList.toggle("hidden");
}

function closeCheckinIfOpen() {
  const drawer = document.getElementById("checkin-drawer");
  if (drawer && !drawer.classList.contains("hidden")) {
    drawer.classList.add("hidden");
  }
}

/* =========================================================
   DAILY SUMMARY
========================================================= */

function openSummary() {
  fetch(`/summary?date=${PLAN_DATE}`)
    .then(r => r.text())
    .then(html => {
      document.getElementById("summary-content").innerHTML = html;
      document.getElementById("summary-modal").style.display = "flex";
    })
    .catch(err => {
      document.getElementById("summary-content").innerHTML =
        "<p style='color:red'>Failed to load summary</p>";
      document.getElementById("summary-modal").style.display = "flex";
      console.error(err);
    });
}

function closeSummary() {
  document.getElementById("summary-modal").style.display = "none";
}

/* ESC key */
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    const modal = document.getElementById("summary-modal");
    if (modal && modal.style.display === "flex") {
      closeSummary();
    }
  }
});

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
   HABITS / REFLECTION SYNC
========================================================= */

function syncHabit(cb) {
  const main = document.querySelector(
    'input[name="habits"][value="' + cb.dataset.habit + '"]'
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
        <textarea id="editText" style="width:100%;min-height:140px;">
${data.text}
        </textarea><br><br>
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
function handleSmartSave() {
  // prepare slots / smart planner logic
  document.getElementById("planner-form").submit();
  const smartText = document.querySelector(
    'textarea[name="smart_plan"]'
  ).value.trim();

  if (!smartText) {
    document.getElementById("planner-form").submit();
    return;
  }

  // TEMP: submit directly if no time patterns
  if (!/@|\bfrom\b/i.test(smartText)) {
    document.getElementById("planner-form").submit();
    return;
  }

  // 🔎 Ask backend to preview conflicts
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
      if (!result.conflicts.length) {
        document.getElementById("planner-form").submit();
        return;
      }

      openSmartPreview(result);
    });
}
function openSmartPreview(result) {
  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");

  const html = result.conflicts.map(c =>
    `<div style="margin-bottom:10px">
      <strong>${c.time}</strong>
      <pre>${c.existing}</pre>
      <hr>
      <pre>${c.incoming}</pre>
    </div>`
  ).join("");

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
