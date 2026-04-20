"""Praxys API — FastAPI application with SQLite backend and JWT auth."""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env from project root for local config (encryption key, JWT secret, etc.)
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from api.auth import get_current_user_id
from api.env_compat import getenv_compat
from api.views import utc_isoformat
from db.session import get_db

from db.session import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    init_db()
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


app = FastAPI(title="Praxys API", version="2.0.0", lifespan=lifespan)

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

# Admin routes
from api.routes.admin import router as admin_router
app.include_router(admin_router, prefix="/api", tags=["admin"])

# Data routes
from api.routes import today, training, goal, history, plan, settings, sync, science, insights
from api.routes import ai as ai_routes

for router_module in [today, training, goal, history, plan, settings, sync, science, ai_routes, insights]:
    app.include_router(router_module.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


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
