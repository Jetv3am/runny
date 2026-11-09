"""Local-first Running Coach API using Apple Health exports.

Run from the project root:
    uvicorn app.main:app --reload
Then open http://127.0.0.1:8000 to upload export.zip or export.xml.
"""

from datetime import datetime, timezone
import secrets
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import db
from app.analytics import build_fitness_profile
from app.apple_health import AppleHealthImportError, parse_apple_health_upload
from app.config import MAX_UPLOAD_MB, MAX_XML_MB, SYNC_API_TOKEN
from app.planner import DISTANCE_KM, DAY_NAMES, build_weekly_plan
from app.ml.profile import build_ml_fitness_profile, fitness_profile_to_dict, fitness_profile_for_llm
from app.ml.pace_predictor import (
    train_pace_model, predict_next_run_pace, get_model_status,
)
from app.ai.coach import generate_ai_training_plan, answer_coaching_query
from app.ai.rag import index_training_history, get_rag_status, retrieve_relevant_runs
from app.ai.guardrails import run_guardrails

class HealthKitWorkout(BaseModel):
    """One running workout sent directly from the companion iOS app."""

    id: str = Field(min_length=1, max_length=120)
    start_date: datetime
    end_date: datetime
    distance_m: float | None = Field(default=None, ge=0)
    duration_s: float = Field(ge=0)
    energy_kcal: float | None = Field(default=None, ge=0)
    average_heartrate: float | None = Field(default=None, ge=0, le=300)
    minimum_heartrate: float | None = Field(default=None, ge=0, le=300)
    max_heartrate: float | None = Field(default=None, ge=0, le=300)
    source_name: str | None = Field(default="HealthKit", max_length=200)


class HealthKitWorkoutBatch(BaseModel):
    workouts: list[HealthKitWorkout] = Field(max_length=500)


class RunningGoalInput(BaseModel):
    goal_type: str = Field(description="One of: 5k, 10k, half_marathon, marathon")
    target_time_seconds: int | None = Field(default=None, ge=1, le=86400)
    race_date: str | None = Field(default=None, description="Optional race date in YYYY-MM-DD format")
    training_days: list[str] = Field(min_length=1, max_length=7, description="Available days, e.g. Monday, Wednesday, Saturday")


class CoachingQueryInput(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="Runner's coaching question")


