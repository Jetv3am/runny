"""Conservative, rule-based weekly plan scaffold (no LLM calls)."""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from typing import Any

DISTANCE_KM = {"5k": 5.0, "10k": 10.0, "half_marathon": 21.0975, "marathon": 42.195}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def build_weekly_plan(profile: dict[str, Any], goal: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Build a starter week. Not a medical assessment or a substitute for coaching."""
    today = today or datetime.now(timezone.utc).date()
    training_days = set(goal.get("training_days", []))
    valid_days = [day for day in DAY_NAMES if day in training_days]
    weekly_km = float(profile.get("weekly_distance_km_last_7_days") or 0)
    runs_in_period = int(profile.get("runs_in_period") or 0)
    goal_type = goal.get("goal_type", "5k")

    # Do not prescribe speed work from an empty or very sparse baseline.
    conservative_mode = runs_in_period < 3 or weekly_km <= 0
    max_sessions = min(4 if not conservative_mode else 3, len(valid_days))
    selected_days = valid_days[:max_sessions]
    sessions: list[dict[str, Any]] = []

    if not selected_days:
        return {
            "goal": goal_type,
            "week_start": today.isoformat(),
            "weekly_target_km": 0,
            "sessions": [],
            "message": "Choose at least one available training day to generate a plan.",
            "conservative_mode": True,
        }

    # Use recent volume as a starting point; don't increase weekly distance in this MVP.
    target_km = round(weekly_km if weekly_km > 0 else 6.0, 1)
    if conservative_mode:
        session_types = ["easy_run", "easy_run", "easy_run"]
    elif len(selected_days) >= 3:
        session_types = ["easy_run", "quality_intro", "long_run", "recovery_run"][:len(selected_days)]
    else:
        session_types = ["easy_run", "long_run"][:len(selected_days)]

    # Split distance across sessions, weighted toward the long run.
    weights = []
    for session_type in session_types:
        weights.append(0.4 if session_type == "long_run" else 0.2 if session_type == "quality_intro" else 0.2)
    total_weight = sum(weights) or 1
    for index, (day_name, session_type, weight) in enumerate(zip(selected_days, session_types, weights)):
        offset = (DAY_NAMES.index(day_name) - today.weekday()) % 7
        session_date = today + timedelta(days=offset)
        distance_km = round(target_km * weight / total_weight, 1)
        if session_type == "long_run":
            title = "Easy long run"
            detail = "Keep the effort conversational; stop if you feel pain or unusually fatigued."
        elif session_type == "quality_intro":
            title = "Controlled steady run"
            detail = "Warm up easily, add a few short controlled steady segments, then cool down. Skip intensity if tired."
        elif session_type == "recovery_run":
            title = "Recovery run"
            detail = "Very easy effort. It should feel easier than your normal run."
        else:
            title = "Easy run"
            detail = "Run at a comfortable, conversational effort. Walk breaks are fine."
        sessions.append({
            "date": session_date.isoformat(),
            "day": day_name,
            "type": session_type,
            "title": title,
            "target_distance_km": distance_km,
            "intensity": "easy" if session_type != "quality_intro" else "controlled",
            "instructions": detail,
        })

    return {
        "goal": goal_type,
        "goal_distance_km": DISTANCE_KM[goal_type],
        "target_time_seconds": goal.get("target_time_seconds"),
        "race_date": goal.get("race_date"),
        "week_start": today.isoformat(),
        "baseline_weekly_distance_km": round(weekly_km, 1),
        "weekly_target_km": round(sum(s["target_distance_km"] for s in sessions), 1),
        "sessions": sessions,
        "conservative_mode": conservative_mode,
        "message": (
            "Limited running history: this is an easy-run-only starting template. Import more data before adding intensity."
            if conservative_mode else
            "Starter template based on recent volume. Review how you feel and adjust; this is not yet an adaptive or race-optimized plan."
        ),
    }
