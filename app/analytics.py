"""Small, deterministic fitness summaries. This module intentionally has no AI calls."""

from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _pace_seconds_per_km(duration_s: float, distance_m: float) -> float | None:
    if duration_s <= 0 or distance_m <= 0:
        return None
    return duration_s / (distance_m / 1000)


def _format_pace(seconds_per_km: float | None) -> str | None:
    if seconds_per_km is None:
        return None
    whole_seconds = round(seconds_per_km)
    minutes, seconds = divmod(whole_seconds, 60)
    return f"{minutes}:{seconds:02d} min/km"


def build_fitness_profile(
    activities: list[dict[str, Any]],
    health_metrics: list[dict[str, Any]],
    days: int = 28,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Summarize recent running fitness from imported records.

    This is a descriptive baseline, not a medical assessment or an automatic
    training prescription. Missing measurements stay missing; we don't guess.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    cutoff = now - timedelta(days=days)
    last_7_cutoff = now - timedelta(days=7)
    previous_7_cutoff = now - timedelta(days=14)

    parsed_runs: list[tuple[datetime, dict[str, Any]]] = []
    for activity in activities:
        activity_type = str(activity.get("type") or "").lower()
        if "run" not in activity_type:
            continue
        start = _parse_datetime(activity.get("start_date"))
        if start is None or not (cutoff <= start <= now):
            continue
        parsed_runs.append((start, activity))

    parsed_runs.sort(key=lambda pair: pair[0])
    recent_runs = [item for _, item in parsed_runs]

    def distance_for(start_after: datetime, start_at_or_before: datetime) -> float:
        total = 0.0
        for started, activity in parsed_runs:
            distance = activity.get("distance_m")
            if start_after < started <= start_at_or_before and isinstance(distance, (int, float)):
                total += max(0.0, float(distance))
        return total

    last_7_distance_m = distance_for(last_7_cutoff, now)
    previous_7_distance_m = distance_for(previous_7_cutoff, last_7_cutoff)
    distances_m = [
        float(a["distance_m"]) for a in recent_runs
        if isinstance(a.get("distance_m"), (int, float)) and float(a["distance_m"]) > 0
    ]

    pace_values = [
        pace for a in recent_runs
        if isinstance(a.get("distance_m"), (int, float))
        and isinstance(a.get("duration_s"), (int, float))
        for pace in [_pace_seconds_per_km(float(a["duration_s"]), float(a["distance_m"]))]
        if pace is not None
    ]
    average_pace = mean(pace_values) if pace_values else None

    heart_rates = [
        float(a["average_heartrate"]) for a in recent_runs
        if isinstance(a.get("average_heartrate"), (int, float)) and float(a["average_heartrate"]) > 0
    ]

    vo2_records = []
    for metric in health_metrics:
        if metric.get("metric_type") != "vo2_max":
            continue
        measured_at = _parse_datetime(metric.get("measured_at"))
        if measured_at and measured_at <= now and isinstance(metric.get("value"), (int, float)):
            vo2_records.append((measured_at, metric))
    vo2_records.sort(key=lambda pair: pair[0], reverse=True)

    if len(recent_runs) < 3:
        confidence = "low"
        confidence_note = "Fewer than 3 runs were found in this period; trends may be misleading."
    elif len(recent_runs) < 8:
        confidence = "moderate"
        confidence_note = "Some recent running history is available; more consistent data will improve the baseline."
    else:
        confidence = "higher"
        confidence_note = "A useful amount of recent running history is available, though this is still an estimate."

    longest_run_m = max(distances_m) if distances_m else None
    latest_vo2 = vo2_records[0][1] if vo2_records else None
    previous_vo2 = vo2_records[1][1] if len(vo2_records) > 1 else None

    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "period_days": days,
        "runs_in_period": len(recent_runs),
        "weekly_distance_km_last_7_days": round(last_7_distance_m / 1000, 2),
        "weekly_distance_km_previous_7_days": round(previous_7_distance_m / 1000, 2),
        "distance_change_percent_week_over_week": (
            round((last_7_distance_m - previous_7_distance_m) / previous_7_distance_m * 100, 1)
            if previous_7_distance_m > 0 else None
        ),
        "total_distance_km_in_period": round(sum(distances_m) / 1000, 2),
        "average_runs_per_week": round(len(recent_runs) / (days / 7), 2),
        "longest_run_km": round(longest_run_m / 1000, 2) if longest_run_m is not None else None,
        "average_run_pace": _format_pace(average_pace),
        "average_run_heart_rate_bpm": round(mean(heart_rates), 1) if heart_rates else None,
        "vo2_max_latest": (
            {
                "value": latest_vo2.get("value"),
                "unit": latest_vo2.get("unit") or "ml/kg/min",
                "measured_at": latest_vo2.get("measured_at"),
                "source_name": latest_vo2.get("source_name"),
            }
            if latest_vo2 else None
        ),
        "vo2_max_previous": (
            {
                "value": previous_vo2.get("value"),
                "unit": previous_vo2.get("unit") or "ml/kg/min",
                "measured_at": previous_vo2.get("measured_at"),
                "source_name": previous_vo2.get("source_name"),
            }
            if previous_vo2 else None
        ),
        "confidence": confidence,
        "confidence_note": confidence_note,
        "notes": [
            "VO2 max is reported from the imported Health records; it is not inferred when absent.",
            "Pace is averaged across recorded runs with both distance and duration; it is not weighted by distance.",
            "A short history describes recent activity but does not establish a safe training load by itself.",
        ],
    }
