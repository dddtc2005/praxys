"""Unit tests for COROS sync client parsers."""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from requests import RequestException

from sync.coros_sync import (
    _compute_sleep_score,
    _format_date,
    _md5,
    _mobile_encrypt,
    fetch_activity_detail_data,
    is_token_valid,
    parse_activities,
    parse_activity_weather,
    parse_daily_metrics,
    parse_fitness_summary,
    parse_sleep,
    parse_splits,
)


def test_fetch_activity_detail_data_uses_training_hub_detail_endpoint():
    response = MagicMock()
    response.json.return_value = {"result": "0000", "data": {"weather": {}}}

    with patch("sync.coros_sync.requests.post", return_value=response) as post:
        detail = fetch_activity_detail_data("token", "us", "act-1", 100)

    assert detail == {"weather": {}}
    post.assert_called_once()
    _, kwargs = post.call_args
    assert kwargs["params"] == {"labelId": "act-1", "sportType": 100}
    assert kwargs["headers"]["accessToken"] == "token"
    response.raise_for_status.assert_called_once_with()


def test_fetch_activity_detail_data_ignores_malformed_envelope():
    response = MagicMock()
    response.json.return_value = []

    with patch("sync.coros_sync.requests.post", return_value=response):
        assert fetch_activity_detail_data("token", "us", "act-1", 100) == {}


def test_parse_activity_weather_scales_tenths():
    weather = parse_activity_weather(
        {"weather": {"temperature": 192, "humidity": 570}},
    )

    assert weather == {
        "temperature_c": "19.2",
        "relative_humidity_pct": "57.0",
        "environment_source": "coros_activity_weather",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"weather": None},
        {"weather": {"temperature": 192}},
        {"weather": {"humidity": 570}},
        {"weather": {"temperature": "bad", "humidity": 570}},
        {"weather": {"temperature": 192, "humidity": 1200}},
    ],
)
def test_parse_activity_weather_requires_a_valid_complete_pair(payload):
    assert parse_activity_weather(payload) == {}


def test_sync_coros_enriches_only_outdoor_runs_with_weather(monkeypatch):
    weather_calls = []
    written_rows = []
    raw_activities = [
        {"labelId": "2000", "sportType": 100, "date": 20260719},
        {"labelId": "2001", "sportType": 100, "date": 20260720},
        {"labelId": "2002", "sportType": 102, "date": 20260721},
        {"labelId": "2003", "sportType": 101, "date": 20260722},
    ]

    def fetch_weather(access_token, region, activity_id, sport_type):
        weather_calls.append((activity_id, sport_type))
        if activity_id == "2002":
            raise RequestException(
                "weather unavailable",
                response=SimpleNamespace(status_code=404),
            )
        return {"weather": {"temperature": 192, "humidity": 570}}

    def capture_activities(user_id, rows, db):
        written_rows.extend(rows)
        return len(rows)

    token_timestamp = int(time.time())
    monkeypatch.setattr(
        "sync.coros_sync.refresh_if_needed",
        lambda creds, email, password: (creds, False),
    )
    monkeypatch.setattr(
        "sync.coros_sync.fetch_activities",
        lambda access_token, region, start, end: raw_activities,
    )
    monkeypatch.setattr(
        "sync.coros_sync.fetch_activity_detail_data",
        fetch_weather,
    )
    monkeypatch.setattr(
        "sync.coros_sync.fetch_activity_detail",
        lambda *args, **kwargs: b"",
    )
    monkeypatch.setattr(
        "sync.coros_sync.fetch_daily_metrics",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "sync.coros_sync.parse_daily_metrics",
        lambda raw: [],
    )
    monkeypatch.setattr(
        "sync.coros_sync.fetch_sleep",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "sync.coros_sync.parse_sleep",
        lambda raw: [],
    )
    monkeypatch.setattr(
        "sync.coros_sync.fetch_fitness_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        "sync.coros_sync.parse_fitness_summary",
        lambda raw: {},
    )
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    monkeypatch.setattr("db.sync_writer.write_activities", capture_activities)
    for name in (
        "write_splits",
        "write_samples",
        "write_recovery",
        "write_profile_thresholds",
    ):
        monkeypatch.setattr(f"db.sync_writer.{name}", lambda *args, **kwargs: 0)

    class NullDB:
        def query(self, model):
            class Query:
                def filter(self, *args):
                    return self

                def all(self):
                    return [
                        SimpleNamespace(
                            activity_id="2000",
                            temperature_c=25.0,
                            relative_humidity_pct=50.0,
                            environment_source="coros_activity_weather",
                        ),
                    ]

            return Query()

        def commit(self):
            pass

    from api.routes.sync import _sync_coros

    result = _sync_coros(
        "weather-user",
        {
            "email": "runner@example.com",
            "password": "secret",
            "access_token": "token",
            "coros_user_id": "coros-user",
            "timestamp": token_timestamp,
            "mobile_access_token": "mobile-token",
            "mobile_timestamp": token_timestamp,
        },
        None,
        NullDB(),
    )

    assert result["activities"] == 4
    assert weather_calls == [("2001", 100), ("2002", 102)]
    rows_by_id = {row["activity_id"]: row for row in written_rows}
    assert rows_by_id["2001"]["temperature_c"] == "19.2"
    assert rows_by_id["2001"]["relative_humidity_pct"] == "57.0"
    assert rows_by_id["2001"]["environment_source"] == "coros_activity_weather"
    assert "temperature_c" not in rows_by_id["2000"]
    assert "temperature_c" not in rows_by_id["2002"]
    assert "temperature_c" not in rows_by_id["2003"]


