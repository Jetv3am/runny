"""Recovery and readiness estimation.

Combines training load balance (TSB), recency of hard efforts, and
volume trends to produce a 0–100 readiness score that indicates how
prepared the athlete is for their next quality session.

This is a heuristic model, not a physiological measurement. It provides
a useful "gut check" but should be interpreted alongside subjective feel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from typing import Any


@dataclass
class ReadinessResult:
    """Daily readiness assessment."""
    score: int                  # 0–100
    label: str                  # 'fully_ready', 'ready', 'moderate', 'fatigued', 'rest_needed'
    factors: dict[str, Any]     # Breakdown of contributing factors
    recommendation: str         # Short coaching note


def _days_since_last_hard_session(
    activities: list[dict[str, Any]],
    today: date,
) -> float:
    """Count days since the last quality/hard session.

    Heuristic: a "hard" session is one with high HR (>155 bpm) or
    moderate-to-fast pace with significant distance.
    """
    latest_hard: date | None = None

    for activity in activities:
        if str(activity.get("type") or "").lower() != "running":
            continue

        start_str = activity.get("start_date")
        if not start_str:
            continue
        try:
            start = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            activity_date = start.date()
        except (ValueError, TypeError):
            continue

        if activity_date > today:
            continue

        is_hard = False
        avg_hr = activity.get("average_heartrate")
        if isinstance(avg_hr, (int, float)) and float(avg_hr) > 155:
            is_hard = True

        distance_m = float(activity.get("distance_m") or 0)
        duration_s = float(activity.get("duration_s") or 0)
        if distance_m > 3000 and duration_s > 0:
            pace = duration_s / (distance_m / 1000)
            if pace < 330:  # Faster than 5:30/km
                is_hard = True

        # Long runs (>12km) count as moderately hard regardless of pace
        if distance_m > 12000:
            is_hard = True

        if is_hard and (latest_hard is None or activity_date > latest_hard):
            latest_hard = activity_date

    if latest_hard is None:
        return 7.0  # No hard sessions found → assume well rested

    return max(0.0, (today - latest_hard).days)


def _weekly_volume_trend(
    activities: list[dict[str, Any]],
    today: date,
) -> float:
    """Compare this week's volume to last week's.

    Returns a ratio: >1.0 means higher volume this week, <1.0 means lower.
    """
    this_week_start = today - timedelta(days=today.weekday())  # Monday
    last_week_start = this_week_start - timedelta(days=7)

    this_week_km = 0.0
    last_week_km = 0.0

    for activity in activities:
        if str(activity.get("type") or "").lower() != "running":
            continue
        distance_m = activity.get("distance_m")
        if not isinstance(distance_m, (int, float)):
            continue

        start_str = activity.get("start_date")
        if not start_str:
            continue
        try:
            start = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            activity_date = start.date()
        except (ValueError, TypeError):
            continue

        if this_week_start <= activity_date <= today:
            this_week_km += float(distance_m) / 1000
        elif last_week_start <= activity_date < this_week_start:
            last_week_km += float(distance_m) / 1000

    if last_week_km <= 0:
        return 1.0  # No data to compare
    return this_week_km / last_week_km


def compute_readiness(
    tsb_form: float,
    activities: list[dict[str, Any]],
    now: datetime | None = None,
) -> ReadinessResult:
    """Compute a readiness score combining TSB, recovery time, and volume.

    Args:
        tsb_form: Current Training Stress Balance (CTL - ATL). Positive = fresh.
        activities: Recent activity list for recovery and volume analysis.
        now: Reference timestamp.

    Returns:
        ReadinessResult with score, label, and recommendation.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.date()

    # --- Factor 1: TSB / Form (40% weight) ---
    # TSB > 15: very fresh (possibly detraining)
    # TSB 0–15: good form
    # TSB -10 to 0: absorbing, some fatigue
    # TSB < -10: high fatigue
    if tsb_form > 20:
        tsb_score = 90  # Very fresh, maybe too rested
    elif tsb_form > 10:
        tsb_score = 95  # Optimal freshness
    elif tsb_form > 0:
        tsb_score = 85
    elif tsb_form > -10:
        tsb_score = 60
    elif tsb_form > -20:
        tsb_score = 35
    else:
        tsb_score = 15  # Heavily fatigued

    # --- Factor 2: Days since last hard session (35% weight) ---
    days_since_hard = _days_since_last_hard_session(activities, today)

    if days_since_hard >= 3:
        recovery_score = 95  # Well recovered
    elif days_since_hard >= 2:
        recovery_score = 80
    elif days_since_hard >= 1:
        recovery_score = 55  # Did hard work yesterday
    else:
        recovery_score = 30  # Hard session today already

    # --- Factor 3: Volume trend (25% weight) ---
    volume_ratio = _weekly_volume_trend(activities, today)

    if volume_ratio <= 0.7:
        volume_score = 90  # Reduced volume (recovery week)
    elif volume_ratio <= 1.0:
        volume_score = 80  # Maintaining or slightly lower
    elif volume_ratio <= 1.1:
        volume_score = 65  # Slight increase
    elif volume_ratio <= 1.2:
        volume_score = 45  # Moderate increase — caution
    else:
        volume_score = 25  # Big jump in volume — high risk

    # Weighted combination
    raw_score = (
        tsb_score * 0.40 +
        recovery_score * 0.35 +
        volume_score * 0.25
    )
    score = int(round(max(0, min(100, raw_score))))

    # Label
    if score >= 80:
        label = "fully_ready"
        recommendation = "You're well recovered. Great day for a quality session or long run."
    elif score >= 65:
        label = "ready"
        recommendation = "Good readiness. An easy-to-moderate effort is appropriate."
    elif score >= 45:
        label = "moderate"
        recommendation = "Some fatigue present. Keep today's effort easy and listen to your body."
    elif score >= 25:
        label = "fatigued"
        recommendation = "Accumulated fatigue detected. Consider an easy recovery run or rest day."
    else:
        label = "rest_needed"
        recommendation = "Significant fatigue. Take a rest day or do very light cross-training."

    return ReadinessResult(
        score=score,
        label=label,
        factors={
            "tsb_form": round(tsb_form, 1),
            "tsb_score": tsb_score,
            "days_since_hard_session": round(days_since_hard, 1),
            "recovery_score": recovery_score,
            "weekly_volume_ratio": round(volume_ratio, 2),
            "volume_score": volume_score,
        },
        recommendation=recommendation,
    )
