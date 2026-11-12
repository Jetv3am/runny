"""Pass 2 of the Apple Health import: the samples recorded *during* each run.

Collects watch distance and heart-rate records that fall inside a kept workout, removes
paused time, and turns them into one `Stream` per workout.

Why a second pass instead of buffering in pass 1: Apple doesn't promise that records
come before workouts in the file, and buffering every heart-rate reading of a
multi-year export would defeat the flat-memory design. Memory here scales with total
*running* time, not export size.
"""

from __future__ import annotations

from array import array
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from coach.domain.streams import Stream
from coach.ingestion.apple_export import ParsedWorkout
from coach.ingestion.export_reader import (
    LENGTH_M,
    ProgressFn,
    convert,
    export_elements,
    number,
    parse_date,
)

_DISTANCE = "HKQuantityTypeIdentifierDistanceWalkingRunning"
_HEART_RATE = "HKQuantityTypeIdentifierHeartRate"
# The samples must account for most of the run, or the splits would be fiction.
COVERAGE_RANGE = (0.8, 1.2)


class _RunSamples:
    """Raw samples inside one workout's time window, kept per recording source."""

    def __init__(self, workout: ParsedWorkout):
        self.workout = workout
        self.start_ts = workout.start_at.timestamp()
        self.end_ts = workout.end_at.timestamp()
        self.distance: defaultdict[str, array] = defaultdict(lambda: array("d"))  # s, e, m
        self.heart_rate: defaultdict[str, array] = defaultdict(lambda: array("d"))  # t, bpm

    def to_stream(self) -> Stream | None:
        source = self._distance_source()
        if source is None:
            return None
        start, end, metres = (np.frombuffer(self.distance[source], dtype=float)
                              .reshape(-1, 3).T)
        order = np.argsort(start)
        wall_t, cumulative = _cumulative(self.start_ts, start[order], end[order],
                                         metres[order])
        cumulative *= self.workout.distance_m / cumulative[-1]  # agree with Apple's total

        hr_t, bpm = np.empty(0), np.empty(0)
        if self.heart_rate:
            readings = max(self.heart_rate.values(), key=len)  # the source that tracked HR
            hr_t, bpm = np.frombuffer(readings, dtype=float).reshape(-1, 2).T
            order = np.argsort(hr_t)
            hr_t, bpm = hr_t[order], bpm[order]
        return Stream(t_s=self._active_seconds(wall_t), distance_m=cumulative,
                      hr_t_s=self._active_seconds(hr_t), hr_bpm=bpm)

    def _distance_source(self) -> str | None:
        """The source whose samples best explain the workout's distance. Picking one
        avoids double counting when iPhone and Watch both recorded the run."""
        totals = {source: sum(samples[2::3]) for source, samples in self.distance.items()}
        if not totals:
            return None
        source = min(totals, key=lambda s: abs(totals[s] - self.workout.distance_m))
        low, high = COVERAGE_RANGE
        coverage = totals[source] / self.workout.distance_m
        return source if low <= coverage <= high else None

    def _active_seconds(self, wall_ts: np.ndarray) -> np.ndarray:
        """Seconds since the start with paused time removed."""
        active = wall_ts - self.start_ts
        for paused_from, resumed in self.workout.pauses:
            begin, finish = paused_from.timestamp(), resumed.timestamp()
            active -= np.clip(wall_ts - begin, 0, finish - begin)
        return active


def _cumulative(start_ts: float, starts: np.ndarray, ends: np.ndarray,
                metres: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Turn per-interval distances into a cumulative curve. A gap between samples
    gets an explicit flat stretch, so distance isn't smeared across idle time."""
    times, totals = [start_ts], [0.0]
    covered = 0.0
    for begin, finish, amount in zip(starts, ends, metres, strict=True):
        if begin > times[-1]:
            times.append(begin)
            totals.append(covered)
        covered += amount
        times.append(max(finish, times[-1]))
        totals.append(covered)
    return np.array(times), np.array(totals)


def collect_streams(path: Path, workouts: Sequence[ParsedWorkout],
                    on_progress: ProgressFn | None = None) -> dict[str, Stream]:
    """Workout id -> Stream, for the workouts whose samples cover the run."""
    if not workouts:
        return {}
    runs = sorted((_RunSamples(w) for w in workouts), key=lambda r: r.start_ts)
    starts = [r.start_ts for r in runs]
    # Cheap pre-filter on the date text before the (slow) date parsing.
    run_days = {f"{moment:%Y-%m-%d}" for w in workouts for moment in (w.start_at, w.end_at)}

    with export_elements(path, on_progress) as elements:
        for elem in elements:
            kind = elem.get("type")
            if elem.tag != "Record" or kind not in (_DISTANCE, _HEART_RATE):
                continue
            raw_start = elem.get("startDate") or ""
            if raw_start[:10] not in run_days or (start := parse_date(raw_start)) is None:
                continue
            ts = start.timestamp()
            index = bisect_right(starts, ts) - 1
            if index < 0 or ts > runs[index].end_ts:
                continue
            run, source = runs[index], elem.get("sourceName") or ""
            if kind == _HEART_RATE:
                if (bpm := number(elem.get("value"))) is not None:
                    run.heart_rate[source].extend((ts, bpm))
            elif ((end := parse_date(elem.get("endDate"))) is not None
                  and (metres := convert(elem.get("value"), elem.get("unit"), LENGTH_M))
                  is not None):
                run.distance[source].extend((ts, end.timestamp(), metres))

    return {run.workout.id: stream for run in runs if (stream := run.to_stream()) is not None}
