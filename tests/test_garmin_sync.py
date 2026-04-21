from sync.garmin_sync import (
    parse_activities,
    parse_daily_metrics,
    parse_splits,
    parse_user_profile,
)

SAMPLE_ACTIVITY = {
    "activityId": 12345678901,
    "startTimeLocal": "2026-03-10 07:00:00",
    "activityType": {"typeKey": "running"},
    "distance": 12500.0,
    "duration": 3600.0,
    "averageHR": 145,
    "maxHR": 172,
    "elevationGain": 150.0,
    "averageRunningCadenceInStepsPerMinute": 170,
    "calories": 850,
    "aerobicTrainingEffect": 3.2,
    "anaerobicTrainingEffect": 1.5,
    "hrTimeInZone_1": 60.0,
    "hrTimeInZone_2": 600.0,
    "hrTimeInZone_3": 1800.0,
    "hrTimeInZone_4": 900.0,
    "hrTimeInZone_5": 240.0,
}


def test_parse_activities():
    rows = parse_activities([SAMPLE_ACTIVITY])
    assert len(rows) == 1
    r = rows[0]
    assert r["activity_id"] == "12345678901"
    assert r["date"] == "2026-03-10"
    assert r["start_time"] == "2026-03-10 07:00:00"
    assert r["activity_type"] == "running"
    assert r["distance_km"] == "12.5"
    assert r["duration_sec"] == "3600"
    assert r["avg_hr"] == "145"
    assert r["max_hr"] == "172"
    assert r["elevation_gain_m"] == "150.0"
    assert r["avg_cadence"] == "170"
    assert r["calories"] == "850"


def test_parse_activities_computes_avg_pace():
    rows = parse_activities([SAMPLE_ACTIVITY])
    # 3600s / 12.5km = 288 sec/km = 4:48
    assert rows[0]["avg_pace_min_km"] == "4:48"


def test_parse_activities_training_effect():
    rows = parse_activities([SAMPLE_ACTIVITY])
    assert rows[0]["aerobic_te"] == "3.2"
    assert rows[0]["anaerobic_te"] == "1.5"


def test_parse_activities_hr_zones():
    rows = parse_activities([SAMPLE_ACTIVITY])
    assert rows[0]["hr_zone1_sec"] == "60"
    assert rows[0]["hr_zone2_sec"] == "600"
    assert rows[0]["hr_zone3_sec"] == "1800"
    assert rows[0]["hr_zone4_sec"] == "900"
    assert rows[0]["hr_zone5_sec"] == "240"


def test_parse_activities_handles_missing_fields():
    minimal = {"activityId": 1, "startTimeLocal": "2026-03-10 07:00:00"}
    rows = parse_activities([minimal])
    assert len(rows) == 1
    assert rows[0]["activity_id"] == "1"
    assert rows[0]["avg_hr"] == ""
    assert rows[0]["avg_pace_min_km"] == ""
    assert rows[0]["aerobic_te"] == ""
    assert rows[0]["hr_zone1_sec"] == ""


# --- Splits (from lapDTOs) ---

SAMPLE_LAP_DTOS = {
    "lapDTOs": [
        {
            "distance": 1000.0,
            "duration": 288.0,
            "averageHR": 140.0,
            "maxHR": 155.0,
            "averageRunCadence": 170.0,
            "elevationGain": 10.0,
            "elevationLoss": 5.0,
            "connectIQMeasurement": [
                {"developerFieldNumber": 10, "value": "265.0"},
            ],
        },
        {
            "distance": 1000.0,
            "duration": 285.0,
            "averageHR": 148.0,
            "maxHR": 160.0,
            "averageRunCadence": 172.0,
            "elevationGain": 5.0,
            "elevationLoss": 8.0,
            "connectIQMeasurement": [],
        },
    ],
}


def test_parse_splits():
    rows = parse_splits("99999", SAMPLE_LAP_DTOS)
    assert len(rows) == 2

    r1 = rows[0]
    assert r1["activity_id"] == "99999"
    assert r1["split_num"] == "1"
    assert r1["distance_km"] == "1.0"
    assert r1["duration_sec"] == "288"
    assert r1["avg_pace_min_km"] == "4:48"
    assert r1["avg_hr"] == "140"
    assert r1["max_hr"] == "155"
    assert r1["avg_cadence"] == "170"
    assert r1["elevation_change_m"] == "5.0"
    assert r1["avg_power"] == "265"

    r2 = rows[1]
    assert r2["split_num"] == "2"
    assert r2["avg_power"] == ""  # no ConnectIQ power


def test_parse_splits_empty():
    assert parse_splits("123", {}) == []
    assert parse_splits("123", {"lapDTOs": []}) == []


def test_parse_splits_missing_optional_fields():
    data = {"lapDTOs": [{"distance": 1000.0, "duration": 300.0}]}
    rows = parse_splits("111", data)
    assert len(rows) == 1
    assert rows[0]["avg_hr"] == ""
    assert rows[0]["avg_power"] == ""
    assert rows[0]["elevation_change_m"] == ""


# --- Daily Metrics ---

SAMPLE_TRAINING_STATUS = {
    "mostRecentVO2Max": {
        "generic": {"vo2MaxPreciseValue": 54.3},
    },
    "latestTrainingStatusKey": "productive",
}


