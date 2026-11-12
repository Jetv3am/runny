"""Parser pass 2: per-run samples -> streams (splits, pauses, sources, coverage)."""

from __future__ import annotations

from pathlib import Path

import pytest

from coach.domain.streams import splits
from coach.ingestion.apple_export import parse_export
from coach.ingestion.samples import collect_streams
from tests.export_builder import export_xml, export_zip, record, sampled_run

START = "2026-10-03 07:00:00 -0700"


def _streams(tmp_path: Path, *elements: str, zipped: bool = False):
    xml = export_xml(*elements)
    path = tmp_path / "export.upload"
    path.write_bytes(export_zip(xml) if zipped else xml)
    workouts = parse_export(path).workouts
    return workouts, collect_streams(path, workouts)


def test_steady_run_gives_exact_splits(tmp_path):
    run, samples = sampled_run(START, [(5_000, 300)], every_s=7)
    (workout,), streams = _streams(tmp_path, run.xml(), *samples, zipped=True)
    result = splits(streams[workout.id])
    assert [s.duration_s for s in result] == pytest.approx([300] * 5, abs=0.5)
    assert {s.avg_hr for s in result} == {150}


def test_paused_time_is_removed(tmp_path):
    # 2-minute pause (traffic light) 400 s in: km 2 must still read ~5:00, not 7:00.
    run, samples = sampled_run(START, [(3_000, 300)], pause=(400, 120))
    (workout,), streams = _streams(tmp_path, run.xml(), *samples)
    assert [s.duration_s for s in splits(streams[workout.id])] == pytest.approx([300] * 3,
                                                                                 abs=0.5)


def test_double_recording_by_phone_and_watch_is_not_double_counted(tmp_path):
    run, samples = sampled_run(START, [(5_000, 300)], sources=("Apple Watch", "iPhone"))
    (workout,), streams = _streams(tmp_path, run.xml(), *samples)
    assert streams[workout.id].total_m == pytest.approx(5_000)
    assert len(splits(streams[workout.id])) == 5


def test_partial_samples_give_no_stream_rather_than_wrong_splits(tmp_path):
    run, samples = sampled_run(START, [(6_000, 300)])
    distance_samples = [s for s in samples if "Distance" in s]
    _, streams = _streams(tmp_path, run.xml(), *distance_samples[: len(distance_samples) // 2])
    assert streams == {}


def test_run_across_midnight_keeps_samples_from_both_days(tmp_path):
    run, samples = sampled_run("2026-10-03 23:50:00 -0700", [(4_000, 300)])
    (workout,), streams = _streams(tmp_path, run.xml(), *samples)
    assert streams[workout.id].total_m == pytest.approx(4_000)
    assert len(splits(streams[workout.id])) == 4


def test_samples_outside_runs_are_ignored(tmp_path):
    run, samples = sampled_run(START, [(3_000, 300)])
    walking = record("HeartRate", 95, "2026-10-03 12:00:00 -0700")  # same day, no run
    (workout,), streams = _streams(tmp_path, run.xml(), *samples, walking)
    assert 95 not in streams[workout.id].hr_bpm


def test_runs_without_samples_have_no_stream(tmp_path):
    run, _ = sampled_run(START, [(5_000, 300)])
    _, streams = _streams(tmp_path, run.xml())
    assert streams == {}
