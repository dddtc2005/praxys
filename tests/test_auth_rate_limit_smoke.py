"""Production-wiring smoke tests for AuthRateLimitMiddleware.

Imports the real api.main:app (not a stub fixture) to catch regressions that
would slip past tests/test_auth_rate_limit.py — e.g., dropping
app.add_middleware(AuthRateLimitMiddleware) or inverting is_rate_limit_disabled().

Uses the same module-reload pattern as tests/test_wechat_auth.py so env vars
are honoured at api.main import time.
"""
from __future__ import annotations

import importlib
import tempfile

import pytest
from fastapi.testclient import TestClient

_FAKE_IP = "198.51.100.99"
_LOGIN_URL = "/api/auth/login"
_BAD_CREDS = {"username": "nobody@example.com", "password": "wrong-password"}
_XFF = {"X-Forwarded-For": _FAKE_IP}


def _build_app(monkeypatch, data_dir: str, rate_limit_disabled: bool):
    """Rebuild api.main inside *data_dir* with the limiter on or off."""
    monkeypatch.setenv("DATA_DIR", data_dir)
    monkeypatch.setenv("TRAINSIGHT_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "TRAINSIGHT_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )
    monkeypatch.setenv("TRAINSIGHT_ADMIN_EMAIL", "")
    monkeypatch.delenv("WECHAT_MINIAPP_APPID", raising=False)
    monkeypatch.delenv("WECHAT_MINIAPP_SECRET", raising=False)

    if rate_limit_disabled:
        monkeypatch.setenv("PRAXYS_AUTH_RATE_LIMIT_DISABLED", "true")
    else:
        monkeypatch.delenv("PRAXYS_AUTH_RATE_LIMIT_DISABLED", raising=False)

    from db import session as db_session

    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    import api.users
    import api.invitations

    importlib.reload(api.users)
    importlib.reload(api.invitations)

    import api.main

    importlib.reload(api.main)
    return api.main.app


@pytest.mark.parametrize(
    "rate_limit_disabled,expect_429",
    [
        pytest.param(False, True, id="limiter-enabled"),
        pytest.param(True, False, id="limiter-disabled"),
    ],
)
def test_login_rate_limit_production_wiring(
    monkeypatch, rate_limit_disabled: bool, expect_429: bool
) -> None:
    """With the real app, exhausting the login limit fires 429; disabling bypasses it.

    Exercises the actual app.add_middleware(AuthRateLimitMiddleware) call in
    api/main.py — not just the standalone middleware fixture in
    test_auth_rate_limit.py. A regression that drops the middleware line,
    inverts is_rate_limit_disabled(), or reorders middleware so a later layer
    swallows the 429 would fail here.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        app = _build_app(monkeypatch, tmpdir, rate_limit_disabled)
        client = TestClient(app)

        # 10 requests — all must pass the limiter (or all pass because disabled).
        for i in range(10):
            r = client.post(_LOGIN_URL, data=_BAD_CREDS, headers=_XFF)
            assert r.status_code != 429, (
                f"unexpected 429 on attempt {i + 1} before limit reached: {r.text}"
            )

        # The 11th: blocked when limiter active, bypassed when disabled.
        r11 = client.post(_LOGIN_URL, data=_BAD_CREDS, headers=_XFF)

        if expect_429:
            assert r11.status_code == 429, (
                f"expected 429 on 11th attempt but got {r11.status_code}: {r11.text}"
            )
            payload = r11.json()
            assert payload["detail"] == "AUTH_RATE_LIMITED"
            assert isinstance(payload.get("retry_after"), int)
            assert int(r11.headers["retry-after"]) >= 1
        else:
            assert r11.status_code != 429, (
                f"limiter should be bypassed but got 429 on 11th attempt: {r11.text}"
            )
