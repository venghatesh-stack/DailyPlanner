from datetime import date

def compute_eisenhower_quadrants(tasks):
    today = date.today()

    quadrants = {
        "do_now": [],
        "schedule": [],
        "delegate": [],
        "eliminate": [],
    }

    for task in tasks:
        if not task.get("due_date"):
            continue

        if task["due_date"] == today:
            quadrants["do_now"].append(task)
        elif task["due_date"] > today:
            quadrants["schedule"].append(task)

    return quadrants
