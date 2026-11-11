"""Data-access seam: everything above this module is unaware of where data comes from.

Serves imported Apple Health data. Until the first import it falls back to the
synthetic demo athlete, so the UI is never empty.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta, timezone
from functools import lru_cache

from sqlalchemy import select

from coach import config
from coach.demo import generator
from coach.domain.classify import (
    ASSUMED_HRR_WITHOUT_HR,
    classify_run,
    derive_profile,
    run_title,
)
from coach.domain.models import AthleteProfile, Goal, HealthSample, Workout
from coach.domain.training_load import trimp
from coach.schemas import DataSource
from coach.storage.database import session_scope
from coach.storage.tables import HealthMetricRow, WorkoutRow


@dataclass(frozen=True, slots=True)
class _Snapshot:
    profile: AthleteProfile
    workouts: tuple[Workout, ...]  # oldest first
    health: tuple[HealthSample, ...]


def today() -> date:
    return date.today()


def invalidate() -> None:
    """Drop cached data; call after anything writes workouts or health metrics."""
    _imported.cache_clear()


@lru_cache(maxsize=1)
def _imported() -> _Snapshot | None:
    """Everything imported, converted to domain objects. None until the first import."""
    with session_scope() as session:
        rows = session.scalars(select(WorkoutRow).order_by(WorkoutRow.start_at)).all()
        if not rows:
            return None
        metrics = session.scalars(
            select(HealthMetricRow).order_by(HealthMetricRow.day)).all()

    health = tuple(HealthSample(day=m.day, type=m.type, value=m.value, unit=m.unit)
                   for m in metrics)
    profile = derive_profile(
        config.athlete_name(),
        resting_hr_readings=[h.value for h in health if h.type == "resting_hr"],
        workout_heart_rates=[(r.avg_hr, r.max_hr) for r in rows if r.avg_hr and r.max_hr],
    )
    median_distance = statistics.median(r.distance_m for r in rows)
    return _Snapshot(profile=profile,
                     workouts=tuple(_to_workout(r, profile, median_distance) for r in rows),
                     health=health)


def _to_workout(row: WorkoutRow, profile: AthleteProfile, median_distance_m: float) -> Workout:
    workout_type = classify_run(row.distance_m, row.avg_hr, profile, median_distance_m)
    reserve = profile.max_hr - profile.resting_hr
    load_hr = row.avg_hr or profile.resting_hr + ASSUMED_HRR_WITHOUT_HR * reserve
    local_tz = timezone(timedelta(minutes=row.utc_offset_min))
    return Workout(
        id=row.id,
        title=run_title(workout_type, row.distance_m, row.indoor),
        type=workout_type,
        start_at=row.start_at.astimezone(local_tz),  # .date() is the day it was run locally
        distance_m=row.distance_m,
        duration_s=row.duration_s,
        avg_hr=_rounded(row.avg_hr),
        max_hr=_rounded(row.max_hr),
        elevation_gain_m=row.elevation_gain_m,
        energy_kcal=row.energy_kcal,
        avg_cadence=_rounded(row.avg_cadence),
        temperature_c=row.temperature_c,
        trimp=round(trimp(row.duration_s, load_hr, profile.resting_hr, profile.max_hr,
                          profile.sex_factor), 1),
        # Splits need per-second samples (GPX + HR records): Phase 2.
    )


def _rounded(value: float | None) -> int | None:
    return round(value) if value is not None else None


# ---------- Public API (unchanged since Phase 0) ----------------------------------

def data_source() -> DataSource:
    return "apple_health" if _imported() else "demo"


def get_profile() -> AthleteProfile:
    snapshot = _imported()
    return snapshot.profile if snapshot else generator.PROFILE


def get_workouts() -> tuple[Workout, ...]:
    """All workouts, oldest first."""
    snapshot = _imported()
    return snapshot.workouts if snapshot else _demo_workouts(today())


def get_workout(workout_id: str) -> Workout | None:
    return next((w for w in get_workouts() if w.id == workout_id), None)


def get_health_samples() -> tuple[HealthSample, ...]:
    snapshot = _imported()
    return snapshot.health if snapshot else _demo_health(today())


def get_goal() -> Goal:
    # Goals become user-editable in Phase 4; until then every athlete gets the default.
    return generator.demo_goal(today())


@lru_cache(maxsize=2)
def _demo_workouts(day: date) -> tuple[Workout, ...]:
    return tuple(generator.generate_workouts(day))


@lru_cache(maxsize=2)
def _demo_health(day: date) -> tuple[HealthSample, ...]:
    return tuple(generator.generate_health_samples(day))
