"""Apple Health import jobs.

1. `receive_upload` streams the upload to disk and records an import (status: processing).
2. `run_import` (background thread) reads it in two passes - runs and daily metrics, then
   the samples inside each run - and stores everything in ONE transaction, so the
   dashboard never shows a half-imported export.
3. The raw upload is deleted afterwards; only the extracted data is kept.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePath

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert

from coach import config
from coach.domain.streams import Stream
from coach.ingestion.apple_export import ParsedMetric, ParsedWorkout, parse_export
from coach.ingestion.cleaning import drop_duplicate_recordings
from coach.ingestion.export_reader import ExportError, ProgressFn
from coach.ingestion.samples import collect_streams
from coach.schemas import ImportRecord
from coach.services import models, repository
from coach.storage import stream_codec
from coach.storage.database import session_scope
from coach.storage.tables import HealthMetricRow, ImportRow, WorkoutRow, WorkoutStreamRow

log = logging.getLogger(__name__)

ALLOWED_SUFFIXES = frozenset({".zip", ".xml"})
MAX_UPLOAD_BYTES = 4 * 1024**3  # 4 GiB
# Progress bar spans (percent) for the two passes; storing + training take the last 5%.
WORKOUT_PASS = (0.0, 45.0)
SAMPLE_PASS = (45.0, 95.0)
TRAINING_PROGRESS = 97.0  # storing, then the (seconds-long) model training
PROGRESS_EVERY_S = 1.0
HISTORY_LIMIT = 20


class UploadRejected(ValueError):
    """Raised when an upload fails validation."""


def _upload_path(import_id: str) -> Path:
    # No original suffix needed: the parser sniffs ZIP vs XML from the content.
    return config.uploads_dir() / f"{import_id}.upload"


def _now() -> datetime:
    return datetime.now(UTC)


# ---------- Intake ----------------------------------------------------------------

async def receive_upload(filename: str, chunks: AsyncIterator[bytes]) -> ImportRecord:
    if PurePath(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise UploadRejected("Upload an Apple Health export.zip or export.xml file.")
    import_id = uuid.uuid4().hex[:12]
    path = _upload_path(import_id)
    size = 0
    try:
        with path.open("wb") as out:
            async for chunk in chunks:
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise UploadRejected("File exceeds the 4 GB limit.")
                out.write(chunk)
        if size == 0:
            raise UploadRejected("The uploaded file is empty.")
    except BaseException:
        path.unlink(missing_ok=True)
        raise

    row = ImportRow(id=import_id, filename=PurePath(filename).name[:255], size_bytes=size,
                    status="processing", progress=0.0, message="Queued for processing.",
                    created_at=_now())
    with session_scope() as session:
        session.add(row)
    return _to_record(row)


# ---------- Background job --------------------------------------------------------

class _ProgressReporter:
    """Writes progress to the import row, at most once per PROGRESS_EVERY_S."""

    def __init__(self, import_id: str):
        self._import_id = import_id
        self._last_write = 0.0

    def stage(self, span: tuple[float, float], message: str) -> ProgressFn:
        """Callback mapping one pass's 0..1 progress onto `span` (percent) of the bar."""
        start, end = span

        def report(fraction: float) -> None:
            now = time.monotonic()
            if now - self._last_write < PROGRESS_EVERY_S:
                return
            self._last_write = now
            _update(self._import_id, progress=round(start + fraction * (end - start), 1),
                    message=message)
        return report


def run_import(import_id: str) -> None:
    """Parse and store one upload. Runs in a worker thread; never raises."""
    path = _upload_path(import_id)
    progress = _ProgressReporter(import_id)
    try:
        result = parse_export(path, progress.stage(WORKOUT_PASS, "Reading your runs…"))
        workouts = drop_duplicate_recordings(result.workouts)
        streams = collect_streams(path, workouts,
                                  progress.stage(SAMPLE_PASS, "Reading splits and heart rate…"))
        new_runs = _store(import_id, workouts, result.metrics, streams)
        repository.invalidate()
        _update(import_id, progress=TRAINING_PROGRESS, message="Training your prediction model…")
        models.train_after_import()
        _finish(import_id, "completed", _summary(
            runs=len(workouts), new_runs=new_runs, with_splits=len(streams),
            metrics=len(result.metrics), duplicates=len(result.workouts) - len(workouts)))
        log.info("Import %s done: %s, %d streams", import_id, result.stats, len(streams))
    except ExportError as exc:
        _finish(import_id, "failed", str(exc))
    except Exception:
        log.exception("Import %s crashed", import_id)
        _finish(import_id, "failed", "Something went wrong while importing. "
                                     "The API log has the details.")
    finally:
        path.unlink(missing_ok=True)


