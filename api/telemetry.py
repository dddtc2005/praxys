"""Application Insights telemetry helpers — lazy, no-op when unconfigured.

Three Coach-tier signals power the operator dashboard for issue #221:

- ``record_coach_tokens(insight_type, model, prompt_tokens, completion_tokens)``
  emits an OpenTelemetry counter ``praxys.coach_tokens`` so daily token spend
  by ``insight_type`` is queryable in ``customMetrics``.
- ``record_coach_run(insight_type, status, user_id)`` emits a counter
  ``praxys.coach_run`` (or a customEvent when the events extension is
  installed) so cache hit rate is derivable from ``status`` over time. The
  raw user id is hashed before emission — telemetry is not a PII surface.
- ``record_coach_error(error_class)`` emits ``praxys.coach_error`` so a
  sustained spike in operator-actionable error classes (Auth, BadRequest)
  pages oncall.

Why a counter for coach_run / coach_error instead of a customEvent: the
``azure-monitor-events-extension`` package is the canonical customEvent
emitter, but it is not pulled in by ``azure-monitor-opentelemetry`` — and
the issue forbids new dependencies. We therefore opportunistically use it
when present and fall back to a counter (which lands in customMetrics)
otherwise. The KQL queries documented on the issue translate directly:
``count(status==X)`` becomes ``sum(value) where status==X`` because each
record contributes value=1.

Lazy / no-op contract: every helper short-circuits silently when the
``APPLICATIONINSIGHTS_CONNECTION_STRING`` env var is unset (same signal
``api/main.py`` uses to skip ``configure_azure_monitor``) or when the OTel
meter API isn't importable — sync hooks must never break because telemetry
is misconfigured.
"""
from __future__ import annotations

import hashlib
import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


def _telemetry_enabled() -> bool:
    """True iff App Insights is wired in this process.

    Mirrors the gate ``api/main.py`` uses to decide whether to call
    ``configure_azure_monitor()``. Cheap to call on every record — env
    lookup is dict-fast.
    """
    return bool(os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"))


@lru_cache(maxsize=1)
def _meter() -> Any | None:
    """Return the OTel meter, or None when unavailable.

    Memoised because ``get_meter`` is cheap but creating the meter every
    call would still add overhead inside the hot path of ``chat_json``.
    Cleared by tests via ``_meter.cache_clear()``.
    """
    if not _telemetry_enabled():
        return None
    try:
        from opentelemetry import metrics  # type: ignore[import-not-found]
    except ImportError:
        # OTel SDK absent — same fallback contract as get_client() in api/llm.py.
        return None
    return metrics.get_meter("praxys.coach")


@lru_cache(maxsize=8)
def _counter(name: str, description: str) -> Any | None:
    """Return a memoised OTel ``Counter`` for ``name`` or None when telemetry is off.

    Counters are cumulative and dimensioned via attributes at record time —
    one Counter instance per metric name handles the full attribute fan-out.
    """
    meter = _meter()
    if meter is None:
        return None
    return meter.create_counter(name=name, description=description)


@lru_cache(maxsize=1)
def _track_event() -> Any | None:
    """Return ``track_event`` from the events extension if installed, else None.

    The extension ships as ``azure-monitor-events-extension`` and is *not*
    a transitive dep of ``azure-monitor-opentelemetry``. Importing
    optimistically lets us upgrade to true customEvents the moment an
    operator opts in (e.g. by ``pip install``-ing it on the Azure App
    Service) without changing call sites.
    """
    if not _telemetry_enabled():
        return None
    try:
        from azure.monitor.events.extension import track_event  # type: ignore[import-not-found]
    except ImportError:
        return None
    return track_event


def hash_user_id(user_id: str) -> str:
    """Stable, non-reversible hash for telemetry dimensioning.

    SHA-256 truncated to 16 hex chars (64 bits) — wide enough that operators
    can group "events from the same user" without colliding across the
    plausible user-base size, narrow enough that a short hash is readable in
    the App Insights UI. Telemetry is not a PII surface; the raw email or
    UUID never leaves the process.
    """
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]


