"""Science framework: load, validate, and recommend training theories.

Each pillar (load, recovery, prediction, zones) has multiple theories stored
as YAML files in data/science/{pillar}/. Label sets (cosmetic zone names)
are stored in data/science/labels/.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

PILLARS = ("load", "recovery", "prediction", "zones")

_SCIENCE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "science")


@dataclass
class Citation:
    key: str
    title: str
    year: int | None = None
    authors: str | None = None
    journal: str | None = None
    url: str | None = None
    note: str | None = None


@dataclass
class TsbZone:
    """A single TSB zone boundary (math only, no labels)."""
    min: float | None = None
    max: float | None = None


@dataclass
class TsbZoneLabeled:
    """TSB zone with boundary + display label (merged from theory + labels)."""
    min: float | None = None
    max: float | None = None
    label: str = ""
    color: str = "#64748b"
    description: str = ""


@dataclass
class Theory:
    """A training science theory for one pillar."""
    id: str
    pillar: str
    name: str
    description: str
    simple_description: str = ""
    advanced_description: str = ""
    author: str = "system"
    citations: list[Citation] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    tsb_zones: list[TsbZone] = field(default_factory=list)
    # Populated after merging with label file:
    tsb_zones_labeled: list[TsbZoneLabeled] = field(default_factory=list)
    # Raw YAML data for pillar-specific params:
    signal: dict[str, Any] = field(default_factory=dict)
    diagnosis: dict[str, Any] = field(default_factory=dict)
    # Zone framework specific:
    zone_boundaries: dict[str, list[float]] = field(default_factory=dict)
    zone_names: dict[str, list[str]] = field(default_factory=dict)
    zone_count: int = 5
    target_distribution: list[float] = field(default_factory=list)
    # Prediction specific:
    distance_power_fractions: dict[str, float] = field(default_factory=dict)
    riegel_exponent: float = 1.06
    threshold_reference_km: float = 10.0


@dataclass
class LabelSet:
    """Display labels for TSB zones (cosmetic only)."""
    id: str
    name: str
    tsb_zone_labels: list[dict[str, str]] = field(default_factory=list)


@dataclass
class PillarRecommendation:
    pillar: str
    recommended_id: str
    reason: str
    confidence: str  # "strong" | "moderate" | "weak"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _parse_citations(raw: list[dict] | None) -> list[Citation]:
    if not raw:
        return []
    return [Citation(**{k: v for k, v in c.items() if k in Citation.__dataclass_fields__}) for c in raw]


def _parse_tsb_zones(raw: list[dict] | None) -> list[TsbZone]:
    if not raw:
        return []
    return [TsbZone(min=z.get("min"), max=z.get("max")) for z in raw]


def load_theory(pillar: str, theory_id: str) -> Theory:
    """Load a single theory YAML file.

    Validates params against the pillar-specific Pydantic schema at load time.
    Raises pydantic.ValidationError if required fields are missing or wrong type.
    """
    from analysis.theory_schema import validate_theory_params

    path = os.path.join(_SCIENCE_DIR, pillar, f"{theory_id}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Theory not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Validate params against pillar schema (fail fast on bad YAML)
    raw_params = data.get("params", {})
    validate_theory_params(pillar, raw_params)

    theory = Theory(
        id=data["id"],
        pillar=data.get("pillar", pillar),
        name=data["name"],
        description=data.get("description", ""),
        simple_description=data.get("simple_description", ""),
        advanced_description=data.get("advanced_description", ""),
        author=data.get("author", "system"),
        citations=_parse_citations(data.get("citations")),
        params=data.get("params", {}),
        tsb_zones=_parse_tsb_zones(data.get("tsb_zones")),
        signal=data.get("signal", {}),
        diagnosis=data.get("diagnosis", {}),
    )

    # Prediction-specific fields
    params = theory.params
    if "distance_power_fractions" in params:
        theory.distance_power_fractions = params["distance_power_fractions"]
    if "riegel_exponent" in params:
        theory.riegel_exponent = params["riegel_exponent"]
    if "threshold_reference_km" in params:
        theory.threshold_reference_km = params["threshold_reference_km"]

    # Zone-specific fields
    if "boundaries" in params:
        theory.zone_boundaries = params["boundaries"]
    if "zone_names" in params:
        theory.zone_names = params["zone_names"]
    if "zone_count" in params:
        theory.zone_count = params["zone_count"]
    if "target_distribution" in params:
        theory.target_distribution = params["target_distribution"]

    return theory


def load_labels(label_id: str) -> LabelSet:
    """Load a label set YAML file."""
    path = os.path.join(_SCIENCE_DIR, "labels", f"{label_id}.yaml")
    if not os.path.exists(path):
        # Fall back to standard labels
        path = os.path.join(_SCIENCE_DIR, "labels", "standard.yaml")
        if not os.path.exists(path):
            return LabelSet(id="standard", name="Standard")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return LabelSet(
        id=data.get("id", label_id),
        name=data.get("name", label_id),
        tsb_zone_labels=data.get("tsb_zone_labels", []),
    )


def merge_zones_with_labels(
    zones: list[TsbZone], labels: LabelSet
) -> list[TsbZoneLabeled]:
    """Merge theory zone boundaries with label-set display info."""
    result = []
    label_list = labels.tsb_zone_labels or []
    for i, zone in enumerate(zones):
        lbl = label_list[i] if i < len(label_list) else {}
        result.append(TsbZoneLabeled(
            min=zone.min,
            max=zone.max,
            label=lbl.get("label", f"Zone {i + 1}"),
            color=lbl.get("color", "#64748b"),
            description=lbl.get("description", ""),
        ))
    return result


def list_theories(pillar: str) -> list[Theory]:
    """List all available theories for a pillar."""
    pillar_dir = os.path.join(_SCIENCE_DIR, pillar)
    if not os.path.isdir(pillar_dir):
        return []
    theories = []
    for fname in sorted(os.listdir(pillar_dir)):
        if fname.endswith(".yaml") or fname.endswith(".yml"):
            theory_id = fname.rsplit(".", 1)[0]
            try:
                theories.append(load_theory(pillar, theory_id))
            except (FileNotFoundError, KeyError, yaml.YAMLError) as e:
                logger.warning("Failed to load theory %s/%s: %s", pillar, theory_id, e)
                continue
    return theories


def list_label_sets() -> list[LabelSet]:
    """List all available label sets."""
    labels_dir = os.path.join(_SCIENCE_DIR, "labels")
    if not os.path.isdir(labels_dir):
        return []
    sets = []
    for fname in sorted(os.listdir(labels_dir)):
        if fname.endswith(".yaml") or fname.endswith(".yml"):
            label_id = fname.rsplit(".", 1)[0]
            try:
                sets.append(load_labels(label_id))
            except (FileNotFoundError, KeyError, yaml.YAMLError) as e:
                logger.warning("Failed to load label set %s: %s", label_id, e)
                continue
    return sets


def load_active_science(
    science_choices: dict[str, str],
    zone_labels: str = "standard",
) -> dict[str, Theory]:
    """Load the user's active theory for each pillar, with labels applied."""
    labels = load_labels(zone_labels)
    result = {}
    for pillar in PILLARS:
        theory_id = science_choices.get(pillar)
        if not theory_id:
            # Use first available theory as fallback
            available = list_theories(pillar)
            theory_id = available[0].id if available else None
        if theory_id:
            try:
                theory = load_theory(pillar, theory_id)
                if theory.tsb_zones:
                    theory.tsb_zones_labeled = merge_zones_with_labels(
                        theory.tsb_zones, labels
                    )
                result[pillar] = theory
            except FileNotFoundError:
                pass
    return result


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------

