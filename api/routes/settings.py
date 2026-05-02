"""User settings endpoints.

Supports both file-based (backward compat) and DB-based config persistence.
When user_id and db are available (from auth), uses DB; otherwise falls back to files.
"""
from datetime import datetime, timedelta, timezone
import logging
import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit
from dataclasses import asdict
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from analysis.config import (
    load_config,
    save_config,
    load_config_from_db,
    save_config_to_db,
    TrainingBase,
    PLATFORM_CAPABILITIES,
)
from analysis.providers import available_providers
from analysis.thresholds import detect_thresholds
from analysis.training_base import get_display_config
from api.auth import get_data_user_id, require_write_access
from api.env_compat import getenv_compat
from api.views import utc_isoformat
from db.session import get_db
from db.sync_scheduler import (
    ALLOWED_SYNC_INTERVAL_HOURS,
    DEFAULT_SYNC_INTERVAL_HOURS,
    normalize_sync_interval_hours,
)

router = APIRouter()


SUPPORTED_LANGUAGES = {"en", "zh"}
_STRAVA_STATE_TTL_MINUTES = 10


class SettingsUpdate(BaseModel):
    """Partial update for user settings."""

    display_name: str | None = None
    unit_system: str | None = None
    connections: list[str] | None = None
    # dict[str, Any] so the nested `threshold_sources` mapping
    # (e.g. {"threshold_sources": {"cp_estimate": "stryd"}}) flows through.
    preferences: dict[str, Any] | None = None
    training_base: TrainingBase | None = None
    thresholds: dict[str, Any] | None = None
    zones: dict[str, list[float]] | None = None
    goal: dict[str, Any] | None = None
    source_options: dict[str, Any] | None = None
    language: str | None = None


def _detect_thresholds_from_db(user_id: str, db) -> dict:
    """Auto-detect thresholds from fitness_data in the database.

    For each threshold, returns:

        {
          "value":  latest value (float),           // display convenience
          "source": source of the latest value,
          "options": [                              // all known sources
            {"source": "stryd",  "value": 265.0, "date": "2026-04-20"},
            {"source": "garmin", "value": 350.0, "date": "2026-04-22"},
          ]
        }

    ``options`` powers the Settings UI's source selector when a threshold has
    multiple provider sources (typically CP — Stryd vs Garmin). With only one
    source, the selector can stay hidden and the single value is shown as
    read-only. With zero sources the threshold is simply absent from the
    result.
    """
    from db.models import FitnessData

    result: dict = {}
    # (metric_type, threshold_key, default_source_when_row.source_is_null)
    metric_map = [
        ("cp_estimate", "cp_watts", "stryd"),
        ("lthr_bpm", "lthr_bpm", "garmin"),
        ("lt_pace_sec_km", "threshold_pace_sec_km", "garmin"),
        ("max_hr_bpm", "max_hr_bpm", "garmin"),
        ("rest_hr_bpm", "rest_hr_bpm", "garmin"),
    ]

    for metric_type, threshold_key, default_source in metric_map:
        # Filter null-date rows at the DB level so the invariant "rows[0]
        # is the latest" holds regardless of SQLite's NULL-ordering quirks.
        # Python-side per-source grouping: <100 rows per user in practice,
        # so a subquery-less approach keeps this readable.
        rows = (
            db.query(FitnessData)
            .filter(
                FitnessData.user_id == user_id,
                FitnessData.metric_type == metric_type,
                FitnessData.value.isnot(None),
                FitnessData.date.isnot(None),
            )
            .order_by(FitnessData.date.desc())
            .all()
        )
        if not rows:
            continue
        seen_sources: dict[str, FitnessData] = {}
        for row in rows:
            src = row.source or default_source
            # First occurrence wins — rows are already date-desc, so this is
            # the most recent row per source.
            if src not in seen_sources:
                seen_sources[src] = row
        options: list[dict] = []
        for src, r in seen_sources.items():
            try:
                options.append({
                    "source": src,
                    "value": round(float(r.value), 1),
                    "date": r.date.isoformat() if r.date else None,
                })
            except (TypeError, ValueError) as exc:
                # One malformed row mustn't blank out the whole Settings page.
                logger.warning(
                    "detect_thresholds: skipping row %s for user %s (%s=%r): %s",
                    r.id, user_id, metric_type, r.value, exc,
                )
        if not options:
            continue
        options.sort(key=lambda o: o["date"] or "", reverse=True)
        # Use options[0] rather than rows[0] so the displayed value always
        # matches one of the options the UI will render.
        result[threshold_key] = {
            "value": options[0]["value"],
            "source": options[0]["source"],
            "options": options,
        }

    # Fallback: derive max HR from activities if fitness_data has no row.
    # Exposed as a synthetic "activities" source so the UI can still show a
    # value — users can't select a different source when there isn't one.
    if "max_hr_bpm" not in result:
        from db.models import Activity
        from sqlalchemy import func
        max_hr = db.query(func.max(Activity.max_hr)).filter(
            Activity.user_id == user_id,
            Activity.max_hr.isnot(None),
        ).scalar()
        if max_hr:
            result["max_hr_bpm"] = {
                "value": round(float(max_hr), 1),
                "source": "activities",
                "options": [
                    {"source": "activities", "value": round(float(max_hr), 1), "date": None},
                ],
            }

    return result


