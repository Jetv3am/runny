"""ML model endpoints: the model card, and manual retraining."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from coach.schemas import ModelCard
from coach.services import models

router = APIRouter(tags=["models"])


@router.get("/models/race-time", response_model=ModelCard)
def race_time_model() -> ModelCard:
    """Whether predictions use the personal ML model, and how it scored vs VDOT."""
    return models.card()


@router.post("/models/race-time/train", response_model=ModelCard)
def train_race_time_model() -> ModelCard:
    """Retrain now (also happens automatically after each import). Takes seconds."""
    try:
        return models.train()
    except models.NotTrainable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
