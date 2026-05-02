#!/usr/bin/env python3
"""Praxys MCP Server — dual-mode (local/remote) training data tools.

Mode detection (in priority order):
  - PRAXYS_LOCAL=1 (or legacy TRAINSIGHT_LOCAL=1) → local mode (direct Python
    imports, dev user, DB). Use this when iterating against your local DB
    instead of production.
  - Otherwise → remote mode (HTTP API with JWT auth). PRAXYS_URL overrides
    the default of https://api.praxys.run; PRAXYS_FRONTEND_URL likewise
    for the browser-login flow.

Production is the default so the plugin works out-of-the-box for end users.
Set PRAXYS_LOCAL=1 in your shell to develop against the local FastAPI/DB.
"""
import json
import os
import sys
import logging

logger = logging.getLogger(__name__)

# Add project root to path for local mode imports
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, _PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("praxys", instructions="Training data tools for Praxys dashboard")

# Mode detection — prefer PRAXYS_*, fall back to legacy TRAINSIGHT_* for one
# release (deprecation: 2026-05-19). Defaults to praxys.run production so the
# plugin works out-of-the-box; local devs opt in via PRAXYS_LOCAL=1 (see the
# module docstring and CLAUDE.md "Running" section).
_DEFAULT_BACKEND = "https://api.praxys.run"
_DEFAULT_FRONTEND = "https://www.praxys.run"


def _clean(value: str | None) -> str:
    """Trim and reject unexpanded ${VAR} placeholders that slip through MCP env."""
    if not value:
        return ""
    v = value.strip().rstrip("/")
    return "" if v.startswith("${") and v.endswith("}") else v


def _is_truthy(value: str | None) -> bool:
    return bool(value) and value.strip().lower() not in ("", "0", "false", "no")


# Local mode is opt-in. Without this flag we hit production by default, so
# end users get a working plugin without any env wiring. The previous
# heuristic ("no PRAXYS_URL means local") silently broke as soon as we
# baked in production defaults — it would have routed unconfigured users'
# tool calls to localhost and surfaced obscure connection errors.
IS_REMOTE = not (
    _is_truthy(os.environ.get("PRAXYS_LOCAL"))
    or _is_truthy(os.environ.get("TRAINSIGHT_LOCAL"))
)
REMOTE_URL = (
    _clean(os.environ.get("PRAXYS_URL"))
    or _clean(os.environ.get("TRAINSIGHT_URL"))
    or (_DEFAULT_BACKEND if IS_REMOTE else "")
)
FRONTEND_URL = (
    _clean(os.environ.get("PRAXYS_FRONTEND_URL"))
    or _clean(os.environ.get("TRAINSIGHT_FRONTEND_URL"))
    or (_DEFAULT_FRONTEND if IS_REMOTE else "")
)


# ---------------------------------------------------------------------------
# Remote helpers (HTTP API)
# ---------------------------------------------------------------------------

# Token path migrated from ~/.trainsight to ~/.praxys; still read legacy.
_TOKEN_PATH = os.path.expanduser("~/.praxys/token")
_LEGACY_TOKEN_PATH = os.path.expanduser("~/.trainsight/token")

_NOT_AUTHENTICATED_MSG = (
    "Not authenticated. Please run the `login` tool first with your "
    "Praxys email and password, or manually cache a token at ~/.praxys/token"
)


def _get_remote_headers():
    """Get auth headers for remote API calls."""
    for path in (_TOKEN_PATH, _LEGACY_TOKEN_PATH):
        if os.path.exists(path):
            with open(path) as f:
                token = f.read().strip()
            if token:
                return {"Authorization": f"Bearer {token}"}
    return {}


