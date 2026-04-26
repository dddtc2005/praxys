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
    miss forces a full body, L3 returns a pre-computed JSON-encoded
    payload from the DB instead of re-running the pack. The route
    wraps those bytes in ``Response(media_type="application/json")``
    so FastAPI serves them verbatim — no re-encoding pass.
  * **L1 (packs)** — the fallback path on a cache miss (first read after
    a write, race during a concurrent write). Still the source-of-truth
    compute; everything else here is layered as an optimisation.

Invalidation semantics — reuse L2's revision counters:

  ``source_version`` is a pipe-separated string of the L2
  ``cache_revisions`` rows for the scopes the section reads, with
  scopes sorted alphabetically so two callers produce byte-identical
  strings, plus a date salt for time-windowed sections (today/training/
  goal). Example for ``today`` on 2026-04-26 with all-zero revisions:
  ``"activities=0|config=0|fitness=0|plans=0|recovery=0|d=2026-04-26"``.
  Any sync-writer or settings-route bump advances the relevant scope,
  so the cached row's source_version no longer matches and the next
  read recomputes.

Race-correctness: the snapshot of source_version is taken BEFORE the
compute runs. If a write commits between snapshot and compute-finish,
the cache row gets written labelled with the older revisions; the very
next read sees current (advanced) revisions, mismatches, and recomputes
cleanly. The cache is **best-effort, never wrong**.

Session isolation: the cache write happens on a **dedicated** session
(``_write_cache_isolated``), not the request session. That keeps two
footguns out of the request-scoped ``db``:

  1. ``SessionLocal`` defaults to ``expire_on_commit=True``, which would
     expire any ORM proxy a future pack returned in its payload after
     our cache-write commit.
  2. A cache-write rollback would otherwise discard anything else the
     route had staged on the session.

