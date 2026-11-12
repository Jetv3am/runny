"""Runtime settings from environment variables (no extra dependency needed yet)."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
# backend/data - gitignored. Holds the SQLite database and transient uploads.
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def cors_origins() -> list[str]:
    """Browser origins allowed to call the API directly (only uploads need this today)."""
    raw = os.environ.get("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def data_dir() -> Path:
    """Root for local state. Override with COACH_DATA_DIR (tests use a temp dir)."""
    path = Path(os.environ.get("COACH_DATA_DIR", DEFAULT_DATA_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def uploads_dir() -> Path:
    """Uploads live here only while being parsed, then are deleted."""
    path = data_dir() / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    """Trained model files (personal: derived from your health data)."""
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_url() -> str:
    return os.environ.get("COACH_DATABASE_URL", f"sqlite:///{data_dir() / 'coach.db'}")


def athlete_name() -> str:
    """Apple Health exports don't include a name; used for the dashboard greeting."""
    return os.environ.get("COACH_ATHLETE_NAME", "Runner")
