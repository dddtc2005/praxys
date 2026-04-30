"""Shared Azure OpenAI client + JSON-mode chat helper.

Auth uses DefaultAzureCredential, picking up `az login` locally or workload
identity / OIDC in cloud. No API key path. When `AZURE_AI_ENDPOINT` is unset
or the optional `openai` / `azure-identity` SDKs are missing, `get_client()`
returns None — callers fall back to rule-based prose rather than raising.

Two model deployment names are exposed:
- ``INSIGHT_MODEL`` (env ``PRAXYS_INSIGHT_MODEL``): reasoning model used by the
  post-sync insight generator. Default ``gpt-5.4``.
- ``TRANSLATE_MODEL`` (env ``TRANSLATE_MODEL``): smaller model used by the
  i18n translation script. Default ``gpt-5.4-mini``.

This module is the canonical place for Azure OpenAI auth scaffolding;
``scripts/translate_missing.py`` delegates here.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

INSIGHT_MODEL = os.environ.get("PRAXYS_INSIGHT_MODEL", "gpt-5.4")
TRANSLATE_MODEL = os.environ.get("TRANSLATE_MODEL", "gpt-5.4-mini")
API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")


@lru_cache(maxsize=1)
def get_client() -> Any | None:
    """Return an AzureOpenAI client or None when unavailable.

    Returns None (rather than raising) when:
    - The optional ``openai`` or ``azure-identity`` SDKs are not installed.
    - The ``AZURE_AI_ENDPOINT`` env var is unset.

    Both fallback paths log once at module-call time so operators see the
    AI-tier state in deploy logs (otherwise a missing SDK or unset endpoint
    silently disables AI insights for the lifetime of the process).

    Tests that mutate ``AZURE_AI_ENDPOINT`` should call ``get_client.cache_clear()``
    afterwards because the result is memoised at process scope.
    """
    try:
        from openai import AzureOpenAI  # type: ignore[import-not-found]
        from azure.identity import (  # type: ignore[import-not-found]
            DefaultAzureCredential,
            get_bearer_token_provider,
        )
    except ImportError as e:
        logger.warning(
            "Azure OpenAI SDK missing — AI insights disabled, "
            "rule-based fallback active (%s)", e
        )
        return None
    endpoint = os.environ.get("AZURE_AI_ENDPOINT")
    if not endpoint:
        logger.info(
            "AZURE_AI_ENDPOINT unset — AI insights disabled, "
            "rule-based fallback active"
        )
        return None
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    logger.info(
        "Azure OpenAI client initialised: endpoint=%s api_version=%s "
        "insight_model=%s translate_model=%s",
        endpoint, API_VERSION, INSIGHT_MODEL, TRANSLATE_MODEL,
    )
    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_version=API_VERSION,
        azure_ad_token_provider=token_provider,
    )


def chat_json(
    client: Any,
    *,
    system: str,
    user: str,
    model: str,
    max_completion_tokens: int = 4096,
    temperature: float = 0.3,
    retry: int = 1,
    insight_type: str | None = None,
) -> dict | None:
    """Strict JSON chat completion. Returns parsed dict or None on failure.

    Uses ``response_format={"type": "json_object"}`` so the model is
    constrained to emit a JSON object.

    Failure handling distinguishes operator-actionable errors (auth misconfig,
    bad request — logged at ERROR, no retry) from transient errors (rate
    limit, transient API error, JSON decode — logged at WARNING and retried).
    Returns None in either case so callers fall back to rule-based prose;
    distinct log levels let alerting route operator-actionable failures
    differently from noisy transient ones.

    ``insight_type`` is forwarded to telemetry — when set, per-call token
    usage and operator-actionable errors are dimensioned by it so daily
    spend and Auth-error spikes are queryable per Coach surface in App
    Insights. Defaults to ``"unknown"`` so non-Coach callers still emit
    metrics, just without per-surface breakdown.
    """
    from api import telemetry

    itype = insight_type or "unknown"

    # SDK exception classes — imported here so this module stays importable
    # without the openai SDK (chat_json is unreachable in that case because
    # ``get_client`` returns None first). When the SDK is missing we still
    # need real BaseException subclasses in the ``except`` clauses below;
    # falling back to ``()`` made Python reject the tuple at runtime
    # ("catching classes that do not inherit from BaseException").
    try:
        from openai import (  # type: ignore[import-not-found]
            APIError,
            AuthenticationError,
            BadRequestError,
            RateLimitError,
        )
    except ImportError:  # pragma: no cover — get_client returns None first
        class _SdkUnavailable(BaseException):
            """Sentinel that never matches — keeps except clauses syntactically valid."""

        AuthenticationError = BadRequestError = RateLimitError = APIError = _SdkUnavailable  # type: ignore[assignment]

    last_err: Exception | None = None
    for attempt in range(retry + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                max_completion_tokens=max_completion_tokens,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            # ``resp.usage`` is None on streaming responses; we don't stream
            # but guarding keeps telemetry robust if a future caller flips it.
            usage = getattr(resp, "usage", None)
            if usage is not None:
                telemetry.record_coach_tokens(
                    insight_type=itype,
                    model=model,
                    prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
            content = resp.choices[0].message.content or ""
            return json.loads(content)
        except AuthenticationError:
            logger.error(
                "chat_json: Azure auth failed — DefaultAzureCredential or "
                "endpoint misconfigured", exc_info=True,
            )
            telemetry.record_coach_error(error_class="Auth")
            return None  # operator-actionable, no retry
        except BadRequestError as e:
            logger.error("chat_json: bad request (no retry): %s", e)
            telemetry.record_coach_error(error_class="BadRequest")
            return None  # malformed prompt — bug in caller
        except (RateLimitError, APIError, json.JSONDecodeError) as e:
            last_err = e  # transient — fall through to retry
        except Exception as e:  # pragma: no cover — unexpected
            last_err = e
        if attempt < retry:
            continue
    logger.warning(
        "chat_json failed after %d attempt(s): %s",
        retry + 1, last_err,
    )
    return None
