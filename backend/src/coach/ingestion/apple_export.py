"""Streaming parser for Apple Health exports (Apple's export.zip, or a bare export.xml).

Keeps only what the app uses: running workouts, plus one value per day of the health
metrics in `_METRICS`. Memory stays flat even for multi-GB exports, because each
top-level element is discarded as soon as it has been read.
"""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import IO, Literal
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import iterparse

MIN_RUN_DISTANCE_M = 800  # shorter = accidental start or GPS noise
# Zip-bomb guard, counted on *decompressed* bytes (a ZIP's declared sizes can lie).
# Heavy multi-year exports reach ~5 GB of XML.
MAX_XML_BYTES = 12 * 1024**3
_APPLE_DATE = "%Y-%m-%d %H:%M:%S %z"
_ZIP_SIGNATURE = b"PK\x03\x04"

MetricType = Literal["vo2max", "resting_hr"]
_METRICS: dict[str, tuple[MetricType, str]] = {
    "HKQuantityTypeIdentifierVO2Max": ("vo2max", "ml/kg/min"),
    "HKQuantityTypeIdentifierRestingHeartRate": ("resting_hr", "bpm"),
}

_LENGTH_M = {"m": 1.0, "km": 1000.0, "cm": 0.01, "mi": 1609.344, "ft": 0.3048, "yd": 0.9144}
_DURATION_S = {"s": 1.0, "sec": 1.0, "min": 60.0, "h": 3600.0, "hr": 3600.0}
# HealthKit: "Cal" (capital C) is a kilocalorie; "cal" is a calorie.
_ENERGY_KCAL = {"kcal": 1.0, "Cal": 1.0, "cal": 0.001, "kJ": 1 / 4.184, "J": 1 / 4184}


class ExportError(ValueError):
    """The file can't be imported. The message is shown to the user as-is."""


@dataclass(frozen=True, slots=True)
class ParsedWorkout:
    id: str  # stable across re-imports of the same export
    source_name: str | None
    start_at: datetime  # aware, in the timezone it was recorded in
    end_at: datetime
    distance_m: float
    duration_s: float
    avg_hr: float | None
    max_hr: float | None
    energy_kcal: float | None
    elevation_gain_m: float | None
    avg_cadence: float | None
    temperature_c: float | None
    indoor: bool


@dataclass(frozen=True, slots=True)
class ParsedMetric:
    type: MetricType
    day: date  # local calendar day of the reading
    value: float
    unit: str
    measured_at: datetime


@dataclass(slots=True)
class ParseStats:
    workouts_seen: int = 0
    runs_kept: int = 0
    skipped_not_running: int = 0
    skipped_unusable: int = 0  # too short, or missing dates/distance
    records_seen: int = 0


@dataclass(slots=True)
class ParseResult:
    workouts: list[ParsedWorkout]
    metrics: list[ParsedMetric]
    stats: ParseStats = field(default_factory=ParseStats)


ProgressFn = Callable[[float], None]  # receives the fraction read, 0.0-1.0


# ---------- Entry point ---------------------------------------------------------

def parse_export(path: Path, on_progress: ProgressFn | None = None) -> ParseResult:
    stats = ParseStats()
    workouts: list[ParsedWorkout] = []
    daily: dict[tuple[MetricType, date], ParsedMetric] = {}

    with _open_xml(path) as (raw, total_bytes):
        reader = _CountingReader(raw, total_bytes, on_progress)
        try:
            for elem in _top_level_elements(reader):
                if elem.tag == "Workout":
                    stats.workouts_seen += 1
                    _collect_workout(elem, workouts, stats)
                elif elem.tag == "Record":
                    stats.records_seen += 1
                    if (metric := _parse_metric(elem)) is not None:
                        _keep_latest(daily, metric)
        except DefusedXmlException as exc:
            raise ExportError("This XML declares entities, which we refuse to process for "
                              "safety. Real Apple Health exports never do.") from exc
        except ParseError as exc:
            raise ExportError(f"The XML is malformed or truncated ({exc}).") from exc

    workouts.sort(key=lambda w: w.start_at)
    metrics = sorted(daily.values(), key=lambda m: (m.type, m.day))
    return ParseResult(workouts=workouts, metrics=metrics, stats=stats)


