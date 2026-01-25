SUMMARY_TEMPLATE = """
{% if view == "daily" %}

<h3>📊 Daily Summary – {{ date }}</h3>
{% include "_top_nav.html" %}

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

