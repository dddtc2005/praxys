"""Tests for Stryd workout upload functions."""
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from sync.stryd_sync import (
    build_workout_blocks,
    create_workout_api,
    delete_workout_api,
    _parse_structured_description,
    _make_segment,
)


# --- build_workout_blocks ---


class TestBuildWorkoutBlocks:
    """Tests for converting AI plan workouts to Stryd block format."""

    def test_easy_run_single_block(self):
        """Easy run produces a single warmup-class block."""
        workout = {
            "workout_type": "easy",
            "planned_duration_min": "50",
            "target_power_min": "140",
            "target_power_max": "191",
            "workout_description": "Easy aerobic run.",
        }
        blocks = build_workout_blocks(workout, cp_watts=248.0)
        assert len(blocks) == 1
        seg = blocks[0]["segments"][0]
        assert seg["intensity_class"] == "warmup"
        assert seg["duration_time"]["minute"] == 50
        # CP percentages: 140/248 ≈ 56%, 191/248 ≈ 77%
        assert seg["intensity_percent"]["min"] == 56
        assert seg["intensity_percent"]["max"] == 77

    def test_recovery_run(self):
        """Recovery run uses warmup class with lower power."""
        workout = {
            "workout_type": "recovery",
            "planned_duration_min": "35",
            "target_power_min": "130",
            "target_power_max": "155",
            "workout_description": "Recovery shake-out.",
        }
        blocks = build_workout_blocks(workout, cp_watts=248.0)
        assert len(blocks) == 1
        seg = blocks[0]["segments"][0]
        assert seg["intensity_class"] == "warmup"
        assert seg["intensity_percent"]["min"] == 52  # 130/248
        assert seg["intensity_percent"]["max"] == 62  # round(155/248*100) = 62

    def test_structured_interval_description(self):
        """Interval workout with structured description parses into warmup + intervals + cooldown."""
        workout = {
            "workout_type": "interval",
            "planned_duration_min": "65",
            "target_power_min": "265",
            "target_power_max": "280",
            "workout_description": "WU 15min, 4x4min @265-280W w/ 3min jog recovery, CD 10min.",
        }
        blocks = build_workout_blocks(workout, cp_watts=248.0)
        assert len(blocks) == 3  # warmup, intervals, cooldown

        # Warmup
        assert blocks[0]["repeat"] == 1
        assert blocks[0]["segments"][0]["intensity_class"] == "warmup"
        assert blocks[0]["segments"][0]["duration_time"]["minute"] == 15

        # Intervals: 4x(work + rest)
        assert blocks[1]["repeat"] == 4
        assert len(blocks[1]["segments"]) == 2
        assert blocks[1]["segments"][0]["intensity_class"] == "work"
        assert blocks[1]["segments"][0]["duration_time"]["minute"] == 4
        assert blocks[1]["segments"][1]["intensity_class"] == "rest"
        assert blocks[1]["segments"][1]["duration_time"]["minute"] == 3

        # Work intensity: 265/248 ≈ 107%, 280/248 ≈ 113%
        work_pct = blocks[1]["segments"][0]["intensity_percent"]
        assert work_pct["min"] == 107
        assert work_pct["max"] == 113

        # Cooldown
        assert blocks[2]["segments"][0]["intensity_class"] == "cooldown"
        assert blocks[2]["segments"][0]["duration_time"]["minute"] == 10

    def test_threshold_description(self):
        """Threshold workout with 2x20min reps."""
        workout = {
            "workout_type": "threshold",
            "planned_duration_min": "65",
            "target_power_min": "235",
            "target_power_max": "255",
            "workout_description": "WU 10min, 2x20min @235-255W w/ 5min easy, CD 10min.",
        }
        blocks = build_workout_blocks(workout, cp_watts=248.0)
        assert len(blocks) == 3
        assert blocks[1]["repeat"] == 2
        assert blocks[1]["segments"][0]["duration_time"]["minute"] == 20

    def test_rest_day_fallback(self):
        """Rest day still produces blocks (caller should filter)."""
        workout = {
            "workout_type": "rest",
            "planned_duration_min": "",
            "target_power_min": "",
            "target_power_max": "",
            "workout_description": "Rest day.",
        }
        blocks = build_workout_blocks(workout, cp_watts=248.0)
        # Falls back to default single block
        assert len(blocks) == 1

    def test_no_power_targets_uses_defaults(self):
        """When power targets are missing, uses type-based defaults."""
        workout = {
            "workout_type": "long_run",
            "planned_duration_min": "140",
            "target_power_min": "",
            "target_power_max": "",
            "workout_description": "Long trail run.",
        }
        blocks = build_workout_blocks(workout, cp_watts=248.0)
        seg = blocks[0]["segments"][0]
        assert seg["intensity_percent"]["min"] == 68
        assert seg["intensity_percent"]["max"] == 78

    def test_blocks_have_uuids(self):
        """All blocks and segments have unique UUIDs."""
        workout = {
            "workout_type": "interval",
            "planned_duration_min": "65",
            "target_power_min": "265",
            "target_power_max": "280",
            "workout_description": "WU 15min, 4x4min @265-280W w/ 3min jog recovery, CD 10min.",
        }
        blocks = build_workout_blocks(workout, cp_watts=248.0)
        uuids = set()
        for b in blocks:
            uuids.add(b["uuid"])
            for seg in b["segments"]:
                uuids.add(seg["uuid"])
        # All unique
        total = sum(1 + len(b["segments"]) for b in blocks)
        assert len(uuids) == total


