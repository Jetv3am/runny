"""XGBoost-based next-run pace predictor.

Trains a gradient-boosted regression model on engineered physiological features
derived from the athlete's training history. The model predicts the expected
average pace (sec/km) for the next run given the current training state.

Features are engineered from:
- Banister training load signals (CTL, ATL, TSB)
- Rolling pace/HR averages (7-day, 14-day)
- Recovery metrics (days since last run, days since hard session)
- Temporal patterns (day of week, time of day)
- Volume context (distance bucket, weekly volume)

The model uses a temporal train/test split to prevent data leakage, and
persists trained artifacts via joblib for zero-cost inference at request time.

References:
    Chen, T. & Guestrin, C. (2016). XGBoost: A Scalable Tree Boosting System.
    Banister, E. W. (1991). Modeling elite athletic performance.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np

try:
    import xgboost as xgb
    _HAS_XGBOOST = True
except ImportError:
    _HAS_XGBOOST = False

from app.ml.training_load import compute_training_load, calculate_workout_trimp

logger = logging.getLogger(__name__)

# Model artifact storage
MODEL_DIR = Path(os.getenv("MODEL_DIR", "models"))
MODEL_PATH = MODEL_DIR / "pace_predictor_xgb.joblib"
METADATA_PATH = MODEL_DIR / "pace_predictor_meta.joblib"


@dataclass
class PacePrediction:
    """Predicted pace for the next run."""
    predicted_pace_sec_per_km: float
    predicted_pace_formatted: str       # e.g. "5:23 /km"
    confidence_interval_low: float      # sec/km
    confidence_interval_high: float     # sec/km
    confidence_interval_formatted: str  # e.g. "5:11 to 5:35 /km"
    model_version: str
    feature_importance: dict[str, float]
    features_used: dict[str, float]
    training_metrics: dict[str, float] | None


@dataclass
class TrainingMetrics:
    """Model training evaluation metrics."""
    mae_sec_per_km: float       # Mean Absolute Error
    rmse_sec_per_km: float      # Root Mean Squared Error
    r_squared: float            # Coefficient of determination
    train_samples: int
    test_samples: int
    feature_count: int
    train_date: str


# --- Feature engineering ---

FEATURE_NAMES = [
    "ctl_fitness",
    "atl_fatigue",
    "tsb_form",
    "rolling_pace_7d",
    "rolling_pace_14d",
    "rolling_hr_7d",
    "rolling_hr_14d",
    "rolling_distance_7d",
    "days_since_last_run",
    "days_since_hard_session",
    "weekly_volume_km",
    "run_count_7d",
    "run_count_14d",
    "day_of_week",
    "avg_distance_km_7d",
    "pace_variance_7d",
    "hr_pace_ratio_7d",
    "cumulative_trimp_7d",
    "cumulative_trimp_14d",
    "monotony_7d",
]


def _format_pace(seconds_per_km: float) -> str:
    """Format pace as M:SS /km."""
    total = int(round(seconds_per_km))
    m, s = divmod(total, 60)
    return f"{m}:{s:02d} /km"


def _parse_activity_date(activity: dict[str, Any]) -> datetime | None:
    """Parse activity start_date into a timezone-aware datetime."""
    start_str = activity.get("start_date")
    if not start_str:
        return None
    try:
        dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _is_hard_session(activity: dict[str, Any]) -> bool:
    """Determine if a run was a hard effort."""
    avg_hr = activity.get("average_heartrate")
    if isinstance(avg_hr, (int, float)) and float(avg_hr) > 155:
        return True
    distance_m = float(activity.get("distance_m") or 0)
    duration_s = float(activity.get("duration_s") or 0)
    if distance_m > 3000 and duration_s > 0:
        pace = duration_s / (distance_m / 1000)
        if pace < 330:  # Faster than 5:30/km
            return True
    if distance_m > 12000:
        return True
    return False


def _engineer_features(
    activities: list[dict[str, Any]],
    target_idx: int,
    resting_hr: float = 60.0,
    max_hr: float = 190.0,
) -> dict[str, float] | None:
    """Engineer features for a single training example.

    Features are computed from the *prior* history looking backward from
    the activity at target_idx. This ensures no data leakage.

    Args:
        activities: Chronologically sorted activities (oldest first).
        target_idx: Index of the activity to predict (features from prior runs).
        resting_hr: Athlete's resting heart rate.
        max_hr: Athlete's max heart rate.

    Returns:
        Feature dict, or None if insufficient prior data.
    """
    if target_idx < 5:  # Need at least 5 prior runs for meaningful features
        return None

    target = activities[target_idx]
    target_dt = _parse_activity_date(target)
    if target_dt is None:
        return None

    # Collect prior running activities
    prior = []
    for i in range(target_idx):
        act = activities[i]
        if str(act.get("type") or "").lower() != "running":
            continue
        dt = _parse_activity_date(act)
        if dt is None:
            continue
        distance_m = act.get("distance_m")
        duration_s = act.get("duration_s")
        if not isinstance(distance_m, (int, float)) or not isinstance(duration_s, (int, float)):
            continue
        if float(distance_m) < 1000 or float(duration_s) < 180:
            continue
        pace = float(duration_s) / (float(distance_m) / 1000.0)
        if pace < 150 or pace > 600:
            continue
        prior.append({
            "dt": dt,
            "distance_m": float(distance_m),
            "duration_s": float(duration_s),
            "pace_per_km": pace,
            "avg_hr": float(act.get("average_heartrate")) if isinstance(act.get("average_heartrate"), (int, float)) and float(act.get("average_heartrate")) > 0 else None,
            "is_hard": _is_hard_session(act),
            "raw": act,
        })

    if len(prior) < 5:
        return None

    # --- Compute CTL/ATL/TSB from prior activities ---
    prior_raw = [p["raw"] for p in prior]
    load_snapshot = compute_training_load(
        prior_raw, resting_hr=resting_hr, max_hr=max_hr, days=90, now=target_dt,
    )

    # --- Rolling windows ---
    seven_days_ago = target_dt - timedelta(days=7)
    fourteen_days_ago = target_dt - timedelta(days=14)

    runs_7d = [p for p in prior if p["dt"] > seven_days_ago]
    runs_14d = [p for p in prior if p["dt"] > fourteen_days_ago]

    # Rolling pace averages
    rolling_pace_7d = np.mean([p["pace_per_km"] for p in runs_7d]) if runs_7d else prior[-1]["pace_per_km"]
    rolling_pace_14d = np.mean([p["pace_per_km"] for p in runs_14d]) if runs_14d else prior[-1]["pace_per_km"]

    # Rolling HR averages
    hrs_7d = [p["avg_hr"] for p in runs_7d if p["avg_hr"] is not None]
    hrs_14d = [p["avg_hr"] for p in runs_14d if p["avg_hr"] is not None]
    rolling_hr_7d = np.mean(hrs_7d) if hrs_7d else 0.0
    rolling_hr_14d = np.mean(hrs_14d) if hrs_14d else 0.0

    # Rolling distance
    rolling_distance_7d = sum(p["distance_m"] / 1000 for p in runs_7d)

    # Days since last run
    days_since_last = (target_dt - prior[-1]["dt"]).total_seconds() / 86400.0

    # Days since last hard session
    hard_sessions = [p for p in prior if p["is_hard"]]
    if hard_sessions:
        days_since_hard = (target_dt - hard_sessions[-1]["dt"]).total_seconds() / 86400.0
    else:
        days_since_hard = 14.0

    # Weekly volume
    weekly_volume = sum(p["distance_m"] / 1000 for p in runs_7d)

    # Run counts
    run_count_7d = len(runs_7d)
    run_count_14d = len(runs_14d)

    # Day of week (0=Mon, 6=Sun)
    day_of_week = target_dt.weekday()

    # Average distance per run in last 7 days
    avg_distance_7d = np.mean([p["distance_m"] / 1000 for p in runs_7d]) if runs_7d else 0.0

    # Pace variance (consistency indicator)
    pace_variance_7d = float(np.var([p["pace_per_km"] for p in runs_7d])) if len(runs_7d) >= 2 else 0.0

    # HR-to-pace ratio (cardiac efficiency indicator)
    hr_pace_pairs = [(p["avg_hr"], p["pace_per_km"]) for p in runs_7d if p["avg_hr"] is not None]
    if hr_pace_pairs:
        hr_pace_ratio = np.mean([hr / pace for hr, pace in hr_pace_pairs])
    else:
        hr_pace_ratio = 0.0

    # Cumulative TRIMP
    trimp_7d = load_snapshot.total_trimp_7d
    trimp_14d = load_snapshot.total_trimp_28d * 0.5  # Approximate 14d from 28d

    # Monotony
    monotony = load_snapshot.monotony or 0.0

    return {
        "ctl_fitness": load_snapshot.ctl_fitness,
        "atl_fatigue": load_snapshot.atl_fatigue,
        "tsb_form": load_snapshot.tsb_form,
        "rolling_pace_7d": float(rolling_pace_7d),
        "rolling_pace_14d": float(rolling_pace_14d),
        "rolling_hr_7d": float(rolling_hr_7d),
        "rolling_hr_14d": float(rolling_hr_14d),
        "rolling_distance_7d": float(rolling_distance_7d),
        "days_since_last_run": float(days_since_last),
        "days_since_hard_session": float(days_since_hard),
        "weekly_volume_km": float(weekly_volume),
        "run_count_7d": float(run_count_7d),
        "run_count_14d": float(run_count_14d),
        "day_of_week": float(day_of_week),
        "avg_distance_km_7d": float(avg_distance_7d),
        "pace_variance_7d": float(pace_variance_7d),
        "hr_pace_ratio_7d": float(hr_pace_ratio),
        "cumulative_trimp_7d": float(trimp_7d),
        "cumulative_trimp_14d": float(trimp_14d),
        "monotony_7d": float(monotony),
    }


def _build_dataset(
    activities: list[dict[str, Any]],
    resting_hr: float = 60.0,
    max_hr: float = 190.0,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, float]]]:
    """Build feature matrix and target vector from activity history.

    Uses temporal ordering: each sample's features come only from prior runs.

    Returns:
        (X, y, feature_dicts) where X is the feature matrix, y is pace sec/km,
        and feature_dicts are the raw feature dictionaries.
    """
    # Sort chronologically (oldest first)
    sorted_activities = sorted(
        [a for a in activities if str(a.get("type") or "").lower() == "running"],
        key=lambda a: a.get("start_date", ""),
    )

    X_list: list[list[float]] = []
    y_list: list[float] = []
    feat_dicts: list[dict[str, float]] = []

    for idx in range(len(sorted_activities)):
        act = sorted_activities[idx]
        distance_m = act.get("distance_m")
        duration_s = act.get("duration_s")
        if not isinstance(distance_m, (int, float)) or not isinstance(duration_s, (int, float)):
            continue
        if float(distance_m) < 1500 or float(duration_s) < 300:
            continue

        pace = float(duration_s) / (float(distance_m) / 1000.0)
        if pace < 150 or pace > 600:
            continue

        features = _engineer_features(sorted_activities, idx, resting_hr, max_hr)
        if features is None:
            continue

        X_list.append([features[name] for name in FEATURE_NAMES])
        y_list.append(pace)
        feat_dicts.append(features)

    return np.array(X_list), np.array(y_list), feat_dicts


# --- Model training ---

def train_pace_model(
    activities: list[dict[str, Any]],
    resting_hr: float = 60.0,
    max_hr: float = 190.0,
    test_fraction: float = 0.2,
) -> TrainingMetrics | None:
    """Train the XGBoost pace prediction model.

    Uses a temporal train/test split (last N% of runs as test set) to
    prevent data leakage. Persists the trained model to disk.

    Args:
        activities: All running activities from the database.
        resting_hr: Athlete's resting heart rate.
        max_hr: Athlete's max heart rate.
        test_fraction: Fraction of data to hold out for testing.

    Returns:
        TrainingMetrics with evaluation results, or None if insufficient data.
    """
    if not _HAS_XGBOOST:
        logger.error("XGBoost is not installed. Run: pip install xgboost")
        return None

    X, y, feat_dicts = _build_dataset(activities, resting_hr, max_hr)

    if len(X) < 10:
        logger.warning("Insufficient data for model training: %d samples (need ≥10)", len(X))
        return None

    # Temporal split: train on earlier runs, test on recent runs
    split_idx = int(len(X) * (1 - test_fraction))
    split_idx = max(5, split_idx)  # Ensure at least 5 training samples

    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    if len(X_test) < 2:
        logger.warning("Not enough test data: %d test samples", len(X_test))
        return None

    # Train XGBoost regressor
    model = xgb.XGBRegressor(
        n_estimators=150,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        min_child_weight=3,
        objective="reg:squarederror",
        random_state=42,
        verbosity=0,
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    # Evaluate
    y_pred = model.predict(X_test)
    residuals = y_test - y_pred
    mae = float(np.mean(np.abs(residuals)))
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((y_test - np.mean(y_test)) ** 2))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Feature importance
    importance = dict(zip(FEATURE_NAMES, model.feature_importances_.tolist()))

    # Persist model
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    metrics = TrainingMetrics(
        mae_sec_per_km=round(mae, 2),
        rmse_sec_per_km=round(rmse, 2),
        r_squared=round(r_squared, 4),
        train_samples=len(X_train),
        test_samples=len(X_test),
        feature_count=len(FEATURE_NAMES),
        train_date=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )

    artifact = {
        "model": model,
        "feature_names": FEATURE_NAMES,
        "importance": importance,
        "metrics": asdict(metrics),
    }
    joblib.dump(artifact, MODEL_PATH)
    joblib.dump(asdict(metrics), METADATA_PATH)

    logger.info(
        "Pace predictor trained: MAE=%.1f sec/km, RMSE=%.1f sec/km, R²=%.4f (%d train / %d test)",
        mae, rmse, r_squared, len(X_train), len(X_test),
    )

    return metrics


# --- Inference ---

def _load_model() -> tuple[Any, list[str], dict[str, float], dict[str, float]] | None:
    """Load the persisted XGBoost model and metadata."""
    if not MODEL_PATH.exists():
        return None
    try:
        artifact = joblib.load(MODEL_PATH)
        return (
            artifact["model"],
            artifact["feature_names"],
            artifact["importance"],
            artifact["metrics"],
        )
    except Exception as exc:
        logger.error("Failed to load pace predictor model: %s", exc)
        return None


def predict_next_run_pace(
    activities: list[dict[str, Any]],
    resting_hr: float = 60.0,
    max_hr: float = 190.0,
    now: datetime | None = None,
) -> PacePrediction | None:
    """Predict expected pace for the next run.

    Uses the trained XGBoost model with current training state features.
    Falls back to rolling average if model is not trained.

    Args:
        activities: Recent running activities.
        resting_hr: Athlete's resting heart rate.
        max_hr: Athlete's max heart rate.
        now: Reference timestamp.

    Returns:
        PacePrediction, or None if prediction is not possible.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # Sort chronologically
    sorted_activities = sorted(
        [a for a in activities if str(a.get("type") or "").lower() == "running"],
        key=lambda a: a.get("start_date", ""),
    )

    if len(sorted_activities) < 5:
        return None

    # Create a synthetic "next run" entry to generate features for
    synthetic_next = {
        "type": "Running",
        "start_date": now.isoformat(),
        "distance_m": 5000,
        "duration_s": 1500,  # Placeholder
    }
    extended = sorted_activities + [synthetic_next]
    target_idx = len(extended) - 1

    features = _engineer_features(extended, target_idx, resting_hr, max_hr)
    if features is None:
        return None

    # Try XGBoost model first
    loaded = _load_model()
    if loaded is not None and _HAS_XGBOOST:
        model, feature_names, importance, train_metrics = loaded
        X = np.array([[features[name] for name in feature_names]])

        predicted = float(model.predict(X)[0])

        # Estimate confidence interval using the model's residual statistics
        rmse = train_metrics.get("rmse_sec_per_km", 15.0)
        ci_low = predicted - 1.96 * rmse * 0.5   # ~68% CI
        ci_high = predicted + 1.96 * rmse * 0.5

        # Sort importance and take top features
        sorted_importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True)[:8])

        return PacePrediction(
            predicted_pace_sec_per_km=round(predicted, 1),
            predicted_pace_formatted=_format_pace(predicted),
            confidence_interval_low=round(ci_low, 1),
            confidence_interval_high=round(ci_high, 1),
            confidence_interval_formatted=f"{_format_pace(ci_low)} to {_format_pace(ci_high)}",
            model_version="xgboost_v1",
            feature_importance=sorted_importance,
            features_used={k: round(v, 2) for k, v in features.items()},
            training_metrics=train_metrics,
        )

    # Fallback: weighted rolling average
    recent = sorted_activities[-7:]
    paces = []
    for act in recent:
        d = act.get("distance_m")
        t = act.get("duration_s")
        if isinstance(d, (int, float)) and isinstance(t, (int, float)) and float(d) > 0:
            paces.append(float(t) / (float(d) / 1000.0))

    if not paces:
        return None

    # Exponential weights: most recent run weighted highest
    weights = [math.exp(0.3 * i) for i in range(len(paces))]
    predicted = sum(p * w for p, w in zip(paces, weights)) / sum(weights)
    std = float(np.std(paces)) if len(paces) >= 3 else 15.0

    return PacePrediction(
        predicted_pace_sec_per_km=round(predicted, 1),
        predicted_pace_formatted=_format_pace(predicted),
        confidence_interval_low=round(predicted - std, 1),
        confidence_interval_high=round(predicted + std, 1),
        confidence_interval_formatted=f"{_format_pace(predicted - std)} to {_format_pace(predicted + std)}",
        model_version="rolling_average_fallback",
        feature_importance={},
        features_used={k: round(v, 2) for k, v in features.items()} if features else {},
        training_metrics=None,
    )


def get_model_status() -> dict[str, Any]:
    """Return the current model training status and metadata."""
    if not MODEL_PATH.exists():
        return {
            "status": "not_trained",
            "message": "No trained model found. Call POST /ml/train to train the pace predictor.",
        }

    try:
        meta = joblib.load(METADATA_PATH)
        return {
            "status": "trained",
            "metrics": meta,
        }
    except Exception:
        return {
            "status": "trained",
            "message": "Model exists but metadata could not be loaded.",
        }
