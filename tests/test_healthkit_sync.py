import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app import db, main


class HealthKitSyncEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DATABASE_PATH
        self.original_token = main.SYNC_API_TOKEN
        db.DATABASE_PATH = str(Path(self.tmp.name) / "test.db")
        main.SYNC_API_TOKEN = "unit-test-token"
        db.init_db()

    def tearDown(self):
        db.DATABASE_PATH = self.original_db_path
        main.SYNC_API_TOKEN = self.original_token
        self.tmp.cleanup()

    def test_sync_is_idempotent_and_normalizes_dates(self):
        payload = main.HealthKitWorkoutBatch(workouts=[
            main.HealthKitWorkout(
                id="healthkit_abc-123",
                start_date=datetime(2026, 10, 10, 7, 0, tzinfo=timezone.utc),
                end_date=datetime(2026, 10, 10, 7, 30, tzinfo=timezone.utc),
                distance_m=5000,
                duration_s=1800,
                energy_kcal=300,
                source_name="Apple Watch",
            )
        ])

        first = main.sync_healthkit_workouts(payload, authorization="Bearer unit-test-token")
        second = main.sync_healthkit_workouts(payload, authorization="Bearer unit-test-token")
        rows = db.list_activities(limit=100)

        self.assertEqual(first["workouts_processed"], 1)
        self.assertEqual(second["workouts_processed"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "healthkit_abc-123")
        self.assertEqual(rows[0]["source"], "apple_healthkit")
        self.assertTrue(rows[0]["start_date"].endswith("Z"))
        self.assertEqual(rows[0]["distance_m"], 5000)

    def test_rejects_invalid_token(self):
        payload = main.HealthKitWorkoutBatch(workouts=[])
        with self.assertRaises(Exception) as context:
            main.sync_healthkit_workouts(payload, authorization="Bearer wrong-token")
        self.assertEqual(getattr(context.exception, "status_code", None), 401)


if __name__ == "__main__":
    unittest.main()
