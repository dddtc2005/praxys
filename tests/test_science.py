"""Tests for analysis/science.py — theory loading, validation, and recommendations."""
import pytest

from analysis.science import (
    load_theory,
    load_labels,
    list_theories,
    list_label_sets,
    load_active_science,
    merge_zones_with_labels,
    recommend_science,
    PILLARS,
    TsbZone,
)


class TestLoadTheory:
    """Test loading individual theories from YAML."""

    def test_load_banister_pmc(self):
        theory = load_theory("load", "banister_pmc")
        assert theory.id == "banister_pmc"
        assert theory.pillar == "load"
        assert theory.name == "Banister PMC"
        assert theory.params["ctl_time_constant"] == 42
        assert theory.params["atl_time_constant"] == 7
        assert len(theory.tsb_zones) == 5
        assert len(theory.citations) >= 1

    def test_load_coggan_5zone(self):
        theory = load_theory("zones", "coggan_5zone")
        assert theory.id == "coggan_5zone"
        assert theory.zone_count == 5
        assert "power" in theory.zone_boundaries
        assert len(theory.zone_boundaries["power"]) == 4
        assert theory.zone_names["power"] == ["Recovery", "Endurance", "Tempo", "Threshold", "VO2max"]

    def test_load_critical_power(self):
        theory = load_theory("prediction", "critical_power")
        assert theory.id == "critical_power"
        assert theory.distance_power_fractions["marathon"] == 0.899
        assert theory.riegel_exponent == 1.06

    def test_load_hrv_based_recovery(self):
        theory = load_theory("recovery", "hrv_based")
        assert theory.id == "hrv_based"
        assert theory.params["rolling_days"] == 7
        assert theory.params["baseline_days"] == 30

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_theory("load", "nonexistent_theory")

    def test_pydantic_validation_runs(self):
        """Ensure all existing theories pass Pydantic validation."""
        for pillar in PILLARS:
            for theory in list_theories(pillar):
                # If validation fails, load_theory would raise ValidationError
                assert theory.id


class TestListTheories:
    def test_all_pillars_have_theories(self):
        for pillar in PILLARS:
            theories = list_theories(pillar)
            assert len(theories) >= 1, f"No theories for pillar {pillar}"

    def test_load_pillar_has_two(self):
        theories = list_theories("load")
        ids = [t.id for t in theories]
        assert "banister_pmc" in ids
        assert "banister_ultra" in ids

    def test_recovery_has_single_theory(self):
        theories = list_theories("recovery")
        assert len(theories) == 1
        assert theories[0].id == "hrv_based"


class TestLabels:
    def test_load_standard_labels(self):
        labels = load_labels("standard")
        assert labels.id == "standard"
        assert len(labels.tsb_zone_labels) >= 1

    def test_load_nonexistent_falls_back_to_standard(self):
        labels = load_labels("nonexistent_label_set")
        assert labels.id == "standard"

    def test_list_label_sets(self):
        sets = list_label_sets()
        ids = [s.id for s in sets]
        assert "standard" in ids


class TestMergeZonesWithLabels:
    def test_merge_matches_zones_to_labels(self):
        zones = [TsbZone(min=25), TsbZone(min=5, max=25), TsbZone(max=5)]
        labels = load_labels("standard")
        merged = merge_zones_with_labels(zones, labels)
        assert len(merged) == 3
        assert merged[0].min == 25
        assert merged[0].label  # Should have a label from the label set

    def test_merge_with_fewer_labels_uses_defaults(self):
        zones = [TsbZone(min=i) for i in range(10)]
        labels = load_labels("standard")
        merged = merge_zones_with_labels(zones, labels)
        assert len(merged) == 10
        # Zones beyond label count get default "Zone N" names
        assert merged[9].label.startswith("Zone")


class TestLoadActiveScience:
    def test_loads_all_pillars(self):
        choices = {
            "load": "banister_pmc",
            "recovery": "hrv_based",
            "prediction": "critical_power",
            "zones": "coggan_5zone",
        }
        active = load_active_science(choices)
        assert "load" in active
        assert "recovery" in active
        assert "prediction" in active
        assert "zones" in active

    def test_load_theory_has_labeled_tsb_zones(self):
        choices = {"load": "banister_pmc"}
        active = load_active_science(choices)
        load = active["load"]
        assert len(load.tsb_zones_labeled) > 0
        assert load.tsb_zones_labeled[0].label


class TestRecommendScience:
    def test_returns_all_pillars(self):
        import pandas as pd
        recs = recommend_science(
            pd.DataFrame(), pd.DataFrame(), None, ["garmin"], "power",
        )
        pillars = [r.pillar for r in recs]
        assert "load" in pillars
        assert "recovery" in pillars
        assert "prediction" in pillars
        assert "zones" in pillars

    def test_ultra_recommends_banister_ultra(self):
        import pandas as pd
        recs = recommend_science(
            pd.DataFrame(), pd.DataFrame(), 100.0, ["garmin"], "power",
        )
        load_rec = next(r for r in recs if r.pillar == "load")
        assert load_rec.recommended_id == "banister_ultra"

    def test_recovery_recommends_single_hrv_theory(self):
        import pandas as pd

        recovery_df = pd.DataFrame({"hrv_avg": [50.0] * 42})
        recs = recommend_science(
            pd.DataFrame(), recovery_df, None, ["garmin", "oura"], "power",
        )
        recovery_rec = next(r for r in recs if r.pillar == "recovery")
        assert recovery_rec.recommended_id == "hrv_based"
