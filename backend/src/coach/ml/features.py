"""Training examples for the race-time model: what VDOT predicted, and what was known.

Every input is computed from data strictly *before* the effort's day, including the
VDOT baseline itself. A model that can peek at the race it predicts (leakage) scores
brilliantly in testing and fails in real life.

The target is the log-ratio actual / VDOT-predicted: the model learns *corrections*
to the physiology, not running from scratch. "No correction" is the safe default.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from coach.domain.fitness import LOOKBACK_DAYS, MIN_EFFORT_M, Performance, estimate_vdot
from coach.domain.history import DailyHistory
from coach.domain.vdot import race_time_for_vdot

FEATURES = (
    "log_distance",       # longer races depend more on endurance than VDOT captures
    "is_race",            # a full race vs a race-effort stretch inside a training run
    "days_since_effort",  # how stale the VDOT estimate is
    "ctl",                # fitness (42-day load)
    "tsb",                # form going into the day
    "ctl_ramp_28d",       # fitness trend since four weeks earlier
    "weekly_km_4w",       # recent volume
    "long_run_ratio",     # longest run in 8 weeks / race distance (endurance specificity)
)
# More fitness, volume or long-run specificity must never predict a *slower* time.
MONOTONIC = {"ctl": -1, "weekly_km_4w": -1, "long_run_ratio": -1}
MAX_LONG_RUN_RATIO = 2.0  # beyond twice the race distance, extra length doesn't matter


@dataclass(frozen=True, slots=True)
class Example:
    day: date
    distance_m: float
    actual_s: float
    baseline_s: float  # VDOT prediction from efforts before `day`
    features: tuple[float, ...]

    @property
    def target(self) -> float:
        return math.log(self.actual_s / self.baseline_s)


@dataclass(frozen=True, slots=True)
class Baseline:
    vdot: float
    last_effort_day: date

    def time_s(self, distance_m: float) -> float:
        return race_time_for_vdot(self.vdot, distance_m)


def baseline_before(performances: Sequence[Performance], day: date) -> Baseline | None:
    """The VDOT baseline as it stood going into `day` (efforts on `day` excluded)."""
    prior = [p for p in performances
             if p.day < day and p.distance_m >= MIN_EFFORT_M
             and (day - p.day).days <= LOOKBACK_DAYS]
    vdot = estimate_vdot(prior, day)
    return Baseline(vdot, max(p.day for p in prior)) if vdot is not None else None


def feature_row(history: DailyHistory, day: date, distance_m: float, is_race: bool,
                baseline: Baseline) -> tuple[float, ...]:
    """Inputs for an effort of `distance_m` on `day`, from history up to the day before."""
    before = day - timedelta(days=1)
    ctl = history.at(history.ctl, before)
    longest = float(history.window(history.longest_m, before, 56).max(initial=0.0))
    return (
        math.log(distance_m / 5_000),
        float(is_race),
        float((day - baseline.last_effort_day).days),
        ctl,
        ctl - history.at(history.atl, before),
        ctl - history.at(history.ctl, before - timedelta(days=28)),
        float(history.window(history.distance_m, before, 28).sum()) / 4 / 1_000,
        min(longest / distance_m, MAX_LONG_RUN_RATIO),
    )


def build_examples(performances: Sequence[Performance],
                   history: DailyHistory) -> list[Example]:
    """One example per race-quality effort that had a baseline before it, oldest first."""
    examples = []
    for p in sorted(performances, key=lambda p: p.day):
        if p.distance_m < MIN_EFFORT_M:
            continue
        if (baseline := baseline_before(performances, p.day)) is None:
            continue
        examples.append(Example(
            day=p.day, distance_m=p.distance_m, actual_s=p.duration_s,
            baseline_s=baseline.time_s(p.distance_m),
            features=feature_row(history, p.day, p.distance_m, p.is_race, baseline)))
    return examples


def as_arrays(examples: Sequence[Example]) -> tuple[np.ndarray, np.ndarray]:
    """(X, y) for scikit-learn."""
    return (np.array([e.features for e in examples], dtype=float),
            np.array([e.target for e in examples], dtype=float))
