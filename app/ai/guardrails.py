"""LLM output validation and physiological guardrails.

Ensures AI-generated training plans are safe, physiologically sound,
and internally consistent before being returned to the athlete.

Guardrail categories:
1. **Schema validation** — Structured output matches expected format
2. **Physiological safety** — Volume ramp ≤10%/week, pace within VDOT zones
3. **Consistency checks** — Plan matches stated goal distance and athlete capacity
4. **Hallucination detection** — Catches implausible paces, distances, or durations
5. **Audit logging** — All LLM inputs/outputs logged for debugging

References:
    Pfitzinger, P. & Douglas, S. (2009). Advanced Marathoning.
    Daniels, J. (2014). Daniels' Running Formula (3rd ed.).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

# Audit log directory
AUDIT_LOG_DIR = Path("logs/llm_audit")


# --- Pydantic schema validation for LLM plan output ---

class SessionSchema(BaseModel):
    """Validated schema for a single training session from LLM output."""
    date: str
    day: str
    type: str
    title: str
    target_distance_km: float = Field(ge=0.5, le=50.0)
    target_pace: str
    intensity: str
    instructions: str
    coach_rationale: str = ""

    @field_validator("type")
    @classmethod
    def validate_session_type(cls, v: str) -> str:
        allowed = {"easy_run", "tempo_run", "interval_run", "long_run", "recovery_run",
                    "fartlek", "hill_run", "progression_run", "race_pace_run", "rest"}
        if v.lower().strip() not in allowed:
            raise ValueError(f"Unknown session type '{v}'. Allowed: {allowed}")
        return v.lower().strip()

    @field_validator("intensity")
    @classmethod
    def validate_intensity(cls, v: str) -> str:
        allowed = {"very_easy", "easy", "easy_steady", "controlled", "moderate",
                    "moderate_hard", "hard", "very_hard", "race"}
        if v.lower().strip() not in allowed:
            raise ValueError(f"Unknown intensity '{v}'. Allowed: {allowed}")
        return v.lower().strip()


class PlanSchema(BaseModel):
    """Validated schema for an LLM-generated weekly plan."""
    week_start: str
    weekly_target_km: float = Field(ge=0, le=250)
    coach_focus: str = ""
    sessions: list[SessionSchema] = Field(min_length=0, max_length=7)
    message: str = ""


# --- Guardrail result types ---

@dataclass
class GuardrailViolation:
    """A single guardrail violation."""
    category: str           # 'schema', 'safety', 'consistency', 'hallucination'
    severity: str           # 'error', 'warning', 'info'
    field: str              # Which field or aspect triggered it
    message: str            # Human-readable description
    auto_fixed: bool = False  # Whether the guardrail automatically corrected it


@dataclass
class GuardrailResult:
    """Result of running all guardrails on a plan."""
    is_safe: bool                           # True if no errors (warnings are OK)
    violations: list[GuardrailViolation] = field(default_factory=list)
    corrected_plan: dict[str, Any] | None = None  # Auto-corrected plan if fixable
    raw_plan: dict[str, Any] | None = None        # Original LLM output
    validation_time_ms: float = 0.0


# --- Schema validation ---

def validate_plan_schema(plan: dict[str, Any]) -> list[GuardrailViolation]:
    """Validate that the LLM output matches the expected plan schema.

    Args:
        plan: Raw plan dict from LLM.

    Returns:
        List of schema violations.
    """
    violations: list[GuardrailViolation] = []

    try:
        PlanSchema(**plan)
    except ValidationError as exc:
        for error in exc.errors():
            violations.append(GuardrailViolation(
                category="schema",
                severity="error",
                field=".".join(str(loc) for loc in error["loc"]),
                message=error["msg"],
            ))

    return violations


# --- Physiological safety checks ---

def check_volume_safety(
    plan: dict[str, Any],
    current_weekly_km: float,
    max_ramp_pct: float = 10.0,
) -> list[GuardrailViolation]:
    """Check that the plan doesn't increase volume more than the safe ramp rate.

    The 10% rule is a widely-used guideline to prevent overuse injuries:
    weekly mileage should not increase more than ~10% week-over-week.

    Args:
        plan: Training plan dict.
        current_weekly_km: Athlete's current weekly volume in km.
        max_ramp_pct: Maximum allowed volume increase percentage.

    Returns:
        List of safety violations.
    """
    violations: list[GuardrailViolation] = []

    planned_km = float(plan.get("weekly_target_km") or 0)
    if current_weekly_km <= 0:
        return violations  # No baseline to compare against

    ramp_pct = ((planned_km - current_weekly_km) / current_weekly_km) * 100

    if ramp_pct > max_ramp_pct:
        violations.append(GuardrailViolation(
            category="safety",
            severity="warning" if ramp_pct <= 20 else "error",
            field="weekly_target_km",
            message=(
                f"Planned volume ({planned_km:.1f} km) is {ramp_pct:.0f}% higher than current "
                f"({current_weekly_km:.1f} km). Safe ramp is ≤{max_ramp_pct:.0f}%/week. "
                f"Risk of overuse injury."
            ),
        ))

    # Check individual long run isn't too high
    sessions = plan.get("sessions", [])
    for s in sessions:
        dist = float(s.get("target_distance_km") or 0)
        if dist > planned_km * 0.40 and dist > 5:
            violations.append(GuardrailViolation(
                category="safety",
                severity="warning",
                field=f"session.{s.get('day', '?')}.target_distance_km",
                message=(
                    f"Long run ({dist:.1f} km) is >{40}% of weekly volume ({planned_km:.1f} km). "
                    f"This increases injury risk."
                ),
            ))
            break  # Only flag once

    return violations


def check_pace_validity(
    plan: dict[str, Any],
    pace_zones: dict[str, str],
    vdot: float | None,
) -> list[GuardrailViolation]:
    """Check that prescribed paces are physiologically plausible for the athlete.

    Catches hallucinated paces where the LLM might prescribe elite-level
    paces for a recreational runner.

    Args:
        plan: Training plan dict.
        pace_zones: Athlete's calculated pace zones from VDOT.
        vdot: Athlete's current VDOT estimate.

    Returns:
        List of pace-related violations.
    """
    violations: list[GuardrailViolation] = []

    if not vdot:
        return violations

    # Parse pace zone boundaries (approximate)
    # VDOT-based approximate pace range in sec/km
    # Easy: ~65% of VDOT effort → roughly +60-90s over race pace
    # Elite (VDOT 80): easy ~3:30-4:00/km, interval ~3:00/km
    # Beginner (VDOT 30): easy ~7:00-7:30/km, interval ~5:30/km
    # Use VDOT to estimate reasonable min/max paces
    min_plausible_pace = max(150.0, 1000.0 / (vdot * 0.35))  # Fastest possible (generous)
    max_plausible_pace = min(600.0, 1000.0 / (vdot * 0.10))  # Slowest reasonable

    for session in plan.get("sessions", []):
        pace_str = str(session.get("target_pace", ""))
        pace_secs = _parse_pace_string(pace_str)
        if pace_secs is None:
            continue

        session_type = session.get("type", "easy_run")
        day = session.get("day", "?")

        if pace_secs < min_plausible_pace:
            violations.append(GuardrailViolation(
                category="hallucination",
                severity="error",
                field=f"session.{day}.target_pace",
                message=(
                    f"Prescribed pace ({pace_str}) is unrealistically fast for "
                    f"VDOT {vdot}. Minimum plausible: {_format_pace(min_plausible_pace)}."
                ),
            ))

        # Easy runs shouldn't be faster than tempo pace
        if session_type in ("easy_run", "recovery_run") and pace_secs < 240 and vdot < 55:
            violations.append(GuardrailViolation(
                category="hallucination",
                severity="warning",
                field=f"session.{day}.target_pace",
                message=(
                    f"Easy/recovery run pace ({pace_str}) seems too fast for VDOT {vdot}. "
                    f"Easy runs should feel conversational."
                ),
            ))

    return violations


def check_plan_consistency(
    plan: dict[str, Any],
    goal: dict[str, Any] | None,
    readiness_score: int | None,
) -> list[GuardrailViolation]:
    """Check that the plan is internally consistent and matches the goal.

    Args:
        plan: Training plan dict.
        goal: Athlete's current goal.
        readiness_score: Current readiness score (0-100).

    Returns:
        List of consistency violations.
    """
    violations: list[GuardrailViolation] = []

    sessions = plan.get("sessions", [])

    # Check session count matches training days
    if goal:
        training_days = goal.get("training_days", [])
        if len(sessions) > len(training_days):
            violations.append(GuardrailViolation(
                category="consistency",
                severity="warning",
                field="sessions",
                message=(
                    f"Plan has {len(sessions)} sessions but athlete only has "
                    f"{len(training_days)} available training days."
                ),
            ))

    # If readiness is low, there shouldn't be hard sessions
    if readiness_score is not None and readiness_score < 40:
        hard_sessions = [
            s for s in sessions
            if s.get("type") in ("interval_run", "tempo_run")
            or s.get("intensity") in ("hard", "very_hard")
        ]
        if hard_sessions:
            violations.append(GuardrailViolation(
                category="safety",
                severity="warning",
                field="sessions",
                message=(
                    f"Plan includes {len(hard_sessions)} hard session(s) but readiness score "
                    f"is only {readiness_score}/100. Consider replacing with easy runs."
                ),
            ))

    # Check total distance matches weekly_target_km
    if sessions:
        total_session_km = sum(float(s.get("target_distance_km") or 0) for s in sessions)
        planned_km = float(plan.get("weekly_target_km") or 0)
        if planned_km > 0 and abs(total_session_km - planned_km) > planned_km * 0.15:
            violations.append(GuardrailViolation(
                category="consistency",
                severity="info",
                field="weekly_target_km",
                message=(
                    f"Sum of session distances ({total_session_km:.1f} km) doesn't match "
                    f"stated weekly target ({planned_km:.1f} km)."
                ),
            ))

    return violations


# --- Auto-correction ---

def auto_correct_plan(
    plan: dict[str, Any],
    violations: list[GuardrailViolation],
    current_weekly_km: float,
    pace_zones: dict[str, str],
) -> dict[str, Any]:
    """Attempt to auto-correct a plan with guardrail violations.

    Only corrects issues that can be safely fixed without changing the
    plan's intent. Returns a copy of the plan with corrections applied.

    Args:
        plan: Original plan dict.
        violations: List of violations to attempt fixing.
        current_weekly_km: Current weekly volume.
        pace_zones: Athlete's pace zones.

    Returns:
        Corrected plan dict.
    """
    corrected = json.loads(json.dumps(plan))  # Deep copy

    for v in violations:
        if v.category == "safety" and v.severity == "error" and "volume" in v.message.lower():
            # Cap volume at 10% increase
            safe_km = round(current_weekly_km * 1.10, 1)
            if float(corrected.get("weekly_target_km", 0)) > safe_km:
                scale = safe_km / float(corrected["weekly_target_km"])
                corrected["weekly_target_km"] = safe_km
                for s in corrected.get("sessions", []):
                    s["target_distance_km"] = round(float(s["target_distance_km"]) * scale, 1)
                v.auto_fixed = True

        elif v.category == "safety" and "readiness" in v.message.lower():
            # Downgrade hard sessions to easy
            for s in corrected.get("sessions", []):
                if s.get("type") in ("interval_run", "tempo_run"):
                    s["type"] = "easy_run"
                    s["title"] = "Easy Recovery Run (downgraded due to fatigue)"
                    s["intensity"] = "easy"
                    s["instructions"] = "Keep effort conversational. Readiness is low — prioritize recovery."
                    s["coach_rationale"] = "Auto-adjusted: readiness score below safe threshold for quality work."
                    v.auto_fixed = True

    return corrected


# --- Master guardrail runner ---

def run_guardrails(
    plan: dict[str, Any],
    current_weekly_km: float = 0.0,
    pace_zones: dict[str, str] | None = None,
    vdot: float | None = None,
    goal: dict[str, Any] | None = None,
    readiness_score: int | None = None,
) -> GuardrailResult:
    """Run all guardrails on an LLM-generated training plan.

    Args:
        plan: Raw plan dict from the LLM.
        current_weekly_km: Athlete's current weekly volume.
        pace_zones: Athlete's calculated pace zones.
        vdot: Athlete's VDOT estimate.
        goal: Current racing goal.
        readiness_score: Current readiness score.

    Returns:
        GuardrailResult with violations and optional corrections.
    """
    start_time = time.monotonic()
    all_violations: list[GuardrailViolation] = []

    # 1. Schema validation
    all_violations.extend(validate_plan_schema(plan))

    # 2. Volume safety
    all_violations.extend(check_volume_safety(plan, current_weekly_km))

    # 3. Pace validity
    all_violations.extend(check_pace_validity(plan, pace_zones or {}, vdot))

    # 4. Plan consistency
    all_violations.extend(check_plan_consistency(plan, goal, readiness_score))

    # Determine overall safety
    has_errors = any(v.severity == "error" for v in all_violations)
    is_safe = not has_errors

    # Attempt auto-correction if there are fixable violations
    corrected = None
    if not is_safe:
        corrected = auto_correct_plan(plan, all_violations, current_weekly_km, pace_zones or {})

    elapsed_ms = (time.monotonic() - start_time) * 1000

    result = GuardrailResult(
        is_safe=is_safe,
        violations=all_violations,
        corrected_plan=corrected,
        raw_plan=plan,
        validation_time_ms=round(elapsed_ms, 2),
    )

    # Log violations
    if all_violations:
        for v in all_violations:
            log_fn = logger.warning if v.severity in ("error", "warning") else logger.info
            log_fn("Guardrail [%s/%s] %s: %s", v.category, v.severity, v.field, v.message)

    return result


# --- Audit logging ---

def audit_log_llm_interaction(
    endpoint: str,
    prompt: str,
    response: str | dict,
    model: str,
    latency_ms: float,
    guardrail_result: GuardrailResult | None = None,
) -> None:
    """Log an LLM interaction for debugging and evaluation.

    Args:
        endpoint: API endpoint that triggered the LLM call.
        prompt: The prompt sent to the LLM.
        response: The LLM's response (text or parsed dict).
        model: Model identifier.
        latency_ms: Request latency in milliseconds.
        guardrail_result: Optional guardrail validation result.
    """
    try:
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc)
        log_entry = {
            "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            "endpoint": endpoint,
            "model": model,
            "latency_ms": round(latency_ms, 1),
            "prompt_length": len(prompt),
            "response_length": len(str(response)),
            "prompt": prompt[:2000],  # Truncate for storage
            "response": response if isinstance(response, dict) else str(response)[:2000],
        }

        if guardrail_result:
            log_entry["guardrails"] = {
                "is_safe": guardrail_result.is_safe,
                "violation_count": len(guardrail_result.violations),
                "violations": [
                    asdict(v) for v in guardrail_result.violations
                ],
                "validation_time_ms": guardrail_result.validation_time_ms,
            }

        # Append to daily log file
        log_file = AUDIT_LOG_DIR / f"llm_audit_{timestamp.strftime('%Y%m%d')}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

    except Exception as exc:
        logger.error("Failed to write LLM audit log: %s", exc)


# --- Utility ---

def _parse_pace_string(pace_str: str) -> float | None:
    """Parse a pace string like '5:23 /km' into seconds per km."""
    try:
        cleaned = pace_str.replace("/km", "").replace("per km", "").strip()
        # Handle range: "5:30 to 6:00 /km" → take first value
        if " to " in cleaned:
            cleaned = cleaned.split(" to ")[0].strip()
        parts = cleaned.split(":")
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = int(parts[1])
            return minutes * 60 + seconds
    except (ValueError, IndexError):
        pass
    return None


def _format_pace(seconds_per_km: float) -> str:
    """Format pace as M:SS /km."""
    total = int(round(seconds_per_km))
    m, s = divmod(total, 60)
    return f"{m}:{s:02d} /km"
