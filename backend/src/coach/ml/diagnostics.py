"""Why each candidate effort was (or wasn't) used to train the race-time model.

The used/not-used decision always comes from the real code (race_quality_performances
and build_examples); this module only explains exclusions, so the report can't drift
from what training does. Easy runs were never candidates and are left out entirely.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from coach.domain.classify import HRR_RACE, heart_rate_reserve, race_label
from coach.domain.fitness import (
    LOOKBACK_DAYS,
    MIN_EFFORT_M,
    Performance,
    race_quality_performances,
)
from coach.domain.history import DailyHistory
from coach.domain.models import AthleteProfile, BestEffort, Workout
from coach.ml.features import build_examples

NEAR_MISS_HRR = 0.75  # below race level, but close enough to be worth listing

# Summary categories (counted); candidates also carry a detailed reason (listed).
NO_BASELINE = f"no race-quality effort in the {LOOKBACK_DAYS} days before"
TOO_SHORT = "shorter than 3 km"
NO_HEART_RATE = "no heart rate recorded (can't tell race effort from easy)"
NEAR_MISS = "heart rate just below race level"
UNEVEN_PACE = "race distance at race heart rate, but pace too uneven for a race"


@dataclass(frozen=True, slots=True)
class Candidate:
    day: date
    kind: str  # Race | Effort (stretch of a training run) | Run (race-distance run)
    label: str
    duration_s: float
    avg_hr: int | None
    used: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class EffortReport:
    profile: AthleteProfile
    race_level_hr: int  # average heart rate at HRR_RACE of the reserve
    candidates: list[Candidate]  # oldest first; only those worth a look are listed
    dropped: Counter[str]  # category -> count, including ones not listed

    @property
    def used(self) -> int:
        return sum(c.used for c in self.candidates)


def explain(workouts: Sequence[Workout], efforts: Sequence[BestEffort],
            profile: AthleteProfile, history: DailyHistory | None) -> EffortReport:
    performances = race_quality_performances(workouts, efforts, profile)
    used = {(e.day, e.distance_m, e.actual_s)
            for e in (build_examples(performances, history) if history else [])}
    avg_hr = {(e.day, e.distance_m): e.avg_hr for e in efforts}
    avg_hr |= {(w.day, w.distance_m): w.avg_hr for w in workouts if w.is_race}
    candidates: list[Candidate] = []
    dropped: Counter[str] = Counter()

    for p in performances:  # qualified as race-quality: used unless short or no baseline
        if p.distance_m < MIN_EFFORT_M:
            dropped[TOO_SHORT] += 1
            continue
        is_used = (p.day, p.distance_m, p.duration_s) in used
        if not is_used:
            dropped[NO_BASELINE] += 1
        candidates.append(Candidate(p.day, "Race" if p.is_race else "Effort", _label(p),
                                    p.duration_s, avg_hr.get((p.day, p.distance_m)), is_used,
                                    "" if is_used else NO_BASELINE))

    race_ids = {w.id for w in workouts if w.is_race}
    unraced = [w for w in workouts if w.id not in race_ids and race_label(w.distance_m)]
    for w in unraced:  # whole runs at a race distance that weren't races: missed races?
        hrr = _hrr(w.avg_hr, profile)
        if hrr is not None and hrr >= HRR_RACE:
            reason = f"{UNEVEN_PACE} (classified as {w.type.value})"
            category = UNEVEN_PACE
        else:
            category, reason = _below_race_level(hrr)
        if category:
            dropped[category] += 1
            if reason:
                candidates.append(Candidate(w.day, "Run", race_label(w.distance_m) or "",
                                            w.duration_s, w.avg_hr, False,
                                            f"not counted as a race: {reason}"))

    unraced_ids = {w.id for w in unraced}
    for e in efforts:  # stretches of training runs that weren't quite race effort
        if e.workout_id in race_ids | unraced_ids or e.distance_m < MIN_EFFORT_M:
            continue
        hrr = _hrr(e.avg_hr, profile)
        if hrr is not None and hrr >= HRR_RACE:
            continue  # qualified: already listed above
        category, reason = _below_race_level(hrr)
        if category:
            dropped[category] += 1
            if reason:
                candidates.append(Candidate(e.day, "Effort", e.label, e.duration_s,
                                            e.avg_hr, False, reason))

    level = round(profile.resting_hr + HRR_RACE * (profile.max_hr - profile.resting_hr))
    return EffortReport(profile, level, sorted(candidates, key=lambda c: c.day), dropped)


def _below_race_level(hrr: float | None) -> tuple[str, str]:
    """(category, reason to list). Missing heart rate is counted but not listed (with
    phone-only years it could be hundreds of runs); easy efforts are neither."""
    if hrr is None:
        return NO_HEART_RATE, ""
    if hrr >= NEAR_MISS_HRR:
        return NEAR_MISS, (f"heart rate {round(100 * hrr)}% of reserve "
                           f"(race level is {round(100 * HRR_RACE)}%)")
    return "", ""


def _hrr(avg_hr: int | None, profile: AthleteProfile) -> float | None:
    return heart_rate_reserve(avg_hr, profile) if avg_hr is not None else None


def _label(p: Performance) -> str:
    return race_label(p.distance_m) or f"{p.distance_m / 1000:.1f} km"
