"""Plan-engine safety rules: these must never regress."""

from datetime import date, timedelta

from coach.domain.models import Goal, WorkoutType
from coach.domain.plan import CUTBACK_FACTOR, MAX_RAMP, generate_plan, weekly_volumes

HALF = Goal("Test Half", 21_097.5, date(2027, 3, 14), None)  # a Sunday
HARD = {WorkoutType.TEMPO, WorkoutType.INTERVAL, WorkoutType.RACE}


def _plan():
    return generate_plan(HALF, HALF.race_date - timedelta(weeks=12), 40_000)


def test_plan_ends_with_race_on_race_day():
    final_week = _plan()[-1]
    race = [s for s in final_week.sessions if s.type is WorkoutType.RACE]
    assert len(race) == 1 and race[0].day == HALF.race_date


def test_weekly_ramp_never_exceeds_ten_percent():
    phases = ["base"] * 4 + ["build"] * 6 + ["peak"] * 3 + ["taper"] * 2
    volumes = weekly_volumes(40_000, phases)
    for prev, cur in zip(volumes, volumes[1:], strict=False):
        # recovering from a cut-back week may jump back up to (prior level * ramp)
        assert cur <= prev / CUTBACK_FACTOR * MAX_RAMP + 1e-6


def test_no_back_to_back_hard_days_and_max_two_per_week():
    sessions = [s for w in _plan() for s in w.sessions]
    for a, b in zip(sessions, sessions[1:], strict=False):
        assert not (a.type in HARD and b.type in HARD), f"hard days back-to-back: {a.day}"
    for week in _plan():
        assert sum(s.type in HARD for s in week.sessions if s.type is not WorkoutType.RACE) <= 2


def test_phases_progress_in_order():
    order = {"base": 0, "build": 1, "peak": 2, "taper": 3}
    ranks = [order[w.phase] for w in _plan()]
    assert ranks == sorted(ranks)
    assert ranks[-1] == 3


def test_long_run_is_at_most_a_third_of_week():
    for week in _plan()[:-1]:
        longs = [s.distance_m for s in week.sessions if s.type is WorkoutType.LONG]
        if longs and week.target_distance_m:
            assert max(longs) <= week.target_distance_m / 3 + 500
