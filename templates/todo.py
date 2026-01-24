
# ==========================================================
# TEMPLATE – EISENHOWER MATRIX
# ==========================================================

TODO_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: system-ui; background:#f6f7f9; padding:16px;padding-bottom: calc(120px + env(safe-area-inset-bottom)); /* 👈 ADD THIS */ }
.container { max-width:1100px; margin:auto; background:#fff; padding:20px; border-radius:14px; /* 👇 ADD THIS */
  padding-bottom: 140px; }


.quad { border:1px solid #e5e7eb; border-radius:12px; padding:12px; }
.quad > div {
  margin-top: 8px;
}
.quad:last-child {
  margin-bottom: 40px;
}

.matrix {
   display: grid;
   grid-template-columns: 1fr 1fr;
   gap: 16px;
  padding-bottom: 160px;
}


summary {
  font-weight: 600;
  font-size: 16px;
  cursor: pointer;
  list-style: none;
}

summary::-webkit-details-marker {
  display: none;
}

.floating-bar {
  position: fixed;
  bottom: env(safe-area-inset-bottom, 0);
  left: 0;
  right: 0;
  background: #ffffff;
  border-top: 1px solid #e5e7eb;
  padding: 10px;
  display: flex;
  gap: 10px;
  z-index: 999;
}

.floating-bar button {
  flex: 1;
  padding: 14px;
  font-size: 16px;
  font-weight: 600;
  border-radius: 10px;
  border: none;
}

.floating-bar .save {
  background: #2563eb;
  color: white;
}

.floating-bar .cancel {
  background: #e5e7eb;
}
.task {
  transition:
    opacity 1.1s ease,
    transform 1.1s ease;
}
.task {
  will-change: opacity, transform, max-height;
}

.task.deleting {
  opacity: 0;
  transform: translateX(-24px);
  background: #fef2f2;
  border-color: #fca5a5;
}

.task.collapsing {
  transition:
    max-height 0.6s ease,
    margin 0.6s ease,
    padding 0.6s ease;
  max-height: 0;
  margin-top: 0;
  margin-bottom: 0;
  padding-top: 0;
  padding-bottom: 0;
}


.task + .task {
  border-top: none;
}
.task:focus-within {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15);
}

/* Main row */
.task-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* Index */
.task-index {
  min-width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #f1f5f9;
  color: #475569;
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}


/* Checkbox */
.task-main input[type="checkbox"] {
  width: 18px;
  height: 18px;
}

/* Task text */
.task-main input[type="text"] {
  flex: 1;
  border: none;
  font-size: 16px;
  background: transparent;
  padding: 4px 0;
}

.task-main input[type="text"]:focus {
  outline: none;
  border-bottom: 2px solid #2563eb;
}

.task-delete {
  background: none;
  border: none;
  font-size: 20px;
  color: #dc2626;          /* 👈 visible red */
  cursor: pointer;
  padding: 8px;           /* 👈 touch target */
  border-radius: 8px;
  opacity: 0.85;
}

.task-delete:hover,
.task-delete:active {
  background: rgba(220, 38, 38, 0.12);
  opacity: 1;
}


/* Meta row */
.task-meta input {
  border: 1px solid #e5e7eb;
  background: #f9fafb;
  border-radius: 6px;
  padding: 2px 6px;
  font-size: 12px;
}

.task-meta {
  margin-left: 34px;
  margin-top: 6px;
  display: flex;
  gap: 10px;
}
.task-text {
  resize: none;
  overflow: hidden;
  line-height: 1.4;
}


/* Completed task */
.task.done {
  background: #f8fafc;
  border-color: #94a3b8;
}

.task.done .task-text {
  text-decoration: line-through;
}

/* Prevent mobile auto-zoom */
input,
textarea,
select {
  font-size: 16px !important;
}
####
/* ========================= This section handles Desktop */
####
@media (min-width: 768px) {

  .task {
    position: relative;
  }

  .task-main {
    align-items: center;
  }

  .task-meta {
    margin-left: auto;
    justify-content: flex-end;
    gap: 8px;
  }
}
/* =========================
   MOBILE (≤767px)
   ========================= */
