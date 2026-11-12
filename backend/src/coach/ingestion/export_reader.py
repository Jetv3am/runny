"""Low-level reading of Apple Health exports, shared by both parser passes.

Finds the XML (inside Apple's export.zip, or bare), streams its top-level elements in
flat memory, guards against hostile input, and parses Apple's value formats.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import IO
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import iterparse

# Zip-bomb guard, counted on *decompressed* bytes (a ZIP's declared sizes can lie).
# Heavy multi-year exports reach ~5 GB of XML.
MAX_XML_BYTES = 12 * 1024**3
_ZIP_SIGNATURE = b"PK\x03\x04"
_APPLE_DATE = "%Y-%m-%d %H:%M:%S %z"

LENGTH_M = {"m": 1.0, "km": 1000.0, "cm": 0.01, "mi": 1609.344, "ft": 0.3048, "yd": 0.9144}
DURATION_S = {"s": 1.0, "sec": 1.0, "min": 60.0, "h": 3600.0, "hr": 3600.0}
# HealthKit: "Cal" (capital C) is a kilocalorie; "cal" is a calorie.
ENERGY_KCAL = {"kcal": 1.0, "Cal": 1.0, "cal": 0.001, "kJ": 1 / 4.184, "J": 1 / 4184}

ProgressFn = Callable[[float], None]  # receives the fraction read, 0.0-1.0


class ExportError(ValueError):
    """The file can't be imported. The message is shown to the user as-is."""


@contextmanager
def export_elements(path: Path, on_progress: ProgressFn | None = None
                    ) -> Iterator[Iterator[Element]]:
    """Yield an iterator over the children of <HealthData>, translating parser
    failures into user-facing ExportErrors."""
    with _open_xml(path) as (raw, total_bytes):
        try:
            yield _top_level_elements(_CountingReader(raw, total_bytes, on_progress))
        except DefusedXmlException as exc:
            raise ExportError("This XML declares entities, which we refuse to process for "
                              "safety. Real Apple Health exports never do.") from exc
        except ParseError as exc:
            raise ExportError(f"The XML is malformed or truncated ({exc}).") from exc


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


# ---------- Value helpers ---------------------------------------------------------

def parse_date(value: str | None) -> datetime | None:
    try:
        return datetime.strptime(value or "", _APPLE_DATE)
    except ValueError:
        return None


def number(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def convert(value: str | None, unit: str | None, table: dict[str, float]) -> float | None:
    """`value` in `unit`, converted with a factor table (e.g. LENGTH_M); None if unknown."""
    amount = number(value)
    key = (unit or "").strip()
    factor = table.get(key, table.get(key.lower()))
    return amount * factor if amount is not None and factor is not None else None
