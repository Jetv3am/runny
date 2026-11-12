"""Core domain records. Units: metres, seconds, UTC datetimes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class WorkoutType(StrEnum):
    EASY = "easy"
    LONG = "long"
    TEMPO = "tempo"
    INTERVAL = "interval"
    RECOVERY = "recovery"
    RACE = "race"


QUALITY_TYPES = frozenset({WorkoutType.TEMPO, WorkoutType.INTERVAL, WorkoutType.RACE})


@dataclass(frozen=True, slots=True)
class AthleteProfile:
    name: str
    resting_hr: int
    max_hr: int
    sex_factor: float = 1.92  # Banister TRIMP weighting: 1.92 male, 1.67 female


@dataclass(frozen=True, slots=True)
class Split:
    index: int
    distance_m: float
    duration_s: float
    avg_hr: int | None
    elevation_delta_m: float | None  # None: the samples carry no elevation

    @property
    def pace_s_per_km(self) -> float:
        return pace_s_per_km(self.distance_m, self.duration_s)


@dataclass(frozen=True, slots=True)
class BestEffort:
    """Fastest stretch of one standard distance inside one run (or the whole race)."""
    workout_id: str
    day: date
    distance_key: str
    label: str
    distance_m: float
    duration_s: float
    avg_hr: int | None

    @property
    def pace_s_per_km(self) -> float:
        return pace_s_per_km(self.distance_m, self.duration_s)


@dataclass(frozen=True, slots=True)
class Workout:
    id: str
    title: str
    type: WorkoutType
    start_at: datetime
    distance_m: float
    duration_s: float
    avg_hr: int | None
    max_hr: int | None
    elevation_gain_m: float | None  # None = not recorded (e.g. treadmill), not "flat"
    energy_kcal: float | None
    avg_cadence: int | None
    temperature_c: float | None
    trimp: float
    splits: tuple[Split, ...] = field(default_factory=tuple)

    @property
    def is_race(self) -> bool:
        return self.type is WorkoutType.RACE

    @property
    def day(self) -> date:
        return self.start_at.date()

    @property
    def pace_s_per_km(self) -> float:
        return pace_s_per_km(self.distance_m, self.duration_s)


@dataclass(frozen=True, slots=True)
class HealthSample:
    day: date
    type: str  # "vo2max" | "resting_hr"
    value: float
    unit: str


@dataclass(frozen=True, slots=True)
class Goal:
    race_label: str
    distance_m: float
    race_date: date
    target_time_s: float | None


def pace_s_per_km(distance_m: float, duration_s: float) -> float:
    """Average pace in seconds per kilometre; 0 for zero distance."""
    return duration_s / (distance_m / 1000) if distance_m > 0 else 0.0
