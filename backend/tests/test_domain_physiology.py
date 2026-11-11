"""Physiology maths checked against published Daniels tables and Banister definitions."""

import pytest

from coach.domain.training_load import ewma, form_label, readiness_score, training_load, trimp
from coach.domain.vdot import race_time_for_vdot, training_paces, vdot_from_performance


@pytest.mark.parametrize(
    ("distance_m", "time_s", "expected_vdot"),
    [
        (5_000, 19 * 60 + 57, 50.0),  # Daniels table: VDOT 50 -> 5K 19:57
        (10_000, 41 * 60 + 21, 50.0),  # VDOT 50 -> 10K 41:21
        (5_000, 25 * 60 + 12, 38.0),  # VDOT 38 -> 5K 25:12
    ],
)
def test_vdot_matches_daniels_table(distance_m, time_s, expected_vdot):
    assert vdot_from_performance(distance_m, time_s) == pytest.approx(expected_vdot, abs=0.3)


def test_race_time_round_trips_through_vdot():
    for distance in (5_000, 10_000, 21_097.5, 42_195):
        t = race_time_for_vdot(50, distance)
        assert vdot_from_performance(distance, t) == pytest.approx(50, abs=1e-6)


def test_vdot_50_marathon_is_about_3h10():
    assert race_time_for_vdot(50, 42_195) == pytest.approx(3 * 3600 + 10 * 60 + 49, abs=90)


def test_pace_zones_are_ordered_and_plausible_for_vdot_50():
    zones = {z.key: z for z in training_paces(50)}
    order = ["easy", "marathon", "threshold", "interval", "repetition"]
    assert list(zones) == order
    fast_paces = [zones[k].fast_s_per_km for k in order]
    assert fast_paces == sorted(fast_paces, reverse=True)  # each zone faster than the last
    assert zones["threshold"].fast_s_per_km == pytest.approx(4 * 60 + 15, abs=5)  # ~4:15/km
    assert zones["interval"].fast_s_per_km == pytest.approx(3 * 60 + 55, abs=6)  # ~3:55/km
    for z in zones.values():
        assert z.fast_s_per_km < z.slow_s_per_km


def test_vdot_rejects_non_positive_input():
    with pytest.raises(ValueError):
        vdot_from_performance(0, 100)


def test_trimp_increases_with_intensity_and_duration():
    easy = trimp(3600, 140, 50, 190)
    hard = trimp(3600, 170, 50, 190)
    longer = trimp(7200, 140, 50, 190)
    assert 0 < easy < hard
    assert longer == pytest.approx(easy * 2)


def test_ewma_converges_to_constant_input():
    assert ewma([100.0] * 400, 42)[-1] == pytest.approx(100, abs=0.1)


def test_tsb_uses_previous_day_values():
    points = training_load([100.0, 0.0, 0.0])
    assert points[0].tsb == 0
    assert points[1].tsb == pytest.approx(points[0].ctl - points[0].atl)


@pytest.mark.parametrize(("tsb", "label"), [(30, "Detrained"), (10, "Fresh"), (0, "Neutral"),
                                             (-20, "Productive"), (-40, "Overreaching")])
def test_form_labels(tsb, label):
    assert form_label(tsb) == label


def test_readiness_is_bounded_and_penalises_ramps():
    assert 0 <= readiness_score(-100, 0) <= readiness_score(100, 0) <= 100
    assert readiness_score(0, 15) < readiness_score(0, 0)
