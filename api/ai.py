"""AI training context builder and plan validation.

Serializes computed training metrics into a structured format optimized for
LLM consumption.  The same context powers both the Claude Code skill (now)
and future in-app AI coaching endpoints.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

import pandas as pd

from analysis.config import load_config


# ---------------------------------------------------------------------------
# Training context builder
# ---------------------------------------------------------------------------


def _build_context_from_data(data: dict) -> dict:
    """Reshape pre-computed dashboard data into AI training context.

    Accepts the dict returned by ``get_dashboard_data()`` and produces the
    structured context used by LLM plan generation. This avoids calling
    ``get_dashboard_data()`` a second time when the caller already has the data
    (e.g. the ``/api/ai/context`` route).
    """
    config = load_config()
    today = date.today()

    # -- Science framework --
    science = data.get("science", {})
    science_section: dict = {}
    for pillar in ("load", "recovery", "prediction", "zones"):
        theory = science.get(pillar)
        if theory is None:
            continue
        entry: dict = {"id": theory.id, "name": theory.name}
        if pillar == "zones":
            entry["zone_names"] = theory.zone_names
            entry["target_distribution"] = theory.target_distribution
            entry["zone_boundaries"] = theory.zone_boundaries
        if pillar == "load":
            entry["params"] = theory.params
        science_section[pillar] = entry

    # Resolve zone names for the active training base
    zones_theory = science.get("zones")
    active_zone_names: list[str] | None = None
    active_target_dist: list[float] | None = None
    if zones_theory:
        zn = zones_theory.zone_names
        active_zone_names = zn.get(config.training_base) if isinstance(zn, dict) else zn
        active_target_dist = zones_theory.target_distribution or None

    # -- Athlete profile --
    athlete_profile = {
        "training_base": config.training_base,
        "threshold": data.get("latest_cp"),
        "goal": {
            "distance": config.goal.get("distance", "marathon"),
            "target_time_sec": config.goal.get("target_time_sec") or config.goal.get("race_target_time_sec"),
            "race_date": config.goal.get("race_date", ""),
            "mode": "race_date" if config.goal.get("race_date") else "continuous",
        },
        "zones": config.zones.get(config.training_base, []),
        "zone_names": active_zone_names,
        "target_distribution": active_target_dist,
    }

    # -- Current fitness --
    ff = data.get("fitness_fatigue", {})
    ctl_vals = ff.get("ctl", [])
    atl_vals = ff.get("atl", [])
    tsb_vals = ff.get("tsb", [])
    current_fitness = {
        "ctl": ctl_vals[-1] if ctl_vals else None,
        "atl": atl_vals[-1] if atl_vals else None,
        "tsb": tsb_vals[-1] if tsb_vals else None,
        "cp_trend": data.get("cp_trend_data", {}),
        "predicted_time_sec": data.get("race_countdown", {}).get("predicted_time_sec"),
        "race_countdown": data.get("race_countdown", {}),
    }

    # -- Recent training (last 8 weeks of individual sessions + splits) --
    cutoff = (today - timedelta(weeks=8)).isoformat()
    all_activities = data.get("activities", [])
    recent_sessions = [
        a for a in all_activities
        if a.get("date", "") >= cutoff
    ]

    # Weekly summary
    weekly_summary: dict[str, dict] = {}
    for act in recent_sessions:
        act_date = act.get("date", "")
        if not act_date:
            continue
        try:
            dt = datetime.fromisoformat(act_date)
        except ValueError:
            continue
        week_key = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
        if week_key not in weekly_summary:
            weekly_summary[week_key] = {"week": week_key, "volume_km": 0, "load": 0, "sessions": 0}
        weekly_summary[week_key]["volume_km"] += act.get("distance_km") or 0
        weekly_summary[week_key]["load"] += act.get("rss") or 0
        weekly_summary[week_key]["sessions"] += 1

    # Round summary values
    for ws in weekly_summary.values():
        ws["volume_km"] = round(ws["volume_km"], 1)
        ws["load"] = round(ws["load"], 1)

    recent_training = {
        "diagnosis": data.get("diagnosis", {}),
        "weekly_summary": sorted(weekly_summary.values(), key=lambda w: w["week"]),
        "sessions": recent_sessions,
    }

    # -- Recovery state --
    signal = data.get("signal", {})
    recovery = signal.get("recovery", {})
    recovery_state = {
        "readiness": recovery.get("readiness"),
        "hrv_ms": recovery.get("hrv_ms"),
        "hrv_trend_pct": recovery.get("hrv_trend_pct"),
        "sleep_score": recovery.get("sleep_score"),
    }

    # -- Current plan --
    plan_df = data.get("plan")
    current_plan: list[dict] = []
    if isinstance(plan_df, pd.DataFrame) and not plan_df.empty:
        plan_future = plan_df[plan_df["date"] >= today]
        for _, row in plan_future.iterrows():
            wp = {k: (v if pd.notna(v) else None) for k, v in row.to_dict().items()}
            wp["date"] = str(wp.get("date", ""))
            current_plan.append(wp)

    return {
        "generated_at": datetime.now().isoformat(),
        "athlete_profile": athlete_profile,
        "science": science_section,
        "current_fitness": current_fitness,
        "recent_training": recent_training,
        "recovery_state": recovery_state,
        "current_plan": current_plan,
    }


def build_training_context() -> dict:
    """Build a structured training context dict for LLM plan generation.

    Calls ``get_dashboard_data()`` and reshapes the result into sections:
    athlete_profile, current_fitness, recent_training (with individual
    sessions + splits), recovery_state, and current_plan.
    """
    from api.deps import get_dashboard_data

    data = get_dashboard_data()
    return _build_context_from_data(data)


# ---------------------------------------------------------------------------
# Plan validation
# ---------------------------------------------------------------------------


def validate_plan(
    plan_workouts: list[dict],
    context: dict,
) -> tuple[bool, list[str]]:
    """Validate an AI-generated training plan before writing to CSV.

    Checks:
    - Date range: all dates today or later, max ~35 days span
    - Power targets: within 40-130% of current threshold
    - Required fields: date + workout_type present on every row
    - Distribution: at least 1 rest/off day per week, max 3 quality sessions/week

    Returns (is_valid, list_of_error_messages).
    """
    errors: list[str] = []
    today = date.today()

    if not plan_workouts:
        return False, ["Plan is empty — no workouts provided."]

    # --- Required fields ---
    for i, w in enumerate(plan_workouts):
        if not w.get("date"):
            errors.append(f"Workout {i}: missing date.")
        if not w.get("workout_type"):
            errors.append(f"Workout {i}: missing workout_type.")

    if errors:
        return False, errors

    # --- Parse dates ---
    dates: list[date] = []
    for w in plan_workouts:
        try:
            d = date.fromisoformat(str(w["date"]))
            dates.append(d)
        except ValueError:
            errors.append(f"Invalid date format: {w['date']}")

    if errors:
        return False, errors

    # Date range checks
    dates_sorted = sorted(dates)
    if dates_sorted[0] < today:
        errors.append(f"Plan contains past dates (earliest: {dates_sorted[0]}, today: {today}).")
    span_days = (dates_sorted[-1] - dates_sorted[0]).days + 1
    if span_days > 35:
        errors.append(f"Plan spans {span_days} days — expected at most ~35 days.")

    # --- Power/intensity target sanity ---
    threshold = context.get("athlete_profile", {}).get("threshold")
    if threshold and threshold > 0:
        for w in plan_workouts:
            for col in ("target_power_min", "target_power_max"):
                val = w.get(col)
                if val is not None:
                    try:
                        pwr = float(val)
                    except (ValueError, TypeError):
                        continue
                    if pwr < threshold * 0.40:
                        errors.append(
                            f"{w['date']} {w['workout_type']}: {col}={pwr}W is below "
                            f"40% of threshold ({threshold}W)."
                        )
                    if pwr > threshold * 1.30:
                        errors.append(
                            f"{w['date']} {w['workout_type']}: {col}={pwr}W exceeds "
                            f"130% of threshold ({threshold}W)."
                        )

    # --- Distribution sanity ---
    quality_types = {"threshold", "interval", "tempo", "speed", "race", "time_trial"}
    rest_types = {"rest", "off", "recovery"}

    # Group by ISO week
    weeks: dict[str, list[dict]] = {}
    for w in plan_workouts:
        d = date.fromisoformat(str(w["date"]))
        wk = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
        weeks.setdefault(wk, []).append(w)

    for wk, workouts in weeks.items():
        quality_count = sum(
            1 for w in workouts
            if str(w.get("workout_type", "")).lower() in quality_types
        )
        rest_count = sum(
            1 for w in workouts
            if str(w.get("workout_type", "")).lower() in rest_types
        )
        if quality_count > 3:
            errors.append(f"Week {wk}: {quality_count} quality sessions (max 3 recommended).")
        if rest_count < 1 and len(workouts) >= 6:
            errors.append(f"Week {wk}: no rest/recovery days in a {len(workouts)}-day week.")

    return (len(errors) == 0, errors)


# ---------------------------------------------------------------------------
# Staleness check
# ---------------------------------------------------------------------------


def check_plan_staleness(
    data_dir: str,
    current_cp: float | None = None,
) -> list[str]:
    """Check if the AI-generated plan is stale.

    Returns a list of warning strings (empty if plan is fresh).
    """
    meta_path = os.path.join(data_dir, "ai", "plan_meta.json")
    if not os.path.exists(meta_path):
        return []

    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    warnings: list[str] = []

    # Age check
    generated_at = meta.get("generated_at", "")
    if generated_at:
        try:
            gen_date = datetime.fromisoformat(generated_at).date()
            age_days = (date.today() - gen_date).days
            if age_days > 28:
                warnings.append(
                    f"AI training plan is {age_days} days old — consider regenerating."
                )
        except ValueError:
            pass

    # CP drift check
    cp_at_gen = meta.get("cp_at_generation")
    if cp_at_gen and current_cp and cp_at_gen > 0:
        drift_pct = abs(current_cp - cp_at_gen) / cp_at_gen * 100
        if drift_pct > 3:
            warnings.append(
                f"Threshold has changed {drift_pct:.1f}% since plan was generated "
                f"({cp_at_gen:.0f} → {current_cp:.0f}) — power targets may be inaccurate."
            )

    return warnings