# ---------- File handling ---------------------------------------------------------

@contextmanager
def _open_xml(path: Path) -> Iterator[tuple[IO[bytes], int]]:
    """Yield (binary stream, expected size) for the export XML inside a ZIP or bare file."""
    # Sniff the signature, not zipfile.is_zipfile(): a truncated ZIP (interrupted AirDrop)
    # fails is_zipfile and would be misreported as malformed XML.
    with path.open("rb") as head:
        is_zip = head.read(len(_ZIP_SIGNATURE)) == _ZIP_SIGNATURE
    if not is_zip:
        with path.open("rb") as stream:
            yield stream, path.stat().st_size
        return
    try:
        with zipfile.ZipFile(path) as archive:
            member = _find_export_xml(archive)
            with archive.open(member) as stream:
                yield stream, member.file_size
    except zipfile.BadZipFile as exc:
        raise ExportError("The ZIP file is damaged or incomplete.") from exc


def _find_export_xml(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    """Apple's ZIP holds apple_health_export/export.xml (plus export_cda.xml, routes, ...)."""
    files = [info for info in archive.infolist() if not info.is_dir()]
    candidates = [f for f in files if PurePosixPath(f.filename).name.lower() == "export.xml"]
    if not candidates:
        xml_files = [f for f in files if f.filename.lower().endswith(".xml")]
        candidates = xml_files if len(xml_files) == 1 else []
    if not candidates:
        raise ExportError("No export.xml inside this ZIP. Upload the original export.zip "
                          "from the Health app.")
    return max(candidates, key=lambda f: f.file_size)


class _CountingReader:
    """File-like wrapper: reports progress and enforces the decompressed-size limit."""

    def __init__(self, raw: IO[bytes], total_bytes: int, on_progress: ProgressFn | None):
        self._raw = raw
        self._total = total_bytes
        self._on_progress = on_progress
        self._read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._raw.read(size)
        self._read += len(chunk)
        if self._read > MAX_XML_BYTES:
            raise ExportError(f"The export XML exceeds {MAX_XML_BYTES // 1024**3} GB.")
        if self._on_progress and self._total:
            self._on_progress(min(self._read / self._total, 1.0))
        return chunk


def _top_level_elements(stream: _CountingReader) -> Iterator[Element]:
    """Yield each completed child of <HealthData>, then detach it so memory stays flat.

    Only the finished child is removed - never root.clear(). The parser reads ahead in
    chunks, so siblings may already be attached to the root; clearing it would silently
    drop them (a real data-loss bug v1 hit and fixed).
    """
    root: Element | None = None
    depth = 0
    events = iterparse(stream, events=("start", "end"),
                       forbid_dtd=False,  # Apple's export carries an (entity-free) internal DTD
                       forbid_entities=True, forbid_external=True)
    for event, elem in events:
        if event == "start":
            if root is None:
                if elem.tag != "HealthData":
                    raise ExportError("This file doesn't look like an Apple Health export.")
                root = elem
            depth += 1
            continue
        depth -= 1
        if depth == 1 and root is not None:
            yield elem
            root.remove(elem)


# ---------- Element parsing -------------------------------------------------------

def _collect_workout(elem: Element, out: list[ParsedWorkout], stats: ParseStats) -> None:
    if not _is_running(elem.get("workoutActivityType")):
        stats.skipped_not_running += 1
        return
    workout = _parse_workout(elem)
    if workout is None:
        stats.skipped_unusable += 1
    else:
        out.append(workout)
        stats.runs_kept += 1


def _is_running(activity_type: str | None) -> bool:
    """HKWorkoutActivityTypeRunning, plus indoor/outdoor variants some sources emit."""
    value = (activity_type or "").strip().lower().replace("_", "")
    return value == "running" or value.endswith(("activitytyperunning", "runningindoor",
                                                 "runningoutdoor"))


def _parse_workout(elem: Element) -> ParsedWorkout | None:
    start, end = _parse_date(elem.get("startDate")), _parse_date(elem.get("endDate"))
    if start is None or end is None or end <= start:
        return None
    stats = {c.get("type", ""): c for c in elem if c.tag == "WorkoutStatistics"}
    meta = {c.get("key", ""): c.get("value") for c in elem if c.tag == "MetadataEntry"}

    def stat(kind: str, attr: str, table: dict[str, float]) -> float | None:
        child = stats.get(f"HKQuantityTypeIdentifier{kind}")
        return _convert(child.get(attr), child.get("unit"), table) if child is not None else None

    # iOS 16+ moved totals out of <Workout> attributes into <WorkoutStatistics>.
    distance = (_convert(elem.get("totalDistance"), elem.get("totalDistanceUnit"), _LENGTH_M)
                or stat("DistanceWalkingRunning", "sum", _LENGTH_M))
    if distance is None or distance < MIN_RUN_DISTANCE_M:
        return None
    duration = (_convert(elem.get("duration"), elem.get("durationUnit"), _DURATION_S)
                or (end - start).total_seconds())
    energy = (_convert(elem.get("totalEnergyBurned"), elem.get("totalEnergyBurnedUnit"),
                       _ENERGY_KCAL)
              or stat("ActiveEnergyBurned", "sum", _ENERGY_KCAL))
    steps = stat("StepCount", "sum", {"count": 1.0})
    source = elem.get("sourceName")

    return ParsedWorkout(
        id=_stable_id(elem.get("workoutActivityType"), start, end, source),
        source_name=source,
        start_at=start,
        end_at=end,
        distance_m=distance,
        duration_s=duration,
        avg_hr=stat("HeartRate", "average", {"count/min": 1.0}),
        max_hr=stat("HeartRate", "maximum", {"count/min": 1.0}),
        energy_kcal=energy,
        elevation_gain_m=_meta_quantity(meta.get("HKElevationAscended"), _LENGTH_M),
        avg_cadence=steps / (duration / 60) if steps and duration > 0 else None,
        temperature_c=_temperature_c(meta.get("HKWeatherTemperature")),
        indoor=meta.get("HKIndoorWorkout") == "1",
    )


def _parse_metric(elem: Element) -> ParsedMetric | None:
    known = _METRICS.get(elem.get("type", ""))
    measured_at = _parse_date(elem.get("startDate"))
    value = _number(elem.get("value"))
    if known is None or measured_at is None or value is None:
        return None
    metric_type, unit = known
    return ParsedMetric(type=metric_type, day=measured_at.date(), value=value, unit=unit,
                        measured_at=measured_at)


def _keep_latest(daily: dict[tuple[MetricType, date], ParsedMetric], metric: ParsedMetric) -> None:
    """One value per metric per day: the day's latest reading wins."""
    key = (metric.type, metric.day)
    current = daily.get(key)
    if current is None or metric.measured_at >= current.measured_at:
        daily[key] = metric


# ---------- Value helpers ---------------------------------------------------------

def _parse_date(value: str | None) -> datetime | None:
    try:
        return datetime.strptime(value or "", _APPLE_DATE)
    except ValueError:
        return None


def _number(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _convert(value: str | None, unit: str | None, table: dict[str, float]) -> float | None:
    number = _number(value)
    key = (unit or "").strip()
    factor = table.get(key, table.get(key.lower()))
    return number * factor if number is not None and factor is not None else None


def _split_quantity(raw: str | None) -> tuple[str | None, str | None]:
    """Metadata quantities look like "4520 cm" or "60.8 degF"."""
    parts = (raw or "").split()
    return (parts[0], parts[1]) if len(parts) == 2 else (None, None)


def _meta_quantity(raw: str | None, table: dict[str, float]) -> float | None:
    return _convert(*_split_quantity(raw), table)


def _temperature_c(raw: str | None) -> float | None:
    value, unit = _split_quantity(raw)
    number = _number(value)
    if number is None:
        return None
    return {"degC": number, "degF": (number - 32) * 5 / 9}.get(unit or "")


def _stable_id(*parts: object) -> str:
    raw = "|".join("" if p is None else (p.isoformat() if isinstance(p, datetime) else str(p))
                   for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