def test_sync_coros_weather_rate_limit_aborts_for_backoff(monkeypatch):
    def rate_limited(*args, **kwargs):
        raise RequestException(
            "rate limited",
            response=SimpleNamespace(status_code=429),
        )

    monkeypatch.setattr(
        "sync.coros_sync.refresh_if_needed",
        lambda creds, email, password: (creds, False),
    )
    monkeypatch.setattr(
        "sync.coros_sync.fetch_activities",
        lambda *args, **kwargs: [
            {"labelId": "2001", "sportType": 100, "date": 20260720},
        ],
    )
    monkeypatch.setattr(
        "sync.coros_sync.fetch_activity_detail_data",
        rate_limited,
    )
    monkeypatch.setattr(
        "api.routes.sync._activity_ids_needing_environment",
        lambda user_id, activity_ids, db: set(activity_ids),
    )

    from api.routes.sync import _sync_coros

    with pytest.raises(RequestException):
        _sync_coros(
            "weather-user",
            {
                "email": "runner@example.com",
                "password": "secret",
                "access_token": "token",
                "coros_user_id": "coros-user",
                "timestamp": int(time.time()),
            },
            None,
            object(),
        )


# --- Fixtures ---

RAW_ACTIVITIES = [
    {
        "labelId": "abc123",
        "date": 20260415,
        # COROS sportType 100 = outdoor run; the legacy 1/2/3/4 codes
        # were replaced with the real API codes in #234 but this fixture
        # was missed.
        "sportType": 100,
        "distance": 10000,
        "duration": 3000,
        "avgHeartRate": 155,
        "maxHeartRate": 178,
        "avgPower": 280,
        "totalAscent": 120,
        "avgCadence": 180,
    },
    {
        "labelId": "def456",
        "date": 20260416,
        "sportType": 102,  # 102 = trail running (was 4 in the legacy map)
        "distance": 0,
        "duration": 1800,
        "avgHeartRate": 140,
        "maxHeartRate": 165,
    },
]

RAW_DETAIL = {
    "lapList": [
        {
            "distance": 5000,
            "duration": 1500,
            "avgPower": 285,
            "avgHeartRate": 152,
            "maxHeartRate": 170,
            "avgCadence": 178,
            "totalAscent": 60,
        },
        {
            "distance": 5000,
            "duration": 1500,
            "avgPower": 275,
            "avgHeartRate": 158,
            "maxHeartRate": 178,
            "avgCadence": 182,
            "totalAscent": 60,
        },
    ]
}

