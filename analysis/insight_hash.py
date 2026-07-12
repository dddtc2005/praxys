"""Per-insight-type dataset fingerprinting.

The post-sync insight runner uses a SHA-256 of a canonicalized projection of
the inputs that actually affect each insight type. When the projection
matches the ``meta.dataset_hash`` stored on a previous ``AiInsight`` row, we
skip regeneration — content-addressable cache.

Design notes:
- Numerical inputs are bucketed (e.g. CTL rounded to 0.5) so insignificant
  drift between syncs doesn't burn an LLM call.
- ``science_pillars`` are folded into every projection so that switching e.g.
  the load model from Banister to Seiler naturally invalidates the hash and
  triggers regeneration on the next sync.
- Projections are deliberately lossy: they keep just enough state to tell
  "would the LLM say something materially different?" — not the full input.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

TRAINING_REVIEW_PROMPT_VERSION = "evidence-gated-diagnosis-v2"


def compute_dataset_hash(
    context: dict,
    insight_type: str,
    science_pillars: dict[str, str] | None = None,
) -> str:
    """Return a stable SHA-256 hex digest for the inputs that drive ``insight_type``.

    Args:
        context: Output of :func:`api.ai.build_training_context` (or its
            multi-user variant). Read-only.
        insight_type: One of ``daily_brief``, ``training_review``,
            ``race_forecast``.
        science_pillars: User's selected pillar→theory_id map (e.g.
            ``{"load": "banister_pmc", "recovery": "hrv_based", ...}``).

    Raises:
        ValueError: If ``insight_type`` is unknown.
    """
    pillar_set = tuple(sorted((science_pillars or {}).items()))

    if insight_type == "daily_brief":
        rs = context.get("recovery_state", {}) or {}
        cf = context.get("current_fitness", {}) or {}
        ap = context.get("athlete_profile", {}) or {}
        # Hash projects today's workout slot. Falling back to current_plan[0]
        # would make an unscheduled day depend on the next future workout, so a
        # distant plan edit could incorrectly change today's snapshot identity.
        proj: dict[str, Any] = {
            "hrv_ms": _round(rs.get("hrv_ms"), 0.5),
            "hrv_trend_pct": _round(rs.get("hrv_trend_pct"), 1.0),
            "sleep_score": rs.get("sleep_score"),
            "readiness": rs.get("readiness"),
            "tsb": _round(cf.get("tsb"), 0.5),
            "atl": _round(cf.get("atl"), 0.5),
            "ctl": _round(cf.get("ctl"), 0.5),
            "today_signal": _project_today_signal(context.get("today_signal")),
            "planned_today": _project_plan_entry(context.get("planned_today")),
            "goal": ap.get("goal"),
            "race_countdown": cf.get("race_countdown"),
            "pillars": pillar_set,
        }
    elif insight_type == "training_review":
        proj = {
            "prompt_version": TRAINING_REVIEW_PROMPT_VERSION,
            "inputs": build_training_review_inputs(context),
            "pillars": pillar_set,
        }
    elif insight_type == "race_forecast":
        cf = context.get("current_fitness", {}) or {}
        cp_trend = cf.get("cp_trend") or {}
        ap = context.get("athlete_profile", {}) or {}
        goal = ap.get("goal") or {}
        proj = {
            "cp_current": _round(cp_trend.get("current"), 1.0),
            "cp_direction": cp_trend.get("direction"),
            "cp_slope": _round(cp_trend.get("slope_per_month"), 0.5),
            "predicted_time_sec": _round(cf.get("predicted_time_sec"), 30.0),
            "race_date": goal.get("race_date") or None,
            "target_time_sec": goal.get("target_time_sec"),
            "distance": goal.get("distance"),
            "pillars": pillar_set,
        }
    else:
        raise ValueError(f"Unknown insight_type: {insight_type}")

    payload = json.dumps(proj, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_training_review_inputs(context: dict) -> dict:
    """Return the exact, evidence-gated training-review model payload."""
    recent = context.get("recent_training") or {}
    fitness = context.get("current_fitness") or {}
    profile = context.get("athlete_profile") or {}
    science = context.get("science") or {}
    zones = science.get("zones") or {}

    raw_diagnosis = recent.get("diagnosis") or {}
    diagnosis = dict(raw_diagnosis) if isinstance(raw_diagnosis, dict) else {}
    data_meta = diagnosis.get("data_meta") or {}
    distribution_complete = data_meta.get("distribution_complete") is True
    if not distribution_complete:
        # Zero-filled or partial distributions are display placeholders, not
        # evidence the model may interpret as the athlete's actual training mix.
        diagnosis.pop("distribution", None)
    interval_power = diagnosis.get("interval_power")
    if (
        not isinstance(interval_power, dict)
        or interval_power.get("evidence_complete") is not True
    ):
        # Partial split coverage cannot support whole-window interval claims.
        diagnosis.pop("interval_power", None)

    payload = {
        "weekly_summary": recent.get("weekly_summary") or [],
        "split_level_diagnosis": diagnosis,
        "sessions": [
            {
                "date": session.get("date"),
                "distance_km": session.get("distance_km"),
                "rss": session.get("rss"),
                "duration_min": session.get("duration_min"),
            }
            for session in (recent.get("sessions") or [])
        ],
        "cp_trend": fitness.get("cp_trend"),
        "goal": profile.get("goal"),
        "race_countdown": fitness.get("race_countdown"),
    }
    if distribution_complete:
        target_distribution = zones.get("target_distribution")
        if target_distribution:
            payload["zone_target_distribution"] = target_distribution
            payload["zone_names"] = zones.get("zone_names")
    return payload

def _round(v: Any, step: float) -> float | None:
    """Bucket ``v`` to the nearest ``step``. Returns None for missing/non-numeric.

    Logs once when a non-numeric, non-None value sneaks in — silently dropping
    it would freeze the hash on a typo'd field forever (stuck-cache bug).
    """
    if v is None:
        return None
    if not isinstance(v, (int, float)):
        logger.warning(
            "insight_hash._round: non-numeric value %r — projection lossy", v
        )
        return None
    return round(v / step) * step


def _bucket(v: Any, step: float) -> float | None:
    """Floor-bucket ``v`` to ``step``. Returns None for missing/non-numeric."""
    if v is None:
        return None
    if not isinstance(v, (int, float)):
        logger.warning(
            "insight_hash._bucket: non-numeric value %r — projection lossy", v
        )
        return None
    return int(v // step) * step


def _project_plan_entry(entry: Any) -> Any:
    """Keep only the fields of a plan workout that meaningfully shape the brief."""
    if not isinstance(entry, dict):
        return None
    # Workout prescriptions are emitted to the model verbatim. Keep them exact
    # so a changed target can never inherit prose generated for an older plan.
    return {
        "workout_type": entry.get("workout_type"),
        "start_time": entry.get("start_time"),
        "planned_duration_min": entry.get("planned_duration_min"),
        "planned_distance_km": entry.get("planned_distance_km"),
        "target_power_min": entry.get("target_power_min"),
        "target_power_max": entry.get("target_power_max"),
        "target_hr_min": entry.get("target_hr_min"),
        "target_hr_max": entry.get("target_hr_max"),
        "target_pace_min": entry.get("target_pace_min"),
        "target_pace_max": entry.get("target_pace_max"),
        "workout_description": entry.get("workout_description"),
    }


def _project_today_signal(entry: Any) -> Any:
    """Keep only the Today-signal fields that materially anchor the brief."""
    if not isinstance(entry, dict):
        return None
    return {
        "recommendation": entry.get("recommendation"),
        "reason": entry.get("reason"),
        "alternatives": list(entry.get("alternatives") or []),
    }
