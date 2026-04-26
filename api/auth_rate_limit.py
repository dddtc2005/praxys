"""Per-IP sliding-window rate limiter for the authentication surface.

Why this module exists
----------------------
Praxys is open-source on GitHub. Anyone can read api/routes/register.py,
api/routes/wechat.py, and the FastAPI-Users login route to learn the
exact request shapes. This middleware caps per-IP attempts on the auth
surface so credential-stuffing and invitation-code-bruteforcing become
infeasible, even though the endpoint contracts are public.

Endpoints covered
-----------------
- /api/auth/login                       (FastAPI-Users JWT login)
- /api/auth/register                    (custom invite-aware register)
- /api/auth/wechat/login
- /api/auth/wechat/register
- /api/auth/wechat/link-with-password

Implementation notes
--------------------
- In-memory sliding window per (path, client_ip), backed by a ``deque``
  of timestamps. ``OrderedDict`` of buckets is LRU-bounded so a malicious
  enumerator cannot OOM the worker.
- On Azure App Service with N gunicorn workers the effective ceiling is
  N × the configured value — acceptable as defense against unsophisticated
  brute force, not a sophisticated DoS. Move to a Redis-backed limiter
  if cross-worker enforcement matters.
- Client-IP resolution trusts the *rightmost* X-Forwarded-For entry. The
  leftmost is client-controlled (forgeable); the rightmost is what the
  immediate upstream proxy observed and is therefore safe on a single-hop
  Azure App Service deployment. ``PRAXYS_TRUSTED_PROXY_HOPS`` lets an
  operator walk further left when the proxy chain is longer (e.g.
  Front Door → App Service).
- Disable entirely with ``PRAXYS_AUTH_RATE_LIMIT_DISABLED=true`` for
  tests / local dev.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict, deque
from typing import Mapping

logger = logging.getLogger(__name__)

# (path, (max_requests, window_seconds)). The limits are tuned for a
# small user base: tight enough that brute force is infeasible, loose
# enough that a real user accidentally hammering "login" doesn't get
# locked out for the day.
DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    "/api/auth/login":                       (10, 5 * 60),
    "/api/auth/register":                    (5, 60 * 60),
    "/api/auth/wechat/login":                (30, 5 * 60),
    "/api/auth/wechat/link-with-password":   (10, 15 * 60),
    "/api/auth/wechat/register":             (5, 60 * 60),
}

_DEFAULT_MAX_TRACKED_CLIENTS = 10_000


class _SlidingWindow:
    """Per-key bounded deque of recent request timestamps."""

    __slots__ = ("limit", "window_secs", "_buckets", "_lock", "_max_clients")

    def __init__(self, limit: int, window_secs: int, max_clients: int):
        self.limit = limit
        self.window_secs = window_secs
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_clients = max_clients

    def check_and_record(self, key: str) -> tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)``.

        ``retry_after_seconds`` is 0 when the call is allowed, and the
        smallest integer wait for the oldest in-window entry to expire
        when blocked.
        """
        now = time.monotonic()
        cutoff = now - self.window_secs
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = deque()
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                oldest = bucket[0]
                retry = int(oldest + self.window_secs - now) + 1
                return False, max(1, retry)
            bucket.append(now)
            while len(self._buckets) > self._max_clients:
                self._buckets.popitem(last=False)
        return True, 0


def _client_ip(scope) -> str:
    """Best-effort client IP for rate-limit bucketing.

    Trusts the rightmost X-Forwarded-For entry — that's what the immediate
    upstream proxy observed and is the safe choice on Azure App Service
    (single proxy hop). Leftmost entries are client-controlled and
    forgeable. Tune ``PRAXYS_TRUSTED_PROXY_HOPS`` to walk further left when
    the proxy chain is fixed and longer.
    """
    try:
        hops = max(0, int(os.environ.get("PRAXYS_TRUSTED_PROXY_HOPS", "1")))
    except ValueError:
        hops = 1

    if hops > 0:
        for name, value in scope.get("headers", ()):
            if name == b"x-forwarded-for":
                entries = [
                    e.strip().split(":")[0]
                    for e in value.decode("latin-1").split(",")
                    if e.strip()
                ]
                if entries:
                    idx = max(0, len(entries) - hops)
                    return entries[idx] or "unknown"
                break

    client = scope.get("client")
    return client[0] if client else "unknown"


async def _send_429(send, retry_after: int) -> None:
    body = (
        b'{"detail":"AUTH_RATE_LIMITED","retry_after":'
        + str(retry_after).encode()
        + b"}"
    )
    headers = [
        (b"content-type", b"application/json"),
        (b"retry-after", str(retry_after).encode()),
        (b"content-length", str(len(body)).encode()),
    ]
    await send({"type": "http.response.start", "status": 429, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class AuthRateLimitMiddleware:
    """ASGI middleware enforcing per-path per-IP auth rate limits.

    Only HTTP requests whose path matches a configured limit are
    inspected; all other traffic short-circuits with no overhead beyond a
    dict lookup.
    """

    def __init__(
        self,
        app,
        limits: Mapping[str, tuple[int, int]] | None = None,
        max_tracked_clients: int = _DEFAULT_MAX_TRACKED_CLIENTS,
    ):
        self.app = app
        self._windows = {
            path: _SlidingWindow(limit, window, max_tracked_clients)
            for path, (limit, window) in (limits or DEFAULT_LIMITS).items()
        }

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        window = self._windows.get(scope.get("path", ""))
        if window is None:
            await self.app(scope, receive, send)
            return
        ip = _client_ip(scope)
        key = f"{scope['path']}|{ip}"
        allowed, retry_after = window.check_and_record(key)
        if allowed:
            await self.app(scope, receive, send)
            return
        logger.warning(
            "auth rate limit hit ip=%s path=%s retry_after=%ds",
            ip, scope["path"], retry_after,
        )
        await _send_429(send, retry_after)


def is_rate_limit_disabled() -> bool:
    """True when ``PRAXYS_AUTH_RATE_LIMIT_DISABLED`` opts out (tests, dev)."""
    return os.environ.get("PRAXYS_AUTH_RATE_LIMIT_DISABLED", "").lower() in {
        "1", "true", "yes", "on",
    }
