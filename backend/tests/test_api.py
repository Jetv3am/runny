"""API contract tests against the demo data source."""

import json

import pytest
from fastapi.testclient import TestClient

from coach.main import app

API = "/api/v1"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_health(client):
    body = client.get(f"{API}/health").json()
    assert body["status"] == "ok" and body["data_source"] == "demo"


def test_workouts_paginate_newest_first(client):
    page = client.get(f"{API}/workouts", params={"limit": 5}).json()
    assert len(page["items"]) == 5 and page["total"] > 50
    dates = [w["start_at"] for w in page["items"]]
    assert dates == sorted(dates, reverse=True)


def test_workout_filter_by_type(client):
    page = client.get(f"{API}/workouts", params={"type": "race", "limit": 50}).json()
    assert page["items"] and all(w["is_race"] for w in page["items"])


def test_workout_detail_splits_sum_to_total(client):
    first = client.get(f"{API}/workouts", params={"limit": 1}).json()["items"][0]
    detail = client.get(f"{API}/workouts/{first['id']}").json()
    assert sum(s["duration_s"] for s in detail["splits"]) == pytest.approx(detail["duration_s"],
                                                                          rel=0.01)


def test_unknown_workout_is_404(client):
    assert client.get(f"{API}/workouts/nope").status_code == 404


def test_weekly_volume_zero_filled(client):
    weeks = client.get(f"{API}/workouts/weekly", params={"weeks": 8}).json()
    assert len(weeks) == 8


def test_fitness_summary_is_plausible(client):
    s = client.get(f"{API}/fitness/summary").json()
    assert 40 < s["vdot"] < 56
    assert 0 <= s["readiness"] <= 100
    assert s["briefing"]
    # Units are the client's job: prose from the API must not hard-code them.
    assert not any(unit in s["briefing"] for unit in (" km", " mi", "/km"))


def test_paces_and_predictions_share_vdot(client):
    paces = client.get(f"{API}/fitness/paces").json()
    preds = client.get(f"{API}/predictions/race").json()
    assert paces["vdot"] == preds["vdot"]
    times = [p["predicted_s"] for p in preds["predictions"]]
    assert times == sorted(times)
    for p in preds["predictions"]:
        assert p["p10_s"] < p["predicted_s"] < p["p90_s"]


def test_daily_metrics_length(client):
    assert len(client.get(f"{API}/metrics/daily", params={"days": 30}).json()) == 30


def test_plan_has_race_week(client):
    plan = client.get(f"{API}/plans/current").json()
    last = plan["weeks"][-1]
    assert any(s["type"] == "race" for s in last["sessions"])


def test_plan_descriptions_are_unit_free(client):
    weeks = client.get(f"{API}/plans/current").json()["weeks"]
    sessions = [s for w in weeks for s in w["sessions"]]
    for s in sessions:
        assert " km" not in s["description"] and " m " not in s["description"], s["description"]


def test_cors_allows_frontend_origin_only(client):
    def preflight(origin):
        return client.options(f"{API}/imports", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST"})

    ok = preflight("http://localhost:3000")
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in preflight("https://evil.example").headers


def _chat(client, text):
    with client.stream("POST", f"{API}/chat",
                       json={"messages": [{"role": "user", "content": text}]}) as resp:
        events = [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data: ")]
    return "".join(e.get("delta", "") for e in events), events[-1]


def test_chat_streams_grounded_paces(client):
    text, final = _chat(client, "What are my training paces?")
    assert final == {"done": True, "source": "demo"}
    assert "Threshold" in text and "/km" in text


def test_chat_red_flag_routes_to_safety(client):
    text, _ = _chat(client, "I get chest pain on hills, what pace should I run?")
    assert "medical professional" in text