def _check_auth_error(res):
    """Raise on HTTP errors, surfacing the API's `detail` field when present.

    Without this, requests.HTTPError reports only "400 Client Error: Bad Request"
    and the API's structured 4xx detail (e.g., the sync_interval validation
    message) is dropped, leaving the LLM caller with no actionable info.
    """
    if res.status_code == 401:
        raise RuntimeError(_NOT_AUTHENTICATED_MSG)
    if res.status_code >= 400:
        detail = ""
        try:
            body = res.json()
            if isinstance(body, dict):
                detail = body.get("detail") or body.get("message") or ""
        except ValueError:
            pass
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(
            f"API request failed (HTTP {res.status_code}){suffix}"
        )


def _remote_get(path: str) -> dict:
    import requests
    res = requests.get(f"{REMOTE_URL}{path}", headers=_get_remote_headers(), timeout=30)
    _check_auth_error(res)
    return res.json()


def _remote_post(path: str, data: dict = None) -> dict:
    import requests
    headers = _get_remote_headers()
    headers["Content-Type"] = "application/json"
    res = requests.post(f"{REMOTE_URL}{path}", headers=headers, json=data, timeout=60)
    _check_auth_error(res)
    return res.json()


def _remote_put(path: str, data: dict = None) -> dict:
    import requests
    headers = _get_remote_headers()
    headers["Content-Type"] = "application/json"
    res = requests.put(f"{REMOTE_URL}{path}", headers=headers, json=data, timeout=30)
    _check_auth_error(res)
    return res.json()


def _remote_delete(path: str) -> dict:
    import requests
    res = requests.delete(f"{REMOTE_URL}{path}", headers=_get_remote_headers(), timeout=30)
    _check_auth_error(res)
    return res.json()


# ---------------------------------------------------------------------------
# Local helpers (direct DB access)
# ---------------------------------------------------------------------------

_db_initialized = False
_cached_user_id: str | None = None


def _local_db():
    """Get a local DB session."""
    global _db_initialized
    from db.session import init_db
    if not _db_initialized:
        init_db()
        _db_initialized = True
    # Re-import after init_db sets the module-level SessionLocal
    from db import session as db_session
    return db_session.SessionLocal()


def _local_user_id() -> str:
    """Get the user ID for local mode.

    Priority:
    1. PRAXYS_USER_ID (or legacy TRAINSIGHT_USER_ID) env var (explicit override)
    2. First active user found in the database

    Raises RuntimeError if no users exist (register via the web UI first).
    """
    global _cached_user_id
    if _cached_user_id:
        return _cached_user_id

    # Check env var override (prefer PRAXYS_USER_ID; fall back to legacy)
    env_uid = os.environ.get("PRAXYS_USER_ID") or os.environ.get("TRAINSIGHT_USER_ID")
    if env_uid:
        _cached_user_id = env_uid
        return env_uid

    # Find first active user in DB
    db = _local_db()
    try:
        from db.models import User
        user = db.query(User).filter(User.is_active == True).first()
        if user:
            _cached_user_id = user.id
            logger.info("Local mode: using user %s (%s)", user.id, user.email)
            return user.id
    finally:
        db.close()

    raise RuntimeError(
        "No users found in database. Start the server and register "
        "via the web UI first: python -m uvicorn api.main:app --reload"
    )


def _local_dashboard_data() -> dict:
    db = _local_db()
    try:
        from api.deps import get_dashboard_data
        return get_dashboard_data(user_id=_local_user_id(), db=db)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# MCP Tools — Training Data
# ---------------------------------------------------------------------------

