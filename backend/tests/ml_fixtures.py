"""Synthetic athletes for ML tests, built from domain objects (no database).

`learnable_athlete` hides two real effects that the VDOT baseline can't see:
  1. fitness keeps improving, so VDOT from older efforts lags behind;
  2. short long-runs hurt long races (VDOT famously over-predicts marathons for runners
     who skip long runs).
A good correction model should find both; on pure noise it should find nothing.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, date, datetime, timedelta

from coach.domain.fitness import Performance
from coach.domain.history import DailyHistory, daily_history
from coach.domain.models import Workout, WorkoutType
from coach.domain.vdot import race_time_for_vdot

START = date(2025, 1, 6)  # a Monday
DAYS = 560
RACE_DISTANCES = (5_000, 10_000, 21_097.5, 42_195)


def _workout(day: date, distance_m: float, trimp: float) -> Workout:
    return Workout(id=f"w-{day}", title="Run", type=WorkoutType.EASY,
                   start_at=datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
                   distance_m=distance_m, duration_s=distance_m * 0.33, avg_hr=145,
                   max_hr=160, elevation_gain_m=None, energy_kcal=None, avg_cadence=None,
                   temperature_c=None, trimp=trimp)


def _long_run_km(day_index: int) -> float:
    """Long-run length cycles between ~10 km and ~30 km over ~5-month blocks."""
    return 20 + 10 * math.sin(day_index / 25)


def learnable_athlete(seed: int = 7, *, effects: bool = True, start: date = START
                      ) -> tuple[list[Workout], list[Performance], DailyHistory]:
    rng = random.Random(seed)
    workouts, performances = [], []
    for i in range(DAYS):
        day = start + timedelta(days=i)
        true_vdot = 44 + 8 * i / DAYS if effects else 48.0
        if day.weekday() == 6:  # Sunday long run
            workouts.append(_workout(day, _long_run_km(i) * 1000, 120))
        elif day.weekday() in (1, 3, 5):
            workouts.append(_workout(day, 9_000, 80))
        if i > 30 and i % 9 == 4:  # a race-quality effort every ~9 days
            distance = RACE_DISTANCES[(i // 9) % len(RACE_DISTANCES)]
            time_s = race_time_for_vdot(true_vdot, distance)
            if effects:
                longest_8w = max(_long_run_km(j) for j in range(max(i - 56, 0), i)) * 1000
                shortfall = max(0.0, 1 - longest_8w / distance)
                time_s *= math.exp(0.10 * shortfall * math.log2(distance / 5_000))
            performances.append(Performance(day, distance, time_s * rng.uniform(0.99, 1.01)))
    return workouts, performances, daily_history(workouts, start + timedelta(days=DAYS))
