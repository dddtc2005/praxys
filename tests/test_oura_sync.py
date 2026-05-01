from unittest.mock import patch, MagicMock
from sync.oura_sync import (
    fetch_sleep_data, fetch_daily_sleep_data, fetch_readiness_data,
    parse_sleep_records, parse_daily_sleep_records, parse_readiness_records,
    merge_daily_sleep_score, select_oura_hrv_per_day,
)

SAMPLE_SLEEP_RESPONSE = {
    "data": [
        {
            "day": "2026-03-10",
            "total_sleep_duration": 28800,
            "deep_sleep_duration": 7200,
            "rem_sleep_duration": 5400,
            "light_sleep_duration": 16200,
            "efficiency": 92,
            # The /sleep endpoint includes a nested `readiness` block
            # carrying a per-sleep-period readiness contribution. Older
            # code surfaced this as `sleep_score`, which is wrong — it's
            # the readiness number, not a sleep quality score. The fix
            # drops sleep_score from this parser entirely; the actual
            # daily sleep score comes from /daily_sleep.
            "readiness": {"score": 85},
            "average_hrv": 45,
            "average_heart_rate": 52,
        }
    ],
    "next_token": None,
}

SAMPLE_DAILY_SLEEP_RESPONSE = {
    "data": [
        {
            "day": "2026-03-10",
            "score": 78,
            "contributors": {
                "deep_sleep": 80,
                "efficiency": 92,
                "latency": 75,
                "rem_sleep": 70,
                "restfulness": 82,
                "timing": 68,
                "total_sleep": 85,
            },
            "timestamp": "2026-03-10T08:00:00+00:00",
        }
    ],
    "next_token": None,
}

SAMPLE_READINESS_RESPONSE = {
    "data": [
        {
            "day": "2026-03-10",
            "score": 82,
            "temperature_deviation": 0.1,
            "timestamp": "2026-03-10T08:00:00+00:00",
        }
    ],
    "next_token": None,
}


def test_parse_sleep_records_no_sleep_score():
    """The detailed /sleep parser should NOT emit a sleep_score field —
    that key now belongs to parse_daily_sleep_records, which reads from
    Oura's daily_sleep endpoint. Encoding the prior bug-by-default
    behaviour here is what masked the issue for so long."""
    records = parse_sleep_records(SAMPLE_SLEEP_RESPONSE["data"])
    assert len(records) == 1
    r = records[0]
    assert r["date"] == "2026-03-10"
    assert r["total_sleep_sec"] == "28800"
    assert r["deep_sleep_sec"] == "7200"
    assert r["efficiency"] == "92"
    assert "sleep_score" not in r, (
        "parse_sleep_records must not emit sleep_score — the /sleep "
        "endpoint's readiness.score is a per-sleep readiness contribution, "
        "not a sleep quality score."
    )


def test_parse_daily_sleep_records():
    records = parse_daily_sleep_records(SAMPLE_DAILY_SLEEP_RESPONSE["data"])
    assert len(records) == 1
    r = records[0]
    assert r["date"] == "2026-03-10"
    # The actual daily sleep score (78), distinct from the readiness
    # score (82) and from /sleep's nested readiness.score (85).
    assert r["sleep_score"] == "78"


def test_parse_readiness_records():
    records = parse_readiness_records(SAMPLE_READINESS_RESPONSE["data"])
    assert len(records) == 1
    r = records[0]
    assert r["date"] == "2026-03-10"
    assert r["readiness_score"] == "82"
    assert r["body_temperature_delta"] == "0.1"


