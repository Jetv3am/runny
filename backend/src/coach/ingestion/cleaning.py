"""Clean-up rules applied to parsed data before it is stored."""

from __future__ import annotations

from collections.abc import Sequence

from coach.ingestion.apple_export import ParsedWorkout

DUPLICATE_OVERLAP = 0.5  # share of the shorter run that must overlap to count as the same run


def _overlap_fraction(a: ParsedWorkout, b: ParsedWorkout) -> float:
    overlap = (min(a.end_at, b.end_at) - max(a.start_at, b.start_at)).total_seconds()
    shorter = min(a.duration_s, b.duration_s)
    return max(overlap, 0.0) / shorter if shorter > 0 else 0.0


def _richness(w: ParsedWorkout) -> tuple[bool, bool, bool, float]:
    """Prefer the recording with heart rate, then cadence, then elevation, then the longer one."""
    return (w.avg_hr is not None, w.avg_cadence is not None, w.elevation_gain_m is not None,
            w.duration_s)


def drop_duplicate_recordings(workouts: Sequence[ParsedWorkout]) -> list[ParsedWorkout]:
    """One run recorded by two apps (Watch + Strava, say) shows up twice with overlapping
    times. Keep the richer recording so mileage and load aren't double-counted."""
    kept: list[ParsedWorkout] = []
    for workout in sorted(workouts, key=lambda w: w.start_at):
        if kept and _overlap_fraction(kept[-1], workout) > DUPLICATE_OVERLAP:
            if _richness(workout) > _richness(kept[-1]):
                kept[-1] = workout
            continue
        kept.append(workout)
    return kept