RAW_DAILY_METRICS = [
    {
        "happenDay": 20260415,
        "avgSleepHrv": 45.2,
        "rhr": 52,
        "trainingLoad": 120,
        "fatigueRate": 3.5,
    },
    {
        "happenDay": 20260416,
        "avgSleepHrv": 48.0,
        "rhr": 50,
        "trainingLoad": 80,
    },
]

RAW_FITNESS = {
    "vo2max": 52.3,
    "lthr": 168,
    "lactateThresholdPace": 258,
    "staminaLevel": 75.2,
}

RAW_SLEEP = [
    {
        "happenDay": 20260415,
        "performance": 82,
        "sleepData": {
            "totalSleepTime": 480,
            "deepTime": 120,
            "eyeTime": 90,
            "lightTime": 250,
            "wakeTime": 20,
        },
    },
    {
        "happenDay": 20260416,
        "performance": -1,
        "sleepData": {
            "totalSleepTime": 420,
            "deepTime": 100,
            "eyeTime": 80,
            "lightTime": 220,
            "wakeTime": 20,
        },
    },
    {
        "date": 20260417,
        "performance": 75,
        "sleepData": {
            "totalSleepTime": 450,
            "deepTime": 110,
            "eyeTime": 85,
        },
    },
]


# --- Tests ---


class TestFormatDate:
    def test_yyyymmdd_int(self):
        assert _format_date(20260415) == "2026-04-15"

    def test_yyyymmdd_str(self):
        assert _format_date("20260415") == "2026-04-15"

    def test_none(self):
        assert _format_date(None) == ""

    def test_iso_passthrough(self):
        assert _format_date("2026-04-15T10:00:00") == "2026-04-15"


class TestMd5:
    def test_known_hash(self):
        assert _md5("password") == "5f4dcc3b5aa765d61d8327deb882cf99"


class TestTokenValid:
    def test_valid_token(self):
        creds = {"timestamp": int(time.time()) - 100}
        assert is_token_valid(creds) is True

    def test_expired_token(self):
        creds = {"timestamp": int(time.time()) - 90000}
        assert is_token_valid(creds) is False

    def test_missing_timestamp(self):
        assert is_token_valid({}) is False


class TestParseActivities:
    def test_basic_parse(self):
        rows = parse_activities(RAW_ACTIVITIES)
        assert len(rows) == 2

        r0 = rows[0]
        assert r0["activity_id"] == "abc123"
        assert r0["date"] == "2026-04-15"
        assert r0["activity_type"] == "running"
        assert r0["source"] == "coros"
        assert float(r0["distance_km"]) == 10.0
        assert float(r0["duration_sec"]) == 3000
        assert r0["avg_hr"] == "155"
        assert r0["max_hr"] == "178"
        assert r0["avg_power"] == "280.0"
        assert r0["elevation_gain_m"] == "120.0"

    def test_zero_distance(self):
        rows = parse_activities(RAW_ACTIVITIES)
        r1 = rows[1]
        assert r1["distance_km"] == ""
        assert r1["activity_type"] == "trail_running"

    def test_empty_list(self):
        assert parse_activities([]) == []


class TestParseSplits:
    def test_basic_splits(self):
        rows = parse_splits("abc123", RAW_DETAIL)
        assert len(rows) == 2
        assert rows[0]["activity_id"] == "abc123"
        assert rows[0]["split_num"] == "1"
        assert float(rows[0]["distance_km"]) == 5.0
        assert rows[0]["avg_power"] == "285.0"
        assert rows[1]["split_num"] == "2"

    def test_empty_detail(self):
        assert parse_splits("x", {}) == []
        assert parse_splits("x", {"lapList": []}) == []


class TestParseDailyMetrics:
    def test_basic_metrics(self):
        rows = parse_daily_metrics(RAW_DAILY_METRICS)
        assert len(rows) == 2

        r0 = rows[0]
        assert r0["date"] == "2026-04-15"
        assert r0["source"] == "coros"
        assert r0["hrv_ms"] == "45"
        assert r0["resting_hr"] == "52"
        assert r0["training_load"] == "120"
        assert r0["fatigue_rate"] == "3.5"

    def test_empty(self):
        assert parse_daily_metrics([]) == []


