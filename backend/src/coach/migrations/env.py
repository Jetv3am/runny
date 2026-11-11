"""Alembic environment. Used by `migrate()` at startup and by the CLI (backend/alembic.ini)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection, create_engine

from coach import config as app_config
from coach.storage.tables import Base, UTCDateTime

# Deliberately no logging.config.fileConfig(): at startup it would reconfigure (and by
# default silence) uvicorn's loggers.
target_metadata = Base.metadata


def _render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Write app-specific types as plain SQLAlchemy types, so migration files never
    import application code (which keeps changing after the migration is written)."""
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime()"
    return False


def _configure(**kwargs: object) -> None:
    context.configure(target_metadata=target_metadata, render_as_batch=True,  # SQLite ALTERs
                      render_item=_render_item, **kwargs)


def _run(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


def _url() -> str:
    return context.config.get_main_option("sqlalchemy.url") or app_config.database_url()


if context.is_offline_mode():
    _configure(url=_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif (shared := context.config.attributes.get("connection")) is not None:
    _run(shared)  # programmatic: reuse the app's connection
else:
    with create_engine(_url()).connect() as connection:
        _run(connection)
        connection.commit()
