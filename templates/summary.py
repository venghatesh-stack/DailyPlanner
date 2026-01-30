SUMMARY_TEMPLATE = """
{% if view == "daily" %}

<h3>📊 Daily Summary – {{ date }}</h3>
{% include "_top_nav.html" %}

<!-- TASKS -->
<table class="summary-table">
  <thead>
    <tr>
      <th>Time</th>
      <th>Task</th>
    </tr>
  </thead>
  <tbody>
    {% for t in data.tasks %}
      <tr>
        <td class="time">
          {{ t.start_label }} – {{ t.end_label }}
        </td>
        <td>{{ t.text }}</td>
      </tr>
    {% endfor %}
  </tbody>
</table>

<div class="section">
  <h4>Habits</h4>
  {{ data.habits | join(", ") if data.habits else "—" }}
</div>

<div class="section">
  <h4>Reflection</h4>
  {{ data.reflection or "—" }}
</div>

{% else %}

<!-- WEEKLY SUMMARY -->
<h3>📆 Weekly Summary</h3>

{% if not data %}
  <div class="empty">No scheduled tasks</div>
{% endif %}

{% for day, tasks in data.items() %}
  <div class="section">
    <h4>{{ day }}</h4>

    {% if tasks %}
      <table style="width:100%; border-collapse:collapse; font-size:14px;">
        <tbody>
          {% for task in tasks %}
          <tr style="border-bottom:1px solid #f0f0f0;">
            <td style="padding:6px 4px; width:30%; color:#2563eb; font-weight:600;">
              {{ task.label or "—" }}
            </td>
            <td style="padding:6px 4px;">
              {{ task.text }}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    {% else %}
      <div class="empty">No tasks</div>
    {% endif %}
  </div>
{% endfor %}

{% endif %}

"""

