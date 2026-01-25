from datetime import timedelta,datetime

def build_gantt_tasks(tasks):
    gantt = []

    for t in tasks:
        if not t.get("start_date") or not t.get("duration_days"):
            continue

        start = datetime.fromisoformat(t["start_date"]).date()
        end = start + timedelta(days=(t["duration_days"] or 1) - 1)

        progress = 0
        if t.get("planned_hours", 0) > 0:
            progress = min(
                100,
                round((t.get("actual_hours", 0) / t["planned_hours"]) * 100)
            )

        gantt.append({
            "id": t["id"],
            "name": t["task_text"],        # REQUIRED
            "start": start.isoformat(),    # REQUIRED
            "end": end.isoformat(),        # REQUIRED
            "progress": int(progress)      # 0–100 (NOT 0–1)
        })


    return gantt
