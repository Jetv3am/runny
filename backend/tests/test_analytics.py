"""Phase 2 analytics end-to-end: samples -> splits, run types, personal bests, VDOT."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from coach.domain.vdot import vdot_from_performance
from coach.main import create_app
from coach.storage.database import session_scope
from coach.storage.tables import WorkoutStreamRow
from tests.export_builder import export_xml, export_zip, fmt, sampled_run

API = "/api/v1"


def _start(days_ago: int) -> str:
    moment = datetime.combine(date.today() - timedelta(days=days_ago), time(7, 0))
    return fmt(moment.astimezone())


# Same average HR (160) for the interval session and the tempo: only pace shape differs.
REPS = [(400, 225), (400, 390)] * 8  # 400 m at 3:45/km, 400 m jog at 6:30/km
RUNS = {
    "interval": sampled_run(_start(9), REPS, hr=160),
    "tempo": sampled_run(_start(7), [(8_000, 260)], hr=160),
    "hard": sampled_run(_start(5), [(6_000, 240)], hr=175),  # race effort, not a race
    **{f"easy{i}": sampled_run(_start(20 + i), [(8_000, 345)], hr=140) for i in range(4)},
}
EXPORT = export_zip(export_xml(*(part for run, samples in RUNS.values()
                                 for part in (run.xml(), *samples))))


def _upload(client: TestClient) -> None:
    client.post(f"{API}/imports", files={"file": ("export.zip", EXPORT, "application/zip")})


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        _upload(test_client)
        yield test_client


def _workouts(client: TestClient) -> dict[str, dict]:
    """Workouts keyed by the RUNS name, matched on start time."""
    items = client.get(f"{API}/workouts", params={"limit": 50}).json()["items"]
    by_start = {w["start_at"][:16]: w for w in items}
    return {name: by_start[datetime.strptime(run.start, "%Y-%m-%d %H:%M:%S %z")
                           .isoformat()[:16]]
            for name, (run, _) in RUNS.items()}


def test_import_reports_splits(client):
    assert "7 runs have splits" in client.get(f"{API}/imports").json()[0]["message"]


def test_interval_session_is_told_apart_from_a_tempo_by_pace_shape(client):
    workouts = _workouts(client)
    assert workouts["interval"]["type"] == "interval"
    assert workouts["tempo"]["type"] == "tempo"


def test_workout_detail_has_splits(client):
    tempo_id = _workouts(client)["tempo"]["id"]
    detail = client.get(f"{API}/workouts/{tempo_id}").json()
    assert len(detail["splits"]) == 8
    assert {round(s["pace_s_per_km"]) for s in detail["splits"]} == {260}
    assert {s["avg_hr"] for s in detail["splits"]} == {160}
    assert detail["splits"][0]["elevation_delta_m"] is None  # not in watch samples


def test_personal_bests_come_from_inside_runs(client):
    bests = {pb["key"]: pb for pb in client.get(f"{API}/fitness/personal-bests").json()}
    hard_id = _workouts(client)["hard"]["id"]
    assert bests["5k"]["all_time"]["duration_s"] == pytest.approx(1200, abs=1)
    assert bests["5k"]["all_time"]["workout_id"] == hard_id
    assert bests["1k"]["all_time"]["duration_s"] == pytest.approx(240, abs=1)
    assert bests["5k"]["recent"] == bests["5k"]["all_time"]
    assert bests["10k"]["all_time"] is None  # no run was long enough


def test_hard_training_run_unlocks_vdot_without_any_race(client):
    paces = client.get(f"{API}/fitness/paces")
    assert paces.status_code == 200
    assert paces.json()["vdot"] == pytest.approx(vdot_from_performance(5_000, 1_200), abs=0.1)


def test_reimport_replaces_streams_instead_of_duplicating(client):
    _upload(client)
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(WorkoutStreamRow)) == len(RUNS)
    assert len(client.get(f"{API}/workouts/{_workouts(client)['tempo']['id']}")
               .json()["splits"]) == 8