@mcp.tool()
def get_daily_brief() -> str:
    """Get today's training brief: training signal (Go/Modify/Rest), recovery status, upcoming workouts, last activity, weekly load."""
    if IS_REMOTE:
        data = _remote_get("/api/today")
    else:
        import pandas as pd
        from api.views import last_activity, upcoming_workouts, week_load
        raw = _local_dashboard_data()
        data = {
            "signal": raw["signal"],
            "recovery_analysis": raw.get("recovery_analysis"),
            "last_activity": last_activity(raw.get("activities", [])),
            "week_load": week_load(raw.get("weekly_review", {})),
            "upcoming": upcoming_workouts(raw.get("plan", pd.DataFrame())),
            "warnings": raw.get("warnings", []),
        }
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_training_review() -> str:
    """Get training analysis: zone distribution, fitness/fatigue trends, diagnosis findings, suggestions, and workout flags."""
    if IS_REMOTE:
        data = _remote_get("/api/training")
    else:
        raw = _local_dashboard_data()
        data = {
            "diagnosis": raw.get("diagnosis"),
            "fitness_fatigue": raw.get("fitness_fatigue"),
            "cp_trend": raw.get("cp_trend"),
            "weekly_review": raw.get("weekly_review"),
            "workout_flags": raw.get("workout_flags"),
        }
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_race_forecast() -> str:
    """Get race prediction: predicted finish time, required CP/pace, goal feasibility assessment, and CP trend."""
    if IS_REMOTE:
        data = _remote_get("/api/goal")
    else:
        raw = _local_dashboard_data()
        data = {
            "race_countdown": raw.get("race_countdown"),
            "cp_trend": raw.get("cp_trend"),
            "cp_trend_data": raw.get("cp_trend_data"),
            "latest_cp": raw.get("latest_cp"),
        }
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_training_context() -> str:
    """Get full training context for AI plan generation: athlete profile, current fitness, recent training, recovery state, and active plan."""
    if IS_REMOTE:
        data = _remote_get("/api/ai/context")
    else:
        from api.ai import build_training_context
        data = build_training_context()
    return json.dumps(data, indent=2, default=str)


# ---------------------------------------------------------------------------
# MCP Tools — Settings & Connections
# ---------------------------------------------------------------------------

