
from datetime import date, timedelta

from flask import Blueprint, jsonify, request, session
from requests.exceptions import HTTPError

from auth import login_required
from supabase_client import get, post, update
from utils.user_tz import user_now, user_today

habits_bp = Blueprint("habits", __name__)
@habits_bp.route("/api/habits/add", methods=["POST"])
@login_required
def add_habit():
    user_id = session["user_id"]
    data = request.get_json()

    # Trust user-chosen casing; previously force-uppercased ("WALKING" instead of "Walking").
    name = (data.get("name") or "").strip()
    habit_type = data.get("habit_type", "number")
    start_date = data.get("start_date") or user_today().isoformat()

    # Boolean habits: auto-fill unit and goal
    if habit_type == "boolean":
        unit = "BOOLEAN"
        goal = 1.0
    else:
        unit = (data.get("unit") or "").strip().upper()
        goal = float(data.get("goal") or 0)

    if not name:
        return jsonify({"error": "Habit name is required"}), 400
    if habit_type != "boolean" and (not unit or not goal):
        return jsonify({"error": "Unit and goal are required for numeric habits"}), 400

    try:
        inserted = post(
            "habit_master",
            {
                "user_id": user_id,
                "name": name,
                "unit": unit,
                "goal": goal,
                "habit_type": habit_type,
                "position": 9999,
                "is_deleted": False,
                "start_date": start_date,
            },
            prefer="return=representation"
        )

        habit = inserted[0]
        post("habit_goal_history", {
            "habit_id": habit["id"],
            "goal": goal,
            "effective_from": start_date
        })
        return jsonify({
            "id": habit["id"],
            "name": habit["name"],
            "unit": habit["unit"],
            "goal": habit["goal"],
            "value": 0
        })

    except HTTPError as e:
        if e.response.status_code == 409:
            return jsonify({"error": "Habit already exists"}), 409

        raise
@habits_bp.route("/api/habits/delete", methods=["POST"])
@login_required
def delete_habit():
    data = request.get_json()
    habit_id = data.get("habit_id")

    update(
        "habit_master",
        params={
            "id": f"eq.{habit_id}",
            "user_id": f"eq.{session['user_id']}"
        },
        json={"is_deleted": True}
    )

    return jsonify({"success": True})
@habits_bp.route("/api/habits/update", methods=["POST"])
@login_required
def update_habit():
    data = request.get_json()
    user_id = session["user_id"]

    # Validate ownership
    habit = get(
        "habit_master",
        {
            "id": f"eq.{data['habit_id']}",
            "user_id": f"eq.{user_id}",
            "is_deleted": "eq.false"
        }
    )

    if not habit:
        return jsonify({"error": "Habit not found"}), 404
    
    post("habit_goal_history", {
        "habit_id": data["habit_id"],
        "goal": float(data["goal"]),
        "effective_from": data.get("effective_from") or user_today().isoformat()
    })

    return jsonify({"success": True})

@habits_bp.route("/api/habits/reorder", methods=["POST"])
@login_required
def reorder_habit():
    data = request.get_json()

    update(
        "habit_master",
        params={"id": f"eq.{data['habit_id']}", "user_id": f"eq.{session['user_id']}"},
        json={"position": data["position"]}
    )

    return jsonify({"success": True})

@habits_bp.route("/api/v2/habit-weekly/<habit_id>")
@login_required
def habit_weekly(habit_id):
    user_id = session["user_id"]
    today = user_today()
    start = today - timedelta(days=6)

    rows = get(
        "habit_entries",
        params={
            "user_id": f"eq.{user_id}",
            "habit_id": f"eq.{habit_id}",
            "plan_date": f"gte.{start.isoformat()}"
        }
    )

    date_map = {r["plan_date"]: float(r["value"] or 0) for r in rows}

    data = []
    for i in range(7):
        day = (start + timedelta(days=i)).isoformat()
        data.append(date_map.get(day, 0))

    return jsonify(data)
@habits_bp.route("/api/habits/<habit_id>", methods=["GET", "PUT"])
@login_required
def habit_detail(habit_id):

    user_id = session["user_id"]

    # ---------- GET ----------
    if request.method == "GET":

        row = get(
            "habit_master",
            params={
                "id": f"eq.{habit_id}",
                "user_id": f"eq.{user_id}",
                "is_deleted": "eq.false"
            }
        )

        if not row:
            return jsonify({"error": "Habit not found"}), 404

        return jsonify(row[0])

    # ---------- PUT ----------
    if request.method == "PUT":

        data = request.get_json()

        name = data.get("name")
        unit = data.get("unit")
        goal = data.get("goal")

        if goal is None:
            return jsonify({"error": "Goal required"}), 400

        update(
            "habit_master",
            params={
                "id": f"eq.{habit_id}",
                "user_id": f"eq.{user_id}",
                "is_deleted": "eq.false"
            },
            json={
                "name": name,
                "unit": unit,
                "goal": float(goal)
            }
        )
           # 🔴 INSERT GOAL HISTORY
        post(
            "habit_goal_history",
            {
                "habit_id": habit_id,
                "goal": float(goal),
                "effective_from": user_today().isoformat()
            }
        )
        return jsonify({"success": True})

@habits_bp.route("/api/habits/restore", methods=["POST"])
@login_required
def restore_habit():
    data = request.get_json()
    habit_id = data.get("habit_id")
    if not habit_id:
        return jsonify({"error": "habit_id required"}), 400

    update("habit_master",
           params={"id": f"eq.{habit_id}", "user_id": f"eq.{session['user_id']}"},
           json={"is_deleted": False})
    return jsonify({"success": True})


