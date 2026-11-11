"""Shared fixtures: every test gets its own throwaway database and data directory."""

from __future__ import annotations

import pytest

from coach.services import repository
from coach.storage import database


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("COACH_DATABASE_URL", raising=False)
    database.reset()
    repository.invalidate()
    database.migrate()
    yield tmp_path
    database.reset()
    repository.invalidate()
