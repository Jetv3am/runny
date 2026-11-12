"""Apple Health export parser: formats, units, timezones, and hostile input."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from coach.ingestion.apple_export import parse_export
from coach.ingestion.cleaning import drop_duplicate_recordings
from coach.ingestion.export_reader import ExportError
from tests.export_builder import Run, export_xml, export_zip, record

FIXTURES = Path(__file__).parent / "fixtures"


def _write(tmp_path: Path, data: bytes, name: str = "export.upload") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_v1_sample_legacy_attribute_format():
    """Pre-iOS-16 exports carry totals as <Workout> attributes."""
    result = parse_export(FIXTURES / "apple_health_v1_sample.xml")
    assert result.stats.runs_kept == 2 and result.stats.skipped_not_running == 1  # cycling
    first = result.workouts[0]
    assert first.distance_m == 5000 and first.duration_s == 32.5 * 60
    assert (first.avg_hr, first.max_hr, first.energy_kcal) == (151, 174, 310)
    assert [m.value for m in result.metrics] == [46.8, 47.2]


def test_modern_format_reads_statistics_and_metadata(tmp_path):
    result = parse_export(_write(tmp_path, export_xml(Run().xml())))
    (run,) = result.workouts
    assert run.distance_m == pytest.approx(10_000)
    assert run.duration_s == 50 * 60
    assert run.energy_kcal == 640
    assert (run.avg_hr, run.max_hr) == (150, 172)
    assert run.avg_cadence == pytest.approx(170)  # 8500 steps / 50 min
    assert run.elevation_gain_m == pytest.approx(45.2)  # "4520 cm"
    assert run.temperature_c == pytest.approx(16.0)  # "60.8 degF"
    assert run.indoor is False


def test_keeps_local_time_so_evening_runs_stay_on_their_day(tmp_path):
    """18:30 -0700 is 01:30 UTC the next day; the run must stay on Oct 3."""
    (run,) = parse_export(_write(tmp_path, export_xml(Run().xml()))).workouts
    assert run.start_at.date() == date(2026, 10, 3)
    assert run.start_at.utcoffset().total_seconds() == -7 * 3600


def test_zip_uses_export_xml_and_ignores_clinical_records(tmp_path):
    result = parse_export(_write(tmp_path, export_zip(export_xml(Run().xml()))))
    assert result.stats.runs_kept == 1


def test_skips_non_running_and_too_short_workouts(tmp_path):
    xml = export_xml(
        Run().xml(),
        Run(activity="HKWorkoutActivityTypeCycling", start="2026-10-04 07:00:00 -0700").xml(),
        Run(distance_km=0.3, start="2026-10-05 07:00:00 -0700").xml(),
    )
    stats = parse_export(_write(tmp_path, xml)).stats
    assert (stats.runs_kept, stats.skipped_not_running, stats.skipped_unusable) == (1, 1, 1)


def test_one_metric_value_per_day_latest_wins(tmp_path):
    xml = export_xml(
        record("RestingHeartRate", 55, "2026-10-03 06:00:00 -0700"),
        record("RestingHeartRate", 52, "2026-10-03 21:00:00 -0700"),  # later same local day
        record("VO2Max", 48.1, "2026-10-04 07:00:00 -0700"),
        record("StepCount", 9000, "2026-10-04 07:00:00 -0700"),  # not a tracked metric
    )
    metrics = parse_export(_write(tmp_path, xml)).metrics
    assert [(m.type, m.day, m.value) for m in metrics] == [
        ("resting_hr", date(2026, 10, 3), 52), ("vo2max", date(2026, 10, 4), 48.1)]


def test_workout_ids_are_stable_across_imports(tmp_path):
    path = _write(tmp_path, export_xml(Run().xml()))
    assert parse_export(path).workouts[0].id == parse_export(path).workouts[0].id


def test_reports_progress_up_to_complete(tmp_path):
    seen: list[float] = []
    parse_export(_write(tmp_path, export_xml(Run().xml())), on_progress=seen.append)
    assert seen and seen[-1] == 1.0


@pytest.mark.parametrize(("data", "message"), [
    (b"<NotHealth/>", "doesn't look like an Apple Health export"),
    (b"<HealthData><Workout", "malformed"),
    (export_zip(b"")[:200], "damaged"),
])
def test_rejects_bad_files_with_friendly_errors(tmp_path, data, message):
    with pytest.raises(ExportError, match=message):
        parse_export(_write(tmp_path, data))


def test_refuses_entity_expansion_attacks(tmp_path):
    """'Billion laughs': entities that expand exponentially. Never in real exports."""
    bomb = (b'<?xml version="1.0"?><!DOCTYPE HealthData [<!ENTITY a "aaaaaaaaaa">'
            b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><HealthData>&b;</HealthData>')
    with pytest.raises(ExportError, match="entities"):
        parse_export(_write(tmp_path, bomb))


def test_zip_without_export_xml_is_rejected(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("photos/cat.jpg", b"meow")
    with pytest.raises(ExportError, match="No export.xml"):
        parse_export(_write(tmp_path, buffer.getvalue()))


def test_duplicate_recordings_keep_the_richer_one(tmp_path):
    xml = export_xml(
        Run(source="Strava", avg_hr=None).xml(),  # same run, no heart rate
        Run(source="Apple Watch", start="2026-10-03 18:31:00 -0700").xml(),
        Run(start="2026-10-04 18:30:00 -0700", end="2026-10-04 19:20:00 -0700").xml(),
    )
    kept = drop_duplicate_recordings(parse_export(_write(tmp_path, xml)).workouts)
    assert [(w.source_name, w.start_at.day) for w in kept] == [("Apple Watch", 3),
                                                               ("Apple Watch", 4)]