@mcp.tool()
def get_settings() -> str:
    """Get current user settings: training base, thresholds, zones, goal, connected platforms, and display config."""
    if IS_REMOTE:
        data = _remote_get("/api/settings")
    else:
        db = _local_db()
        try:
            from analysis.config import load_config_from_db
            from analysis.training_base import get_display_config
            config = load_config_from_db(_local_user_id(), db)
            from dataclasses import asdict
            data = {
                "config": asdict(config),
                "display": get_display_config(config.training_base),
            }
        finally:
            db.close()
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def update_settings(settings: dict) -> str:
    """Update user settings. Pass a dict with fields to update (training_base, thresholds, zones, goal, science)."""
    if IS_REMOTE:
        data = _remote_put("/api/settings", settings)
    else:
        db = _local_db()
        try:
            from analysis.config import load_config_from_db, save_config_to_db
            config = load_config_from_db(_local_user_id(), db)
            for key, value in settings.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            save_config_to_db(_local_user_id(), config, db)
            data = {"status": "updated"}
        finally:
            db.close()
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_sync_settings() -> str:
    """Get current auto-sync frequency and allowed options."""
    if IS_REMOTE:
        settings = _remote_get("/api/settings")
        source_options = settings.get("config", {}).get("source_options", {})
        from db.sync_scheduler import (
            ALLOWED_SYNC_INTERVAL_HOURS,
            DEFAULT_SYNC_INTERVAL_HOURS,
            get_user_sync_interval_hours,
        )
        data = {
            "sync_interval_hours": get_user_sync_interval_hours(source_options),
            "allowed_sync_interval_hours": settings.get(
                "sync_interval_options_hours", list(ALLOWED_SYNC_INTERVAL_HOURS)
            ),
            "default_sync_interval_hours": settings.get(
                "default_sync_interval_hours", DEFAULT_SYNC_INTERVAL_HOURS
            ),
        }
    else:
        db = _local_db()
        try:
            from analysis.config import load_config_from_db
            from db.sync_scheduler import (
                ALLOWED_SYNC_INTERVAL_HOURS,
                DEFAULT_SYNC_INTERVAL_HOURS,
                get_user_sync_interval_hours,
            )

            config = load_config_from_db(_local_user_id(), db)
            data = {
                "sync_interval_hours": get_user_sync_interval_hours(config.source_options),
                "allowed_sync_interval_hours": list(ALLOWED_SYNC_INTERVAL_HOURS),
                "default_sync_interval_hours": DEFAULT_SYNC_INTERVAL_HOURS,
            }
        finally:
            db.close()
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def set_sync_frequency(hours: int) -> str:
    """Set auto-sync frequency in hours (allowed: 6, 12, 24)."""
    from db.sync_scheduler import (
        ALLOWED_SYNC_INTERVAL_HOURS,
        normalize_sync_interval_hours,
    )

    try:
        normalized_hours = normalize_sync_interval_hours(hours)
    except ValueError as exc:
        return json.dumps(
            {
                "status": "error",
                "message": str(exc),
                "allowed_sync_interval_hours": list(ALLOWED_SYNC_INTERVAL_HOURS),
            },
            indent=2,
            default=str,
        )
    if IS_REMOTE:
        try:
            updated = _remote_put("/api/settings", {
                "source_options": {"sync_interval_hours": normalized_hours}
            })
        except RuntimeError as exc:
            return json.dumps(
                {
                    "status": "error",
                    "message": str(exc),
                    "allowed_sync_interval_hours": list(ALLOWED_SYNC_INTERVAL_HOURS),
                },
                indent=2,
                default=str,
            )
        source_options = updated.get("config", {}).get("source_options", {})
        data = {
            "status": updated.get("status", "ok"),
            "sync_interval_hours": source_options.get("sync_interval_hours", normalized_hours),
        }
    else:
        db = _local_db()
        try:
            from analysis.config import load_config_from_db, save_config_to_db
            config = load_config_from_db(_local_user_id(), db)
            source_options = dict(config.source_options or {})
            source_options["sync_interval_hours"] = normalized_hours
            config.source_options = source_options
            save_config_to_db(_local_user_id(), config, db)
            data = {"status": "updated", "sync_interval_hours": normalized_hours}
        finally:
            db.close()
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_connections() -> str:
    """Get connected platforms and their status. Credentials are never returned — only connection status."""
    if IS_REMOTE:
        data = _remote_get("/api/settings/connections")
    else:
        db = _local_db()
        try:
            from db.models import UserConnection
            connections = db.query(UserConnection).filter(
                UserConnection.user_id == _local_user_id()
            ).all()
            result = {}
            for conn in connections:
                result[conn.platform] = {
                    "status": conn.status,
                    "last_sync": conn.last_sync.isoformat() if conn.last_sync else None,
                    "has_credentials": conn.encrypted_credentials is not None,
                }
            data = {"connections": result}
        finally:
            db.close()
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def connect_platform(platform: str, credentials: dict) -> str:
    """Connect a platform by storing encrypted credentials.

    Args:
        platform: One of 'garmin', 'stryd', 'oura'
        credentials: Platform-specific credentials dict:
            - garmin: {"email": "...", "password": "...", "is_cn": false}
            - stryd: {"email": "...", "password": "..."}
            - oura: {"token": "..."}

    IMPORTANT: Never ask the user to type credentials in the conversation.
    Instead, ask them to enter credentials in the web Settings page. Only use
    this tool if the user explicitly provides credentials or if reading from
    a secure source.
    """
    if IS_REMOTE:
        data = _remote_post(f"/api/settings/connections/{platform}", credentials)
    else:
        db = _local_db()
        try:
            from db.models import UserConnection
            from db.crypto import get_vault
            from analysis.config import PLATFORM_CAPABILITIES

            vault = get_vault()
            encrypted_data, wrapped_dek = vault.encrypt(json.dumps(credentials))

            caps = PLATFORM_CAPABILITIES.get(platform, {})
            prefs = {k: v for k, v in caps.items() if v}

            conn = db.query(UserConnection).filter(
                UserConnection.user_id == _local_user_id(),
                UserConnection.platform == platform,
            ).first()
            if conn:
                conn.encrypted_credentials = encrypted_data
                conn.wrapped_dek = wrapped_dek
                conn.status = "connected"
                conn.preferences = prefs
            else:
                conn = UserConnection(
                    user_id=_local_user_id(),
                    platform=platform,
                    encrypted_credentials=encrypted_data,
                    wrapped_dek=wrapped_dek,
                    status="connected",
                    preferences=prefs,
                )
                db.add(conn)
            db.commit()
            # Invalidate cached Garmin OAuth tokens so the next sync re-auths
            # with the new credentials. Mirrors the API route — skipping this
            # would reproduce the shared-tokenstore leak for local MCP users.
            if platform == "garmin":
                from api.routes.sync import clear_garmin_tokens
                try:
                    clear_garmin_tokens(_local_user_id())
                except OSError:
                    pass  # logged inside clear_garmin_tokens; treat as best-effort here
            data = {"status": "connected", "platform": platform}
        finally:
            db.close()
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def disconnect_platform(platform: str) -> str:
    """Disconnect a platform — deletes stored credentials."""
    if IS_REMOTE:
        data = _remote_delete(f"/api/settings/connections/{platform}")
    else:
        db = _local_db()
        try:
            from db.models import UserConnection
            conn = db.query(UserConnection).filter(
                UserConnection.user_id == _local_user_id(),
                UserConnection.platform == platform,
            ).first()
            if conn:
                db.delete(conn)
                db.commit()
            if platform == "garmin":
                from api.routes.sync import clear_garmin_tokens
                try:
                    clear_garmin_tokens(_local_user_id())
                except OSError:
                    pass
            data = {"status": "disconnected", "platform": platform}
        finally:
            db.close()
    return json.dumps(data, indent=2, default=str)


