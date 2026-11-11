"""Public data contracts shared by the REST API and (later) the AI coach tools.

Frontend TypeScript types are generated from these via OpenAPI - edit here only.
Units: metres, seconds, seconds-per-km. Formatting is the client's job.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from coach.domain.models import WorkoutType

DataSource = Literal["demo", "apple_health"]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthStatus(Schema):
    status: Literal["ok"]
    version: str
    data_source: DataSource


# --- Workouts -----------------------------------------------------------------

class SplitOut(Schema):
    index: int
    distance_m: float
    duration_s: float
    pace_s_per_km: float
    avg_hr: int | None
    elevation_delta_m: float


class WorkoutSummary(Schema):
    id: str
    title: str
    type: WorkoutType
    start_at: datetime
    distance_m: float
    duration_s: float
    pace_s_per_km: float
    avg_hr: int | None
    elevation_gain_m: float | None
    trimp: float
    is_race: bool


class WorkoutDetail(WorkoutSummary):
    max_hr: int | None
    energy_kcal: float | None
    avg_cadence: int | None
    temperature_c: float | None
    splits: list[SplitOut]


class WorkoutPage(Schema):
    items: list[WorkoutSummary]
    total: int
    limit: int
    offset: int


class WeeklyVolume(Schema):
    week_start: date
    distance_m: float
    duration_s: float
    runs: int


# --- Fitness ------------------------------------------------------------------

class DailyMetric(Schema):
    date: date
    distance_m: float
    trimp: float
    ctl: float = Field(description="Chronic training load (fitness), 42-day EWMA of TRIMP")
    atl: float = Field(description="Acute training load (fatigue), 7-day EWMA of TRIMP")
    tsb: float = Field(description="Training stress balance (form) = yesterday's CTL - ATL")


class HealthMetric(Schema):
    date: date
    type: Literal["vo2max", "resting_hr"]
    value: float
    unit: str


class FitnessSummary(Schema):
    athlete_name: str
    vdot: float | None
    vdot_change_28d: float | None
    ctl: float
    atl: float
    tsb: float
    form: str
    readiness: int = Field(ge=0, le=100)
    readiness_label: str
    week_distance_m: float
    week_runs: int
    avg_week_distance_4w_m: float
    briefing: str = Field(description="Plain-language advice. Contains no numbers/units by design")


class PaceZoneOut(Schema):
    key: str
    name: str
    purpose: str
    fast_s_per_km: float
    slow_s_per_km: float


class TrainingPaces(Schema):
    vdot: float
    zones: list[PaceZoneOut]


# --- Predictions --------------------------------------------------------------

class RacePrediction(Schema):
    key: str
    label: str
    distance_m: float
    predicted_s: float
    p10_s: float = Field(description="Optimistic bound (10th percentile)")
    p90_s: float = Field(description="Conservative bound (90th percentile)")
    pace_s_per_km: float


class RacePredictions(Schema):
    source: Literal["vdot_baseline", "ml"]
    vdot: float
    based_on: str
    generated_at: datetime
    predictions: list[RacePrediction]


# --- Plans --------------------------------------------------------------------

SessionStatus = Literal["planned", "completed", "missed", "rest"]


class PlannedSessionOut(Schema):
    date: date
    type: WorkoutType | None
    title: str
    description: str
    distance_m: float
    target_fast_s_per_km: float | None
    target_slow_s_per_km: float | None
    status: SessionStatus
    completed_workout_id: str | None


class PlanWeekOut(Schema):
    index: int
    start_date: date
    phase: Literal["base", "build", "peak", "taper"]
    target_distance_m: float
    sessions: list[PlannedSessionOut]


class GoalOut(Schema):
    race_label: str
    distance_m: float
    race_date: date
    target_time_s: float | None
    predicted_time_s: float | None


class TrainingPlan(Schema):
    goal: GoalOut
    generator: Literal["rules"]
    weeks: list[PlanWeekOut]


# --- Imports ------------------------------------------------------------------

ImportStatus = Literal["processing", "completed", "failed"]


class ImportRecord(Schema):
    id: str
    filename: str
    size_bytes: int
    status: ImportStatus
    progress: float = Field(ge=0, le=100, description="Percent complete")
    message: str
    created_at: datetime


# --- Coach chat ---------------------------------------------------------------

class ChatMessage(Schema):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(Schema):
    messages: list[ChatMessage] = Field(min_length=1, max_length=50)
