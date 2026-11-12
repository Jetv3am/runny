"""Phase 3 end to end: import -> automatic training -> registry -> predictions/plan/CLI.

Promotion is forced here (and only Ridge runs, for speed): these tests check the
plumbing. Whether a model *earns* promotion is tested in test_ml.py.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from coach.main import create_app
from coach.ml import __main__ as cli
from coach.ml import race_model
from coach.storage.database import session_scope
from coach.storage.tables import ModelVersionRow
from tests.export_builder import Run, export_xml, export_zip, fmt
from tests.ml_fixtures import DAYS, learnable_athlete

API = "/api/v1"


def _export(race_count: int | None = None) -> bytes:
    """The learnable athlete as an Apple Health export ending yesterday."""
    workouts, performances, _ = learnable_athlete(start=date.today() - timedelta(days=DAYS))
    performances = performances[-race_count:] if race_count else performances

    def run(day: date, hour: int, km: float, minutes: float, hr: int) -> str:
        begin = datetime.combine(day, time(hour)).astimezone()
        return Run(start=fmt(begin), end=fmt(begin + timedelta(minutes=minutes)),
                   distance_km=km, duration_min=minutes, avg_hr=hr, max_hr=hr + 10).xml()

    training = [run(w.day, 7, w.distance_m / 1000, w.distance_m / 1000 * 5.5, 140)
                for w in workouts]
    races = [run(p.day, 17, p.distance_m / 1000, p.duration_s / 60, 175) for p in performances]
    return export_zip(export_xml(*training, *races))


@pytest.fixture
def force_promotion(monkeypatch):
    monkeypatch.setattr(race_model, "PROMOTION_GAIN", -1.0)
    monkeypatch.setattr(race_model, "CANDIDATES", {"ridge": race_model.CANDIDATES["ridge"]})


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def _import(client: TestClient, export: bytes) -> None:
    upload = {"file": ("export.zip", export, "application/zip")}
    assert client.post(f"{API}/imports", files=upload).status_code == 202
    assert client.get(f"{API}/imports").json()[0]["status"] == "completed"


def _active_rows() -> list[ModelVersionRow]:
    with session_scope() as session:
        return list(session.scalars(select(ModelVersionRow)
                                    .where(ModelVersionRow.status == "active")))


def test_demo_data_is_never_trained_on(client):
    assert client.get(f"{API}/models/race-time").json()["status"] == "demo"
    response = client.post(f"{API}/models/race-time/train")
    assert response.status_code == 409
    assert "Import" in response.json()["detail"]


def test_import_trains_and_predictions_use_the_model(client, force_promotion):
    _import(client, _export())
    card = client.get(f"{API}/models/race-time").json()
    assert card["status"] == "active"
    assert card["efforts"] >= card["efforts_needed"]
    assert card["ml"]["mape_pct"] > 0 and card["baseline"]["mape_pct"] > 0

    predictions = client.get(f"{API}/predictions/race").json()
    assert predictions["source"] == "ml"
    assert predictions["model_version"] == card["version"]
    assert "personal" in predictions["based_on"]
    for p in predictions["predictions"]:
        assert p["p10_s"] < p["predicted_s"] < p["p90_s"]


def test_goal_race_uses_the_same_model_as_the_predictions_page(client, force_promotion):
    _import(client, _export())
    goal = client.get(f"{API}/plans/current").json()["goal"]
    half = next(p for p in client.get(f"{API}/predictions/race").json()["predictions"]
                if p["distance_m"] == goal["distance_m"])
    assert goal["predicted_time_s"] == half["predicted_s"]


def test_retraining_retires_the_old_model_and_its_file(client, force_promotion, tmp_path):
    _import(client, _export())
    first = client.get(f"{API}/models/race-time").json()["version"]
    second = client.post(f"{API}/models/race-time/train").json()["version"]
    assert second != first
    assert [row.id for row in _active_rows()] == [second]
    assert [f.name for f in (tmp_path / "models").iterdir()] == [f"race_time-{second}.joblib"]


def test_a_tampered_model_file_is_never_loaded(client, force_promotion, tmp_path):
    _import(client, _export())
    (model_file,) = (tmp_path / "models").iterdir()
    model_file.write_bytes(model_file.read_bytes() + b"tampered")
    response = client.get(f"{API}/predictions/race")
    assert response.status_code == 200
    assert response.json()["source"] == "vdot_baseline"  # falls back, doesn't crash


def test_too_few_efforts_keeps_the_baseline(client):
    _import(client, _export(race_count=6))
    card = client.get(f"{API}/models/race-time").json()
    assert card["status"] == "collecting_data"
    assert card["efforts"] < card["efforts_needed"]
    assert client.get(f"{API}/predictions/race").json()["source"] == "vdot_baseline"


def test_cli_trains_and_reports_without_the_web_app(client, force_promotion, capsys):
    assert cli.main(["train"]) == 1  # demo data: refused, with an explanation
    assert "Import" in capsys.readouterr().err
    _import(client, _export())
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Active" in out and "ML error" in out and "VDOT error" in out
