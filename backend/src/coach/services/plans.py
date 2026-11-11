"""Training plan use case: rules engine + plan-vs-actual status."""

from __future__ import annotations

from datetime import timedelta

from coach.domain.plan import PlannedSession, generate_plan
from coach.domain.vdot import race_time_for_vdot, training_paces
from coach.schemas import GoalOut, PlannedSessionOut, PlanWeekOut, SessionStatus, TrainingPlan
from coach.services import repository
from coach.services.fitness import current_vdot
from coach.services.workouts import weekly_volume


def _status(session: PlannedSession, completed_id: str | None) -> SessionStatus:
    if session.type is None:
        return "rest"
    if completed_id:
        return "completed"
    return "missed" if session.day < repository.today() else "planned"


def current_plan() -> TrainingPlan:
    goal = repository.get_goal()
    today = repository.today()
    vdot = current_vdot()
    zones = {z.key: z for z in training_paces(vdot)} if vdot else {}

    recent = weekly_volume(5)[:-1]  # last 4 complete weeks
    start_volume = sum(w.distance_m for w in recent) / len(recent) or 20_000
    weeks = generate_plan(goal, today, start_volume)

    plan_start = weeks[0].start if weeks else today
    done_by_day = {w.day: w.id for w in repository.get_workouts()
                   if plan_start <= w.day < plan_start + timedelta(weeks=len(weeks))}

    def to_out(s: PlannedSession) -> PlannedSessionOut:
        zone = zones.get(s.pace_zone) if s.pace_zone else None
        completed_id = done_by_day.get(s.day) if s.type else None
        return PlannedSessionOut(
            date=s.day, type=s.type, title=s.title, description=s.description,
            distance_m=s.distance_m,
            target_fast_s_per_km=zone.fast_s_per_km if zone else None,
            target_slow_s_per_km=zone.slow_s_per_km if zone else None,
            status=_status(s, completed_id),
            completed_workout_id=completed_id,
        )

    return TrainingPlan(
        goal=GoalOut(
            race_label=goal.race_label, distance_m=goal.distance_m, race_date=goal.race_date,
            target_time_s=goal.target_time_s,
            predicted_time_s=round(race_time_for_vdot(vdot, goal.distance_m)) if vdot else None,
        ),
        generator="rules",
        weeks=[PlanWeekOut(index=w.index, start_date=w.start, phase=w.phase,
                           target_distance_m=w.target_distance_m,
                           sessions=[to_out(s) for s in w.sessions]) for w in weeks],
    )
