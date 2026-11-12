"""Candidate algorithms, model selection, and the trained model that gets saved.

Promotion rule: the best candidate is used only if, in walk-forward testing, it cuts
the VDOT baseline's error by at least PROMOTION_GAIN. Otherwise the physiology wins
and the app says so - an honest baseline beats a confidently wrong model.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from coach.ml.evaluate import MIN_TRAIN, Regressor, WalkForward, band, walk_forward
from coach.ml.features import FEATURES, MONOTONIC, Example, as_arrays

MIN_TEST = 4
MIN_EXAMPLES = MIN_TRAIN + MIN_TEST
PROMOTION_GAIN = 0.05  # must cut the baseline's MAPE by at least 5%
EXTRAPOLATION_PER_DOUBLING = 0.01  # wider bands beyond the longest distance learned from


def _ridge() -> Regressor:
    # Strong shrinkage: with few efforts, corrections stay small (close to VDOT).
    return make_pipeline(StandardScaler(), Ridge(alpha=10.0))


def _gbm() -> Regressor:
    return HistGradientBoostingRegressor(
        learning_rate=0.05, max_iter=150, max_depth=3, min_samples_leaf=5,
        l2_regularization=1.0, early_stopping=False, random_state=0,
        monotonic_cst=[MONOTONIC.get(name, 0) for name in FEATURES])


CANDIDATES: dict[str, Callable[[], Regressor]] = {"ridge": _ridge, "gbm": _gbm}


@dataclass(frozen=True, slots=True)
class RaceTimeModel:
    """What gets saved: the fitted correction model plus its calibrated band."""

    algorithm: str
    features: tuple[str, ...]
    estimator: Regressor
    band: tuple[float, float]  # p10/p90 of out-of-sample log-errors
    max_distance_m: float  # longest effort it learned from

    def predict(self, baseline_s: float, row: Sequence[float],
                distance_m: float) -> tuple[float, float, float]:
        """(predicted, p10, p90) seconds for one race."""
        correction = float(self.estimator.predict(np.array([row], dtype=float))[0])
        predicted = baseline_s * math.exp(correction)
        widen = EXTRAPOLATION_PER_DOUBLING * max(0.0, math.log2(distance_m / self.max_distance_m))
        low, high = self.band
        return predicted, predicted * math.exp(low - widen), predicted * math.exp(high + widen)


@dataclass(frozen=True, slots=True)
class Selection:
    examples: int
    span: tuple[date, date] | None  # first and last effort day learned from
    best: WalkForward | None  # None: not enough efforts to test anything
    candidates: dict[str, float]  # algorithm -> walk-forward MAPE %
    model: RaceTimeModel | None  # set only when promoted

    @property
    def promoted(self) -> bool:
        return self.model is not None


def select(examples: Sequence[Example]) -> Selection:
    """Walk-forward every candidate, then fit the winner on everything if it earns it."""
    span = (examples[0].day, examples[-1].day) if examples else None
    if len(examples) < MIN_EXAMPLES:
        return Selection(len(examples), span, None, {}, None)
    results = [r for name, make in CANDIDATES.items()
               if (r := walk_forward(examples, make, name)) is not None and r.model.n >= MIN_TEST]
    if not results:
        return Selection(len(examples), span, None, {}, None)
    best = min(results, key=lambda r: r.model.mape_pct)
    scores = {r.algorithm: r.model.mape_pct for r in results}
    if best.model.mape_pct > best.baseline.mape_pct * (1 - PROMOTION_GAIN):
        return Selection(len(examples), span, best, scores, None)
    X, y = as_arrays(examples)  # noqa: N806
    model = RaceTimeModel(
        algorithm=best.algorithm, features=FEATURES,
        estimator=CANDIDATES[best.algorithm]().fit(X, y),
        band=band(best.errors), max_distance_m=max(e.distance_m for e in examples))
    return Selection(len(examples), span, best, scores, model)
