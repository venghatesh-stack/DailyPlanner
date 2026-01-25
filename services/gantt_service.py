from datetime import timedelta

def build_gantt_tasks(tasks):
    gantt = []

    for t in tasks:
        if not t.get("start_date") or not t.get("duration_days"):
            continue

        start = t["start_date"]
        end = start + timedelta(days=t["duration_days"] - 1)

        progress = 0
        if t.get("planned_hours", 0) > 0:
            progress = min(
                100,
                round((t.get("actual_hours", 0) / t["planned_hours"]) * 100)
            )

        gantt.append({
            "id": t["id"],
            "text": t["task_text"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "duration": t["duration_days"],
            "progress": progress / 100,  # JS libraries expect 0–1
            "project_id": t.get("project_id")
        })

    return gantt
