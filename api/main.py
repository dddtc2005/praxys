"""Trail Running Dashboard API."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

from api.routes import today, training, goal, history, plan, settings, sync, science

app = FastAPI(title="Trail Running Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)

app.include_router(today.router, prefix="/api")
app.include_router(training.router, prefix="/api")
app.include_router(goal.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(plan.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(sync.router, prefix="/api")
app.include_router(science.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
