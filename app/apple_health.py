"""Parser for Apple's built-in Health export (export.xml or export.zip).

The parser streams XML elements rather than loading the entire export into
memory. It imports running workouts and VO2 max samples; unrelated health data
is deliberately ignored for this running-coach MVP.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from collections import Counter
from datetime import datetime, timezone
from typing import BinaryIO


class AppleHealthImportError(ValueError):
    """Raised when an uploaded file is not a supported Apple Health export."""


@dataclass
class ParsedHealthExport:
    workouts: list[dict]
    health_metrics: list[dict]
    ignored_workouts: int = 0
    diagnostics: dict = field(default_factory=dict)


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _float_or_none(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise_date(value: str | None) -> str | None:
    """Convert Apple's timestamp (usually with a numeric timezone) to UTC ISO 8601."""
    if not value:
        return None
    raw = value.strip()
    parsed = None
    # Common Apple Health format: '2026-10-10 07:00:00 -0700'
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(raw, fmt)
            break
        except ValueError:
            pass
    if parsed is None:
        candidate = raw.replace(" ", "T", 1)
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")



def _convert_duration(value: str | None, unit: str | None) -> float | None:
    number = _float_or_none(value)
    if number is None:
        return None
    unit_key = (unit or "").strip().lower()
    if unit_key in {"s", "sec", "secs", "second", "seconds"}:
        return number
    if unit_key in {"min", "mins", "minute", "minutes"}:
        return number * 60
    if unit_key in {"h", "hr", "hrs", "hour", "hours"}:
        return number * 3600
    return None


def _convert_distance(value: str | None, unit: str | None) -> float | None:
    number = _float_or_none(value)
    if number is None:
        return None
    unit_key = (unit or "").strip().lower().replace(" ", "")
    if unit_key in {"m", "meter", "meters", "metre", "metres"}:
        return number
    if unit_key in {"km", "kilometer", "kilometers", "kilometre", "kilometres"}:
        return number * 1000
    if unit_key in {"mi", "mile", "miles"}:
        return number * 1609.344
    if unit_key in {"yd", "yard", "yards"}:
        return number * 0.9144
    return None


def _convert_energy(value: str | None, unit: str | None) -> float | None:
    number = _float_or_none(value)
    if number is None:
        return None
    unit_key = (unit or "").strip().lower()
    if unit_key in {"kcal", "kilocalorie", "kilocalories"}:
        return number
    if unit_key in {"cal", "calorie", "calories"}:
        return number / 1000
    if unit_key in {"kj", "kilojoule", "kilojoules"}:
        return number / 4.184
    return None


def _stable_id(*parts: object) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _is_running(activity_type: str | None) -> bool:
    """Recognize Apple's running activity variants without matching unrelated sports."""
    if not activity_type:
        return False
    value = activity_type.strip().lower().replace("_", "")
    # Apple exports usually use HKWorkoutActivityTypeRunning. Some sources label
    # indoor/outdoor variants separately, so accept those too.
    return value == "running" or value.endswith("activitytyperunning") or value.endswith("runningindoor") or value.endswith("runningoutdoor")


def _parse_hr_value(value: str | None) -> float | None:
    """Extract a numeric heart rate (bpm) from strings like '155 count/min' or '155 bpm'."""
    if not value:
        return None
    import re
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(value))
    if m:
        try:
            num = float(m.group(1))
            if 30.0 <= num <= 250.0:
                return round(num, 1)
        except (ValueError, TypeError):
            pass
    return None


