"""Tests for analysis/zones.py — zone computation and intensity classification."""
import pytest

from analysis.zones import compute_zones, classify_intensity


class TestComputeZones:
    def test_power_5zone_default(self):
        zones = compute_zones("power", 250)
        assert len(zones) == 5
        assert zones[0]["name"] == "Recovery"
        assert zones[0]["lower"] == 0
        assert zones[0]["upper"] == 138  # round(0.55 * 250)
        assert zones[-1]["name"] == "VO2max"
        assert zones[-1]["upper"] is None

    def test_hr_5zone_default(self):
        zones = compute_zones("hr", 170)
        assert len(zones) == 5
        assert zones[0]["unit"] == "bpm"
        assert zones[0]["name"] == "Recovery"

    def test_pace_zones_inverted(self):
        """Pace zones: higher value = slower. Zone 1 is slowest."""
        zones = compute_zones("pace", 300)
        assert len(zones) == 5
        # Zone 1 (Recovery) should have the highest sec/km values
        assert zones[0]["lower"] > zones[1]["lower"]

    def test_custom_3zone_boundaries(self):
        zones = compute_zones("power", 250, custom_boundaries=[0.80, 1.00])
        assert len(zones) == 3
        # Default names should be "Zone 1", "Zone 2", "Zone 3"
        assert zones[0]["name"] == "Zone 1"
        assert zones[2]["name"] == "Zone 3"

    def test_custom_names_applied(self):
        zones = compute_zones(
            "power", 250,
            custom_boundaries=[0.80, 1.00],
            zone_names=["Easy", "Moderate", "Hard"],
        )
        assert zones[0]["name"] == "Easy"
        assert zones[1]["name"] == "Moderate"
        assert zones[2]["name"] == "Hard"

    def test_wrong_name_count_uses_generic(self):
        """If zone_names count doesn't match zone count, fall back to generic."""
        zones = compute_zones(
            "power", 250,
            custom_boundaries=[0.80, 1.00],
            zone_names=["A", "B"],  # 2 names for 3 zones
        )
        assert zones[0]["name"] == "Zone 1"


class TestClassifyIntensity:
    def test_power_easy_zone(self):
        result = classify_intensity("power", 100, 250)
        assert result == "easy"

    def test_power_tempo_zone(self):
        result = classify_intensity("power", 160, 250)
        assert result == "tempo"

    def test_power_threshold_zone(self):
        result = classify_intensity("power", 210, 250)
        assert result == "threshold"

    def test_power_supra_zone(self):
        result = classify_intensity("power", 250, 250)
        assert result == "supra_threshold"

    def test_hr_classification(self):
        result = classify_intensity("hr", 100, 170)
        assert result == "easy"

    def test_pace_easy(self):
        """Slow pace (high sec/km) should classify as easy."""
        result = classify_intensity("pace", 400, 300)
        assert result == "easy"

    def test_pace_fast(self):
        """Fast pace (low sec/km) should classify as high intensity."""
        result = classify_intensity("pace", 280, 300)
        assert result in ("threshold", "supra_threshold")

    def test_3zone_boundaries_return_zone_N(self):
        """Non-5-zone configs should return zone_N keys."""
        result = classify_intensity("power", 100, 250, boundaries=[0.80, 1.00])
        assert result == "zone_0"
        result = classify_intensity("power", 220, 250, boundaries=[0.80, 1.00])
        assert result == "zone_1"
        result = classify_intensity("power", 260, 250, boundaries=[0.80, 1.00])
        assert result == "zone_2"

    def test_zero_threshold_handled(self):
        result = classify_intensity("power", 100, 0)
        assert isinstance(result, str)