Why a single ``dashboard_cache`` table instead of one-per-section (as
issue #148 literally specifies): same correctness, half the schema.
SQLite's database-level write lock means per-section tables wouldn't
even reduce contention. Trade-off documented in the PR for #148.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Callable, Literal, TypedDict

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.exc import DatabaseError, IntegrityError, OperationalError
from sqlalchemy.orm import Session

from db.cache_revision import get_revisions
from db.models import DashboardCache

logger = logging.getLogger(__name__)


# Cached endpoint sections. ``Section`` is the closed enum at the API
# boundary — a route passing a string outside this set is a programmer
# error and ``compute_source_version`` / ``write_cache`` raise ``KeyError``
# loudly rather than silently writing an orphan row.
Section = Literal["today", "training", "goal"]


# Per-section scope mapping. Mirrors ``api.etag.ENDPOINT_SCOPES`` for
# the same endpoints — the union of L2 scopes a section's payload depends
# on. Adding a new pack to a section means adding the new scope here AND
# to ``api.etag.ENDPOINT_SCOPES`` (otherwise stale cache hits become
# possible). The alignment is enforced by
# ``test_section_scopes_align_with_etag_endpoint_scopes``.
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
SECTION_SCOPES: dict[Section, tuple[str, ...]] = {
    "today":    ("activities", "recovery", "plans", "fitness", "config"),
    "training": ("activities", "splits", "recovery", "plans", "fitness", "config"),
    "goal":     ("activities", "fitness", "config"),
}


# Sections whose payload depends on ``date.today()`` (current-week load,
# race countdown, fitness-series window, "upcoming next 7 days"). The
# date is mixed into ``source_version`` so a cache row from yesterday
# cannot replay yesterday's framing this morning. Same axis as
# ``api.etag._DATE_SALTED_ENDPOINTS`` — alignment enforced by the same
# scope-alignment test.
_DATE_SALTED_SECTIONS: frozenset[Section] = frozenset({"today", "training", "goal"})


# Errors we expect to recover from inside the cache layer. Anything else
# (KeyError on a typo'd section, TypeError on a bad input shape) is a
# programmer error and should propagate so it shows up in tests rather
# than as a silent miss-forever loop in production.
_RECOVERABLE_DB_ERRORS = (OperationalError, DatabaseError, IntegrityError)


class SectionStats(TypedDict):
    """Per-section observation snapshot returned by :func:`get_stats`."""

    hits: int
    misses: int
    ratio: float


class _Counters:
    """In-process hit/miss/failure counters for the cache layer.

    Advisory only — counters reset on process restart and aren't shared
    across worker processes. The acceptance criterion ">95 % hit ratio
    after 1 day" is measured from the production Application Insights
    stream which sees every worker; these counters are for tests and
    for a future debug endpoint.
    """

    __slots__ = ("hits", "misses", "write_failures", "corrupt_rows")

    def __init__(self) -> None:
        self.hits: dict[str, int] = {}
        self.misses: dict[str, int] = {}
        self.write_failures: dict[str, int] = {}
        self.corrupt_rows: dict[str, int] = {}

    def record_hit(self, section: str) -> None:
        self.hits[section] = self.hits.get(section, 0) + 1

    def record_miss(self, section: str) -> None:
        self.misses[section] = self.misses.get(section, 0) + 1

    def record_write_failure(self, section: str) -> None:
        self.write_failures[section] = self.write_failures.get(section, 0) + 1

    def record_corrupt_row(self, section: str) -> None:
        self.corrupt_rows[section] = self.corrupt_rows.get(section, 0) + 1

    def snapshot(self) -> dict[str, SectionStats]:
        sections = sorted(set(self.hits) | set(self.misses))
        out: dict[str, SectionStats] = {}
        for s in sections:
            h = self.hits.get(s, 0)
            m = self.misses.get(s, 0)
            total = h + m
            out[s] = SectionStats(
                hits=h, misses=m, ratio=(h / total) if total else 0.0,
            )
        return out

    def reset(self) -> None:
        self.hits.clear()
        self.misses.clear()
        self.write_failures.clear()
        self.corrupt_rows.clear()


_COUNTERS = _Counters()


def get_stats() -> dict[str, SectionStats]:
    """Snapshot of cache hits/misses by section since process start.

    Use as an instrumentation surface for the #148 acceptance criterion
    and for tests that assert a hit / miss occurred. Write-failure and
    corrupt-row counters live on the underlying ``_Counters`` and can
    be added to the public surface if the production stream needs them.
    """
    return _COUNTERS.snapshot()


def reset_stats() -> None:
    """Test-only helper to reset the in-process counters between cases."""
    _COUNTERS.reset()


def compute_source_version(
    db: Session, user_id: str, section: Section,
) -> str:
    """Build the ``source_version`` string for ``(user_id, section)``.

    Format: ``"<scope1>=<rev1>|<scope2>=<rev2>|...|d=<YYYY-MM-DD>"`` for
    date-salted sections, omitting the trailing ``d=`` part otherwise.
    Scope order is sorted alphabetically so two callers building the
    same source_version produce byte-identical strings (the cache hit
    test is a string compare).

    Raises :class:`KeyError` when ``section`` is not a known cache
    section — surfaces a typo loudly rather than as a permanent miss.
    """
    if section not in SECTION_SCOPES:
        raise KeyError(
            f"unknown cache section {section!r}; "
            f"expected one of {tuple(SECTION_SCOPES)}"
        )
    scopes = SECTION_SCOPES[section]
    revs = get_revisions(db, user_id, scopes)
    parts = [f"{s}={revs.get(s, 0)}" for s in sorted(scopes)]
    if section in _DATE_SALTED_SECTIONS:
        parts.append(f"d={date.today().isoformat()}")
    return "|".join(parts)


def _looks_like_json(body: bytes) -> bool:
    """Cheap structural sanity check on cached bytes.

    Returns True iff ``body`` starts and ends with matched JSON
    object/array delimiters. The bytes were valid JSON when written
    (``json.dumps`` round-trip in :func:`_encode`); this catches
    storage-side bit-rot or a future writer that bypasses ``_encode``
    and writes garbage. Cheaper than a full ``json.loads`` parse on
    every cache hit, which would defeat the verbatim-bytes return.
    """
    if not body:
        return False
    first = body[0]
    last = body[-1]
    # ord('{') = 123, ord('}') = 125, ord('[') = 91, ord(']') = 93
    return (first == 123 and last == 125) or (first == 91 and last == 93)


def _encode(payload: dict) -> bytes:
    """Serialise a payload exactly the way FastAPI would.

    ``jsonable_encoder`` handles the type coercion (``date``,
    ``datetime``, numpy floats, pandas timestamps); ``json.dumps`` with
    ``separators=(",", ":")`` matches FastAPI's default ``JSONResponse``
    output. The cached bytes are therefore byte-identical to a freshly-
    served response, which is what makes the verbatim-byte cache-hit
    path correct.
    """
    return json.dumps(
        jsonable_encoder(payload), separators=(",", ":"),
    ).encode("utf-8")


def read_cache(
    db: Session, user_id: str, section: Section,
) -> tuple[str, bytes] | None:
    """Return ``(source_version, payload_bytes)`` for a cached row, or None.

    ``payload_bytes`` is the JSON-encoded response body verbatim — the
    caller returns it via ``Response(content=..., media_type="application/json")``
    on a hit, skipping FastAPI's response-encoding pass.
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
    db: Session, user_id: str, section: Section,
    source_version: str, body: bytes,
) -> None:
    """Upsert the cache row for ``(user_id, section)`` with pre-encoded bytes.

    ``body`` MUST be the JSON-encoded response payload — caller is
    responsible for producing it via :func:`_encode` (or any equivalent
    that matches FastAPI's default JSON serialisation). Storing pre-
    encoded bytes is what lets cache hits return the body verbatim from
    the route.

    Wraps the INSERT in a savepoint so a UNIQUE-violation losing race
    against a concurrent worker doesn't roll back the surrounding
    transaction; on collision we fall through to UPDATE — last writer
    wins, which is fine since both writers compute against the same
    input revisions.

    Raises :class:`KeyError` when ``section`` is not a known cache
    section. The CHECK constraint on
    ``DashboardCache.__table_args__`` is the storage-layer belt; this
    Python-side check is the suspenders.
    """
    if section not in SECTION_SCOPES:
        raise KeyError(
            f"unknown cache section {section!r}; "
            f"expected one of {tuple(SECTION_SCOPES)}"
        )
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
        # Concurrent worker won the insert. Logged at INFO (not WARNING)
        # because this is the expected race-loss path, not an error.
        logger.info(
            "dashboard_cache: insert collision for (user=%s, section=%s) "
            "— recovering via UPDATE",
            user_id, section,
        )
        existing = db.execute(
            select(DashboardCache)
            .where(DashboardCache.user_id == user_id)
            .where(DashboardCache.section == section)
        ).scalar_one_or_none()
        if existing is not None:
            existing.source_version = source_version
            existing.payload_json = body


def _delete_cache_row(user_id: str, section: Section) -> None:
    """Delete one cache row on a dedicated session.

    Used to remove a corrupt payload before recomputing — a follow-up
    write may also fail (disk full, lock timeout) but at least the
    corrupt row is gone, so the next read becomes a clean cold miss
    instead of replaying the corrupt-detection branch indefinitely.

    Runs on a fresh ``SessionLocal`` so a failure here cannot poison
    the request session.
    """
    from db.session import SessionLocal
    if SessionLocal is None:
        return
    cache_db = SessionLocal()
    try:
        cache_db.execute(
            delete(DashboardCache)
            .where(DashboardCache.user_id == user_id)
            .where(DashboardCache.section == section)
        )
        cache_db.commit()
    except _RECOVERABLE_DB_ERRORS as exc:
        logger.warning(
            "dashboard_cache: delete failed for (user=%s, section=%s, "
            "error_id=L3_CACHE_DELETE_FAIL, exc_class=%s): %s",
            user_id, section, type(exc).__name__, exc,
        )
        cache_db.rollback()
    finally:
        cache_db.close()


def _write_cache_isolated(
    user_id: str, section: Section, source_version: str, body: bytes,
) -> None:
    """Write to the cache on a dedicated session.

    Isolating the cache write from the request session avoids two traps:

      1. ``SessionLocal``'s default ``expire_on_commit=True`` would
         expire every ORM object the request session has loaded — fine
         today because the L1 packs return plain dicts, but a future
         pack that returns a row with a lazy-loaded relationship would
         break silently after our commit.
      2. A cache-write failure (disk full, lock timeout) calling
         ``db.rollback()`` on the request session would discard
         anything else the route had staged. Today's three callers are
         pure read endpoints so there's nothing to discard, but the
         decoupling means a future caller that also stages writes
         can't accidentally lose data through this layer.

    Recovers from expected DB-error classes (``OperationalError``,
    ``DatabaseError``, ``IntegrityError``); a programmer error
    (``KeyError``, ``TypeError``) propagates so it shows up in tests.
    """
    from db.session import SessionLocal
    if SessionLocal is None:
        # Tests that haven't called init_db (rare); the cache layer
        # must never break a request, so silently skip the write.
        return
    cache_db = SessionLocal()
    try:
        write_cache(cache_db, user_id, section, source_version, body)
        cache_db.commit()
    except _RECOVERABLE_DB_ERRORS as exc:
        _COUNTERS.record_write_failure(section)
        logger.warning(
            "dashboard_cache: write failed for (user=%s, section=%s, "
            "error_id=L3_CACHE_WRITE_FAIL, exc_class=%s): %s",
            user_id, section, type(exc).__name__, exc,
        )
        cache_db.rollback()
    finally:
        cache_db.close()


def cached_or_compute(
    db: Session, user_id: str, section: Section,
    compute: Callable[[], dict],
) -> bytes:
    """Return the JSON-encoded response body, served from cache or freshly built.

    Returns ``bytes`` (not a dict) so the route can wrap them in a
    ``Response(media_type="application/json")`` and skip FastAPI's
    response-encoding pass. The bytes on a cache hit are byte-identical
    to what FastAPI would have produced from ``compute()`` — both paths
    serialise via ``jsonable_encoder`` + ``json.dumps(separators=(",", ":"))``.

    Race correctness: the ``source_version`` snapshot is taken **before**
    ``compute()`` runs (line marked below) and the cache row is written
    tagged with that snapshot. A write that commits mid-compute leaves
    the cache labelled with the older revisions; the next reader sees
    fresh revisions, mismatches, and recomputes. The cache is best-
    effort, never wrong.

    Reliability: any expected DB-class failure inside the cache layer
    falls through to ``compute()`` and returns the freshly-encoded
    body. The cache layer must never break a request.
    """
    # MUST happen before compute(). Race-correctness invariant — see
    # the module docstring's "Race-correctness" paragraph. Moving this
    # after compute() would silently poison the cache forever whenever
    # a write commits during compute.
    try:
        snapshot_sv = compute_source_version(db, user_id, section)
    except _RECOVERABLE_DB_ERRORS as exc:
        logger.warning(
            "dashboard_cache: source_version lookup failed for "
            "(user=%s, section=%s, error_id=L3_CACHE_SV_FAIL, "
            "exc_class=%s): %s",
            user_id, section, type(exc).__name__, exc,
        )
        return _encode(compute())

    try:
        cached = read_cache(db, user_id, section)
    except _RECOVERABLE_DB_ERRORS as exc:
        logger.warning(
            "dashboard_cache: read failed for (user=%s, section=%s, "
            "error_id=L3_CACHE_READ_FAIL, exc_class=%s): %s",
            user_id, section, type(exc).__name__, exc,
        )
        cached = None

    if cached is not None and cached[0] == snapshot_sv:
        body = cached[1]
        if _looks_like_json(body):
            _COUNTERS.record_hit(section)
            return body
        _COUNTERS.record_corrupt_row(section)
        logger.warning(
            "dashboard_cache: corrupt payload detected for (user=%s, "
            "section=%s, error_id=L3_CACHE_CORRUPT, len=%d) — deleting "
            "and recomputing.",
            user_id, section, len(body),
        )
        _delete_cache_row(user_id, section)

    body = _encode(compute())
    _COUNTERS.record_miss(section)
    _write_cache_isolated(user_id, section, snapshot_sv, body)
    return body
