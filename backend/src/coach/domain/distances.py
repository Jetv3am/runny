"""Standard running distances: one definition shared by race detection, best efforts,
and predictions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StandardDistance:
    key: str  # stable API identifier
    label: str
    metres: float


ONE_K = StandardDistance("1k", "1K", 1_000)
MILE = StandardDistance("mile", "1 Mile", 1_609.344)
FIVE_K = StandardDistance("5k", "5K", 5_000)
TEN_K = StandardDistance("10k", "10K", 10_000)
HALF_MARATHON = StandardDistance("half", "Half Marathon", 21_097.5)
MARATHON = StandardDistance("marathon", "Marathon", 42_195)

RACES: tuple[StandardDistance, ...] = (FIVE_K, TEN_K, HALF_MARATHON, MARATHON)
BEST_EFFORTS: tuple[StandardDistance, ...] = (ONE_K, MILE, *RACES)
