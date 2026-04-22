"""User configuration: connections, preferences, training base, thresholds, zones, goals."""
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Literal
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)

TrainingBase = Literal["power", "hr", "pace"]
PlatformName = Literal["garmin", "stryd", "strava", "oura", "coros"]
PlanSource = Literal["garmin", "stryd", "strava", "oura", "coros", "ai"]
DataCategory = Literal["activities", "recovery", "fitness", "plan"]

# Default zone boundaries as fractions of threshold value.
# 4 boundaries define 5 zones (Z1..Z5).
DEFAULT_ZONES: dict[str, list[float]] = {
    "power": [0.55, 0.75, 0.90, 1.05],   # Coggan-style
    "hr": [0.72, 0.82, 0.89, 0.96],       # Friel-style
    "pace": [1.29, 1.14, 1.06, 1.00],     # Inverted (slower -> faster)
}


class PlatformCaps(TypedDict):
    """Capability flags for a single platform."""
    activities: bool
    recovery: bool
    fitness: bool
    plan: bool


# What each platform can provide.
PLATFORM_CAPABILITIES: dict[str, PlatformCaps] = {
    "garmin": {"activities": True, "recovery": True, "fitness": True, "plan": False},
    "stryd":  {"activities": True, "recovery": False, "fitness": True, "plan": True},
    "strava": {"activities": True, "recovery": False, "fitness": False, "plan": False},
    "oura":   {"activities": False, "recovery": True, "fitness": False, "plan": False},
    "coros":  {"activities": True, "recovery": False, "fitness": True, "plan": False},
}


@dataclass
class UserConfig:
    """Top-level user configuration stored as JSON."""

    # User display name (shown in sidebar, optional)
    display_name: str = ""

    # Unit system: "metric" (km, min/km) or "imperial" (miles, min/mile)
    unit_system: str = "metric"

    # Which platforms the user has connected
    connections: list[str] = field(default_factory=lambda: [
        "garmin", "stryd", "oura",
    ])

    # Which source to trust per data category (where choice is needed).
    # Fitness has no preference — auto-merged from all connected sources.
    preferences: dict[str, str] = field(default_factory=lambda: {
        "activities": "garmin",
        "recovery": "oura",
        "plan": "stryd",
    })

    training_base: TrainingBase = "power"

    thresholds: dict = field(default_factory=lambda: {
        "cp_watts": None,
        "lthr_bpm": None,
        "threshold_pace_sec_km": None,
        "max_hr_bpm": None,
        "rest_hr_bpm": None,
        "source": "auto",
    })

    zones: dict[str, list[float]] = field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_ZONES.items()}
    )

    goal: dict = field(default_factory=lambda: {
        "race_date": "",
        "distance": "marathon",
        "target_time_sec": 0,
    })

    # Science framework: one theory per pillar
    science: dict[str, str] = field(default_factory=lambda: {
        "load": "banister_pmc",
        "recovery": "hrv_based",
        "prediction": "critical_power",
        "zones": "coggan_5zone",
    })

    # Per-activity-type source routing.  Keys are activity types (e.g.
    # "running", "cycling") or the catch-all "default".  Values are platform
    # names (e.g. "garmin", "stryd").
    activity_routing: dict[str, str] = field(default_factory=lambda: {
        "default": "garmin",
    })

    # Display preference for zone labels (cosmetic, does not affect math)
    zone_labels: str = "standard"

    source_options: dict = field(default_factory=lambda: {
        "garmin_region": "international",  # "international" or "cn"
    })

    # UI language preference: "en" | "zh" | None (None = auto-detect from browser)
    language: str | None = None

    def __post_init__(self) -> None:
        """Validate cross-field constraints."""
        # Validate preferences reference connected platforms with matching capabilities.
        # "ai" is a special plan source — not a platform, so skip platform checks for it.
        for category, platform in self.preferences.items():
            if not platform:
                continue
            if category == "plan" and platform == "ai":
                continue  # AI is a valid plan source, not a platform
            if platform not in self.connections:
                continue  # Tolerate — platform may be disconnected temporarily
            caps = PLATFORM_CAPABILITIES.get(platform)
            if caps and category in caps and not caps[category]:
                logger.warning(
                    "%s does not support %s, but is set as preference",
                    platform, category,
                )
        # Filter empty strings from connections (from migration edge cases)
        self.connections = [c for c in self.connections if c]
        # Ensure activity_routing has a "default" entry
        if "default" not in self.activity_routing:
            self.activity_routing["default"] = self.preferences.get(
                "activities", "garmin"
            )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "config.json"
)


