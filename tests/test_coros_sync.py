"""Unit tests for COROS sync client parsers."""

from sync.coros_sync import (
    is_token_valid,
    parse_activities,
    parse_splits,
    parse_daily_metrics,
    parse_fitness_summary,
    parse_sleep,
    _format_date,
    _md5,
    _mobile_encrypt,
    _compute_sleep_score,
)
import time


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
