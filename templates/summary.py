SUMMARY_TEMPLATE = """
<h3>📊 Daily Summary – {{ date }}</h3>

<div class="section">
  <h4>Tasks</h4>
  {% for task in data.tasks %}
    <div>
      <strong>{{ task.label }}</strong><br>
      {{ task.text | replace('\n','<br>') | safe }}
    </div>
  {% endfor %}
</div>

<div class="section">
  <h4>Habits</h4>
  {{ data.habits | join(", ") }}
</div>

<div class="section">
  <h4>Reflection</h4>
  {{ data.reflection }}
</div>

"""