def _workout_to_activity(elem: ET.Element) -> dict | None:
    activity_type = elem.attrib.get("workoutActivityType", "")
    if not _is_running(activity_type):
        return None

    start_date = _normalise_date(elem.attrib.get("startDate"))
    end_date = _normalise_date(elem.attrib.get("endDate"))
    if not start_date or not end_date:
        return None

    average_hr = None
    minimum_hr = None
    maximum_hr = None
    stat_distance_m = None

    for child in elem:
        tag = _local_tag(child.tag)
        if tag == "WorkoutStatistics":
            stat_type = child.attrib.get("type", "")
            if "HeartRate" in stat_type:
                if average_hr is None:
                    average_hr = _float_or_none(child.attrib.get("average"))
                if minimum_hr is None:
                    minimum_hr = _float_or_none(child.attrib.get("minimum"))
                if maximum_hr is None:
                    maximum_hr = _float_or_none(child.attrib.get("maximum"))
            elif "DistanceWalkingRunning" in stat_type or "RunningDistance" in stat_type:
                stat_distance_m = _convert_distance(
                    child.attrib.get("sum"), child.attrib.get("unit")
                )
        elif tag == "MetadataEntry":
            key = (child.attrib.get("key") or "").strip().lower().replace("_", "").replace(" ", "")
            val = child.attrib.get("value")
            if "averageheartrate" in key or "avgheartrate" in key:
                if average_hr is None:
                    average_hr = _parse_hr_value(val)
            elif "maxheartrate" in key or "maximumheartrate" in key:
                if maximum_hr is None:
                    maximum_hr = _parse_hr_value(val)
            elif "minheartrate" in key or "minimumheartrate" in key:
                if minimum_hr is None:
                    minimum_hr = _parse_hr_value(val)

    distance_m = _convert_distance(
        elem.attrib.get("totalDistance"), elem.attrib.get("totalDistanceUnit")
    )
    if distance_m is None:
        distance_m = stat_distance_m


    raw_start = (elem.attrib.get("startDate") or "").strip()
    local_day = raw_start[:10] if len(raw_start) >= 10 else start_date[:10]

    return {
        "id": f"apple_health_{_stable_id(start_date, end_date, activity_type, elem.attrib.get('sourceName'), distance_m)}",
        "source": "apple_health",
        "name": f"Run — {local_day}",
        "type": "Running",
        "start_date": start_date,
        "end_date": end_date,

        "distance_m": distance_m,
        "duration_s": _convert_duration(
            elem.attrib.get("duration"), elem.attrib.get("durationUnit")
        ),
        "average_heartrate": average_hr,
        "minimum_heartrate": minimum_hr,
        "max_heartrate": maximum_hr,
        "energy_kcal": _convert_energy(
            elem.attrib.get("totalEnergyBurned"), elem.attrib.get("totalEnergyBurnedUnit")
        ),
        "source_name": elem.attrib.get("sourceName"),
    }


def _record_to_metric(elem: ET.Element) -> dict | None:
    record_type = elem.attrib.get("type", "")
    # Be tolerant of case and punctuation differences between export versions,
    # while still requiring this to be a VO2 max quantity record.
    normalized_type = "".join(ch for ch in record_type.lower() if ch.isalnum())
    if "vo2max" not in normalized_type:
        return None

    measured_at = _normalise_date(elem.attrib.get("startDate") or elem.attrib.get("creationDate"))
    value = _float_or_none(elem.attrib.get("value"))
    if not measured_at or value is None:
        return None

    source_name = elem.attrib.get("sourceName")
    return {
        "id": f"apple_health_{_stable_id(record_type, measured_at, value, source_name)}",
        "metric_type": "vo2_max",
        "value": value,
        "unit": elem.attrib.get("unit") or "ml/kg/min",
        "measured_at": measured_at,
        "source_name": source_name,
    }


