"""Daniels & Gilbert VDOT model: fitness from performances, race equivalents, pace zones.

Velocity v is in metres/minute and time t in minutes inside the formulas;
the public API speaks metres and seconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MARATHON_M = 42_195.0


def _vo2_cost(v_m_per_min: float) -> float:
    """Oxygen cost (ml/kg/min) of running at velocity v."""
    return -4.60 + 0.182258 * v_m_per_min + 0.000104 * v_m_per_min**2


def _sustainable_fraction(t_min: float) -> float:
    """Fraction of VO2max sustainable for a race lasting t minutes."""
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def _velocity_for_vo2(vo2: float) -> float:
    """Invert _vo2_cost: velocity (m/min) that costs `vo2`."""
    a, b, c = 0.000104, 0.182258, -(4.60 + vo2)
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def vdot_from_performance(distance_m: float, duration_s: float) -> float:
    """VDOT implied by covering `distance_m` in `duration_s` at race effort."""
    if distance_m <= 0 or duration_s <= 0:
        raise ValueError("distance and duration must be positive")
    t_min = duration_s / 60
    return _vo2_cost(distance_m / t_min) / _sustainable_fraction(t_min)


def race_time_for_vdot(vdot: float, distance_m: float) -> float:
    """Equivalent race time (s) for `distance_m` at a given VDOT, via bisection.

    vdot_from_performance is strictly decreasing in time, so bisection is safe.
    """
    lo, hi = 60.0, 60.0 * 60 * 12
    for _ in range(80):
        mid = (lo + hi) / 2
        if vdot_from_performance(distance_m, mid) > vdot:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def pace_at_fraction(vdot: float, fraction: float) -> float:
    """Pace (s/km) when running at `fraction` of VO2max."""
    return 60_000 / _velocity_for_vo2(vdot * fraction)


@dataclass(frozen=True, slots=True)
class PaceZone:
    key: str
    name: str
    purpose: str
    fast_s_per_km: float
    slow_s_per_km: float


# key, name, purpose, low %VO2max, high %VO2max (marathon handled separately)
_ZONE_FRACTIONS: tuple[tuple[str, str, str, float, float], ...] = (
    ("easy", "Easy", "Aerobic base, recovery, and long runs", 0.65, 0.74),
    ("threshold", "Threshold", "Comfortably hard, sustainable ~60 min", 0.86, 0.88),
    ("interval", "Interval", "VO2max development, 3-5 min repeats", 0.95, 1.00),
    ("repetition", "Repetition", "Speed and economy, short fast reps", 1.03, 1.07),
)
_MARATHON_BAND = 0.015  # +/- 1.5% around goal marathon pace


def training_paces(vdot: float) -> list[PaceZone]:
    """Daniels training zones ordered easy -> repetition."""
    zones = [
        PaceZone(key, name, purpose, pace_at_fraction(vdot, hi), pace_at_fraction(vdot, lo))
        for key, name, purpose, lo, hi in _ZONE_FRACTIONS
    ]
    marathon_pace = race_time_for_vdot(vdot, MARATHON_M) / (MARATHON_M / 1000)
    zones.insert(
        1,
        PaceZone(
            "marathon",
            "Marathon",
            "Goal marathon pace, steady and controlled",
            marathon_pace * (1 - _MARATHON_BAND),
            marathon_pace * (1 + _MARATHON_BAND),
        ),
    )
    return zones
