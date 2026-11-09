"""Tests for the three new AI/ML upgrades:
1. XGBoost pace prediction model
2. RAG-augmented coaching
3. LLM guardrails
"""

import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import asdict

from app.ml.pace_predictor import (
    _engineer_features,
    _build_dataset,
    _format_pace,
    FEATURE_NAMES,
)
from app.ai.rag import (
    _activity_to_document,
    _format_pace_str,
)
from app.ai.guardrails import (
    validate_plan_schema,
    check_volume_safety,
    check_pace_validity,
    check_plan_consistency,
    run_guardrails,
    auto_correct_plan,
    _parse_pace_string,
)


def _make_runs(count: int = 15, base_pace: float = 330.0, base_hr: float = 150.0) -> list[dict]:
    """Generate a series of realistic running activities for testing."""
    now = datetime.now(timezone.utc)
    runs = []
    for i in range(count):
        run_date = now - timedelta(days=count - i)
        distance_m = 5000 + (i % 3) * 1000  # 5k, 6k, 7k pattern
        pace_variation = (i % 5 - 2) * 5  # ±10 sec/km variation
        pace = base_pace + pace_variation
        duration_s = pace * (distance_m / 1000.0)
        hr = base_hr + (i % 4 - 1) * 5  # ±5 bpm variation

        runs.append({
            "id": f"test_run_{i}",
            "source": "apple_health",
            "name": f"Run {i}",
            "type": "Running",
            "start_date": run_date.isoformat().replace("+00:00", "Z"),
            "end_date": (run_date + timedelta(seconds=duration_s)).isoformat().replace("+00:00", "Z"),
            "distance_m": distance_m,
            "duration_s": duration_s,
            "average_heartrate": hr,
            "max_heartrate": hr + 20,
            "energy_kcal": distance_m * 0.06,
            "source_name": "Garmin Connect",
        })
    return runs


class TestXGBoostPacePredictor(unittest.TestCase):
    """Test the XGBoost-based pace prediction system."""

    def test_feature_engineering(self):
        """Features should be computed from prior history without leakage."""
        runs = _make_runs(15)
        # Sort chronologically
        sorted_runs = sorted(runs, key=lambda r: r["start_date"])

        # First few runs should return None (insufficient history)
        features = _engineer_features(sorted_runs, 2)
        self.assertIsNone(features)

        # Later runs should produce valid features
        features = _engineer_features(sorted_runs, 10)
        self.assertIsNotNone(features)
        self.assertEqual(set(features.keys()), set(FEATURE_NAMES))

        # Check feature values are reasonable
        self.assertGreater(features["rolling_pace_7d"], 150)
        self.assertLess(features["rolling_pace_7d"], 600)
        self.assertGreaterEqual(features["days_since_last_run"], 0)
        self.assertIn(features["day_of_week"], range(7))

    def test_build_dataset(self):
        """Dataset should have correct dimensions and no NaN values."""
        runs = _make_runs(20)
        X, y, feat_dicts = _build_dataset(runs)

        self.assertGreater(len(X), 0)
        self.assertEqual(len(X), len(y))
        self.assertEqual(len(X), len(feat_dicts))
        self.assertEqual(X.shape[1], len(FEATURE_NAMES))

        # All targets should be valid pace values
        for pace in y:
            self.assertGreater(pace, 150)
            self.assertLess(pace, 600)

    def test_format_pace(self):
        self.assertEqual(_format_pace(330.0), "5:30 /km")
        self.assertEqual(_format_pace(300.0), "5:00 /km")
        self.assertEqual(_format_pace(265.0), "4:25 /km")

    def test_insufficient_data(self):
        """Should return empty dataset with too few runs."""
        runs = _make_runs(3)
        X, y, _ = _build_dataset(runs)
        self.assertEqual(len(X), 0)


class TestRAG(unittest.TestCase):
    """Test RAG document creation and formatting."""

    def test_activity_to_document(self):
        """Activities should be converted to natural-language documents."""
        activity = {
            "id": "test_1",
            "type": "Running",
            "start_date": "2026-10-20T08:00:00Z",
            "distance_m": 8000,
            "duration_s": 2400,
            "average_heartrate": 155,
            "max_heartrate": 175,
            "source": "apple_health",
            "source_name": "Garmin Connect",
        }
        result = _activity_to_document(activity)
        self.assertIsNotNone(result)

        doc, meta = result
        self.assertIn("8.0 km", doc)
        self.assertIn("155 bpm", doc)
        self.assertIn("5:00/km", doc)
        self.assertEqual(meta["distance_km"], 8.0)
        self.assertEqual(meta["avg_hr"], 155.0)
        self.assertIn("moderate", meta["effort"])

    def test_non_running_activity_skipped(self):
        """Non-running activities should return None."""
        activity = {"type": "Cycling", "distance_m": 5000, "duration_s": 1200,
                     "start_date": "2026-10-20T08:00:00Z"}
        result = _activity_to_document(activity)
        self.assertIsNone(result)

    def test_format_pace_str(self):
        self.assertEqual(_format_pace_str(330.0), "5:30/km")
        self.assertEqual(_format_pace_str(300.0), "5:00/km")


