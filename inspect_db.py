#!/usr/bin/env python3
"""Quick CLI tool to inspect the local SQLite database."""

import sqlite3
import sys
from datetime import datetime

DB_PATH = "running_coach.db"

def inspect():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
    except Exception as e:
        print(f"Error opening {DB_PATH}: {e}")
        return

    print("=" * 65)
    print(" 🏃 RUNNING COACH DATABASE SUMMARY")
    print("=" * 65)

    # 1. Table Counts
    for table in ["activities", "health_metrics", "running_goals"]:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            cnt = cur.fetchone()[0]
            print(f" • Table '{table}': {cnt:,} rows")
        except Exception:
            print(f" • Table '{table}': (not created)")

    # 2. Date Range for Activities
    try:
        cur.execute("SELECT MIN(start_date), MAX(start_date), SUM(distance_m) FROM activities")
        first_date, last_date, total_m = cur.fetchone()
        if first_date and last_date:
            total_km = round((total_m or 0) / 1000, 1)
            print(f"\n 📅 Running History: {first_date[:10]} to {last_date[:10]} ({total_km:,} km total)")
    except Exception:
        pass

    # 3. Recent Workouts
    print("\n" + "=" * 65)
    print(" 🏁 LATEST 10 RUNS IN DATABASE")
    print("=" * 65)
    cur.execute("""
        SELECT name, start_date, distance_m, duration_s, average_heartrate, max_heartrate, source_name
        FROM activities
        ORDER BY start_date DESC
        LIMIT 10
    """)
    rows = cur.fetchall()
    if not rows:
        print(" (No activities found)")
    else:
        print(f"{'Date':<14} {'Distance':<10} {'Time':<8} {'Pace':<11} {'HR (Avg/Max)':<12} {'Source'}")
        print("-" * 85)
        for r in rows:
            raw_s = r["start_date"]
            dt = raw_s[:10] if raw_s else "Unknown"
            km = (r["distance_m"] or 0) / 1000

            dist_str = f"{km:.2f} km" if km > 0 else "—"

            dur_s = int(r["duration_s"] or 0)
            m, s = divmod(dur_s, 60)
            h, m = divmod(m, 60)
            dur_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"
            
            # Pace
            if km > 0 and dur_s > 0:
                pace_s = dur_s / km
                pm, ps = divmod(int(pace_s), 60)
                pace_str = f"{pm}:{ps:02d} /km"
            else:
                pace_str = "—"

            avg_hr = int(r["average_heartrate"]) if r["average_heartrate"] else "—"
            max_hr = int(r["max_heartrate"]) if r["max_heartrate"] else "—"
            hr_str = f"{avg_hr}/{max_hr} bpm" if avg_hr != "—" else "—"
            src = (r["source_name"] or "Apple Health")[:18]

            print(f"{dt:<18} {dist_str:<10} {dur_str:<8} {pace_str:<11} {hr_str:<12} {src}")

    # 4. Recent Health Metrics (VO2 Max)
    print("\n" + "=" * 65)
    print(" 🫀 LATEST VO2 MAX RECORDS")
    print("=" * 65)
    cur.execute("""
        SELECT measured_at, value, unit, source_name
        FROM health_metrics
        WHERE metric_type = 'vo2_max'
        ORDER BY measured_at DESC
        LIMIT 5
    """)
    metrics = cur.fetchall()
    if not metrics:
        print(" (No VO2 max samples found)")
    else:
        for m in metrics:
            dt = m["measured_at"][:10]
            val = m["value"]
            unit = m["unit"] or "ml/kg/min"
            src = m["source_name"] or "Apple Watch"
            print(f" • {dt}: {val:.1f} {unit} ({src})")

    # 5. Current Goal
    print("\n" + "=" * 65)
    print(" 🎯 CURRENT SAVED GOAL")
    print("=" * 65)
    cur.execute("SELECT goal_type, target_time_seconds, race_date, training_days_json FROM running_goals ORDER BY id DESC LIMIT 1")
    g = cur.fetchone()
    if not g:
        print(" (No goal saved yet)")
    else:
        target_s = g["target_time_seconds"]
        if target_s:
            tm, ts = divmod(target_s, 60)
            th, tm = divmod(tm, 60)
            t_str = f"{th}:{tm:02d}:{ts:02d}" if th > 0 else f"{tm}:{ts:02d}"
        else:
            t_str = "Not set"
        print(f" • Target Event: {g['goal_type'].upper()}")
        print(f" • Target Time:  {t_str}")
        print(f" • Race Date:    {g['race_date'] or 'Not set'}")
        print(f" • Training Days:{g['training_days_json']}")
    print("=" * 65 + "\n")

    conn.close()

if __name__ == "__main__":
    inspect()
