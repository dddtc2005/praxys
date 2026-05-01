"""Praxys API — FastAPI application with SQLite backend and JWT auth."""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Configure stdout logging before anything else — once configure_azure_monitor
# attaches its own handler to the root logger, a later basicConfig() call is a
# no-op (basicConfig only runs when no handlers are present).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

# Load .env from project root for local config (encryption key, JWT secret, etc.)
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Wire Azure Monitor before framework imports so auto-instrumentation
# (FastAPI, requests, SQLAlchemy, logging) hooks correctly. On App Service
# (detected via WEBSITE_SITE_NAME — the same signal CORS uses below) we
# authenticate to Application Insights via the system-assigned managed
# identity, so no instrumentation key or secret lives in app settings; the
# connection-string env var only names the routing endpoint. Off Azure the
# SDK falls back to connection-string auth if the env var happens to be
# set (useful for a contributor pointing at a dev resource). No-op when
# APPLICATIONINSIGHTS_CONNECTION_STRING is unset.
if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry import configure_azure_monitor
    if os.environ.get("WEBSITE_SITE_NAME"):
        from azure.identity import ManagedIdentityCredential
        # client_id=None → system-assigned MI. Set AZURE_CLIENT_ID in App
        # Service config to switch to a user-assigned MI later.
        _mi_client_id = os.environ.get("AZURE_CLIENT_ID")
        _credential = (
            ManagedIdentityCredential(client_id=_mi_client_id)
            if _mi_client_id
            else ManagedIdentityCredential()
        )
        configure_azure_monitor(credential=_credential)
    else:
        configure_azure_monitor()

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy.orm import Session

from api.auth import get_current_user_id
from api.env_compat import getenv_compat
from api.version import get_api_version
from api.views import utc_isoformat
from db.session import get_db

from db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    init_db()

    # Resolve the JWT secret eagerly so a misconfigured deployment (no
    # PRAXYS_JWT_SECRET and no dev opt-in) dies at boot rather than on the
    # first authenticated request — uvicorn treats a lifespan exception as
    # a failed start and won't route traffic.
    from api.auth_secrets import get_jwt_secret
    get_jwt_secret()

    # Start sync scheduler unless explicitly disabled.
    # On Azure with gunicorn pre-fork workers, each worker runs this lifespan,
    # so with the default-on behavior every worker spawns its own scheduler
    # thread. Per-row last_sync checks make duplicate ticks idempotent, but if
    # you want exactly one scheduler set PRAXYS_SYNC_SCHEDULER=false on
    # N-1 workers (or rely on a single-worker deployment).
    # Users can still trigger manual sync from UI/CLI at any time.
    logger = logging.getLogger(__name__)
    scheduler_enabled = (getenv_compat("SYNC_SCHEDULER", "true") or "true").lower() != "false"
    logger.info("Sync scheduler %s", "enabled" if scheduler_enabled else "disabled by env")
    if scheduler_enabled:
        from db.sync_scheduler import start_scheduler
        start_scheduler()
    try:
        yield
    finally:
        if scheduler_enabled:
            try:
                from db.sync_scheduler import stop_scheduler
                stop_scheduler()
            except Exception:
                logger.exception("Failed to stop sync scheduler cleanly")


app = FastAPI(title="Praxys API", version=get_api_version(), lifespan=lifespan)

# GZip API responses. Linux App Service's nginx proxy doesn't compress
# dynamic upstream responses by default, so without this, JSON payloads
# from /api/training, /api/plan, /api/today etc. ship uncompressed over
# the GFW. minimum_size=500 skips tiny responses where the compression
# overhead outweighs the savings. Added before other middleware so it
# runs last on the response path (middleware order = reverse LIFO).
app.add_middleware(GZipMiddleware, minimum_size=500)

# CORS — use FastAPI middleware for local dev only.
# On Azure, platform-level CORS is configured via `az webapp cors` and takes
# precedence. Using both causes conflicts (Azure handles preflight, but FastAPI
# middleware doesn't add headers to the actual response).
if not os.environ.get("WEBSITE_SITE_NAME"):
    # Not running on Azure App Service → add middleware for local dev
    origins_str = getenv_compat(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ) or ""
    origins = [o.strip() for o in origins_str.split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

# Per-IP rate limit on the auth surface — see api/auth_rate_limit.py for the
# threat model. Skipped only when explicitly disabled (tests / local dev).
from api.auth_rate_limit import AuthRateLimitMiddleware, is_rate_limit_disabled
if is_rate_limit_disabled():
    logging.getLogger(__name__).warning(
        "Auth rate limit disabled by PRAXYS_AUTH_RATE_LIMIT_DISABLED — "
        "/api/auth/* endpoints accept unlimited attempts per IP."
    )
else:
    app.add_middleware(AuthRateLimitMiddleware)

# Auth routes
from api.users import fastapi_users, auth_backend

app.include_router(
    fastapi_users.get_auth_router(auth_backend, requires_verification=False),
    prefix="/api/auth",
    tags=["auth"],
)

# Custom registration with invitation code check
from api.routes.register import register_router
app.include_router(register_router, prefix="/api/auth", tags=["auth"])

# WeChat Mini Program auth (login / link / register)
from api.routes.wechat import router as wechat_auth_router
app.include_router(wechat_auth_router, prefix="/api")

# Admin routes
from api.routes.admin import router as admin_router
app.include_router(admin_router, prefix="/api", tags=["admin"])

from api.routes.announcements import router as announcements_router
app.include_router(announcements_router, prefix="/api", tags=["announcements"])

# Data routes
from api.routes import today, training, goal, history, plan, settings, sync, science, insights
from api.routes import ai as ai_routes

for router_module in [today, training, goal, history, plan, settings, sync, science, ai_routes, insights]:
    app.include_router(router_module.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/version")
def version() -> dict:
    """Public — frontend Settings page reads this to surface the live
    API build alongside the bundled web version, mirroring the mini
    program's ``Praxys <version>`` line."""
    return {"version": get_api_version()}


@app.get("/api/auth/me")
def get_me(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Return current user profile including admin status."""
    from db.models import User
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return {
        "id": user.id,
        "email": user.email,
        "is_superuser": user.is_superuser,
        "is_demo": user.is_demo,
        "created_at": utc_isoformat(user.created_at),
    }
