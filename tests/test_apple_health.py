import io
import unittest
import zipfile
from datetime import datetime, timezone

from app.analytics import build_fitness_profile
from app.apple_health import parse_apple_health_upload, parse_health_xml

SAMPLE_XML = b'''<?xml version="1.0"?>
<HealthData locale="en_US">
  <Record type="HKQuantityTypeIdentifierVO2Max" sourceName="Watch" unit="ml/kg/min" startDate="2026-10-01 06:00:00 -0700" value="47.2" />
  <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="30" durationUnit="min" totalDistance="5" totalDistanceUnit="km" totalEnergyBurned="300" totalEnergyBurnedUnit="kcal" sourceName="Watch" startDate="2026-10-10 07:00:00 -0700" endDate="2026-10-10 07:30:00 -0700">
    <WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate" average="150" minimum="120" maximum="175" unit="count/min" />
  </Workout>
  <Workout workoutActivityType="HKWorkoutActivityTypeCycling" duration="40" durationUnit="min" sourceName="Watch" startDate="2026-10-11 07:00:00 -0700" endDate="2026-10-11 07:40:00 -0700" />
</HealthData>'''


class AppleHealthParserTests(unittest.TestCase):
    def test_parses_runs_and_vo2_but_ignores_other_workouts(self):
        result = parse_health_xml(io.BytesIO(SAMPLE_XML))
        self.assertEqual(len(result.workouts), 1)
        self.assertEqual(result.ignored_workouts, 1)
        self.assertEqual(len(result.health_metrics), 1)
        run = result.workouts[0]
        self.assertEqual(run["distance_m"], 5000)
        self.assertEqual(run["duration_s"], 1800)
        self.assertEqual(run["average_heartrate"], 150)
        self.assertEqual(run["minimum_heartrate"], 120)
        self.assertEqual(run["max_heartrate"], 175)
        self.assertTrue(run["start_date"].endswith("Z"))
        self.assertEqual(result.health_metrics[0]["value"], 47.2)

    def test_keeps_records_after_many_prior_records(self):
        records = "\n".join(
            f'<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" unit="count/min" startDate="2026-10-01 06:{i % 60:02d}:00 -0700" value="120" />'
            for i in range(80)
        )
        xml_text = (
            '<?xml version="1.0"?><HealthData locale="en_US">'
            + records
            + '<Record type="HKQuantityTypeIdentifierVO2Max" sourceName="Watch" unit="ml/kg/min" startDate="2026-10-15 06:00:00 -0700" value="49.1" />'
            + '<Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="30" durationUnit="min" totalDistance="5" totalDistanceUnit="km" sourceName="Watch" startDate="2026-10-15 07:00:00 -0700" endDate="2026-10-15 07:30:00 -0700" />'
            + '</HealthData>'
        )
        result = parse_health_xml(io.BytesIO(xml_text.encode()))
        self.assertEqual(len(result.workouts), 1)
        self.assertEqual(len(result.health_metrics), 1)

    def test_accepts_zip_export(self):
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("apple_health_export/export.xml", SAMPLE_XML)
        zipped.seek(0)
        result = parse_apple_health_upload(zipped, max_xml_bytes=1_000_000)
        self.assertEqual(len(result.workouts), 1)
        self.assertEqual(len(result.health_metrics), 1)

    def test_profile_calculations(self):
        now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
        activities = [
            {
                "type": "Running",
                "start_date": "2026-10-10T15:00:00Z",
                "distance_m": 10000,
                "duration_s": 3600,
                "average_heartrate": 155,
            },
            {
                "type": "Running",
                "start_date": "2026-10-13T15:00:00Z",
                "distance_m": 5000,
                "duration_s": 1800,
                "average_heartrate": 145,
            },
        ]
        metrics = [
            {"metric_type": "vo2_max", "value": 47.2, "unit": "ml/kg/min", "measured_at": "2026-10-12T00:00:00Z", "source_name": "Watch"}
        ]
        profile = build_fitness_profile(activities, metrics, days=28, now=now)
        self.assertEqual(profile["runs_in_period"], 2)
        self.assertEqual(profile["weekly_distance_km_last_7_days"], 15.0)
        self.assertEqual(profile["longest_run_km"], 10.0)
        self.assertEqual(profile["average_run_pace"], "6:00 min/km")
        self.assertEqual(profile["vo2_max_latest"]["value"], 47.2)
        self.assertEqual(profile["confidence"], "low")


if __name__ == "__main__":
    unittest.main()