def record_coach_tokens(
    *,
    insight_type: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Record token usage from a successful Azure OpenAI completion.

    Emits one increment per token-type so a single KQL ``sum(value)`` call
    reproduces total spend; the ``token_type`` dimension lets operators
    split prompt vs. completion when looking for prompt-bloat regressions.
    """
    counter = _counter("praxys.coach_tokens", "Azure OpenAI tokens consumed by Coach")
    if counter is None:
        return
    base = {"insight_type": insight_type, "model": model}
    try:
        if prompt_tokens:
            counter.add(prompt_tokens, {**base, "token_type": "prompt"})
        if completion_tokens:
            counter.add(completion_tokens, {**base, "token_type": "completion"})
        total = (prompt_tokens or 0) + (completion_tokens or 0)
        if total:
            counter.add(total, {**base, "token_type": "total"})
    except Exception:
        # Telemetry must never break the caller. Log once and swallow.
        logger.debug("record_coach_tokens failed", exc_info=True)


def record_coach_run(*, insight_type: str, status: str, user_id: str) -> None:
    """Record one runner outcome for a single ``insight_type``.

    Status is one of ``generated``, ``hash_match``, ``cap_reached``,
    ``generator_returned_none`` — the runner already produces these strings.
    Cache hit rate = ``count(status='hash_match') / count(*)``.

    Prefers the customEvents path when available; falls back to a counter
    otherwise (see module docstring for why).
    """
    try:
        user_id_hash = hash_user_id(user_id)
    except Exception:
        # The runner always passes a real str user_id today; this guard is
        # purely defensive so a future caller passing None can't take down
        # the post-sync hook with an AttributeError. Telemetry must be
        # invisible when it can't do its job.
        logger.debug("record_coach_run: bad user_id, skipping", exc_info=True)
        return
    attrs = {
        "insight_type": insight_type,
        "status": status,
        "user_id_hash": user_id_hash,
    }
    track = _track_event()
    if track is not None:
        try:
            track("praxys.coach_run", attrs)
            return
        except Exception:
            logger.debug("track_event(coach_run) failed; falling back to counter", exc_info=True)
    counter = _counter("praxys.coach_run", "Coach insight-runner outcomes")
    if counter is None:
        return
    try:
        counter.add(1, attrs)
    except Exception:
        logger.debug("record_coach_run counter failed", exc_info=True)


def record_coach_error(*, error_class: str) -> None:
    """Record an operator-actionable Coach error (Auth, BadRequest).

    Transient errors (rate limit, JSON decode) are deliberately excluded —
    they are noise on this signal. Log spikes here gate the oncall page.
    """
    attrs = {"error_class": error_class}
    track = _track_event()
    if track is not None:
        try:
            track("praxys.coach_error", attrs)
            return
        except Exception:
            logger.debug("track_event(coach_error) failed; falling back to counter", exc_info=True)
    counter = _counter("praxys.coach_error", "Coach operator-actionable errors")
    if counter is None:
        return
    try:
        counter.add(1, attrs)
    except Exception:
        logger.debug("record_coach_error counter failed", exc_info=True)


def record_feedback(*, kind: str, status: str) -> None:
    """Record one user-feedback submission outcome.

    ``kind`` is one of ``bug`` / ``feature`` / ``other``; ``status`` is the
    post-triage row status (``new``, ``triaged``, ``issue_created``,
    ``failed``). Lets operators graph feedback volume by type and the
    auto-publish success rate without the raw report ever entering telemetry
    — only these two low-cardinality dimensions are emitted, never the message.

    Prefers the customEvents path when available; falls back to a counter
    (lands in customMetrics) otherwise — same contract as record_coach_run.
    """
    attrs = {"kind": kind, "status": status}
    track = _track_event()
    if track is not None:
        try:
            track("praxys.feedback", attrs)
            return
        except Exception:
            logger.debug("track_event(feedback) failed; falling back to counter", exc_info=True)
    counter = _counter("praxys.feedback", "User-submitted feedback submissions")
    if counter is None:
        return
    try:
        counter.add(1, attrs)
    except Exception:
        logger.debug("record_feedback counter failed", exc_info=True)

def record_db_health(*, status: str, backend: str) -> None:
    """Record a database health signal (issues #350 / #351).

    ``status`` is one of ``integrity_failed`` / ``check_error`` (from the
    startup ``PRAGMA quick_check`` / ``SELECT 1`` in ``db/session.py``) or
    ``readiness_failed`` (from the ``/api/health/ready`` probe). ``backend``
    is ``sqlite`` or ``postgresql``. Emitting a low-cardinality counter lets
    an Azure Monitor alert page oncall when a corrupt / unreachable database
    would otherwise be invisible to the liveness-only ``/api/health`` check.

    Prefers the customEvents path when available; falls back to a counter
    (lands in customMetrics) otherwise — same contract as record_feedback.
    """
    attrs = {"status": status, "backend": backend}
    track = _track_event()
    if track is not None:
        try:
            track("praxys.db_health", attrs)
            return
        except Exception:
            logger.debug("track_event(db_health) failed; falling back to counter", exc_info=True)
    counter = _counter("praxys.db_health", "Database health-check failures")
    if counter is None:
        return
    try:
        counter.add(1, attrs)
    except Exception:
        logger.debug("record_db_health counter failed", exc_info=True)


# ---------------------------------------------------------------------------
# Sync / connection observability (per-platform failure aggregation)
# ---------------------------------------------------------------------------
#
# Sync + connect outcomes are emitted as low-cardinality counters so operators
# can aggregate failures per platform (and, for Garmin, per MFA / non-MFA flow)
# and tell a *systemic* break (a spike across many distinct users -- a platform
# outage, a Cloudflare block, or a library regression like the #369 widget-token
# rejection) apart from an *individual* problem (one user's wrong password). The
# user id is hashed, so a distinct-user count (dcount(user_id_hash)) is the
# systemic-vs-individual discriminator without telemetry ever seeing a raw id.

# Failure classes a *single* user causes on their own -- a spike here is not
# operator-actionable (wrong credentials / mistyped code), so alerts exclude them.
USER_FAULT_FAILURE_CLASSES = frozenset({"bad_credentials", "mfa_code_rejected"})

# Failure classes where a spike across many users signals a platform-side or
# our-side breakage. These gate the systemic-failure alert.
SYSTEMIC_FAILURE_CLASSES = frozenset({
    "rate_limited", "captcha_required", "access_blocked", "token_rejected",
    "mfa_unattended", "platform_error", "network_error", "unknown",
})


def classify_platform_error(exc: BaseException) -> str:
    """Map a sync/connect exception to a low-cardinality telemetry failure class.

    Heuristic and best-effort: matches on exception *type name* + message
    substrings so it stays dependency-free and works across every platform
    provider. Distinct from ``db.sync_scheduler.classify_sync_failure`` (which
    decides DB status + retry backoff) -- this decides the telemetry dimension.
    Ordering matters: the systemic 401 (``token_rejected``, upstream #369) is
    matched before the generic bad-credentials 401.
    """
    name = type(exc).__name__
    msg = str(exc) or ""
    low = msg.lower()

    if name == "GarminConnectTooManyRequestsError" or "429" in msg or "too many" in low or "rate limit" in low:
        return "rate_limited"
    if "captcha" in low:
        return "captcha_required"
    if "403" in msg or "cloudflare" in low or "bot challenge" in low:
        return "access_blocked"
    # #369: the API tier rejects the token -- socialProfile 401 "Token is not active".
    if "token is not active" in low or "social profile" in low or "socialprofile" in low:
        return "token_rejected"
    # Background sync hit MFA with no interactive prompt (or our re-auth rewrap).
    if "prompt_mfa" in low or "mfa required" in low or "requires re-authentication" in low:
        return "mfa_unattended"
    if "verification code" in low or "mfa code" in low or "invalid mfa" in low:
        return "mfa_code_rejected"
    if (
        name == "GarminConnectAuthenticationError"
        or "invalid username or password" in low
        or "could not verify" in low
        or "authentication failed" in low
        or "401" in msg
    ):
        return "bad_credentials"
    if any(code in msg for code in ("500", "502", "503", "504")) or "server error" in low:
        return "platform_error"
    if (
        name in ("ConnectionError", "Timeout", "ReadTimeout", "ConnectTimeout", "GarminConnectConnectionError")
        or "timed out" in low
        or "connection refused" in low
        or "connection error" in low
    ):
        return "network_error"
    return "unknown"


def record_sync(
    *, platform: str, outcome: str, failure_class: str, trigger: str, user_id: str
) -> None:
    """Record one sync attempt outcome.

    ``outcome`` is ``success`` | ``failure``; ``failure_class`` is ``none`` on
    success else a :func:`classify_platform_error` value; ``trigger`` is
    ``scheduled`` | ``manual``. The ``user_id_hash`` dimension lets an alert
    count *distinct affected users* to separate a systemic break from one
    unhappy account. Prefers customEvents; falls back to a counter.
    """
    try:
        user_id_hash = hash_user_id(user_id)
    except Exception:
        logger.debug("record_sync: bad user_id, skipping", exc_info=True)
        return
    attrs = {
        "platform": platform,
        "outcome": outcome,
        "failure_class": failure_class,
        "trigger": trigger,
        "user_id_hash": user_id_hash,
    }
    track = _track_event()
    if track is not None:
        try:
            track("praxys.sync", attrs)
            return
        except Exception:
            logger.debug("track_event(sync) failed; falling back to counter", exc_info=True)
    counter = _counter("praxys.sync", "Platform sync attempt outcomes")
    if counter is None:
        return
    try:
        counter.add(1, attrs)
    except Exception:
        logger.debug("record_sync counter failed", exc_info=True)


def record_connection(
    *, platform: str, flow: str, stage: str, outcome: str,
    failure_class: str, user_id: str, region: str = "n/a",
) -> None:
    """Record one account-connection attempt outcome.

    ``flow`` is ``mfa`` | ``non_mfa`` | ``n/a`` (the Garmin MFA vs non-MFA
    sub-category); ``stage`` is ``credentials`` | ``mfa_verify``; ``outcome`` is
    ``connected`` | ``mfa_required`` | ``error``; ``region`` is ``cn`` |
    ``international`` | ``n/a``. Same systemic-vs-individual discriminator as
    :func:`record_sync` via ``user_id_hash``.
    """
    try:
        user_id_hash = hash_user_id(user_id)
    except Exception:
        logger.debug("record_connection: bad user_id, skipping", exc_info=True)
        return
    attrs = {
        "platform": platform,
        "flow": flow,
        "stage": stage,
        "outcome": outcome,
        "failure_class": failure_class,
        "region": region,
        "user_id_hash": user_id_hash,
    }
    track = _track_event()
    if track is not None:
        try:
            track("praxys.connection", attrs)
            return
        except Exception:
            logger.debug("track_event(connection) failed; falling back to counter", exc_info=True)
    counter = _counter("praxys.connection", "Account connection attempt outcomes")
    if counter is None:
        return
    try:
        counter.add(1, attrs)
    except Exception:
        logger.debug("record_connection counter failed", exc_info=True)
