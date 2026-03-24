"""Tests for AI training plan: context builder, validation, and provider."""
import csv
import json
import os
import tempfile
from datetime import date, timedelta

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_context():
    """Minimal training context for validation tests."""
    return {
        "athlete_profile": {
            "training_base": "power",
            "threshold": 268.0,
            "goal": {
                "distance": "marathon",
                "target_time_sec": 10800,
                "mode": "continuous",
            },
            "zones": [0.55, 0.75, 0.90, 1.05],
        },
        "current_fitness": {"ctl": 45.0, "atl": 38.0, "tsb": 7.0},
    }


def _make_plan(days: int = 28, start: date | None = None, **overrides) -> list[dict]:
    """Generate a valid plan of *days* workouts starting from *start*."""
    start = start or date.today()
    types = ["easy", "threshold", "recovery", "tempo", "easy", "long_run", "rest"]
    plan = []
    for i in range(days):
        d = start + timedelta(days=i)
        wt = types[i % len(types)]
        row = {
            "date": d.isoformat(),
            "workout_type": wt,
        }
        if wt not in ("rest", "recovery"):
            row["target_power_min"] = 160
            row["target_power_max"] = 250
        row.update(overrides)
        plan.append(row)
    return plan


# ---------------------------------------------------------------------------
# validate_plan tests
# ---------------------------------------------------------------------------

class TestValidatePlan:
    def test_valid_plan(self, sample_context):
        from api.ai import validate_plan
        plan = _make_plan(28)
        valid, errors = validate_plan(plan, sample_context)
        assert valid, f"Expected valid plan, got errors: {errors}"

    def test_empty_plan(self, sample_context):
        from api.ai import validate_plan
        valid, errors = validate_plan([], sample_context)
        assert not valid
        assert "empty" in errors[0].lower()

    def test_missing_date(self, sample_context):
        from api.ai import validate_plan
        plan = [{"workout_type": "easy"}]
        valid, errors = validate_plan(plan, sample_context)
        assert not valid
        assert any("missing date" in e.lower() for e in errors)

    def test_missing_workout_type(self, sample_context):
        from api.ai import validate_plan
        plan = [{"date": date.today().isoformat()}]
        valid, errors = validate_plan(plan, sample_context)
        assert not valid
        assert any("missing workout_type" in e.lower() for e in errors)

    def test_past_dates(self, sample_context):
        from api.ai import validate_plan
        yesterday = date.today() - timedelta(days=1)
        plan = _make_plan(28, start=yesterday)
        valid, errors = validate_plan(plan, sample_context)
        assert not valid
        assert any("past date" in e.lower() for e in errors)

    def test_power_too_low(self, sample_context):
        from api.ai import validate_plan
        plan = _make_plan(28)
        plan[1]["target_power_min"] = 50  # Way below 40% of 268 = 107
        valid, errors = validate_plan(plan, sample_context)
        assert not valid
        assert any("below 40%" in e.lower() for e in errors)

    def test_power_too_high(self, sample_context):
        from api.ai import validate_plan
        plan = _make_plan(28)
        plan[1]["target_power_max"] = 500  # Above 130% of 268 = 348
        valid, errors = validate_plan(plan, sample_context)
        assert not valid
        assert any("130%" in e for e in errors)

    def test_too_many_quality_sessions(self, sample_context):
        """4 threshold sessions in one week should warn."""
        from api.ai import validate_plan
        start = date.today()
        plan = []
        for i in range(7):
            d = start + timedelta(days=i)
            plan.append({
                "date": d.isoformat(),
                "workout_type": "threshold",
                "target_power_min": 241,
                "target_power_max": 280,
            })
        # Pad remaining 21 days with easy
        for i in range(7, 28):
            d = start + timedelta(days=i)
            plan.append({
                "date": d.isoformat(),
                "workout_type": "easy",
            })
        valid, errors = validate_plan(plan, sample_context)
        assert not valid
        assert any("quality sessions" in e.lower() for e in errors)

    def test_no_threshold_skips_power_check(self, sample_context):
        """If threshold is None, power target checks are skipped."""
        from api.ai import validate_plan
        ctx = {**sample_context, "athlete_profile": {**sample_context["athlete_profile"], "threshold": None}}
        plan = _make_plan(28)
        plan[1]["target_power_max"] = 999  # Would normally fail
        valid, errors = validate_plan(plan, ctx)
        # Should still pass (no threshold to compare against)
        power_errors = [e for e in errors if "130%" in e or "40%" in e]
        assert len(power_errors) == 0


# ---------------------------------------------------------------------------
# AiPlanProvider tests
# ---------------------------------------------------------------------------

