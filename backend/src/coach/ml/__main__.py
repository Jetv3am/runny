"""Train or inspect the personal race-time model without running the web app.

    uv run python -m coach.ml train     # retrain on the imported data now
    uv run python -m coach.ml status    # what the app is using, and why
    uv run python -m coach.ml efforts   # which efforts it learns from, and why not others

Uses the same database as the app (backend/data/coach.db, or COACH_DATA_DIR).
"""

from __future__ import annotations

import argparse
import sys

from coach.domain.fitness import LOOKBACK_DAYS
from coach.ml.diagnostics import NEAR_MISS, NO_BASELINE, NO_HEART_RATE, EffortReport
from coach.schemas import ModelCard
from coach.services import models, repository
from coach.storage import database

_EXPLAIN = {
    "demo": "Showing demo data. Import an Apple Health export to train on your runs.",
    "not_trained": "Not trained yet. Run `python -m coach.ml train`.",
    "collecting_data": "Not enough race-quality efforts yet; predictions use VDOT.",
    "baseline_better": "Trained, but VDOT alone was more accurate, so the app uses VDOT.",
    "active": "Active: predictions use the personal ML model.",
}


def describe(card: ModelCard) -> str:
    lines = [_EXPLAIN[card.status],
             f"Race-quality efforts: {card.efforts} (needs {card.efforts_needed})"]
    if card.ml and card.baseline:
        name = models.ALGORITHM_NAMES.get(card.algorithm or "", card.algorithm)
        lines += [
            f"Best candidate: {name}, tested on {card.test_efforts} unseen efforts "
            f"({card.data_from} to {card.data_to})",
            f"  ML error:   {card.ml.mape_pct:5.2f}%  (avg {card.ml.mae_s:.0f} s)",
            f"  VDOT error: {card.baseline.mape_pct:5.2f}%  (avg {card.baseline.mae_s:.0f} s)",
        ]
        if card.band_coverage_pct is not None:
            lines.append(f"  Band hit rate: {card.band_coverage_pct}% (aim: 80%)")
    return "\n".join(lines)


_HINTS = {
    NO_BASELINE: ("Efforts after a break of {days}+ days have no recent VDOT to compare "
                  "against, so they can't be training examples (they still set one)."),
    NEAR_MISS: ("If some of the 'just below race level' efforts were all-out, your max "
                "heart rate ({max_hr}) may be estimated too high."),
    NO_HEART_RATE: "Runs without heart rate can't count: wear the watch (or a strap).",
}


def _clock(seconds: float) -> str:
    minutes, secs = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def describe_efforts(report: EffortReport) -> str:
    p = report.profile
    lines = [f"Heart-rate profile used: resting {p.resting_hr} bpm, max {p.max_hr} bpm.",
             f"Race level: average {report.race_level_hr} bpm or more.",
             f"Used for training: {report.used} (the model needs {models.MIN_EXAMPLES})", ""]
    if report.candidates:
        lines.append(f"{'DATE':<11} {'KIND':<7} {'DISTANCE':<14} {'TIME':>8}  {'HR':>3}  STATUS")
        lines += [f"{c.day.isoformat():<11} {c.kind:<7} {c.label:<14} {_clock(c.duration_s):>8}  "
                  f"{c.avg_hr if c.avg_hr is not None else '-':>3}  "
                  f"{'used' if c.used else c.reason}" for c in report.candidates]
    if report.dropped:
        lines += ["", "Not used, by reason:"]
        lines += [f"  {count:>4}  {reason}" for reason, count in report.dropped.most_common()]
        hints = [_HINTS[r].format(days=LOOKBACK_DAYS, max_hr=p.max_hr)
                 for r in report.dropped if r in _HINTS]
        lines += ["", *hints] if hints else []
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m coach.ml", description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("train", "status", "efforts"))
    args = parser.parse_args(argv)
    database.migrate()  # the CLI may run before the app ever has
    if repository.data_source() == "demo":
        print("(No import yet: showing demo data.)", file=sys.stderr)
    if args.command == "efforts":
        print(describe_efforts(models.effort_report()))
        return 0
    try:
        card = models.train() if args.command == "train" else models.card()
    except models.NotTrainable as exc:
        print(exc, file=sys.stderr)
        return 1
    print(describe(card))
    return 0


if __name__ == "__main__":
    sys.exit(main())