@media (max-width: 767px) {

  /* Grid → single column */
  .matrix {
    grid-template-columns: 1fr;
    width: 100%;
    max-width: 100%;
  }

  .quad {
    width: 100%;
    min-width: 0;
  }

  .task {
    position: relative;
  }

  /* Task row layout */
  .task-main {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    width: 100%;
    min-width: 0;          /* 👈 critical */
    gap: 6px;
    box-sizing: border-box;
  }

  /* Checkbox */
  .task-main input[type="checkbox"] {
    transform: scale(1.25);
    margin: 0;
    margin-top: 2px;
  }

  /* Task text */
  .task-text {
    flex: 1 1 auto;
    min-width: 0;
    box-sizing: border-box;
  }

  /* Delete icon — NO auto margin */
  .task-delete {
    font-size: 20px;
    min-width: 36px;
    flex-shrink: 0;
    margin: 0;
    padding: 4px;
    background: #fee2e2;
    border-radius: 8px;
  }

  /* Repeat dropdown — close to delete */
  .task-repeat {
    margin-left: 4px;
  }

  /* Meta row (date/time goes next line naturally) */
  .task-meta {
    width: 100%;
    display: flex;
    justify-content: flex-start;
    gap: 8px;
    margin-top: 6px;
  }

  .motivation {
    padding: 12px 14px;
    font-size: 13px;
  }

  details.quad {
    overflow: visible;
  }
}


/* ===== Motivational Quote ===== */

