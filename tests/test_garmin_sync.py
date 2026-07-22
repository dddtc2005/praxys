import contextlib
from datetime import date
from types import SimpleNamespace

import pytest
from garminconnect.exceptions import (
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from sync.garmin_sync import (
    parse_activities,
    parse_activity_weather,
    parse_daily_metrics,
    parse_garmin_recovery,
    parse_heart_rates,
    parse_running_ftp,
    parse_splits,
    parse_user_profile,
)


def _garmin_connection_error(status_code):
    return GarminConnectConnectionError(
        f"API call client error ({status_code}): API Error {status_code}",
    )


def test_parse_activity_weather_converts_fahrenheit_to_celsius():
    weather = parse_activity_weather({"temp": 86, "relativeHumidity": 72})

    assert weather == {
        "temperature_c": "30.0",
        "relative_humidity_pct": "72.0",
        "environment_source": "garmin_activity_weather",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"temp": 86},
        {"relativeHumidity": 72},
        {"temp": "not-a-number", "relativeHumidity": 72},
        {"temp": 86, "relativeHumidity": 101},
    ],
)
def test_parse_activity_weather_requires_a_valid_complete_pair(payload):
    assert parse_activity_weather(payload) == {}


def test_sync_garmin_enriches_only_outdoor_runs_with_weather(
    tmp_path, monkeypatch,
):
    weather_calls = []
    written_rows = []
    raw_activities = [
        {
            "activityId": 1000,
            "startTimeLocal": "2026-07-19 07:00:00",
            "activityType": {"typeKey": "running"},
        },
        {
            "activityId": 1001,
            "startTimeLocal": "2026-07-20 07:00:00",
            "activityType": {"typeKey": "running"},
        },
        {
            "activityId": 1002,
            "startTimeLocal": "2026-07-21 07:00:00",
            "activityType": {"typeKey": "trail_running"},
        },
        {
            "activityId": 1003,
            "startTimeLocal": "2026-07-22 07:00:00",
            "activityType": {"typeKey": "treadmill_running"},
        },
    ]

    class FakeGarmin:
        def __init__(self, email, password, is_cn=False):
            self.client = type("Client", (), {})()

        def login(self, token_dir):
            pass

        def get_activities_by_date(self, *args, **kwargs):
            return raw_activities

        def get_activity_weather(self, activity_id):
            weather_calls.append(str(activity_id))
            if str(activity_id) == "1002":
                raise _garmin_connection_error(404)
            return {"temp": 86, "relativeHumidity": 72}

        def get_activity_splits(self, activity_id):
            return {}

        def get_activity_details(self, activity_id, maxchart):
            return {}

        def get_lactate_threshold(self, **kwargs):
            return []

        def get_user_profile(self):
            return {}

        def get_heart_rates(self, activity_date):
            return {}

        def connectapi(self, path):
            return {}

        def get_training_status(self, activity_date):
            return {}

        def get_training_readiness(self, activity_date):
            return None

        def get_race_predictions(self):
            return None

        def get_hrv_data(self, activity_date):
            return None

        def get_sleep_data(self, activity_date):
            return None

    def capture_activities(user_id, rows, db):
        written_rows.extend(rows)
        return len(rows)

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("garminconnect.Garmin", FakeGarmin)
    monkeypatch.setattr("sync.garmin_sync.RATE_LIMIT_DELAY", 0)
    monkeypatch.setattr("db.sync_writer.write_activities", capture_activities)
    for name in (
        "write_splits",
        "write_samples",
        "write_lactate_threshold",
        "write_daily_metrics",
        "write_recovery",
        "write_profile_thresholds",
    ):
        monkeypatch.setattr(f"db.sync_writer.{name}", lambda *args, **kwargs: 0)

    class FakeConfig:
        source_options = {"garmin_activity_categories": ["running"]}

    monkeypatch.setattr(
        "analysis.config.load_config_from_db",
        lambda user_id, db: FakeConfig(),
    )

    class NullDB:
        def query(self, model):
            class Query:
                def filter(self, *args):
                    return self

                def all(self):
                    return [
                        SimpleNamespace(
                            activity_id="1000",
                            temperature_c=25.0,
                            relative_humidity_pct=50.0,
                            environment_source="garmin_activity_weather",
                        ),
                    ]

            return Query()

        def begin_nested(self):
            return contextlib.nullcontext()

    from api.routes.sync import _sync_garmin

    result = _sync_garmin(
        "weather-user",
        {"email": "runner@example.com", "password": "secret"},
        date.today().isoformat(),
        NullDB(),
    )

    assert result["activities"] == 4
    assert weather_calls == ["1001", "1002"]
    rows_by_id = {row["activity_id"]: row for row in written_rows}
    assert rows_by_id["1001"]["temperature_c"] == "30.0"
    assert rows_by_id["1001"]["relative_humidity_pct"] == "72.0"
    assert (
        rows_by_id["1001"]["environment_source"]
        == "garmin_activity_weather"
    )
    assert "temperature_c" not in rows_by_id["1000"]
    assert "temperature_c" not in rows_by_id["1002"]
    assert "temperature_c" not in rows_by_id["1003"]


