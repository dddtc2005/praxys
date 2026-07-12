"""Bilingual (en + zh) LLM insight generators.

Training review and race forecast each take a training context
(:func:`api.ai.build_training_context`) plus the user's selected science
pillars and return an ``AiInsight`` upsert payload. The daily entry point
intentionally returns ``None`` so Today uses the deterministic metric instead
of free-form model advice.

Returned payload shape (matches ``db.models.AiInsight`` columns):

.. code-block:: python

    {
        "headline": str,                # English
        "summary": str,                 # English
        "findings": [{"type": "positive|warning|neutral", "text": str}, ...],
        "recommendations": [str, ...],
        "translations": {"zh": {<same shape>}},
        "meta_extra": {"model": str, "pillars": dict},
    }

Categorical fields (finding ``type`` keys, severity enums) are STABLE English
strings and never translated — the frontend resolves them via
``web/src/lib/display-labels.ts``.

Prompts cite the user's selected pillar names by name (e.g. "per Plews HRV
trend", "per Banister TSB") so the generated prose is grounded in the user's
chosen science theory rather than generic coaching boilerplate.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from analysis.insight_hash import build_training_review_inputs
from api import llm
from api.coach import COACH_PERSONA

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public generator functions
# ---------------------------------------------------------------------------


def generate_daily_brief(
    context: dict, science_pillars: dict[str, str]
) -> dict | None:
    """Use the deterministic Today signal instead of free-form model advice.

    A model can produce fluent prose that contradicts the canonical action even
    when prompted or asked for a matching decision enum. Until daily coaching is
    represented by a fully server-owned structured action, the pure metric is the
    sole source of Today advice. Training review and race forecast remain model-
    generated because they do not compete with a same-day safety verdict.
    """
    _ = context, science_pillars
    logger.debug("Insight daily_brief skipped: deterministic_today_signal")
    return None


def generate_training_review(
    context: dict, science_pillars: dict[str, str]
) -> dict | None:
    """Generate multi-week training diagnosis + suggestions narrative."""
    return _generate(
        context=context,
        science_pillars=science_pillars,
        insight_type="training_review",
        system_prompt=_training_review_system(context),
        user_payload=build_training_review_inputs(context),
    )


def generate_race_forecast(
    context: dict, science_pillars: dict[str, str]
) -> dict | None:
    """Generate race feasibility narrative + CP milestone interpretation."""
    return _generate(
        context=context,
        science_pillars=science_pillars,
        insight_type="race_forecast",
        system_prompt=_race_forecast_system(context),
        user_payload=_race_forecast_inputs(context),
    )


# ---------------------------------------------------------------------------
# Shared generator core
# ---------------------------------------------------------------------------


def _generate(
    *,
    context: dict,
    science_pillars: dict[str, str],
    insight_type: str,
    system_prompt: str,
    user_payload: dict,
) -> dict | None:
    client = llm.get_client()
    if client is None:
        logger.debug("Insight %s skipped: LLM client unavailable", insight_type)
        return None

    user_msg = json.dumps(user_payload, default=str)
    raw = llm.chat_json(
        client,
        system=system_prompt,
        user=user_msg,
        model=llm.INSIGHT_MODEL,
        insight_type=insight_type,
    )
    if not raw:
        # chat_json already logged the underlying error; no need to repeat.
        return None
    ok, reason = _validate_bilingual_shape(raw)
    if not ok:
        _log_rejection(insight_type, reason, raw)
        return None

    en = raw["en"]
    zh = raw["zh"]
    return {
        "headline": en["headline"],
        "summary": en["summary"],
        "findings": en["findings"],
        "recommendations": en["recommendations"],
        "translations": {"zh": zh},
        "meta_extra": {
            "model": llm.INSIGHT_MODEL,
            "pillars": dict(science_pillars or {}),
        },
    }


# ---------------------------------------------------------------------------
# System prompts (one per insight type)
# ---------------------------------------------------------------------------


_BILINGUAL_RULES = """
Return STRICT JSON in this exact shape:
{
  "en": {
    "headline": "<short English headline, ≤80 chars>",
    "summary":  "<2-3 sentence English summary>",
    "findings": [{"type": "positive|warning|neutral", "text": "<English>"}, ...],
    "recommendations": ["<short English imperative>", ...]
  },
  "zh": {
    "headline": "<Simplified Chinese headline, ≤40 characters>",
    "summary":  "<2-3 sentence Simplified Chinese summary>",
    "findings": [{"type": "positive|warning|neutral", "text": "<Simplified Chinese>"}, ...],
    "recommendations": ["<short Simplified Chinese imperative>", ...]
  }
}

