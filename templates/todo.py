# ==========================================================
# TEMPLATE – EISENHOWER MATRIX (VIEW-ONLY EXECUTION)
# ==========================================================

TODO_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
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
</style>
</head>

<body>
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
  <summary>{{ label }}</summary>

  {% for category, subs in todo[q].items() %}
    {% for tasks in subs.values() %}
      {% for t in tasks %}
        <div class="task {% if t.done %}done{% endif %}" data-id="{{ t.id }}">
          <div class="task-main">
            <span class="task-index">{{ loop.index }}.</span>

            <input type="checkbox"
                   {% if t.done %}checked{% endif %}
                   onchange="toggleDone('{{ t.id }}', this.checked)">

            <div class="task-text">
              {{ t.text }}
              {% if t.project_id %}
                <span class="badge">📁 Project</span>
              {% endif %}
              {% if t.recurring %}
                <span class="badge">🔁 {{ t.recurrence or "Recurring" }}</span>
              {% endif %}
            </div>
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
function toggleDone(taskId, done) {
  fetch("/todo/toggle-done", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: taskId,
      is_done: done,
      plan_date: "{{ plan_date }}"
    })
  })
  .then(() => {
    const el = document.querySelector('[data-id="'+taskId+'"]');
    if (el) el.classList.toggle("done", done);
  })
  .catch(() => alert("Save failed"));
}
</script>

</body>
</html>
"""
