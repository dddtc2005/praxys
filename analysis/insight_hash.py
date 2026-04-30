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
from typing import Any


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
        plan_list = context.get("current_plan") or []
        # ``current_plan`` comes from a pandas DataFrame's iterrows() and may
        # not have a guaranteed order. Sort by date so two upcoming workouts
        # on the same day don't flip the hash between syncs.
        plan_first = (
            sorted(
                (p for p in plan_list if isinstance(p, dict)),
                key=lambda p: str(p.get("date") or ""),
            )[0]
            if plan_list
            else None
        )
        proj: dict[str, Any] = {
            "hrv_ms": _round(rs.get("hrv_ms"), 0.5),
            "hrv_trend_pct": _round(rs.get("hrv_trend_pct"), 1.0),
            "sleep_score": rs.get("sleep_score"),
            "readiness": rs.get("readiness"),
            "tsb": _round(cf.get("tsb"), 0.5),
            "atl": _round(cf.get("atl"), 0.5),
            "ctl": _round(cf.get("ctl"), 0.5),
            "plan_first": _project_plan_entry(plan_first),
            "pillars": pillar_set,
        }
    elif insight_type == "training_review":
        rt = context.get("recent_training", {}) or {}
        sessions = rt.get("sessions") or []
        session_sigs = [
            (
                s.get("date"),
                _round(s.get("distance_km"), 0.5),
                _round(s.get("rss"), 5.0),
                _bucket(s.get("avg_power"), 10),
            )
            for s in sessions
        ]
        weekly = [
            (
                w.get("week"),
                _round(w.get("volume_km"), 1.0),
                _round(w.get("load"), 5.0),
                w.get("sessions"),
            )
            for w in (rt.get("weekly_summary") or [])
        ]
        cp_trend = (context.get("current_fitness", {}) or {}).get("cp_trend") or {}
        proj = {
            "sessions": session_sigs,
            "weekly": weekly,
            "cp_direction": cp_trend.get("direction"),
            "cp_slope": _round(cp_trend.get("slope_per_month"), 0.5),
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


def _round(v: Any, step: float) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v) / step) * step
    except (TypeError, ValueError):
        return None


def _bucket(v: Any, step: float) -> float | None:
    if v is None:
        return None
    try:
        return int(float(v) // step) * step
    except (TypeError, ValueError):
        return None


def _project_plan_entry(entry: Any) -> Any:
    """Keep only the fields of a plan workout that meaningfully shape the brief."""
    if not isinstance(entry, dict):
        return None
    return {
        "workout_type": entry.get("workout_type"),
        "planned_duration_min": _round(entry.get("planned_duration_min"), 5.0),
        "planned_distance_km": _round(entry.get("planned_distance_km"), 0.5),
        "target_power_min": _bucket(entry.get("target_power_min"), 10),
        "target_power_max": _bucket(entry.get("target_power_max"), 10),
    }
