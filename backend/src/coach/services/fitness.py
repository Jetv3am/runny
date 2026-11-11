"""Fitness analytics: training load series, current VDOT, readiness, pace zones."""

from __future__ import annotations

from datetime import timedelta

from coach.domain import training_load as tl
from coach.domain.fitness import estimate_vdot
from coach.domain.vdot import training_paces as compute_paces
from coach.schemas import DailyMetric, FitnessSummary, HealthMetric, PaceZoneOut, TrainingPaces
from coach.services import repository
from coach.services.workouts import weekly_volume


def _full_daily_series() -> list[DailyMetric]:
    """Daily metrics from the first workout through today (load needs full history)."""
    workouts = repository.get_workouts()
    today = repository.today()
    if not workouts:
        return []
    by_day: dict = {}
    for w in workouts:
        distance, load = by_day.get(w.day, (0.0, 0.0))
        by_day[w.day] = (distance + w.distance_m, load + w.trimp)
    first = workouts[0].day
    days = [first + timedelta(days=i) for i in range((today - first).days + 1)]
    totals = [by_day.get(d, (0.0, 0.0)) for d in days]
    loads = tl.training_load([t for _, t in totals])
    return [
        DailyMetric(date=d, distance_m=round(dist, 1), trimp=round(trimp, 1),
                    ctl=round(p.ctl, 1), atl=round(p.atl, 1), tsb=round(p.tsb, 1))
        for d, (dist, trimp), p in zip(days, totals, loads, strict=True)
    ]


def daily_metrics(days: int) -> list[DailyMetric]:
    return _full_daily_series()[-days:]


def health_metrics(metric_type: str | None = None) -> list[HealthMetric]:
    return [HealthMetric(date=s.day, type=s.type, value=s.value, unit=s.unit)
            for s in repository.get_health_samples()
            if metric_type is None or s.type == metric_type]


def current_vdot() -> float | None:
    return estimate_vdot(repository.get_workouts(), repository.today())


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
    vdot_then = estimate_vdot(repository.get_workouts(), today - timedelta(days=28))
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
