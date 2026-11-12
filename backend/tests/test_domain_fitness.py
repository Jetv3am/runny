"""Which performances count towards VDOT, and how they're weighted."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from coach.domain.fitness import Performance, estimate_vdot, race_quality_performances
from coach.domain.models import AthleteProfile, BestEffort, Workout, WorkoutType
from coach.domain.vdot import vdot_from_performance

PROFILE = AthleteProfile(name="T", resting_hr=50, max_hr=190)  # race HR (85%) = 169
TODAY = date(2026, 11, 10)


def _effort(workout_id: str, avg_hr: int | None, seconds: float = 1_200) -> BestEffort:
    return BestEffort(workout_id, TODAY, "5k", "5K", 5_000, seconds, avg_hr)


def _race(workout_id: str) -> Workout:
    return Workout(id=workout_id, title="10K Race", type=WorkoutType.RACE,
                   start_at=datetime(2026, 11, 1, 8, tzinfo=UTC), distance_m=10_000,
                   duration_s=2_500, avg_hr=172, max_hr=182, elevation_gain_m=None,
                   energy_kcal=None, avg_cadence=None, temperature_c=None, trimp=150)


def test_training_efforts_count_only_at_race_heart_rate():
    efforts = [_effort("hard", 172), _effort("tempo", 160), _effort("no-hr", None)]
    kept = race_quality_performances([], efforts, PROFILE)
    # Only the 172 bpm one, and it's flagged as a training effort, not a race.
    assert kept == [Performance(TODAY, 5_000, 1_200, is_race=False)]


def test_a_race_is_not_counted_twice_through_its_own_best_effort():
    race = _race("race")
    kept = race_quality_performances([race], [_effort("race", 175, 1_180)], PROFILE)
    assert kept == [Performance(race.day, 10_000, 2_500)]


def test_estimate_ignores_short_and_stale_performances():
    fresh = Performance(TODAY, 5_000, 1_200)
    short = Performance(TODAY, 1_000, 200)  # a blistering 1K says little about VO2max
    stale = Performance(date(2026, 1, 1), 10_000, 2_000)  # outside 120 days
    assert estimate_vdot([fresh, short, stale], TODAY) == pytest.approx(
        vdot_from_performance(5_000, 1_200))


def test_cold_start_is_none():
    assert estimate_vdot([], TODAY) is None
