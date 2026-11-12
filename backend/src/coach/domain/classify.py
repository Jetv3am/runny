"""Infer what kind of run a workout was, and the athlete profile, from raw Apple Health data.

Apple doesn't label runs as tempo/long/etc., so these are heuristics on distance,
heart-rate intensity and - when per-run samples exist - how much the pace varied.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from coach.domain.distances import RACES, StandardDistance
from coach.domain.models import AthleteProfile, WorkoutType

WORKOUT_TITLES: dict[WorkoutType, str] = {
    WorkoutType.EASY: "Easy Run",
    WorkoutType.LONG: "Long Run",
    WorkoutType.TEMPO: "Tempo Run",
    WorkoutType.INTERVAL: "Interval Session",
    WorkoutType.RECOVERY: "Recovery Jog",
    WorkoutType.RACE: "Race",
}

# GPS/watch distance usually reads a little long, never much short.
_RACE_TOLERANCE = (-0.01, 0.04)

# Heart-rate reserve fractions (Karvonen) separating intensity bands.
HRR_RACE = 0.85
HRR_INTERVAL = 0.86  # used only when pace samples are missing
HRR_TEMPO = 0.76
HRR_RECOVERY = 0.62
HRR_LONG_CEILING = 0.82  # a "long run" that's harder than this is really a workout
# Pace variability (coefficient of variation of 200 m segment speeds): steady runs sit
# around 0.03-0.08, hilly ones ~0.10; reps with jog recoveries are 0.2+.
INTERVAL_PACE_CV = 0.15
HRR_VARIABLE_INTERVAL = 0.70  # fartlek-ish swings at easy effort aren't a session

LONG_RUN_FACTOR = 1.5  # relative to the athlete's median run
LONG_RUN_MIN_M = 8_000
RECOVERY_FACTOR = 0.8
# Runs recorded without heart rate are assumed to be easy effort for training load.
ASSUMED_HRR_WITHOUT_HR = 0.65

DEFAULT_RESTING_HR = 60
DEFAULT_MAX_HR = 190
MIN_HR_RESERVE = 40
# Max-HR plausibility: a real peak comes with a hard average (race: 176 avg, 186 max);
# a strap/optical glitch spikes during an ordinary run (150 avg, 240 max).
PLAUSIBLE_MAX_HR = (120, 220)
MAX_PEAK_OVER_AVG = 1.25


def race_distance(distance_m: float) -> StandardDistance | None:
    """The standard race this distance matches (allowing for GPS drift), else None."""
    low, high = _RACE_TOLERANCE
    return next((race for race in RACES
                 if race.metres * (1 + low) <= distance_m <= race.metres * (1 + high)), None)


def race_label(distance_m: float) -> str | None:
    """'5K', '10K', ... if the distance matches a standard race, else None."""
    race = race_distance(distance_m)
    return race.label if race else None


def heart_rate_reserve(avg_hr: float, profile: AthleteProfile) -> float:
    return (avg_hr - profile.resting_hr) / (profile.max_hr - profile.resting_hr)


def classify_run(distance_m: float, avg_hr: float | None, profile: AthleteProfile,
                 median_distance_m: float, pace_cv: float | None = None) -> WorkoutType:
    """`pace_cv`: pace variability from the run's samples; None if it has none."""
    is_long = distance_m >= max(LONG_RUN_FACTOR * median_distance_m, LONG_RUN_MIN_M)
    is_variable = pace_cv is not None and pace_cv >= INTERVAL_PACE_CV
    if avg_hr is None:  # no HR: distance and pace shape are all we have
        if is_variable:
            return WorkoutType.INTERVAL
        return WorkoutType.LONG if is_long else WorkoutType.EASY

    hrr = heart_rate_reserve(avg_hr, profile)
    # Checked before races: an interval session can total exactly 10 km at race-like
    # average HR, but races are run at a steady pace.
    if is_variable and hrr >= HRR_VARIABLE_INTERVAL:
        return WorkoutType.INTERVAL
    if hrr >= HRR_RACE and race_label(distance_m):
        return WorkoutType.RACE
    if is_long and hrr < HRR_LONG_CEILING:
        return WorkoutType.LONG
    if hrr >= HRR_INTERVAL and pace_cv is None:  # no samples: intensity is the only clue
        return WorkoutType.INTERVAL
    if hrr >= HRR_TEMPO:  # steady and hard
        return WorkoutType.TEMPO
    if hrr < HRR_RECOVERY and distance_m < RECOVERY_FACTOR * median_distance_m:
        return WorkoutType.RECOVERY
    return WorkoutType.EASY


def run_title(workout_type: WorkoutType, distance_m: float, indoor: bool = False) -> str:
    if workout_type is WorkoutType.RACE and (label := race_label(distance_m)):
        return f"{label} Race"
    if indoor and workout_type is WorkoutType.EASY:
        return "Treadmill Run"
    return WORKOUT_TITLES[workout_type]


def derive_profile(name: str, resting_hr_readings: Sequence[float],
                   workout_heart_rates: Sequence[tuple[float, float]]) -> AthleteProfile:
    """Resting HR: median of the latest 30 readings.
    Max HR: highest *plausible* workout peak, given as (avg_hr, max_hr) pairs.

    Plausibility, not rank: "2nd-highest peak" would discard a runner's one genuine
    race effort as if it were a glitch, understate max HR, and make every tempo run
    look like a race.
    """
    resting = (round(statistics.median(resting_hr_readings[-30:]))
               if resting_hr_readings else DEFAULT_RESTING_HR)
    low, high = PLAUSIBLE_MAX_HR
    peaks = [peak for avg, peak in workout_heart_rates
             if low <= peak <= high and peak <= avg * MAX_PEAK_OVER_AVG]
    max_hr = round(max(peaks)) if peaks else DEFAULT_MAX_HR
    return AthleteProfile(name=name, resting_hr=resting,
                          max_hr=max(max_hr, resting + MIN_HR_RESERVE))
