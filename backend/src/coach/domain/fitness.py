"""Current-fitness estimation from recent race-quality performances."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from coach.domain.classify import HRR_RACE, heart_rate_reserve
from coach.domain.models import AthleteProfile, BestEffort, Workout
from coach.domain.vdot import vdot_from_performance

LOOKBACK_DAYS = 120
DECAY_DAYS = 45  # weight halves roughly every ~31 days (e-folding at 45)
TOP_N = 3
MIN_EFFORT_M = 3_000  # shorter efforts say more about speed than aerobic fitness


@dataclass(frozen=True, slots=True)
class Performance:
    day: date
    distance_m: float
    duration_s: float
    is_race: bool = True  # False: a race-effort stretch inside a training run


def race_quality_performances(workouts: Sequence[Workout], efforts: Iterable[BestEffort],
                              profile: AthleteProfile) -> list[Performance]:
    """Races, plus training efforts whose heart rate shows they were run at race effort.

    VDOT assumes an all-out performance. A 5K inside an easy run would drag the
    estimate down; one run at race heart rate is as good as a race result.
    (Plausibility over rank again: the heart rate vouches for the effort.)
    """
    races = [w for w in workouts if w.is_race]
    race_ids = {w.id for w in races}
    hard_efforts = [e for e in efforts
                    if e.workout_id not in race_ids and e.avg_hr is not None
                    and heart_rate_reserve(e.avg_hr, profile) >= HRR_RACE]
    return ([Performance(w.day, w.distance_m, w.duration_s) for w in races]
            + [Performance(e.day, e.distance_m, e.duration_s, is_race=False)
               for e in hard_efforts])


def estimate_vdot(performances: Iterable[Performance], as_of: date) -> float | None:
    """Recency-weighted mean VDOT of the top-N performances in the lookback window.

    Returns None when there is no qualifying performance (cold start).
    """
    scored: list[tuple[float, float]] = []  # (vdot, recency weight)
    for p in performances:
        age = (as_of - p.day).days
        if p.distance_m < MIN_EFFORT_M or not 0 <= age <= LOOKBACK_DAYS:
            continue
        scored.append((vdot_from_performance(p.distance_m, p.duration_s),
                       math.exp(-age / DECAY_DAYS)))
    if not scored:
        return None
    top = sorted(scored, key=lambda s: s[0] * s[1], reverse=True)[:TOP_N]
    return sum(v * wt for v, wt in top) / sum(wt for _, wt in top)
