"""A run's samples over *active* time (pauses removed): splits, best efforts, pace shape.

Pure numpy maths, no I/O. Distance is cumulative metres, so "time at distance d" is an
interpolation: splits and efforts are exact between samples instead of snapping to
whichever sample happened to land near a boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from coach.domain.distances import BEST_EFFORTS, StandardDistance
from coach.domain.models import Split

SPLIT_M = 1_000.0
MIN_LAST_SPLIT_M = 100.0  # a trailing 40 m "split" would show a meaningless pace
VARIABILITY_SEGMENT_M = 200.0
MIN_VARIABILITY_SEGMENTS = 8


@dataclass(frozen=True, eq=False)
class Stream:
    t_s: np.ndarray  # active seconds since the start, non-decreasing
    distance_m: np.ndarray  # cumulative metres at each t_s, non-decreasing
    hr_t_s: np.ndarray  # active seconds of each heart-rate reading
    hr_bpm: np.ndarray

    def __post_init__(self) -> None:
        if self.t_s.shape != self.distance_m.shape or self.hr_t_s.shape != self.hr_bpm.shape:
            raise ValueError("each time array needs a value array of the same length")

    @property
    def total_m(self) -> float:
        return float(self.distance_m[-1]) if self.distance_m.size else 0.0

    @cached_property
    def curve(self) -> tuple[np.ndarray, np.ndarray]:
        """(distance, time) with distance strictly increasing, ready for interpolation.

        Of repeated distances (standing still without auto-pause) the *last* time is
        kept: an effort may start when you move again, and one that ends at the stop is
        charged for the wait. A stop is never counted as running.
        """
        keep = np.diff(self.distance_m, append=np.inf) > 0
        return self.distance_m[keep], self.t_s[keep]

    def time_at(self, distance_m: float | np.ndarray) -> np.ndarray:
        distance, time = self.curve
        return np.interp(distance_m, distance, time)

    def avg_hr(self, start_s: float, end_s: float) -> int | None:
        if not self.hr_bpm.size:
            return None
        inside = (self.hr_t_s >= start_s) & (self.hr_t_s <= end_s)
        if inside.any():
            return round(float(self.hr_bpm[inside].mean()))
        # Sparse readings (none inside a short window): read the trend at its midpoint.
        return round(float(np.interp((start_s + end_s) / 2, self.hr_t_s, self.hr_bpm)))


@dataclass(frozen=True, slots=True)
class WindowEffort:
    distance: StandardDistance
    duration_s: float
    avg_hr: int | None


def splits(stream: Stream, every_m: float = SPLIT_M) -> tuple[Split, ...]:
    total = stream.total_m
    marks = np.arange(every_m, total, every_m)
    covered = float(marks[-1]) if marks.size else 0.0
    if total - covered >= MIN_LAST_SPLIT_M:
        marks = np.append(marks, total)  # partial final split
    bounds = np.concatenate(([0.0], marks))
    times = stream.time_at(bounds)
    return tuple(
        Split(index=i + 1, distance_m=round(float(d1 - d0), 1),
              duration_s=round(float(t1 - t0), 1), avg_hr=stream.avg_hr(t0, t1),
              elevation_delta_m=None)  # watch distance samples carry no elevation
        for i, (d0, d1, t0, t1) in enumerate(zip(bounds, bounds[1:], times, times[1:],
                                                 strict=False))
    )


def best_efforts(stream: Stream,
                 distances: Sequence[StandardDistance] = BEST_EFFORTS) -> list[WindowEffort]:
    """Fastest window covering each standard distance the run is long enough for.

    On a piecewise-linear curve the optimal window has a start or end on a sample, so
    trying both families of windows is exact - and vectorised.
    """
    distance, time = stream.curve
    if distance.size < 2:
        return []
    total = float(distance[-1])
    efforts = []
    for standard in distances:
        span = standard.metres
        if span > total:
            continue
        starts = distance[distance + span <= total]
        ends = distance[distance >= span]
        start_times = np.concatenate((np.interp(starts, distance, time),
                                      np.interp(ends - span, distance, time)))
        end_times = np.concatenate((np.interp(starts + span, distance, time),
                                    np.interp(ends, distance, time)))
        best = int(np.argmin(end_times - start_times))
        start_s, end_s = float(start_times[best]), float(end_times[best])
        efforts.append(WindowEffort(standard, round(end_s - start_s, 1),
                                    stream.avg_hr(start_s, end_s)))
    return efforts


def pace_variability(stream: Stream) -> float | None:
    """Coefficient of variation of speed over 200 m segments; None for short runs."""
    segments = int(stream.total_m // VARIABILITY_SEGMENT_M)
    if segments < MIN_VARIABILITY_SEGMENTS:
        return None
    durations = np.diff(stream.time_at(np.arange(segments + 1) * VARIABILITY_SEGMENT_M))
    durations = durations[durations > 0]
    if durations.size < MIN_VARIABILITY_SEGMENTS:
        return None
    speeds = VARIABILITY_SEGMENT_M / durations
    return float(speeds.std() / speeds.mean())


def stream_from_splits(split_list: Sequence[Split]) -> Stream:
    """Coarse stream through split boundaries (demo data has splits but no samples)."""
    distance = np.concatenate(([0.0], np.cumsum([s.distance_m for s in split_list])))
    time = np.concatenate(([0.0], np.cumsum([s.duration_s for s in split_list])))
    with_hr = [(t0, s) for t0, s in zip(time, split_list, strict=False) if s.avg_hr is not None]
    return Stream(t_s=time, distance_m=distance,
                  hr_t_s=np.array([t0 + s.duration_s / 2 for t0, s in with_hr], dtype=float),
                  hr_bpm=np.array([s.avg_hr for _, s in with_hr], dtype=float))
