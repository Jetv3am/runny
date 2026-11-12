"""Walk-forward evaluation: always train on the past and test on the future.

Random K-fold would let the model learn from races *after* the one it predicts, which
can't happen in real life and makes scores look better than they are.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, Self

import numpy as np

from coach.ml.features import Example, as_arrays

MIN_TRAIN = 8  # efforts needed before the first test
MAX_FOLDS = 25  # refit at most this many times (keeps training fast on long histories)
MIN_CALIBRATION = 5  # past errors needed before a band can be built (or judged)
BAND_QUANTILES = (0.10, 0.90)
MIN_BAND = 0.01  # never claim better than +/-1%: false precision


class Regressor(Protocol):
    """The slice of the scikit-learn estimator API used here."""

    def fit(self, X: np.ndarray, y: np.ndarray) -> Self: ...  # noqa: N803 - sklearn naming
    def predict(self, X: np.ndarray) -> np.ndarray: ...  # noqa: N803


@dataclass(frozen=True, slots=True)
class Metrics:
    mape_pct: float  # mean absolute percentage error of the predicted time
    mae_s: float
    n: int


@dataclass(frozen=True, slots=True)
class WalkForward:
    algorithm: str
    model: Metrics
    baseline: Metrics  # VDOT alone, on exactly the same test efforts
    errors: np.ndarray  # out-of-sample log(actual / predicted), oldest first
    coverage_pct: float | None  # share of actual times inside the p10-p90 band


def band(errors: np.ndarray) -> tuple[float, float]:
    """p10/p90 of past log-errors (split-conformal), at least +/-MIN_BAND wide."""
    low, high = np.quantile(errors, BAND_QUANTILES)
    return min(float(low), -MIN_BAND), max(float(high), MIN_BAND)


def walk_forward_blocks(days: np.ndarray) -> list[np.ndarray]:
    """Boolean masks of test efforts. Same-day efforts (e.g. the 5K and 10K inside one
    run) always land in the same block, so a day is never half-train, half-test."""
    unique = np.unique(days)
    seen = np.searchsorted(np.sort(days), unique)  # efforts strictly before each day
    candidates = unique[seen >= MIN_TRAIN]
    if not candidates.size:
        return []
    return [np.isin(days, chunk)
            for chunk in np.array_split(candidates, min(MAX_FOLDS, candidates.size))]


def walk_forward(examples: Sequence[Example], make: Callable[[], Regressor],
                 algorithm: str) -> WalkForward | None:
    """Score one algorithm; None if there's not enough history to test anything."""
    X, y = as_arrays(examples)  # noqa: N806
    days = np.array([e.day.toordinal() for e in examples])
    actual = np.array([e.actual_s for e in examples])
    baseline = np.array([e.baseline_s for e in examples])
    blocks = walk_forward_blocks(days)
    if not blocks:
        return None

    correction = np.full(len(examples), np.nan)
    covered: list[bool] = []
    for test in blocks:
        train = days < days[test].min()
        correction[test] = make().fit(X[train], y[train]).predict(X[test])
        # Judge the band using only errors from earlier blocks, as it would be built live.
        past = _errors(actual, baseline, correction, days < days[test].min())
        if past.size >= MIN_CALIBRATION:
            low, high = band(past)
            now = np.log(actual[test] / (baseline[test] * np.exp(correction[test])))
            covered.extend((low <= now) & (now <= high))

    tested = ~np.isnan(correction)
    predicted = baseline * np.exp(np.where(tested, correction, 0.0))
    return WalkForward(
        algorithm=algorithm,
        model=_metrics(actual[tested], predicted[tested]),
        baseline=_metrics(actual[tested], baseline[tested]),
        errors=_errors(actual, baseline, correction, tested),
        coverage_pct=round(100 * float(np.mean(covered)), 1) if covered else None)


def _errors(actual: np.ndarray, baseline: np.ndarray, correction: np.ndarray,
            mask: np.ndarray) -> np.ndarray:
    keep = mask & ~np.isnan(correction)
    return np.log(actual[keep] / (baseline[keep] * np.exp(correction[keep])))


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> Metrics:
    gap = np.abs(predicted - actual)
    return Metrics(mape_pct=round(100 * float(np.mean(gap / actual)), 2),
                   mae_s=round(float(np.mean(gap)), 1), n=int(actual.size))
