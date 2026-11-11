"""Race-time predictions. Currently the VDOT physiology baseline; ML arrives in Phase 3."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from coach.domain.vdot import race_time_for_vdot
from coach.schemas import RacePrediction, RacePredictions
from coach.services.fitness import current_vdot

STANDARD_RACES: tuple[tuple[str, str, float], ...] = (
    ("5k", "5K", 5_000),
    ("10k", "10K", 10_000),
    ("half", "Half marathon", 21_097.5),
    ("marathon", "Marathon", 42_195),
)


def _uncertainty(distance_m: float) -> float:
    """Relative band width: 2% at 5K, +1% per doubling (extrapolation is less certain)."""
    return 0.02 + 0.01 * max(0.0, math.log2(distance_m / 5_000))


def predict(distance_m: float, vdot: float) -> tuple[float, float, float]:
    """(predicted, p10, p90) seconds."""
    predicted = race_time_for_vdot(vdot, distance_m)
    band = _uncertainty(distance_m)
    return predicted, predicted * (1 - band), predicted * (1 + band)


def race_predictions() -> RacePredictions | None:
    vdot = current_vdot()
    if vdot is None:
        return None
    predictions = []
    for key, label, distance in STANDARD_RACES:
        predicted, p10, p90 = predict(distance, vdot)
        predictions.append(RacePrediction(
            key=key, label=label, distance_m=distance,
            predicted_s=round(predicted), p10_s=round(p10), p90_s=round(p90),
            pace_s_per_km=round(predicted / (distance / 1000), 1),
        ))
    return RacePredictions(
        source="vdot_baseline",
        vdot=round(vdot, 1),
        based_on="Daniels VDOT from your race efforts in the last 120 days (recency-weighted)",
        generated_at=datetime.now(UTC),
        predictions=predictions,
    )
