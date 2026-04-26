"""HTTP ETag / 304-revalidation for the dashboard endpoints (issue #147).

After L1 (#146) split ``get_dashboard_data`` into per-endpoint packs, each
pack reads a known subset of tables. L2 turns that into an HTTP-cache win:
warm visits skip the full response-body re-send when no relevant data has
changed since the client's last visit.

How it composes:

  1. Sync writers and config-mutation routes call
     ``db.cache_revision.bump_revisions`` after their commit, advancing a
     monotonic counter for each affected scope.
  2. Each route declares which scopes its packs read via
     ``ENDPOINT_SCOPES`` and depends on ``etag_guard_for_scopes(...)``.
  3. The dependency hashes the user_id + per-scope revisions into a short
     ETag. If the request's ``If-None-Match`` matches, the route returns
     304 with no body. Otherwise the route serves the full payload with
     ``ETag`` + ``Cache-Control: private, must-revalidate, max-age=0`` so
     the browser revalidates next visit (instead of serving stale).

The hash is cheap — one indexed SELECT against ``cache_revisions`` (PK is
``(user_id, scope)``), then ``blake2b(digest_size=8)``. p95 well under the
50 ms target on the existing DB size.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Iterable

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from api.auth import get_data_user_id
from db.cache_revision import get_revisions
from db.session import get_db

logger = logging.getLogger(__name__)


# Per-endpoint scope mapping. The scopes are the union of all tables the
# endpoint's packs read. Adding a new pack to an endpoint must be paired
# with adding the new scope here, otherwise stale 304s become possible.
#
# Notes on each entry:
#   /api/today       — signal pack (warnings reads cp_at_generation from
#                      training_plans meta, so plans matters even though
#                      the Today widget is "training-base agnostic"); plus
#                      today_widgets which reads activities and plan.
#   /api/training    — diagnosis (activities, splits, recovery, fitness)
#                      + fitness_pack (activities, plans, fitness).
#   /api/goal        — race pack reads thresholds (fitness), latest CP
#                      (activities + fitness), and goal config.
#   /api/history     — activities + splits only; goal/recovery edits do
#                      NOT bust the History page.
#   /api/science     — config only; sync writes do NOT bust Science.
ENDPOINT_SCOPES: dict[str, tuple[str, ...]] = {
    "today":    ("activities", "recovery", "plans", "fitness", "config"),
    "training": ("activities", "splits", "recovery", "plans", "fitness", "config"),
    "goal":     ("activities", "fitness", "config"),
    "history":  ("activities", "splits", "config"),
    "science":  ("config",),
}


CACHE_CONTROL = "private, must-revalidate, max-age=0"


def compute_etag(
    db: Session, user_id: str, scopes: Iterable[str],
    *, salt: str | None = None,
) -> str:
    """Build a short, opaque ETag from the user's revision counters.

    The ETag string is RFC-7232-quoted (``W/`` weak prefix) because the
    body bytes for the same revision tuple are NOT guaranteed to be byte-
    identical — JSON key ordering, float rounding, and ``date.today()`` in
    a few formatters can shift the body without any data change. A weak
    validator means "semantically equivalent" which is exactly what we
    want: same data → same cache entry, even if a few cosmetic bytes drift.

    ``salt`` lets a route mix request-scoped variants into the hash —
    notably ``/api/history`` whose response depends on ``limit``, ``offset``
    and ``source`` query params. Without the salt, a paginated response
    would share an ETag with a different page and the browser would replay
    a wrong cached body on the matching 304.
    """
    revs = get_revisions(db, user_id, scopes)
    parts = [user_id]
    for scope in sorted(revs):
        parts.append(f"{scope}={revs[scope]}")
    if salt:
        parts.append(f"salt={salt}")
    raw = "|".join(parts).encode("utf-8")
    digest = hashlib.blake2b(raw, digest_size=8).hexdigest()
    return f'W/"{digest}"'


class ETagGuard:
    """Per-request ETag carrier returned by ``etag_guard_for_scopes``.

    Routes call ``apply(response)`` on the success path so cache headers
    accompany the body. When the client already has the latest version
    (``is_match``), routes return ``not_modified()`` instead of re-running
    the pack functions.
    """

    __slots__ = ("etag", "_if_none_match")

    def __init__(self, etag: str, if_none_match: str | None) -> None:
        self.etag = etag
        # RFC-7232: a strong-match request header should still match a weak
        # validator on the GET response when the resource is known to be
        # safe-method idempotent. We're serving GETs only, so a literal
        # string compare against the weak ETag is correct here.
        self._if_none_match = (if_none_match or "").strip()

    @property
    def is_match(self) -> bool:
        if not self._if_none_match:
            return False
        # Browsers never send the W/ prefix back stripped, but proxies
        # occasionally normalize it; accept either form to be defensive.
        candidates = {self.etag, self.etag.removeprefix("W/")}
        # Also handle the comma-separated list form per RFC 7232 §3.2.
        for token in (t.strip() for t in self._if_none_match.split(",")):
            if token in candidates:
                return True
        return False

    def apply(self, response: Response) -> None:
        response.headers["ETag"] = self.etag
        response.headers["Cache-Control"] = CACHE_CONTROL

    def not_modified(self) -> Response:
        return Response(
            status_code=304,
            headers={"ETag": self.etag, "Cache-Control": CACHE_CONTROL},
        )


def etag_guard_for_scopes(scopes: tuple[str, ...]):
    """Build a FastAPI dependency that yields an ``ETagGuard`` per request.

    Usage in a route:

        guard = Depends(etag_guard_for_scopes(ENDPOINT_SCOPES["today"]))

        if guard.is_match:
            return guard.not_modified()
        guard.apply(response)
        # ... build payload ...

    The dependency reuses the route's ``user_id`` + ``db`` resolution path
    so there's no second auth round-trip, just one extra small SELECT.
    """

    def _dep(
        request: Request,
        user_id: str = Depends(get_data_user_id),
        db: Session = Depends(get_db),
    ) -> ETagGuard:
        etag = compute_etag(db, user_id, scopes)
        return ETagGuard(etag, request.headers.get("if-none-match"))

    return _dep
