"""Zone calculation for all training bases."""
from analysis.config import TrainingBase, DEFAULT_ZONES

# Default zone names per base for Coggan 5-zone (used when no names provided)
_DEFAULT_NAMES: dict[str, list[str]] = {
    "power": ["Easy", "Tempo", "Threshold", "Supra-CP", "VO2max"],
    "hr": ["Recovery", "Aerobic", "Tempo", "Threshold", "VO2max"],
    "pace": ["Recovery", "Easy", "Tempo", "Threshold", "Interval"],
}

_UNITS: dict[str, str] = {"power": "W", "hr": "bpm", "pace": "sec/km"}


def compute_zones(
    base: TrainingBase,
    threshold_value: float,
    custom_boundaries: list[float] | None = None,
    zone_names: list[str] | None = None,
) -> list[dict]:
    """Compute training zones based on training base and threshold.

    Supports variable zone counts: N boundaries produce N+1 zones.

    Args:
        base: "power", "hr", or "pace"
        threshold_value: CP (W), LTHR (bpm), or threshold pace (sec/km)
        custom_boundaries: fractions defining zone boundaries; defaults used if None
        zone_names: optional names for each zone; generic "Zone N" used if None

    Returns:
        List of zone dicts with: name, lower, upper, unit
    """
    boundaries = custom_boundaries or DEFAULT_ZONES[base]
    n_zones = len(boundaries) + 1
    unit = _UNITS.get(base, "")

    # Resolve zone names
    if zone_names and len(zone_names) == n_zones:
        names = zone_names
    elif not custom_boundaries and base in _DEFAULT_NAMES:
        names = _DEFAULT_NAMES[base]
    else:
        names = [f"Zone {i + 1}" for i in range(n_zones)]

    vals = [round(b * threshold_value) for b in boundaries]

    if base in ("power", "hr"):
        # Zones go low → high
        zones = [{"name": names[0], "lower": 0, "upper": vals[0], "unit": unit}]
        for i in range(1, len(vals)):
            zones.append({"name": names[i], "lower": vals[i - 1], "upper": vals[i], "unit": unit})
        zones.append({"name": names[-1], "lower": vals[-1], "upper": None, "unit": unit})
        return zones
    else:  # pace — higher value = slower
        # Zone 1 is slowest (highest sec/km), last zone is fastest (lowest)
        zones = [{"name": names[0], "lower": vals[0], "upper": None, "unit": unit}]
        for i in range(1, len(vals)):
            zones.append({"name": names[i], "lower": vals[i], "upper": vals[i - 1], "unit": unit})
        zones.append({"name": names[-1], "lower": 0, "upper": vals[-1], "unit": unit})
        return zones


def classify_intensity(
    base: TrainingBase,
    value: float,
    threshold: float,
    boundaries: list[float] | None = None,
) -> str:
    """Classify a value into an intensity zone name.

    Supports variable boundary counts. Returns "zone_N" for the matched zone
    (0-indexed), or legacy names for 4-boundary (5-zone) configs.

    Args:
        base: "power", "hr", or "pace"
        value: power (W), HR (bpm), or pace (sec/km)
        threshold: CP, LTHR, or threshold pace
        boundaries: custom zone boundaries (fractions); defaults used if None

    Returns:
        Zone key: e.g. "easy", "tempo", "threshold", "supra_threshold" for 5-zone,
        or "zone_0", "zone_1", etc. for other configs
    """
    bounds = boundaries or DEFAULT_ZONES[base]

    # Legacy 4-boundary (5-zone) names for backward compatibility
    _LEGACY_KEYS = ["easy", "tempo", "threshold", "supra_threshold"]

    if base in ("power", "hr"):
        ratio = value / threshold if threshold > 0 else 0
        # Walk boundaries top-down
        for i in range(len(bounds) - 1, -1, -1):
            if ratio >= bounds[i]:
                zone_idx = i + 1  # zone above this boundary
                if len(bounds) == 4 and zone_idx <= len(_LEGACY_KEYS):
                    return _LEGACY_KEYS[min(zone_idx, len(_LEGACY_KEYS) - 1)]
                return f"zone_{zone_idx}"
        return _LEGACY_KEYS[0] if len(bounds) == 4 else "zone_0"
    else:  # pace — lower value = faster
        ratio = threshold / value if value > 0 else 0
        inv_bounds = [1.0 / b if b > 0 else 0 for b in bounds]
        for i in range(len(inv_bounds) - 1, -1, -1):
            if ratio >= inv_bounds[i]:
                zone_idx = i + 1
                if len(bounds) == 4 and zone_idx <= len(_LEGACY_KEYS):
                    return _LEGACY_KEYS[min(zone_idx, len(_LEGACY_KEYS) - 1)]
                return f"zone_{zone_idx}"
        return _LEGACY_KEYS[0] if len(bounds) == 4 else "zone_0"
