"""Workout listing, detail, and weekly volume."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from coach.domain.models import WorkoutType
from coach.schemas import WeeklyVolume, WorkoutDetail, WorkoutPage, WorkoutSummary
from coach.services import repository


def list_workouts(limit: int, offset: int, workout_type: WorkoutType | None = None) -> WorkoutPage:
    """Newest-first page of workouts, optionally filtered by type."""
    workouts = [w for w in reversed(repository.get_workouts())
                if workout_type is None or w.type is workout_type]
    page = workouts[offset:offset + limit]
    return WorkoutPage(
        items=[WorkoutSummary.model_validate(w) for w in page],
        total=len(workouts),
        limit=limit,
        offset=offset,
    )


def get_workout(workout_id: str) -> WorkoutDetail | None:
    workout = repository.get_workout(workout_id)
    return WorkoutDetail.model_validate(workout) if workout else None


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weekly_volume(weeks: int) -> list[WeeklyVolume]:
    """Zero-filled weekly totals for the last `weeks` weeks, including the current one."""
    current = week_start(repository.today())
    starts = [current - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    totals: dict[date, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])
    for w in repository.get_workouts():
        bucket = totals[week_start(w.day)]
        bucket[0] += w.distance_m
        bucket[1] += w.duration_s
        bucket[2] += 1
    return [
        WeeklyVolume(week_start=s, distance_m=round(totals[s][0], 1),
                     duration_s=totals[s][1], runs=int(totals[s][2]))
        for s in starts
    ]
