"""FastAPI application factory. Run: uv run uvicorn coach.main:app --reload --port 8100"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from coach import __version__, config
from coach.api import analytics, interactive, models
from coach.services import imports
from coach.storage import database

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    database.migrate()
    imports.recover_interrupted()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Running Coach API", version=__version__, lifespan=lifespan)
    # Most traffic arrives same-origin via the Next.js proxy; large uploads come direct.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(analytics.router, prefix=API_PREFIX)
    app.include_router(interactive.router, prefix=API_PREFIX)
    app.include_router(models.router, prefix=API_PREFIX)
    return app


app = create_app()
