"""Tests for the auth-endpoint rate limiter (api/auth_rate_limit.py).

Two layers of coverage:

- ``_SlidingWindow`` is exercised directly with a stubbed clock so the
  window-rollover and LRU-eviction paths run without real sleeps.
- The full ASGI middleware is exercised through a tiny FastAPI app
  (mirrors api/main.py wiring without depending on the auth machinery)
  to verify per-path bucketing, per-IP bucketing via X-Forwarded-For,
  the 429 body, and the Retry-After header.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth_rate_limit import (
    AuthRateLimitMiddleware,
    _SlidingWindow,
    _client_ip,
    is_rate_limit_disabled,
)


# ---------------------------------------------------------------------------
# _SlidingWindow unit tests
# ---------------------------------------------------------------------------


def test_sliding_window_allows_under_limit():
    win = _SlidingWindow(limit=3, window_secs=60, max_clients=10)
    for _ in range(3):
        allowed, retry = win.check_and_record("ip-a")
        assert allowed is True
        assert retry == 0


def test_sliding_window_blocks_at_limit_with_retry_after():
    win = _SlidingWindow(limit=2, window_secs=60, max_clients=10)
    win.check_and_record("ip-a")
    win.check_and_record("ip-a")
    allowed, retry = win.check_and_record("ip-a")
    assert allowed is False
    # Retry-After is bounded by the window length.
    assert 1 <= retry <= 60


def test_sliding_window_separates_keys():
    win = _SlidingWindow(limit=1, window_secs=60, max_clients=10)
    assert win.check_and_record("ip-a") == (True, 0)
    assert win.check_and_record("ip-b") == (True, 0)
    assert win.check_and_record("ip-a")[0] is False


def test_sliding_window_evicts_old_entries(monkeypatch):
    """Once timestamps fall outside the window, capacity is restored."""
    fake_now = [1000.0]
    monkeypatch.setattr(
        "api.auth_rate_limit.time.monotonic", lambda: fake_now[0]
    )
    win = _SlidingWindow(limit=2, window_secs=10, max_clients=10)
    win.check_and_record("ip-a")
    win.check_and_record("ip-a")
    assert win.check_and_record("ip-a")[0] is False
    fake_now[0] += 11  # roll past the window
    assert win.check_and_record("ip-a") == (True, 0)


def test_sliding_window_lru_caps_tracked_clients():
    win = _SlidingWindow(limit=10, window_secs=60, max_clients=2)
    win.check_and_record("ip-a")
    win.check_and_record("ip-b")
    win.check_and_record("ip-c")  # forces eviction of ip-a (oldest)
    # Re-recording ip-a creates a new bucket; previous count is gone.
    # If LRU did not evict, ip-a would still count as 1 here, but with
    # eviction we observe it as fresh.
    bucket_a_size_after = len(win._buckets["ip-a"]) if "ip-a" in win._buckets else 0
    assert bucket_a_size_after == 0 or "ip-a" not in win._buckets


# ---------------------------------------------------------------------------
# _client_ip unit tests
# ---------------------------------------------------------------------------


def _scope_with_xff(xff_value: bytes) -> dict:
    return {
        "type": "http",
        "headers": [(b"x-forwarded-for", xff_value)],
        "client": ("127.0.0.1", 50000),
    }


def test_client_ip_trusts_rightmost_by_default(monkeypatch):
    monkeypatch.delenv("PRAXYS_TRUSTED_PROXY_HOPS", raising=False)
    scope = _scope_with_xff(b"forged-leftmost, real-1.2.3.4")
    assert _client_ip(scope) == "real-1.2.3.4"


def test_client_ip_strips_port_suffix(monkeypatch):
    monkeypatch.delenv("PRAXYS_TRUSTED_PROXY_HOPS", raising=False)
    scope = _scope_with_xff(b"5.6.7.8:443")
    assert _client_ip(scope) == "5.6.7.8"


def test_client_ip_falls_back_to_scope_client_when_xff_absent():
    scope = {"type": "http", "headers": [], "client": ("9.9.9.9", 50000)}
    assert _client_ip(scope) == "9.9.9.9"


def test_client_ip_respects_proxy_hops(monkeypatch):
    monkeypatch.setenv("PRAXYS_TRUSTED_PROXY_HOPS", "2")
    scope = _scope_with_xff(b"orig, hop1, hop2")
    # With 2 trusted hops we walk one entry left of the rightmost.
    assert _client_ip(scope) == "hop1"


def test_client_ip_zero_hops_ignores_xff(monkeypatch):
    monkeypatch.setenv("PRAXYS_TRUSTED_PROXY_HOPS", "0")
    scope = _scope_with_xff(b"forged, also-forged")
    scope["client"] = ("9.9.9.9", 1)
    assert _client_ip(scope) == "9.9.9.9"


# ---------------------------------------------------------------------------
# Middleware integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def rl_client():
    """Tiny FastAPI app that mirrors api/main.py wiring of the limiter.

    The handlers are stubs so the test isolates the middleware's behavior
    from real auth, DB, or WeChat code paths.
    """
    app = FastAPI()
    app.add_middleware(
        AuthRateLimitMiddleware,
        limits={
            "/api/auth/login": (3, 60),
            "/api/auth/register": (2, 60),
        },
    )

    @app.post("/api/auth/login")
    async def _login_stub():
        return {"ok": True}

    @app.post("/api/auth/register")
    async def _register_stub():
        return {"ok": True}

    @app.get("/api/health")
    async def _health_stub():
        return {"ok": True}

    return TestClient(app)


def _xff(ip: str) -> dict:
    return {"X-Forwarded-For": ip}


def test_middleware_allows_under_limit(rl_client):
    for _ in range(3):
        r = rl_client.post("/api/auth/login", headers=_xff("1.1.1.1"))
        assert r.status_code == 200, r.text


def test_middleware_blocks_with_retry_after(rl_client):
    for _ in range(3):
        rl_client.post("/api/auth/login", headers=_xff("1.1.1.1"))
    blocked = rl_client.post("/api/auth/login", headers=_xff("1.1.1.1"))
    assert blocked.status_code == 429
    payload = blocked.json()
    assert payload["detail"] == "AUTH_RATE_LIMITED"
    assert payload["retry_after"] >= 1
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.headers["content-type"].startswith("application/json")


def test_middleware_separates_ips(rl_client):
    """Different X-Forwarded-For values get independent buckets."""
    for _ in range(3):
        rl_client.post("/api/auth/login", headers=_xff("1.1.1.1"))
    # 1.1.1.1 is now blocked, but 2.2.2.2 should still pass.
    assert rl_client.post("/api/auth/login", headers=_xff("1.1.1.1")).status_code == 429
    assert rl_client.post("/api/auth/login", headers=_xff("2.2.2.2")).status_code == 200


def test_middleware_separates_paths(rl_client):
    """A login bucket exhaustion does not block a register attempt."""
    for _ in range(3):
        rl_client.post("/api/auth/login", headers=_xff("1.1.1.1"))
    assert rl_client.post("/api/auth/login", headers=_xff("1.1.1.1")).status_code == 429
    # Register has its own bucket and limit (2).
    assert rl_client.post("/api/auth/register", headers=_xff("1.1.1.1")).status_code == 200


def test_middleware_ignores_unconfigured_paths(rl_client):
    """Health is not in the limits dict; never rate-limited."""
    for _ in range(20):
        r = rl_client.get("/api/health", headers=_xff("1.1.1.1"))
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Disable flag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
def test_disable_flag_recognizes_truthy_values(monkeypatch, value):
    monkeypatch.setenv("PRAXYS_AUTH_RATE_LIMIT_DISABLED", value)
    assert is_rate_limit_disabled() is True


@pytest.mark.parametrize("value", ["", "false", "0", "no"])
def test_disable_flag_recognizes_falsy_values(monkeypatch, value):
    monkeypatch.setenv("PRAXYS_AUTH_RATE_LIMIT_DISABLED", value)
    assert is_rate_limit_disabled() is False
