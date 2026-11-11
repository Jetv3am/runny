"""Current-fitness estimation from recent race-effort performances."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date

from coach.domain.models import Workout
from coach.domain.vdot import vdot_from_performance

LOOKBACK_DAYS = 120
DECAY_DAYS = 45  # weight halves roughly every ~31 days (e-folding at 45)
TOP_N = 3
MIN_EFFORT_M = 3_000


def estimate_vdot(workouts: Iterable[Workout], as_of: date) -> float | None:
    """Recency-weighted mean VDOT of the top-N race efforts in the lookback window.

    Returns None when there is no qualifying effort (cold start).
    """
    efforts: list[tuple[float, float]] = []  # (vdot, recency weight)
    for w in workouts:
        age = (as_of - w.day).days
        if not w.is_race or w.distance_m < MIN_EFFORT_M or not 0 <= age <= LOOKBACK_DAYS:
            continue
        efforts.append((vdot_from_performance(w.distance_m, w.duration_s),
                        math.exp(-age / DECAY_DAYS)))
    if not efforts:
        return None
    top = sorted(efforts, key=lambda e: e[0] * e[1], reverse=True)[:TOP_N]
    return sum(v * wt for v, wt in top) / sum(wt for _, wt in top)