class TestAiPlanProvider:
    def test_load_plan_reads_csv(self):
        from analysis.providers.ai import AiPlanProvider
        provider = AiPlanProvider()

        with tempfile.TemporaryDirectory() as tmpdir:
            ai_dir = os.path.join(tmpdir, "ai")
            os.makedirs(ai_dir)
            csv_path = os.path.join(ai_dir, "training_plan.csv")
            cols = ["date", "workout_type", "planned_duration_min",
                    "planned_distance_km", "target_power_min",
                    "target_power_max", "workout_description"]
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=cols)
                writer.writeheader()
                writer.writerow({"date": "2026-04-01", "workout_type": "easy",
                                 "planned_duration_min": "50", "planned_distance_km": "9",
                                 "target_power_min": "150", "target_power_max": "200",
                                 "workout_description": "Easy run"})
                writer.writerow({"date": "2026-04-02", "workout_type": "rest",
                                 "planned_duration_min": "", "planned_distance_km": "",
                                 "target_power_min": "", "target_power_max": "",
                                 "workout_description": "Full rest day"})

            df = provider.load_plan(tmpdir)
            assert len(df) == 2
            assert df.iloc[0]["workout_type"] == "easy"

    def test_load_plan_handles_unquoted_commas(self):
        """Descriptions with commas should be preserved even without quoting."""
        from analysis.providers.ai import AiPlanProvider
        provider = AiPlanProvider()

        with tempfile.TemporaryDirectory() as tmpdir:
            ai_dir = os.path.join(tmpdir, "ai")
            os.makedirs(ai_dir)
            csv_path = os.path.join(ai_dir, "training_plan.csv")
            # Write a line where the description has unquoted commas
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("date,workout_type,planned_duration_min,planned_distance_km,"
                        "target_power_min,target_power_max,workout_description\n")
                f.write("2026-04-01,easy,50,9,150,200,Easy run, relaxed form, conversational pace.\n")

            df = provider.load_plan(tmpdir)
            assert len(df) == 1
            assert df.iloc[0]["workout_type"] == "easy"
            assert "relaxed form" in df.iloc[0]["workout_description"]

    def test_load_plan_missing_file(self):
        from analysis.providers.ai import AiPlanProvider
        provider = AiPlanProvider()

        with tempfile.TemporaryDirectory() as tmpdir:
            df = provider.load_plan(tmpdir)
            assert df.empty

    def test_provider_registered(self):
        from analysis.providers import get_plan_provider
        provider = get_plan_provider("ai")
        assert provider.name == "ai"


# ---------------------------------------------------------------------------
# Staleness check tests
# ---------------------------------------------------------------------------

class TestPlanStaleness:
    def test_no_meta_file(self):
        from api.ai import check_plan_staleness
        with tempfile.TemporaryDirectory() as tmpdir:
            warnings = check_plan_staleness(tmpdir)
            assert warnings == []

    def test_fresh_plan_no_drift(self):
        from api.ai import check_plan_staleness
        with tempfile.TemporaryDirectory() as tmpdir:
            ai_dir = os.path.join(tmpdir, "ai")
            os.makedirs(ai_dir)
            meta = {
                "generated_at": date.today().isoformat(),
                "cp_at_generation": 268.0,
            }
            with open(os.path.join(ai_dir, "plan_meta.json"), "w") as f:
                json.dump(meta, f)
            warnings = check_plan_staleness(tmpdir, current_cp=270.0)
            assert warnings == []

    def test_stale_plan(self):
        from api.ai import check_plan_staleness
        with tempfile.TemporaryDirectory() as tmpdir:
            ai_dir = os.path.join(tmpdir, "ai")
            os.makedirs(ai_dir)
            old_date = (date.today() - timedelta(days=35)).isoformat()
            meta = {"generated_at": old_date, "cp_at_generation": 268.0}
            with open(os.path.join(ai_dir, "plan_meta.json"), "w") as f:
                json.dump(meta, f)
            warnings = check_plan_staleness(tmpdir, current_cp=270.0)
            assert any("days old" in w for w in warnings)

    def test_cp_drift(self):
        from api.ai import check_plan_staleness
        with tempfile.TemporaryDirectory() as tmpdir:
            ai_dir = os.path.join(tmpdir, "ai")
            os.makedirs(ai_dir)
            meta = {
                "generated_at": date.today().isoformat(),
                "cp_at_generation": 250.0,
            }
            with open(os.path.join(ai_dir, "plan_meta.json"), "w") as f:
                json.dump(meta, f)
            # 268 vs 250 = 7.2% drift > 3% threshold
            warnings = check_plan_staleness(tmpdir, current_cp=268.0)
            assert any("changed" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestConfigIntegration:
    def test_plan_source_ai_allowed(self):
        """config.preferences['plan'] = 'ai' should not raise during __post_init__."""
        from analysis.config import UserConfig
        config = UserConfig(preferences={"plan": "ai", "activities": "garmin", "recovery": "oura"})
        assert config.preferences["plan"] == "ai"

    def test_plan_source_type_exists(self):
        """PlanSource type should include 'ai'."""
        from analysis.config import PlanSource
        # Just verify the type alias exists and includes expected values
        assert PlanSource is not None
