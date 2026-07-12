"""Compatibility constants for deterministic Today responses."""

# Strip this server-owned key from legacy persisted daily-brief metadata.
DAILY_BRIEF_FRESHNESS_KEY = "daily_brief_freshness"

# Cache/ETag salt for the deterministic /api/today representation.
TODAY_RESPONSE_VERSION = "metric-provenance-today-v2"
TRAINING_RESPONSE_VERSION = "evidence-summary-v2"
PLAN_RESPONSE_VERSION = "connection-aware-plan-v2"