@pytest.mark.parametrize(
    "weather_error",
    [
        GarminConnectTooManyRequestsError("rate limited"),
        _garmin_connection_error(403),
    ],
)
def test_sync_garmin_weather_systemic_error_aborts_for_backoff(
    tmp_path, monkeypatch, weather_error,
):
    class RateLimitedGarmin:
        def __init__(self, email, password, is_cn=False):
            self.client = type("Client", (), {})()

        def login(self, token_dir):
            pass

        def get_activities_by_date(self, *args, **kwargs):
            return [
                {
                    "activityId": 1001,
                    "startTimeLocal": "2026-07-20 07:00:00",
                    "activityType": {"typeKey": "running"},
                },
            ]

        def get_activity_weather(self, activity_id):
            raise weather_error

    class FakeConfig:
        source_options = {"garmin_activity_categories": ["running"]}

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("garminconnect.Garmin", RateLimitedGarmin)
    monkeypatch.setattr(
        "analysis.config.load_config_from_db",
        lambda user_id, db: FakeConfig(),
    )
    monkeypatch.setattr(
        "api.routes.sync._activity_ids_needing_environment",
        lambda user_id, activity_ids, db: set(activity_ids),
    )

    from api.routes.sync import _sync_garmin

    with pytest.raises(type(weather_error)):
        _sync_garmin(
            "weather-user",
            {"email": "runner@example.com", "password": "secret"},
            date.today().isoformat(),
            object(),
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
                {
                    "developerFieldNumber": 10,
                    "developerFieldName": "Stryd Power",
                    "value": "265.0",
                },
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
    assert r1["power_source"] == "stryd"

    r2 = rows[1]
    assert r2["split_num"] == "2"
    assert r2["avg_power"] == ""  # no ConnectIQ power
    assert r2["power_source"] == ""


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
    assert rows[0]["power_source"] == "garmin"


def test_parse_splits_connectiq_fallback_when_native_absent():
    """ConnectIQ field 10 picks up when native power isn't present."""
    data = {
        "lapDTOs": [{
            "distance": 1000.0, "duration": 300.0,
            "connectIQMeasurement": [
                {
                    "developerFieldNumber": 10,
                    "developerFieldName": "Stryd Power",
                    "value": "270.0",
                },
            ],
        }],
    }
    rows = parse_splits("a1", data)
    assert rows[0]["avg_power"] == "270"
    assert rows[0]["power_source"] == "stryd"


def test_parse_splits_ignores_unnamed_connectiq_field():
    """An app-scoped field number alone cannot establish Stryd provenance."""
    data = {
        "lapDTOs": [{
            "distance": 1000.0,
            "duration": 300.0,
            "connectIQMeasurement": [
                {"developerFieldNumber": 10, "value": "270.0"},
            ],
        }],
    }

    rows = parse_splits("a1", data)

    assert rows[0]["avg_power"] == ""
    assert rows[0]["power_source"] == ""


def test_parse_splits_ignores_generic_connectiq_power_field():
    """A power metric without an explicit Stryd identity has unknown provenance."""
    data = {
        "lapDTOs": [{
            "distance": 1000.0,
            "duration": 300.0,
            "connectIQMeasurement": [
                {
                    "developerFieldNumber": 10,
                    "developerFieldName": "Running Power",
                    "value": "270.0",
                },
            ],
        }],
    }

    rows = parse_splits("a1", data)

    assert rows[0]["avg_power"] == ""
    assert rows[0]["power_source"] == ""


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


# --- User profile (LTHR + max HR thresholds) ---
# Garmin's user-settings endpoint does NOT return resting HR — that lives in
# get_heart_rates(date). Profile carries LTHR and (occasionally) a maxHr.


def test_parse_user_profile_extracts_lthr_from_real_shape():
    """The actual Garmin /userprofile-service/userprofile/user-settings payload
    (International, 2026-04) has LTHR under userData.lactateThresholdHeartRate.
    """
    profile = {
        "userData": {
            "lactateThresholdHeartRate": 172,
            "vo2MaxRunning": 55.0,
            "thresholdHeartRateAutoDetected": True,
        },
    }
    assert parse_user_profile(profile) == {"lthr_bpm": 172}


def test_parse_user_profile_extracts_max_hr_when_present():
    """Defensive: if a future Garmin shape adds maxHr to the profile, pick it up."""
    profile = {"userData": {"maxHr": 188, "lactateThresholdHeartRate": 170}}
    assert parse_user_profile(profile) == {"max_hr_bpm": 188, "lthr_bpm": 170}


def test_parse_user_profile_handles_alternate_max_hr_names():
    profile = {"userData": {"heartRateMax": 192.0}}
    assert parse_user_profile(profile) == {"max_hr_bpm": 192}


def test_parse_user_profile_without_userdata_wrapper():
    """Some Garmin responses put fields at top level instead of nested."""
    profile = {"maxHeartRate": 185, "lactateThresholdHeartRate": 170}
    assert parse_user_profile(profile) == {"max_hr_bpm": 185, "lthr_bpm": 170}


def test_parse_user_profile_empty_or_invalid():
    assert parse_user_profile(None) == {}
    assert parse_user_profile({}) == {}
    assert parse_user_profile({"userData": {"maxHr": "not a number"}}) == {}


def test_parse_user_profile_does_not_pull_rest_hr_from_profile():
    """Regression: profile must not pretend to return rest HR. Garmin's
    profile endpoint has no resting-HR field; that data comes from
    get_heart_rates. A parser that guesses rest_hr here would write
    garbage into fitness_data.rest_hr_bpm."""
    # Even when a profile-shaped dict contains a top-level restingHeartRate
    # (which real Garmin profiles don't), the parser ignores it.
    profile = {"userData": {"lactateThresholdHeartRate": 172}, "restingHeartRate": 46}
    out = parse_user_profile(profile)
    assert "rest_hr_bpm" not in out


# --- Heart rates (RHR sources) ---


def test_parse_heart_rates_extracts_rhr_and_rolling_avg():
    """Real shape from get_heart_rates(date) on International, 2026-04."""
    hr = {
        "maxHeartRate": 95,  # daily max — NOT lifetime max, we ignore it
        "minHeartRate": 45,
        "restingHeartRate": 46,
        "lastSevenDaysAvgRestingHeartRate": 47,
    }
    assert parse_heart_rates(hr) == {"resting_hr": 46, "rolling_rest_hr": 47}


def test_parse_heart_rates_handles_partial_payload():
    """Some days Garmin returns only the rolling average, no daily value yet."""
    assert parse_heart_rates({"lastSevenDaysAvgRestingHeartRate": 48}) == {
        "rolling_rest_hr": 48,
    }


def test_parse_heart_rates_handles_missing_and_invalid():
    assert parse_heart_rates(None) == {}
    assert parse_heart_rates({}) == {}
    assert parse_heart_rates({"restingHeartRate": None}) == {}
    assert parse_heart_rates({"restingHeartRate": "N/A"}) == {}


# --- Running FTP / Critical Power ---


def test_parse_running_ftp_happy_path():
    """Real shape from /biometric-service/biometric/latestFunctionalThresholdPower/RUNNING."""
    payload = {
        "sport": "RUNNING",
        "functionalThresholdPower": 350,
        "isStale": False,
        "calendarDate": "2026-03-21T17:27:44.759",
    }
    assert parse_running_ftp(payload) == {"cp_watts": 350.0}


def test_parse_running_ftp_skips_stale():
    """Garmin flags isStale=True when it no longer trusts the value; don't write it."""
    payload = {
        "sport": "RUNNING",
        "functionalThresholdPower": 350,
        "isStale": True,
    }
    assert parse_running_ftp(payload) == {}


def test_parse_running_ftp_missing_or_invalid():
    assert parse_running_ftp(None) == {}
    assert parse_running_ftp({}) == {}
    assert parse_running_ftp({"functionalThresholdPower": None}) == {}
    assert parse_running_ftp({"functionalThresholdPower": "N/A"}) == {}


# --- Recovery parser robustness ---
# Each test below pins one payload shape that must not crash
# parse_garmin_recovery. If you change the parser, these must still return
# a row (or None) — never raise. The covered shapes include Garmin's
# present-but-null nests (hrvSummary/dailySleepDTO/sleepScores),
# non-dict containers, and invalid numeric fields.


def test_parse_garmin_recovery_returns_none_when_all_sources_empty():
    assert parse_garmin_recovery("2026-04-21") is None


def test_parse_garmin_recovery_handles_null_hrv_summary():
    """hrvSummary can come back as explicit null; must not raise."""
    row = parse_garmin_recovery(
        "2026-04-21",
        hrv_data={"hrvSummary": None},
        sleep_data={"dailySleepDTO": {"sleepScore": 85}},
    )
    assert row is not None
    assert row["sleep_score"] == "85"
    assert "hrv_ms" not in row


def test_parse_garmin_recovery_handles_null_daily_sleep():
    """dailySleepDTO can come back as explicit null; must not raise."""
    row = parse_garmin_recovery(
        "2026-04-21",
        hrv_data={"hrvSummary": {"lastNightAvg": 42.5}},
        sleep_data={"dailySleepDTO": None},
    )
    assert row is not None
    assert row["hrv_ms"] == "42"


def test_parse_garmin_recovery_handles_null_sleep_scores():
    """sleepScores (or its overall child) can be null."""
    row = parse_garmin_recovery(
        "2026-04-21",
        sleep_data={"dailySleepDTO": {
            "sleepScores": None,
            "sleepTimeSeconds": 27000,
            "restingHeartRate": 52,
        }},
    )
    assert row is not None
    assert row["total_sleep_hours"] == "7.5"
    assert row["resting_hr"] == "52"
    # No sleep_score at any level → field absent, not a crash
    assert "sleep_score" not in row


def test_parse_garmin_recovery_extracts_all_fields_from_full_payload():
    """Per-key asserts so additive new fields don't fail this test for a
    non-behavioural reason."""
    row = parse_garmin_recovery(
        "2026-04-21",
        hrv_data={"hrvSummary": {"lastNightAvg": 48}},
        sleep_data={"dailySleepDTO": {
            "sleepScores": {"overall": {"value": 78}},
            "sleepTimeSeconds": 27900,
            "restingHeartRate": 50,
        }},
        training_readiness=[{"score": 72}],
    )
    assert row is not None
    assert row["date"] == "2026-04-21"
    assert row["source"] == "garmin"
    assert row["readiness_score"] == "72"
    assert row["hrv_ms"] == "48"
    assert row["sleep_score"] == "78"
    assert row["total_sleep_hours"] == "7.8"
    assert row["resting_hr"] == "50"


def test_parse_garmin_recovery_handles_null_overall_in_sleep_scores():
    """sleepScores present but the nested `overall` is null."""
    row = parse_garmin_recovery(
        "2026-04-21",
        sleep_data={"dailySleepDTO": {
            "sleepScores": {"overall": None},
            "sleepScore": 65,  # legacy flat field
            "restingHeartRate": 48,
        }},
    )
    assert row is not None
    # Falls through to the legacy sleepScore rather than raising on the
    # None overall dict.
    assert row["sleep_score"] == "65"
    assert row["resting_hr"] == "48"


def test_parse_garmin_recovery_handles_non_dict_containers():
    """Garmin sometimes returns lists or strings for endpoints that have
    no data. Non-dict inputs must be skipped without raising."""
    row = parse_garmin_recovery(
        "2026-04-21",
        hrv_data=[],  # empty list instead of dict
        sleep_data={"dailySleepDTO": []},  # list nested under expected dict key
        training_readiness="not-a-list",  # unexpected string
    )
    # No data from any source → returns None
    assert row is None


@pytest.mark.parametrize("bad_rhr", [None, 0, -5, 10])
def test_parse_garmin_recovery_ignores_unreasonable_rhr(bad_rhr):
    """RHR values <= 20 are sensor artefacts; None must also be skipped."""
    import pytest as _  # ensure parametrize import is valid
    row = parse_garmin_recovery(
        "2026-04-21",
        sleep_data={"dailySleepDTO": {
            "sleepScore": 70, "restingHeartRate": bad_rhr,
        }},
    )
    assert row is not None
    assert "resting_hr" not in row


def test_parse_garmin_recovery_uses_heart_rates_rhr():
    """When get_heart_rates(date) is available, its restingHeartRate is the
    authoritative source — even if sleep data lacks one (International)."""
    row = parse_garmin_recovery(
        "2026-04-22",
        sleep_data={"dailySleepDTO": {"sleepScore": 80, "avgHeartRate": 49}},
        heart_rates={"restingHeartRate": 46, "lastSevenDaysAvgRestingHeartRate": 47},
    )
    assert row is not None
    assert row["resting_hr"] == "46"
    assert row["sleep_score"] == "80"


def test_parse_garmin_recovery_heart_rates_wins_over_sleep():
    """If both sources provide RHR, heart_rates (the dedicated endpoint) wins."""
    row = parse_garmin_recovery(
        "2026-04-22",
        sleep_data={"dailySleepDTO": {"sleepScore": 80, "restingHeartRate": 58}},
        heart_rates={"restingHeartRate": 46},
    )
    assert row is not None
    assert row["resting_hr"] == "46"


def test_parse_garmin_recovery_falls_back_to_sleep_rhr_when_no_heart_rates():
    """Legacy payload shape where sleep carries RHR — keep it working."""
    row = parse_garmin_recovery(
        "2026-04-22",
        sleep_data={"dailySleepDTO": {"sleepScore": 80, "restingHeartRate": 52}},
        heart_rates=None,
    )
    assert row is not None
    assert row["resting_hr"] == "52"


def test_parse_garmin_recovery_raises_on_non_numeric_string():
    """float() on a non-numeric string is expected to raise. The caller in
    _sync_garmin has a per-day try/except that swallows this, so the loop
    survives — this test documents the contract that non-numeric strings
    are not silently coerced by the parser itself."""
    import pytest as _pytest
    with _pytest.raises((ValueError, TypeError)):
        parse_garmin_recovery(
            "2026-04-21",
            hrv_data={"hrvSummary": {"lastNightAvg": "N/A"}},
        )
