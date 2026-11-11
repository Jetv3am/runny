"""Deterministic demo coach: routes a question to a 'tool' (service call) by keyword.

Mirrors the Phase 5 architecture (intent -> tool -> grounded answer) without an
LLM, so the chat UI is fully exercisable today. Every number comes from services.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from coach.assistant import formatting as fmt
from coach.services import fitness, plans, predictions, repository

SAFETY_TERMS = ("chest pain", "faint", "dizzy", "can't breathe", "cannot breathe",
                "sharp pain", "palpitation", "passed out")

SAFETY_REPLY = (
    "That sounds like it needs a medical professional, not a running coach. Please stop "
    "training and get checked out by a doctor or urgent care, especially if symptoms are "
    "severe or ongoing. I'm happy to help plan a return to running once you're cleared."
)


def _paces() -> str:
    paces = fitness.training_paces()
    if paces is None:
        return "I need at least one recent race effort to set your pace zones."
    lines = [f"- **{z.name}**: {fmt.pace(z.fast_s_per_km)} to {fmt.pace(z.slow_s_per_km)}"
             f" ({z.purpose.lower()})" for z in paces.zones]
    return f"Based on your current VDOT of {paces.vdot}, your training paces are:\n\n" + \
        "\n".join(lines)


def _predictions() -> str:
    result = predictions.race_predictions()
    if result is None:
        return "I need at least one recent race effort before I can predict race times."
    lines = [f"- **{p.label}**: {fmt.duration(p.predicted_s)} "
             f"(range {fmt.duration(p.p10_s)} to {fmt.duration(p.p90_s)})"
             for p in result.predictions]
    return (f"From your VDOT of {result.vdot}, here's what you're ready for today:\n\n"
            + "\n".join(lines)
            + "\n\nThese assume a good day, sensible pacing, and race-specific training.")


def _form() -> str:
    s = fitness.summary()
    return (f"Your fitness (CTL) is {s.ctl:.0f}, fatigue (ATL) is {s.atl:.0f}, so your form "
            f"(TSB) is {s.tsb:+.0f}, which is **{s.form.lower()}**. Readiness is "
            f"{s.readiness}/100: {s.readiness_label.lower()}.\n\n{s.briefing}")


def _plan() -> str:
    plan = plans.current_plan()
    today = repository.today()
    upcoming = [s for w in plan.weeks for s in w.sessions if s.date >= today and s.type]
    if not upcoming:
        return "There are no upcoming sessions in your plan."
    nxt = upcoming[0]
    when = "Today" if nxt.date == today else nxt.date.strftime("%A")
    pace_note = (f" Aim for {fmt.pace(nxt.target_fast_s_per_km)} to "
                 f"{fmt.pace(nxt.target_slow_s_per_km)}."
                 if nxt.target_fast_s_per_km and nxt.target_slow_s_per_km else "")
    weeks_left = len(plan.weeks)
    return (f"**{when}: {nxt.title}, {fmt.km(nxt.distance_m)}.** {nxt.description}{pace_note}"
            f"\n\nYou're {weeks_left} week(s) out from {plan.goal.race_label}.")


def _overview() -> str:
    s = fitness.summary()
    vdot = f"VDOT {s.vdot}" if s.vdot else "no VDOT yet"
    return (f"Here's where you stand: {vdot}, form is {s.form.lower()}, and you've run "
            f"{fmt.km(s.week_distance_m)} across {s.week_runs} run(s) this week.\n\n"
            "Ask me about your **training paces**, **race predictions**, **fatigue and "
            "readiness**, or **your next workout**.")


# (keywords, tool) - first match wins; order matters.
_INTENTS: tuple[tuple[tuple[str, ...], Callable[[], str]], ...] = (
    (("pace", "zone", "how fast"), _paces),
    (("predict", "race time", "marathon", "5k", "10k", "half", "pr ", "personal best"),
     _predictions),
    (("tired", "fatigue", "form", "load", "ready", "readiness", "recover", "rest"), _form),
    (("plan", "workout", "today", "tomorrow", "next", "schedule", "session"), _plan),
)


def answer(question: str) -> str:
    text = question.lower()
    if any(term in text for term in SAFETY_TERMS):
        return SAFETY_REPLY
    for keywords, tool in _INTENTS:
        if any(k in text for k in keywords):
            return tool()
    return _overview()


async def stream_answer(question: str, delay_s: float = 0.015) -> AsyncIterator[str]:
    """Yield the answer word-by-word to exercise the streaming UI."""
    words = answer(question).split(" ")
    for i, word in enumerate(words):
        yield word if i == 0 else f" {word}"
        if delay_s:
            await asyncio.sleep(delay_s)
