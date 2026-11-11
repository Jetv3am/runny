"""Human-readable formatting for coach text replies (the UI formats its own numbers)."""

from __future__ import annotations


def pace(seconds_per_km: float) -> str:
    minutes, seconds = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{seconds:02d}/km"


def duration(seconds: float) -> str:
    hours, rem = divmod(round(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def km(metres: float) -> str:
    return f"{metres / 1000:.1f} km"