.motivation {
  position: relative;   /* 👈 REQUIRED */
  margin: 20px 0 36px;
  padding: 16px 18px;
  border-radius: 14px;
  background: linear-gradient(135deg, #f8fafc, #eef2ff);
  border-left: 4px solid #6366f1;
  display: flex;
  gap: 14px;
}


.motivation-icon {
  font-size: 22px;
  line-height: 1;
}

.motivation-text {
  font-size: 17px;
  font-style: italic;
  font-weight: 500;     /* 👈 semi-bold, tasteful */
  line-height: 1.6;
  color: #1f2937;
  max-width: 640px;
}
.motivation::before {
  content: "Reflection";
  position: absolute;
  top: -12px;
  left: 16px;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6366f1;
  font-weight: 600;
  background: #fff;
  padding: 0 6px;
}

.motivation {
  animation: quoteFade 0.4s ease-out;
}

@keyframes quoteFade {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}


.task-main span[title] {
  margin-right: 4px;
}
.repeat-select {
  font-size: 12px;
  padding: 4px 6px;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
  background: #f9fafb;
  color: #374151;
}
.project-select {
  font-size: 12px;
  padding: 4px 6px;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
  background: #f9fafb;
  color: #374151;
}



</style>
</head>

<body>
<div class="container">
<a href="/">⬅ Back to Daily Planner</a>
<div class="page-header">
  <h2>📋 Eisenhower Matrix – {{ plan_date }}</h2>
 <form method="post"
      action="/todo/copy-prev"
      style="margin:16px 0;">

  <input type="hidden" name="year" value="{{ year }}">
  <input type="hidden" name="month" value="{{ month }}">
  <input type="hidden" name="day" value="{{ plan_date.day }}">

  <button type="submit">
    📥 Copy open tasks from previous day
  </button>

  </form>

</div>
<!-- Travel mode Code Changes  -->
<form method="post" action="/todo/travel-mode" style="margin:12px 0;">
  <input type="hidden" name="year" value="{{ year }}">
  <input type="hidden" name="month" value="{{ month }}">
  <input type="hidden" name="day" value="{{ plan_date.day }}">
  <button type="submit">✈️ Enable Travel Mode</button>
</form>
<!-- Travel mode Code Changes -->

<form method="get" style="margin:12px 0;">
  <input type="hidden" name="day" value="{{ plan_date.day }}">

  <select name="month" onchange="this.form.submit()">
    {% for m in range(1,13) %}
      <option value="{{m}}" {% if m==month %}selected{% endif %}>
        {{ calendar.month_name[m] }}
      </option>
    {% endfor %}
  </select>

  <select name="year" onchange="this.form.submit()">
    {% for y in range(year-5, year+6) %}
      <option value="{{y}}" {% if y==year %}selected{% endif %}>{{y}}</option>
    {% endfor %}
  </select>
</form>
<div class="floating-bar">
  <button type="submit"
          form="todo-form"
          class="save">
    💾 Save
  </button>

  <button type="button"
          class="cancel"
          onclick="window.location.reload()">
    ❌ Cancel
  </button>
</div>

<div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px;">
{% for d in days %}
  <a href="/todo?year={{year}}&month={{month}}&day={{d.day}}"
     style="
       width:36px;height:36px;
       display:flex;align-items:center;justify-content:center;
       border-radius:50%;
       text-decoration:none;
       border:1px solid #ddd;
       color:#000;
       {% if d.day == plan_date.day %}
         background:#2563eb;color:#fff;
       {% endif %}
     ">
    {{ d.day }}
  </a>
{% endfor %}
</div>
{% if quote %}
<div class="motivation">
  <span class="motivation-icon">{{ quote.icon }}</span>
  <span class="motivation-text">{{ quote.text }}</span>
</div>
{% endif %}
{% if request.args.get('travel') %}
<div style="
  margin:12px 0;
  padding:8px 12px;
  border-radius:999px;
  background:#eef2ff;
  color:#3730a3;
  font-weight:600;
  display:inline-block;
">
  ✈️ Travel Mode Active
</div>
{% endif %}

<form method="post" id="todo-form">

  <!-- ============================= -->
  <!-- MATRIX CONTAINER (GRID)       -->
  <!-- ============================= -->
  <div class="matrix">

    <!-- Hidden inputs -->
    <input type="hidden" name="year" value="{{ year }}">
    <input type="hidden" name="month" value="{{ month }}">
    <input type="hidden" name="day" value="{{ plan_date.day }}">

    <!-- ================================= -->
    <!-- START: QUADRANT LOOP (4 times)   -->
    <!-- ================================= -->
    {% for q, label in [
      ('do','🔥 Do Now'),
      ('schedule','📅 Schedule'),
      ('delegate','🤝 Delegate'),
      ('eliminate','🗑 Eliminate')
    ] %}

      <details class="quad" open>
        <summary>{{ label }}</summary>
        <div id="{{ q }}">

          <!-- =============================== -->
          <!-- CATEGORY / TASK RENDERING       -->
          <!-- =============================== -->
          {% for category, subs in todo[q].items() %}
            <details open>
              <summary>{{ TASK_CATEGORIES.get(category, "📁") }} {{ category }}</summary>

              {% if category == "Travel" %}
                {# -------- Travel: static subgroups -------- #}
                {% for sub, icon in STATIC_TRAVEL_SUBGROUPS.items() %}

                  <details open style="margin-left:12px;">
                    <summary>{{ icon }} {{ sub }}</summary>

                    {% for t in subs.get(sub, []) %}
                      <div class="task {% if t.done %}done{% endif %}">
                        <input type="hidden" name="{{ q }}_id[]" value="{{ t.id }}">
                        <!-- 👇 ADD THIS LINE -->
                        <input type="hidden"
                          name="{{ q }}_deleted[{{ t.id }}]"
                          value="0">

                        <div class="task-main">
                          <span class="task-index">{{ loop.index }}.</span>

                          <!-- Preserve category / subcategory -->
                          <input type="hidden" name="{{ q }}_category[]" value="{{ t.category }}">
                          <input type="hidden" name="{{ q }}_subcategory[]" value="{{ t.subcategory }}">
                          <input type="hidden"
                              name="{{ q }}_done_state[{{ t.id }}]"
                              value="{{ 1 if t.done else 0 }}">



                         <textarea
                            class="task-text"
                            oninput="autoGrow(this); autosaveTask(this.closest('.task'))">
                         </textarea>

                          <input type="checkbox"
                              {% if t.done %}checked{% endif %}
                              onchange="toggleDone(this); autosaveTask(this.closest('.task'), 200)">


                          {% if t.recurring %}
                            <button type="button"
                                    class="task-delete"
                                    title="Delete this and future occurrences"
                                    onclick="deleteRecurring('{{ t.id }}')">🗑</button>
                          {% else %}
                            <button type="button"
                                      class="task-delete"
                                      title="Remove after Save"
                                      onclick="requestDelete(this, '{{ q }}')">
                                🗑
                            </button>


                          {% endif %}
                            <select
                          class="project-select"
                          onchange="autosaveProject(this)"
                          data-id="{{ t.id }}"
                        >
                          <option value="">— No Project —</option>

                          {% for p in projects %}
                            <option
                              value="{{ p.id }}"
                              {% if t.project_id == p.id %}selected{% endif %}
                            >
                              {{ p.name }}
                            </option>
                          {% endfor %}
                        </select>
                          {% if t.recurring %}
                            <span title="Repeats {{ t.recurrence }}" style="font-size:13px;color:#6366f1;">
                              🔁 {{ t.recurrence or "Recurring" }}
                            </span>
                          {% else %}
                            <select class="repeat-select"
                                    onchange="setRecurrence('{{ t.id }}', this.value)">
                              <option value="">Repeat…</option>
                              <option value="daily">Daily</option>
                              <option value="weekly">Weekly</option>
                              <option value="monthly">Monthly</option>
                            </select>
                          {% endif %}
                        </div>

                        <div class="task-meta">
                          <input type="date" name="{{ q }}_date[]" value="{{ t.task_date or '' }}">
                          <input type="time" name="{{ q }}_time[]" value="{{ t.task_time or '' }}">
                        </div>
                      </div>
                    {% endfor %}

                    {% if not subs.get(sub) %}
                      <div class="empty-group">No tasks</div>
                    {% endif %}
                  </details>
                {% endfor %}

              {% else %}
                {# -------- Non-Travel categories: flat list -------- #}
                {% for tasks in subs.values() %}
                  {% for t in tasks %}
                    <div class="task {% if t.done %}done{% endif %}">
                      <input type="hidden" name="{{ q }}_id[]" value="{{ t.id }}">
                      <!-- 👇 ADD THIS LINE -->
                      <input type="hidden"
                      name="{{ q }}_deleted[{{ t.id }}]"
                      value="0">

                      <div class="task-main">
                        <span class="task-index">{{ loop.index }}.</span>

                        <input type="hidden" name="{{ q }}_category[]" value="{{ t.category }}">
                        <input type="hidden" name="{{ q }}_subcategory[]" value="{{ t.subcategory }}">
                        <input type="hidden"
                                name="{{ q }}_done_state[{{ t.id }}]"
                                value="{{ 1 if t.done else 0 }}">


                        <textarea name="{{ q }}[]"
                                  class="task-text"
                                  rows="1"
                                  placeholder="Add a task"
                                  oninput="autoGrow(this); autosaveTask(this.closest('.task'))">{{ t.text }}</textarea>

                        <input type="checkbox"
                            {% if t.done %}checked{% endif %}
                            onchange="toggleDone(this); autosaveTask(this.closest('.task'), 200)">


                        {% if t.recurring %}
                          <button type="button"
                                  class="task-delete"
                                  title="Delete this and future occurrences"
                                  onclick="deleteRecurring('{{ t.id }}')">🗑</button>
                        {% else %}
                          <button type="button"
                              class="task-delete"
                              title="Remove after Save"
                              onclick="requestDelete(this, '{{ q }}')">
                            🗑
                          </button>

                        {% endif %}
                        <select
                          class="project-select"
                          onchange="autosaveProject(this)"
                          data-id="{{ t.id }}"
                        >
                          <option value="">— No Project —</option>

                          {% for p in projects %}
                            <option
                              value="{{ p.id }}"
                              {% if t.project_id == p.id %}selected{% endif %}
                            >
                              {{ p.name }}
                            </option>
                          {% endfor %}
                        </select>

                        {% if t.recurring %}
                          <span title="Repeats {{ t.recurrence }}" style="font-size:13px;color:#6366f1;">
                            🔁 {{ t.recurrence or "Recurring" }}
                          </span>
                        {% else %}
                          <select class="repeat-select"
                                  onchange="setRecurrence('{{ t.id }}', this.value)">
                            <option value="">Repeat…</option>
                            <option value="daily">Daily</option>
                            <option value="weekly">Weekly</option>
                            <option value="monthly">Monthly</option>
                          </select>
                        {% endif %}
                      </div>

                      <div class="task-meta">
                        <input type="date" name="{{ q }}_date[]" value="{{ t.task_date or '' }}">
                        <input type="time" name="{{ q }}_time[]" value="{{ t.task_time or '' }}">
                      </div>
                    </div>
                  {% endfor %}
                {% endfor %}
              {% endif %}

            </details>
          {% endfor %}
        </div>

        <!-- Add button for this quadrant -->
        <button type="button" onclick="addTask('{{ q }}')">+ Add</button>

      </details>
      <br>

    {% endfor %}
    <!-- ================================= -->
    <!-- END: QUADRANT LOOP                -->
    <!-- ================================= -->

  </div>
</form>

</div>




<script>

const pendingDeletes = new Map();
let autoSaveTimer = null;
let deleteBatch = {
  taskIds: new Set(),
  timer: null
};
function requestDelete(btn, quadrant) {
  const task = btn.closest('.task');
  if (!task) return;

  const del = task.querySelector(
    `input[type="hidden"][name^="${quadrant}_deleted"]`
  );
  if (!del) return;

  const match = del.name.match(/\[(.+?)\]/);
  if (!match) return;

  const taskId = match[1];

  // 🔑 Mark pending delete (NOT saved yet)
  del.value = "pending";

  // Track in batch
  deleteBatch.taskIds.add(taskId);

  // Animate
  task.getBoundingClientRect();
  task.classList.add("deleting");

  setTimeout(() => {
    task.classList.add("collapsing");
  }, 1200);

  // 🔔 Show ONE toast
  showBatchUndoToast();

  // 🔁 Reset timer if already running
  if (deleteBatch.timer) {
    clearTimeout(deleteBatch.timer);
  }

  deleteBatch.timer = setTimeout(commitBatchDelete, 7000);
}
function commitBatchDelete() {
  // Mark all as deleted
  deleteBatch.taskIds.forEach(taskId => {
    const input = document.querySelector(
      `input[type="hidden"][name$="_deleted[${taskId}]"]`
    );
    if (input) input.value = "1";
  });

  deleteBatch.taskIds.clear();

  document.getElementById("todo-form")?.submit();
}


function showBatchUndoToast() {
  const toast = document.getElementById("undo-toast");
  const undoBtn = document.getElementById("undo-btn");

  const count = deleteBatch.taskIds.size;
  toast.querySelector("span").textContent =
    count === 1 ? "Task deleted" : `${count} tasks deleted`;

  toast.style.display = "flex";

  undoBtn.onclick = () => {
    if (deleteBatch.timer) {
      clearTimeout(deleteBatch.timer);
      deleteBatch.timer = null;
    }

    // Restore all tasks
    deleteBatch.taskIds.forEach(taskId => {
      const delInput = document.querySelector(
        `input[type="hidden"][name$="_deleted[${taskId}]"]`
      );
      const taskEl = delInput?.closest(".task");

      if (delInput) delInput.value = "0";
      if (taskEl) {
        taskEl.classList.remove("deleting", "collapsing");
      }
    });

    deleteBatch.taskIds.clear();
    toast.style.display = "none";
  };

  // Auto-hide toast (visual only)
  setTimeout(() => {
    toast.style.display = "none";
  }, 7000);
}



function addTask(q, category = "General", subcategory = "General") {
  const container = document.getElementById(q);
  if (!container) return;

  const row = document.createElement("div");
  row.className = "task";
  row.dataset.saved = "0";   // 👈 REQUIRED
  const id = "new_" + Date.now();

  row.innerHTML = `
    <input type="hidden" name="${q}_id[]" value="${id}">
    <input type="hidden" name="${q}_deleted[${id}]" value="0">
    <input type="hidden" name="${q}_category[]" value="${category}">
    <input type="hidden" name="${q}_subcategory[]" value="${subcategory}">
    <input type="hidden" name="${q}_done_state[${id}]" value="0">


    <div class="task-main">
      <span class="task-index">*</span>

      <textarea name="${q}[]"
                class="task-text"
                oninput="autoGrow(this); autosaveTask(this.closest('.task'))"
                rows="1"
                placeholder="Add a task"
                autofocus></textarea>

      <input type="checkbox"
       onchange="toggleDone(this); autosaveTask(this.closest('.task'), 300)">


      <button type="button"
              class="task-delete"
              title="Remove before save"
              onclick="this.closest('.task').remove()">🗑</button>
    </div>

    <div class="task-meta">
      <input type="date" name="${q}_date[]">
      <input type="time" name="${q}_time[]">
    </div>
  `;

  container.appendChild(row);

  // Auto-grow immediately
  const textarea = row.querySelector("textarea");
  if (textarea) autoGrow(textarea);
}

function renumberTasks(container) {
  container.querySelectorAll(".task").forEach((task, i) => {
    const idx = task.querySelector(".task-index");
    if (idx) idx.textContent = (i + 1) + ".";
  });
}


const autosaveTimers = new WeakMap();

function autosaveTask(taskEl, delay = 800) {
  const idInput  = taskEl.querySelector('input[name$="_id[]"]');
  const textarea = taskEl.querySelector("textarea");
  const checkbox = taskEl.querySelector('input[type="checkbox"]');

  if (!idInput || !textarea) return;

  const taskId = idInput.value;

  clearTimeout(autosaveTimers.get(taskEl));

  autosaveTimers.set(taskEl, setTimeout(() => {
    fetch("/todo/autosave", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: taskId,
        plan_date: "{{ plan_date }}",
        quadrant: taskEl.closest("[id]").id,
        task_text: textarea.value.trim(),
        is_done: checkbox?.checked || false,
      })
    })
    .then(r => r.json())
    .then(res => {

      if (taskId.startsWith("new_") && res.id) {
        idInput.value = res.id;
        taskEl.dataset.saved = "1";
      }

      renumberTasks(taskEl.parentElement);
      showToast("Saved");

    })
    .catch(err => {
      console.error("Autosave failed", err);
      showToast("Save failed", 3000);
    });

  }, delay));
}


