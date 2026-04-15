"""Garmin Connect data parsing — fetch/parse layer for the sync API route."""

RATE_LIMIT_DELAY = 0.5  # seconds between per-activity API calls


def _garmin_speed_to_pace_sec_km(speed_value: float) -> float | None:
    """Convert Garmin LT speed value to pace in sec/km.

    Garmin API returns speed in a unit where typical threshold running
    values are ~0.36-0.42. Based on real data analysis:
    - 0.383 corresponds to roughly 4:21/km (261 sec/km)
    - This matches 1000 / (speed * 10.2) approximately
    - The value appears to be in 10*m/s or a similar Garmin-specific unit

    We store the raw value and compute pace as: 1000 / (speed * factor).
    Factor calibrated so 0.383 ≈ 4:21/km (261s): factor ≈ 10.0
    i.e., speed is in dam/s (decameters per second): 0.383 dam/s = 3.83 m/s
    pace = 1000 / 3.83 = 261 sec/km ≈ 4:21/km ✓
    """
    if not speed_value or speed_value <= 0:
        return None
    # Garmin speed appears to be in dam/s (×10 to get m/s)
    speed_ms = speed_value * 10.0
    if speed_ms <= 0:
        return None
    return round(1000.0 / speed_ms)


def parse_activities(raw_activities: list[dict]) -> list[dict]:
    """Transform Garmin activity list data into our CSV schema.

    Training effect and HR zone data come directly from the activity list
    endpoint (no separate detail call needed).
    """
    rows = []
    for a in raw_activities:
        activity_type = a.get("activityType", {})
        if isinstance(activity_type, dict):
            activity_type = activity_type.get("typeKey", "")
        start_time = a.get("startTimeLocal", "")
        date_str = start_time[:10] if start_time else ""
        distance_m = a.get("distance", 0) or 0
        duration = a.get("duration", 0) or 0

        # Compute avg pace (min/km) from distance and duration
        avg_pace = ""
        if distance_m and duration:
            pace_sec_per_km = duration / (distance_m / 1000)
            mins = int(pace_sec_per_km // 60)
            secs = int(pace_sec_per_km % 60)
            avg_pace = f"{mins}:{secs:02d}"

        # Training effect — directly on the activity list object
        ae_te = a.get("aerobicTrainingEffect")
        an_te = a.get("anaerobicTrainingEffect")

        # HR zone time — directly on the activity list as hrTimeInZone_N
        hr_zones = {}
        for z in range(1, 6):
            val = a.get(f"hrTimeInZone_{z}")
            hr_zones[f"hr_zone{z}_sec"] = str(int(val)) if val is not None else ""

        rows.append({
            "activity_id": str(a.get("activityId", "")),
            "date": date_str,
            "start_time": start_time,
            "activity_type": str(activity_type),
            "distance_km": str(round(distance_m / 1000, 1)) if distance_m else "",
            "duration_sec": str(int(duration)) if duration else "",
            "avg_pace_min_km": avg_pace,
            "avg_hr": str(int(a["averageHR"])) if a.get("averageHR") else "",
            "max_hr": str(int(a["maxHR"])) if a.get("maxHR") else "",
            "elevation_gain_m": str(a["elevationGain"]) if a.get("elevationGain") else "",
            "avg_cadence": str(int(a["averageRunningCadenceInStepsPerMinute"])) if a.get("averageRunningCadenceInStepsPerMinute") else "",
            "calories": str(int(a["calories"])) if a.get("calories") else "",
            "aerobic_te": str(round(float(ae_te), 1)) if ae_te is not None else "",
            "anaerobic_te": str(round(float(an_te), 1)) if an_te is not None else "",
            **hr_zones,
        })
    return rows


def parse_splits(activity_id: str, splits_data: dict) -> list[dict]:
    """Parse per-lap split data from get_activity_splits() response.

    Garmin returns laps as lapDTOs. ConnectIQ power (e.g. Stryd) appears in
    connectIQMeasurement array with a specific developerFieldNumber.
    """
    rows = []
    laps = splits_data.get("lapDTOs", [])
    if not laps:
        return rows

    for i, lap in enumerate(laps, start=1):
        distance_m = lap.get("distance", 0) or 0
        duration_sec = lap.get("duration", 0) or 0

        avg_pace = ""
        if distance_m and duration_sec:
            pace_sec_per_km = duration_sec / (distance_m / 1000)
            mins = int(pace_sec_per_km // 60)
            secs = int(pace_sec_per_km % 60)
            avg_pace = f"{mins}:{secs:02d}"

        # ConnectIQ power from Stryd — look in connectIQMeasurement array
        avg_power = ""
        for ciq in lap.get("connectIQMeasurement", []):
            if ciq.get("developerFieldNumber") == 10:
                try:
                    avg_power = str(int(float(ciq["value"])))
                except (ValueError, KeyError):
                    pass
                break

        elev_gain = lap.get("elevationGain")
        elev_loss = lap.get("elevationLoss", 0)
        elev_change = ""
        if elev_gain is not None:
            elev_change = str(round(elev_gain - (elev_loss or 0), 1))

        rows.append({
            "activity_id": str(activity_id),
            "split_num": str(i),
            "distance_km": str(round(distance_m / 1000, 2)) if distance_m else "",
            "duration_sec": str(int(duration_sec)) if duration_sec else "",
            "avg_pace_min_km": avg_pace,
            "avg_hr": str(int(lap["averageHR"])) if lap.get("averageHR") else "",
            "max_hr": str(int(lap["maxHR"])) if lap.get("maxHR") else "",
            "avg_cadence": str(int(lap["averageRunCadence"])) if lap.get("averageRunCadence") else "",
            "elevation_change_m": elev_change,
            "avg_power": avg_power,
        })
    return rows


def parse_daily_metrics(
    date_str: str,
    training_status: dict,
    resting_hr: int | None = None,
    training_readiness: dict | None = None,
    race_predictions: dict | None = None,
) -> list[dict]:
    """Build a daily_metrics row from Garmin API responses."""
    # VO2max is nested inside training_status.mostRecentVO2Max.generic
    vo2max_data = training_status.get("mostRecentVO2Max", {}) or {}
    generic = vo2max_data.get("generic", {}) or {}
    vo2max = generic.get("vo2MaxPreciseValue", "")
    status = training_status.get("latestTrainingStatusKey",
             training_status.get("trainingStatusKey", ""))

    # Training readiness — API returns a list, take first entry
    readiness = ""
    if training_readiness:
        entry = training_readiness
        if isinstance(training_readiness, list) and training_readiness:
            entry = training_readiness[0]
        readiness = entry.get("score", "")

    # Marathon race prediction — flat keys like timeMarathon (seconds)
    marathon_pred = ""
    if race_predictions and isinstance(race_predictions, dict):
        val = race_predictions.get("timeMarathon")
        if val is not None:
            marathon_pred = str(int(val))

    return [{
        "date": date_str,
        "vo2max": str(vo2max) if vo2max else "",
        "training_status": str(status),
        "resting_hr": str(resting_hr) if resting_hr else "",
        "training_readiness": str(readiness) if readiness else "",
        "marathon_prediction_sec": marathon_pred,
    }]


def parse_lactate_threshold(lt_data: dict) -> list[dict]:
    """Parse Garmin lactate threshold API response into CSV rows.

    Two response formats:
    1. Range query (latest=False): {"speed": [entries], "heart_rate": [entries], "power": [entries]}
       Each entry: {"from": "2025-04-01", "value": 0.383, "updatedDate": "..."}
    2. Latest query (latest=True): {"speed_and_heart_rate": {speed, heartRate, calendarDate}, "power": {ftp, ...}}
    """
    rows = []

    if not isinstance(lt_data, dict):
        return rows

    # Format 1: Range query — parallel arrays for speed, heart_rate, power
    if "speed" in lt_data and isinstance(lt_data["speed"], list):
        # Build lookup dicts by date for each metric
        speed_by_date = {}
        for entry in lt_data.get("speed", []):
            if isinstance(entry, dict) and entry.get("from"):
                speed_by_date[entry["from"]] = entry.get("value")

        hr_by_date = {}
        for entry in lt_data.get("heart_rate", []):
            if isinstance(entry, dict) and entry.get("from"):
                hr_by_date[entry["from"]] = entry.get("value")

        power_by_date = {}
        for entry in lt_data.get("power", []):
            if isinstance(entry, dict) and entry.get("from"):
                power_by_date[entry["from"]] = entry.get("value")

        # Merge all dates
        all_dates = sorted(set(list(speed_by_date.keys()) + list(hr_by_date.keys()) + list(power_by_date.keys())))

        for d in all_dates:
            speed_val = speed_by_date.get(d)
            hr_val = hr_by_date.get(d)
            power_val = power_by_date.get(d)

            pace = _garmin_speed_to_pace_sec_km(speed_val) if speed_val else None

            rows.append({
                "date": d,
                "lthr_bpm": str(int(float(hr_val))) if hr_val else "",
                "lt_power_watts": str(int(float(power_val))) if power_val else "",
                "lt_pace_sec_km": str(pace) if pace else "",
                "lt_speed_raw": str(round(float(speed_val), 6)) if speed_val else "",
            })

        return rows

    # Format 2: Latest query — single combined entry
    if "speed_and_heart_rate" in lt_data:
        shr = lt_data["speed_and_heart_rate"]
        if isinstance(shr, dict):
            date_str = str(shr.get("calendarDate", ""))[:10]
            hr_val = shr.get("heartRate")
            speed_val = shr.get("speed")

            power_data = lt_data.get("power", {})
            power_val = power_data.get("functionalThresholdPower") if isinstance(power_data, dict) else None
            if not date_str and isinstance(power_data, dict):
                date_str = str(power_data.get("calendarDate", ""))[:10]

            pace = _garmin_speed_to_pace_sec_km(speed_val) if speed_val else None

            if date_str:
                rows.append({
                    "date": date_str,
                    "lthr_bpm": str(int(float(hr_val))) if hr_val else "",
                    "lt_power_watts": str(int(float(power_val))) if power_val else "",
                    "lt_pace_sec_km": str(pace) if pace else "",
                    "lt_speed_raw": str(round(float(speed_val), 6)) if speed_val else "",
                })

    return rows
