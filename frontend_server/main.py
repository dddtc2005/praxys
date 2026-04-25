"""Static-file server for the Praxys frontend.

This module runs on a *separate* App Service site (`praxys-frontend`) from
the API (`trainsight-app`). Both share the same Plan B1, so adding this
site costs $0 incremental — App Service Plans support up to 10 sites.

Why a separate site instead of mounting StaticFiles inside ``api/main.py``:

- The frontend artifact (`web/dist/`) becomes cloud-portable. The same
  build can later sit on Tencent COS (CN audience, post-ICP) without any
  Azure-specific glue. Backend stays singular at ``api.praxys.run``;
  CN frontend → Tencent CDN, OS frontend → Azure App Service. DNS
  GeoDNS at DnsPod handles the split.
- API and frontend deploys decouple. Frontend deploys are now a few
  hundred kilobytes of static files (and a 30-line FastAPI shim), seconds
  to ship. Backend deploys keep their full Python deps + tests.
- Failure isolation. An API outage no longer takes the static frontend
  down (PWA-precached clients keep working; cold loads still resolve to
  the static shell, which then shows a clear error state if the API is
  unreachable).

A SPA fallback (404 → index.html) is implemented by subclassing
``StaticFiles`` rather than adding a separate catchall route, because the
mount-based approach preserves Starlette's automatic MIME-type handling
for static assets — a custom catchall would re-derive types by hand.
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import Response

# Default location: two parents up from this file → repo root → web/dist.
# The deploy zip preserves this layout. Tests pass an explicit path to
# ``create_app(dist_dir=...)`` instead of patching this default.
_DEFAULT_DIST_DIR = Path(__file__).resolve().parent.parent / "web" / "dist"


_ASSET_SUFFIXES = (
    ".js", ".mjs", ".css", ".map", ".woff2", ".woff", ".ttf",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".json", ".txt", ".webmanifest", ".xml",
)


def _looks_like_asset(path: str) -> bool:
    return path.lower().endswith(_ASSET_SUFFIXES)


class SPAStaticFiles(StaticFiles):
    """``StaticFiles`` that falls back to ``index.html`` on 404.

    React Router (and any client-side router) needs every non-asset URL
    to return the SPA shell so the router can take over on the client.
    Vanilla ``StaticFiles`` returns 404 for anything that isn't on disk —
    fine for asset paths (``/assets/index-xyz.js``) but breaks
    ``/today``, ``/training``, etc. We override 404 specifically for
    routes that look like SPA navigation, and let asset 404s through so
    a missing asset stays a real 404 (otherwise broken builds silently
    return ``index.html`` and the failure becomes invisible).
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            # Asset paths (under /assets/, or with a known static extension)
            # genuinely 404 — don't paper over them.
            if path.startswith("assets/") or _looks_like_asset(path):
                raise
            return await super().get_response("index.html", scope)


def create_app(dist_dir: Path | None = None) -> FastAPI:
    """Build the static-serving FastAPI app rooted at ``dist_dir``.

    Factory shape (rather than a module-level singleton) so tests can
    point at a fixture-built dist tree without monkeypatching module
    state. Production callers use the bare ``app`` object below.
    """
    if dist_dir is None:
        dist_dir = _DEFAULT_DIST_DIR

    app = FastAPI(title="Praxys Frontend", version="1.0.0")

    @app.middleware("http")
    async def add_response_headers(request: Request, call_next):
        """Set cache-control + browser security headers on every response.

        Cache-control by path shape:
        - Hashed assets under ``/assets/`` are content-addressed (Vite emits
          filenames with content hashes), so they're safe to cache for a year.
        - The SPA shell at ``/index.html`` (and SPA-router fallbacks that
          end up serving it) must revalidate on every load — otherwise a
          deploy doesn't reach already-loaded clients until they hard-refresh.

        Security headers ported from the deleted ``staticwebapp.config.json``
        ``globalHeaders`` block. Without these, prod silently regressed from
        nosniff/X-Frame/Referrer-Policy when the frontend moved off SWA — a
        change that gets caught by no automated test if we don't assert it.
        """
        response: Response = await call_next(request)
        path = request.url.path
        if path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif _looks_like_asset(path):
            # Brand assets, fonts, favicon — long but not immutable.
            response.headers["Cache-Control"] = "public, max-age=86400"
        else:
            # Anything that resolves to index.html (root, SPA routes) must
            # revalidate so a deploy is visible on the next refresh.
            response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

        # Security headers — set on every response, asset or shell. Cheap,
        # universally applicable, and the cost of a missing header is
        # measured in vulnerabilities not bytes.
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.get("/healthz")
    async def healthz() -> dict:
        """Liveness probe — separate from the backend's ``/api/health``.

        App Service's health-check feature (and any external uptime probe)
        can hit this to verify the static container is responding without
        crossing into the API site.
        """
        return {"ok": True, "service": "praxys-frontend"}

    # Mount last so the explicit /healthz route above wins. ``html=True``
    # makes ``/`` resolve to ``index.html`` automatically. ``check_dir=False``
    # defers the existence check to request time — important because
    # ``app = create_app()`` runs at module import, and a fresh checkout
    # without ``web/dist/`` (e.g. running pytest before any frontend build)
    # would otherwise crash on import.
    app.mount(
        "/",
        SPAStaticFiles(directory=str(dist_dir), html=True, check_dir=False),
        name="static",
    )
    return app


# Production entry point. Uvicorn / App Service runs:
#   uvicorn frontend_server.main:app --host 0.0.0.0 --port 8000
app = create_app()
