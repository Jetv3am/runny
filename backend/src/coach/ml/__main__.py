"""Train or inspect the personal race-time model without running the web app.

    uv run python -m coach.ml train     # retrain on the imported data now
    uv run python -m coach.ml status    # what the app is using, and why

Uses the same database as the app (backend/data/coach.db, or COACH_DATA_DIR).
"""

from __future__ import annotations

import argparse
import sys

from coach.schemas import ModelCard
from coach.services import models
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m coach.ml", description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("train", "status"))
    args = parser.parse_args(argv)
    database.migrate()  # the CLI may run before the app ever has
    try:
        card = models.train() if args.command == "train" else models.card()
    except models.NotTrainable as exc:
        print(exc, file=sys.stderr)
        return 1
    print(describe(card))
    return 0


if __name__ == "__main__":
    sys.exit(main())
