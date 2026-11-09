import unittest
from datetime import datetime, timezone

from app.ml.vdot import calculate_vdot, predict_race_time
from app.ml.profile import build_ml_fitness_profile
from app.ai.coach import generate_ai_training_plan, answer_coaching_query


class MLCoachTests(unittest.TestCase):
    def test_daniels_vdot_and_prediction(self):
        vdot = calculate_vdot(5000, 1500)  # 25:00 5k
        self.assertIsNotNone(vdot)
        self.assertAlmostEqual(vdot, 38.31, places=1)

        pred_5k = predict_race_time(vdot, 5000)
        self.assertIsNotNone(pred_5k)
        self.assertAlmostEqual(pred_5k, 1500, delta=10)

        pred_10k = predict_race_time(vdot, 10000)
        self.assertIsNotNone(pred_10k)
        self.assertTrue(3000 < pred_10k < 3200)

    def test_adaptive_plan_generation(self):
        now = datetime.now(timezone.utc)
        runs = [
            {
                "id": f"test_run_{i}",
                "source": "apple_health",
                "name": f"Run {i}",
                "type": "Running",
                "start_date": (now).isoformat().replace("+00:00", "Z"),
                "end_date": (now).isoformat().replace("+00:00", "Z"),
                "distance_m": 5000,
                "duration_s": 1500,
                "average_heartrate": 150,
                "energy_kcal": 300,
            }
            for i in range(5)
        ]
        goal = {
            "goal_type": "5k",
            "target_time_seconds": 1440,
            "training_days": ["Tuesday", "Thursday", "Saturday"],
        }
        profile = build_ml_fitness_profile(runs, [], goal=goal, now=now)
        plan = generate_ai_training_plan(profile, goal, today=now.date())

        self.assertIn("sessions", plan)
        self.assertEqual(len(plan["sessions"]), 3)
        self.assertTrue(plan["weekly_target_km"] > 0)
        for s in plan["sessions"]:
            self.assertIn("target_pace", s)
            self.assertIn("coach_rationale", s)

    def test_coaching_query_fallback(self):
        now = datetime.now(timezone.utc)
        profile = build_ml_fitness_profile([], [], now=now)
        res = answer_coaching_query(profile, "How is my fatigue today?")
        self.assertIn("answer", res)
        self.assertTrue(len(res["answer"]) > 10)


if __name__ == "__main__":
    unittest.main()
