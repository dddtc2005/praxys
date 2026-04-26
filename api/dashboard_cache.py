"""Per-section materialised dashboard cache (issue #148 / L3).

After L1 (#146) split ``get_dashboard_data`` into per-endpoint packs and
L2 (#147) layered HTTP-level 304 revalidation on top, cold reads still
pay full compute. L3 closes the gap: each endpoint's response is
materialised at the cache layer and served as a SELECT on warm reads.

Composition with L1 / L2:

  * **L2 (ETag/304)** — handles the warm-revalidation case. The browser
    keeps a copy keyed on the ETag; a matching ``If-None-Match`` returns
    304 with no body and skips both compute and serialisation.
  * **L3 (this module)** — handles the cold / 200 case. When the ETag
    miss forces a full body, L3 returns a pre-computed payload from the
    DB instead of re-running the pack.
  * **L1 (packs)** — the fallback path on a cache miss (first read after
    a write, race during a concurrent write). Still the source-of-truth
    compute; everything else here is layered as an optimisation.

Invalidation semantics — reuse L2's revision counters:

  ``source_version`` is a string like
  ``"activities=12|recovery=3|plans=1|fitness=4|config=2|d=2026-04-26"``
  built from the L2 ``cache_revisions`` rows for the scopes the section
  reads, plus a date salt for time-windowed sections (today/training/
  goal). Any sync-writer or settings-route bump advances the relevant
  scope, so the cached row's source_version no longer matches and the
  next read recomputes.

Race-correctness: the snapshot of source_version is taken BEFORE the
compute runs. If a write commits between snapshot and compute-finish,
the cache row gets written labelled with the older revisions; the very
next read sees current (advanced) revisions, mismatches, and recomputes
cleanly. The cache is **best-effort, never wrong**.

Why a single ``dashboard_cache`` table instead of one-per-section (as
issue #148 literally specifies): same correctness, half the schema.
SQLite's table-level write lock means per-section tables wouldn't even
reduce contention. Trade-off documented in the PR for #148.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Callable

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.cache_revision import get_revisions
from db.models import DashboardCache

logger = logging.getLogger(__name__)


# Per-section scope mapping. Mirrors ``api.etag.ENDPOINT_SCOPES`` for
# the same endpoints — the union of L2 scopes a section's payload depends
# on. Adding a new pack to a section means adding the new scope here AND
# to ``api.etag.ENDPOINT_SCOPES`` (otherwise stale cache hits become
# possible).
#
# Sections deliberately NOT cached at L3:
#   * ``history``: paginated by ``limit/offset/source`` query params, so
#     a single row per (user_id, section) would either thrash on every
#     page change or balloon into one row per param tuple. L2 already
#     304s warm history visits — the cold path stays at L1 compute for
#     now. Reconsider if measurements show /api/history p50 needs help.
#   * ``science``: post-L1 p50 is ~206 ms — already inside the target
#     band, and the locale-axis (``Accept-Language``) would require a
#     two-key cache. Defer until measurements justify the complexity.
SECTION_SCOPES: dict[str, tuple[str, ...]] = {
    "today":    ("activities", "recovery", "plans", "fitness", "config"),
    "training": ("activities", "splits", "recovery", "plans", "fitness", "config"),
    "goal":     ("activities", "fitness", "config"),
}


# Sections whose payload depends on ``date.today()`` (current-week load,
# race countdown, fitness-series window, "upcoming next 7 days"). The
# date is mixed into ``source_version`` so a cache row from yesterday
# cannot replay yesterday's framing this morning. Same axis as
# ``api.etag._DATE_SALTED_ENDPOINTS``.
_DATE_SALTED_SECTIONS: frozenset[str] = frozenset({"today", "training", "goal"})


# Lightweight in-process counters for hit-ratio observability. These are
# advisory only — they reset on process restart and don't try to be
# accurate across worker processes. The acceptance criterion in #148
# ("> 95 % hit ratio after 1 day") is measured from the production
# Application Insights stream which sees every worker, not from these.
class _Counters:
    """Per-process hit/miss counters keyed by section.

    Exposed via :func:`get_stats` so a debug endpoint or test can read
    them. ``reset()`` is provided for test isolation.
    """

    __slots__ = ("hits", "misses")

    def __init__(self) -> None:
        self.hits: dict[str, int] = {}
        self.misses: dict[str, int] = {}

    def record_hit(self, section: str) -> None:
        self.hits[section] = self.hits.get(section, 0) + 1

    def record_miss(self, section: str) -> None:
        self.misses[section] = self.misses.get(section, 0) + 1

    def snapshot(self) -> dict:
        sections = sorted(set(self.hits) | set(self.misses))
        out: dict[str, dict[str, int | float]] = {}
        for s in sections:
            h = self.hits.get(s, 0)
            m = self.misses.get(s, 0)
            total = h + m
            out[s] = {
                "hits": h,
                "misses": m,
                "ratio": (h / total) if total else 0.0,
            }
        return out

    def reset(self) -> None:
        self.hits.clear()
        self.misses.clear()


_COUNTERS = _Counters()


def get_stats() -> dict:
    """Snapshot of cache hits/misses by section since process start.

    Returned shape: ``{section: {hits: N, misses: M, ratio: H/(H+M)}}``.
    Use as an instrumentation surface for the #148 acceptance criterion
    and for tests that assert a hit / miss occurred.
    """
    return _COUNTERS.snapshot()


def reset_stats() -> None:
    """Test-only helper to reset the in-process counters between cases."""
    _COUNTERS.reset()


def compute_source_version(
    db: Session, user_id: str, section: str,
) -> str:
    """Build the ``source_version`` string for ``(user_id, section)``.

    Format: ``"<scope1>=<rev1>|<scope2>=<rev2>|...|d=<YYYY-MM-DD>"`` for
    date-salted sections, omitting the trailing ``d=`` part otherwise.
    Scope order is sorted alphabetically so two callers building the
    same source_version produce byte-identical strings (the cache hit
    test is a string compare).
    """
    scopes = SECTION_SCOPES[section]
    revs = get_revisions(db, user_id, scopes)
    parts = [f"{s}={revs.get(s, 0)}" for s in sorted(scopes)]
    if section in _DATE_SALTED_SECTIONS:
        parts.append(f"d={date.today().isoformat()}")
    return "|".join(parts)


def read_cache(
    db: Session, user_id: str, section: str,
) -> tuple[str, bytes] | None:
    """Return ``(source_version, payload_json)`` for a cached row, or None.

    ``payload_json`` is raw bytes — caller decodes via :func:`json.loads`
    only on a hit. Skipping the decode on a miss keeps the cold path
    cost identical to the non-cached implementation.
    """
    row = db.execute(
        select(DashboardCache.source_version, DashboardCache.payload_json)
        .where(DashboardCache.user_id == user_id)
        .where(DashboardCache.section == section)
    ).first()
    if row is None:
        return None
    return (row[0], bytes(row[1]) if row[1] is not None else b"")


def write_cache(
    db: Session, user_id: str, section: str,
    source_version: str, payload: dict,
) -> None:
    """Upsert the cache row for ``(user_id, section)``.

    Serialises ``payload`` via FastAPI's ``jsonable_encoder`` so all the
    non-JSON-native types the packs emit (``date``, ``datetime``, numpy
    floats, pandas timestamps) get coerced to plain JSON the same way
    FastAPI's response encoder would. The bytes stored on disk are then
    exactly what the response would have serialised to anyway, which
    means a cache hit can return the bytes verbatim with zero risk of
    drift between the cached and freshly-computed shape.

    Commits as a sub-transaction (savepoint) so a UNIQUE-violation
    losing race against a concurrent worker doesn't roll back the
    surrounding read transaction. On collision we fall through to an
    UPDATE — last writer wins, which is fine since both writers compute
    against the same input revisions.
    """
    body = json.dumps(jsonable_encoder(payload), separators=(",", ":")).encode("utf-8")
    existing = db.execute(
        select(DashboardCache)
        .where(DashboardCache.user_id == user_id)
        .where(DashboardCache.section == section)
    ).scalar_one_or_none()
    if existing is not None:
        existing.source_version = source_version
        existing.payload_json = body
        return
    try:
        with db.begin_nested():
            db.add(DashboardCache(
                user_id=user_id, section=section,
                source_version=source_version, payload_json=body,
            ))
    except IntegrityError:
        # Concurrent worker won the insert; fall through to UPDATE on
        # the now-existing row. The savepoint keeps the surrounding
        # transaction intact even when this sub-write rolls back.
        existing = db.execute(
            select(DashboardCache)
            .where(DashboardCache.user_id == user_id)
            .where(DashboardCache.section == section)
        ).scalar_one_or_none()
        if existing is not None:
            existing.source_version = source_version
            existing.payload_json = body


def cached_or_compute(
    db: Session, user_id: str, section: str,
    compute: Callable[[], dict],
) -> dict:
    """Return a cached payload if fresh, else compute + cache + return.

    The contract:

      1. Snapshot ``source_version`` from current revision counters.
      2. Read the cache row. If ``source_version`` matches the snapshot,
         return the deserialised payload (cache hit, sub-50 ms).
      3. Otherwise call ``compute()`` (the L1 pack-based path), write
         the result back tagged with the *snapshot* source_version, and
         return it (cache miss).

    Race correctness: tagging the write with the pre-compute snapshot
    means a write that commits mid-compute leaves the cache labelled
    with the older revisions — the next reader sees fresh revisions,
    mismatches, and recomputes. We never overwrite the cache with a
    payload labelled fresher than the data it was built from.

    On any DB error the function falls through to ``compute()`` and
    returns the fresh payload without writing the cache, so a busted
    cache table can never break a request.
    """
    try:
        snapshot_sv = compute_source_version(db, user_id, section)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "dashboard_cache: source_version lookup failed for "
            "(user=%s, section=%s): %s — falling through to compute.",
            user_id, section, exc,
        )
        return compute()

    try:
        cached = read_cache(db, user_id, section)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "dashboard_cache: read failed for (user=%s, section=%s): %s "
            "— falling through to compute.",
            user_id, section, exc,
        )
        cached = None

    if cached is not None and cached[0] == snapshot_sv:
        try:
            payload = json.loads(cached[1].decode("utf-8")) if cached[1] else {}
            _COUNTERS.record_hit(section)
            return payload
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            # Corrupt row — log and recompute. The next write will
            # overwrite it with a valid payload.
            logger.warning(
                "dashboard_cache: corrupt payload for (user=%s, section=%s): "
                "%s — recomputing.", user_id, section, exc,
            )

    payload = compute()
    _COUNTERS.record_miss(section)

    try:
        write_cache(db, user_id, section, snapshot_sv, payload)
        # Commit so a concurrent reader sees the populated row. The
        # surrounding request's get_db dependency does not commit
        # automatically for read endpoints; without this commit the
        # cache row is rolled back at the end of the request and every
        # read stays a miss.
        db.commit()
    except Exception as exc:
        logger.warning(
            "dashboard_cache: write failed for (user=%s, section=%s): %s "
            "— payload returned, cache not updated.",
            user_id, section, exc,
        )
        try:
            db.rollback()
        except Exception:  # pragma: no cover — defensive
            pass

    return payload
