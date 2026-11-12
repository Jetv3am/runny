"""Race-time predictions: the active personal ML model, else the VDOT baseline.

Every prediction in the app (Predictions page, goal race, coach) goes through
`_predict`, so they can never disagree about which model is in charge.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from coach.domain.distances import RACES
from coach.domain.vdot import race_time_for_vdot
from coach.schemas import RacePrediction, RacePredictions
from coach.services import models
from coach.services.fitness import current_vdot

BASELINE_BASIS = ("Daniels VDOT from your races and race-effort training runs (heart rate "
                  "at race level) in the last 120 days, recency-weighted")


def _baseline_band(distance_m: float) -> float:
    """Relative band width: 2% at 5K, +1% per doubling (extrapolation is less certain)."""
    return 0.02 + 0.01 * max(0.0, math.log2(distance_m / 5_000))


def _predict(distance_m: float, vdot: float,
             predictor: models.Predictor | None) -> tuple[float, float, float]:
    """(predicted, p10, p90) seconds."""
    if predictor is not None:
        return predictor.predict(distance_m)
    predicted = race_time_for_vdot(vdot, distance_m)
    band = _baseline_band(distance_m)
    return predicted, predicted * (1 - band), predicted * (1 + band)


def predicted_time_s(distance_m: float) -> float | None:
    """Best available prediction for one distance (used for the goal race)."""
    vdot = current_vdot()
    return _predict(distance_m, vdot, models.active_predictor())[0] if vdot else None


def race_predictions() -> RacePredictions | None:
    vdot = current_vdot()
    if vdot is None:
        return None
    predictor = models.active_predictor()
    predictions = []
    for race in RACES:
        predicted, p10, p90 = _predict(race.metres, vdot, predictor)
        predictions.append(RacePrediction(
            key=race.key, label=race.label, distance_m=race.metres,
            predicted_s=round(predicted), p10_s=round(p10), p90_s=round(p90),
            pace_s_per_km=round(predicted / (race.metres / 1000), 1),
        ))
    return RacePredictions(
        source="ml" if predictor else "vdot_baseline",
        vdot=round(vdot, 1),
        based_on=predictor.describe() if predictor else BASELINE_BASIS,
        model_version=predictor.version.id if predictor else None,
        generated_at=datetime.now(UTC),
        predictions=predictions,
    )