</script>
<script>


function toggleDone(checkbox) {
  const task = checkbox.closest(".task");
  if (!task) return;

  task.classList.toggle("done", checkbox.checked);

  const hidden = task.querySelector(
    'input[type="hidden"][name*="_done_state"]'
  );
  if (hidden) {
    hidden.value = checkbox.checked ? "1" : "0";
  }

  //autosaveForm(200);
}


function autoGrow(textarea) {
  if (!textarea) return;

  // Reset height so shrink also works
  textarea.style.height = "auto";

  // Set height to scroll height
  textarea.style.height = textarea.scrollHeight + "px";
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("textarea.task-text").forEach(autoGrow);
});
function setRecurrence(taskId, recurrence) {
  if (taskId.startsWith("new_")) {
    alert("Please save the task before making it recurring.");
    return;
  }
  fetch("/set_recurrence", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task_id: taskId,
      recurrence: recurrence
    })
  }).then(() => location.reload());
}

function deleteRecurring(taskId) {
  if (!confirm("Delete this task from today onwards? Past entries will remain.")) {
    return;
  }

  fetch("/delete_recurring", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId })
  }).then(() => location.reload());
}


</script>

{% if request.args.get('copied') %}
<div id="copied-toast"
     style="
       position: fixed;
       bottom: 140px;   /* 👈 slightly higher than Save toast */
       left: 50%;
       transform: translateX(-50%);
       background: #16a34a;
       color: white;
       padding: 12px 20px;
       border-radius: 999px;
       font-weight: 600;
       box-shadow: 0 10px 25px rgba(0,0,0,.15);
       z-index: 9999;
     ">
  📥 Open tasks copied