def resolve_thresholds(
    config_thresholds: dict,
    detected: dict,
    threshold_sources: dict | None = None,
    activity_source: str | None = None,
) -> dict:
    """Pick the effective value for each threshold from detected sources.

    ``config_thresholds`` is ignored (kept in the signature so callers don't
    break; remove on the next major API version). Manual numeric overrides
    are not supported — source selection lives in ``threshold_sources``.

    Selection order:
        1. Explicit: ``threshold_sources[metric_type]`` if that source has
           an entry in ``options``.
        2. Default: ``activity_source`` — keeps CP aligned with the
           activities the user is viewing.
        3. Fallback: ``options[0]``. _detect_thresholds_from_db sorts
           options by date desc, so this is the most recent row.
    """
    _ = config_thresholds  # intentionally unused
    # metric_type keys match fitness_data.metric_type for all but CP.
    threshold_to_metric = {
        "cp_watts": "cp_estimate",
        "lthr_bpm": "lthr_bpm",
        "threshold_pace_sec_km": "lt_pace_sec_km",
        "max_hr_bpm": "max_hr_bpm",
        "rest_hr_bpm": "rest_hr_bpm",
    }
    sources_pref = threshold_sources or {}
    effective: dict[str, Any] = {}

    for key, metric_type in threshold_to_metric.items():
        info = detected.get(key)
        if not info or not info.get("options"):
            effective[key] = {"value": None, "origin": "none"}
            continue
        options = info["options"]
        preferred = sources_pref.get(metric_type) or activity_source
        picked = None
        if preferred:
            picked = next((o for o in options if o["source"] == preferred), None)
            if picked is None:
                # User chose a source that has no data yet; log so the
                # apparent mismatch between selection and displayed value
                # is visible in server logs.
                logger.debug(
                    "resolve_thresholds: preferred source %r for %s has no data; "
                    "falling back to latest (%s=%s)",
                    preferred, metric_type, options[0]["source"], options[0]["value"],
                )
        if picked is None:
            # latest — invariant maintained by _detect_thresholds_from_db's
            # `options.sort(key=...date, reverse=True)`.
            picked = options[0]
        effective[key] = {
            "value": picked["value"],
            "origin": f"auto ({picked['source']})",
        }
    return effective