def _store(import_id: str, workouts: Sequence[ParsedWorkout],
           metrics: Sequence[ParsedMetric], streams: Mapping[str, Stream]) -> int:
    """Upsert everything in a single transaction. Returns how many runs are new.
    Re-importing the same export is a no-op thanks to stable workout ids."""
    with session_scope() as session:
        existing = set(session.scalars(select(WorkoutRow.id)))
        if workouts:
            stmt = insert(WorkoutRow)
            columns = [c.name for c in WorkoutRow.__table__.columns if c.name != "id"]
            session.execute(
                stmt.on_conflict_do_update(index_elements=["id"],
                                           set_={c: stmt.excluded[c] for c in columns}),
                [_workout_values(import_id, w) for w in workouts])
        if streams:
            stmt = insert(WorkoutStreamRow)
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["workout_id"],
                    set_={c: stmt.excluded[c] for c in ("sample_count", "data")}),
                [{"workout_id": workout_id, "data": stream_codec.encode(stream),
                  "sample_count": stream.t_s.size + stream.hr_t_s.size}
                 for workout_id, stream in streams.items()])
        if metrics:
            stmt = insert(HealthMetricRow)
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["type", "day"],
                    set_={c: stmt.excluded[c] for c in ("value", "unit", "measured_at")}),
                [{"type": m.type, "day": m.day, "value": m.value, "unit": m.unit,
                  "measured_at": m.measured_at} for m in metrics])
    return sum(1 for w in workouts if w.id not in existing)


def _workout_values(import_id: str, w: ParsedWorkout) -> dict[str, object]:
    offset = w.start_at.utcoffset()
    return {
        "id": w.id, "import_id": import_id, "source_name": w.source_name,
        "start_at": w.start_at, "end_at": w.end_at,
        "utc_offset_min": int(offset.total_seconds() // 60) if offset else 0,
        "distance_m": w.distance_m, "duration_s": w.duration_s,
        "avg_hr": w.avg_hr, "max_hr": w.max_hr, "energy_kcal": w.energy_kcal,
        "elevation_gain_m": w.elevation_gain_m, "avg_cadence": w.avg_cadence,
        "temperature_c": w.temperature_c, "indoor": w.indoor,
    }


def _summary(*, runs: int, new_runs: int, with_splits: int, metrics: int,
             duplicates: int) -> str:
    if runs == 0:
        return "No running workouts found in this export."
    parts = [f"Imported {runs:,} runs ({new_runs:,} new) and {metrics:,} daily health readings.",
             f"{with_splits:,} runs have splits."]
    if duplicates:
        parts.append(f"Merged {duplicates:,} duplicate recordings from other apps.")
    return " ".join(parts)


def _update(import_id: str, **values: object) -> None:
    with session_scope() as session:
        session.execute(update(ImportRow).where(ImportRow.id == import_id).values(**values))


def _finish(import_id: str, status: str, message: str) -> None:
    extra = {"progress": 100.0} if status == "completed" else {}
    _update(import_id, status=status, message=message, finished_at=_now(), **extra)


# ---------- Queries & housekeeping ------------------------------------------------

def list_imports() -> list[ImportRecord]:
    with session_scope() as session:
        rows = session.scalars(
            select(ImportRow).order_by(ImportRow.created_at.desc()).limit(HISTORY_LIMIT))
        return [_to_record(row) for row in rows]


def recover_interrupted() -> None:
    """At startup: a 'processing' import can't still be running (jobs live in-process),
    e.g. `--reload` restarted the server mid-import. Fail it loudly and clean up."""
    with session_scope() as session:
        session.execute(
            update(ImportRow).where(ImportRow.status == "processing")
            .values(status="failed", finished_at=_now(),
                    message="Interrupted: the server restarted during the import. "
                            "Please upload the file again."))
    for leftover in config.uploads_dir().glob("*.upload"):
        leftover.unlink(missing_ok=True)


def _to_record(row: ImportRow) -> ImportRecord:
    return ImportRecord(id=row.id, filename=row.filename, size_bytes=row.size_bytes,
                        status=row.status, progress=row.progress, message=row.message,
                        created_at=row.created_at)
