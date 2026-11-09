"""AI Coaching and Adaptive Plan Generator.

Combines the quantitative ML Fitness Profile (VDOT, Banister training load,
Jack Daniels pace zones, readiness score) with Gemini LLM reasoning to
generate personalized, pace-calibrated weekly running plans.

Includes:
- RAG: Retrieves relevant past workouts from the vector store to ground
  coaching responses in athlete-specific training history.
- Guardrails: Validates all LLM-generated plans for physiological safety,
  schema correctness, and internal consistency before returning them.
- Audit logging: Records all LLM inputs/outputs for debugging and evaluation.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import GEMINI_API_KEY, GEMINI_MODEL
from app.ml.profile import FitnessProfile, fitness_profile_for_llm
from app.planner import DISTANCE_KM, DAY_NAMES
from app.ai.rag import build_rag_context, retrieve_relevant_runs
from app.ai.guardrails import (
    run_guardrails,
    audit_log_llm_interaction,
    GuardrailResult,
)

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def generate_ai_training_plan(
    profile: FitnessProfile,
    goal: dict[str, Any],
    today: date | None = None,
    user_notes: str | None = None,
) -> dict[str, Any]:
    """Generate an adaptive weekly training plan using ML metrics and AI.

    If GEMINI_API_KEY is configured, calls Gemini with the runner's ML profile
    and goal to generate an AI-coached plan. Otherwise, falls back to the
    adaptive ML rule engine that calibrates paces and volume to VDOT and TSB.

    Args:
        profile: Complete ML FitnessProfile.
        goal: Runner's goal dict (goal_type, target_time_seconds, race_date, training_days).
        today: Reference start date.
        user_notes: Optional runner preferences or constraints.

    Returns:
        Structured weekly plan dictionary.
    """
    today = today or datetime.now(timezone.utc).date()

    # Extract current state for guardrails
    current_weekly_km = float(profile.training_load.get("total_trimp_7d", 0)) * 0.15  # Approximate km from TRIMP
    pace_zones = profile.vdot.get("pace_zones") or {}
    vdot_val = profile.vdot.get("estimated_vdot")
    readiness = int(profile.readiness.get("score") or 70)

    # If Gemini API key is available, attempt LLM plan generation
    if GEMINI_API_KEY:
        try:
            llm_plan = _call_gemini_for_plan(profile, goal, today, user_notes)
            if llm_plan and "sessions" in llm_plan and len(llm_plan["sessions"]) > 0:
                # Run guardrails on LLM output
                guardrail_result = run_guardrails(
                    plan=llm_plan,
                    current_weekly_km=current_weekly_km,
                    pace_zones=pace_zones,
                    vdot=vdot_val,
                    goal=goal,
                    readiness_score=readiness,
                )

                if not guardrail_result.is_safe and guardrail_result.corrected_plan:
                    logger.info(
                        "Guardrails auto-corrected %d violation(s) in LLM plan",
                        len(guardrail_result.violations),
                    )
                    llm_plan = guardrail_result.corrected_plan

                llm_plan["generator"] = "gemini_ai"
                llm_plan["guardrails"] = {
                    "passed": guardrail_result.is_safe,
                    "violations": [
                        {"category": v.category, "severity": v.severity,
                         "message": v.message, "auto_fixed": v.auto_fixed}
                        for v in guardrail_result.violations
                    ],
                    "validation_time_ms": guardrail_result.validation_time_ms,
                }
                return llm_plan
        except Exception as exc:
            logger.warning("Gemini plan generation failed, using ML adaptive planner: %s", exc)

    # Fallback to deterministic ML-calibrated planner
    ml_plan = _build_adaptive_ml_plan(profile, goal, today)
    ml_plan["generator"] = "ml_engine"
    return ml_plan


def _build_adaptive_ml_plan(
    profile: FitnessProfile,
    goal: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    """Build an adaptive weekly plan based on ML metrics (VDOT, CTL, TSB, readiness)."""
    training_days = set(goal.get("training_days", []))
    valid_days = [day for day in DAY_NAMES if day in training_days]
    goal_type = goal.get("goal_type", "5k").strip().lower()
    goal_dist = DISTANCE_KM.get(goal_type, 5.0)

    if not valid_days:
        return {
            "goal": goal_type,
            "goal_distance_km": goal_dist,
            "week_start": today.isoformat(),
            "weekly_target_km": 0,
            "sessions": [],
            "message": "Choose at least one available training day to generate a plan.",
            "status": "missing_training_days",
        }

    # Extract ML metrics
    vdot_val = profile.vdot.get("estimated_vdot")
    pace_zones = profile.vdot.get("pace_zones") or {}
    load = profile.training_load
    ctl = float(load.get("ctl_fitness") or 0.0)
    atl = float(load.get("atl_fatigue") or 0.0)
    tsb = float(load.get("tsb_form") or 0.0)
    load_status = load.get("status", "absorbing")
    readiness_score = int(profile.readiness.get("score") or 70)
    readiness_label = profile.readiness.get("label", "ready")
    recommendation = profile.readiness.get("recommendation", "")

    # Establish baseline weekly volume using CTL
    anchor_volume = max(ctl * 1.4, 10.0) if ctl > 0 else 12.0

    # Volume adaptation based on training load & readiness
    if load_status == "overreaching" or readiness_score < 45:
        target_volume = round(anchor_volume * 0.75, 1)
        coach_focus = "Recovery & Adaptation Week: High fatigue detected. Reducing volume to absorb prior training."
    elif load_status == "optimal" and readiness_score >= 75:
        target_volume = round(anchor_volume * 1.08, 1)
        coach_focus = "Build Week: High readiness and balanced fatigue. Safe to build progressive aerobic volume."
    elif load_status == "fresh":
        target_volume = round(anchor_volume * 1.05, 1)
        coach_focus = "Freshness Phase: Your form is high. Prime state to introduce controlled threshold work."
    else:
        target_volume = round(anchor_volume * 1.0, 1)
        coach_focus = "Aerobic Base Maintenance: Steady consistency to consolidate aerobic fitness."

    num_days = min(len(valid_days), 5)
    selected_days = valid_days[:num_days]

    # Structure session archetypes
    sessions_meta = []
    if num_days == 1:
        sessions_meta.append(("easy_run", 1.0))
    elif num_days == 2:
        sessions_meta.append(("easy_run", 0.45))
        sessions_meta.append(("long_run", 0.55))
    elif num_days == 3:
        if vdot_val and readiness_score >= 60 and load_status != "overreaching":
            sessions_meta.append(("easy_run", 0.30))
            sessions_meta.append(("tempo_run", 0.25))
            sessions_meta.append(("long_run", 0.45))
        else:
            sessions_meta.append(("easy_run", 0.32))
            sessions_meta.append(("recovery_run", 0.28))
            sessions_meta.append(("long_run", 0.40))
    elif num_days == 4:
        if vdot_val and readiness_score >= 60 and load_status != "overreaching":
            sessions_meta.append(("easy_run", 0.25))
            sessions_meta.append(("tempo_run", 0.22))
            sessions_meta.append(("easy_run", 0.20))
            sessions_meta.append(("long_run", 0.33))
        else:
            sessions_meta.append(("easy_run", 0.25))
            sessions_meta.append(("recovery_run", 0.20))
            sessions_meta.append(("easy_run", 0.22))
            sessions_meta.append(("long_run", 0.33))
    else:  # 5 days
        sessions_meta.append(("easy_run", 0.20))
        sessions_meta.append(("tempo_run", 0.20))
        sessions_meta.append(("recovery_run", 0.15))
        sessions_meta.append(("interval_run" if vdot_val and readiness_score >= 75 else "easy_run", 0.15))
        sessions_meta.append(("long_run", 0.30))

    easy_pace_str = pace_zones.get("easy", "6:00 to 6:40 /km")
    tempo_pace_str = pace_zones.get("tempo", "5:10 /km")
    interval_pace_str = pace_zones.get("interval", "4:45 /km")

    sessions: list[dict[str, Any]] = []
    for idx, ((session_type, weight), day_name) in enumerate(zip(sessions_meta, selected_days)):
        day_offset = (DAY_NAMES.index(day_name) - today.weekday()) % 7
        session_date = today + timedelta(days=day_offset)
        session_km = max(round(target_volume * weight, 1), 3.0)

        if session_type == "tempo_run":
            title = "Threshold / Tempo Run"
            intensity = "moderate_hard"
            target_pace = tempo_pace_str
            description = (
                f"Warm up 1-2 km easy ({easy_pace_str}), then run steady threshold pace "
                f"({tempo_pace_str}). Effort should feel comfortably hard. Cool down 1 km easy."
            )
            rationale = f"Calibrated for your VDOT of {vdot_val or 'estimated baseline'} to build lactate clearance capacity."
        elif session_type == "interval_run":
            title = "Aerobic Intervals"
            intensity = "hard"
            target_pace = interval_pace_str
            description = (
                f"Warm up 1.5 km easy. Run 4 to 5 repetitions at interval pace ({interval_pace_str}) "
                f"with 2:00 standing/walking recovery. Cool down 1 km easy."
            )
            rationale = "High readiness score permits VO2 peak aerobic stimulus to lift running economy."
        elif session_type == "long_run":
            title = "Aerobic Endurance Long Run"
            intensity = "easy_steady"
            target_pace = easy_pace_str
            description = (
                f"Maintain a relaxed, rhythmic effort throughout ({easy_pace_str}). "
                f"Focus on relaxed breathing and light cadence."
            )
            rationale = f"Primary cardiovascular stimulus. Keeps volume proportional to current CTL ({ctl:.1f})."
        elif session_type == "recovery_run":
            title = "Active Recovery Jog"
            intensity = "very_easy"
            target_pace = f"{easy_pace_str.split(' to ')[-1] if ' to ' in easy_pace_str else easy_pace_str} (slow)"
            description = "Super comfortable shakeout. Keep heart rate low and muscles loose."
            rationale = "Promotes blood flow and active recovery without creating additional muscular fatigue."
        else:  # easy_run
            title = "Aerobic Base Run"
            intensity = "easy"
            target_pace = easy_pace_str
            description = f"Comfortable conversational effort at {easy_pace_str}. You should be able to speak full sentences."
            rationale = "Builds capillary density and mitochondrial efficiency safely."

        sessions.append({
            "date": session_date.isoformat(),
            "day": day_name,
            "type": session_type,
            "title": title,
            "target_distance_km": session_km,
            "target_pace": target_pace,
            "intensity": intensity,
            "instructions": description,
            "coach_rationale": rationale,
        })

    total_planned_km = round(sum(s["target_distance_km"] for s in sessions), 1)

    return {
        "goal": goal_type,
        "goal_distance_km": goal_dist,
        "target_time_seconds": goal.get("target_time_seconds"),
        "race_date": goal.get("race_date"),
        "week_start": today.isoformat(),
        "weekly_target_km": total_planned_km,
        "vdot": vdot_val,
        "training_load_status": load_status,
        "tsb_form": tsb,
        "readiness_score": readiness_score,
        "readiness_label": readiness_label,
        "coach_focus": coach_focus,
        "sessions": sessions,
        "message": (
            f"Adaptive plan generated using your VDOT ({vdot_val or 'estimated'}) and "
            f"Readiness Score ({readiness_score}/100, form TSB {tsb:+0.1f}). {recommendation}"
        ),
    }


def _call_gemini_for_plan(
    profile: FitnessProfile,
    goal: dict[str, Any],
    today: date,
    user_notes: str | None,
) -> dict[str, Any] | None:
    """Call Google Gemini API using structured JSON schema."""
    llm_profile = fitness_profile_for_llm(profile)

    system_instruction = (
        "You are an elite, science-grounded running coach following the training methodologies "
        "of Jack Daniels (VDOT, physiological pace zones) and Eric Banister (training load, CTL/ATL/TSB). "
        "Your role is to produce a realistic, personalized 1-week training schedule for a runner "
        "based strictly on their quantitative fitness profile and goal. "
        "Output ONLY valid JSON adhering strictly to the requested schema."
    )

    prompt = f"""
