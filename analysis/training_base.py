"""Display configuration per training base — labels, units, zone names."""
from analysis.config import TrainingBase


def get_display_config(base: TrainingBase) -> dict:
    """Return display labels, units, and zone names for the active training base.

    Included in every API response so the frontend never hardcodes labels.
    """
    if base == "power":
        return {
            "threshold_label": "Critical Power",
            "threshold_abbrev": "CP",
            "threshold_unit": "W",
            "load_label": "RSS",
            "load_unit": "",
            "intensity_metric": "Power",
            "zone_names": ["Recovery", "Endurance", "Tempo", "Threshold", "VO2max"],
            "trend_label": "CP Trend",
        }
    elif base == "hr":
        return {
            "threshold_label": "Lactate Threshold HR",
            "threshold_abbrev": "LTHR",
            "threshold_unit": "bpm",
            "load_label": "TRIMP",
            "load_unit": "",
            "intensity_metric": "Heart Rate",
            "zone_names": ["Recovery", "Endurance", "Tempo", "Threshold", "VO2max"],
            "trend_label": "LTHR Trend",
        }
    else:  # pace
        return {
            "threshold_label": "Threshold Pace",
            "threshold_abbrev": "TP",
            "threshold_unit": "/km",
            "load_label": "rTSS",
            "load_unit": "",
            "intensity_metric": "Pace",
            "zone_names": ["Recovery", "Endurance", "Tempo", "Threshold", "VO2max"],
            "trend_label": "Threshold Pace Trend",
        }