def test_parse_daily_metrics():
    rows = parse_daily_metrics("2026-03-10", SAMPLE_TRAINING_STATUS, resting_hr=48)
    assert len(rows) == 1
    r = rows[0]
    assert r["date"] == "2026-03-10"
    assert r["vo2max"] == "54.3"
    assert r["training_status"] == "productive"
    assert r["resting_hr"] == "48"
    assert r["training_readiness"] == ""
    assert r["marathon_prediction_sec"] == ""


def test_parse_daily_metrics_with_readiness_list():
    """Training readiness API returns a list — take first entry."""
    readiness = [{"score": 75, "level": "MODERATE"}]
    rows = parse_daily_metrics(
        "2026-03-10", SAMPLE_TRAINING_STATUS,
        training_readiness=readiness,
    )
    assert rows[0]["training_readiness"] == "75"


def test_parse_daily_metrics_with_readiness_dict():
    """Also handle dict format in case API changes."""
    readiness = {"score": 82}
    rows = parse_daily_metrics(
        "2026-03-10", SAMPLE_TRAINING_STATUS,
        training_readiness=readiness,
    )
    assert rows[0]["training_readiness"] == "82"


def test_parse_daily_metrics_with_race_predictions():
    predictions = {"timeMarathon": 12573, "timeHalfMarathon": 5781, "time5K": 1236}
    rows = parse_daily_metrics(
        "2026-03-10", SAMPLE_TRAINING_STATUS,
        race_predictions=predictions,
    )
    assert rows[0]["marathon_prediction_sec"] == "12573"


def test_parse_daily_metrics_fallback_training_status_key():
    """Older format uses trainingStatusKey instead of latestTrainingStatusKey."""
    status = {"trainingStatusKey": "recovery", "mostRecentVO2Max": {"generic": {}}}
    rows = parse_daily_metrics("2026-03-10", status)
    assert rows[0]["training_status"] == "recovery"


def test_parse_daily_metrics_empty():
    rows = parse_daily_metrics("2026-03-10", {})
    assert rows[0]["vo2max"] == ""
    assert rows[0]["training_status"] == ""
    assert rows[0]["training_readiness"] == ""
    assert rows[0]["marathon_prediction_sec"] == ""


# --- Activity power (native Garmin + ConnectIQ fallback) ---


def test_parse_activities_native_power():
    """Activity-level averagePower/maxPower from native running power."""
    act = {
        **SAMPLE_ACTIVITY,
        "averagePower": 252.4,
        "maxPower": 410,
    }
    rows = parse_activities([act])
    assert rows[0]["avg_power"] == "252.4"
    assert rows[0]["max_power"] == "410.0"


def test_parse_activities_no_power_when_missing():
    """Activities without power fields leave the column empty."""
    rows = parse_activities([SAMPLE_ACTIVITY])
    assert rows[0]["avg_power"] == ""
    assert rows[0]["max_power"] == ""


def test_parse_splits_prefers_native_power_over_connectiq():
    """Native lap averagePower wins over ConnectIQ field 10."""
    data = {
        "lapDTOs": [{
            "distance": 1000.0, "duration": 300.0,
            "averageHR": 150.0, "averageRunCadence": 170.0,
            "elevationGain": 0.0, "elevationLoss": 0.0,
            "averagePower": 245.0,
            "connectIQMeasurement": [
                {"developerFieldNumber": 10, "value": "999.0"},
            ],
        }],
    }
    rows = parse_splits("a1", data)
    assert rows[0]["avg_power"] == "245"


def test_parse_splits_connectiq_fallback_when_native_absent():
    """ConnectIQ field 10 picks up when native power isn't present."""
    data = {
        "lapDTOs": [{
            "distance": 1000.0, "duration": 300.0,
            "connectIQMeasurement": [
                {"developerFieldNumber": 10, "value": "270.0"},
            ],
        }],
    }
    rows = parse_splits("a1", data)
    assert rows[0]["avg_power"] == "270"


def test_parse_splits_ignores_connectiq_non_power_field():
    """ConnectIQ field 10 from an unrelated app (by name) is skipped."""
    data = {
        "lapDTOs": [{
            "distance": 1000.0, "duration": 300.0,
            "connectIQMeasurement": [
                {
                    "developerFieldNumber": 10,
                    "developerFieldName": "Leg Spring Stiffness",
                    "value": "11.5",
                },
            ],
        }],
    }
    rows = parse_splits("a1", data)
    # Non-power field 10 must not be mis-read as power.
    assert rows[0]["avg_power"] == ""


# --- User profile (max HR + resting HR thresholds) ---


def test_parse_user_profile_extracts_max_and_rest_hr():
    profile = {"userData": {"maxHr": 188, "restingHeartRate": 48}}
    assert parse_user_profile(profile) == {"max_hr_bpm": 188, "rest_hr_bpm": 48}


def test_parse_user_profile_handles_alternate_field_names():
    profile = {"userData": {"heartRateMax": 192.0, "restHr": 50}}
    assert parse_user_profile(profile) == {"max_hr_bpm": 192, "rest_hr_bpm": 50}


def test_parse_user_profile_without_userdata_wrapper():
    """Some Garmin responses put fields at top level instead of nested."""
    profile = {"maxHeartRate": 185, "restingHeartRate": 52}
    assert parse_user_profile(profile) == {"max_hr_bpm": 185, "rest_hr_bpm": 52}


def test_parse_user_profile_empty_or_invalid():
    assert parse_user_profile(None) == {}
    assert parse_user_profile({}) == {}
    assert parse_user_profile({"userData": {"maxHr": "not a number"}}) == {}
