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

    Tests that mutate ``AZURE_AI_ENDPOINT`` should call ``get_client.cache_clear()``
    afterwards because the result is memoised at process scope.
    """
    try:
        from openai import AzureOpenAI  # type: ignore[import-not-found]
        from azure.identity import (  # type: ignore[import-not-found]
            DefaultAzureCredential,
            get_bearer_token_provider,
        )
    except ImportError:
        return None
    endpoint = os.environ.get("AZURE_AI_ENDPOINT")
    if not endpoint:
        return None
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
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
) -> dict | None:
    """Strict JSON chat completion. Returns parsed dict or None on failure.

    Uses ``response_format={"type": "json_object"}`` so the model is constrained
    to emit a JSON object. On JSON decode failure or transient SDK errors,
    retries up to ``retry`` additional times then returns None.
    """
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
            content = resp.choices[0].message.content or ""
            return json.loads(content)
        except Exception as e:  # SDK + json.JSONDecodeError both surface here
            last_err = e
            if attempt < retry:
                continue
    logger.warning("chat_json failed after %d attempt(s): %s", retry + 1, last_err)
    return None
