"""ML Fitness Profile orchestrator.

Runs all ML models (VDOT, training load, pace trends, readiness, race prediction)
and combines their outputs into a single comprehensive FitnessProfile. This is the
primary entry point for the ML engine — the API layer calls this module, and
its output is also what gets passed to the Gemini LLM for plan generation.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

from app.ml.vdot import estimate_vdot, VdotEstimate
from app.ml.training_load import compute_training_load, TrainingLoadSnapshot
from app.ml.pace_trend import analyze_pace_trend, PaceTrend
from app.ml.readiness import compute_readiness, ReadinessResult
from app.ml.race_predictor import predict_race_readiness, RacePrediction


@dataclass
class FitnessProfile:
    """Complete ML-computed fitness assessment."""
    generated_at: str
    runner_summary: dict[str, Any]      # High-level stats
    vdot: dict[str, Any]                # VDOT estimation + race predictions + pace zones
    training_load: dict[str, Any]       # CTL/ATL/TSB + daily loads
    pace_trend: dict[str, Any]          # Trend direction + history
    readiness: dict[str, Any]           # Readiness score + recommendation
    race_prediction: dict[str, Any] | None  # Race readiness if goal exists
    confidence: str                     # Overall confidence level
    data_quality: dict[str, Any]        # Info about data completeness


def build_ml_fitness_profile(
    activities: list[dict[str, Any]],
    health_metrics: list[dict[str, Any]],
    goal: dict[str, Any] | None = None,
    resting_hr: float = 60.0,
    max_hr: float = 190.0,
    days: int = 42,
    now: datetime | None = None,
) -> FitnessProfile:
    """Build a comprehensive fitness profile by running all ML models.

    This is the main orchestrator. It:
    1. Estimates VDOT from quality runs
    2. Computes training load (CTL/ATL/TSB)
    3. Analyzes pace trends
    4. Scores readiness
    5. Predicts race readiness (if a goal is set)

    Args:
        activities: All running activities from the database.
        health_metrics: Health metrics (VO2max samples, etc.).
        goal: Current racing goal, or None.
        resting_hr: Athlete's resting HR (default 60).
        max_hr: Athlete's max HR (default 190).
        days: Analysis window in days.
        now: Reference timestamp.

    Returns:
        FitnessProfile with all ML outputs.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # Filter to running activities only
    running_activities = [
        a for a in activities
        if str(a.get("type") or "").lower() == "running"
    ]

    # --- Run all ML models ---

    # 1. VDOT estimation
    vdot_result: VdotEstimate = estimate_vdot(activities, days=days, now=now)

    # 2. Training load
    load_result: TrainingLoadSnapshot = compute_training_load(
        activities, resting_hr=resting_hr, max_hr=max_hr, days=90, now=now
    )

    # 3. Pace trend
    trend_result: PaceTrend = analyze_pace_trend(activities, window_days=days, now=now)

    # 4. Readiness
    readiness_result: ReadinessResult = compute_readiness(
        tsb_form=load_result.tsb_form,
        activities=activities,
        now=now,
    )

    # 5. Race prediction (only if a goal exists)
    race_result: RacePrediction | None = None
    if goal:
        race_result = predict_race_readiness(
            current_vdot=vdot_result.estimated_vdot,
            goal_type=goal.get("goal_type", "5k"),
            target_time_seconds=goal.get("target_time_seconds"),
            race_date=goal.get("race_date"),
            trend_direction=trend_result.direction,
            trend_rate=trend_result.rate_sec_per_km_per_week,
            ctl_fitness=load_result.ctl_fitness,
            runs_in_period=len(running_activities),
            now=now,
        )

    # --- Data quality assessment ---
    total_runs = len(running_activities)
    runs_with_hr = sum(
        1 for a in running_activities
        if isinstance(a.get("average_heartrate"), (int, float)) and float(a.get("average_heartrate")) > 0
    )
    hr_coverage = runs_with_hr / total_runs if total_runs > 0 else 0.0

    data_quality = {
        "total_runs_in_window": total_runs,
        "runs_with_heart_rate": runs_with_hr,
        "heart_rate_coverage_pct": round(hr_coverage * 100, 1),
        "vo2max_samples": len(health_metrics),
        "has_sufficient_data": total_runs >= 5,
        "recommendations": [],
    }

    if total_runs < 5:
        data_quality["recommendations"].append(
            "Import more runs (at least 5) for reliable fitness estimation."
        )
    if hr_coverage < 0.5:
        data_quality["recommendations"].append(
            "Heart rate data improves accuracy. Ensure your watch records HR during runs."
        )
    if total_runs >= 5 and hr_coverage >= 0.5:
        data_quality["recommendations"].append(
            "Good data quality. Keep syncing runs for increasingly accurate assessments."
        )

    # Overall confidence
    if total_runs >= 10 and hr_coverage >= 0.6:
        overall_confidence = "high"
    elif total_runs >= 5:
        overall_confidence = "moderate"
    else:
        overall_confidence = "low"

    # --- Runner summary ---
    runner_summary = {
        "total_runs": total_runs,
        "estimated_vdot": vdot_result.estimated_vdot,
        "fitness_status": load_result.status,
        "readiness_score": readiness_result.score,
        "readiness_label": readiness_result.label,
        "pace_trend": trend_result.direction,
        "recommendation": readiness_result.recommendation,
    }

    # --- Serialize all results ---
    vdot_dict = {
        "estimated_vdot": vdot_result.estimated_vdot,
        "sample_count": vdot_result.sample_count,
        "confidence": vdot_result.confidence,
        "race_predictions": vdot_result.race_predictions,
        "pace_zones": vdot_result.pace_zones,
        "trend": vdot_result.trend,
        "samples": [
            {
                "vdot": s.vdot,
                "date": s.date.isoformat(),
                "distance_km": round(s.distance_m / 1000, 2),
                "pace_per_km_formatted": f"{int(s.pace_per_km // 60)}:{int(s.pace_per_km % 60):02d} /km",
                "confidence": round(s.confidence, 2),
                "source": s.source,
            }
            for s in vdot_result.samples[:15]  # Limit for API response size
        ],
    }

    load_dict = {
        "ctl_fitness": load_result.ctl_fitness,
        "atl_fatigue": load_result.atl_fatigue,
        "tsb_form": load_result.tsb_form,
        "status": load_result.status,
        "monotony": load_result.monotony,
        "strain": load_result.strain,
        "total_trimp_7d": load_result.total_trimp_7d,
        "total_trimp_28d": load_result.total_trimp_28d,
        "daily_loads": load_result.daily_loads,  # For charting
    }

    trend_dict = {
        "direction": trend_result.direction,
        "rate_sec_per_km_per_week": trend_result.rate_sec_per_km_per_week,
        "r_squared": trend_result.r_squared,
        "confidence": trend_result.confidence,
        "data_points": trend_result.data_points,
        "window_days": trend_result.window_days,
        "easy_pace_trend": trend_result.easy_pace_trend,
        "quality_pace_trend": trend_result.quality_pace_trend,
        "pace_history": trend_result.pace_history,
    }

    readiness_dict = {
        "score": readiness_result.score,
        "label": readiness_result.label,
        "factors": readiness_result.factors,
        "recommendation": readiness_result.recommendation,
    }

    race_dict = None
    if race_result:
        race_dict = {
            "goal_name": race_result.goal_name,
            "goal_distance_km": race_result.goal_distance_km,
            "target_time": race_result.target_time,
            "predicted_time": race_result.predicted_time,
            "current_vdot": race_result.current_vdot,
            "required_vdot": race_result.required_vdot,
            "vdot_gap": race_result.vdot_gap,
            "weeks_remaining": race_result.weeks_remaining,
            "probability": race_result.probability,
            "probability_label": race_result.probability_label,
            "assessment": race_result.assessment,
            "factors": race_result.factors,
        }

    return FitnessProfile(
        generated_at=now.isoformat().replace("+00:00", "Z"),
        runner_summary=runner_summary,
        vdot=vdot_dict,
        training_load=load_dict,
        pace_trend=trend_dict,
        readiness=readiness_dict,
        race_prediction=race_dict,
        confidence=overall_confidence,
        data_quality=data_quality,
    )


def fitness_profile_to_dict(profile: FitnessProfile) -> dict[str, Any]:
    """Convert FitnessProfile to a plain dict for JSON serialization."""
    return asdict(profile)


def fitness_profile_for_llm(profile: FitnessProfile) -> dict[str, Any]:
    """Extract the subset of profile data needed for LLM plan generation.

    Strips out detailed time-series data (daily_loads, pace_history, samples)
    to keep the LLM prompt token-efficient while preserving all the metrics
    the LLM needs for coaching decisions.
    """
    d = asdict(profile)

    # Remove verbose charting data that the LLM doesn't need
    d["training_load"].pop("daily_loads", None)
    d["pace_trend"].pop("pace_history", None)
    d["vdot"].pop("samples", None)

    # Remove internal scoring factors
    if d.get("race_prediction"):
        d["race_prediction"].pop("factors", None)
    d["readiness"].pop("factors", None)

    return d
