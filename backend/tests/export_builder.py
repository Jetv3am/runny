"""Builds small Apple Health exports in the modern (iOS 16+) shape for tests."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

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
        # Modern exports: no totalDistance/totalEnergyBurned attributes on <Workout>.
        return (f'<Workout workoutActivityType="{self.activity}" duration="{self.duration_min}" '
                f'durationUnit="min" sourceName="{self.source}" startDate="{self.start}" '
                f'endDate="{self.end}">{"".join(meta)}{"".join(stats)}</Workout>')


def _meta(key: str, value: object) -> str:
    return f'<MetadataEntry key="{key}" value="{value}"/>'


def record(kind: str, value: float, when: str) -> str:
    unit = "count/min" if "Heart" in kind else "mL/min·kg"
    return (f'<Record type="HKQuantityTypeIdentifier{kind}" sourceName="Apple Watch" '
            f'unit="{unit}" startDate="{when}" endDate="{when}" value="{value}"/>')


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