Hard rules:

- 'type' values are STABLE English enum keys: positive, warning, neutral. NEVER translate them.
- 'findings' arrays in en and zh MUST have the same length and the same 'type' value at each index.
- 'recommendations' arrays in en and zh MUST have the same length. Length is 0-3 entries each. Fewer is better than padded — return 0 if there's nothing concrete to say, 1-3 if there is. Do not invent advice to hit a quota.
- Do NOT translate technical acronyms: HRV, TSB, CTL, ATL, CP, VO2max, RPE.
- Science-pillar / theory NAMES stay in English in BOTH languages: write "Banister PMC", "Plews HRV-guided", "Critical Power Model", "Coggan 5-zone", "Seiler Polarized" verbatim — never paraphrase them as "阈值功率模型" / "Banister 表现管理模型" etc. The product links these names to the Science page; paraphrases break the link.
- In Chinese: use 您 (formal you), 阈值功率 (not 临界功率) ONLY when referring to the metric (the user's CP value), 同步历史数据 (not 回填), 基准 (not 基线).
- Plain text only — no markdown, no bullet points, no headings.

Context-awareness rules:
- If a race is ≤ 14 days away AND load (ATL, weekly volume) is dropping, recognize this as a planned taper. Do NOT flag the drop as a regression; affirm the taper and focus advice on freshness, sleep, race execution.
- If the athlete is in race mode (race_date set, days_left ≤ 28), keep advice consistent with closing the gap to the goal — don't suggest brand-new training blocks.
"""


def _frame_intro(context: dict) -> str:
    """Persona prefix + the user's selected science pillars, named.

    The persona (``COACH_PERSONA``) supplies the voice; this function tacks
    on the pillar enumeration so the model knows which framework names to
    cite. Keeping pillar enumeration separate from the persona means the
    persona stays stable across surfaces while pillar names are
    per-request.
    """
    science = context.get("science") or {}
    load = (science.get("load") or {}).get("name") or "Banister PMC"
    # Default matches data/science/recovery/hrv_based.yaml's name so the
    # fallback prompt phrase is already in the linkifier map.
    recovery = (science.get("recovery") or {}).get("name") or "HRV-Based Recovery"
    prediction = (science.get("prediction") or {}).get("name") or "Critical Power"
    zones = (science.get("zones") or {}).get("name") or "Five-zone"
    return (
        f"{COACH_PERSONA}\n\n"
        "The athlete's chosen scientific framework:\n"
        f"- Load model: {load}\n"
        f"- Recovery model: {recovery}\n"
        f"- Race-prediction model: {prediction}\n"
        f"- Zone framework: {zones}\n"
    )


def _training_review_system(context: dict) -> str:
    return (
        _frame_intro(context)
        + "\n\nYou will receive 6-8 weeks of training sessions (date, distance, "
        "RSS, duration), weekly aggregates, and a deterministic diagnosis whose "
        "intensity fields come only from timestamped samples or activity splits. "
        "Produce a diagnosis: headline names the dominant pattern, summary explains "
        "the trajectory, and findings flag specific issues (volume trend, interval "
        "intensity, distribution vs the zone framework's target distribution, "
        "consistency, threshold trend). Distribution and target fields are omitted "
        "when evidence is incomplete; never infer a distribution when they are absent. "
        "Never infer interval intensity or zone distribution from activity "
        "averages in any training base.\n\n"
        "Recommendations rules — next-cycle structural, consistent with the goal:\n"
        "- Concrete next-cycle actions ('add 1x supra-CP session/week', "
        "  'cut volume 15% next 2 weeks').\n"
        "- Stay consistent with the goal mode: if a race is set, don't propose "
        "  brand-new training blocks that wouldn't finish before race day.\n"
        "- 0-3 entries. Pick highest-impact only.\n"
        + _BILINGUAL_RULES
    )


def _race_forecast_system(context: dict) -> str:
    return (
        _frame_intro(context)
        + "\n\nYou will receive the athlete's current threshold power, CP trend, "
        "predicted race time (from the prediction model), goal race date and "
        "target time. Produce a feasibility narrative: headline says whether "
        "the goal is on track / close / unlikely, summary explains the gap and "
        "trend, findings flag the key constraints (threshold gap, time runway, "
        "weekly improvement needed). When no race date is set, frame the "
        "narrative around CP milestones instead.\n\n"
        "Recommendations rules — gap-closing, scoped to this page:\n"
        "- Specifically about closing the gap to the race target OR hitting the "
        "  next CP milestone: a concrete CP target, a weekly load shift, race "
        "  pacing, race-week prep.\n"
        "- Do NOT recommend abstract training blocks that don't tie back to the "
        "  goal numbers in front of the athlete.\n"
        "- 0-3 entries. If the trend already projects on-target, 0-1 is fine.\n"
        + _BILINGUAL_RULES
    )


# ---------------------------------------------------------------------------
# Per-type input projections (the user message)
# ---------------------------------------------------------------------------


def _goal_context(context: dict) -> dict:
    """Goal + race-countdown summary surfaced to every prompt.

    The Coach persona uses this to recognize taper windows, race-week
    behavior, and goal-mode framing in training-review and race-forecast
    prompts.
    """
    cf = context.get("current_fitness") or {}
    ap = context.get("athlete_profile") or {}
    return {
        "goal": ap.get("goal"),
        "race_countdown": cf.get("race_countdown"),
    }



def _race_forecast_inputs(context: dict) -> dict:
    cf = context.get("current_fitness") or {}
    ap = context.get("athlete_profile") or {}
    return {
        "threshold": ap.get("threshold"),
        "cp_trend": cf.get("cp_trend"),
        "predicted_time_sec": cf.get("predicted_time_sec"),
        "goal": ap.get("goal"),
        "race_countdown": cf.get("race_countdown"),
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_bilingual_shape(raw: Any) -> tuple[bool, str]:
    """Validate ``raw`` against the strict en+zh schema.

    Returns ``(ok, reason)``. ``reason`` is a short tag suitable for logging
    (e.g. ``"missing_zh"``, ``"finding_type_mismatch"``) so a debug log can
    pinpoint which check failed without dumping the full payload.
    """
    if not isinstance(raw, dict):
        return False, "not_dict"
    for lang in ("en", "zh"):
        block = raw.get(lang)
        if not isinstance(block, dict):
            return False, f"missing_{lang}"
        if not isinstance(block.get("headline"), str) or not block["headline"]:
            return False, f"{lang}_headline_invalid"
        if not isinstance(block.get("summary"), str) or not block["summary"]:
            return False, f"{lang}_summary_invalid"
        findings = block.get("findings")
        if not isinstance(findings, list):
            return False, f"{lang}_findings_not_list"
        for f in findings:
            if not isinstance(f, dict):
                return False, f"{lang}_finding_not_dict"
            if f.get("type") not in {"positive", "warning", "neutral"}:
                return False, f"{lang}_finding_type_unknown"
            if not isinstance(f.get("text"), str) or not f["text"]:
                return False, f"{lang}_finding_text_invalid"
        recs = block.get("recommendations")
        if not isinstance(recs, list) or not all(isinstance(r, str) for r in recs):
            return False, f"{lang}_recommendations_invalid"
        if len(recs) > 3:
            # Enforce the "≤ 3 recommendations" prompt rule. The LLM
            # otherwise drifts to 5-8 entries, which dilutes signal.
            return False, f"{lang}_too_many_recommendations"
    # findings/recommendations must align across languages
    if len(raw["en"]["findings"]) != len(raw["zh"]["findings"]):
        return False, "findings_length_mismatch"
    if len(raw["en"]["recommendations"]) != len(raw["zh"]["recommendations"]):
        return False, "recommendations_length_mismatch"
    for en_f, zh_f in zip(raw["en"]["findings"], raw["zh"]["findings"]):
        if en_f["type"] != zh_f["type"]:
            return False, "finding_type_mismatch"
    return True, "ok"


def _log_rejection(insight_type: str, reason: str, raw: Any) -> None:
    """Log a rejected insight payload with a stable reason code."""
    preview = json.dumps(raw, ensure_ascii=False)[:300] if raw else None
    logger.warning(
        "Insight %s rejected: reason=%s model=%s raw_preview=%r",
        insight_type, reason, llm.INSIGHT_MODEL, preview,
    )
