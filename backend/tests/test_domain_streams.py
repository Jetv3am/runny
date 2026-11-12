"""Splits, best efforts and pace variability from per-run samples."""

from __future__ import annotations

import numpy as np
import pytest

from coach.domain.distances import FIVE_K, ONE_K
from coach.domain.models import Split
from coach.domain.streams import (
    Stream,
    best_efforts,
    pace_variability,
    splits,
    stream_from_splits,
)


def _stream(points: list[tuple[float, float]], hr: list[tuple[float, float]] = ()) -> Stream:
    t, d = zip(*points, strict=True)
    hr_t, bpm = zip(*hr, strict=True) if hr else ((), ())
    return Stream(np.array(t, float), np.array(d, float), np.array(hr_t, float),
                  np.array(bpm, float))


def _steady(km: float, pace_s: float, step_s: float = 10) -> Stream:
    """Constant pace, a sample every `step_s` seconds, HR 150."""
    total_s = km * pace_s
    t = np.arange(0, total_s + step_s, step_s)
    t[-1] = total_s
    return Stream(t, t / pace_s * 1000, t, np.full(t.size, 150.0))


def test_splits_interpolate_between_samples():
    (first, second, last) = splits(_steady(2.5, 300, step_s=7))  # samples miss the km marks
    assert (first.distance_m, first.duration_s, first.avg_hr) == (1000, 300, 150)
    assert second.duration_s == pytest.approx(300)
    assert (last.distance_m, last.duration_s) == (500, 150)  # partial final split


def test_tiny_trailing_split_is_dropped():
    assert len(splits(_steady(2.04, 300))) == 2


def test_best_effort_finds_the_fast_stretch_inside_a_run():
    # 2 km easy (6:00/km), 1 km hard (4:00/km), 2 km easy
    stream = _stream([(0, 0), (720, 2000), (960, 3000), (1680, 5000)])
    one_k, five_k = best_efforts(stream, [ONE_K, FIVE_K])
    assert one_k.duration_s == 240  # exactly the hard kilometre
    assert five_k.duration_s == 1680


def test_best_effort_window_can_end_between_samples():
    # 4:00/km for 500 m, then 5:00/km. Best 1K = 0..1000 m, and 1000 m is not a sample.
    stream = _stream([(0, 0), (120, 500), (420, 1500)])
    (one_k,) = best_efforts(stream, [ONE_K])
    assert one_k.duration_s == pytest.approx(270)  # 120 s + 500 m at 5:00/km


def test_no_effort_for_distances_longer_than_the_run():
    assert best_efforts(_steady(4.9, 300), [FIVE_K]) == []


def test_a_stop_is_never_counted_as_running():
    # Stood still 60 s at 500 m (no auto-pause). An effort may start when they move
    # again (500..1500 m in 300 s), but one *ending* at the stop pays for the wait.
    stream = _stream([(0, 0), (150, 500), (210, 500), (360, 1000), (510, 1500)])
    (one_k,) = best_efforts(stream, [ONE_K])
    assert one_k.duration_s == pytest.approx(300)
    assert stream.time_at(500.0) == 210  # arrival at the stop = when they left it


def test_pace_variability_separates_intervals_from_steady_running():
    steady = _steady(8, 300)
    reps = [(0.0, 0.0)]
    for _ in range(8):  # 400 m at 3:45/km, 400 m jog at 6:30/km
        t, d = reps[-1]
        reps += [(t + 90, d + 400), (t + 90 + 156, d + 800)]
    assert pace_variability(steady) == pytest.approx(0, abs=0.01)
    assert pace_variability(_stream(reps)) > 0.2


def test_pace_variability_needs_enough_distance():
    assert pace_variability(_steady(1.2, 300)) is None


def test_avg_hr_falls_back_to_the_trend_for_sparse_readings():
    stream = _stream([(0, 0), (600, 2000)], hr=[(0, 140), (600, 160)])
    assert stream.avg_hr(250, 350) == 150  # no reading inside: midpoint of the trend


def test_stream_from_demo_splits_round_trips():
    demo = (Split(1, 1000, 300, 150, 2.0), Split(2, 1000, 280, 155, -1.0))
    stream = stream_from_splits(demo)
    assert [s.duration_s for s in splits(stream)] == [300, 280]
    assert [s.avg_hr for s in splits(stream)] == [150, 155]
