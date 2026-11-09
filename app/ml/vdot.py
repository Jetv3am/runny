"""VDOT estimation using the Daniels/Gilbert formula.

Estimates aerobic fitness (VO2max equivalent) from running performance data.
The VDOT system, developed by Dr. Jack Daniels, maps running velocity and
duration to an equivalent VO2max score, which can then predict race times
across distances.

References:
    Daniels, J. (2014). Daniels' Running Formula (3rd ed.).
    Gilbert, J. (2005). Oxygen Power: Performance Tables for Distance Runners.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class VdotSample:
    """A single VDOT estimate derived from one run."""
    vdot: float
    date: datetime
    distance_m: float
    duration_s: float
    pace_per_km: float  # seconds per km
    confidence: float   # 0.0 to 1.0
    source: str         # 'quality_effort', 'long_run', 'moderate_effort'


@dataclass
class VdotEstimate:
    """Aggregated VDOT estimate with race predictions."""
    estimated_vdot: float | None
    sample_count: int
    confidence: str     # 'low', 'moderate', 'high'
    race_predictions: dict[str, str]   # {"5k": "22:30", "10k": "46:45", ...}
    pace_zones: dict[str, str]         # {"easy": "5:30-6:00", "tempo": "4:45", ...}
    samples: list[VdotSample]
    trend: str | None   # 'improving', 'stable', 'declining'


# --- Daniels/Gilbert formula components ---

def _oxygen_cost(velocity_m_per_min: float) -> float:
    """Calculate oxygen cost of running at a given velocity.

    Args:
        velocity_m_per_min: Running speed in meters per minute.

    Returns:
        Oxygen cost in ml/kg/min.
    """
    v = velocity_m_per_min
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def _percent_vo2max(duration_min: float) -> float:
    """Calculate the fraction of VO2max sustainable for a given duration.

    Args:
        duration_min: Duration of effort in minutes.

    Returns:
        Fraction of VO2max (typically 0.6 to 1.0).
    """
    t = duration_min
    return (
        0.8
        + 0.1894393 * math.exp(-0.012778 * t)
        + 0.2989558 * math.exp(-0.1932605 * t)
    )


def calculate_vdot(distance_m: float, duration_s: float) -> float | None:
    """Calculate VDOT from a single run performance.

    Args:
        distance_m: Distance run in meters.
        duration_s: Duration of the run in seconds.

    Returns:
        VDOT value, or None if inputs are invalid.
    """
    if distance_m <= 0 or duration_s <= 0:
        return None

    duration_min = duration_s / 60.0
    velocity_m_per_min = distance_m / duration_min

    # Formula is calibrated for reasonable running speeds (roughly 3–7 min/km).
    # Very slow walks or sprints produce nonsensical VDOT values.
    pace_per_km_s = duration_s / (distance_m / 1000.0)
    if pace_per_km_s < 150 or pace_per_km_s > 600:  # Sub-2:30/km or slower than 10:00/km
        return None

    vo2 = _oxygen_cost(velocity_m_per_min)
    if vo2 <= 0:
        return None

    fraction = _percent_vo2max(duration_min)
    if fraction <= 0:
        return None

    vdot = vo2 / fraction
    # Sanity check: reasonable human VDOT range is ~15 to ~85
    if vdot < 10 or vdot > 90:
        return None

    return round(vdot, 2)


def predict_race_time(vdot: float, distance_m: float) -> float | None:
    """Predict race time in seconds for a given VDOT and distance.

    Uses numerical bisection to invert the VDOT formula.

    Args:
        vdot: The runner's VDOT score.
        distance_m: Race distance in meters.

    Returns:
        Predicted time in seconds, or None if no solution found.
    """
    if vdot <= 0 or distance_m <= 0:
        return None

    # Bisection search: find duration where calculated VDOT matches target
    low_s = (distance_m / 1000.0) * 150.0   # ~2:30/km sprint pace
    high_s = (distance_m / 1000.0) * 600.0  # ~10:00/km slow jog pace

    # Clamp to reasonable bounds
    low_s = max(low_s, 60.0)
    high_s = min(high_s, 86400.0)

    for _ in range(100):  # Binary search iterations
        mid_s = (low_s + high_s) / 2.0
        computed_vdot = calculate_vdot(distance_m, mid_s)
        if computed_vdot is None:
            # If out of formula range, adjust towards center
            high_s = mid_s
            continue
        if abs(computed_vdot - vdot) < 0.01:
            return round(mid_s, 0)
        if computed_vdot > vdot:
            # Running too fast → increase time
            low_s = mid_s
        else:
            high_s = mid_s

    return round((low_s + high_s) / 2.0, 0)


def _format_time(seconds: float | None) -> str | None:
    """Format seconds as H:MM:SS or MM:SS."""
    if seconds is None:
        return None
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _format_pace(seconds_per_km: float) -> str:
    """Format pace as M:SS /km."""
    total = int(round(seconds_per_km))
    m, s = divmod(total, 60)
    return f"{m}:{s:02d} /km"


def _is_quality_effort(run: dict[str, Any]) -> tuple[bool, float, str]:
    """Determine if a run represents a meaningful fitness effort.

    Returns:
        (is_quality, confidence, source_label)
    """
    distance_m = float(run.get("distance_m") or 0)
    duration_s = float(run.get("duration_s") or 0)
    avg_hr = run.get("average_heartrate")

    if distance_m < 2000 or duration_s < 600:
        return False, 0.0, "too_short"

    pace_per_km = duration_s / (distance_m / 1000.0)

    # Long runs (>8km) are useful even at easy effort
    if distance_m >= 8000:
        confidence = 0.6 if avg_hr is None else 0.75
        return True, confidence, "long_run"

    # If we have HR data, filter by effort level
    if avg_hr is not None and isinstance(avg_hr, (int, float)):
        hr = float(avg_hr)
        # Rough heuristic: >140 bpm suggests moderate+ effort for most adults.
        # This is imprecise without knowing max HR, but catches easy recovery jogs.
        if hr > 135:
            return True, 0.85, "quality_effort"
        elif hr > 120:
            return True, 0.5, "moderate_effort"
        else:
            return False, 0.0, "recovery_jog"

    # No HR: accept runs with reasonable pace and distance > 3km
    if distance_m >= 3000 and 180 < pace_per_km < 480:
        return True, 0.5, "moderate_effort"

    return False, 0.3, "uncertain"


def estimate_vdot(
    activities: list[dict[str, Any]],
    days: int = 42,
    now: datetime | None = None,
) -> VdotEstimate:
    """Estimate current VDOT from recent running activities.

    Uses exponential decay weighting so recent runs matter more than older ones.

    Args:
        activities: List of activity dicts from the database.
        days: Number of days of history to consider.
        now: Reference timestamp (defaults to now).

    Returns:
        VdotEstimate with score, predictions, and pace zones.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    samples: list[VdotSample] = []
    halflife_days = 21.0  # Recent runs weighted 2x vs 3-week-old runs

    for activity in activities:
        if str(activity.get("type") or "").lower() != "running":
            continue

        distance_m = activity.get("distance_m")
        duration_s = activity.get("duration_s")
        if not isinstance(distance_m, (int, float)) or not isinstance(duration_s, (int, float)):
            continue

        start_str = activity.get("start_date")
        if not start_str:
            continue
        try:
            start = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            start = start.astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue

        age_days = (now - start).total_seconds() / 86400
        if age_days < 0 or age_days > days:
            continue

        is_quality, base_confidence, source = _is_quality_effort(activity)
        if not is_quality:
            continue

        vdot = calculate_vdot(float(distance_m), float(duration_s))
        if vdot is None:
            continue

        # Exponential decay: more recent runs get higher weight
        time_weight = math.exp(-math.log(2) * age_days / halflife_days)
        confidence = base_confidence * time_weight

        pace_per_km = float(duration_s) / (float(distance_m) / 1000.0)

        samples.append(VdotSample(
            vdot=vdot,
            date=start,
            distance_m=float(distance_m),
            duration_s=float(duration_s),
            pace_per_km=pace_per_km,
            confidence=confidence,
            source=source,
        ))

    if not samples:
        return VdotEstimate(
            estimated_vdot=None,
            sample_count=0,
            confidence="low",
            race_predictions={},
            pace_zones={},
            samples=[],
            trend=None,
        )

    # Weighted average VDOT, using confidence as weight
    total_weight = sum(s.confidence for s in samples)
    if total_weight <= 0:
        weighted_vdot = sum(s.vdot for s in samples) / len(samples)
    else:
        weighted_vdot = sum(s.vdot * s.confidence for s in samples) / total_weight

    weighted_vdot = round(weighted_vdot, 1)

    # Determine confidence level
    if len(samples) >= 6:
        confidence_level = "high"
    elif len(samples) >= 3:
        confidence_level = "moderate"
    else:
        confidence_level = "low"

    # Race predictions
    race_distances = {
        "5k": 5000,
        "10k": 10000,
        "half_marathon": 21097.5,
        "marathon": 42195,
    }
    race_predictions = {}
    for name, dist in race_distances.items():
        predicted = predict_race_time(weighted_vdot, dist)
        formatted = _format_time(predicted)
        if formatted:
            race_predictions[name] = formatted

    # Daniels pace zones from VDOT
    pace_zones = _calculate_pace_zones(weighted_vdot)

    # Trend detection: compare first half vs second half of samples
    trend = _detect_vdot_trend(samples)

    return VdotEstimate(
        estimated_vdot=weighted_vdot,
        sample_count=len(samples),
        confidence=confidence_level,
        race_predictions=race_predictions,
        pace_zones=pace_zones,
        samples=sorted(samples, key=lambda s: s.date, reverse=True),
        trend=trend,
    )


