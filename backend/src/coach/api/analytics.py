"""Read-only analytics endpoints: workouts, fitness, predictions, plans."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from coach import __version__
from coach.domain.models import WorkoutType
from coach.schemas import (
    DailyMetric,
    FitnessSummary,
    HealthMetric,
    HealthStatus,
    RacePredictions,
    TrainingPaces,
    TrainingPlan,
    WeeklyVolume,
    WorkoutDetail,
    WorkoutPage,
)
from coach.services import fitness, plans, predictions, repository, workouts

router = APIRouter()

NO_EFFORTS = "No recent race efforts yet. Import data or log a race to unlock this."


@router.get("/health", response_model=HealthStatus, tags=["system"])
def health() -> HealthStatus:
    return HealthStatus(status="ok", version=__version__, data_source=repository.data_source())


@router.get("/workouts", response_model=WorkoutPage, tags=["workouts"])
def list_workouts(
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    type: WorkoutType | None = None,  # noqa: A002 - public query param name
) -> WorkoutPage:
    return workouts.list_workouts(limit, offset, type)


@router.get("/workouts/weekly", response_model=list[WeeklyVolume], tags=["workouts"])
def weekly_volume(weeks: Annotated[int, Query(ge=1, le=104)] = 12) -> list[WeeklyVolume]:
    return workouts.weekly_volume(weeks)


@router.get("/workouts/{workout_id}", response_model=WorkoutDetail, tags=["workouts"])
def get_workout(workout_id: str) -> WorkoutDetail:
    workout = workouts.get_workout(workout_id)
    if workout is None:
        raise HTTPException(status_code=404, detail="Workout not found")
    return workout


@router.get("/fitness/summary", response_model=FitnessSummary, tags=["fitness"])
def fitness_summary() -> FitnessSummary:
    return fitness.summary()


@router.get("/fitness/paces", response_model=TrainingPaces, tags=["fitness"])
def training_paces() -> TrainingPaces:
    paces = fitness.training_paces()
    if paces is None:
        raise HTTPException(status_code=404, detail=NO_EFFORTS)
    return paces


@router.get("/metrics/daily", response_model=list[DailyMetric], tags=["fitness"])
def daily_metrics(days: Annotated[int, Query(ge=7, le=730)] = 120) -> list[DailyMetric]:
    return fitness.daily_metrics(days)


@router.get("/metrics/health", response_model=list[HealthMetric], tags=["fitness"])
def health_metrics(type: Literal["vo2max", "resting_hr"] | None = None) -> list[HealthMetric]:  # noqa: A002
    return fitness.health_metrics(type)


@router.get("/predictions/race", response_model=RacePredictions, tags=["predictions"])
def race_predictions() -> RacePredictions:
    result = predictions.race_predictions()
    if result is None:
        raise HTTPException(status_code=404, detail=NO_EFFORTS)
    return result


@router.get("/plans/current", response_model=TrainingPlan, tags=["plans"])
def current_plan() -> TrainingPlan:
    return plans.current_plan()
