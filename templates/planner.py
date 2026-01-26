PLANNER_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<script src="{{ url_for('static', filename='planner.js') }}" defer></script>

<body>
{% include "_top_nav.html" %}
<div id="clock"> </div>
<div class="container">

  <!-- ================= TIMELINE HEADER ================= -->
  <div class="timeline-header">

    <div class="month-bar">
      <button class="month-nav"
              onclick="location.href='/?year={{ prev_month.year }}&month={{ prev_month.month }}&day=1'">‹</button>

      <span class="month-label">{{ selected_date.strftime("%B %Y") }}</span>

      <button class="month-nav"
              onclick="location.href='/?year={{ next_month.year }}&month={{ next_month.month }}&day=1'">›</button>
    </div>

    <div class="date-jump">
      <input type="month" id="jump-month" value="{{ selected_date.strftime('%Y-%m') }}">
      <input type="number" id="jump-day" min="1" max="31" value="{{ selected_date.day }}">
      <button type="button" onclick="jumpToDate()">Go</button>
    </div>

    <div class="day-timeline">
      {% for d in timeline_days %}
        <a href="/?year={{ d.year }}&month={{ d.month }}&day={{ d.day }}"
           class="day-item {% if d == selected_date %}active{% endif %} {% if d == today %}today{% endif %}">
          <div class="dow">{{ d.strftime("%a") }}</div>
          <div class="num">{{ d.day }}</div>
        </a>
      {% endfor %}
    </div>

  </div>
  <!-- =============== END TIMELINE HEADER =============== -->

  <form method="post" id="planner-form">
    <input type="hidden" name="year" value="{{ year }}">
    <input type="hidden" name="month" value="{{ month }}">
    <input type="hidden" name="day" value="{{ selected_day }}">

    <h3>🧠 Smart Planner Input</h3>
    <textarea name="smart_plan"
      style="width:100%;min-height:120px;margin-bottom:16px;"
      placeholder="One task per line."></textarea>

    <h3>🗒 Tasks (No Time Yet)</h3>
    <div id ="untimed-list">
    {% for t in untimed_tasks %}
      <div class="untimed-item" data-id="{{ t.id }}" data-text="{{ t.text | e }}">
        <div>{{ t.text }}</div>
        <button type="button" onclick="promoteUntimed(this)" data-id="{{ t.id }}">📋 Promote</button>
        <button type="button" onclick="scheduleUntimed('{{ t.id }}')">🕒 Schedule</button>
      </div>
    {% endfor %}
    </div>
    <h3>📅 Day Schedule</h3>

    <div class="day-schedule">

      <div class="day-grid">
        {% for slot in plans %}
          <div class="time-row {% if now_slot and slot == now_slot %}now-slot{% endif %}">
            <div class="time-column">{{ slot_labels[slot] }}</div>
            <div class="grid-line"></div>
          </div>
        {% endfor %}
      </div>

      <div class="events-layer">
        {% for block in blocks %}
          <div class="event-block"
               onclick="editEvent({{ block.start_slot }}, {{ block.end_slot }})"
               style="
                 top: calc({{ block.start_slot - 1 }} * var(--slot-height));
                 height: calc({{ block.end_slot - block.start_slot + 1 }} * var(--slot-height));
               ">
            {% if block.recurring_id %}🔁 {% endif %}
            {{ block.text }}
          </div>
        {% endfor %}
      </div>

    </div>

    <div style="display:none">
      {% for slot in plans %}
        <textarea name="plan_{{slot}}">{{ plans[slot].plan }}</textarea>
      {% endfor %}
    </div>

    <div class="card habits-card">
      <strong>Daily Habits</strong>
      <div class="habits">
        {% for habit in habit_list %}
          <label class="habit-item">
            <input type="checkbox" name="habits" value="{{ habit }}"
                   {% if habit in habits %}checked{% endif %}>
            {{ habit }}
          </label>
        {% endfor %}
      </div>
    </div>

    <div class="card reflection-card">
      <strong>Daily Reflection</strong>
      <textarea name="reflection" rows="4">{{ reflection }}</textarea>
    </div>

  </form>
</div>

<div class="action-stack">
  <button type="button" onclick="toggleCheckin()">🧭 Check-in</button>
  <button type="submit" form="planner-form">💾 Save</button>
  <button type="button" onclick="location.reload()">❌ Cancel</button>
</div>

<!-- ================= MODALS ================= -->
<div id="modal" style="display:none">
<div id="modal-content"></div>
</div>
<div id="summary-modal" style="display:none"></div>

<!-- ================= SCRIPTS ================= -->
<!-- (all your existing inline JS stays exactly as-is below) -->
  <div id="modal" style="display:none"></div>
  <div id="summary-modal" style="display:none"></div>

  <!-- ================= IST TIME HELPERS ================= -->
  <script>
    const PLAN_DATE = "{{ plan_date.isoformat() }}";

    /* Single source of truth for IST */
    function istNow() {
      return new Date(
        new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" })
      );
    }

    /* yyyy-mm-dd + hh:mm → IST Date */
    function istDateFromInputs(dateStr, timeStr = "00:00") {
      return new Date(
        new Date(`${dateStr}T${timeStr}`)
          .toLocaleString("en-US", { timeZone: "Asia/Kolkata" })
      );
    }
  </script>

  <!-- ================= SCRIPTS ================= -->
  <!-- (all your existing inline JS stays exactly as-is below) -->

</body>
</html>
"""
