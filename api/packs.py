"""Per-endpoint dashboard packs (issue #146).

Each pack is a small, composable function returning only the data a single
endpoint actually serves. The 5 endpoints (`/api/today`, `/api/training`,
`/api/goal`, `/api/history`, `/api/science`) used to share a single
`get_dashboard_data()` that did ~22 top-level computations, then each
endpoint dropped 60-85% of the result. With packs, an endpoint pays only
for the work it actually consumes.

A `RequestContext` holds the request-scoped cache so that within a single
HTTP request, shared inputs (config, deduplicated activities, thresholds,
science, EWMA load series) are computed exactly once even when the route
calls multiple packs.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from functools import cached_property

import pandas as pd

from analysis.config import load_config_from_db
from analysis.data_loader import load_data_from_db
from analysis.metrics import (
    compute_ewma_load,
    compute_tsb,
    daily_training_signal,
    get_distance_config,
    project_tsb,
)
from analysis.providers.models import ThresholdEstimate
from analysis.science import load_active_science
from analysis.training_base import get_display_config
from api.deps import (
    _build_activities_list,
    _build_compliance,
    _build_race_countdown,
    _build_sleep_perf,
    _build_threshold_trend_chart,
    _build_warnings,
    _build_workout_flags,
    _compute_daily_load,
    _compute_diagnosis,
    _compute_recovery_analysis,
    _compute_threshold_data,
    _ensure_env,
    _estimate_plan_daily_loads,
    _get_todays_plan,
    _plan_row_duration_sec,
    _plan_workout_load,
    _resolve_thresholds,
    _select_prediction_method,
)
from api.views import upcoming_workouts

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request-scoped cache
# ---------------------------------------------------------------------------


class RequestContext:
    """Request-scoped cache for inputs shared across packs.

    Each ``cached_property`` is computed at most once per ``RequestContext``
    instance, so a route calling multiple packs in the same request pays
    for shared work (config, deduplicated activities, thresholds, science,
    EWMA load series) only once. Construct one ``RequestContext`` per
    request and pass it to each pack the endpoint needs.
    """

    def __init__(self, user_id: str, db) -> None:
        _ensure_env()
        self.user_id = user_id
        self.db = db
        self.today = date.today()

    # --- raw inputs --------------------------------------------------------

    @cached_property
    def config(self):
        return load_config_from_db(self.user_id, self.db)

    @cached_property
    def _data(self) -> dict:
        return load_data_from_db(self.user_id, self.db)

    @cached_property
    def merged_activities(self) -> pd.DataFrame:
        """Activities deduplicated by primary-source preference.

        Mirrors the dedup pass at the top of the legacy
        ``get_dashboard_data``: when the same activity is synced by two
        sources (Garmin + Stryd, same date, durations within 10%), keep
        the row whose source matches ``preferences.activities``.
        """
        merged = self._data["activities"]
        primary_source = self.config.preferences.get("activities")
        if not primary_source or merged.empty or "source" not in merged.columns:
            return merged
        merged = merged.copy()
        merged["_date"] = pd.to_datetime(merged["date"]).dt.date
        merged["_dur"] = pd.to_numeric(
            merged.get("duration_sec", 0), errors="coerce"
        ).fillna(0)
        merged["_is_primary"] = merged["source"] == primary_source

        keep_mask = pd.Series(True, index=merged.index)
        for _dt, group in merged.groupby("_date"):
            if len(group) <= 1:
                continue
            primary = group[group["_is_primary"]]
            others = group[~group["_is_primary"]]
            for oidx, orow in others.iterrows():
                for _, prow in primary.iterrows():
                    if prow["_dur"] > 0 and orow["_dur"] > 0:
                        ratio = abs(prow["_dur"] - orow["_dur"]) / max(
                            prow["_dur"], orow["_dur"]
                        )
                        if ratio < 0.10:
                            keep_mask[oidx] = False
                            break
        return (
            merged[keep_mask]
            .drop(columns=["_date", "_dur", "_is_primary"], errors="ignore")
            .reset_index(drop=True)
        )

    @cached_property
    def splits(self) -> pd.DataFrame:
        return self._data["splits"]

    @cached_property
    def recovery(self) -> pd.DataFrame:
        return self._data["recovery"]

    @cached_property
    def plan(self) -> pd.DataFrame:
        return self._data["plan"]

    @cached_property
    def thresholds(self) -> ThresholdEstimate:
        return _resolve_thresholds(
            self.config, user_id=self.user_id, db=self.db,
        )

    @cached_property
    def latest_cp_watts(self) -> float | None:
        cp = self.thresholds.cp_watts
        return cp if cp and cp > 0 else None

    @cached_property
    def science(self) -> dict:
        locale = (
            self.config.language
            if self.config.language in {"en", "zh"}
            else None
        )
        return load_active_science(
            self.config.science, self.config.zone_labels, locale=locale,
        )

    @cached_property
    def display(self) -> dict:
        return get_display_config(self.config.training_base)

    # --- derived series ----------------------------------------------------

    @cached_property
    def _load_constants(self) -> tuple[int, int]:
        load_theory = self.science.get("load")
        params = load_theory.params if load_theory else {}
        return (
            int(params.get("ctl_time_constant", 42)),
            int(params.get("atl_time_constant", 7)),
        )

    @cached_property
    def fitness_series(self) -> dict:
        """Daily load + EWMA-derived CTL/ATL/TSB over the full data window."""
        merged = self.merged_activities
        ctl_tc, atl_tc = self._load_constants
        earliest = self.today - timedelta(days=365)
        if not merged.empty and "date" in merged.columns:
            first_date = pd.to_datetime(merged["date"]).min()
            if pd.notna(first_date):
                earliest = first_date.date()
        full_range = pd.date_range(earliest, self.today)
        daily_load = _compute_daily_load(
            merged, full_range, self.config, self.thresholds,
        )
        ctl = compute_ewma_load(daily_load, time_constant=ctl_tc)
        atl = compute_ewma_load(daily_load, time_constant=atl_tc)
        tsb = compute_tsb(ctl, atl)
        return {
            "daily_load": daily_load,
            "ctl": ctl,
            "atl": atl,
            "tsb": tsb,
            "earliest": earliest,
        }

    @cached_property
    def projection(self) -> dict:
        ctl_tc, atl_tc = self._load_constants
        fs = self.fitness_series
        days = 14
        future_loads = _estimate_plan_daily_loads(
            self.plan, self.today, days, self.thresholds,
            self.config.training_base,
        )
        current_ctl = float(fs["ctl"].iloc[-1]) if not fs["ctl"].empty else 0.0
        current_atl = float(fs["atl"].iloc[-1]) if not fs["atl"].empty else 0.0
        proj_ctl, proj_atl, proj_tsb = project_tsb(
            current_ctl, current_atl, future_loads,
            ctl_tc=ctl_tc, atl_tc=atl_tc,
        )
        proj_dates = [
            (self.today + timedelta(days=i + 1)).strftime("%Y-%m-%d")
            for i in range(days)
        ]
        return {
            "ctl": proj_ctl,
            "atl": proj_atl,
            "tsb": proj_tsb,
            "dates": proj_dates,
        }

    @cached_property
    def threshold_data(self) -> dict:
        latest, trend, cp_values, pairs = _compute_threshold_data(
            self.merged_activities, self.config,
            user_id=self.user_id, db=self.db,
        )
        return {
            "latest": latest,
            "trend": trend,
            "cp_values": cp_values,
            "pairs": pairs,
        }

    @cached_property
    def cp_trend_chart(self) -> dict:
        return _build_threshold_trend_chart(
            self.merged_activities, self.config,
            user_id=self.user_id, db=self.db,
        )

    @cached_property
    def recovery_analysis(self) -> dict:
        analysis, _, _, _ = _compute_recovery_analysis(self.recovery)
        return analysis

    @cached_property
    def data_meta(self) -> dict:
        merged = self.merged_activities
        recovery = self.recovery
        chart = self.cp_trend_chart
        activity_count = len(merged) if not merged.empty else 0
        data_days = (
            (self.today - self.fitness_series["earliest"]).days
            if not merged.empty else 0
        )
        cp_point_count = len(chart.get("dates", [])) if chart else 0
        has_recovery = (
            not recovery.empty if hasattr(recovery, "empty") else bool(recovery)
        )
        return {
            "activity_count": activity_count,
            "data_days": data_days,
            "cp_points": cp_point_count,
            "has_recovery": has_recovery,
            "pmc_sufficient": data_days >= 42,
            "cp_trend_sufficient": cp_point_count >= 3,
        }

    @cached_property
    def science_notes(self) -> dict:
        return {
            pillar: {
                "name": theory.name,
                "description": getattr(theory, "simple_description", "") or "",
                "citations": [
                    {
                        "label": getattr(c, "title", getattr(c, "key", "")),
                        "url": getattr(c, "url", ""),
                    }
                    for c in (getattr(theory, "citations", None) or [])
                    if getattr(c, "url", None)
                ],
            }
            for pillar, theory in self.science.items()
            if theory and hasattr(theory, "name")
        }

    @cached_property
    def tsb_zones(self) -> list[dict]:
        load_theory = self.science.get("load")
        return [
            {"min": z.min, "max": z.max, "label": z.label, "color": z.color}
            for z in (load_theory.tsb_zones_labeled if load_theory else [])
        ]


# ---------------------------------------------------------------------------
# Local helpers (small enough to inline; not reused outside packs)
# ---------------------------------------------------------------------------


def _build_last_activity(merged: pd.DataFrame) -> dict | None:
    """Pull the single most recent activity for the Today widget.

    The Today page only renders the latest activity card, so building the
    full activities list (with splits) just to take ``activities[0]`` is
    wasted work. This helper returns the same shape ``api.views.last_activity``
    consumes, but skips the iteration over every activity and split.
    """
    if merged.empty or "date" not in merged.columns:
        return None
    sorted_m = merged.sort_values("date", ascending=False)
    if sorted_m.empty:
        return None
    row = sorted_m.iloc[0]
    if pd.isna(row.get("date")):
        return None
    return {
        "date": str(row["date"]),
        "activity_type": row.get("activity_type", "running"),
        "distance_km": (
            round(float(row.get("distance_km", 0)), 2)
            if pd.notna(row.get("distance_km")) else None
        ),
        "duration_sec": (
            int(row.get("duration_sec", 0))
            if pd.notna(row.get("duration_sec")) else None
        ),
        "avg_power": (
            round(float(row.get("avg_power", 0)), 1)
            if pd.notna(row.get("avg_power")) else None
        ),
        "avg_pace_min_km": (
            str(row.get("avg_pace_min_km", ""))
            if pd.notna(row.get("avg_pace_min_km")) else None
        ),
        "rss": (
            round(float(row.get("rss", 0)), 1)
            if pd.notna(row.get("rss")) else None
        ),
    }


def _current_week_load(
    daily_load: pd.Series, plan: pd.DataFrame, training_base: str,
    thresholds, today: date,
) -> dict | None:
    """Current ISO week's actual + planned load (single-week extract).

    Cheaper than ``_build_compliance`` for the 8-week chart when the caller
    (Today widget) only renders the latest entry. Uses ISO week numbers to
    match ``_build_compliance`` so the labels stay consistent.
    """
    if daily_load is None or daily_load.empty:
        return None
    today_ts = pd.Timestamp(today)
    week_year = today_ts.isocalendar().year
    week_num = today_ts.isocalendar().week

    df = daily_load.reset_index()
    df.columns = ["date", "load"]
    df["_d"] = pd.to_datetime(df["date"])
    df["_y"] = df["_d"].dt.isocalendar().year
    df["_w"] = df["_d"].dt.isocalendar().week
    actual_rows = df[(df["_y"] == week_year) & (df["_w"] == week_num)]
    if actual_rows.empty:
        return None
    actual = round(float(actual_rows["load"].sum()), 1)

    planned: float | None = None
    if not plan.empty and "date" in plan.columns:
        plan_copy = plan.copy()
        plan_copy["_d"] = pd.to_datetime(plan_copy["date"], errors="coerce")
        plan_copy = plan_copy.dropna(subset=["_d"])
        plan_copy["_y"] = plan_copy["_d"].dt.isocalendar().year
        plan_copy["_w"] = plan_copy["_d"].dt.isocalendar().week
        plan_week = plan_copy[
            (plan_copy["_y"] == week_year) & (plan_copy["_w"] == week_num)
        ]
        if not plan_week.empty:
            total = 0.0
            for _, row in plan_week.iterrows():
                dur_sec = _plan_row_duration_sec(row)
                total += _plan_workout_load(
                    row, dur_sec, training_base, thresholds,
                )
            planned = round(total, 1)

    return {
        "week_label": f"W{int(week_num)}",
        "actual": actual,
        "planned": planned,
    }


# ---------------------------------------------------------------------------
# Packs — each returns ONLY the keys its endpoint needs.
# ---------------------------------------------------------------------------


def get_signal_pack(ctx: RequestContext) -> dict:
    """Today's training signal + sparkline + recovery + warnings.

    Used by ``/api/today``. Pays for: full EWMA load (for current TSB),
    recovery analysis, warnings, projection (for sparkline tail). Does NOT
    pay for diagnosis, threshold trends, weekly compliance, full activity
    list, workout flags, or sleep-performance scatter.
    """
    fs = ctx.fitness_series
    proj = ctx.projection
    current_tsb = float(fs["tsb"].iloc[-1]) if not fs["tsb"].empty else 0.0
    recovery_analysis = ctx.recovery_analysis

    planned_today, planned_detail = _get_todays_plan(ctx.plan, ctx.today)
    load_theory = ctx.science.get("load")
    signal = daily_training_signal(
        recovery_analysis, current_tsb, planned_today,
        planned_detail=planned_detail,
        signal_thresholds=load_theory.signal if load_theory else None,
        hrv_only=True,
    )
    warnings = _build_warnings(
        recovery_analysis, current_tsb, ctx.config,
        data_dir=None, latest_cp_watts=ctx.latest_cp_watts,
    )

    display_days = 60
    date_range = pd.date_range(
        ctx.today - timedelta(days=display_days), ctx.today,
    )
    display_tsb = fs["tsb"].iloc[-len(date_range):]
    ff_dates = [d.strftime("%Y-%m-%d") for d in date_range]
    tsb_sparkline = {
        "dates": ff_dates[-14:],
        "values": [round(float(v), 1) for v in display_tsb.values][-14:],
        "projected_dates": proj["dates"][:7],
        "projected_values": proj["tsb"][:7],
    }

    return {
        "signal": signal,
        "tsb_sparkline": tsb_sparkline,
        "recovery_analysis": recovery_analysis,
        "warnings": warnings,
    }


def get_today_widgets(ctx: RequestContext) -> dict:
    """Last activity + current-week load summary + upcoming workouts.

    Used by ``/api/today``. Skips the full activity-list build: only the
    most recent activity is rendered on the Today page, so we extract one
    row instead of formatting all of them with splits.
    """
    return {
        "last_activity": _build_last_activity(ctx.merged_activities),
        "week_load": _current_week_load(
            ctx.fitness_series["daily_load"], ctx.plan,
            ctx.config.training_base, ctx.thresholds, ctx.today,
        ),
        "upcoming": upcoming_workouts(ctx.plan),
    }


def get_diagnosis_pack(ctx: RequestContext) -> dict:
    """Zone-aware diagnosis + workout flags + sleep-performance scatter.

    Used by ``/api/training``. Pays for splits and threshold-trend data.
    """
    cp_trend = ctx.threshold_data["trend"]
    return {
        "diagnosis": _compute_diagnosis(
            ctx.merged_activities, ctx.splits, cp_trend,
            ctx.config, ctx.thresholds, ctx.science,
        ),
        "workout_flags": _build_workout_flags(
            ctx.merged_activities, ctx.recovery, ctx.config.training_base,
        ),
        "sleep_perf": _build_sleep_perf(
            ctx.merged_activities, ctx.recovery, ctx.config.training_base,
        ),
    }


def get_fitness_pack(ctx: RequestContext) -> dict:
    """60-day fitness/fatigue chart + 8-week compliance + threshold trend.

    Used by ``/api/training``.
    """
    fs = ctx.fitness_series
    proj = ctx.projection
    display_days = 60
    date_range = pd.date_range(
        ctx.today - timedelta(days=display_days), ctx.today,
    )
    display_ctl = fs["ctl"].iloc[-len(date_range):]
    display_atl = fs["atl"].iloc[-len(date_range):]
    display_tsb = fs["tsb"].iloc[-len(date_range):]
    ff_dates = [d.strftime("%Y-%m-%d") for d in date_range]
    fitness_fatigue = {
        "dates": ff_dates,
        "ctl": [round(float(v), 1) for v in display_ctl.values],
        "atl": [round(float(v), 1) for v in display_atl.values],
        "tsb": [round(float(v), 1) for v in display_tsb.values],
        "projected_dates": proj["dates"],
        "projected_ctl": proj["ctl"],
        "projected_atl": proj["atl"],
        "projected_tsb": proj["tsb"],
    }
    weekly_review = _build_compliance(
        ctx.merged_activities, ctx.plan, ctx.config.training_base,
        fs["daily_load"], ctx.thresholds,
    )
    return {
        "fitness_fatigue": fitness_fatigue,
        "cp_trend": ctx.cp_trend_chart,
        "weekly_review": weekly_review,
    }


def get_race_pack(ctx: RequestContext) -> dict:
    """Race countdown + threshold trend chart and series for /api/goal."""
    td = ctx.threshold_data
    config = ctx.config
    race_date_str = str(config.goal.get("race_date", "")).strip()
    raw_target = (
        config.goal.get("target_time_sec")
        or config.goal.get("race_target_time_sec")
    )
    target_time_sec = int(raw_target) if raw_target else None
    distance_key = (
        str(config.goal.get("distance", "marathon")).strip() or "marathon"
    )
    dist_config = get_distance_config(distance_key)
    threshold_pace = ctx.thresholds.threshold_pace_sec_km

    prediction_theory = ctx.science.get("prediction")
    prediction_theory_id = config.science.get("prediction", "critical_power")
    theory_exponent = None
    if prediction_theory and prediction_theory.params:
        theory_fractions = prediction_theory.params.get(
            "distance_power_fractions", {},
        )
        theory_fraction = theory_fractions.get(distance_key)
        if theory_fraction:
            dist_config = {**dist_config, "power_fraction": theory_fraction}
        theory_exponent = prediction_theory.params.get("riegel_exponent")

    prediction_method = _select_prediction_method(
        config.training_base, prediction_theory_id,
        has_cp=bool(ctx.latest_cp_watts), has_pace=bool(threshold_pace),
    )

    race_countdown = _build_race_countdown(
        race_date_str, target_time_sec,
        latest_threshold=td["latest"],
        latest_cp_watts=ctx.latest_cp_watts,
        power_pace_pairs=td["pairs"],
        cp_trend_data=td["trend"],
        today=ctx.today,
        distance_km=dist_config["km"],
        power_fraction=dist_config["power_fraction"],
        distance_label=dist_config["label"],
        distance_key=distance_key,
        training_base=config.training_base,
        threshold_pace=threshold_pace,
        riegel_exponent=theory_exponent,
        prediction_method=prediction_method,
        prediction_theory_name=(
            prediction_theory.name if prediction_theory else None
        ),
    )

    return {
        "race_countdown": race_countdown,
        "cp_trend": ctx.cp_trend_chart,
        "cp_trend_data": td["trend"],
        "latest_cp": td["latest"],
    }


def get_history_pack(ctx: RequestContext) -> dict:
    """Full activities list (with splits) for /api/history.

    Returns the only piece of data /api/history actually consumes — the
    deduplication and pagination concerns stay in the route since they
    depend on query parameters.
    """
    return {
        "activities": _build_activities_list(
            ctx.merged_activities, ctx.splits,
        ),
    }


def get_science_pack(ctx: RequestContext) -> dict:
    """Active science theories + summarized notes + TSB zone bands."""
    return {
        "science": ctx.science,
        "science_notes": ctx.science_notes,
        "tsb_zones": ctx.tsb_zones,
    }