def _migrate_config(data: dict) -> dict:
    """Migrate old config format (sources) to new format (connections + preferences).

    Old format:  {"sources": {"activities": "garmin", "health": "oura", "plan": "stryd"}}
    New format:  {"connections": ["garmin", "stryd", "oura"],
                  "preferences": {"activities": "garmin", "recovery": "oura", "plan": "stryd"}}
    """
    if "sources" in data and "connections" not in data:
        sources = data.pop("sources")
        # Derive connections from unique source values, filtering empty strings
        data["connections"] = [v for v in dict.fromkeys(sources.values()) if v]
        # Map old "health" key to new "recovery" key
        data["preferences"] = {
            "activities": sources.get("activities", "garmin"),
            "recovery": sources.get("health", "oura"),
            "plan": sources.get("plan", "stryd"),
        }

    # Migrate preferences.activities -> activity_routing
    prefs = data.get("preferences", {})
    if prefs.get("activities") and "activity_routing" not in data:
        data["activity_routing"] = {"default": prefs["activities"]}

    return data


def load_config(config_path: str | None = None) -> UserConfig:
    """Load user config from JSON file. Returns defaults if file missing."""
    path = config_path or _DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        return UserConfig()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data = _migrate_config(data)
    return UserConfig(**data)


def save_config(config: UserConfig, config_path: str | None = None) -> None:
    """Persist user config to JSON file."""
    path = config_path or _DEFAULT_CONFIG_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(config), f, indent=2)


# ---------------------------------------------------------------------------
# Database-based config (multi-user deployable architecture)
# ---------------------------------------------------------------------------


def load_config_from_db(user_id: str, db) -> UserConfig:
    """Load user config from database.

    Args:
        user_id: The user's ID.
        db: A SQLAlchemy sync Session.

    Returns:
        A UserConfig dataclass populated from the DB, or defaults if not found.
    """
    from db.models import UserConfig as UserConfigModel

    row = db.query(UserConfigModel).filter(UserConfigModel.user_id == user_id).first()
    if not row:
        return UserConfig()

    # Preferences: use stored preferences if set, otherwise derive from connections
    stored_prefs = row.preferences if row.preferences else {}
    derived_prefs = _get_preferences_from_db(user_id, db)
    # Merge: stored prefs take priority, fill gaps from derived
    merged_prefs = {**derived_prefs, **stored_prefs}

    return UserConfig(
        display_name=row.display_name or "",
        unit_system=getattr(row, "unit_system", "metric") or "metric",
        connections=_get_connections_from_db(user_id, db),
        preferences=merged_prefs,
        training_base=row.training_base or "power",
        thresholds=row.thresholds or {},
        zones=row.zones or {k: list(v) for k, v in DEFAULT_ZONES.items()},
        goal=row.goal or {},
        science=row.science or {},
        zone_labels=row.zone_labels or "standard",
        activity_routing=row.activity_routing or {"default": "garmin"},
        source_options=row.source_options or {},
        language=getattr(row, "language", None),
    )


def _get_connections_from_db(user_id: str, db) -> list[str]:
    """Get connected platform names from user_connections table."""
    from db.models import UserConnection

    rows = (
        db.query(UserConnection.platform)
        .filter(
            UserConnection.user_id == user_id,
            UserConnection.status.in_(["connected", "error"]),
        )
        .all()
    )
    return [r[0] for r in rows]


def _get_preferences_from_db(user_id: str, db) -> dict:
    """Derive preferences from user_connections.

    Builds a category -> platform mapping from connection preferences.
    """
    from db.models import UserConnection

    prefs = {}
    rows = (
        db.query(UserConnection)
        .filter(
            UserConnection.user_id == user_id,
            UserConnection.status.in_(["connected", "error"]),
        )
        .all()
    )
    for row in rows:
        conn_prefs = row.preferences or {}
        for category, enabled in conn_prefs.items():
            if enabled and category not in prefs:
                prefs[category] = row.platform
    return prefs


def save_config_to_db(user_id: str, config: UserConfig, db) -> None:
    """Save user config to database.

    Args:
        user_id: The user's ID.
        config: The UserConfig dataclass to persist.
        db: A SQLAlchemy sync Session.
    """
    from db.models import UserConfig as UserConfigModel

    row = db.query(UserConfigModel).filter(UserConfigModel.user_id == user_id).first()
    if not row:
        row = UserConfigModel(user_id=user_id)
        db.add(row)

    row.display_name = config.display_name
    row.unit_system = config.unit_system
    row.training_base = config.training_base
    row.preferences = config.preferences
    row.thresholds = config.thresholds
    row.zones = config.zones
    row.goal = config.goal
    row.science = config.science
    row.zone_labels = config.zone_labels
    row.activity_routing = config.activity_routing
    row.source_options = config.source_options
    row.language = config.language
    db.commit()
