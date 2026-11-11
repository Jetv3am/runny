"""Deterministic synthetic training history for a demo athlete.

Paces and race results are derived from a 'true' VDOT that improves over the
block, so downstream physiology maths produces realistic numbers.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, date, datetime, time, timedelta

from coach.domain.classify import WORKOUT_TITLES
from coach.domain.models import AthleteProfile, Goal, HealthSample, Split, Workout, WorkoutType
from coach.domain.training_load import trimp
from coach.domain.vdot import pace_at_fraction, race_time_for_vdot

PROFILE = AthleteProfile(name="Demo Runner", resting_hr=50, max_hr=190)
HISTORY_DAYS = 182
SEED = 42
BODY_MASS_KG = 70

# weekday -> (type, share of weekly volume)
_WEEK_TEMPLATE: dict[int, tuple[WorkoutType, float]] = {
    1: (WorkoutType.INTERVAL, 0.14),
    2: (WorkoutType.EASY, 0.17),
    3: (WorkoutType.TEMPO, 0.16),
    4: (WorkoutType.RECOVERY, 0.08),
    5: (WorkoutType.EASY, 0.15),
    6: (WorkoutType.LONG, 0.30),
}
# type -> (%VO2max used for average pace, %HR reserve)
_EFFORT: dict[WorkoutType, tuple[float, float]] = {
    WorkoutType.RECOVERY: (0.62, 0.58),
    WorkoutType.EASY: (0.68, 0.65),
    WorkoutType.LONG: (0.67, 0.68),
    WorkoutType.TEMPO: (0.80, 0.80),
    WorkoutType.INTERVAL: (0.78, 0.83),
}
# weeks-before-today -> (label, distance) for races replacing the Sunday long run
_RACES: dict[int, tuple[str, float]] = {
    20: ("Parkrun 5K", 5_000),
    14: ("City 10K", 10_000),
    8: ("Spring 5K", 5_000),
    3: ("Riverside 10K", 10_000),
}
_RACE_HRR = {5_000: 0.93, 10_000: 0.91}


def _true_vdot(days_ago: int) -> float:
    progress = 1 - days_ago / HISTORY_DAYS
    return 44.0 + 6.0 * progress + 0.4 * math.sin(days_ago / 9)


def _weekly_volume_m(weeks_ago: int) -> float:
    week_index = HISTORY_DAYS // 7 - weeks_ago
    base = 30_000 + 700 * week_index
    return base * (0.8 if week_index % 4 == 3 else 1.0)


def _hr(hrr_fraction: float, rng: random.Random) -> int:
    reserve = PROFILE.max_hr - PROFILE.resting_hr
    return round(PROFILE.resting_hr + hrr_fraction * reserve + rng.uniform(-4, 4))


def _splits(distance_m: float, duration_s: float, avg_hr: int, elevation_m: float,
            wtype: WorkoutType, rng: random.Random) -> tuple[Split, ...]:
    full_km, remainder = divmod(distance_m, 1000)
    lengths = [1000.0] * int(full_km) + ([remainder] if remainder >= 50 else [])
    if not lengths:
        return ()
    avg_pace = duration_s / (distance_m / 1000)
    raw: list[float] = []
    for i in range(len(lengths)):
        if wtype is WorkoutType.INTERVAL:
            factor = 0.92 if i % 2 else 1.08
        elif wtype is WorkoutType.RACE:
            factor = 1.0 - 0.01 * (i / len(lengths))  # slight negative split
        else:
            factor = 1.0
        raw.append(avg_pace * factor * rng.uniform(0.98, 1.02))
    total = sum(p * length / 1000 for p, length in zip(raw, lengths, strict=True))
    scale = duration_s / total  # make splits sum exactly to duration
    return tuple(
        Split(
            index=i + 1,
            distance_m=length,
            duration_s=pace * scale * length / 1000,
            avg_hr=avg_hr + round((i / len(lengths)) * 6) + rng.randint(-3, 3),
            elevation_delta_m=round(rng.uniform(-1, 1) * elevation_m / len(lengths) * 2, 1),
        )
        for i, (pace, length) in enumerate(zip(raw, lengths, strict=True))
    )


def _make_workout(day: date, wtype: WorkoutType, distance_m: float, duration_s: float,
                  hrr: float, title: str, rng: random.Random) -> Workout:
    avg_hr = _hr(hrr, rng)
    elevation = round(distance_m / 1000 * rng.uniform(3, 12), 1)
    start = datetime.combine(day, time(13, rng.randint(0, 59)), tzinfo=UTC)
    season = 16 + 8 * math.sin((day.timetuple().tm_yday - 105) / 365 * 2 * math.pi)
    return Workout(
        id=f"demo-{day.isoformat()}",
        title=title,
        type=wtype,
        start_at=start,
        distance_m=round(distance_m, 1),
        duration_s=round(duration_s),
        avg_hr=avg_hr,
        max_hr=min(PROFILE.max_hr, avg_hr + rng.randint(8, 18)),
        elevation_gain_m=elevation,
        energy_kcal=round(BODY_MASS_KG * distance_m / 1000 * 1.04),
        avg_cadence=rng.randint(166, 182),
        temperature_c=round(season + rng.uniform(-3, 3), 1),
        trimp=round(trimp(duration_s, avg_hr, PROFILE.resting_hr, PROFILE.max_hr,
                          PROFILE.sex_factor), 1),
        splits=_splits(distance_m, duration_s, avg_hr, elevation, wtype, rng),
    )


def generate_workouts(today: date) -> list[Workout]:
    """All demo workouts from HISTORY_DAYS ago up to yesterday, oldest first."""
    rng = random.Random(SEED)
    workouts: list[Workout] = []
    for days_ago in range(HISTORY_DAYS, 0, -1):
        day = today - timedelta(days=days_ago)
        weeks_ago = days_ago // 7
        vdot = _true_vdot(days_ago)
        race = _RACES.get(weeks_ago) if day.weekday() == 6 else None
        if race:
            label, distance = race
            duration = race_time_for_vdot(vdot, distance) * rng.uniform(0.99, 1.01)
            workouts.append(_make_workout(day, WorkoutType.RACE, distance, duration,
                                          _RACE_HRR[int(distance)], label, rng))
            continue
        slot = _WEEK_TEMPLATE.get(day.weekday())
        if slot is None or rng.random() < 0.08:  # rest day or skipped run
            continue
        wtype, share = slot
        distance = _weekly_volume_m(weeks_ago) * share * rng.uniform(0.9, 1.1)
        vo2_fraction, hrr = _EFFORT[wtype]
        duration = pace_at_fraction(vdot, vo2_fraction) * distance / 1000 * rng.uniform(0.98, 1.03)
        title = WORKOUT_TITLES[wtype]
        workouts.append(_make_workout(day, wtype, distance, duration, hrr, title, rng))
    return workouts


def generate_health_samples(today: date) -> list[HealthSample]:
    """Weekly Apple-Watch-style VO2max and resting HR readings."""
    rng = random.Random(SEED + 1)
    samples: list[HealthSample] = []
    for days_ago in range(HISTORY_DAYS, 0, -7):
        day = today - timedelta(days=days_ago)
        progress = 1 - days_ago / HISTORY_DAYS
        samples.append(HealthSample(day, "vo2max",
                                    round(_true_vdot(days_ago) * 1.02 + rng.uniform(-0.6, 0.6), 1),
                                    "ml/kg/min"))
        samples.append(HealthSample(day, "resting_hr",
                                    round(55 - 5 * progress + rng.uniform(-1.5, 1.5)), "bpm"))
    return samples


def demo_goal(today: date) -> Goal:
    """A half marathon ten Sundays from now."""
    race_day = today + timedelta(days=(6 - today.weekday()) + 7 * 9)
    return Goal(race_label="Harbour Half Marathon", distance_m=21_097.5, race_date=race_day,
                target_time_s=1 * 3600 + 40 * 60)
