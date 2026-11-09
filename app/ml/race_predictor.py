"""Race readiness prediction.

Estimates the probability of achieving a target race time given:
- Current VDOT vs required VDOT
- Weeks remaining until race day
- Current training load and improvement trend
- Training consistency

Uses a logistic-style scoring model to produce a 0–100% probability.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from typing import Any

from app.ml.vdot import calculate_vdot, predict_race_time, _format_time


RACE_DISTANCES_M = {
    "5k": 5000,
    "10k": 10000,
    "half_marathon": 21097.5,
    "marathon": 42195,
}


@dataclass
class RacePrediction:
    """Race readiness assessment."""
    goal_name: str
    goal_distance_km: float
    target_time: str | None          # Formatted target time
    target_time_seconds: int | None
    predicted_time: str | None       # Formatted predicted time from current VDOT
    predicted_time_seconds: float | None
    current_vdot: float | None
    required_vdot: float | None      # VDOT needed for target time
    vdot_gap: float | None           # required - current (negative = already fast enough)
    weeks_remaining: int | None
    probability: float               # 0.0 to 1.0
    probability_label: str           # 'very_likely', 'likely', 'possible', 'stretch', 'unlikely'
    assessment: str                  # Human-readable assessment
    factors: dict[str, Any]          # Breakdown of scoring factors


def _required_vdot_for_time(distance_m: float, target_seconds: float) -> float | None:
    """Find the VDOT needed to run a given distance in a target time."""
    return calculate_vdot(distance_m, target_seconds)


def _expected_vdot_improvement(
    current_vdot: float,
    weeks_remaining: int,
    trend_direction: str | None,
    trend_rate: float | None,
    ctl_fitness: float | None,
) -> float:
    """Estimate how much VDOT improvement is realistic over the remaining weeks.

    Based on typical adaptation rates:
    - A beginner can improve ~0.3-0.5 VDOT/week with consistent training
    - An intermediate runner: ~0.1-0.3 VDOT/week
    - An advanced runner: ~0.05-0.1 VDOT/week

    These rates diminish as VDOT increases (diminishing returns).
    """
    # Base weekly improvement rate, scaled by current fitness level
    if current_vdot < 35:
        base_rate = 0.35  # Beginner
    elif current_vdot < 45:
        base_rate = 0.20  # Intermediate
    elif current_vdot < 55:
        base_rate = 0.10  # Advanced
    else:
        base_rate = 0.05  # Elite

    # Adjust based on current trend
    trend_multiplier = 1.0
    if trend_direction == "improving" and trend_rate is not None:
        trend_multiplier = 1.3  # Already on an upward trajectory
    elif trend_direction == "declining":
        trend_multiplier = 0.4  # Things are going wrong
    elif trend_direction == "stable":
        trend_multiplier = 0.8  # Plateaued

    # Adjust for training load: higher CTL = better training stimulus
    if ctl_fitness is not None:
        if ctl_fitness > 60:
            load_multiplier = 1.2
        elif ctl_fitness > 30:
            load_multiplier = 1.0
        elif ctl_fitness > 10:
            load_multiplier = 0.7
        else:
            load_multiplier = 0.4
    else:
        load_multiplier = 0.8

    # Diminishing returns: improvement slows with each passing week
    total_improvement = 0.0
    for week in range(weeks_remaining):
        weekly_gain = base_rate * trend_multiplier * load_multiplier
        # Each week has slightly less marginal gain
        weekly_gain *= math.exp(-0.01 * week)
        total_improvement += weekly_gain

    return round(total_improvement, 2)


def predict_race_readiness(
    current_vdot: float | None,
    goal_type: str,
    target_time_seconds: int | None = None,
    race_date: str | None = None,
    trend_direction: str | None = None,
    trend_rate: float | None = None,
    ctl_fitness: float | None = None,
    runs_in_period: int = 0,
    now: datetime | None = None,
) -> RacePrediction:
    """Predict probability of achieving a race goal.

    Args:
        current_vdot: Athlete's current estimated VDOT.
        goal_type: Race type key (e.g., '5k', '10k', 'half_marathon', 'marathon').
        target_time_seconds: Target finish time in seconds.
        race_date: Race date in YYYY-MM-DD format.
        trend_direction: From pace trend analysis ('improving', 'stable', 'declining').
        trend_rate: Pace change rate in sec/km per week.
        ctl_fitness: Current chronic training load.
        runs_in_period: Number of runs in the analysis period.
        now: Reference timestamp.

    Returns:
        RacePrediction with probability and assessment.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.date()

    distance_m = RACE_DISTANCES_M.get(goal_type, 5000)
    goal_distance_km = round(distance_m / 1000, 2)
    goal_name = goal_type.replace("_", " ").title()

    # Calculate predicted time from current VDOT
    predicted_seconds = predict_race_time(current_vdot, distance_m) if current_vdot else None

    # Calculate required VDOT for target time
    required_vdot = None
    if target_time_seconds:
        required_vdot = _required_vdot_for_time(distance_m, float(target_time_seconds))

    # VDOT gap
    vdot_gap = None
    if current_vdot is not None and required_vdot is not None:
        vdot_gap = round(required_vdot - current_vdot, 1)

    # Weeks remaining
    weeks_remaining = None
    if race_date:
        try:
            race_day = date.fromisoformat(race_date)
            days_remaining = (race_day - today).days
            weeks_remaining = max(0, days_remaining // 7)
        except ValueError:
            pass

    # --- Probability calculation ---
    factors: dict[str, Any] = {}

    if current_vdot is None:
        # Can't predict without VDOT
        return RacePrediction(
            goal_name=goal_name,
            goal_distance_km=goal_distance_km,
            target_time=_format_time(target_time_seconds) if target_time_seconds else None,
            target_time_seconds=target_time_seconds,
            predicted_time=None,
            predicted_time_seconds=None,
            current_vdot=None,
            required_vdot=required_vdot,
            vdot_gap=None,
            weeks_remaining=weeks_remaining,
            probability=0.0,
            probability_label="insufficient_data",
            assessment="Not enough running data to make a prediction. Import more runs to build a fitness baseline.",
            factors={"reason": "no_vdot_estimate"},
        )

    # Factor 1: VDOT gap (most important)
    if target_time_seconds and required_vdot and vdot_gap is not None:
        # How much improvement is expected?
        expected_improvement = _expected_vdot_improvement(
            current_vdot,
            weeks_remaining or 12,
            trend_direction,
            trend_rate,
            ctl_fitness,
        )
        factors["expected_vdot_improvement"] = expected_improvement
        factors["vdot_gap"] = vdot_gap

        if vdot_gap <= 0:
            # Already fast enough
            vdot_probability = min(0.95, 0.85 + abs(vdot_gap) * 0.02)
        elif vdot_gap <= expected_improvement:
            # Gap is within expected improvement range
            vdot_probability = 0.7 - (vdot_gap / expected_improvement) * 0.3
            vdot_probability = max(0.4, vdot_probability)
        elif vdot_gap <= expected_improvement * 1.5:
            # Stretch but possible
            vdot_probability = 0.25
        else:
            # Very unlikely
            vdot_probability = max(0.05, 0.15 - (vdot_gap - expected_improvement * 1.5) * 0.05)
    elif target_time_seconds is None:
        # No target time: just predict finish time
        vdot_probability = 0.8  # High confidence in finishing
    else:
        vdot_probability = 0.5  # Unknown gap

    factors["vdot_probability"] = round(vdot_probability, 2)

    # Factor 2: Training consistency
    if runs_in_period >= 12:
        consistency_factor = 1.0
    elif runs_in_period >= 8:
        consistency_factor = 0.9
    elif runs_in_period >= 4:
        consistency_factor = 0.7
    else:
        consistency_factor = 0.5
    factors["consistency_factor"] = consistency_factor

    # Factor 3: Time to prepare
    if weeks_remaining is not None:
        min_weeks = {
            "5k": 4, "10k": 6, "half_marathon": 10, "marathon": 16,
        }
        needed = min_weeks.get(goal_type, 8)
        if weeks_remaining >= needed * 1.5:
            time_factor = 1.0
        elif weeks_remaining >= needed:
            time_factor = 0.9
        elif weeks_remaining >= needed * 0.6:
            time_factor = 0.7
        else:
            time_factor = 0.4
    else:
        time_factor = 0.8  # Unknown: assume reasonable timeframe
    factors["time_factor"] = time_factor

    # Combined probability
    probability = round(
        vdot_probability * 0.55 +
        consistency_factor * 0.15 +
        time_factor * 0.30,
        2,
    )
    probability = max(0.0, min(1.0, probability))

    # Label
    if probability >= 0.80:
        label = "very_likely"
    elif probability >= 0.60:
        label = "likely"
    elif probability >= 0.40:
        label = "possible"
    elif probability >= 0.20:
        label = "stretch"
    else:
        label = "unlikely"

    # Assessment text
    if target_time_seconds:
        target_str = _format_time(target_time_seconds)
        predicted_str = _format_time(predicted_seconds)

        if vdot_gap is not None and vdot_gap <= 0:
            assessment = (
                f"Your current fitness ({current_vdot} VDOT) already supports a "
                f"{predicted_str} {goal_name}. Your target of {target_str} is within reach "
                f"with a solid race-day effort."
            )
        elif vdot_gap is not None and weeks_remaining is not None:
            assessment = (
                f"You need ~{vdot_gap} VDOT improvement to hit {target_str} for the {goal_name}. "
                f"With {weeks_remaining} weeks of consistent training, "
                f"an improvement of ~{factors.get('expected_vdot_improvement', '?')} VDOT is realistic. "
                f"Current predicted time: {predicted_str}."
            )
        else:
            assessment = (
                f"Current predicted {goal_name} time: {predicted_str}. "
                f"Target: {target_str}. Continue building fitness for a better prediction."
            )
    else:
        predicted_str = _format_time(predicted_seconds)
        assessment = (
            f"Based on your current VDOT of {current_vdot}, your predicted {goal_name} "
            f"time is {predicted_str}. Set a target time for a more detailed readiness assessment."
        )

    return RacePrediction(
        goal_name=goal_name,
        goal_distance_km=goal_distance_km,
        target_time=_format_time(target_time_seconds) if target_time_seconds else None,
        target_time_seconds=target_time_seconds,
        predicted_time=_format_time(predicted_seconds),
        predicted_time_seconds=predicted_seconds,
        current_vdot=current_vdot,
        required_vdot=required_vdot,
        vdot_gap=vdot_gap,
        weeks_remaining=weeks_remaining,
        probability=probability,
        probability_label=label,
        assessment=assessment,
        factors=factors,
    )
