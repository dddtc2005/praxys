"""Tests for the static-file server (frontend_server/main.py).

Covers the three behaviours that would silently break in production:

1. SPA routing — non-asset paths must serve ``index.html`` so the
   client-side router can take over. A regression here turns ``/today``
   into a hard 404.
2. Real 404s for missing assets — if a build is broken and emits a
   reference to a missing asset, the user sees a real 404 (not a
   silently-rewritten index.html, which would mask the regression).
3. Cache-control headers — a regression that drops the immutable header
   on hashed assets means every page load re-fetches the entire
   bundle; a regression that drops must-revalidate on the SPA shell
   means deploys never reach already-loaded clients.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frontend_server.main import create_app


@pytest.fixture
def fake_dist(tmp_path):
    """Build a minimal fake ``web/dist/`` and return the path.

    Using ``create_app(dist_dir=...)`` instead of monkeypatching module
    state, so we don't have to reload the module (which re-runs its
    top-level code and would undo any patch).
    """
    dist = tmp_path / "web" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><html><body>SPA</body></html>")
    (dist / "assets" / "index-abc123.js").write_text("console.log('app');\n")
    (dist / "favicon.svg").write_text("<svg/>")
    return dist


@pytest.fixture
def client(fake_dist):
    return TestClient(create_app(dist_dir=fake_dist))


def test_root_returns_index_html(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "SPA" in res.text


def test_explicit_index_returns_index_html(client):
    res = client.get("/index.html")
    assert res.status_code == 200
    assert "SPA" in res.text


def test_spa_route_falls_back_to_index_html(client):
    """A client navigating to /today directly must get index.html so the
    router can take over. Same for /training, /goal, deep routes, etc.
    """
    for path in ("/today", "/training", "/goal", "/some/deep/route"):
        res = client.get(path)
        assert res.status_code == 200, f"{path} -> {res.status_code}"
        assert "SPA" in res.text


def test_known_asset_path_returns_real_content(client):
    res = client.get("/assets/index-abc123.js")
    assert res.status_code == 200
    assert "console.log" in res.text


def test_missing_asset_under_assets_dir_returns_real_404(client):
    """A 404 on /assets/* must NOT silently serve index.html. A broken
    build that references a non-existent chunk must surface as a real
    failure, otherwise we mask it behind a 200-with-html-body that
    confuses the browser's script loader.
    """
    res = client.get("/assets/does-not-exist.js")
    assert res.status_code == 404


def test_missing_file_with_known_extension_returns_real_404(client):
    """Even outside /assets/, a path ending in a static extension that
    doesn't resolve must 404 — same reasoning as above.
    """
    for path in ("/missing.js", "/missing.css", "/missing.png", "/missing.woff2"):
        res = client.get(path)
        assert res.status_code == 404, f"{path} -> {res.status_code}"


def test_cache_control_immutable_for_hashed_assets(client):
    res = client.get("/assets/index-abc123.js")
    cc = res.headers.get("cache-control", "")
    assert "max-age=31536000" in cc
    assert "immutable" in cc


def test_cache_control_short_for_brand_assets(client):
    res = client.get("/favicon.svg")
    cc = res.headers.get("cache-control", "")
    # Not under /assets/ → 1-day cache, not immutable.
    assert "max-age=86400" in cc
    assert "immutable" not in cc


def test_cache_control_must_revalidate_on_spa_shell(client):
    res = client.get("/")
    cc = res.headers.get("cache-control", "")
    assert "must-revalidate" in cc


def test_cache_control_must_revalidate_on_spa_route_fallback(client):
    """SPA-router fallbacks resolve to index.html — they must inherit
    the must-revalidate cache policy, not the asset cache policy.
    """
    res = client.get("/today")
    cc = res.headers.get("cache-control", "")
    assert "must-revalidate" in cc


def test_healthz_endpoint(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"ok": True, "service": "praxys-frontend"}


# Security headers — these were emitted by the deleted staticwebapp.config.json
# globalHeaders block. When the frontend moved off SWA the headers silently
# disappeared from prod responses; we assert them here so that regression
# can never happen quietly again.

@pytest.mark.parametrize("path", ["/", "/today", "/assets/index-abc123.js", "/favicon.svg"])
def test_security_headers_present_on_every_response(client, path):
    res = client.get(path)
    assert res.headers.get("x-content-type-options") == "nosniff", (
        f"{path}: missing X-Content-Type-Options"
    )
    assert res.headers.get("x-frame-options") == "DENY", (
        f"{path}: missing X-Frame-Options"
    )
    assert res.headers.get("referrer-policy") == "strict-origin-when-cross-origin", (
        f"{path}: missing Referrer-Policy"
    )
