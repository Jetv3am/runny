"""Model registry: every training run is recorded; the active model's file is verified.

Model files are pickles (joblib), and unpickling runs code. So the registry records
each file's SHA-256 when it writes it and refuses to load a file that doesn't match.
Only files this app wrote itself are ever loaded.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import joblib
from sqlalchemy import select, update

from coach import config
from coach.ml.features import FEATURES
from coach.ml.race_model import RaceTimeModel, Selection
from coach.storage.database import session_scope
from coach.storage.tables import ModelVersionRow

log = logging.getLogger(__name__)

RACE_TIME = "race_time"


@dataclass(frozen=True, slots=True)
class Version:
    id: str
    status: str  # active | retired | rejected | insufficient_data
    trained_at: datetime
    examples: int
    algorithm: str | None
    metrics: dict | None


def record(selection: Selection, task: str = RACE_TIME) -> Version:
    """Store a training run. The new run replaces whatever was active: fresh evidence
    wins, even when it says the baseline is better."""
    version_id = uuid.uuid4().hex
    artifact = digest = None
    if selection.model is not None:
        artifact = f"{task}-{version_id}.joblib"
        joblib.dump(selection.model, config.models_dir() / artifact)
        digest = _sha256(config.models_dir() / artifact)
    status = ("active" if selection.promoted
              else "rejected" if selection.best else "insufficient_data")
    row = ModelVersionRow(id=version_id, task=task, status=status,
                          trained_at=datetime.now(UTC), examples=selection.examples,
                          algorithm=selection.best.algorithm if selection.best else None,
                          metrics=_metrics(selection), artifact=artifact,
                          artifact_sha256=digest)
    with session_scope() as session:
        is_active = (ModelVersionRow.task == task) & (ModelVersionRow.status == "active")
        retired_files = [a for a in session.scalars(select(ModelVersionRow.artifact)
                                                   .where(is_active)) if a]
        session.execute(update(ModelVersionRow).where(is_active)
                        .values(status="retired", artifact=None, artifact_sha256=None))
        session.add(row)
    for name in retired_files:  # only after the commit: never orphan an active row
        (config.models_dir() / name).unlink(missing_ok=True)
    return _to_version(row)


def latest(task: str = RACE_TIME) -> Version | None:
    with session_scope() as session:
        row = session.scalars(select(ModelVersionRow).where(ModelVersionRow.task == task)
                              .order_by(ModelVersionRow.trained_at.desc()).limit(1)).first()
        return _to_version(row) if row else None


def load_active(task: str = RACE_TIME) -> tuple[Version, RaceTimeModel] | None:
    """The active model, or None (never trained, not promoted, or its file is bad)."""
    with session_scope() as session:
        row = session.scalars(select(ModelVersionRow).where(
            ModelVersionRow.task == task, ModelVersionRow.status == "active")).first()
        if row is None or not row.artifact or not row.artifact_sha256:
            return None
        version, artifact, digest = _to_version(row), row.artifact, row.artifact_sha256
    try:
        return version, _load(str(config.models_dir() / artifact), digest)
    except (OSError, ValueError) as exc:
        log.warning("Not using model %s: %s", version.id, exc)
        return None


@lru_cache(maxsize=4)
def _load(path: str, expected_sha256: str) -> RaceTimeModel:
    if _sha256(Path(path)) != expected_sha256:
        raise ValueError("model file doesn't match its recorded checksum")
    model = joblib.load(path)
    if not isinstance(model, RaceTimeModel) or model.features != FEATURES:
        raise ValueError("model file is from an incompatible version; retrain")
    return model


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metrics(selection: Selection) -> dict | None:
    best = selection.best
    if best is None:
        return None
    first, last = selection.span or (None, None)
    return {"model": asdict(best.model), "baseline": asdict(best.baseline),
            "coverage_pct": best.coverage_pct, "candidates": selection.candidates,
            "features": list(FEATURES),
            "data_from": first.isoformat() if first else None,
            "data_to": last.isoformat() if last else None}


def _to_version(row: ModelVersionRow) -> Version:
    return Version(id=row.id, status=row.status, trained_at=row.trained_at,
                   examples=row.examples, algorithm=row.algorithm, metrics=row.metrics)
