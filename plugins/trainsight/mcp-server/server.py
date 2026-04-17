#!/usr/bin/env python3
"""Trainsight MCP Server — dual-mode (local/remote) training data tools.

Mode detection:
  - TRAINSIGHT_URL env var set → remote mode (HTTP API with JWT auth)
  - TRAINSIGHT_URL not set → local mode (direct Python imports, dev user, DB)
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

mcp = FastMCP("trainsight", instructions="Training data tools for Trainsight dashboard")

# Mode detection
REMOTE_URL = os.environ.get("TRAINSIGHT_URL", "")
IS_REMOTE = bool(REMOTE_URL)


# ---------------------------------------------------------------------------
# Remote helpers (HTTP API)
# ---------------------------------------------------------------------------

_TOKEN_PATH = os.path.expanduser("~/.trainsight/token")

_NOT_AUTHENTICATED_MSG = (
    "Not authenticated. Please run the `login` tool first with your "
    "Trainsight email and password, or manually cache a token at ~/.trainsight/token"
)


def _get_remote_headers():
    """Get auth headers for remote API calls."""
    if os.path.exists(_TOKEN_PATH):
        with open(_TOKEN_PATH) as f:
            token = f.read().strip()
        if token:
            return {"Authorization": f"Bearer {token}"}
    return {}


def _check_auth_error(res):
    """Check for auth errors and return a helpful message."""
    if res.status_code == 401:
        raise RuntimeError(_NOT_AUTHENTICATED_MSG)
    res.raise_for_status()


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
    1. TRAINSIGHT_USER_ID env var (explicit override)
    2. First active user found in the database

    Raises RuntimeError if no users exist (register via the web UI first).
    """
    global _cached_user_id
    if _cached_user_id:
        return _cached_user_id

    # Check env var override
    env_uid = os.environ.get("TRAINSIGHT_USER_ID")
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
            data = {"status": "disconnected", "platform": platform}
        finally:
            db.close()
    return json.dumps(data, indent=2, default=str)


# ---------------------------------------------------------------------------
# MCP Tools — Plans & Sync
# ---------------------------------------------------------------------------

@mcp.tool()
def push_training_plan(plan_csv: str) -> str:
    """Push an AI-generated training plan. Pass the plan as CSV text (date,workout_type,planned_duration_min,target_power_min,target_power_max,workout_description)."""
    if IS_REMOTE:
        data = _remote_post("/api/plan/upload", {"csv": plan_csv})
    else:
        import csv
        import io
        from db import sync_writer
        db = _local_db()
        try:
            reader = csv.DictReader(io.StringIO(plan_csv))
            rows = list(reader)
            count = sync_writer.write_training_plan(
                _local_user_id(), rows, "ai", db
            )
            db.commit()
            data = {"status": "saved", "rows": count}
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
            if sources:
                # Sync individual sources
                results = []
                for s in sources:
                    res = requests.post(f"{url}/{s}", timeout=5)
                    results.append({"source": s, "status": res.json().get("status", "error")})
                data = {"results": results}
            else:
                res = requests.post(url, timeout=5)
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
                connections = db.query(UserConnection).filter(
                    UserConnection.user_id == _local_user_id()
                ).all()
                data = {}
                for conn in connections:
                    data[conn.platform] = {
                        "status": "idle",
                        "last_sync": conn.last_sync.isoformat() if conn.last_sync else None,
                        "connected": conn.status in ("connected", "error"),
                    }
            finally:
                db.close()
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def login() -> str:
    """Authenticate with Trainsight via browser login.

    Opens the Trainsight login page in your browser. After you log in,
    the token is automatically captured and cached for CLI use.
    No passwords are entered in the CLI.
    """
    if not IS_REMOTE:
        return json.dumps({"status": "skipped", "message": "Login not needed in local mode"})

    import threading
    import webbrowser
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs

    CALLBACK_PORT = 9876
    token_result = {"token": None, "error": None}

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

    # Start local callback server
    server = HTTPServer(("127.0.0.1", CALLBACK_PORT), CallbackHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # Open browser with callback URL
    callback_url = f"http://localhost:{CALLBACK_PORT}/callback"
    login_url = f"{REMOTE_URL}/login?cli_callback={callback_url}"
    webbrowser.open(login_url)

    # Wait for callback (timeout 120 seconds)
    server_thread.join(timeout=120)
    server.shutdown()

    if token_result["token"]:
        token = token_result["token"]
        os.makedirs(os.path.dirname(_TOKEN_PATH), exist_ok=True)
        with open(_TOKEN_PATH, "w") as f:
            f.write(token)

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
    """Show which Trainsight account is currently authenticated."""
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
