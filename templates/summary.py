SUMMARY_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {
  font-family: system-ui;
  background:#f6f7f9;
  padding:16px;
}
.container {
  max-width:900px;
  margin:auto;
  background:#fff;
  padding:16px;
  border-radius:12px;
}
h2 { margin-top:0; }
.section { margin-bottom:20px; }
.day {
  margin-top:16px;
  font-weight:700;
}
.task {
  margin:6px 0;
}
.badge {
  font-size:12px;
  opacity:.6;
}
.empty {
  opacity:.6;
  font-style:italic;
}
a {
  font-weight:600;
  text-decoration:none;
}
</style>
</head>

<body>
<div class="container">

{% if view == "daily" %}

  <h2>📊 Daily Summary – {{ date }}</h2>

  <!-- TASKS -->
  <div class="section">
    <h3>✅ Tasks</h3>

    {% if data.tasks %}
      {% for tag, priorities in data.tasks.items() %}
        <div class="badge">#{{ tag }}</div>

        {% for priority, items in priorities.items() %}
          <strong>{{ priority }}</strong>
          {% for item in items %}
            <div class="task">• {{ item }}</div>
          {% endfor %}
        {% endfor %}
      {% endfor %}
    {% else %}
      <div class="empty">No scheduled tasks</div>
    {% endif %}
  </div>

  <!-- HABITS -->
  <div class="section">
    <h3>🔁 Habits</h3>
    {% if data.habits %}
      {{ data.habits | join(", ") }}
    {% else %}
      <div class="empty">No habits tracked</div>
    {% endif %}
  </div>

  <!-- REFLECTION -->
  <div class="section">
    <h3>✍️ Reflection</h3>
    {% if data.reflection %}
      <p>{{ data.reflection }}</p>
    {% else %}
      <div class="empty">No reflection written</div>
    {% endif %}
  </div>

{% elif view == "weekly" %}

  <h2>🗓 Weekly Summary ({{ start }} → {{ end }})</h2>

  {% if not data %}
    <div class="empty">No tasks this week</div>
  {% endif %}

  {% for day, tasks in data.items() %}
    <div class="section">
      <div class="day">{{ day }}</div>
      {% for task in tasks %}
        <div class="task">• {{ task }}</div>
      {% endfor %}
    </div>
  {% endfor %}

{% endif %}

<br>
<a href="/">← Back to Planner</a>

</div>
</body>
</html>
"""

