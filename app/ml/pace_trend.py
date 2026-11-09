"""Pace trend analysis using linear regression.

Detects whether a runner's fitness is improving, stable, or declining by
fitting a regression line to pace data over a rolling window. When heart
rate data is available, pace is normalized by HR to isolate real fitness
changes from confounding factors (heat, hills, fatigue).

Uses scikit-learn's LinearRegression when available, falls back to a
manual OLS implementation so the module works without the dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from sklearn.linear_model import LinearRegression
    import numpy as np
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False


@dataclass
class PaceTrend:
    """Result of pace trend analysis."""
    direction: str              # 'improving', 'stable', 'declining'
    rate_sec_per_km_per_week: float | None  # Negative = getting faster
    r_squared: float | None     # Goodness of fit (0–1)
    confidence: str             # 'low', 'moderate', 'high'
    data_points: int
    window_days: int
    easy_pace_trend: dict | None     # Trend for easy/recovery runs
    quality_pace_trend: dict | None  # Trend for tempo/harder runs
    pace_history: list[dict]    # For charting: [{date, pace_per_km, adjusted_pace, hr}]


@dataclass
class _PacePoint:
    """Internal: a single pace data point."""
    date: datetime
    day_offset: float  # Days since start of window
    pace_per_km: float  # Seconds per km
    adjusted_pace: float  # HR-adjusted pace (or raw if no HR)
    avg_hr: float | None
    distance_m: float
    is_easy: bool


def _cardiac_adjusted_pace(pace_s_per_km: float, avg_hr: float, reference_hr: float = 150.0) -> float:
    """Normalize pace by heart rate to remove weather/terrain effects.

    The idea: if you ran the same pace but at a higher HR today vs last week,
    your "cardiac-adjusted pace" is faster (you're less fit today, or it was
    hotter). This isolates fitness from external conditions.

    Args:
        pace_s_per_km: Actual pace in seconds per km.
        avg_hr: Average heart rate during the run.
        reference_hr: Reference HR to normalize to.

    Returns:
        Adjusted pace in seconds per km.
    """
    if avg_hr <= 0:
        return pace_s_per_km
    # Pace adjustment: scale pace proportionally to HR difference from reference
    # Higher HR at same pace → adjusted pace is faster (worse fitness signal)
    hr_ratio = reference_hr / avg_hr
    return pace_s_per_km * hr_ratio


def _linear_regression_manual(x: list[float], y: list[float]) -> tuple[float, float, float]:
    """Simple OLS linear regression fallback when sklearn is not available.

    Returns:
        (slope, intercept, r_squared)
    """
    n = len(x)
    if n < 2:
        return 0.0, 0.0, 0.0

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    ss_xx = sum((xi - mean_x) ** 2 for xi in x)
    ss_yy = sum((yi - mean_y) ** 2 for yi in y)
    ss_xy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))

    if ss_xx == 0:
        return 0.0, mean_y, 0.0

    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    if ss_yy == 0:
        r_squared = 1.0 if ss_xy == 0 else 0.0
    else:
        r_squared = (ss_xy ** 2) / (ss_xx * ss_yy)

    return slope, intercept, r_squared


def _fit_regression(x_values: list[float], y_values: list[float]) -> tuple[float, float, float]:
    """Fit linear regression using sklearn if available, else manual OLS."""
    if _HAS_SKLEARN and len(x_values) >= 2:
        X = np.array(x_values).reshape(-1, 1)
        y = np.array(y_values)
        model = LinearRegression()
        model.fit(X, y)
        slope = float(model.coef_[0])
        intercept = float(model.intercept_)
        y_pred = model.predict(X)
        ss_res = float(np.sum((y - y_pred) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
        return slope, intercept, r_squared
    return _linear_regression_manual(x_values, y_values)


def _classify_effort(activity: dict[str, Any]) -> bool:
    """Classify whether a run is 'easy' based on HR and pace heuristics."""
    avg_hr = activity.get("average_heartrate")
    if isinstance(avg_hr, (int, float)) and float(avg_hr) > 0:
        # Below ~145 bpm is typically easy for most recreational runners
        return float(avg_hr) < 145

    # No HR: assume easy if pace > 5:30/km
    distance_m = float(activity.get("distance_m") or 0)
    duration_s = float(activity.get("duration_s") or 0)
    if distance_m > 0 and duration_s > 0:
        pace = duration_s / (distance_m / 1000)
        return pace > 330  # 5:30/km
    return True


def _compute_sub_trend(points: list[_PacePoint]) -> dict | None:
    """Compute trend for a subset of pace points."""
    if len(points) < 3:
        return None

    weeks = [p.day_offset / 7.0 for p in points]
    paces = [p.adjusted_pace for p in points]

    slope, _, r_sq = _fit_regression(weeks, paces)

    # Slope is in sec/km per week. Negative = getting faster.
    if slope < -1.5 and r_sq > 0.15:
        direction = "improving"
    elif slope > 1.5 and r_sq > 0.15:
        direction = "declining"
    else:
        direction = "stable"

    return {
        "direction": direction,
        "rate_sec_per_km_per_week": round(slope, 2),
        "r_squared": round(r_sq, 3),
        "data_points": len(points),
    }


def analyze_pace_trend(
    activities: list[dict[str, Any]],
    window_days: int = 42,
    now: datetime | None = None,
) -> PaceTrend:
    """Analyze pace trends from running activities.

    Args:
        activities: List of activity dicts from the database.
        window_days: Number of days to look back.
        now: Reference timestamp (defaults to now).

    Returns:
        PaceTrend with direction, rate, and confidence.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=window_days)

    points: list[_PacePoint] = []

    for activity in activities:
        if str(activity.get("type") or "").lower() != "running":
            continue

        distance_m = activity.get("distance_m")
        duration_s = activity.get("duration_s")
        if not isinstance(distance_m, (int, float)) or not isinstance(duration_s, (int, float)):
            continue
        if float(distance_m) < 1500 or float(duration_s) < 300:
            continue  # Skip very short runs

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

        if start < cutoff or start > now:
            continue

        pace_per_km = float(duration_s) / (float(distance_m) / 1000.0)
        # Filter out unreasonable paces
        if pace_per_km < 150 or pace_per_km > 600:
            continue

        avg_hr = activity.get("average_heartrate")
        if isinstance(avg_hr, (int, float)) and float(avg_hr) > 0:
            adjusted = _cardiac_adjusted_pace(pace_per_km, float(avg_hr))
            hr_val = float(avg_hr)
        else:
            adjusted = pace_per_km
            hr_val = None

        day_offset = (start - cutoff).total_seconds() / 86400.0
        is_easy = _classify_effort(activity)

        points.append(_PacePoint(
            date=start,
            day_offset=day_offset,
            pace_per_km=pace_per_km,
            adjusted_pace=adjusted,
            avg_hr=hr_val,
            distance_m=float(distance_m),
            is_easy=is_easy,
        ))

    if len(points) < 3:
        return PaceTrend(
            direction="insufficient_data",
            rate_sec_per_km_per_week=None,
            r_squared=None,
            confidence="low",
            data_points=len(points),
            window_days=window_days,
            easy_pace_trend=None,
            quality_pace_trend=None,
            pace_history=[],
        )

    # Sort by date
    points.sort(key=lambda p: p.date)

    # Overall trend on adjusted pace
    weeks = [p.day_offset / 7.0 for p in points]
    paces = [p.adjusted_pace for p in points]
    slope, _, r_squared = _fit_regression(weeks, paces)

    # Convert slope from sec/km per week-number to sec/km per week
    rate = round(slope, 2)

    # Determine direction and confidence
    if r_squared is not None and r_squared > 0.3:
        confidence = "high"
    elif r_squared is not None and r_squared > 0.1:
        confidence = "moderate"
    else:
        confidence = "low"

    if rate < -1.5 and confidence != "low":
        direction = "improving"  # Getting faster
    elif rate > 1.5 and confidence != "low":
        direction = "declining"  # Getting slower
    else:
        direction = "stable"

    # Sub-trends for easy vs quality runs
    easy_points = [p for p in points if p.is_easy]
    quality_points = [p for p in points if not p.is_easy]

    easy_trend = _compute_sub_trend(easy_points)
    quality_trend = _compute_sub_trend(quality_points)

    # Build pace history for charting
    pace_history = [
        {
            "date": p.date.isoformat(),
            "pace_per_km": round(p.pace_per_km, 1),
            "adjusted_pace": round(p.adjusted_pace, 1),
            "avg_hr": round(p.avg_hr, 0) if p.avg_hr else None,
            "distance_km": round(p.distance_m / 1000, 2),
            "is_easy": p.is_easy,
        }
        for p in points
    ]

    return PaceTrend(
        direction=direction,
        rate_sec_per_km_per_week=rate,
        r_squared=round(r_squared, 3) if r_squared is not None else None,
        confidence=confidence,
        data_points=len(points),
        window_days=window_days,
        easy_pace_trend=easy_trend,
        quality_pace_trend=quality_trend,
        pace_history=pace_history,
    )
