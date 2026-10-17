"""SQLite persistence for Apple Health workouts and selected health metrics."""

import sqlite3
import json
from contextlib import contextmanager
from typing import Any

from app.config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'apple_health',
    name TEXT,
    type TEXT,
    start_date TEXT NOT NULL,
    end_date TEXT,
    distance_m REAL,
    duration_s REAL,
    average_heartrate REAL,
    max_heartrate REAL,
    energy_kcal REAL,
    minimum_heartrate REAL,
    source_name TEXT,
    synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS health_metrics (
    id TEXT PRIMARY KEY,
    metric_type TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    measured_at TEXT NOT NULL,
    source_name TEXT,
    synced_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_activities_start_date
    ON activities(start_date);
CREATE INDEX IF NOT EXISTS idx_health_metrics_type_date
    ON health_metrics(metric_type, measured_at);

CREATE TABLE IF NOT EXISTS running_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_type TEXT NOT NULL,
    target_time_seconds INTEGER,
    race_date TEXT,
    training_days_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


@contextmanager
def get_conn():
    """Open a connection and reliably commit or roll back the transaction."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables and migrate columns from the earlier Strava prototype."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)

        # Keep existing local databases usable if this project was previously
        # run with the Strava version. SQLite does not add columns via CREATE IF NOT EXISTS.
        existing_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(activities)").fetchall()
        }
        migrations = {
            "minimum_heartrate": "REAL",
            "source_name": "TEXT",
        }
        for column, sql_type in migrations.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE activities ADD COLUMN {column} {sql_type}")


def upsert_activities(activities: list[dict[str, Any]], synced_at: str) -> None:
    """Insert workouts, updating an existing row when its stable ID matches."""
    if not activities:
        return
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO activities (
                id, source, name, type, start_date, end_date, distance_m,
                duration_s, average_heartrate, max_heartrate, energy_kcal,
                synced_at, minimum_heartrate, source_name
            ) VALUES (
                :id, :source, :name, :type, :start_date, :end_date, :distance_m,
                :duration_s, :average_heartrate, :max_heartrate, :energy_kcal,
                :synced_at, :minimum_heartrate, :source_name
            )
            ON CONFLICT(id) DO UPDATE SET
                source = excluded.source,
                name = excluded.name,
                type = excluded.type,
                start_date = excluded.start_date,
                end_date = excluded.end_date,
                distance_m = excluded.distance_m,
                duration_s = excluded.duration_s,
                average_heartrate = excluded.average_heartrate,
                max_heartrate = excluded.max_heartrate,
                minimum_heartrate = excluded.minimum_heartrate,
                energy_kcal = excluded.energy_kcal,
                source_name = excluded.source_name,
                synced_at = excluded.synced_at
            """,
            [
                {
                    **activity,
                    "synced_at": synced_at,
                    "minimum_heartrate": activity.get("minimum_heartrate"),
                    "source_name": activity.get("source_name"),
                }
                for activity in activities
            ],
        )


def upsert_health_metrics(metrics: list[dict[str, Any]], synced_at: str) -> None:
    """Insert or update selected health metric samples such as VO2 max."""
    if not metrics:
        return
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO health_metrics (
                id, metric_type, value, unit, measured_at, source_name, synced_at
            ) VALUES (
                :id, :metric_type, :value, :unit, :measured_at, :source_name, :synced_at
            )
            ON CONFLICT(id) DO UPDATE SET
                metric_type = excluded.metric_type,
                value = excluded.value,
                unit = excluded.unit,
                measured_at = excluded.measured_at,
                source_name = excluded.source_name,
                synced_at = excluded.synced_at
            """,
            [{**metric, "synced_at": synced_at} for metric in metrics],
        )


def list_activities(limit: int = 100, since: str | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if since:
            rows = conn.execute(
                "SELECT * FROM activities WHERE start_date >= ? ORDER BY start_date DESC LIMIT ?",
                (since, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM activities ORDER BY start_date DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]


def list_health_metrics(limit: int = 100, metric_type: str | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if metric_type:
            rows = conn.execute(
                "SELECT * FROM health_metrics WHERE metric_type = ? ORDER BY measured_at DESC LIMIT ?",
                (metric_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM health_metrics ORDER BY measured_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]


def count_activities() -> int:
    with get_conn() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0])


def count_health_metrics() -> int:
    with get_conn() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM health_metrics").fetchone()[0])


def save_running_goal(goal: dict[str, Any]) -> dict[str, Any]:
    """Keep the latest goal as the active goal for this single-user MVP."""
    with get_conn() as conn:
        conn.execute("DELETE FROM running_goals")
        cursor = conn.execute(
            """INSERT INTO running_goals (goal_type, target_time_seconds, race_date, training_days_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (goal["goal_type"], goal.get("target_time_seconds"), goal.get("race_date"),
             json.dumps(goal["training_days"]), goal["created_at"]),
        )
        saved = dict(goal)
        saved["id"] = cursor.lastrowid
        return saved


def get_running_goal() -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM running_goals ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        goal = dict(row)
        goal["training_days"] = json.loads(goal.pop("training_days_json"))
        return goal
