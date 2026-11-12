"""Builds small Apple Health exports in the modern (iOS 16+) shape for tests."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Apple's real exports start with an internal DTD like this (no entity declarations).
APPLE_PROLOGUE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [
<!ELEMENT HealthData (ExportDate,Me,(Record|Correlation|Workout|ActivitySummary)*)>
<!ATTLIST HealthData locale CDATA #REQUIRED>
<!ELEMENT Workout ((MetadataEntry|WorkoutEvent|WorkoutRoute|WorkoutStatistics)*)>
<!ATTLIST Workout workoutActivityType CDATA #REQUIRED>
]>
"""


@dataclass
class Run:
    start: str = "2026-10-03 18:30:00 -0700"
    end: str = "2026-10-03 19:20:00 -0700"
    distance_km: float = 10.0
    duration_min: float = 50.0
    avg_hr: float | None = 150
    max_hr: float | None = 172
    steps: float | None = 8_500
    elevation_cm: float | None = 4520
    temp_f: float | None = 60.8
    indoor: bool = False
    source: str = "Apple Watch"
    activity: str = "HKWorkoutActivityTypeRunning"
    pauses: list[tuple[str, str]] = field(default_factory=list)  # (paused, resumed)

    def xml(self) -> str:
        span = f'startDate="{self.start}" endDate="{self.end}"'
        stats = [f'<WorkoutStatistics type="HKQuantityTypeIdentifierDistanceWalkingRunning" '
                 f'{span} sum="{self.distance_km}" unit="km"/>',
                 f'<WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" '
                 f'{span} sum="640" unit="kcal"/>']
        if self.avg_hr is not None:
            stats.append(f'<WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate" '
                         f'{span} average="{self.avg_hr}" '
                         f'minimum="110" maximum="{self.max_hr}" unit="count/min"/>')
        if self.steps is not None:
            stats.append(f'<WorkoutStatistics type="HKQuantityTypeIdentifierStepCount" '
                         f'{span} sum="{self.steps}" unit="count"/>')
        meta = [_meta("HKIndoorWorkout", int(self.indoor))]
        if self.elevation_cm is not None:
            meta.append(_meta("HKElevationAscended", f"{self.elevation_cm} cm"))
        if self.temp_f is not None:
            meta.append(_meta("HKWeatherTemperature", f"{self.temp_f} degF"))
        events = [f'<WorkoutEvent type="HKWorkoutEventType{kind}" date="{when}"/>'
                  for paused, resumed in self.pauses
                  for kind, when in (("Pause", paused), ("Resume", resumed))]
        # Modern exports: no totalDistance/totalEnergyBurned attributes on <Workout>.
        return (f'<Workout workoutActivityType="{self.activity}" duration="{self.duration_min}" '
                f'durationUnit="min" sourceName="{self.source}" startDate="{self.start}" '
                f'endDate="{self.end}">{"".join(meta)}{"".join(events)}{"".join(stats)}</Workout>')


def _meta(key: str, value: object) -> str:
    return f'<MetadataEntry key="{key}" value="{value}"/>'


def record(kind: str, value: float, when: str) -> str:
    unit = "count/min" if "Heart" in kind else "mL/min·kg"
    return (f'<Record type="HKQuantityTypeIdentifier{kind}" sourceName="Apple Watch" '
            f'unit="{unit}" startDate="{when}" endDate="{when}" value="{value}"/>')


APPLE_DATE = "%Y-%m-%d %H:%M:%S %z"


def fmt(moment: datetime) -> str:
    return moment.strftime(APPLE_DATE)


def sampled_run(start: str, legs: list[tuple[float, float]], *, hr: float = 150,
                pause: tuple[float, float] | None = None, every_s: int = 10,
                sources: tuple[str, ...] = ("Apple Watch",)) -> tuple[Run, list[str]]:
    """A run plus the distance/HR records a watch writes during it.

    legs: (metres, pace s/km) stretches run back to back.
    pause: (after this many active seconds, for this many seconds) - the clock stops.
    sources: every listed device records the same distance (e.g. iPhone and Watch).
    """
    begin = datetime.strptime(start, APPLE_DATE)
    pause_at, pause_len = pause or (float("inf"), 0.0)

    def wall(active_s: float, *, ending: bool = False) -> datetime:
        """Clock time for an active second. At the pause boundary itself, a sample
        that *ends* there ends before the pause; one that *starts* there, after it."""
        after_pause = active_s > pause_at if ending else active_s >= pause_at
        return begin + timedelta(seconds=active_s + (pause_len if after_pause else 0))

    records, active, metres_done = [], 0.0, 0.0
    for metres, pace in legs:
        leg_end = active + metres / 1000 * pace
        while active < leg_end - 1e-9:
            step = min(every_s, leg_end - active)
            if active < pause_at < active + step:
                step = pause_at - active  # no sample straddles the pause
            covered = step / pace * 1000
            for source in sources:
                records.append(
                    f'<Record type="HKQuantityTypeIdentifierDistanceWalkingRunning" '
                    f'sourceName="{source}" unit="km" startDate="{fmt(wall(active))}" '
                    f'endDate="{fmt(wall(active + step, ending=True))}" '
                    f'value="{covered / 1000:.6f}"/>')
            active += step
            metres_done += covered
    records += [record("HeartRate", hr, fmt(wall(t))) for t in range(0, int(active), 5)]
    pauses = ([(fmt(begin + timedelta(seconds=pause_at)),
                fmt(begin + timedelta(seconds=pause_at + pause_len)))] if pause else [])
    run = Run(start=start, end=fmt(wall(active, ending=True)), distance_km=metres_done / 1000,
              duration_min=active / 60, avg_hr=hr, max_hr=hr + 10, pauses=pauses)
    return run, records


def export_xml(*elements: str) -> bytes:
    body = "\n".join(elements)
    return (f'{APPLE_PROLOGUE}<HealthData locale="en_US">'
            f'<ExportDate value="2026-11-01 08:00:00 -0700"/><Me/>{body}</HealthData>').encode()


def export_zip(xml: bytes) -> bytes:
    """Mirror Apple's layout, including the clinical export_cda.xml that must be ignored."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("apple_health_export/export.xml", xml)
        archive.writestr("apple_health_export/export_cda.xml", b"<ClinicalDocument/>")
        archive.writestr("apple_health_export/workout-routes/route_1.gpx", b"<gpx/>")
    return buffer.getvalue()
