"""Fitness analytics: training load series, current VDOT, readiness, pace zones, PBs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from coach.domain import training_load as tl
from coach.domain.distances import BEST_EFFORTS
from coach.domain.fitness import estimate_vdot, race_quality_performances
from coach.domain.history import daily_history
from coach.domain.models import BestEffort
from coach.domain.vdot import training_paces as compute_paces
from coach.schemas import (
    BestEffortOut,
    DailyMetric,
    FitnessSummary,
    HealthMetric,
    PaceZoneOut,
    PersonalBest,
    TrainingPaces,
)
from coach.services import repository
from coach.services.workouts import weekly_volume

RECENT_PB_DAYS = 90


def _full_daily_series() -> list[DailyMetric]:
    """Daily metrics from the first workout through today (load needs full history)."""
    history = daily_history(repository.get_workouts(), repository.today())
    if history is None:
        return []
    return [
        DailyMetric(date=d, distance_m=round(float(dist), 1), trimp=round(float(load), 1),
                    ctl=round(float(c), 1), atl=round(float(a), 1), tsb=round(float(b), 1))
        for d, dist, load, c, a, b in zip(history.days, history.distance_m, history.trimp,
                                          history.ctl, history.atl, history.tsb, strict=True)
    ]


def daily_metrics(days: int) -> list[DailyMetric]:
    return _full_daily_series()[-days:]


def health_metrics(metric_type: str | None = None) -> list[HealthMetric]:
    return [HealthMetric(date=s.day, type=s.type, value=s.value, unit=s.unit)
            for s in repository.get_health_samples()
            if metric_type is None or s.type == metric_type]


def vdot_on(day: date) -> float | None:
    performances = race_quality_performances(
        repository.get_workouts(), repository.get_best_efforts(), repository.get_profile())
    return estimate_vdot(performances, day)


def current_vdot() -> float | None:
    return vdot_on(repository.today())


def personal_bests() -> list[PersonalBest]:
    """Per standard distance: the all-time best and the best of the last 90 days."""
    efforts = repository.get_best_efforts()
    cutoff = repository.today() - timedelta(days=RECENT_PB_DAYS)
    bests = []
    for standard in BEST_EFFORTS:
        at_distance = [e for e in efforts if e.distance_key == standard.key]
        bests.append(PersonalBest(
            key=standard.key, label=standard.label, distance_m=standard.metres,
            all_time=_fastest(at_distance),
            recent=_fastest([e for e in at_distance if e.day >= cutoff])))
    return bests


def _fastest(efforts: Sequence[BestEffort]) -> BestEffortOut | None:
    if not efforts:
        return None
    best = min(efforts, key=lambda e: e.duration_s)
    return BestEffortOut(workout_id=best.workout_id, date=best.day,
                         duration_s=best.duration_s, pace_s_per_km=round(best.pace_s_per_km, 1),
                         avg_hr=best.avg_hr)


def training_paces() -> TrainingPaces | None:
    vdot = current_vdot()
    if vdot is None:
        return None
    zones = [PaceZoneOut.model_validate(z) for z in compute_paces(vdot)]
    return TrainingPaces(vdot=round(vdot, 1), zones=zones)


_ADVICE = {
    "Fresh": "You're well rested. A good day for a quality session.",
    "Neutral": "Balanced load. Train as planned.",
    "Productive": "You're absorbing solid training. Keep easy days truly easy.",
    "Overreaching": "Fatigue is high. Swap intensity for rest or an easy jog.",
    "Detrained": "Load has dropped off. Ease back in with consistent easy runs.",
}


def _briefing(form: str) -> str:
    """Advice only: no numbers or units, which the client formats in the user's units."""
    return _ADVICE[form]


def summary() -> FitnessSummary:
    series = _full_daily_series()
    today_metric = series[-1] if series else None
    week_ago = series[-8] if len(series) >= 8 else None
    ctl = today_metric.ctl if today_metric else 0.0
    atl = today_metric.atl if today_metric else 0.0
    tsb = today_metric.tsb if today_metric else 0.0
    ramp = ctl - week_ago.ctl if week_ago else 0.0

    today = repository.today()
    vdot_now = current_vdot()
    vdot_then = vdot_on(today - timedelta(days=28))
    weeks = weekly_volume(5)
    this_week, previous = weeks[-1], weeks[:-1]
    avg_4w = sum(w.distance_m for w in previous) / len(previous)

    readiness = tl.readiness_score(tsb, ramp)
    form = tl.form_label(tsb)
    return FitnessSummary(
        athlete_name=repository.get_profile().name,
        vdot=round(vdot_now, 1) if vdot_now else None,
        vdot_change_28d=round(vdot_now - vdot_then, 1) if vdot_now and vdot_then else None,
        ctl=ctl, atl=atl, tsb=tsb, form=form,
        readiness=readiness,
        readiness_label=tl.readiness_label(readiness),
        week_distance_m=this_week.distance_m,
        week_runs=this_week.runs,
        avg_week_distance_4w_m=round(avg_4w, 1),
        briefing=_briefing(form),
    )