# ---------------------------------------------------------------------------
# MCP Tools — Plans & Sync
# ---------------------------------------------------------------------------

def _parse_plan_csv(plan_csv: str) -> list[dict]:
    """Parse a plan CSV into TrainingPlan kwargs dicts. Raises ValueError on bad rows."""
    import csv as _csv
    import io as _io
    from datetime import datetime as _dt

    rows = []
    reader = _csv.DictReader(_io.StringIO(plan_csv))
    for i, raw in enumerate(reader):
        d_raw = raw.get("date", "")
        rows.append({
            "date": _dt.strptime(d_raw, "%Y-%m-%d").date() if d_raw else None,
            "workout_type": raw.get("workout_type", ""),
            "planned_duration_min": float(raw["planned_duration_min"])
                if raw.get("planned_duration_min") else None,
            "planned_distance_km": float(raw["planned_distance_km"])
                if raw.get("planned_distance_km") else None,
            "target_power_min": float(raw["target_power_min"])
                if raw.get("target_power_min") else None,
            "target_power_max": float(raw["target_power_max"])
                if raw.get("target_power_max") else None,
            "workout_description": raw.get("workout_description", ""),
        })
    return rows


def _local_push_plan(plan_csv: str, mode: str) -> dict:
    """Local mirror of POST /api/plan/upload?mode=...."""
    from datetime import date as _date, datetime as _dt
    from db.models import TrainingPlan
    db = _local_db()
    try:
        parsed = _parse_plan_csv(plan_csv)
        if not parsed:
            return {"status": "error", "message": "No rows in CSV"}
        user_id = _local_user_id()
        if mode == "replace":
            db.query(TrainingPlan).filter(
                TrainingPlan.user_id == user_id,
                TrainingPlan.source == "ai",
                TrainingPlan.date >= _date.today(),
            ).delete(synchronize_session=False)
        else:
            target_dates = {p["date"] for p in parsed if p["date"] is not None}
            if target_dates:
                db.query(TrainingPlan).filter(
                    TrainingPlan.user_id == user_id,
                    TrainingPlan.source == "ai",
                    TrainingPlan.date.in_(target_dates),
                ).delete(synchronize_session=False)
        for kwargs in parsed:
            db.add(TrainingPlan(
                user_id=user_id, source="ai",
                meta={"uploaded_at": _dt.utcnow().isoformat()},
                **kwargs,
            ))
        db.commit()
        return {"status": "saved", "rows": len(parsed), "mode": mode}
    finally:
        db.close()


