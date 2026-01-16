SUMMARY_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: system-ui; background:#f6f7f9; padding:16px; }
.container { max-width:900px; margin:auto; background:#fff; padding:20px; border-radius:14px; }
h2 { margin-top:0; }
.tag { margin-top:16px; }
.priority { margin-left:16px; color:#475569; }
.task { margin-left:32px; }
.day { margin-top:18px; font-weight:600; }
</style>
</head>

<body>
<div class="container">
<a href="/">⬅ Back to Planner</a>

{% if view == "daily" %}
  <h2>📊 Daily Summary – {{ date }}</h2>

  {% for tag, priorities in data.items() %}
    <div class="tag">
      <strong>#{{ tag }}</strong>
      {% for p, tasks in priorities.items() %}
        <div class="priority">{{ p }}</div>
        {% for t in tasks %}
          <div class="task">• {{ t }}</div>
        {% endfor %}
      {% endfor %}
    </div>
  {% endfor %}

{% else %}
  <h2>📈 Weekly Summary ({{ start }} → {{ end }})</h2>

  {% for day, tasks in data.items() %}
    <div class="day">{{ day }}</div>
    {% for t in tasks %}
      <div class="task">• {{ t }}</div>
    {% endfor %}
  {% endfor %}
{% endif %}

</div>
</body>
</html>
"""