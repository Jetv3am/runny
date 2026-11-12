"""Race-time model orchestration: train from the repository, explain, and predict.

Training runs automatically after each import, from the Retrain button, or from the
CLI (`uv run python -m coach.ml train`). The app uses the model only while it is
active, i.e. it beat the VDOT baseline on efforts it had never seen.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date, timedelta

from coach.domain.fitness import Performance, race_quality_performances
from coach.domain.history import DailyHistory, daily_history
from coach.ml import registry
from coach.ml.features import Baseline, Example, baseline_before, build_examples, feature_row
from coach.ml.race_model import MIN_EXAMPLES, RaceTimeModel, select
from coach.schemas import ModelCard, ModelScore
from coach.services import repository

log = logging.getLogger(__name__)

ALGORITHM_NAMES = {"ridge": "linear (ridge)", "gbm": "gradient-boosted trees"}
_STATUS = {"active": "active", "rejected": "baseline_better",
           "insufficient_data": "collecting_data"}
_train_lock = threading.Lock()  # an import and a Retrain click must not race


class NotTrainable(RuntimeError):
    """Training isn't possible right now (e.g. only demo data)."""


def _inputs() -> tuple[list[Performance], DailyHistory | None]:
    workouts = repository.get_workouts()
    performances = race_quality_performances(
        workouts, repository.get_best_efforts(), repository.get_profile())
    return performances, daily_history(workouts, repository.today())


def examples() -> list[Example]:
    performances, history = _inputs()
    return build_examples(performances, history) if history else []


def train() -> ModelCard:
    if repository.data_source() == "demo":
        raise NotTrainable("The model trains on your own runs. Import an Apple Health "
                           "export first.")
    with _train_lock:
        version = registry.record(select(examples()))
    log.info("Race-time model %s: %s on %d efforts", version.id, version.status,
             version.examples)
    return card()


def train_after_import() -> None:
    """Best effort: a training failure must never fail the import itself."""
    try:
        train()
    except Exception:
        log.exception("Training after import failed; predictions stay on VDOT")


def card() -> ModelCard:
    if repository.data_source() == "demo":
        return ModelCard(status="demo", efforts=0, efforts_needed=MIN_EXAMPLES)
    efforts = len(examples())
    latest = registry.latest()
    if latest is None or latest.status not in _STATUS:
        return ModelCard(status="not_trained", efforts=efforts, efforts_needed=MIN_EXAMPLES)
    metrics = latest.metrics or {}
    return ModelCard(
        status=_STATUS[latest.status], efforts=efforts, efforts_needed=MIN_EXAMPLES,
        version=latest.id, algorithm=latest.algorithm, trained_at=latest.trained_at,
        test_efforts=metrics.get("model", {}).get("n"),
        ml=_score(metrics.get("model")), baseline=_score(metrics.get("baseline")),
        band_coverage_pct=metrics.get("coverage_pct"),
        data_from=metrics.get("data_from"), data_to=metrics.get("data_to"))


def _score(raw: dict | None) -> ModelScore | None:
    return ModelScore(mape_pct=raw["mape_pct"], mae_s=raw["mae_s"]) if raw else None


@dataclass(frozen=True, slots=True)
class Predictor:
    """The active model plus today's inputs, built exactly as during training."""

    version: registry.Version
    model: RaceTimeModel
    history: DailyHistory
    baseline: Baseline
    day: date  # predictions are for a race tomorrow: all of today's data counts

    def predict(self, distance_m: float) -> tuple[float, float, float]:
        row = feature_row(self.history, self.day, distance_m, True, self.baseline)
        return self.model.predict(self.baseline.time_s(distance_m), row, distance_m)

    def describe(self) -> str:
        metrics = self.version.metrics or {}
        ml, base = metrics.get("model", {}), metrics.get("baseline", {})
        name = ALGORITHM_NAMES.get(self.model.algorithm, self.model.algorithm)
        return (f"Your VDOT baseline, corrected by a personal {name} model trained on "
                f"{self.version.examples} of your race-quality efforts. Tested on efforts "
                f"it hadn't seen, it was off by {ml.get('mape_pct')}% on average, vs "
                f"{base.get('mape_pct')}% for VDOT alone.")


def active_predictor() -> Predictor | None:
    if repository.data_source() == "demo" or (loaded := registry.load_active()) is None:
        return None
    performances, history = _inputs()
    day = repository.today() + timedelta(days=1)
    if history is None or (baseline := baseline_before(performances, day)) is None:
        return None  # e.g. no qualifying effort in the lookback window any more
    version, model = loaded
    return Predictor(version, model, history, baseline, day)