app = FastAPI(
    title="Running Coach API",
    description=(
        "A local-first running coach foundation. Import workouts from an Apple Health "
        "export, review your training data, and calculate a basic fitness profile. "
        "No Strava account or paid API is required."
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home() -> FileResponse:
    """Serve the responsive dashboard frontend."""
    return FileResponse(Path(__file__).parent / "templates" / "dashboard.html")

@app.get("/health/status")
def health_status() -> dict:
    return {
        "status": "ok",
        "data_source": "apple_health_export",
        "stored_activities": db.count_activities(),
        "stored_health_metrics": db.count_health_metrics(),
    }


@app.post("/health/import")
def import_health_export(file: UploadFile = File(...)) -> dict:
    """Import Apple Health's export ZIP or the export.xml file contained in it."""
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in {".zip", ".xml"}:
        raise HTTPException(status_code=415, detail="Upload an Apple Health .zip or .xml file.")

    file.file.seek(0, 2)
    upload_size = file.file.tell()
    file.file.seek(0)
    max_upload_bytes = MAX_UPLOAD_MB * 1024 * 1024
    if upload_size > max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds the configured {MAX_UPLOAD_MB} MB upload limit.",
        )

    try:
        parsed = parse_apple_health_upload(file.file, MAX_XML_MB * 1024 * 1024)
    except AppleHealthImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, EOFError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read the uploaded file: {exc}") from exc
    finally:
        file.file.close()

    synced_at = _now_iso()
    db.upsert_activities(parsed.workouts, synced_at)
    db.upsert_health_metrics(parsed.health_metrics, synced_at)

    return {
        "status": "imported",
        "filename": filename,
        "source": "apple_health",
        "running_workouts_processed": len(parsed.workouts),
        "other_workouts_ignored": parsed.ignored_workouts,
        "vo2_max_samples_processed": len(parsed.health_metrics),
        "total_workout_elements_seen": parsed.diagnostics.get("workout_elements_seen", len(parsed.workouts) + parsed.ignored_workouts),
        "diagnostics": parsed.diagnostics,
        "synced_at": synced_at,
        "note": "Imports are idempotent: uploading the same export again updates matching records rather than duplicating them.",
    }


@app.get("/activities")
def list_activities(limit: int = Query(default=100, ge=1, le=1000)) -> list[dict]:
    """List recent imported running workouts."""
    return db.list_activities(limit=limit)


@app.get("/health/metrics")
def list_health_metrics(
    limit: int = Query(default=100, ge=1, le=1000),
    metric_type: str | None = Query(default=None, description="For example: vo2_max"),
) -> list[dict]:
    """List imported health metrics. The initial parser currently stores VO2 max."""
    return db.list_health_metrics(limit=limit, metric_type=metric_type)


@app.get("/fitness/profile/basic")
def fitness_profile_basic(days: int = Query(default=28, ge=7, le=365)) -> dict:
    """Legacy: basic deterministic fitness summary (no ML)."""
    activities = db.list_activities(limit=10000)
    metrics = db.list_health_metrics(limit=1000, metric_type="vo2_max")
    return build_fitness_profile(activities, metrics, days=days)


@app.get("/fitness/profile")
def fitness_profile_ml(days: int = Query(default=42, ge=7, le=365)) -> dict:
    """ML-powered fitness profile with VDOT, training load, pace trends, and readiness."""
    activities = db.list_activities(limit=10000)
    metrics = db.list_health_metrics(limit=1000, metric_type="vo2_max")
    goal = db.get_running_goal()
    profile = build_ml_fitness_profile(
        activities, metrics, goal=goal, days=days,
    )
    return fitness_profile_to_dict(profile)


@app.get("/fitness/history")
def fitness_history(days: int = Query(default=90, ge=14, le=365)) -> dict:
    """Training load time-series data for charting (CTL/ATL/TSB over time)."""
    activities = db.list_activities(limit=10000)
    metrics = db.list_health_metrics(limit=1000, metric_type="vo2_max")
    profile = build_ml_fitness_profile(activities, metrics, days=days)
    return {
        "period_days": days,
        "daily_loads": profile.training_load["daily_loads"],
        "pace_history": profile.pace_trend["pace_history"],
        "current": {
            "ctl_fitness": profile.training_load["ctl_fitness"],
            "atl_fatigue": profile.training_load["atl_fatigue"],
            "tsb_form": profile.training_load["tsb_form"],
            "status": profile.training_load["status"],
        },
    }


@app.get("/coaching/insight")
def coaching_insight(days: int = Query(default=42, ge=7, le=365)) -> dict:
    """Get a structured coaching insight from the ML engine.

    This endpoint returns the ML-computed metrics formatted as actionable
    coaching advice. A future version will pass this through Gemini for
    natural-language coaching.
    """
    activities = db.list_activities(limit=10000)
    metrics = db.list_health_metrics(limit=1000, metric_type="vo2_max")
    goal = db.get_running_goal()
    profile = build_ml_fitness_profile(
        activities, metrics, goal=goal, days=days,
    )

    insights = []

    # VDOT insight
    vdot = profile.vdot.get("estimated_vdot")
    if vdot:
        insights.append({
            "category": "fitness_level",
            "title": "Estimated Fitness (VDOT)",
            "value": vdot,
            "detail": f"Your current VDOT of {vdot} places you at a "
                       f"{profile.vdot.get('confidence', 'unknown')} confidence level.",
        })

    # Training load insight
    status = profile.training_load.get("status")
    tsb = profile.training_load.get("tsb_form")
    if status:
        status_messages = {
            "fresh": "You're well rested. Good time to push a quality session.",
            "optimal": "Great balance of fitness and freshness. Ready to perform.",
            "absorbing": "You're building fitness but carrying some fatigue. Stay consistent.",
            "overreaching": "High fatigue detected. Consider a recovery week.",
        }
        insights.append({
            "category": "training_load",
            "title": "Training Status",
            "value": status,
            "detail": status_messages.get(status, ""),
            "tsb_form": tsb,
        })

    # Readiness insight
    insights.append({
        "category": "readiness",
        "title": "Today's Readiness",
        "value": profile.readiness.get("score"),
        "label": profile.readiness.get("label"),
        "detail": profile.readiness.get("recommendation", ""),
    })

    # Race prediction insight
    if profile.race_prediction:
        insights.append({
            "category": "race_readiness",
            "title": f"{profile.race_prediction.get('goal_name', 'Race')} Readiness",
            "probability": profile.race_prediction.get("probability"),
            "label": profile.race_prediction.get("probability_label"),
            "detail": profile.race_prediction.get("assessment", ""),
        })

    return {
        "generated_at": profile.generated_at,
        "confidence": profile.confidence,
        "insights": insights,
        "data_quality": profile.data_quality,
    }


@app.post("/goals")
def save_goal(payload: RunningGoalInput) -> dict:
    """Save the current user's race goal and available training days."""
    goal_type = payload.goal_type.strip().lower()
    if goal_type not in DISTANCE_KM:
        raise HTTPException(status_code=422, detail=f"goal_type must be one of: {', '.join(DISTANCE_KM)}")
    training_days = list(dict.fromkeys(day.strip().title() for day in payload.training_days))
    invalid_days = [day for day in training_days if day not in DAY_NAMES]
    if invalid_days:
        raise HTTPException(status_code=422, detail=f"Invalid training days: {', '.join(invalid_days)}")
    if payload.race_date:
        try:
            race_date = datetime.strptime(payload.race_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="race_date must use YYYY-MM-DD format") from exc
        if race_date < datetime.now(timezone.utc).date():
            raise HTTPException(status_code=422, detail="race_date cannot be in the past")
    goal = {
        "goal_type": goal_type,
        "target_time_seconds": payload.target_time_seconds,
        "race_date": payload.race_date,
        "training_days": training_days,
        "created_at": _now_iso(),
    }
    return db.save_running_goal(goal)


@app.get("/goals")
def get_goal() -> dict:
    goal = db.get_running_goal()
    if goal is None:
        raise HTTPException(status_code=404, detail="No goal saved yet. POST a goal to /goals first.")
    return goal


@app.get("/training/plan/basic")
def training_plan_basic(days: int = Query(default=28, ge=7, le=365)) -> dict:
    """Legacy: simple conservative rule-based weekly plan."""
    goal = db.get_running_goal()
    if goal is None:
        raise HTTPException(status_code=400, detail="Save a running goal first by POSTing to /goals.")
    activities = db.list_activities(limit=10000)
    metrics = db.list_health_metrics(limit=1000, metric_type="vo2_max")
    profile = build_fitness_profile(activities, metrics, days=days)
    return build_weekly_plan(profile, goal)


@app.get("/training/plan")
def training_plan(days: int = Query(default=42, ge=7, le=365)) -> dict:
    """Generate an adaptive weekly plan powered by ML metrics (VDOT, CTL/ATL, readiness, Daniels pace zones)."""
    goal = db.get_running_goal()
    if goal is None:
        raise HTTPException(status_code=400, detail="Save a running goal first by POSTing to /goals.")
    activities = db.list_activities(limit=10000)
    metrics = db.list_health_metrics(limit=1000, metric_type="vo2_max")
    profile = build_ml_fitness_profile(activities, metrics, goal=goal, days=days)
    return generate_ai_training_plan(profile, goal)


@app.post("/coaching/ask")
def coaching_ask(payload: CoachingQueryInput, days: int = Query(default=42, ge=7, le=365)) -> dict:
    """Ask the AI coach a question grounded in your current ML training metrics."""
    activities = db.list_activities(limit=10000)
    metrics = db.list_health_metrics(limit=1000, metric_type="vo2_max")
    goal = db.get_running_goal()
    profile = build_ml_fitness_profile(activities, metrics, goal=goal, days=days)
    return answer_coaching_query(profile, payload.query)


@app.post("/health/workouts/sync")
def sync_healthkit_workouts(
    payload: HealthKitWorkoutBatch,
    authorization: str | None = Header(default=None),
) -> dict:
    """Receive new running workouts from the iOS HealthKit companion app.

    This endpoint requires SYNC_API_TOKEN to be configured. Repeated uploads are
    safe because each HealthKit workout UUID is used as the stable database ID.
    """
    if not SYNC_API_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Direct HealthKit sync is disabled. Set SYNC_API_TOKEN in your .env file and restart the server.",
        )
    expected = f"Bearer {SYNC_API_TOKEN}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token.")

    activities: list[dict] = []
    for workout in payload.workouts:
        # Keep this MVP focused on runs; cycling and other activities are ignored.
        start = workout.start_date
        end = workout.end_date
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        start_iso = start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        end_iso = end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        # The iOS client filters to running workouts before upload. Store a stable
        # HealthKit UUID so repeated syncs upsert the same run instead of duplicating it.
        activity_id = workout.id.strip()
        if not activity_id.startswith("healthkit_"):
            activity_id = f"healthkit_{activity_id}"
        activities.append({
            "id": activity_id,
            "source": "apple_healthkit",
            "name": f"Run — {start_iso[:10]}",
            "type": "Running",
            "start_date": start_iso,
            "end_date": end_iso,
            "distance_m": workout.distance_m,
            "duration_s": workout.duration_s,
            "average_heartrate": workout.average_heartrate,
            "minimum_heartrate": workout.minimum_heartrate,
            "max_heartrate": workout.max_heartrate,
            "energy_kcal": workout.energy_kcal,
            "source_name": workout.source_name or "HealthKit",
        })

    synced_at = _now_iso()
    db.upsert_activities(activities, synced_at)
    return {
        "status": "synced",
        "source": "apple_healthkit",
        "workouts_processed": len(activities),
        "other_workouts_ignored": 0,
        "synced_at": synced_at,
    }