@patch("sync.oura_sync.requests.get")
def test_fetch_sleep_data(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_SLEEP_RESPONSE
    mock_get.return_value = mock_resp

    data = fetch_sleep_data("fake_token", "2026-03-01", "2026-03-10")
    assert len(data) == 1
    mock_get.assert_called_once()
    call_url = mock_get.call_args[0][0]
    assert "/sleep" in call_url
    assert "/daily_sleep" not in call_url, (
        "fetch_sleep_data must hit /sleep, not /daily_sleep"
    )


@patch("sync.oura_sync.requests.get")
def test_fetch_daily_sleep_data(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_DAILY_SLEEP_RESPONSE
    mock_get.return_value = mock_resp

    data = fetch_daily_sleep_data("fake_token", "2026-03-01", "2026-03-10")
    assert len(data) == 1
    mock_get.assert_called_once()
    call_url = mock_get.call_args[0][0]
    assert "/daily_sleep" in call_url


@patch("sync.oura_sync.requests.get")
def test_fetch_readiness_data(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_READINESS_RESPONSE
    mock_get.return_value = mock_resp

    data = fetch_readiness_data("fake_token", "2026-03-01", "2026-03-10")
    assert len(data) == 1


# ---------------------------------------------------------------------------
# merge_daily_sleep_score — joins /daily_sleep's score back into per-period
# /sleep rows. Critical glue: without it, the writer falls back to the empty
# sleep_score field on /sleep rows and the cell renders "—".
# ---------------------------------------------------------------------------


def test_merge_daily_sleep_score_basic():
    sleep_rows = [
        {"date": "2026-03-10", "total_sleep_sec": "28800"},
        {"date": "2026-03-11", "total_sleep_sec": "27000"},
    ]
    daily_sleep_rows = [
        {"date": "2026-03-10", "sleep_score": "78"},
        {"date": "2026-03-11", "sleep_score": "82"},
    ]
    out = merge_daily_sleep_score(sleep_rows, daily_sleep_rows)
    assert out[0]["sleep_score"] == "78"
    assert out[1]["sleep_score"] == "82"


def test_merge_daily_sleep_score_missing_day_left_untouched():
    """A /sleep day with no matching /daily_sleep entry stays without a
    sleep_score key. The writer reads dict.get('sleep_score') → None →
    _float(None) → None, which is the right "no value" semantics. The
    alternative — injecting an empty string — would make the writer
    think it had a value and could mask a real partial-coverage bug."""
    sleep_rows = [
        {"date": "2026-03-10", "total_sleep_sec": "28800"},
        {"date": "2026-03-11", "total_sleep_sec": "27000"},
    ]
    daily_sleep_rows = [{"date": "2026-03-10", "sleep_score": "78"}]
    out = merge_daily_sleep_score(sleep_rows, daily_sleep_rows)
    assert out[0]["sleep_score"] == "78"
    assert "sleep_score" not in out[1]


def test_merge_daily_sleep_score_empty_score_skipped():
    """Oura occasionally returns a daily_sleep row with an empty
    score (sleep is detected but the daily score isn't yet computed).
    Such rows must not overwrite anything."""
    sleep_rows = [{"date": "2026-03-10", "total_sleep_sec": "28800"}]
    daily_sleep_rows = [{"date": "2026-03-10", "sleep_score": ""}]
    out = merge_daily_sleep_score(sleep_rows, daily_sleep_rows)
    assert "sleep_score" not in out[0]


def test_merge_daily_sleep_score_does_not_corrupt_unrelated_dates():
    """A /daily_sleep entry for a day not in /sleep is silently
    discarded — the merge writes nowhere, so no orphan rows appear
    downstream. Important for the case where /daily_sleep covers a
    longer window than /sleep (e.g. nap-only day vs full sleep)."""
    sleep_rows = [{"date": "2026-03-10", "total_sleep_sec": "28800"}]
    daily_sleep_rows = [
        {"date": "2026-03-09", "sleep_score": "75"},
        {"date": "2026-03-10", "sleep_score": "78"},
    ]
    out = merge_daily_sleep_score(sleep_rows, daily_sleep_rows)
    assert len(out) == 1
    assert out[0]["sleep_score"] == "78"


def test_merge_daily_sleep_score_handles_empty_inputs():
    assert merge_daily_sleep_score([], []) == []
    assert merge_daily_sleep_score([{"date": "2026-03-10"}], []) == [{"date": "2026-03-10"}]
    assert merge_daily_sleep_score([], [{"date": "2026-03-10", "sleep_score": "78"}]) == []


# ---------------------------------------------------------------------------
# select_oura_hrv_per_day — multi-record-per-day tiebreak
#
# Production data-loss path: Oura returns long_sleep + late_nap + rest for the
# same `day`, naps come back with `average_hrv: null`, and a naive
# last-write-wins dict lets the nap clobber the long_sleep's valid HRV. Once
# the writer's existing-date dedup locks that null in, recovery analysis
# stalls on "Insufficient HRV data" forever.
# ---------------------------------------------------------------------------


def _record(day: str, hrv, hr, type_: str | None = "long_sleep") -> dict:
    rec: dict = {"day": day, "average_hrv": hrv, "average_heart_rate": hr}
    if type_ is not None:
        rec["type"] = type_
    return rec


def test_select_oura_hrv_long_sleep_beats_nap_with_null_hrv():
    """The exact production failure mode: nap with null HRV must not win."""
    sleep_raw = [
        _record("2026-04-29", 45, 52, type_="long_sleep"),
        _record("2026-04-29", None, None, type_="late_nap"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert out["2026-04-29"]["hrv_avg"] == "45"
    assert out["2026-04-29"]["resting_hr"] == "52"
    assert out["2026-04-29"]["_type"] == "long_sleep"


def test_select_oura_hrv_order_independent_for_null_naps():
    """Order shouldn't matter — long_sleep with HRV always beats null naps."""
    sleep_raw = [
        _record("2026-04-29", None, None, type_="late_nap"),
        _record("2026-04-29", 45, 52, type_="long_sleep"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert out["2026-04-29"]["hrv_avg"] == "45"


def test_select_oura_hrv_long_sleep_beats_rest_with_hrv():
    """When both records have positive HRV, long_sleep wins (even when rest sorts last)."""
    sleep_raw = [
        _record("2026-04-29", 45, 52, type_="long_sleep"),
        _record("2026-04-29", 38, 60, type_="rest"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert out["2026-04-29"]["hrv_avg"] == "45"
    assert out["2026-04-29"]["_type"] == "long_sleep"


def test_select_oura_hrv_falls_back_to_nap_when_long_sleep_missing_hrv():
    """If only the nap has HRV, it wins — the alternative is null HRV."""
    sleep_raw = [
        _record("2026-04-29", None, None, type_="long_sleep"),
        _record("2026-04-29", 38, 60, type_="late_nap"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert out["2026-04-29"]["hrv_avg"] == "38"


def test_select_oura_hrv_handles_missing_or_null_type():
    """`type` may be missing or JSON null — long_sleep candidate still wins."""
    sleep_raw = [
        _record("2026-04-29", 45, 52, type_=None),  # missing
        _record("2026-04-29", 50, 55, type_="long_sleep"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert out["2026-04-29"]["hrv_avg"] == "50"
    assert out["2026-04-29"]["_type"] == "long_sleep"


def test_select_oura_hrv_skips_records_without_day():
    """Records with empty/missing `day` are dropped silently."""
    sleep_raw = [
        {"day": "", "average_hrv": 45, "average_heart_rate": 52, "type": "long_sleep"},
        {"average_hrv": 50, "average_heart_rate": 55, "type": "long_sleep"},
        _record("2026-04-29", 45, 52, type_="long_sleep"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert list(out.keys()) == ["2026-04-29"]


def test_select_oura_hrv_zero_treated_as_invalid():
    """An average_hrv of 0 (occasional sensor glitch) shouldn't block a real reading."""
    sleep_raw = [
        _record("2026-04-29", 0, 0, type_="long_sleep"),
        _record("2026-04-29", 42, 50, type_="late_nap"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert out["2026-04-29"]["hrv_avg"] == "42"
