SUMMARY_TEMPLATE = """
<style>
  body {
    font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
    background: #f6f7f9;
    margin: 0;
    padding: 16px;
  }

  .summary-title {
    font-size: 22px;
    font-weight: 700;
    margin: 12px 0 18px;
  }

  .section {
    margin-bottom: 18px;
  }

  .card {
    background: #ffffff;
    border-radius: 16px;
    padding: 16px;
    box-shadow: 0 10px 24px rgba(0,0,0,0.06);
  }

  /* ---------- TABLE ---------- */

  .summary-table {
    width: 100%;
    border-collapse: collapse;
  }

  .summary-table th {
    text-align: left;
    font-size: 13px;
    font-weight: 600;
    color: #6b7280;
    padding: 10px 12px;
    background: #f9fafb;
  }

  .summary-table td {
    padding: 14px 12px;
    border-top: 1px solid #eef2f7;
    vertical-align: top;
    font-size: 15px;
  }

  .summary-table td.time {
    width: 190px;
    font-weight: 700;
    color: #2563eb;
    white-space: nowrap;
  }

  .summary-table tr:hover {
    background: #f8fafc;
  }

  .empty {
    color: #9ca3af;
    font-style: italic;
    padding: 12px 0;
  }

  /* ---------- TEXT SECTIONS ---------- */

  .section h4 {
    margin: 0 0 8px;
    font-size: 15px;
    font-weight: 600;
  }

  .muted {
    color: #9ca3af;
  }
  


</style>

{% if view == "daily" %}

<div class="nav-icons">  {% include "_top_nav.html" %}  </div>

<h2 class="summary-title">
  📊 Daily Summary – {{ date.strftime("%d %b %Y") if date else date }}
</h2>

<div class="section card">
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
          <td class="time">{{ t.time_label }}</td>
          <td>{{ t.text }}</td>
        </tr>
      {% else %}
        <tr>
          <td colspan="2" class="empty">No tasks scheduled for this day</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<div class="section card">
  <h4>🔥 Habits</h4>
  {% if data.habits %}
    {{ data.habits | join(", ") }}
  {% else %}
    <div class="muted">—</div>
  {% endif %}
</div>

<div class="section card">
  <h4>✍️ Reflection</h4>
  {% if data.reflection %}
    {{ data.reflection }}
  {% else %}
    <div class="muted">—</div>
  {% endif %}
</div>

{% else %}

<div class="nav-icons">  {% include "_top_nav.html" %}  </div>
<form method="get" style="margin-bottom:16px;">
  <input type="hidden" name="view" value="weekly">

  <label style="font-size:14px;font-weight:600;">📆 Select Week</label><br>

  <input type="week"
         name="week"
         value="{{ selected_week }}"
         onchange="this.form.submit()"
         style="
           margin-top:6px;
           padding:8px 10px;
           border-radius:10px;
           border:1px solid #e5e7eb;
           font-size:14px;
         ">
</form>

<h2 class="summary-title">
  📆 Weekly Review
  <span class="muted">
    {{ start.strftime("%d %b") }} – {{ end.strftime("%d %b %Y") }}
  </span>
</h2>

<!-- STATS -->
<div class="stats">
  <div class="stat-card">
    <div class="stat-value">{{ data.focused_hours }}</div>
    <div class="stat-label">Focus Hours</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{{ data.habit_days }}/7</div>
    <div class="stat-label">Habit Days</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{{ data.completion_rate }}%</div>
    <div class="stat-label">Completion</div>
  </div>
</div>

<!-- INSIGHTS -->
<div class="section card">
  <h4>🧠 Weekly Insights</h4>
  <ul>
    {% for i in insights %}
      <li>{{ i }}</li>
    {% endfor %}
  </ul>
  <h4>🔥 Habit Streak</h4>
  <div class="streak">
    {% for i in range(7) %}
      <div class="day {{ 'on' if i < data.habit_days else '' }}"></div>
    {% endfor %}
  </div>
</div>

<!-- REFLECTION SYNTHESIS -->
<div class="section card">
  <h4>✍️ Reflection Highlights</h4>
  {% if data.reflections %}
    <ul>
      {% for r in data.reflections %}
        <li>{{ r }}</li>
      {% endfor %}
    </ul>
  {% else %}
    <div class="muted">No reflections logged</div>
  {% endif %}
</div>

<!-- DAILY BREAKDOWN -->
{% for day, tasks in data.days.items() %}
  <div class="section card">
    <h4>{{ day }}</h4>
    <table class="summary-table">
      <tbody>
        {% for t in tasks %}
          <tr class="{{ 'done' if t.done }}">
            <td class="time">{{ t.label }}</td>
            <td>{{ t.text }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
{% endfor %}

{% endif %}


"""


