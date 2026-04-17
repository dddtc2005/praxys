"""Tests for Trainsight MCP server tools in local mode.

Run with: python -m pytest tests/test_mcp_tools.py -v

These tests call the MCP tool functions directly (no MCP protocol),
verifying they return valid JSON with expected structure.
Requires the `mcp` package — skipped in CI if not installed.
"""
import json
import os
import sys
import pytest

# Skip entire module if mcp is not installed (e.g., CI without mcp in requirements)
mcp = pytest.importorskip("mcp", reason="MCP SDK not installed")

# Add project root and MCP server to path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "plugins", "trainsight", "mcp-server"))

# Ensure local mode
os.environ.pop("TRAINSIGHT_URL", None)


@pytest.fixture(autouse=True)
def reset_user_cache():
    """Reset the cached user ID between tests."""
    import server
    server._cached_user_id = None
    server._db_initialized = False
    yield


def _parse(result: str) -> dict:
    """Parse tool output as JSON, fail if invalid."""
    data = json.loads(result)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    return data


# ---------------------------------------------------------------------------
# User detection
# ---------------------------------------------------------------------------

class TestUserDetection:
    def test_finds_user(self):
        from server import _local_user_id
        uid = _local_user_id()
        assert uid, "Should find a user ID"
        assert len(uid) > 0

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("TRAINSIGHT_USER_ID", "test-override-id")
        import server
        server._cached_user_id = None
        uid = server._local_user_id()
        assert uid == "test-override-id"


# ---------------------------------------------------------------------------
# Data tools
# ---------------------------------------------------------------------------

class TestDataTools:
    def test_get_daily_brief(self):
        from server import get_daily_brief
        data = _parse(get_daily_brief())
        assert "signal" in data, "Should contain signal"
        signal = data["signal"]
        assert "recommendation" in signal
        assert signal["recommendation"] in ("go", "modify", "rest", "follow_plan")

    def test_get_training_review(self):
        from server import get_training_review
        data = _parse(get_training_review())
        assert "diagnosis" in data
        assert "fitness_fatigue" in data
        assert "cp_trend" in data

    def test_get_race_forecast(self):
        from server import get_race_forecast
        data = _parse(get_race_forecast())
        assert "race_countdown" in data
        assert "latest_cp" in data

    def test_get_training_context(self):
        from server import get_training_context
        data = _parse(get_training_context())
        assert "athlete_profile" in data
        assert "current_fitness" in data
        assert "recent_training" in data


# ---------------------------------------------------------------------------
# Settings tools
# ---------------------------------------------------------------------------

class TestSettingsTools:
    def test_get_settings(self):
        from server import get_settings
        data = _parse(get_settings())
        assert "config" in data
        config = data["config"]
        assert "training_base" in config
        assert config["training_base"] in ("power", "hr", "pace")

    def test_update_settings_roundtrip(self):
        from server import get_settings, update_settings
        # Read current
        original = _parse(get_settings())
        original_base = original["config"]["training_base"]

        # Update to something different
        new_base = "hr" if original_base != "hr" else "pace"
        _parse(update_settings({"training_base": new_base}))

        # Verify change
        updated = _parse(get_settings())
        assert updated["config"]["training_base"] == new_base

        # Revert
        _parse(update_settings({"training_base": original_base}))

    def test_get_connections(self):
        from server import get_connections
        data = _parse(get_connections())
        assert "connections" in data
        assert isinstance(data["connections"], dict)


# ---------------------------------------------------------------------------
# Plan tools
# ---------------------------------------------------------------------------

class TestPlanTools:
    def test_push_training_plan(self):
        from server import push_training_plan
        csv = (
            "date,workout_type,planned_duration_min,target_power_min,"
            "target_power_max,workout_description\n"
            "2099-01-01,easy,30,180,200,Test easy run\n"
            "2099-01-02,rest,0,0,0,Rest day"
        )
        data = _parse(push_training_plan(csv))
        assert data.get("status") == "saved"
        # rows may be 0 if user already has these dates (upsert dedup)
        assert "rows" in data


# ---------------------------------------------------------------------------
# Sync tools (require running backend, so test graceful fallback)
# ---------------------------------------------------------------------------

class TestSyncTools:
    def test_get_sync_status(self):
        from server import get_sync_status
        data = _parse(get_sync_status())
        # Should return either sync status or DB fallback
        assert isinstance(data, dict)

    def test_trigger_sync_no_backend(self):
        from server import trigger_sync
        data = _parse(trigger_sync())
        # Without a running backend, should return error gracefully
        assert isinstance(data, dict)
