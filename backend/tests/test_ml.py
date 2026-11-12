"""The race-time model: leakage, walk-forward, monotonicity, bands, promotion."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from coach.domain.history import daily_history
from coach.ml import evaluate
from coach.ml.evaluate import MIN_TRAIN, walk_forward_blocks
from coach.ml.features import FEATURES, build_examples
from coach.ml.race_model import MIN_EXAMPLES, select
from tests.ml_fixtures import START, learnable_athlete


@pytest.fixture(scope="module", autouse=True)
def fewer_refits():
    """Real algorithms and promotion rule, but 10 walk-forward refits instead of 25:
    still strictly train-on-past, test-on-future, at a third of the cost."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(evaluate, "MAX_FOLDS", 10)
        yield


@pytest.fixture(scope="module")
def learnable():
    _, performances, history = learnable_athlete()
    return build_examples(performances, history)


@pytest.fixture(scope="module")
def selection(learnable):
    return select(learnable)


def test_features_never_see_the_future():
    workouts, performances, history = learnable_athlete()
    cutoff = START + timedelta(days=300)
    past_only = build_examples([p for p in performances if p.day <= cutoff],
                               daily_history([w for w in workouts if w.day <= cutoff], cutoff))
    with_future = [e for e in build_examples(performances, history) if e.day <= cutoff]
    assert past_only == with_future  # adding later data changed nothing about the past


def test_walk_forward_trains_only_on_strictly_earlier_days():
    days = np.array([1, 2, 3, 4, 5, 6, 7, 8, 8, 9, 10, 10])
    blocks = walk_forward_blocks(days)
    assert blocks, "enough history for at least one test"
    for test in blocks:
        tested = set(days[test])
        assert (days < min(tested)).sum() >= MIN_TRAIN  # warm-up before any test
        for day in tested:  # same-day efforts are never split between train and test
            assert test[days == day].all()
    assert not walk_forward_blocks(days[:MIN_TRAIN])  # too short: nothing to test on


def test_model_learns_real_effects_and_is_promoted(selection):
    assert selection.promoted
    best = selection.best
    assert best.model.mape_pct < best.baseline.mape_pct * 0.75  # a clear win, not noise
    assert 60 <= best.coverage_pct <= 97  # p10-p90 band should catch ~80%


def test_noise_is_not_promoted():
    _, performances, history = learnable_athlete(effects=False)
    result = select(build_examples(performances, history))
    assert result.best is not None and not result.promoted  # VDOT stays in charge


def test_too_few_efforts_means_no_model(learnable):
    result = select(learnable[: MIN_EXAMPLES - 1])
    assert (result.best, result.model, result.promoted) == (None, None, False)


def test_more_fitness_never_predicts_a_slower_time(selection, learnable):
    model = selection.model
    ctl = FEATURES.index("ctl")
    row = list(learnable[-1].features)
    times = []
    for value in np.linspace(10, 120, 12):
        row[ctl] = value
        times.append(model.predict(1_200, row, 5_000)[0])
    assert all(later <= earlier + 1e-9 for earlier, later in zip(times, times[1:], strict=False))


def test_bands_are_ordered_and_widen_beyond_learned_distances(selection, learnable):
    model = selection.model
    row = learnable[-1].features
    predicted, p10, p90 = model.predict(1_200, row, 5_000)
    assert p10 < predicted < p90
    _, far_p10, far_p90 = model.predict(1_200, row, model.max_distance_m * 4)
    _, near_p10, near_p90 = model.predict(1_200, row, model.max_distance_m)
    assert far_p90 / far_p10 > near_p90 / near_p10


def test_examples_start_only_once_a_baseline_exists():
    _, performances, history = learnable_athlete()
    first = build_examples(performances, history)[0]
    assert first.day > min(p.day for p in performances)  # the very first effort can't
    assert isinstance(first.day, date)                   # be predicted from nothing
