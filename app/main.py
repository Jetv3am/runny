"""Local-first Running Coach API using Apple Health exports.

Run from the project root:
    uvicorn app.main:app --reload
Then open http://127.0.0.1:8000 to upload export.zip or export.xml.
"""

from datetime import datetime, timezone
import secrets
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import db
from app.analytics import build_fitness_profile
from app.apple_health import AppleHealthImportError, parse_apple_health_upload
from app.config import MAX_UPLOAD_MB, MAX_XML_MB, SYNC_API_TOKEN
from app.planner import DISTANCE_KM, DAY_NAMES, build_weekly_plan

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


app = FastAPI(
    title="Running Coach API",
    description=(
        "A local-first running coach foundation. Import workouts from an Apple Health "
        "export, review your training data, and calculate a basic fitness profile. "
        "No Strava account or paid API is required."
    ),
    version="0.2.0",
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


@app.get("/fitness/profile")
def fitness_profile(days: int = Query(default=28, ge=7, le=365)) -> dict:
    """Calculate a deterministic recent-fitness summary from imported records."""
    activities = db.list_activities(limit=10000)
    metrics = db.list_health_metrics(limit=1000, metric_type="vo2_max")
    return build_fitness_profile(activities, metrics, days=days)


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


@app.get("/training/plan")
def training_plan(days: int = Query(default=28, ge=7, le=365)) -> dict:
    """Generate a conservative rule-based weekly plan from the latest goal and profile."""
    goal = db.get_running_goal()
    if goal is None:
        raise HTTPException(status_code=400, detail="Save a running goal first by POSTing to /goals.")
    activities = db.list_activities(limit=10000)
    metrics = db.list_health_metrics(limit=1000, metric_type="vo2_max")
    profile = build_fitness_profile(activities, metrics, days=days)
    return build_weekly_plan(profile, goal)


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