def recommend_science(
    activities: Any,
    recovery: Any,
    goal_distance_km: float | None,
    connected_platforms: list[str],
    training_base: str,
) -> list[PillarRecommendation]:
    """Analyze recent training to recommend one theory per pillar."""
    import pandas as pd

    recs: list[PillarRecommendation] = []

    # ── Pillar 1: Load ─────────────────────────────────────────────────
    avg_session_min = 0.0
    longest_run_km = 0.0
    if isinstance(activities, pd.DataFrame) and not activities.empty:
        recent = activities.tail(42)  # ~6 weeks
        if "duration_sec" in recent.columns:
            durations = pd.to_numeric(recent["duration_sec"], errors="coerce").dropna()
            avg_session_min = durations.mean() / 60 if not durations.empty else 0
        if "distance_km" in recent.columns:
            dists = pd.to_numeric(recent["distance_km"], errors="coerce").dropna()
            longest_run_km = float(dists.max()) if not dists.empty else 0

    is_ultra = (
        (goal_distance_km is not None and goal_distance_km >= 50)
        or longest_run_km >= 35
        or avg_session_min >= 120
    )

    if is_ultra:
        recs.append(PillarRecommendation(
            "load", "banister_ultra",
            f"Long sessions (avg {avg_session_min:.0f}min) and/or ultra goal distance",
            "strong" if (goal_distance_km and goal_distance_km >= 50) else "moderate",
        ))
    else:
        recs.append(PillarRecommendation(
            "load", "banister_pmc",
            "Best general-purpose model for 5K–marathon training",
            "strong",
        ))

    # ── Pillar 2: Recovery ─────────────────────────────────────────────
    hrv_coverage = 0.0
    if isinstance(recovery, pd.DataFrame) and not recovery.empty:
        if "hrv_avg" in recovery.columns:
            recent_rec = recovery.tail(42)
            hrv_valid = pd.to_numeric(recent_rec["hrv_avg"], errors="coerce").notna().sum()
            hrv_coverage = hrv_valid / max(len(recent_rec), 1)

    reason = (
        f"Use the canonical HRV-based recovery model ({hrv_coverage:.0%} recent HRV coverage)"
        if hrv_coverage > 0
        else "Use the canonical HRV-based recovery model (recovery unavailable until HRV data exists)"
    )
    recs.append(PillarRecommendation(
        "recovery", "hrv_based", reason, "strong",
    ))

    # ── Pillar 3: Prediction ───────────────────────────────────────────
    has_cp = False
    if isinstance(activities, pd.DataFrame) and "cp_estimate" in activities.columns:
        cp_vals = pd.to_numeric(activities["cp_estimate"], errors="coerce").dropna()
        has_cp = len(cp_vals) >= 3

    if training_base == "power" and has_cp:
        recs.append(PillarRecommendation(
            "prediction", "critical_power",
            "Power data with CP estimates available — most accurate predictions",
            "strong",
        ))
    else:
        recs.append(PillarRecommendation(
            "prediction", "riegel",
            "Riegel formula works well with pace/HR data",
            "moderate",
        ))

    # ── Pillar 4: Zones ────────────────────────────────────────────────
    # Default to Coggan; could analyze distribution to suggest polarized
    recs.append(PillarRecommendation(
        "zones", "coggan_5zone",
        "Standard 5-zone model for structured training",
        "strong",
    ))

    return recs