class TestParseFitnessSummary:
    def test_full_summary(self):
        result = parse_fitness_summary(RAW_FITNESS)
        assert result["vo2max"] == 52.3
        assert result["lthr_bpm"] == 168
        assert result["lt_pace_sec_km"] == 258
        assert result["stamina_level"] == "75.2"

    def test_empty_data(self):
        assert parse_fitness_summary({}) == {}


class TestMobileEncrypt:
    def test_roundtrip_deterministic(self):
        """Encryption with same inputs produces same output."""
        key = "0123456789abcdef"
        result1 = _mobile_encrypt("test@example.com", key)
        result2 = _mobile_encrypt("test@example.com", key)
        assert result1 == result2
        assert len(result1) > 0

    def test_different_inputs(self):
        key = "0123456789abcdef"
        r1 = _mobile_encrypt("user1@test.com", key)
        r2 = _mobile_encrypt("user2@test.com", key)
        assert r1 != r2

    def test_output_is_base64(self):
        import base64
        key = "0123456789abcdef"
        result = _mobile_encrypt("hello", key)
        # Should not raise
        decoded = base64.b64decode(result)
        # AES-128-CBC output is always a multiple of 16 bytes
        assert len(decoded) % 16 == 0


class TestComputeSleepScore:
    def test_optimal_sleep(self):
        # 8h total, 20% deep (96min), 22% REM (106min), 50% light (240min), 10min wake
        score = _compute_sleep_score(480, 96, 106, 240, 10)
        assert score == 100

    def test_short_sleep(self):
        # 5h total → duration penalized, but good architecture still scores OK
        score = _compute_sleep_score(300, 48, 60, 180, 12)
        assert score is not None
        assert 60 < score < 90

    def test_no_deep_no_rem(self):
        # 8h but no deep or REM, all light
        score = _compute_sleep_score(480, 0, 0, 480, 0)
        assert score is not None
        assert score < 50

    def test_zero_total(self):
        assert _compute_sleep_score(0, 0, 0) is None

    def test_high_wake_penalty(self):
        # Good sleep but 50min awake
        good = _compute_sleep_score(480, 96, 106, 240, 10)
        bad_wake = _compute_sleep_score(480, 96, 106, 240, 50)
        assert bad_wake < good

    def test_excessive_light_penalty(self):
        # 70% light sleep
        score = _compute_sleep_score(480, 48, 48, 336, 10)
        assert score < 85

    def test_real_coros_data(self):
        # From actual COROS data: 463min total, 28 deep, 143 REM, 292 light, 32 wake
        score = _compute_sleep_score(463, 28, 143, 292, 32)
        assert score is not None
        assert 50 < score < 90


class TestParseSleep:
    def test_basic_sleep(self):
        rows = parse_sleep(RAW_SLEEP)
        assert len(rows) == 3

        r0 = rows[0]
        assert r0["date"] == "2026-04-15"
        assert r0["total_sleep_sec"] == "28800"   # 480 min * 60
        assert r0["deep_sleep_sec"] == "7200"      # 120 min * 60
        assert r0["rem_sleep_sec"] == "5400"        # 90 min * 60
        # sleep_score is computed, should be a non-empty string
        assert r0["sleep_score"] != ""
        assert 0 < int(r0["sleep_score"]) <= 100
        assert r0["source"] == "coros"

    def test_all_rows_have_score(self):
        rows = parse_sleep(RAW_SLEEP)
        for r in rows:
            assert r["sleep_score"] != ""
            assert 0 < int(r["sleep_score"]) <= 100

    def test_date_field_fallback(self):
        rows = parse_sleep(RAW_SLEEP)
        r2 = rows[2]
        assert r2["date"] == "2026-04-17"
        assert r2["total_sleep_sec"] == "27000"    # 450 min * 60
        assert r2["deep_sleep_sec"] == "6600"       # 110 min * 60
        assert r2["rem_sleep_sec"] == "5100"         # 85 min * 60

    def test_empty(self):
        assert parse_sleep([]) == []
