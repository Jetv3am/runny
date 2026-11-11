"""Run classification and athlete-profile derivation."""

from __future__ import annotations

import pytest

from coach.domain.classify import classify_run, derive_profile, race_label, run_title
from coach.domain.models import AthleteProfile, WorkoutType

PROFILE = AthleteProfile(name="Test", resting_hr=50, max_hr=190)  # reserve 140
MEDIAN = 8_000


def _hr(hrr: float) -> float:
    return PROFILE.resting_hr + hrr * (PROFILE.max_hr - PROFILE.resting_hr)


@pytest.mark.parametrize(("distance", "hrr", "expected"), [
    (5_050, 0.92, WorkoutType.RACE),        # 5K at race effort (GPS reads a bit long)
    (9_000, 0.92, WorkoutType.INTERVAL),    # hard but not a race distance
    (8_000, 0.80, WorkoutType.TEMPO),
    (18_000, 0.70, WorkoutType.LONG),
    (18_000, 0.84, WorkoutType.TEMPO),      # "long" but too hard: a workout
    (5_000, 0.55, WorkoutType.RECOVERY),    # short and very easy
    (8_000, 0.55, WorkoutType.EASY),        # very easy but normal length
    (8_000, 0.68, WorkoutType.EASY),
])
def test_classify_by_distance_and_intensity(distance, hrr, expected):
    assert classify_run(distance, _hr(hrr), PROFILE, MEDIAN) is expected


@pytest.mark.parametrize(("distance", "expected"), [
    (14_000, WorkoutType.LONG), (8_000, WorkoutType.EASY)])
def test_classify_without_heart_rate_uses_distance_only(distance, expected):
    assert classify_run(distance, None, PROFILE, MEDIAN) is expected


def test_long_run_needs_a_minimum_distance_for_low_mileage_runners():
    """1.5x a 3 km median is 4.5 km - not a long run."""
    assert classify_run(5_000, _hr(0.65), PROFILE, 3_000) is WorkoutType.EASY


@pytest.mark.parametrize(("distance", "label"), [
    (4_960, "5K"), (10_300, "10K"), (21_300, "Half Marathon"), (42_400, "Marathon"),
    (4_900, None), (11_000, None)])
def test_race_label_tolerates_gps_drift(distance, label):
    assert race_label(distance) == label


def test_titles():
    assert run_title(WorkoutType.RACE, 10_050) == "10K Race"
    assert run_title(WorkoutType.EASY, 6_000, indoor=True) == "Treadmill Run"
    assert run_title(WorkoutType.TEMPO, 8_000) == "Tempo Run"


def test_profile_ignores_a_heart_rate_glitch():
    # 240 bpm during a 150-avg run is a strap/optical spike, not a real peak.
    profile = derive_profile("A", [52, 50, 51], [(150, 178), (160, 181), (150, 240), (155, 176)])
    assert (profile.resting_hr, profile.max_hr) == (51, 181)


def test_profile_keeps_a_single_genuine_race_peak():
    """Regression: a rank-based rule (2nd-highest) threw away the one race effort,
    put max HR 11 bpm too low, and turned every tempo run into a 'race'."""
    profile = derive_profile("A", [52], [(139, 153), (158, 172), (158, 175), (176, 186)])
    assert profile.max_hr == 186


def test_profile_defaults_without_data():
    profile = derive_profile("A", [], [])
    assert (profile.resting_hr, profile.max_hr) == (60, 190)


def test_profile_keeps_a_usable_heart_rate_reserve():
    profile = derive_profile("A", [70], [(85, 95), (82, 90)])  # only very easy runs recorded
    assert profile.max_hr - profile.resting_hr >= 40