@mcp.tool()
def push_training_plan(plan_csv: str, mode: str = "replace") -> str:
    """Push an AI-generated training plan. Pass the plan as CSV text (columns: date,workout_type,planned_duration_min,planned_distance_km,target_power_min,target_power_max,workout_description).

    mode='replace' (default): wipes all future AI plan entries for this user, then inserts.
    Use this for full-window plan generation (the typical 28-day plan).

    mode='merge': only the dates in the CSV are touched; other AI rows are
    preserved. Use this when patching individual days without resending the
    whole plan.
    """
    if mode not in ("replace", "merge"):
        return json.dumps({"status": "error", "message": "mode must be 'replace' or 'merge'"})
    if IS_REMOTE:
        data = _remote_post(f"/api/plan/upload?mode={mode}", {"csv": plan_csv})
    else:
        try:
            data = _local_push_plan(plan_csv, mode)
        except ValueError as e:
            data = {"status": "error", "message": f"Invalid CSV: {e}"}
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def update_training_day(
    plan_date: str,
    workout_type: str,
    planned_duration_min: float | None = None,
    planned_distance_km: float | None = None,
    target_power_min: float | None = None,
    target_power_max: float | None = None,
    workout_description: str | None = None,
) -> str:
    """Upsert a single AI plan workout for the given date (YYYY-MM-DD).

    Replaces any existing AI entry for that date with the new values; other
    dates are untouched. Use this for shifts and partial edits — much safer
    than push_training_plan when you only want to change one day.
    """
    payload = {
        "workout_type": workout_type,
        "planned_duration_min": planned_duration_min,
        "planned_distance_km": planned_distance_km,
        "target_power_min": target_power_min,
        "target_power_max": target_power_max,
        "workout_description": workout_description,
    }
    if IS_REMOTE:
        data = _remote_put(f"/api/plan/{plan_date}", payload)
    else:
        from datetime import datetime as _dt
        from db.models import TrainingPlan
        try:
            d = _dt.strptime(plan_date, "%Y-%m-%d").date()
        except ValueError:
            return json.dumps({"status": "error", "message": "date must be YYYY-MM-DD"})
        db = _local_db()
        try:
            user_id = _local_user_id()
            db.query(TrainingPlan).filter(
                TrainingPlan.user_id == user_id,
                TrainingPlan.source == "ai",
                TrainingPlan.date == d,
            ).delete(synchronize_session=False)
            plan = TrainingPlan(
                user_id=user_id, date=d, source="ai",
                workout_type=workout_type,
                planned_duration_min=planned_duration_min,
                planned_distance_km=planned_distance_km,
                target_power_min=target_power_min,
                target_power_max=target_power_max,
                workout_description=workout_description or "",
                meta={"uploaded_at": _dt.utcnow().isoformat()},
            )
            db.add(plan)
            db.commit()
            db.refresh(plan)
            data = {
                "id": plan.id, "date": plan.date.isoformat(),
                "workout_type": plan.workout_type,
                "planned_duration_min": plan.planned_duration_min,
                "planned_distance_km": plan.planned_distance_km,
                "target_power_min": plan.target_power_min,
                "target_power_max": plan.target_power_max,
                "workout_description": plan.workout_description,
                "source": plan.source,
            }
        finally:
            db.close()
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def delete_training_day(plan_date: str) -> str:
    """Delete the AI plan workout(s) for the given date (YYYY-MM-DD)."""
    if IS_REMOTE:
        data = _remote_delete(f"/api/plan/{plan_date}")
    else:
        from datetime import datetime as _dt
        from db.models import TrainingPlan
        try:
            d = _dt.strptime(plan_date, "%Y-%m-%d").date()
        except ValueError:
            return json.dumps({"status": "error", "message": "date must be YYYY-MM-DD"})
        db = _local_db()
        try:
            deleted = db.query(TrainingPlan).filter(
                TrainingPlan.user_id == _local_user_id(),
                TrainingPlan.source == "ai",
                TrainingPlan.date == d,
            ).delete(synchronize_session=False)
            db.commit()
            data = {"status": "deleted", "rows": deleted, "date": plan_date}
        finally:
            db.close()
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def push_training_insights(
    insight_type: str,
    headline: str,
    summary: str,
    findings: list[dict] | None = None,
    recommendations: list[str] | None = None,
    meta: dict | None = None,
) -> str:
    """Push AI-generated insights to the web dashboard.

    Call this at the end of a training review, daily brief, or race forecast
    to persist your analysis so the user can see it on the web.

    Args:
        insight_type: One of 'training_review', 'daily_brief', 'race_forecast'
        headline: One-sentence summary (e.g., "Strong volume but threshold work needed")
        summary: 2-3 paragraph narrative analysis
        findings: List of {type: "positive"|"warning"|"neutral", text: "..."} findings
        recommendations: List of actionable recommendation strings
        meta: Optional metadata (data_range, training_base, etc.)
    """
    payload = {
        "insight_type": insight_type,
        "headline": headline,
        "summary": summary,
        "findings": findings or [],
        "recommendations": recommendations or [],
        "meta": meta or {},
    }

    if IS_REMOTE:
        data = _remote_post("/api/insights", payload)
    else:
        from datetime import datetime
        db = _local_db()
        try:
            from db.models import AiInsight
            user_id = _local_user_id()
            existing = db.query(AiInsight).filter(
                AiInsight.user_id == user_id,
                AiInsight.insight_type == insight_type,
            ).first()
            if existing:
                existing.headline = headline
                existing.summary = summary
                existing.findings = findings or []
                existing.recommendations = recommendations or []
                existing.meta = meta or {}
                existing.generated_at = datetime.utcnow()
            else:
                db.add(AiInsight(
                    user_id=user_id,
                    insight_type=insight_type,
                    headline=headline,
                    summary=summary,
                    findings=findings or [],
                    recommendations=recommendations or [],
                    meta=meta or {},
                ))
            db.commit()
            data = {"status": "saved", "insight_type": insight_type}
        finally:
            db.close()
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def trigger_sync(sources: list[str] | None = None) -> str:
    """Trigger data sync from connected platforms. Optionally specify sources: ['garmin', 'stryd', 'oura']. Requires the backend server to be running."""
    if IS_REMOTE:
        data = _remote_post("/api/sync", {"sources": sources} if sources else None)
    else:
        # Local mode: sync requires the API server (background threads, rate limiting).
        # Try calling the local API if it's running.
        import requests
        try:
            url = "http://localhost:8000/api/sync"
            # Local sync still goes through the API (needs auth + background tasks)
            local_headers = {}
            if os.path.exists(_TOKEN_PATH):
                with open(_TOKEN_PATH) as f:
                    t = f.read().strip()
                if t:
                    local_headers["Authorization"] = f"Bearer {t}"
            if sources:
                results = []
                for s in sources:
                    res = requests.post(f"{url}/{s}", headers=local_headers, timeout=5)
                    results.append({"source": s, "status": res.json().get("status", "error")})
                data = {"results": results}
            else:
                res = requests.post(url, headers=local_headers, timeout=5)
                data = res.json()
        except requests.ConnectionError:
            data = {"status": "error", "message": "Backend server not running. Start it with: python -m uvicorn api.main:app --reload"}
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_sync_status() -> str:
    """Check the current sync status for all connected platforms."""
    if IS_REMOTE:
        data = _remote_get("/api/sync/status")
    else:
        import requests
        try:
            res = requests.get("http://localhost:8000/api/sync/status", timeout=5)
            data = res.json()
        except requests.ConnectionError:
            # Fall back to checking connections in DB
            db = _local_db()
            try:
                from db.models import UserConnection
                from db.sync_scheduler import ACTIVE_CONNECTION_STATUSES
                connections = db.query(UserConnection).filter(
                    UserConnection.user_id == _local_user_id()
                ).all()
                data = {}
                for conn in connections:
                    data[conn.platform] = {
                        "status": "idle",
                        "last_sync": conn.last_sync.isoformat() if conn.last_sync else None,
                        "connected": conn.status in ACTIVE_CONNECTION_STATUSES,
                    }
            finally:
                db.close()
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def login() -> str:
    """Authenticate with Praxys via browser login.

    Opens the Praxys login page in your browser. After you log in,
    the token is automatically captured and cached for CLI use.
    No passwords are entered in the CLI.
    """
    if not IS_REMOTE:
        return json.dumps({"status": "skipped", "message": "Login not needed in local mode"})

    import socket
    import threading
    import webbrowser
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs

    token_result = {"token": None, "error": None}

    def _find_available_port(preferred: int = 9876) -> int:
        """Try preferred port, fall back to OS-assigned port."""
        for port in [preferred, 0]:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("127.0.0.1", port))
                    return s.getsockname()[1]
            except OSError:
                continue
        raise RuntimeError("Cannot bind to any port for login callback")

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)

            if parsed.path == "/callback" and "token" in params:
                token_result["token"] = params["token"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"""<html><body style="font-family:system-ui;text-align:center;padding:60px;background:#0a0e17;color:#fff">
                    <h1 style="color:#00ff87">Authenticated!</h1>
                    <p>You can close this tab and return to the CLI.</p>
                </body></html>""")
            else:
                token_result["error"] = "No token received"
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Authentication failed")

            # Shut down the server after handling
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, format, *args):
            pass  # Suppress HTTP logs

    # Start local callback server (finds available port)
    callback_port = _find_available_port()
    server = HTTPServer(("127.0.0.1", callback_port), CallbackHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # Open browser with callback URL
    # Token is passed via URL query to localhost only — same pattern as
    # gh auth login, gcloud auth login. Never leaves the local machine.
    callback_url = f"http://localhost:{callback_port}/callback"
    login_url = f"{FRONTEND_URL}/login?cli_callback={callback_url}"
    webbrowser.open(login_url)

    # Wait for callback (timeout 120 seconds)
    server_thread.join(timeout=120)
    server.shutdown()

    if token_result["token"]:
        token = token_result["token"]
        os.makedirs(os.path.dirname(_TOKEN_PATH), exist_ok=True)
        with open(_TOKEN_PATH, "w") as f:
            f.write(token)
        # Restrict file permissions to owner only (0o600)
        try:
            os.chmod(_TOKEN_PATH, 0o600)
        except OSError:
            pass  # Windows doesn't support Unix permissions

        # Fetch user info
        import requests
        me_res = requests.get(
            f"{REMOTE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        user_info = me_res.json() if me_res.ok else {}

        return json.dumps({
            "status": "authenticated",
            "email": user_info.get("email", ""),
            "is_admin": user_info.get("is_superuser", False),
            "token_cached": _TOKEN_PATH,
        })
    else:
        return json.dumps({
            "status": "error",
            "message": token_result.get("error", "Login timed out. Please try again."),
        })


@mcp.tool()
def whoami() -> str:
    """Show which Praxys account is currently authenticated."""
    if not IS_REMOTE:
        uid = _local_user_id()
        db = _local_db()
        try:
            from db.models import User
            user = db.query(User).filter(User.id == uid).first()
            return json.dumps({
                "mode": "local",
                "email": user.email if user else "unknown",
                "user_id": uid,
            })
        finally:
            db.close()

    if not os.path.exists(_TOKEN_PATH):
        return json.dumps({"status": "not_authenticated", "message": _NOT_AUTHENTICATED_MSG})

    import requests
    headers = _get_remote_headers()
    res = requests.get(f"{REMOTE_URL}/api/auth/me", headers=headers, timeout=10)
    if res.status_code == 401:
        return json.dumps({"status": "token_expired", "message": "Token expired. Please run `login` again."})
    res.raise_for_status()
    data = res.json()
    return json.dumps({
        "mode": "remote",
        "url": REMOTE_URL,
        "email": data.get("email"),
        "is_admin": data.get("is_superuser", False),
    })


if __name__ == "__main__":
    mcp.run()