</div>


<script>
  setTimeout(() => {
    const toast = document.getElementById("copied-toast");
    if (toast) toast.remove();
  }, 2500);
</script>
{% endif %}
<div id="modal" style="
  position:fixed;
  inset:0;
  background:rgba(0,0,0,.35);
  display:none;
  align-items:center;
  justify-content:center;
  z-index:9999;
">
  <div style="
    background:#fff;
    padding:18px;
    width:320px;
    border-radius:14px;
  " id="modal-content"></div>
</div>

<div id="undo-toast"
     style="
       position: fixed;
       bottom: 140px;
       left: 50%;
       transform: translateX(-50%);
       background: #111827;
       color: white;
       padding: 12px 18px;
       border-radius: 999px;
       font-weight: 600;
       display: none;
       gap: 12px;
       align-items: center;
       z-index: 9999;
     ">
  <span>Task deleted</span>
  <button id="undo-btn"
          style="
            background: none;
            border: none;
            color: #93c5fd;
            font-weight: 700;
            cursor: pointer;
          ">
    Undo
  </button>
</div>
<div id="toast"
     style="
       position: fixed;
       bottom: 90px;
       left: 50%;
       transform: translateX(-50%);
       background: #111827;
       color: white;
       padding: 12px 18px;
       border-radius: 999px;
       font-weight: 600;
       display: none;
       z-index: 9999;
       box-shadow: 0 10px 25px rgba(0,0,0,.2);
     ">
  <span id="toast-text"></span>
</div>
<script>
function showToast(message, duration = 2000) {
  const toast = document.getElementById("toast");
  const text = document.getElementById("toast-text");
  if (!toast || !text) return;

  text.textContent = message;
  toast.style.display = "block";

  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    toast.style.display = "none";
  }, duration);
}

</script>
{% if toast %}
<script>
 showToast({{ toast.message | tojson }}, 2500);    
</script>
{% endif %}

<script>
function autosaveProject(select) {
  fetch("/todo/autosave", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: select.dataset.id,
      project_id: select.value || null
    })
  });
}
</script>

</body>
</html>
"""