SUMMARY_TEMPLATE = """
<h3>📊 Daily Summary – {{ date }}</h3>

<!-- TASKS -->
<div class="section">
  <h3>✅ Tasks</h3>

  {% if data.tasks %}
    <table style="width:100%; border-collapse:collapse; font-size:14px;">
      <thead>
        <tr style="text-align:left; border-bottom:1px solid #ddd;">
          <th style="padding:6px 4px; width:30%;">Time</th>
          <th style="padding:6px 4px;">Task</th>
        </tr>
      </thead>
      <tbody>
        {% for task in data.tasks %}
        <tr style="border-bottom:1px solid #f0f0f0;">
          <td style="padding:6px 4px; color:#2563eb; font-weight:600;">
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
    <div class="empty">No scheduled tasks</div>
  {% endif %}
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

