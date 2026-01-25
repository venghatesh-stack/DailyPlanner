# ==========================================================
# TEMPLATE – EISENHOWER MATRIX (VIEW-ONLY EXECUTION)
# ==========================================================

TODO_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet"
        href="{{ url_for('static', filename='style.css') }}">
<style>
body {
  font-family: system-ui;
  background:#f6f7f9;
  padding:16px;
  padding-bottom: calc(80px + env(safe-area-inset-bottom));
}

.container {
  max-width:1100px;
  margin:auto;
  background:#fff;
  padding:20px;
  border-radius:14px;
}

.matrix {
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:16px;
}

@media (max-width:767px){
  .matrix { grid-template-columns:1fr; }
}

.quad {
  border:1px solid #e5e7eb;
  border-radius:12px;
  padding:12px;
}

summary {
  font-weight:600;
  font-size:16px;
  cursor:pointer;
  list-style:none;
}

summary::-webkit-details-marker { display:none; }

.task {
  padding:10px;
  border-radius:10px;
  border:1px solid #e5e7eb;
  margin-top:8px;
  transition:background .2s;
}

.task.done {
  background:#f8fafc;
  opacity:.65;
}

.task-main {
  display:flex;
  align-items:center;
  gap:12px;
}

.task-index {
  min-width:26px;
  height:26px;
  border-radius:50%;
  background:#f1f5f9;
  font-size:13px;
  font-weight:600;
  display:flex;
  align-items:center;
  justify-content:center;
}

.task-text {
  flex:1;
  font-size:16px;
}

.task.done .task-text {
  text-decoration:line-through;
}

.badge {
  font-size:12px;
  padding:2px 6px;
  border-radius:6px;
  background:#eef2ff;
  color:#3730a3;
  margin-left:6px;
  white-space:nowrap;
}


.urgency-pill {
  font-size: 11px;
  padding: 1px 6px;        /* ⬅ smaller */
  border-radius: 999px;
  font-weight: 600;
  margin-bottom: 4px;
  display: inline-block;
}
.urgency-pill.soon {
  background: #fef3c7;
  color: #92400e;
}

.urgency-pill.overdue {
  background: #fee2e2;
  color: #991b1b;
}
.task.urgency-overdue {
  border-left: 4px solid #ef4444;
}

.task.urgency-soon {
  border-left: 4px solid #f59e0b;
}


.task.done .urgency-pill {
  display: none;
}
.task-header {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.task-title {
  flex: 1;
  font-size: 16px;
}

.task-details {
  display: none;
  margin-top: 6px;
  padding-left: 28px; /* aligns under text */
  font-size: 13px;
  color: #6b7280;
}

.task.expanded .task-details {
  display: block;
}

.meta {
  margin-top: 2px;
}

/* Overdue stays strong but not loud */
.urgency-pill.overdue {
  background: #fee2e2;
  color: #991b1b;
}

.urgency-pill.soon {
  background: #fef3c7;
  color: #92400e;
}

/* Completed tasks */
.task.done .urgency-pill {
  display: none;
}
.task.done .task-text { text-decoration: line-through; }

</style>
</head>

<body>
{% include "_top_nav.html" %}

<div class="container">

<a href="/">⬅ Back to Daily Planner</a>

<h2 style="margin:12px 0;">📋 Eisenhower Matrix – {{ plan_date }}</h2>

<form method="post" action="/todo/copy-prev" style="margin-bottom:12px;">
  <input type="hidden" name="year" value="{{ year }}">
  <input type="hidden" name="month" value="{{ month }}">
  <input type="hidden" name="day" value="{{ plan_date.day }}">
  <button type="submit">📥 Copy open tasks from previous day</button>
</form>

<form method="post" action="/todo/travel-mode" style="margin-bottom:12px;">
  <input type="hidden" name="year" value="{{ year }}">
  <input type="hidden" name="month" value="{{ month }}">
  <input type="hidden" name="day" value="{{ plan_date.day }}">
  <button type="submit">✈️ Enable Travel Mode</button>
</form>

<form method="get" style="margin-bottom:16px;">
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

{% if quote %}
<div class="motivation">
  <span class="motivation-icon">{{ quote.icon }}</span>
  <span class="motivation-text">{{ quote.text }}</span>
</div>
{% endif %}

<div class="matrix">

{% for q, label in [
  ('do','🔥 Do Now'),
  ('schedule','📅 Schedule'),
  ('delegate','🤝 Delegate'),
  ('eliminate','🗑 Eliminate')
] %}

<details class="quad" open>
  <summary>
    {{ label }}
    {% set c = quadrant_counts[q] %}
    {% if c.total > 0 %}
      <span style="
        font-size:12px;
        font-weight:500;
        color:#6b7280;
        margin-left:6px;
      ">
        ({{ c.done }} / {{ c.total }} done)
      </span>
    {% endif %}
  </summary>


  {% for category, subs in todo[q].items() %}
    {% for tasks in subs.values() %}
      {% for t in tasks %}
        <div class="task
            {% if t.status== 'done' %}done{% endif %}
            {% if t.urgency %}urgency-{{ t.urgency }}{% endif %}
        "
        data-id="{{ t.id }}">

          <!-- HEADER (always visible) -->
          <div class="task-header" onclick="toggleTask(this)">
              <input type="checkbox"
              data-id="{{ t.id }}"
              {% if t.status == "done" %}checked{% endif %}
              onclick="event.stopPropagation()"
              onchange="toggleDone(this)">


            <div class="task-title">
              {{ t.text }}
            </div>

            {% if t.urgency %}
              <span class="urgency-pill {{ t.urgency }}">
                {{ "Overdue" if t.urgency == "overdue" else "Due soon" }}
              </span>
            {% endif %}
          </div>

          <!-- DETAILS (hidden by default) -->
          <div class="task-details">
            {% if t.due_date %}
              <div class="meta">📅 {{ t.due_date }}
                {% if t.due_time %} ⏰ {{ t.due_time }}{% endif %}
              </div>
            {% endif %}

            {% if t.project_name %}
              <div class="meta">📁 {{ t.project_name }}</div>
            {% endif %}

            {% if t.delegated_to %}
              <div class="meta">👤 {{ t.delegated_to }}</div>
            {% endif %}

            {% if t.elimination_reason %}
              <div class="meta muted">Reason: {{ t.elimination_reason }}</div>
            {% endif %}
          </div>

        </div>

      {% endfor %}
    {% endfor %}
  {% endfor %}

</details>
{% endfor %}

</div>
</div>

<script>
function toggleDone(checkbox) {
  const taskId = checkbox.dataset.id;
  if (!taskId) return;

  const task = checkbox.closest(".task");
  const isDone = checkbox.checked;

  // UI update (instant feedback)
  if (task) {
    task.classList.toggle("done", isDone);
  }

  fetch("/projects/tasks/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task_id: taskId,
      status: isDone ? "done" : "open"
    })
  }).catch(err => {
    console.error("Failed to update task status", err);
  });
}
</script>

<script>
function toggleTask(el) {
  const card = el.closest(".task");
  if (!card) return;

  card.classList.toggle("expanded");
}
</script>

</body>
</html>
"""
