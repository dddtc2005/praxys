"""Tests for analysis/config.py — config loading, saving, and migration."""
import json
import os
import tempfile

import pytest

from analysis.config import (
    UserConfig,
    load_config,
    save_config,
    _migrate_config,
    DEFAULT_ZONES,
)


class TestUserConfigDefaults:
    def test_default_connections(self):
        config = UserConfig()
        assert config.connections == ["garmin", "stryd", "oura"]

    def test_default_preferences(self):
        config = UserConfig()
        assert config.preferences["activities"] == "garmin"
        assert config.preferences["recovery"] == "oura"
        assert config.preferences["plan"] == "stryd"

    def test_default_training_base(self):
        config = UserConfig()
        assert config.training_base == "power"

    def test_default_zones_match_constants(self):
        config = UserConfig()
        assert config.zones["power"] == DEFAULT_ZONES["power"]
        assert config.zones["hr"] == DEFAULT_ZONES["hr"]
        assert config.zones["pace"] == DEFAULT_ZONES["pace"]

    def test_default_science_choices(self):
        config = UserConfig()
        assert config.science["load"] == "banister_pmc"
        assert config.science["zones"] == "coggan_5zone"


class TestMigrateConfig:
    def test_old_sources_format_migrated(self):
        old = {
            "sources": {
                "activities": "garmin",
                "health": "oura",
                "plan": "stryd",
            }
        }
        migrated = _migrate_config(old)
        assert "sources" not in migrated
        assert set(migrated["connections"]) == {"garmin", "oura", "stryd"}
        assert migrated["preferences"]["activities"] == "garmin"
        assert migrated["preferences"]["recovery"] == "oura"
        assert migrated["preferences"]["plan"] == "stryd"

    def test_new_format_unchanged(self):
        new = {
            "connections": ["garmin"],
            "preferences": {"activities": "garmin"},
        }
        migrated = _migrate_config(new)
        assert migrated == new

    def test_empty_sources_handled(self):
        old = {"sources": {"activities": "", "health": "", "plan": ""}}
        migrated = _migrate_config(old)
        assert migrated["connections"] == []


class TestLoadSaveConfig:
    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "config.json")
            config = UserConfig()
            config.training_base = "hr"
            config.connections = ["garmin"]
            save_config(config, path)
            loaded = load_config(path)
            assert loaded.training_base == "hr"
            assert loaded.connections == ["garmin"]

    def test_load_missing_file_returns_defaults(self):
        config = load_config("/nonexistent/path/config.json")
        assert config.training_base == "power"
        assert config.connections == ["garmin", "stryd", "oura"]

    def test_save_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "subdir", "config.json")
            save_config(UserConfig(), path)
            assert os.path.exists(path)

    def test_saved_json_is_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "config.json")
            save_config(UserConfig(), path)
            with open(path) as f:
                data = json.load(f)
            assert "connections" in data
            assert "training_base" in data


class TestActivityRouting:
    def test_default_activity_routing(self):
        config = UserConfig()
        assert config.activity_routing == {"default": "garmin"}

    def test_migrate_preferences_to_activity_routing(self):
        """Old config with preferences.activities but no activity_routing gets migrated."""
        old = {
            "connections": ["garmin", "stryd"],
            "preferences": {"activities": "stryd", "recovery": "oura", "plan": "stryd"},
        }
        migrated = _migrate_config(old)
        assert migrated["activity_routing"] == {"default": "stryd"}

    def test_existing_activity_routing_not_overwritten(self):
        """If activity_routing already exists, migration does not overwrite it."""
        data = {
            "connections": ["garmin", "stryd"],
            "preferences": {"activities": "garmin", "recovery": "oura", "plan": "stryd"},
            "activity_routing": {"default": "stryd", "cycling": "garmin"},
        }
        migrated = _migrate_config(data)
        assert migrated["activity_routing"] == {"default": "stryd", "cycling": "garmin"}

    def test_post_init_ensures_default_key(self):
        """__post_init__ adds 'default' key if missing from activity_routing."""
        config = UserConfig(activity_routing={"running": "stryd"})
        assert "default" in config.activity_routing
        assert config.activity_routing["default"] == "garmin"

    def test_roundtrip_with_activity_routing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "config.json")
            config = UserConfig(activity_routing={"default": "stryd", "cycling": "garmin"})
            save_config(config, path)
            loaded = load_config(path)
            assert loaded.activity_routing == {"default": "stryd", "cycling": "garmin"}


class TestPostInit:
    def test_empty_strings_filtered_from_connections(self):
        config = UserConfig(connections=["garmin", "", "stryd", ""])
        assert config.connections == ["garmin", "stryd"]
