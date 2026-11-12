"""Day-by-day training history: the shared backbone of load charts and ML features."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from coach.domain.models import Workout
from coach.domain.training_load import training_load


@dataclass(frozen=True, eq=False)
class DailyHistory:
    """One array slot per calendar day from the first workout through `last_day`."""

    first_day: date
    distance_m: np.ndarray
    trimp: np.ndarray
    longest_m: np.ndarray  # longest single run that day
    ctl: np.ndarray
    atl: np.ndarray
    tsb: np.ndarray

    @property
    def last_day(self) -> date:
        return self.first_day + timedelta(days=len(self.distance_m) - 1)

    @property
    def days(self) -> list[date]:
        return [self.first_day + timedelta(days=i) for i in range(len(self.distance_m))]

    def index(self, day: date) -> int:
        """Slot for `day`; may be negative or past the end (callers clamp via `window`)."""
        return (day - self.first_day).days

    def at(self, series: np.ndarray, day: date) -> float:
        """Value of a per-day series at the end of `day` (0 before the history starts)."""
        i = min(self.index(day), len(series) - 1)
        return float(series[i]) if i >= 0 else 0.0

    def window(self, series: np.ndarray, end: date, days: int) -> np.ndarray:
        """The `days` slots ending with `end` (inclusive), clipped to the history."""
        stop = min(self.index(end) + 1, len(series))
        return series[max(stop - days, 0):max(stop, 0)]


def daily_history(workouts: Sequence[Workout], through: date) -> DailyHistory | None:
    """None without workouts. Load needs the full history, so it always starts at day one."""
    if not workouts:
        return None
    first = min(w.day for w in workouts)
    size = (through - first).days + 1
    distance, load, longest = np.zeros(size), np.zeros(size), np.zeros(size)
    for w in workouts:
        i = (w.day - first).days
        if 0 <= i < size:
            distance[i] += w.distance_m
            load[i] += w.trimp
            longest[i] = max(longest[i], w.distance_m)
    points = training_load(load.tolist())
    return DailyHistory(
        first_day=first, distance_m=distance, trimp=load, longest_m=longest,
        ctl=np.array([p.ctl for p in points]), atl=np.array([p.atl for p in points]),
        tsb=np.array([p.tsb for p in points]))