def parse_health_xml(xml_stream: BinaryIO) -> ParsedHealthExport:
    """Parse Apple Health XML without clearing unprocessed sibling elements.

    Apple's export can contain hundreds of thousands of Record elements. We
    keep a parent stack and remove each completed Workout/Record from its parent
    after processing it. Calling root.clear() for every record can detach sibling
    elements that the parser has already read ahead to, silently losing data.
    """
    workouts: list[dict] = []
    metrics: list[dict] = []
    ignored_workouts = 0
    seen_workout_elements = 0
    seen_record_elements = 0
    workout_type_counts: Counter[str] = Counter()
    vo2_like_record_types: Counter[str] = Counter()

    try:
        context = ET.iterparse(xml_stream, events=("start", "end"))
        first_event, root = next(context)
        if first_event != "start" or _local_tag(root.tag) != "HealthData":
            raise AppleHealthImportError("This XML file does not look like an Apple Health export.")
        stack = [root]

        for event, elem in context:
            if event == "start":
                stack.append(elem)
                continue

            tag = _local_tag(elem.tag)
            if tag == "Workout":
                seen_workout_elements += 1
                activity_type = elem.attrib.get("workoutActivityType", "<missing>")
                workout_type_counts[activity_type] += 1
                activity = _workout_to_activity(elem)
                if activity is None:
                    ignored_workouts += 1
                else:
                    workouts.append(activity)
            elif tag == "Record":
                seen_record_elements += 1
                record_type = elem.attrib.get("type", "<missing>")
                if "vo2" in record_type.lower():
                    vo2_like_record_types[record_type] += 1
                metric = _record_to_metric(elem)
                if metric is not None:
                    metrics.append(metric)

            # Remove only the completed element, never all siblings from root.
            if len(stack) >= 2 and tag in {"Workout", "Record"}:
                try:
                    stack[-2].remove(elem)
                except ValueError:
                    pass
                elem.clear()
            if stack and stack[-1] is elem:
                stack.pop()

    except ET.ParseError as exc:
        raise AppleHealthImportError(f"Could not parse the XML: {exc}") from exc
    except StopIteration as exc:
        raise AppleHealthImportError("The uploaded XML file is empty.") from exc

    return ParsedHealthExport(
        workouts=workouts,
        health_metrics=metrics,
        ignored_workouts=ignored_workouts,
        diagnostics={
            "workout_elements_seen": seen_workout_elements,
            "record_elements_seen": seen_record_elements,
            "workout_activity_types": dict(workout_type_counts.most_common(12)),
            "vo2_like_record_types": dict(vo2_like_record_types.most_common(12)),
        },
    )


def parse_apple_health_upload(file_obj: BinaryIO, max_xml_bytes: int) -> ParsedHealthExport:
    """Accept either Apple's ZIP export or a standalone export.xml file."""
    file_obj.seek(0)
    try:
        is_zip = zipfile.is_zipfile(file_obj)
    except OSError:
        is_zip = False
    file_obj.seek(0)

    if not is_zip:
        file_obj.seek(0, io.SEEK_END)
        xml_size = file_obj.tell()
        file_obj.seek(0)
        if xml_size > max_xml_bytes:
            raise AppleHealthImportError(
                f"XML file is larger than the configured {max_xml_bytes // (1024 * 1024)} MB limit."
            )
        return parse_health_xml(file_obj)

    try:
        with zipfile.ZipFile(file_obj) as archive:
            candidates = [
                info for info in archive.infolist()
                if not info.is_dir() and info.filename.replace("\\", "/").lower().endswith("export.xml")
            ]
            if not candidates:
                xml_candidates = [
                    info for info in archive.infolist()
                    if not info.is_dir() and info.filename.lower().endswith(".xml")
                ]
                if len(xml_candidates) == 1:
                    candidates = xml_candidates
            if not candidates:
                raise AppleHealthImportError(
                    "No export.xml was found inside the ZIP. Upload Apple's original Health export ZIP or export.xml."
                )

            xml_info = max(candidates, key=lambda item: item.file_size)
            if xml_info.file_size > max_xml_bytes:
                raise AppleHealthImportError(
                    f"The XML inside this ZIP is larger than the configured {max_xml_bytes // (1024 * 1024)} MB limit."
                )
            with archive.open(xml_info, "r") as xml_stream:
                return parse_health_xml(xml_stream)
    except zipfile.BadZipFile as exc:
        raise AppleHealthImportError("The ZIP file is damaged or invalid.") from exc
