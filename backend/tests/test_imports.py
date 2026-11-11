"""End-to-end import flow through the API: upload -> background parse -> dashboard data."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from coach.main import create_app
from coach.services import imports
from coach.storage.database import session_scope
from coach.storage.tables import ImportRow
from tests.export_builder import Run, export_xml, export_zip, record

API = "/api/v1"


def _runs(count: int) -> list[str]:
    """`count` runs on consecutive days in October, alternating easy and long."""
    return [Run(start=f"2026-10-{day:02d} 07:00:00 -0700", end=f"2026-10-{day:02d} 08:00:00 -0700",
                distance_km=16 if day % 4 == 0 else 8, avg_hr=140 + day % 3).xml()
            for day in range(1, count + 1)]


# A 10K at race effort on Oct 20 gives VDOT (and so paces/predictions) something to work with.
RACE = Run(start="2026-10-20 08:00:00 -0700", end="2026-10-20 08:42:00 -0700",
           distance_km=10.05, duration_min=42, avg_hr=168, max_hr=180).xml()
EXPORT = export_zip(export_xml(*_runs(12), RACE,
                               record("RestingHeartRate", 50, "2026-10-12 06:00:00 -0700"),
                               record("VO2Max", 49.5, "2026-10-12 07:00:00 -0700")))
RUNS_IN_EXPORT = 13


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:  # `with` runs startup (migrations)
        yield test_client


def _upload(client: TestClient, data: bytes, name: str = "export.zip"):
    # TestClient runs background tasks before returning, so the import is finished here.
    return client.post(f"{API}/imports", files={"file": (name, data, "application/zip")})


def test_upload_imports_runs_and_switches_off_demo_data(client, isolated_data_dir):
    assert client.get(f"{API}/health").json()["data_source"] == "demo"

    response = _upload(client, EXPORT)
    assert response.status_code == 202 and response.json()["status"] == "processing"

    (job,) = client.get(f"{API}/imports").json()
    assert job["status"] == "completed" and job["progress"] == 100
    assert f"{RUNS_IN_EXPORT} runs ({RUNS_IN_EXPORT} new)" in job["message"]

    assert client.get(f"{API}/health").json()["data_source"] == "apple_health"
    page = client.get(f"{API}/workouts", params={"limit": 50}).json()
    assert page["total"] == RUNS_IN_EXPORT
    assert {w["type"] for w in page["items"]} >= {"long", "easy", "race"}
    assert "10K Race" in {w["title"] for w in page["items"]}
    vo2 = client.get(f"{API}/metrics/health", params={"type": "vo2max"}).json()
    assert [m["value"] for m in vo2] == [49.5]
    # The raw upload is deleted once its data is extracted.
    assert not list((isolated_data_dir / "uploads").iterdir())


def test_workouts_keep_their_local_start_time(client):
    _upload(client, EXPORT)
    newest = client.get(f"{API}/workouts", params={"limit": 1}).json()["items"][0]
    assert newest["start_at"] == "2026-10-20T08:00:00-07:00"


def test_reimporting_the_same_export_adds_nothing(client):
    _upload(client, EXPORT)
    _upload(client, EXPORT)
    latest = client.get(f"{API}/imports").json()[0]
    assert f"{RUNS_IN_EXPORT} runs (0 new)" in latest["message"]
    assert client.get(f"{API}/workouts").json()["total"] == RUNS_IN_EXPORT


def test_dashboard_endpoints_work_on_imported_data(client):
    _upload(client, EXPORT)
    for path in ("/fitness/summary", "/fitness/paces", "/metrics/daily?days=30",
                 "/workouts/weekly", "/predictions/race", "/plans/current"):
        assert client.get(f"{API}{path}").status_code == 200, path


def test_bad_export_fails_the_job_with_a_reason(client):
    assert _upload(client, b"<NotHealth/>", "export.xml").status_code == 202
    (job,) = client.get(f"{API}/imports").json()
    assert job["status"] == "failed" and "Apple Health export" in job["message"]
    assert client.get(f"{API}/health").json()["data_source"] == "demo"


def test_wrong_file_type_is_rejected_up_front(client):
    response = client.post(f"{API}/imports", files={"file": ("notes.txt", b"hi", "text/plain")})
    assert response.status_code == 422


def test_startup_fails_imports_interrupted_by_a_restart(client, isolated_data_dir):
    _upload(client, EXPORT)
    with session_scope() as session:
        session.get(ImportRow, client.get(f"{API}/imports").json()[0]["id"]).status = "processing"
    (isolated_data_dir / "uploads" / "orphan.upload").write_bytes(b"half an upload")

    imports.recover_interrupted()

    (job,) = client.get(f"{API}/imports").json()
    assert job["status"] == "failed" and "restarted" in job["message"]
    assert not list((isolated_data_dir / "uploads").iterdir())
