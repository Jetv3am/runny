"""Training load calculations using the Banister impulse-response model.

Computes per-workout Training Impulse (TRIMP), then derives:
- CTL (Chronic Training Load) — 42-day EWMA → "fitness"
- ATL (Acute Training Load) — 7-day EWMA → "fatigue"
- TSB (Training Stress Balance) = CTL - ATL → "form / freshness"

When heart rate data is available, we use Banister's exponential HR weighting.
When HR is missing, we fall back to pace-based intensity estimation.

References:
    Banister, E. W. (1991). Modeling elite athletic performance.
    Lucia, A. et al. (2003). Heart rate and performance parameters in elite cyclists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from typing import Any


@dataclass
class WorkoutLoad:
    """Training load for a single workout."""
    activity_id: str
    date: date
    trimp: float
    method: str  # 'hr_based' or 'pace_based'
    duration_min: float
    distance_km: float
    avg_hr: float | None
    intensity_factor: float  # 0.0–1.0 estimated intensity


@dataclass
class TrainingLoadSnapshot:
    """Current training load state."""
    ctl_fitness: float          # Chronic Training Load (42-day)
    atl_fatigue: float          # Acute Training Load (7-day)
    tsb_form: float             # Training Stress Balance
    status: str                 # 'fresh', 'optimal', 'absorbing', 'overreaching'
    monotony: float | None      # Training monotony index (last 7 days)
    strain: float | None        # Training strain (monotony × weekly load)
    total_trimp_7d: float       # Sum of TRIMP in last 7 days
    total_trimp_28d: float      # Sum of TRIMP in last 28 days
    daily_loads: list[dict]     # Per-day TRIMP for charting
    workout_loads: list[WorkoutLoad]


# --- TRIMP Calculations ---

def _hr_based_trimp(duration_min: float, avg_hr: float, resting_hr: float, max_hr: float) -> float:
    """Calculate TRIMP using Banister's exponential heart rate method.

    TRIMP = duration × delta_HR_ratio × 0.64 × e^(1.92 × delta_HR_ratio)

    The exponential weighting means high-intensity work scores
    disproportionately higher than easy work.
    """
    if max_hr <= resting_hr or avg_hr < resting_hr:
        return 0.0

    delta_hr_ratio = (avg_hr - resting_hr) / (max_hr - resting_hr)
    delta_hr_ratio = max(0.0, min(1.0, delta_hr_ratio))  # Clamp to [0, 1]

    return duration_min * delta_hr_ratio * 0.64 * math.exp(1.92 * delta_hr_ratio)


def _pace_based_trimp(duration_min: float, distance_m: float, reference_easy_pace_s_per_km: float = 360.0) -> float:
    """Estimate TRIMP from pace when heart rate is unavailable.

    Uses the ratio of actual pace to an assumed easy pace as a proxy for
    intensity. A 6:00/km easy pace is used as default reference.

    This is less accurate than HR-based TRIMP but prevents runs without
    HR data from being ignored entirely.
    """
    if distance_m <= 0 or duration_min <= 0:
        return 0.0

    pace_s_per_km = (duration_min * 60) / (distance_m / 1000.0)

    # Intensity ratio: faster than easy pace → higher ratio
    # Clamped so very slow runs don't go below 0.3 and sprints cap at 1.0
    intensity_ratio = reference_easy_pace_s_per_km / pace_s_per_km
    intensity_ratio = max(0.3, min(1.2, intensity_ratio))

    # Approximate: treat intensity_ratio like a HR reserve fraction
    return duration_min * intensity_ratio * 0.64 * math.exp(1.92 * intensity_ratio * 0.7)


def calculate_workout_trimp(
    activity: dict[str, Any],
    resting_hr: float = 60.0,
    max_hr: float = 190.0,
) -> WorkoutLoad | None:
    """Calculate TRIMP for a single running workout.

    Args:
        activity: Activity dict from the database.
        resting_hr: Athlete's resting heart rate (default 60).
        max_hr: Athlete's max heart rate (default 190).

    Returns:
        WorkoutLoad with TRIMP score, or None if the activity is unusable.
    """
    if str(activity.get("type") or "").lower() != "running":
        return None

    duration_s = activity.get("duration_s")
    distance_m = activity.get("distance_m")
    if not isinstance(duration_s, (int, float)) or float(duration_s) <= 0:
        return None

    duration_min = float(duration_s) / 60.0
    distance_km = float(distance_m) / 1000.0 if isinstance(distance_m, (int, float)) and float(distance_m) > 0 else 0.0

    start_str = activity.get("start_date", "")
    try:
        start = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        activity_date = start.date()
    except (ValueError, TypeError):
        return None

    avg_hr = activity.get("average_heartrate")
    if isinstance(avg_hr, (int, float)) and float(avg_hr) > 0:
        avg_hr_f = float(avg_hr)
        trimp = _hr_based_trimp(duration_min, avg_hr_f, resting_hr, max_hr)
        intensity = (avg_hr_f - resting_hr) / (max_hr - resting_hr) if max_hr > resting_hr else 0.5
        method = "hr_based"
    else:
        avg_hr_f = None
        trimp = _pace_based_trimp(duration_min, float(distance_m) if distance_m else 0)
        intensity = 0.5  # Unknown without HR
        method = "pace_based"

    return WorkoutLoad(
        activity_id=str(activity.get("id", "")),
        date=activity_date,
        trimp=round(trimp, 1),
        method=method,
        duration_min=round(duration_min, 1),
        distance_km=round(distance_km, 2),
        avg_hr=avg_hr_f,
        intensity_factor=round(max(0.0, min(1.0, intensity)), 2),
    )


# --- CTL / ATL / TSB ---

def _ewma(daily_values: list[float], span: int) -> list[float]:
    """Exponentially weighted moving average matching the Banister model.

    Uses the standard decay factor: alpha = 2 / (span + 1)
    """
    if not daily_values:
        return []

    alpha = 2.0 / (span + 1)
    result = [daily_values[0]]
    for value in daily_values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def compute_training_load(
    activities: list[dict[str, Any]],
    resting_hr: float = 60.0,
    max_hr: float = 190.0,
    days: int = 90,
    now: datetime | None = None,
) -> TrainingLoadSnapshot:
    """Compute full training load model from activity history.

    Args:
        activities: List of activity dicts from the database.
        resting_hr: Athlete's resting heart rate.
        max_hr: Athlete's estimated max heart rate.
        days: Number of days of history to analyze.
        now: Reference timestamp (defaults to now).

    Returns:
        TrainingLoadSnapshot with CTL, ATL, TSB and daily breakdown.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.date()
    start_date = today - timedelta(days=days)

    # Calculate TRIMP for each workout
    workout_loads: list[WorkoutLoad] = []
    for activity in activities:
        load = calculate_workout_trimp(activity, resting_hr, max_hr)
        if load is not None and start_date <= load.date <= today:
            workout_loads.append(load)

    # Aggregate TRIMP by day
    daily_trimp: dict[date, float] = {}
    for d in range(days + 1):
        daily_trimp[start_date + timedelta(days=d)] = 0.0
    for load in workout_loads:
        if load.date in daily_trimp:
            daily_trimp[load.date] += load.trimp

    # Sort by date and compute EWMA
    sorted_dates = sorted(daily_trimp.keys())
    daily_values = [daily_trimp[d] for d in sorted_dates]

    ctl_series = _ewma(daily_values, span=42)
    atl_series = _ewma(daily_values, span=7)

    ctl = round(ctl_series[-1], 1) if ctl_series else 0.0
    atl = round(atl_series[-1], 1) if atl_series else 0.0
    tsb = round(ctl - atl, 1)

    # Determine training status from TSB
    if tsb > 15:
        status = "fresh"        # Well rested, possibly detraining
    elif tsb > 0:
        status = "optimal"      # Good form, ready to perform
    elif tsb > -15:
        status = "absorbing"    # Building fitness, manageable fatigue
    else:
        status = "overreaching"  # High fatigue, risk of overtraining

    # Training monotony & strain (last 7 days)
    last_7_values = daily_values[-7:] if len(daily_values) >= 7 else daily_values
    if len(last_7_values) >= 3:
        mean_7d = sum(last_7_values) / len(last_7_values)
        variance = sum((v - mean_7d) ** 2 for v in last_7_values) / len(last_7_values)
        std_dev = math.sqrt(variance) if variance > 0 else 0.001
        monotony = round(mean_7d / std_dev, 2) if std_dev > 0 else None
        strain = round(sum(last_7_values) * monotony, 1) if monotony else None
    else:
        monotony = None
        strain = None

    # Weekly TRIMP sums
    seven_days_ago = today - timedelta(days=7)
    twenty_eight_days_ago = today - timedelta(days=28)
    trimp_7d = sum(daily_trimp.get(d, 0) for d in sorted_dates if d > seven_days_ago)
    trimp_28d = sum(daily_trimp.get(d, 0) for d in sorted_dates if d > twenty_eight_days_ago)

    # Build daily loads for charting (last 42 days)
    chart_start = today - timedelta(days=42)
    chart_dates = [d for d in sorted_dates if d >= chart_start]
    chart_ctl_start = max(0, len(sorted_dates) - len(chart_dates))
    daily_chart = []
    for i, d in enumerate(chart_dates):
        idx = chart_ctl_start + i
        daily_chart.append({
            "date": d.isoformat(),
            "trimp": round(daily_trimp.get(d, 0.0), 1),
            "ctl": round(ctl_series[idx], 1) if idx < len(ctl_series) else 0.0,
            "atl": round(atl_series[idx], 1) if idx < len(atl_series) else 0.0,
            "tsb": round(
                (ctl_series[idx] if idx < len(ctl_series) else 0.0) -
                (atl_series[idx] if idx < len(atl_series) else 0.0), 1
            ),
        })

    return TrainingLoadSnapshot(
        ctl_fitness=ctl,
        atl_fatigue=atl,
        tsb_form=tsb,
        status=status,
        monotony=monotony,
        strain=strain,
        total_trimp_7d=round(trimp_7d, 1),
        total_trimp_28d=round(trimp_28d, 1),
        daily_loads=daily_chart,
        workout_loads=sorted(workout_loads, key=lambda w: w.date, reverse=True),
    )
