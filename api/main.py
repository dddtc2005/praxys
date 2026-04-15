"""Trainsight API — FastAPI application with SQLite backend and JWT auth."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.session import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and start sync scheduler on startup."""
    init_db()
    from db.sync_scheduler import start_scheduler
    start_scheduler()
    yield


app = FastAPI(title="Trainsight API", version="2.0.0", lifespan=lifespan)

# CORS — configurable via env var
origins_str = os.environ.get(
    "TRAINSIGHT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
)
origins = [o.strip() for o in origins_str.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Auth routes
from api.users import fastapi_users, auth_backend

app.include_router(
    fastapi_users.get_auth_router(auth_backend),
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
from api.routes import today, training, goal, history, plan, settings, sync, science
from api.routes import ai as ai_routes

for router_module in [today, training, goal, history, plan, settings, sync, science, ai_routes]:
    app.include_router(router_module.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