class TestGuardrails(unittest.TestCase):
    """Test LLM output validation and guardrails."""

    def _make_valid_plan(self) -> dict:
        return {
            "week_start": "2026-10-21",
            "weekly_target_km": 30.0,
            "coach_focus": "Build aerobic base",
            "sessions": [
                {
                    "date": "2026-10-21",
                    "day": "Monday",
                    "type": "easy_run",
                    "title": "Easy Run",
                    "target_distance_km": 8.0,
                    "target_pace": "5:30 /km",
                    "intensity": "easy",
                    "instructions": "Keep it conversational",
                    "coach_rationale": "Aerobic base building",
                },
                {
                    "date": "2026-10-23",
                    "day": "Wednesday",
                    "type": "tempo_run",
                    "title": "Threshold Tempo",
                    "target_distance_km": 10.0,
                    "target_pace": "4:50 /km",
                    "intensity": "moderate_hard",
                    "instructions": "Warm up 2km, 6km at tempo, cool down 2km",
                    "coach_rationale": "Lactate threshold development",
                },
                {
                    "date": "2026-10-25",
                    "day": "Friday",
                    "type": "long_run",
                    "title": "Aerobic Long Run",
                    "target_distance_km": 12.0,
                    "target_pace": "5:40 /km",
                    "intensity": "easy_steady",
                    "instructions": "Relaxed, steady effort",
                    "coach_rationale": "Cardiovascular endurance",
                },
            ],
            "message": "Solid week of training ahead!",
        }

    def test_valid_plan_passes_schema(self):
        """A well-formed plan should have no schema violations."""
        plan = self._make_valid_plan()
        violations = validate_plan_schema(plan)
        self.assertEqual(len(violations), 0)

    def test_invalid_session_type_caught(self):
        """Unknown session types should be flagged."""
        plan = self._make_valid_plan()
        plan["sessions"][0]["type"] = "sprint_race"
        violations = validate_plan_schema(plan)
        self.assertTrue(any(v.category == "schema" for v in violations))

    def test_volume_ramp_warning(self):
        """Volume increases >10% should trigger a warning."""
        plan = self._make_valid_plan()
        plan["weekly_target_km"] = 40.0  # Big jump from 25 km baseline
        violations = check_volume_safety(plan, current_weekly_km=25.0)
        self.assertTrue(any("volume" in v.message.lower() or "higher" in v.message.lower()
                           for v in violations))

    def test_safe_volume_passes(self):
        """Moderate volume increase should pass."""
        plan = self._make_valid_plan()
        plan["weekly_target_km"] = 27.0  # 8% increase from 25
        # Scale session distances to stay under 40% long-run ratio
        plan["sessions"][0]["target_distance_km"] = 7.0
        plan["sessions"][1]["target_distance_km"] = 10.0
        plan["sessions"][2]["target_distance_km"] = 10.0
        violations = check_volume_safety(plan, current_weekly_km=25.0)
        self.assertEqual(len(violations), 0)

    def test_hallucinated_pace_caught(self):
        """Unrealistically fast paces for the athlete's VDOT should be flagged."""
        plan = self._make_valid_plan()
        plan["sessions"][0]["target_pace"] = "2:30 /km"  # Faster than world record
        violations = check_pace_validity(plan, {}, vdot=40.0)
        self.assertTrue(any(v.category == "hallucination" for v in violations))

    def test_readiness_consistency(self):
        """Hard sessions with low readiness should be flagged."""
        plan = self._make_valid_plan()
        violations = check_plan_consistency(plan, goal=None, readiness_score=30)
        self.assertTrue(any("readiness" in v.message.lower() for v in violations))

    def test_run_all_guardrails(self):
        """The master guardrail runner should produce a complete result."""
        plan = self._make_valid_plan()
        result = run_guardrails(
            plan=plan,
            current_weekly_km=28.0,
            vdot=42.0,
            readiness_score=75,
        )
        self.assertIsInstance(result.is_safe, bool)
        self.assertIsNotNone(result.violations)
        self.assertGreater(result.validation_time_ms, 0)

    def test_auto_correction(self):
        """Auto-correction should downgrade hard sessions when readiness is low."""
        plan = self._make_valid_plan()
        from app.ai.guardrails import GuardrailViolation
        violations = [
            GuardrailViolation(
                category="safety",
                severity="warning",
                field="sessions",
                message="readiness score below safe threshold",
            ),
        ]
        corrected = auto_correct_plan(plan, violations, 25.0, {})
        # Tempo run should be downgraded
        tempo_sessions = [s for s in corrected["sessions"] if s["type"] == "tempo_run"]
        self.assertEqual(len(tempo_sessions), 0)

    def test_parse_pace_string(self):
        self.assertEqual(_parse_pace_string("5:30 /km"), 330)
        self.assertEqual(_parse_pace_string("4:00 /km"), 240)
        self.assertEqual(_parse_pace_string("5:30 to 6:00 /km"), 330)
        self.assertIsNone(_parse_pace_string("invalid"))


if __name__ == "__main__":
    unittest.main()
