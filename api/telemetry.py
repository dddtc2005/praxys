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
