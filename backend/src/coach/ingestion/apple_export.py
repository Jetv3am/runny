"""Pass 1 of the Apple Health import: running workouts and daily health metrics.

Keeps only what the app uses: running workouts, plus one value per day of the health
metrics in `_METRICS`. Per-second samples inside each run are pass 2 (`samples.py`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import Element

from coach.ingestion.export_reader import (
    DURATION_S,
    ENERGY_KCAL,
    LENGTH_M,
    ProgressFn,
    convert,
    export_elements,
    number,
    parse_date,
)

MIN_RUN_DISTANCE_M = 800  # shorter = accidental start or GPS noise

MetricType = Literal["vo2max", "resting_hr"]
_METRICS: dict[str, tuple[MetricType, str]] = {
    "HKQuantityTypeIdentifierVO2Max": ("vo2max", "ml/kg/min"),
    "HKQuantityTypeIdentifierRestingHeartRate": ("resting_hr", "bpm"),
}
# Manual pause (button) and auto-pause (stopped moving) both stop the clock.
_PAUSE_EVENTS = frozenset({"HKWorkoutEventTypePause", "HKWorkoutEventTypeMotionPaused"})
_RESUME_EVENTS = frozenset({"HKWorkoutEventTypeResume", "HKWorkoutEventTypeMotionResumed"})

Interval = tuple[datetime, datetime]


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
    pauses: tuple[Interval, ...] = ()  # wall-clock spans when the workout was paused


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


def parse_export(path: Path, on_progress: ProgressFn | None = None) -> ParseResult:
    stats = ParseStats()
    workouts: list[ParsedWorkout] = []
    daily: dict[tuple[MetricType, date], ParsedMetric] = {}

    with export_elements(path, on_progress) as elements:
        for elem in elements:
            if elem.tag == "Workout":
                stats.workouts_seen += 1
                _collect_workout(elem, workouts, stats)
            elif elem.tag == "Record":
                stats.records_seen += 1
                if (metric := _parse_metric(elem)) is not None:
                    _keep_latest(daily, metric)

    workouts.sort(key=lambda w: w.start_at)
    metrics = sorted(daily.values(), key=lambda m: (m.type, m.day))
    return ParseResult(workouts=workouts, metrics=metrics, stats=stats)


# ---------- Workouts --------------------------------------------------------------

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
    start, end = parse_date(elem.get("startDate")), parse_date(elem.get("endDate"))
    if start is None or end is None or end <= start:
        return None
    stats = {c.get("type", ""): c for c in elem if c.tag == "WorkoutStatistics"}
    meta = {c.get("key", ""): c.get("value") for c in elem if c.tag == "MetadataEntry"}

    def stat(kind: str, attr: str, table: dict[str, float]) -> float | None:
        child = stats.get(f"HKQuantityTypeIdentifier{kind}")
        return convert(child.get(attr), child.get("unit"), table) if child is not None else None

    # iOS 16+ moved totals out of <Workout> attributes into <WorkoutStatistics>.
    distance = (convert(elem.get("totalDistance"), elem.get("totalDistanceUnit"), LENGTH_M)
                or stat("DistanceWalkingRunning", "sum", LENGTH_M))
    if distance is None or distance < MIN_RUN_DISTANCE_M:
        return None
    duration = (convert(elem.get("duration"), elem.get("durationUnit"), DURATION_S)
                or (end - start).total_seconds())
    energy = (convert(elem.get("totalEnergyBurned"), elem.get("totalEnergyBurnedUnit"),
                      ENERGY_KCAL)
              or stat("ActiveEnergyBurned", "sum", ENERGY_KCAL))
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
        elevation_gain_m=_meta_quantity(meta.get("HKElevationAscended"), LENGTH_M),
        avg_cadence=steps / (duration / 60) if steps and duration > 0 else None,
        temperature_c=_temperature_c(meta.get("HKWeatherTemperature")),
        indoor=meta.get("HKIndoorWorkout") == "1",
        pauses=_pauses(elem, end),
    )


def _pauses(elem: Element, end: datetime) -> tuple[Interval, ...]:
    """Pair pause/resume events into spans. A pause never resumed lasts until the end."""
    events = sorted((when, child.get("type", "")) for child in elem
                    if child.tag == "WorkoutEvent"
                    and (when := parse_date(child.get("date") or child.get("startDate"))))
    spans: list[Interval] = []
    paused_at: datetime | None = None
    for when, kind in events:
        if kind in _PAUSE_EVENTS and paused_at is None:
            paused_at = when
        elif kind in _RESUME_EVENTS and paused_at is not None:
            spans.append((paused_at, when))
            paused_at = None
    if paused_at is not None:
        spans.append((paused_at, end))
    return tuple(spans)


# ---------- Health metrics --------------------------------------------------------

def _parse_metric(elem: Element) -> ParsedMetric | None:
    known = _METRICS.get(elem.get("type", ""))
    if known is None:  # most records: skip before the (slow) date parsing
        return None
    measured_at = parse_date(elem.get("startDate"))
    value = number(elem.get("value"))
    if measured_at is None or value is None:
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

def _split_quantity(raw: str | None) -> tuple[str | None, str | None]:
    """Metadata quantities look like "4520 cm" or "60.8 degF"."""
    parts = (raw or "").split()
    return (parts[0], parts[1]) if len(parts) == 2 else (None, None)


def _meta_quantity(raw: str | None, table: dict[str, float]) -> float | None:
    return convert(*_split_quantity(raw), table)


def _temperature_c(raw: str | None) -> float | None:
    value, unit = _split_quantity(raw)
    amount = number(value)
    if amount is None:
        return None
    return {"degC": amount, "degF": (amount - 32) * 5 / 9}.get(unit or "")


def _stable_id(*parts: object) -> str:
    raw = "|".join("" if p is None else (p.isoformat() if isinstance(p, datetime) else str(p))
                   for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
