"""Compact binary encoding of a `Stream` for the workout_streams table.

Layout (before zlib): version byte, two uint32 lengths (distance samples, heart-rate
samples), then float32 arrays t_s, distance_m, hr_t_s, hr_bpm. float32 is plenty:
sub-centimetre precision over a marathon, millisecond precision over 24 hours.
An hour's run is a few KB; JSON would be ~10x larger.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

from coach.domain.streams import Stream

_VERSION = 1
_HEADER = struct.Struct("<BII")
_DTYPE = np.dtype("<f4")


def encode(stream: Stream) -> bytes:
    header = _HEADER.pack(_VERSION, stream.t_s.size, stream.hr_t_s.size)
    arrays = (stream.t_s, stream.distance_m, stream.hr_t_s, stream.hr_bpm)
    return zlib.compress(header + b"".join(a.astype(_DTYPE).tobytes() for a in arrays))


def decode(blob: bytes) -> Stream:
    raw = zlib.decompress(blob)
    version, samples, readings = _HEADER.unpack_from(raw)
    if version != _VERSION:
        raise ValueError(f"Unsupported stream format version {version}")
    values = np.frombuffer(raw, dtype=_DTYPE, offset=_HEADER.size).astype(float)
    t, distance, hr_t, hr = np.split(values, np.cumsum([samples, samples, readings]))
    return Stream(t_s=t, distance_m=distance, hr_t_s=hr_t, hr_bpm=hr)
