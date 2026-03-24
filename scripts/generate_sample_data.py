#!/usr/bin/env python3
"""Generate synthetic sample data for all CSV data sources.

Creates realistic 14-day sample data in data/sample/ that mirrors the real
data schemas. Run this to regenerate sample data after schema changes.
"""
import csv
import os
from datetime import date, timedelta


def _write_csv(path: str, rows: list[dict]) -> None:
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def generate(output_dir: str) -> None:
    """Generate all sample CSV files in output_dir."""
    # Use a fixed base date so sample data is deterministic
    base_date = date(2026, 3, 1)

    # --- Garmin activities (14 days) ---
    activities = []
    for i in range(14):
        d = base_date + timedelta(days=i)
        activities.append({
            "activity_id": str(9000 + i),
            "date": d.isoformat(),
            "start_time": f"{d.isoformat()} 07:00:00",
            "activity_type": "running",
            "distance_km": str(round(8 + (i % 5) * 2, 1)),
            "duration_sec": str(3000 + i * 120),
            "avg_pace_min_km": f"{5 + i % 3}:{(i * 7) % 60:02d}",
            "avg_hr": str(140 + i % 10),
            "max_hr": str(165 + i % 10),
            "elevation_gain_m": str(50 + i * 5),
            "avg_cadence": str(170 + i % 5),
            "calories": str(600 + i * 30),
            "aerobic_te": str(round(3.0 + (i % 5) * 0.4, 1)),
            "anaerobic_te": str(round(0.5 + (i % 3) * 0.5, 1)),
            "hr_zone1_sec": str(60 + i * 10),
            "hr_zone2_sec": str(600 + i * 30),
            "hr_zone3_sec": str(800 + i * 20),
            "hr_zone4_sec": str(400 + i * 15),
            "hr_zone5_sec": str(100 + i * 5),
        })
    _write_csv(os.path.join(output_dir, "garmin", "activities.csv"), activities)

    # --- Garmin activity splits ---
    splits = []
    for i in range(14):
        act_id = str(9000 + i)
        # 3-5 splits per activity
        n_splits = 3 + i % 3
        for s in range(n_splits):
            is_work = s > 0 and s < n_splits - 1  # middle splits are "work"
            base_power = 245 + i * 2 if is_work else 185 + i
            splits.append({
                "activity_id": act_id,
                "split_num": str(s + 1),
                "distance_km": str(round(1.5 + s * 0.5, 2)),
                "duration_sec": str(360 + s * 60),
                "avg_pace_min_km": f"{4 + s % 2}:{(s * 15) % 60:02d}",
                "avg_hr": str(135 + s * 8),
                "max_hr": str(155 + s * 6),
                "avg_cadence": str(168 + s * 2),
                "elevation_change_m": str(round(-2 + s * 1.5, 1)),
                "avg_power": str(round(base_power + s * 3, 1)),
            })
    _write_csv(os.path.join(output_dir, "garmin", "activity_splits.csv"), splits)

    # --- Garmin daily metrics ---
    daily_metrics = []
    for i in range(5):
        d = base_date + timedelta(days=i + 9)
        daily_metrics.append({
            "date": d.isoformat(),
            "vo2max": str(round(50 + i * 0.2, 1)),
            "training_status": "productive",
            "resting_hr": str(48 + i % 3),
        })
    _write_csv(os.path.join(output_dir, "garmin", "daily_metrics.csv"), daily_metrics)

    # --- Stryd power data ---
    stryd_types = ["easy", "recovery", "tempo", "threshold", "easy"]
    surfaces = ["road", "road", "trail", "road", "trail"]
    power_data = []
    for i in range(14):
        d = base_date + timedelta(days=i)
        power_data.append({
            "date": d.isoformat(),
            "start_time": f"{d.isoformat()}T07:01:00Z",
            "name": f"Sample Run Day {i + 1}",
            "stryd_type": stryd_types[i % len(stryd_types)],
            "surface_type": surfaces[i % len(surfaces)],
            "avg_power": str(round(220 + i * 2, 1)),
            "max_power": str(round(300 + i * 3, 1)),
            "avg_hr": str(140 + i % 10),
            "max_hr": str(165 + i % 10),
            "avg_cadence": str(170 + i % 5),
            "avg_stride_length": str(round(0.95 + i * 0.01, 3)),
            "avg_oscillation": str(round(6.5 + i * 0.1, 1)),
            "leg_spring_stiffness": str(round(9.5 + i * 0.1, 1)),
            "ground_time_ms": str(215 + i),
            "elevation_gain_m": str(round(20 + i * 3, 1)),
            "avg_speed_ms": str(round(2.7 + i * 0.05, 3)),
            "rss": str(round(65 + i * 3, 1)),
            "lower_body_stress": str(round(60 + i * 2, 1)),
            "cp_estimate": str(round(268 + i * 0.3, 1)),
            "seconds_in_zones": str([2000 + i * 50, 300 + i * 10, 100 + i * 5, 50 + i * 3, 30 + i * 2]),
            "temperature_c": str(round(12 + i * 0.5, 1)),
            "humidity": str(round(0.5 + i * 0.02, 3)),
            "distance_km": str(round(8 + (i % 5) * 2, 1)),
            "duration_sec": str(3000 + i * 120),
        })
    _write_csv(os.path.join(output_dir, "stryd", "power_data.csv"), power_data)

    # --- Stryd training plan ---
    workout_types = ["steady aerobic", "recovery", "tempo", "threshold", "easy"]
    plan_data = []
    for i in range(7):
        d = base_date + timedelta(days=i + 7)
        wt = workout_types[i % len(workout_types)]
        plan_data.append({
            "date": d.isoformat(),
            "workout_type": wt,
            "planned_duration_min": str(45 + i * 5),
            "planned_distance_km": str(round(8 + i * 1.5, 1)),
            "target_power_min": str(200 + i * 5),
            "target_power_max": str(230 + i * 5),
            "workout_description": f"Sample {wt} session",
        })
    _write_csv(os.path.join(output_dir, "stryd", "training_plan.csv"), plan_data)

    # --- Oura sleep ---
    sleep_data = []
    for i in range(14):
        d = base_date + timedelta(days=i)
        sleep_data.append({
            "date": d.isoformat(),
            "sleep_score": str(75 + i % 15),
            "total_sleep_sec": str(25200 + i * 600),
            "deep_sleep_sec": str(5400 + i * 100),
            "rem_sleep_sec": str(5400 + i * 50),
            "light_sleep_sec": str(14400 + i * 200),
            "efficiency": str(85 + i % 10),
        })
    _write_csv(os.path.join(output_dir, "oura", "sleep.csv"), sleep_data)

    # --- Oura readiness ---
    readiness_data = []
    for i in range(14):
        d = base_date + timedelta(days=i)
        readiness_data.append({
            "date": d.isoformat(),
            "readiness_score": str(70 + i % 20),
            "hrv_avg": str(40 + i % 10),
            "resting_hr": str(50 + i % 5),
            "body_temperature_delta": str(round(-0.1 + i * 0.02, 2)),
        })
    _write_csv(os.path.join(output_dir, "oura", "readiness.csv"), readiness_data)


if __name__ == "__main__":
    base = os.path.join(os.path.dirname(__file__), "..", "data", "sample")
    generate(base)
    print(f"Sample data generated in {os.path.abspath(base)}")
