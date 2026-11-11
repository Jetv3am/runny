"""Rule-based periodised training plan generator.

Rules (see DESIGN.md section 10): Base -> Build -> Peak -> Taper, weekly volume
ramps <= 10% with a cut-back every 4th week, long run ~30% of volume,
at most two quality sessions per week, never back-to-back hard days.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from coach.domain.models import Goal, WorkoutType

MAX_RAMP = 1.10
CUTBACK_FACTOR = 0.80
CUTBACK_EVERY = 4
PEAK_CAP = 1.45  # peak volume capped at 145% of starting volume
LONG_RUN_SHARE = 0.30


@dataclass(frozen=True, slots=True)
class PlannedSession:
    day: date
    type: WorkoutType | None  # None = rest day
    title: str
    description: str
    distance_m: float
    pace_zone: str | None  # key into vdot.training_paces


@dataclass(frozen=True, slots=True)
class PlanWeek:
    index: int
    start: date
    phase: str
    target_distance_m: float
    sessions: tuple[PlannedSession, ...]


# weekday -> (type, share of weekly volume, pace zone, title, description)
_Template = dict[int, tuple[WorkoutType, float, str, str, str]]

# Descriptions are unit-free (time-based) - the client renders distances in the user's units.
_EASY = (WorkoutType.EASY, 0.17, "easy", "Easy run", "Conversational pace. Keep HR in zone 2.")
_RECOVERY = (WorkoutType.RECOVERY, 0.10, "easy", "Recovery run",
             "Very relaxed. Slower than you think.")
_LONG = (WorkoutType.LONG, LONG_RUN_SHARE, "easy", "Long run",
         "Steady and easy. Practice fuelling.")
_TEMPO = (WorkoutType.TEMPO, 0.16, "threshold", "Tempo run",
          "10 min easy, 20-30 min at threshold, 10 min easy.")
_INTERVALS = (WorkoutType.INTERVAL, 0.14, "interval", "Intervals",
              "Warm up, 5 x 4 min at interval pace with 2-3 min jogs, cool down.")
_STRIDES = (WorkoutType.EASY, 0.14, "easy", "Easy + strides",
            "Easy run finishing with 6 x 20 s relaxed strides.")

_PHASE_TEMPLATES: dict[str, _Template] = {
    "base": {1: _STRIDES, 2: _EASY, 3: _TEMPO, 5: _RECOVERY, 6: _LONG},
    "build": {1: _INTERVALS, 2: _EASY, 3: _TEMPO, 5: _RECOVERY, 6: _LONG},
    "peak": {1: _INTERVALS, 2: _EASY, 3: _TEMPO, 5: _RECOVERY, 6: _LONG},
    "taper": {1: _INTERVALS, 2: _EASY, 3: _TEMPO, 5: _RECOVERY, 6: _LONG},
}


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def phase_for_week(week: int, total_weeks: int, race_distance_m: float) -> str:
    taper_weeks = 1 if race_distance_m <= 10_000 else 2
    peak_weeks = min(3, max(0, total_weeks - taper_weeks - 2))
    if week >= total_weeks - taper_weeks:
        return "taper"
    if week >= total_weeks - taper_weeks - peak_weeks:
        return "peak"
    base_weeks = max(1, round((total_weeks - taper_weeks - peak_weeks) * 0.4))
    return "base" if week < base_weeks else "build"


def weekly_volumes(start_volume_m: float, phases: list[str]) -> list[float]:
    """Apply ramp, cut-back, peak-cap, and taper rules to produce weekly targets."""
    volumes: list[float] = []
    current = start_volume_m
    cap = start_volume_m * PEAK_CAP
    for i, phase in enumerate(phases):
        if phase == "taper":
            remaining = len(phases) - i
            volumes.append(current * (0.5 if remaining == 1 else 0.7))
            continue
        if i:
            current = min(current * MAX_RAMP, cap)
        is_cutback = (i + 1) % CUTBACK_EVERY == 0
        volumes.append(current * CUTBACK_FACTOR if is_cutback else current)
    return volumes


def _race_week_sessions(monday: date, goal: Goal) -> tuple[PlannedSession, ...]:
    race_day = goal.race_date
    sessions: list[PlannedSession] = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        if day == race_day:
            sessions.append(PlannedSession(day, WorkoutType.RACE, goal.race_label,
                                           "Race day. Trust the taper.", goal.distance_m,
                                           None))
        elif day < race_day and offset in (1, 3):
            sessions.append(PlannedSession(day, WorkoutType.EASY, "Shakeout",
                                           "Short and easy with 4 strides.", 5_000, "easy"))
        else:
            sessions.append(PlannedSession(day, None, "Rest", "Rest or light mobility.", 0, None))
    return tuple(sessions)


def generate_plan(goal: Goal, start: date, start_volume_m: float) -> list[PlanWeek]:
    """Build a week-by-week plan from the Monday of `start` to race week."""
    first_monday = _monday(start)
    total_weeks = max(1, math.ceil(((goal.race_date - first_monday).days + 1) / 7))
    phases = [phase_for_week(w, total_weeks, goal.distance_m) for w in range(total_weeks)]
    volumes = weekly_volumes(start_volume_m, phases)

    weeks: list[PlanWeek] = []
    for index, (phase, volume) in enumerate(zip(phases, volumes, strict=True)):
        monday = first_monday + timedelta(weeks=index)
        if monday <= goal.race_date < monday + timedelta(days=7):
            sessions = _race_week_sessions(monday, goal)
        else:
            sessions = _regular_week(monday, _PHASE_TEMPLATES[phase], volume)
        weeks.append(PlanWeek(index, monday, phase, sum(s.distance_m for s in sessions),
                              sessions))
    return weeks


def _regular_week(monday: date, template: _Template, volume_m: float) -> tuple[PlannedSession, ...]:
    sessions: list[PlannedSession] = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        if offset not in template:
            sessions.append(PlannedSession(day, None, "Rest", "Rest or light mobility.", 0, None))
            continue
        wtype, share, zone, title, description = template[offset]
        distance = round(volume_m * share / 500) * 500  # nearest 0.5 km
        sessions.append(PlannedSession(day, wtype, title, description, distance, zone))
    return tuple(sessions)
