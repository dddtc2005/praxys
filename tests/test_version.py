"""Tests for ``api/version.py`` and the ``/api/version`` endpoint.

The version surface is small but load-bearing — it's what the frontend
Settings page (and any operator hitting the URL during a deploy
verification) uses to confirm which build is live. A regression here
turns the version display into a silent ``develop`` even in production,
which is exactly the bug we'd never notice without a test.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from api.version import get_api_version


def test_get_api_version_falls_back_to_develop(monkeypatch, tmp_path):
    """No env var, no build file → ``develop``. The local-dev path."""
    monkeypatch.delenv("PRAXYS_API_VERSION", raising=False)
    monkeypatch.setattr("api.version._BUILD_FILE", tmp_path / "missing.txt")
    assert get_api_version() == "develop"


def test_get_api_version_reads_build_file(monkeypatch, tmp_path):
    """Build file written by the deploy workflow takes precedence over
    the develop fallback."""
    monkeypatch.delenv("PRAXYS_API_VERSION", raising=False)
    build_file = tmp_path / "_build_version.txt"
    build_file.write_text("2026.04.30.42-2790ff9\n", encoding="utf-8")
    monkeypatch.setattr("api.version._BUILD_FILE", build_file)
    assert get_api_version() == "2026.04.30.42-2790ff9"


def test_get_api_version_env_overrides_build_file(monkeypatch, tmp_path):
    """``PRAXYS_API_VERSION`` env var wins over the build file. Lets an
    operator override the displayed version without rebuilding the
    artifact (e.g. for an emergency rollback annotation)."""
    monkeypatch.setenv("PRAXYS_API_VERSION", "rollback-2026.04.29")
    build_file = tmp_path / "_build_version.txt"
    build_file.write_text("2026.04.30.42-2790ff9\n", encoding="utf-8")
    monkeypatch.setattr("api.version._BUILD_FILE", build_file)
    assert get_api_version() == "rollback-2026.04.29"


def test_get_api_version_strips_whitespace(monkeypatch, tmp_path):
    """Build file written by ``echo`` has a trailing newline; env var
    set via Azure portal might have stray spaces. Both should land on
    a clean version string."""
    monkeypatch.delenv("PRAXYS_API_VERSION", raising=False)
    build_file = tmp_path / "_build_version.txt"
    build_file.write_text("  2026.04.30  \n", encoding="utf-8")
    monkeypatch.setattr("api.version._BUILD_FILE", build_file)
    assert get_api_version() == "2026.04.30"


def test_get_api_version_ignores_empty_build_file(monkeypatch, tmp_path):
    """Empty build file (e.g. a deploy step that ran but produced no
    output) must not display as an empty version — it should fall
    through to the develop sentinel so the bug is visible."""
    monkeypatch.delenv("PRAXYS_API_VERSION", raising=False)
    build_file = tmp_path / "_build_version.txt"
    build_file.write_text("\n", encoding="utf-8")
    monkeypatch.setattr("api.version._BUILD_FILE", build_file)
    assert get_api_version() == "develop"


@pytest.fixture
def version_client(monkeypatch, tmp_path):
    """``TestClient`` with a controlled version source so the endpoint
    test asserts on a known string."""
    import tempfile

    from fastapi.testclient import TestClient

    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )
    monkeypatch.setenv("PRAXYS_API_VERSION", "2026.04.30.42-test")

    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    from api.main import app
    client = TestClient(app)
    yield client
    tmpdir.cleanup()


def test_version_endpoint_returns_current_version(version_client):
    """The endpoint must be public (no auth) and reflect whatever
    ``get_api_version()`` returns. Public so the frontend can show the
    version on the Login screen too if we ever want to."""
    res = version_client.get("/api/version")
    assert res.status_code == 200
    assert res.json() == {"version": "2026.04.30.42-test"}
