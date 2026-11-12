"""The efforts report: every exclusion explained, easy runs left out, decisions unchanged."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from coach.domain.history import daily_history
from coach.domain.models import AthleteProfile, BestEffort, Workout, WorkoutType
from coach.ml.__main__ import describe_efforts
from coach.ml.diagnostics import NEAR_MISS, NO_BASELINE, NO_HEART_RATE, TOO_SHORT, explain

TODAY = date(2026, 11, 10)
PROFILE = AthleteProfile("Test", resting_hr=60, max_hr=190)  # race level: 171 bpm


def _run(days_ago: int, kind: WorkoutType, metres: float, seconds: float,
         hr: int | None) -> Workout:
    day = TODAY - timedelta(days=days_ago)
    return Workout(id=f"w{days_ago}", title="Run", type=kind,
                   start_at=datetime(day.year, day.month, day.day, 8, tzinfo=UTC),
                   distance_m=metres, duration_s=seconds, avg_hr=hr, max_hr=None,
                   elevation_gain_m=None, energy_kcal=None, avg_cadence=None,
                   temperature_c=None, trimp=50)


def _effort(run: Workout, metres: float, seconds: float, hr: int | None) -> BestEffort:
    return BestEffort(run.id, run.day, f"{metres}", f"{metres / 1000:g} km", metres,
                      seconds, hr)


WORKOUTS = [
    _run(30, WorkoutType.RACE, 10_000, 2_400, 175),  # first effort: no baseline before it
    _run(10, WorkoutType.RACE, 5_000, 1_150, 176),   # used
    _run(5, WorkoutType.TEMPO, 10_000, 2_500, 165),  # race distance, HR 81%: missed race?
    _run(4, WorkoutType.EASY, 5_000, 1_500, None),   # phone-only: counted, not listed
    _run(3, WorkoutType.EASY, 5_000, 1_650, 130),    # easy 5 km: not a candidate at all
    _run(2, WorkoutType.TEMPO, 12_000, 2_900, 166),
]
EFFORTS = [
    _effort(WORKOUTS[5], 5_000, 1_180, 168),  # inside a tempo run, HR 83%: near miss
    _effort(WORKOUTS[5], 1_609, 330, 180),    # race-level mile: qualifies, but < 3 km
]


def _report():
    return explain(WORKOUTS, EFFORTS, PROFILE, daily_history(WORKOUTS, TODAY))


def test_every_exclusion_is_explained_and_easy_runs_are_left_out():
    report = _report()
    listed = {(c.day, c.kind): c for c in report.candidates}
    assert report.used == 1 and listed[(TODAY - timedelta(10), "Race")].used
    assert listed[(TODAY - timedelta(30), "Race")].reason == NO_BASELINE
    assert "not counted as a race" in listed[(TODAY - timedelta(5), "Run")].reason
    assert "83% of reserve" in listed[(TODAY - timedelta(2), "Effort")].reason
    assert {c.day for c in report.candidates}.isdisjoint({TODAY - timedelta(3),
                                                          TODAY - timedelta(4)})
    assert report.dropped == {NO_BASELINE: 1, NEAR_MISS: 2, NO_HEART_RATE: 1, TOO_SHORT: 1}
    assert report.race_level_hr == 170  # 60 + 0.85 * (190 - 60) = 170.5, banker's round


def test_cli_report_is_readable_and_gives_the_relevant_hints():
    text = describe_efforts(_report())
    assert "Used for training: 1 (the model needs 12)" in text
    assert "Race level: average 170 bpm or more." in text
    assert "2026-10-11  Race    10K" in text and "40:00" in text
    assert "max heart rate (190) may be estimated too high" in text
    assert "break of 120+ days" in text