# --- ML Model Endpoints ---

@app.post("/ml/train")
def train_ml_model() -> dict:
    """Train the XGBoost pace prediction model on the athlete's training history.

    Uses all running activities in the database. Training uses a temporal
    train/test split to prevent data leakage. The trained model is persisted
    to disk and used for subsequent predictions.
    """
    activities = db.list_activities(limit=10000)
    result = train_pace_model(activities)
    if result is None:
        raise HTTPException(
            status_code=400,
            detail="Insufficient data to train the model. Need at least 10 quality runs.",
        )
    return {
        "status": "trained",
        "metrics": {
            "mae_sec_per_km": result.mae_sec_per_km,
            "rmse_sec_per_km": result.rmse_sec_per_km,
            "r_squared": result.r_squared,
            "train_samples": result.train_samples,
            "test_samples": result.test_samples,
            "feature_count": result.feature_count,
            "train_date": result.train_date,
        },
    }


@app.get("/ml/predict/pace")
def predict_pace() -> dict:
    """Predict expected pace for the next run using the trained XGBoost model.

    Falls back to a weighted rolling average if the model isn't trained yet.
    """
    activities = db.list_activities(limit=10000)
    prediction = predict_next_run_pace(activities)
    if prediction is None:
        raise HTTPException(
            status_code=400,
            detail="Not enough running data to make a prediction. Import more runs first.",
        )
    return {
        "predicted_pace": prediction.predicted_pace_formatted,
        "predicted_pace_sec_per_km": prediction.predicted_pace_sec_per_km,
        "confidence_interval": prediction.confidence_interval_formatted,
        "model_version": prediction.model_version,
        "feature_importance": prediction.feature_importance,
        "features_used": prediction.features_used,
        "training_metrics": prediction.training_metrics,
    }


