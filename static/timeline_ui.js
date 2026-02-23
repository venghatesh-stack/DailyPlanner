let draggedTask = null;

/* ======================
   DRAG START
====================== */

function dragStart(e) {
  draggedTask = e.currentTarget;   // ✅ always card element
  e.dataTransfer.effectAllowed = "move";
}

/* ======================
   DRAG OVER BLOCK
====================== */

function dragOver(e) {
  e.preventDefault();
  e.currentTarget.classList.add("drag-over");
}
function dragLeave(e) {
  const rect = e.currentTarget.getBoundingClientRect();
  const x = e.clientX;
  const y = e.clientY;

  // if pointer is still inside block → ignore
  if (
    x >= rect.left &&
    x <= rect.right &&
    y >= rect.top &&
    y <= rect.bottom
  ) {
    return;
  }

  e.currentTarget.classList.remove("drag-over");
}

/* ======================
   DROP INTO TIME BLOCK
====================== */

function dropTask(e) {
  e.preventDefault();
  e.currentTarget.classList.remove("drag-over");

  if (!draggedTask) return;

  // move visually
  const container = e.currentTarget.querySelector(".time-content");
  if (container) {
    container.appendChild(draggedTask);
  }

  const taskId = draggedTask.dataset.task;
  const newDate = e.currentTarget.dataset.date;

  if (!taskId || !newDate) {
    console.warn("Missing taskId or newDate for reschedule");
    return;
  }

  // ✅ correct endpoint + payload
  fetch("/api/timeline/reschedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task_id: taskId,
      new_date: newDate
    })
  })
  .then(r => r.json())
  .then(resp => {
    if (resp.status !== "ok") {
      console.error("Reschedule failed", resp);
    }
  })
  .catch(err => {
    console.error("Reschedule error", err);
  });

  draggedTask = null;
}

/* ======================
   ZOOM MODE
====================== */

function setZoom(mode) {
  const url = new URL(window.location);
  url.searchParams.set("zoom", mode);
  window.location = url;
}

/* ======================
   PROJECT FILTER
====================== */

function filterProject(pid) {
  const url = new URL(window.location);

  if (pid)
    url.searchParams.set("project", pid);
  else
    url.searchParams.delete("project");

  window.location = url;
}