def _calculate_pace_zones(vdot: float) -> dict[str, str]:
    """Calculate Daniels training pace zones from VDOT.

    These are approximate — Daniels publishes tables with per-VDOT values, but
    a formula-based approach is close enough for plan generation.
    """
    if vdot <= 0:
        return {}

    # Easy pace: ~59-74% VO2max → roughly VDOT at 65% effort
    easy_vdot = vdot * 0.65
    easy_time_5k = predict_race_time(easy_vdot, 5000)
    easy_pace = (easy_time_5k / (5000 / 1000)) if easy_time_5k else None

    # Marathon pace: predict from VDOT directly
    marathon_time = predict_race_time(vdot, 42195)
    marathon_pace = (marathon_time / (42195 / 1000)) if marathon_time else None

    # Threshold/tempo pace: ~83-88% VO2max, roughly 60-min race effort
    tempo_time = predict_race_time(vdot, 10000)  # Approximate threshold pace
    tempo_pace = (tempo_time / (10000 / 1000)) if tempo_time else None

    # Interval pace: roughly 5K race pace
    interval_time = predict_race_time(vdot, 5000)
    interval_pace = (interval_time / (5000 / 1000)) if interval_time else None

    # Repetition pace: roughly mile race pace
    rep_time = predict_race_time(vdot, 1609)
    rep_pace = (rep_time / (1609 / 1000)) if rep_time else None

    zones = {}
    if easy_pace:
        easy_slow = easy_pace * 1.08  # 8% slower end of easy range
        zones["easy"] = f"{_format_pace(easy_pace)} to {_format_pace(easy_slow)}"
    if marathon_pace:
        zones["marathon"] = _format_pace(marathon_pace)
    if tempo_pace:
        zones["tempo"] = _format_pace(tempo_pace)
    if interval_pace:
        zones["interval"] = _format_pace(interval_pace)
    if rep_pace:
        zones["repetition"] = _format_pace(rep_pace)

    return zones


def _detect_vdot_trend(samples: list[VdotSample]) -> str | None:
    """Detect whether VDOT is trending up, down, or stable.

    Compares the weighted average of the newer half of samples to the older half.
    """
    if len(samples) < 4:
        return None

    sorted_samples = sorted(samples, key=lambda s: s.date)
    mid = len(sorted_samples) // 2
    older = sorted_samples[:mid]
    newer = sorted_samples[mid:]

    avg_old = sum(s.vdot for s in older) / len(older)
    avg_new = sum(s.vdot for s in newer) / len(newer)

    diff = avg_new - avg_old
    # VDOT changes of ~0.5 or more over a few weeks are meaningful
    if diff > 0.5:
        return "improving"
    elif diff < -0.5:
        return "declining"
    return "stable"
