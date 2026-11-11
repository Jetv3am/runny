"""ORM tables. Units: metres, seconds, kcal, °C. All datetimes are stored as naive UTC."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UTCDateTime(TypeDecorator[datetime]):
    """Stores naive UTC, returns aware UTC. SQLite has no timezone support, so the
    conversion happens here once instead of being remembered at every call site."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Refusing to store a naive datetime; pass an aware one")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


class Base(DeclarativeBase):
    pass


class ImportRow(Base):
    __tablename__ = "imports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # processing | completed | failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class WorkoutRow(Base):
    """A running workout as recorded by Apple Health. Type/title/TRIMP are *derived*
    at read time (they depend on the athlete profile), so they are not stored."""

    __tablename__ = "workouts"
    __table_args__ = (Index("ix_workouts_start_at", "start_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # stable hash of source fields
    import_id: Mapped[str | None] = mapped_column(
        ForeignKey("imports.id", ondelete="SET NULL"), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # Original UTC offset: a 7pm run in California is "tomorrow" in UTC.
    utc_offset_min: Mapped[int] = mapped_column(Integer, default=0)
    distance_m: Mapped[float] = mapped_column(Float)
    duration_s: Mapped[float] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_cadence: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    indoor: Mapped[bool] = mapped_column(default=False)


class HealthMetricRow(Base):
    """One value per metric per (local) day; the latest reading of the day wins."""

    __tablename__ = "health_metrics"
    __table_args__ = (UniqueConstraint("type", "day", name="uq_health_metrics_type_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32))  # vo2max | resting_hr
    day: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    measured_at: Mapped[datetime] = mapped_column(UTCDateTime)