Runner Profile:
{json.dumps(llm_profile, indent=2)}

Goal Information:
{json.dumps(goal, indent=2)}

Reference Week Start Date: {today.isoformat()}
Runner Notes: {user_notes or 'None provided'}

Generate a structured weekly training plan following these rules:
1. Every session must be on one of the runner's available training days: {goal.get('training_days')}.
2. Use the runner's exact calculated pace zones for target_pace where applicable (e.g. easy, tempo, interval).
3. If readiness score is below 50 or status is 'overreaching', prioritize recovery and reduce volume.
4. If status is 'optimal' or 'fresh', include appropriate quality work suited to their goal.
5. Provide a clear coaching rationale for every session explaining why it fits today's physiological state.

Return a JSON object with this exact structure:
{{
  "week_start": "{today.isoformat()}",
  "weekly_target_km": float,
  "coach_focus": "string summary of the week's training intent",
  "sessions": [
    {{
      "date": "YYYY-MM-DD",
      "day": "DayName",
      "type": "easy_run | tempo_run | interval_run | long_run | recovery_run",
      "title": "Short title",
      "target_distance_km": float,
      "target_pace": "e.g. 5:05 /km",
      "intensity": "easy | controlled | hard",
      "instructions": "Specific guidance for the runner",
      "coach_rationale": "Why this workout was assigned based on readiness/load"
    }}
  ],
  "message": "Friendly motivational coaching summary for the week"
}}
"""

    url = GEMINI_API_URL.format(model=GEMINI_MODEL)
    params = {"key": GEMINI_API_KEY}
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]}
        ],
        "systemInstruction": {
            "parts": [{"text": system_instruction}]
        },
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }

    start_time = time.monotonic()
    with httpx.Client(timeout=25.0) as client:
        response = client.post(url, params=params, json=payload)
        response.raise_for_status()
        data = response.json()
    latency_ms = (time.monotonic() - start_time) * 1000

    candidates = data.get("candidates", [])
    if not candidates:
        return None

    raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    if not raw_text:
        return None

    parsed = json.loads(raw_text)
    goal_type = goal.get("goal_type", "5k").strip().lower()
    parsed["goal"] = goal_type
    parsed["goal_distance_km"] = DISTANCE_KM.get(goal_type, 5.0)
    parsed["target_time_seconds"] = goal.get("target_time_seconds")
    parsed["race_date"] = goal.get("race_date")
    parsed["vdot"] = profile.vdot.get("estimated_vdot")
    parsed["training_load_status"] = profile.training_load.get("status")
    parsed["readiness_score"] = profile.readiness.get("score")

    # Audit log
    audit_log_llm_interaction(
        endpoint="/training/plan",
        prompt=prompt,
        response=parsed,
        model=GEMINI_MODEL,
        latency_ms=latency_ms,
    )

    return parsed


def answer_coaching_query(
    profile: FitnessProfile,
    query: str,
) -> dict[str, str]:
    """Answer a runner's coaching question grounded in their real ML metrics.

    Uses RAG to retrieve relevant past workouts from the vector store,
    injecting them into the LLM prompt for data-grounded responses.
    """
    llm_profile = fitness_profile_for_llm(profile)

    # Retrieve relevant training history via RAG
    rag_context = build_rag_context(query, n_results=5)
    retrieved_runs = retrieve_relevant_runs(query, n_results=5)

    if not GEMINI_API_KEY:
        vdot = profile.vdot.get("estimated_vdot") or "N/A"
        readiness = profile.readiness.get("score") or "N/A"
        label = profile.readiness.get("label", "unknown")
        status = profile.training_load.get("status", "unknown")
        trend = profile.pace_trend.get("direction", "stable")
        pred = profile.race_prediction

        advice = (
            f"Based on your current training data: your VDOT is {vdot}, with a pace trend of {trend}. "
            f"Today's readiness score is {readiness}/100 ({label}), with a training load status of '{status}'. "
        )
        if pred:
            advice += f"For your {pred.get('goal_name')} goal, your readiness is {pred.get('probability_label')} ({pred.get('assessment')})."

        return {
            "answer": advice,
            "source": "ml_engine",
            "rag_context_used": bool(rag_context),
            "relevant_runs_retrieved": len(retrieved_runs),
        }

    system_instruction = (
        "You are an encouraging, expert running coach. Answer the runner's question "
        "referencing their specific numbers: VDOT, training load (CTL/ATL/TSB), readiness score, "
        "and pace zones. When relevant training history is provided, reference specific past "
        "workouts to make your advice concrete and personalized. "
        "Keep advice practical, supportive, and under 200 words."
    )

    # Build prompt with RAG context
    prompt_parts = [
        f"Runner ML Profile:\n{json.dumps(llm_profile, indent=2)}",
    ]
    if rag_context:
        prompt_parts.append(f"\n{rag_context}")
    prompt_parts.append(f"\nRunner Question:\n{query}")
    full_prompt = "\n".join(prompt_parts)

    url = GEMINI_API_URL.format(model=GEMINI_MODEL)
    params = {"key": GEMINI_API_KEY}
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": full_prompt}],
            }
        ],
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "generationConfig": {"temperature": 0.4},
    }

    try:
        start_time = time.monotonic()
        with httpx.Client(timeout=15.0) as client:
            res = client.post(url, params=params, json=payload)
            res.raise_for_status()
            text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        latency_ms = (time.monotonic() - start_time) * 1000

        # Audit log
        audit_log_llm_interaction(
            endpoint="/coaching/ask",
            prompt=full_prompt,
            response=text,
            model=GEMINI_MODEL,
            latency_ms=latency_ms,
        )

        return {
            "answer": text.strip(),
            "source": "gemini_ai",
            "rag_context_used": bool(rag_context),
            "relevant_runs_retrieved": len(retrieved_runs),
        }
    except Exception as exc:
        logger.error("Coaching query failed: %s", exc)
        return {
            "answer": f"Your current readiness score is {profile.readiness.get('score')}/100 and status is '{profile.training_load.get('status')}'. Listen to your body and adjust effort accordingly.",
            "source": "fallback",
            "rag_context_used": False,
            "relevant_runs_retrieved": 0,
        }