# --- _parse_structured_description ---


class TestParseStructuredDescription:
    """Tests for description string parsing."""

    def test_full_interval_description(self):
        blocks = _parse_structured_description(
            "WU 15min, 3x3min @275-290W w/ 3min jog recovery, CD 10min",
            cp_watts=248.0,
        )
        assert blocks is not None
        assert len(blocks) == 3

    def test_unstructured_returns_none(self):
        result = _parse_structured_description("Easy aerobic run.", cp_watts=248.0)
        assert result is None

    def test_done_marker_stripped(self):
        blocks = _parse_structured_description(
            "WU 10min, 2x20min @235-255W w/ 5min easy, CD 10min. [DONE]",
            cp_watts=248.0,
        )
        assert blocks is not None
        assert len(blocks) == 3

    def test_empty_description(self):
        assert _parse_structured_description("", cp_watts=248.0) is None
        assert _parse_structured_description(None, cp_watts=248.0) is None


# --- _make_segment ---


class TestMakeSegment:
    def test_segment_structure(self):
        seg = _make_segment("work", 5, 90, 100)
        assert seg["intensity_class"] == "work"
        assert seg["duration_type"] == "time"
        assert seg["duration_time"] == {"hour": 0, "minute": 5, "second": 0}
        assert seg["intensity_type"] == "percentage"
        assert seg["intensity_percent"] == {"min": 90, "max": 100, "value": 95}
        assert "uuid" in seg

    def test_long_duration(self):
        seg = _make_segment("warmup", 90, 65, 75)
        assert seg["duration_time"] == {"hour": 1, "minute": 30, "second": 0}


# --- create_workout_api ---


class TestCreateWorkoutApi:
    @patch("sync.stryd_sync.requests.post")
    def test_payload_shape(self, mock_post: MagicMock):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": 12345, "stress": 13.0}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        blocks = [{"uuid": "test", "repeat": 1, "segments": []}]
        create_workout_api(
            user_id="abc-123",
            token="tok",
            workout_date="2026-04-10",
            title="Test Workout",
            blocks=blocks,
            workout_type="easy run",
            description="A test",
            surface="road",
        )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["title"] == "Test Workout"
        assert payload["id"] == -1
        assert payload["source"] == "USER"
        assert payload["blocks"] == blocks

    @patch("sync.stryd_sync.requests.post")
    def test_timestamp_calculation(self, mock_post: MagicMock):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": 1}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        create_workout_api("uid", "tok", "2026-04-10", "Test", [])

        call_kwargs = mock_post.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        # 2026-04-10 00:00:00 UTC
        expected_ts = int(datetime(2026, 4, 10, tzinfo=timezone.utc).timestamp())
        assert params["timestamp"] == expected_ts


# --- delete_workout_api ---


class TestDeleteWorkoutApi:
    @patch("sync.stryd_sync.requests.delete")
    def test_delete_url(self, mock_delete: MagicMock):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_delete.return_value = mock_resp

        result = delete_workout_api("abc-123", "tok", "5401718379937792")
        assert result is True

        url = mock_delete.call_args[0][0]
        assert "abc-123" in url
        assert "5401718379937792" in url