@app.get("/ml/status")
def ml_model_status() -> dict:
    """Check the current status and metrics of the trained ML models."""
    return {
        "pace_predictor": get_model_status(),
    }


# --- RAG Endpoints ---

@app.post("/rag/index")
def rag_index(force: bool = Query(default=False, description="Force full reindex")) -> dict:
    """Index training history into the vector store for RAG-augmented coaching.

    Incrementally adds new activities. Set force=true to rebuild from scratch.
    """
    activities = db.list_activities(limit=10000)
    return index_training_history(activities, force_reindex=force)


@app.get("/rag/status")
def rag_status() -> dict:
    """Check the current status of the RAG vector store."""
    return get_rag_status()


@app.get("/rag/search")
def rag_search(q: str = Query(description="Search query"), n: int = Query(default=5, ge=1, le=20)) -> dict:
    """Search the vector store for relevant past runs."""
    results = retrieve_relevant_runs(q, n_results=n)
    return {
        "query": q,
        "results": results,
        "count": len(results),
    }


# --- Guardrails Endpoint ---

@app.post("/guardrails/validate")
def validate_plan(days: int = Query(default=42, ge=7, le=365)) -> dict:
    """Generate a training plan and return detailed guardrail validation results.

    Useful for debugging and evaluating the safety of AI-generated plans.
    """
    goal = db.get_running_goal()
    if goal is None:
        raise HTTPException(status_code=400, detail="Save a running goal first by POSTing to /goals.")
    activities = db.list_activities(limit=10000)
    metrics = db.list_health_metrics(limit=1000, metric_type="vo2_max")
    profile = build_ml_fitness_profile(activities, metrics, goal=goal, days=days)

    plan = generate_ai_training_plan(profile, goal)

    # Run full guardrails independently
    guardrail_result = run_guardrails(
        plan=plan,
        current_weekly_km=float(profile.training_load.get("total_trimp_7d", 0)) * 0.15,
        pace_zones=profile.vdot.get("pace_zones") or {},
        vdot=profile.vdot.get("estimated_vdot"),
        goal=goal,
        readiness_score=int(profile.readiness.get("score") or 70),
    )

    return {
        "plan": plan,
        "guardrails": {
            "is_safe": guardrail_result.is_safe,
            "violations": [
                {"category": v.category, "severity": v.severity,
                 "field": v.field, "message": v.message, "auto_fixed": v.auto_fixed}
                for v in guardrail_result.violations
            ],
            "validation_time_ms": guardrail_result.validation_time_ms,
        },
        "corrected_plan": guardrail_result.corrected_plan,
    }