@router.get("/settings")
def get_settings(
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Return current user config, platform capabilities, detected thresholds, and display config."""
    config = load_config_from_db(user_id, db)
    avail = available_providers()
    detected = _detect_thresholds_from_db(user_id, db)
    effective = resolve_thresholds(
        config.thresholds,
        detected,
        threshold_sources=config.preferences.get("threshold_sources"),
        activity_source=config.preferences.get("activities"),
    )

    return {
        "config": asdict(config),
        "platform_capabilities": PLATFORM_CAPABILITIES,
        "available_providers": {
            "activities": avail.get("activities", []),
            "recovery": avail.get("recovery", []),
            "fitness": avail.get("fitness", []),
            "plan": avail.get("plan", []),
        },
        "available_bases": ["power", "hr", "pace"],
        "display": get_display_config(config.training_base),
        "detected_thresholds": detected,
        "effective_thresholds": effective,
        "sync_interval_options_hours": list(ALLOWED_SYNC_INTERVAL_HOURS),
        "default_sync_interval_hours": DEFAULT_SYNC_INTERVAL_HOURS,
    }


@router.put("/settings")
def update_settings(
    body: SettingsUpdate,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Update user settings and persist to database."""
    config = load_config_from_db(user_id, db)

    if body.display_name is not None:
        config.display_name = body.display_name
    if body.unit_system is not None:
        config.unit_system = body.unit_system
    if body.training_base is not None:
        config.training_base = body.training_base
    if body.connections is not None:
        config.connections = body.connections
    if body.preferences is not None:
        config.preferences.update(body.preferences)
    # `thresholds` updates are accepted-and-dropped: manual numeric overrides
    # are no longer supported; source selection lives in
    # ``preferences.threshold_sources``. Kept in the schema for API compat
    # with older clients. A non-empty payload means a client still thinks it
    # can write numeric thresholds — log so we can find it.
    if body.thresholds:
        logger.info(
            "settings.update: discarding legacy thresholds payload "
            "(user %s, keys=%s)",
            user_id, sorted(body.thresholds.keys()),
        )
    if body.zones is not None:
        config.zones.update(body.zones)
    if body.goal is not None:
        config.goal.update(body.goal)
    if body.source_options is not None:
        source_options_update = dict(body.source_options)
        if "sync_interval_hours" in source_options_update:
            try:
                source_options_update["sync_interval_hours"] = normalize_sync_interval_hours(
                    source_options_update["sync_interval_hours"]
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        config.source_options.update(source_options_update)
    if body.language is not None:
        if body.language not in SUPPORTED_LANGUAGES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported language: {body.language}. Supported: {sorted(SUPPORTED_LANGUAGES)}",
            )
        config.language = body.language

    # Bust ETag caches keyed on config (Today, Training, Goal, History,
    # Science). A settings edit can flip training_base, language, or goal —
    # any of which alters every endpoint's payload, so we bump unconditionally.
    # Bump BEFORE save_config_to_db so the commit inside save_config covers
    # both the config change and the revision bump atomically.
    from db.cache_revision import bump_revisions
    bump_revisions(db, user_id, ["config"])
    save_config_to_db(user_id, config, db)

    return {
        "status": "ok",
        "config": asdict(config),
        "display": get_display_config(config.training_base),
    }


# ---------------------------------------------------------------------------
# Platform connection management
# ---------------------------------------------------------------------------


class ConnectPlatformRequest(BaseModel):
    """Credentials for connecting a platform."""
    # Garmin / Stryd
    email: str | None = None
    password: str | None = None
    # Oura
    token: str | None = None
    # Garmin-specific
    is_cn: bool = False
    # COROS-specific region
    region: str | None = None
    # Strava manual token fallback
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: int | None = None
    scope: str | None = None
    athlete_id: int | None = None
    athlete_username: str | None = None


class StravaOAuthStartRequest(BaseModel):
    """Start parameters for the browser-based Strava OAuth flow."""

    web_origin: str | None = None
    return_to: str = "/settings"
    client_id: str | None = None
    client_secret: str | None = None


def _jwt_secret() -> str:
    """Return the signing secret used for short-lived Strava OAuth state."""

    from api.auth_secrets import get_jwt_secret

    return get_jwt_secret()


def _validate_web_origin(raw_origin: str | None) -> str:
    """Validate a frontend origin used for the Strava return redirect."""

    if not raw_origin:
        raise HTTPException(400, "Missing web origin for Strava OAuth flow")
    parsed = urlparse(raw_origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "Invalid web origin for Strava OAuth flow")
    return f"{parsed.scheme}://{parsed.netloc}"


def _validate_return_to(return_to: str | None) -> str:
    """Restrict post-auth redirects to local app paths."""

    value = (return_to or "/settings").strip()
    if not value.startswith("/") or value.startswith("//"):
        return "/settings"
    return value


def _strava_client_config(user_id: str | None = None, db: Session | None = None) -> tuple[str, str]:
    """Load Strava OAuth client credentials from user's stored connection or env vars."""

    if user_id and db:
        creds = _get_strava_creds(user_id, db)
        if creds:
            cid = creds.get("client_id")
            csec = creds.get("client_secret")
            if cid and csec:
                return cid, csec

    client_id = getenv_compat("STRAVA_CLIENT_ID")
    client_secret = getenv_compat("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail="Strava OAuth is not configured. Provide your Strava Client ID and Client Secret when connecting.",
        )
    return client_id, client_secret


def _get_strava_creds(user_id: str, db: Session) -> dict | None:
    """Return decrypted Strava credentials for a user, or None."""
    import json as json_mod
    from db.crypto import get_vault
    from db.models import UserConnection

    conn = db.query(UserConnection).filter(
        UserConnection.user_id == user_id,
        UserConnection.platform == "strava",
    ).first()
    if not conn or not conn.encrypted_credentials or not conn.wrapped_dek:
        return None
    vault = get_vault()
    return json_mod.loads(vault.decrypt(conn.encrypted_credentials, conn.wrapped_dek))


def _store_strava_client_creds(user_id: str, client_id: str, client_secret: str, db: Session) -> None:
    """Store (or update) Strava client_id/client_secret in the user's connection.

    If a connection already exists, the client credentials are merged into the
    existing encrypted payload so OAuth tokens aren't lost. The connection
    status is NOT set to "connected" — that only happens after the OAuth
    callback successfully exchanges the authorization code for tokens.
    """
    import json as json_mod
    from db.crypto import get_vault
    from db.models import UserConnection

    existing = _get_strava_creds(user_id, db) or {}
    existing["client_id"] = client_id
    existing["client_secret"] = client_secret

    vault = get_vault()
    encrypted_data, wrapped_dek = vault.encrypt(json_mod.dumps(existing))

    conn = db.query(UserConnection).filter(
        UserConnection.user_id == user_id,
        UserConnection.platform == "strava",
    ).first()

    if conn:
        conn.encrypted_credentials = encrypted_data
        conn.wrapped_dek = wrapped_dek
        # Keep existing status — don't flip to "connected" yet
    else:
        conn = UserConnection(
            user_id=user_id,
            platform="strava",
            encrypted_credentials=encrypted_data,
            wrapped_dek=wrapped_dek,
            status="disconnected",
        )
        db.add(conn)
    db.commit()


def _strava_redirect_uri(request: Request) -> str:
    """Resolve the callback URI registered with the Strava app."""

    override = getenv_compat("STRAVA_REDIRECT_URI")
    if override:
        return override
    return str(request.url_for("strava_oauth_callback"))


def _encode_strava_state(user_id: str, web_origin: str, return_to: str) -> str:
    """Create a short-lived signed state token for the Strava OAuth callback."""

    payload = {
        "sub": user_id,
        "purpose": "strava_connect",
        "web_origin": web_origin,
        "return_to": return_to,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_STRAVA_STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def _decode_strava_state(state: str) -> dict[str, Any]:
    """Validate and decode a Strava OAuth state token."""

    try:
        payload = jwt.decode(state, _jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(400, "Invalid Strava OAuth state") from exc
    if payload.get("purpose") != "strava_connect":
        raise HTTPException(400, "Invalid Strava OAuth state")
    return payload


def _upsert_connection_credentials(
    user_id: str,
    platform: str,
    creds: dict[str, Any],
    db: Session,
) -> None:
    """Encrypt and upsert platform credentials in the existing connection row."""

    import json as json_mod

    from db.crypto import get_vault
    from db.models import UserConnection

    vault = get_vault()
    encrypted_data, wrapped_dek = vault.encrypt(json_mod.dumps(creds))

    conn = db.query(UserConnection).filter(
        UserConnection.user_id == user_id,
        UserConnection.platform == platform,
    ).first()

    caps = PLATFORM_CAPABILITIES.get(platform, {})
    prefs = {k: v for k, v in caps.items() if v}

    if conn:
        # Re-uploading credentials is the user's "I fixed it" signal —
        # reset scheduler-backoff state so an auth_required connection
        # rejoins the regular schedule once the user clears whatever
        # gate (CAPTCHA, password change, MFA) blocked it.
        from db.sync_scheduler import reset_connection_backoff

        conn.encrypted_credentials = encrypted_data
        conn.wrapped_dek = wrapped_dek
        conn.status = "connected"
        conn.preferences = prefs
        reset_connection_backoff(conn)
    else:
        conn = UserConnection(
            user_id=user_id,
            platform=platform,
            encrypted_credentials=encrypted_data,
            wrapped_dek=wrapped_dek,
            status="connected",
            preferences=prefs,
        )
        db.add(conn)


def _strava_redirect_target(
    web_origin: str,
    return_to: str,
    *,
    status: str,
    message: str | None = None,
) -> str:
    """Build the final frontend redirect target after the Strava callback."""

    split = urlsplit(return_to)
    params = parse_qsl(split.query, keep_blank_values=True)
    params.append(("strava", status))
    if message:
        params.append(("strava_message", message))
    target = urlunsplit(("", "", split.path, urlencode(params), split.fragment))
    return f"{web_origin}{target}"


@router.get("/settings/connections")
def get_connections(
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Return connected platforms and their status (credentials are never returned)."""
    from db.models import UserConnection

    connections = db.query(UserConnection).filter(
        UserConnection.user_id == user_id,
    ).all()

    result = {}
    for conn in connections:
        result[conn.platform] = {
            "status": conn.status,
            "last_sync": utc_isoformat(conn.last_sync),
            "has_credentials": conn.encrypted_credentials is not None,
            # Surfaced so the UI can show "Reconnect required" instead of
            # "Sync" when status is auth_required, and so it can show
            # "Next retry in 4h" while a transient backoff is in effect.
            # Both are read-only — the user clears them by reconnecting.
            "next_retry_at": utc_isoformat(conn.next_retry_at),
            "consecutive_failures": conn.consecutive_failures or 0,
            "last_error": conn.last_error,
        }
    return {"connections": result}


@router.post("/settings/connections/strava/start")
def start_strava_oauth(
    body: StravaOAuthStartRequest,
    request: Request,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Return the Strava OAuth authorize URL for the current user."""

    from sync.strava_sync import DEFAULT_SCOPE, build_authorize_url

    # If the user supplied client credentials, persist them now so the
    # callback (and future token refreshes) can read them back.
    if body.client_id and body.client_secret:
        _store_strava_client_creds(user_id, body.client_id, body.client_secret, db)

    client_id, _client_secret = _strava_client_config(user_id, db)
    web_origin = _validate_web_origin(body.web_origin or request.headers.get("origin"))
    return_to = _validate_return_to(body.return_to)
    state = _encode_strava_state(user_id, web_origin, return_to)
    authorize_url = build_authorize_url(
        client_id,
        _strava_redirect_uri(request),
        state,
        scope=DEFAULT_SCOPE,
    )
    return {"authorize_url": authorize_url}


@router.get("/settings/connections/strava/callback", name="strava_oauth_callback")
def strava_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    scope: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Handle the Strava OAuth callback and persist the encrypted tokens."""

    payload = _decode_strava_state(state or "")
    web_origin = _validate_web_origin(payload.get("web_origin"))
    return_to = _validate_return_to(payload.get("return_to"))

    if error:
        return RedirectResponse(
            _strava_redirect_target(web_origin, return_to, status="error", message=error)
        )
    if not code:
        return RedirectResponse(
            _strava_redirect_target(
                web_origin, return_to, status="error", message="missing_code"
            )
        )

    from sync.strava_sync import DEFAULT_SCOPE, exchange_code_for_token, fetch_athlete_api

    user_id_from_state = str(payload["sub"])
    client_id, client_secret = _strava_client_config(user_id_from_state, db)
    try:
        token_payload = exchange_code_for_token(code, client_id, client_secret)
        athlete = token_payload.get("athlete") or {}
        access_token = token_payload.get("access_token")
        if access_token and not athlete:
            athlete = fetch_athlete_api(access_token)
    except Exception:
        logger.exception(
            "Strava OAuth callback failed during token exchange/profile fetch"
        )
        return RedirectResponse(
            _strava_redirect_target(
                web_origin,
                return_to,
                status="error",
                message="oauth_callback_failed",
            )
        )

    # Merge OAuth tokens into existing credentials so client_id/client_secret
    # (stored during /start) are preserved.
    existing = _get_strava_creds(user_id_from_state, db) or {}
    existing.update({
        "access_token": token_payload.get("access_token"),
        "refresh_token": token_payload.get("refresh_token"),
        "expires_at": int(token_payload.get("expires_at") or 0),
        "expires_in": int(token_payload.get("expires_in") or 0),
        "scope": scope or DEFAULT_SCOPE,
        "athlete": athlete,
    })
    _upsert_connection_credentials(user_id_from_state, "strava", existing, db)
    db.commit()

    return RedirectResponse(
        _strava_redirect_target(web_origin, return_to, status="connected")
    )


@router.post("/settings/connections/{platform}")
def connect_platform(
    platform: str,
    body: ConnectPlatformRequest,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Connect a platform by storing encrypted credentials."""

    if platform not in PLATFORM_CAPABILITIES:
        return {"status": "error", "message": f"Unknown platform: {platform}"}

    # Build credentials dict based on platform
    if platform in ("garmin", "stryd"):
        if not body.email or not body.password:
            return {"status": "error", "message": "email and password required"}
        creds = {"email": body.email, "password": body.password}
        if platform == "garmin":
            creds["is_cn"] = body.is_cn
    elif platform == "coros":
        if not body.email or not body.password:
            return {"status": "error", "message": "email and password required"}
        coros_region = body.region or "us"
        if coros_region not in ("eu", "us", "cn"):
            coros_region = "us"
        creds: dict[str, Any] = {
            "email": body.email,
            "password": body.password,
            "region": coros_region,
        }
    elif platform == "oura":
        if not body.token:
            return {"status": "error", "message": "token required"}
        creds = {"token": body.token}
    elif platform == "strava":
        if not body.access_token or not body.refresh_token:
            return {"status": "error", "message": "access_token and refresh_token required"}
        creds = {
            "access_token": body.access_token,
            "refresh_token": body.refresh_token,
            "expires_at": int(body.expires_at or 0),
            "scope": body.scope or "read,activity:read_all,profile:read_all",
            "athlete": {
                "id": body.athlete_id,
                "username": body.athlete_username,
            },
        }
    else:
        return {"status": "error", "message": f"Unsupported platform: {platform}"}

    _upsert_connection_credentials(user_id, platform, creds, db)
    db.commit()

    # Invalidate cached OAuth tokens AFTER the new credentials are persisted:
    # if we cleared first and the commit then failed, the next sync would
    # re-auth with the old DB credentials and repopulate the tokenstore with
    # the old account's session — exactly the leak this guards against.
    if platform == "garmin":
        from api.routes.sync import clear_garmin_tokens
        clear_garmin_tokens(user_id)

    return {"status": "connected", "platform": platform}


@router.delete("/settings/connections/{platform}")
def disconnect_platform(
    platform: str,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Disconnect a platform — deletes stored credentials."""
    from db.models import UserConnection

    conn = db.query(UserConnection).filter(
        UserConnection.user_id == user_id,
        UserConnection.platform == platform,
    ).first()
    if conn:
        db.delete(conn)
        db.commit()

    if platform == "garmin":
        from api.routes.sync import clear_garmin_tokens
        clear_garmin_tokens(user_id)

    return {"status": "disconnected", "platform": platform}
