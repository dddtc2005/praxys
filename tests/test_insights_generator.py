"""Tests for ``api.insights_generator`` — the bilingual LLM insight functions.

The tests monkey-patch ``api.llm.get_client`` to inject a fake Azure OpenAI
client whose ``chat.completions.create`` returns a canned response. We never
hit a real model.
"""
from __future__ import annotations

import json
import types
from typing import Any

import pytest

from api import insights_generator, llm


PILLARS = {
    "load": "banister_pmc",
    "recovery": "hrv_based",
    "prediction": "critical_power",
    "zones": "five_zone",
}


def _fake_context() -> dict:
    return {
        "athlete_profile": {
            "training_base": "power",
            "threshold": 280.0,
            "goal": {"distance": "marathon", "race_date": "2026-09-01",
                     "target_time_sec": 10800, "mode": "race_date"},
        },
        "current_fitness": {
            "ctl": 50.0,
            "atl": 45.0,
            "tsb": 5.0,
            "cp_trend": {"direction": "up", "slope_per_month": 1.5,
                         "current": 280.0},
            "predicted_time_sec": 11000,
            "race_countdown": {"days_left": 124, "status": "on_track"},
        },
        "recent_training": {
            "weekly_summary": [
                {"week": "2026-W17", "volume_km": 40.0, "load": 250.0,
                 "sessions": 5},
            ],
            "sessions": [
                {"date": "2026-04-21", "distance_km": 8.0, "rss": 60.0,
                 "avg_power": 200, "duration_min": 45},
            ],
        },
        "recovery_state": {
            "hrv_ms": 60.0, "hrv_trend_pct": 2.0, "sleep_score": 80,
            "readiness": "fresh",
        },
        "current_plan": [
            {"workout_type": "easy", "planned_duration_min": 45,
             "planned_distance_km": 8.0, "target_power_min": 180,
             "target_power_max": 210},
        ],
        "science": {
            "load": {"id": "banister_pmc", "name": "Banister PMC", "params": {}},
            "recovery": {"id": "hrv_based", "name": "Plews HRV-guided"},
            "prediction": {"id": "critical_power", "name": "Critical Power"},
            "zones": {"id": "five_zone", "name": "Coggan 5-zone",
                      "zone_names": ["Z1", "Z2", "Z3", "Z4", "Z5"],
                      "target_distribution": [0.2, 0.6, 0.1, 0.05, 0.05]},
        },
    }


def _valid_bilingual_response() -> dict:
    return {
        "en": {
            "headline": "Recovered — follow today's easy run",
            "summary": "HRV is 2% above baseline and sleep was solid; per Plews "
                       "HRV trend you're recovered. TSB +5 supports the planned easy session.",
            "findings": [
                {"type": "positive", "text": "HRV trending up per Plews HRV"},
                {"type": "neutral", "text": "TSB +5 — fresh"},
            ],
            "recommendations": ["Run the planned 45-min easy", "Hydrate well"],
        },
        "zh": {
            "headline": "您已恢复 — 按计划进行轻松跑",
            "summary": "HRV 高于基准 2%，睡眠良好；按 Plews HRV 趋势您已恢复。"
                       "TSB +5 支持计划中的轻松课。",
            "findings": [
                {"type": "positive", "text": "HRV 按 Plews HRV 趋势上升"},
                {"type": "neutral", "text": "TSB +5 — 状态新鲜"},
            ],
            "recommendations": ["按计划完成 45 分钟轻松跑", "注意补水"],
        },
    }


# ---------------------------------------------------------------------------
# Fake OpenAI client
# ---------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, response_content: str) -> None:
        self.last_call: dict | None = None
        self._content = response_content

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.last_call = kwargs
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, response_content: str) -> None:
        self.completions = _FakeCompletions(response_content)


class _FakeClient:
    def __init__(self, response_content: str) -> None:
        self.chat = _FakeChat(response_content)


# ---------------------------------------------------------------------------
# Tests: client unavailable → None
# ---------------------------------------------------------------------------


def test_returns_none_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(llm, "get_client", lambda: None)
    assert insights_generator.generate_daily_brief(_fake_context(), PILLARS) is None
    assert insights_generator.generate_training_review(_fake_context(), PILLARS) is None
    assert insights_generator.generate_race_forecast(_fake_context(), PILLARS) is None


# ---------------------------------------------------------------------------
# Tests: shape validation
# ---------------------------------------------------------------------------


def test_daily_brief_returns_payload_with_translations(monkeypatch):
    fake = _FakeClient(json.dumps(_valid_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    payload = insights_generator.generate_daily_brief(_fake_context(), PILLARS)

    assert payload is not None
    assert payload["headline"] == "Recovered — follow today's easy run"
    assert "Plews" in payload["summary"]
    assert payload["findings"][0]["type"] == "positive"
    assert "translations" in payload and "zh" in payload["translations"]
    assert payload["translations"]["zh"]["headline"].startswith("您已恢复")
    assert payload["meta_extra"]["pillars"] == PILLARS
    assert payload["meta_extra"]["model"] == llm.INSIGHT_MODEL


def test_training_review_returns_payload(monkeypatch):
    fake = _FakeClient(json.dumps(_valid_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    payload = insights_generator.generate_training_review(_fake_context(), PILLARS)

    assert payload is not None
    # User-message JSON should include the zone target distribution from the
    # selected zone framework (verifies pillar grounding).
    user_msg = json.loads(fake.chat.completions.last_call["messages"][1]["content"])
    assert user_msg["zone_target_distribution"] == [0.2, 0.6, 0.1, 0.05, 0.05]


def test_race_forecast_returns_payload(monkeypatch):
    fake = _FakeClient(json.dumps(_valid_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    payload = insights_generator.generate_race_forecast(_fake_context(), PILLARS)

    assert payload is not None
    user_msg = json.loads(fake.chat.completions.last_call["messages"][1]["content"])
    assert user_msg["goal"]["target_time_sec"] == 10800


# ---------------------------------------------------------------------------
# Tests: prompt cites pillar names
# ---------------------------------------------------------------------------


def test_system_prompt_cites_pillar_names_by_name(monkeypatch):
    fake = _FakeClient(json.dumps(_valid_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    insights_generator.generate_daily_brief(_fake_context(), PILLARS)

    system_prompt = fake.chat.completions.last_call["messages"][0]["content"]
    assert "Banister PMC" in system_prompt
    assert "Plews HRV-guided" in system_prompt
    assert "Coggan 5-zone" in system_prompt


def test_system_prompt_carries_coach_persona(monkeypatch):
    """The Coach persona is the single source of voice — every system
    prompt must inherit from it."""
    fake = _FakeClient(json.dumps(_valid_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    insights_generator.generate_daily_brief(_fake_context(), PILLARS)
    insights_generator.generate_training_review(_fake_context(), PILLARS)
    insights_generator.generate_race_forecast(_fake_context(), PILLARS)

    # All three system prompts include the same Praxys Coach persona —
    # checking the last call is sufficient because the persona prefix is
    # invariant across types.
    last_system_prompt = fake.chat.completions.last_call["messages"][0]["content"]
    assert "Praxys Coach" in last_system_prompt


def test_daily_brief_user_payload_includes_goal_context(monkeypatch):
    """Daily brief must see goal + race countdown so it can recognize taper
    weeks and frame advice consistently with the athlete's race plan."""
    fake = _FakeClient(json.dumps(_valid_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    insights_generator.generate_daily_brief(_fake_context(), PILLARS)
    user_msg = json.loads(fake.chat.completions.last_call["messages"][1]["content"])
    assert user_msg.get("goal", {}).get("race_date") == "2026-09-01"
    assert user_msg.get("race_countdown", {}).get("days_left") == 124


def test_daily_brief_planned_workout_reads_planned_today_only(monkeypatch):
    """Daily brief's planned_workout MUST be today's plan entry, not the
    next future workout. Falling back to current_plan[0] silently surfaces
    the next workout when today is rest, and the LLM then advises on a
    session the athlete isn't supposed to do."""
    fake = _FakeClient(json.dumps(_valid_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    ctx = _fake_context()
    # Today is rest (no planned_today); current_plan still carries a
    # future workout the planner intends for some other day.
    ctx["planned_today"] = None
    ctx["current_plan"] = [
        {"workout_type": "threshold", "planned_duration_min": 90,
         "target_power_min": 240, "target_power_max": 280},
    ]
    insights_generator.generate_daily_brief(ctx, PILLARS)
    user_msg = json.loads(fake.chat.completions.last_call["messages"][1]["content"])
    assert user_msg["planned_workout"] is None, (
        "planned_workout must be None when today is unscheduled — "
        "do not surface the next future workout as today's session"
    )

    # When planned_today is set, that exact entry is what the LLM sees.
    ctx2 = _fake_context()
    ctx2["planned_today"] = {
        "workout_type": "easy", "planned_duration_min": 30,
        "target_power_min": 180, "target_power_max": 200,
    }
    ctx2["current_plan"] = [
        ctx2["planned_today"],
        {"workout_type": "threshold", "planned_duration_min": 90},
    ]
    insights_generator.generate_daily_brief(ctx2, PILLARS)
    user_msg2 = json.loads(fake.chat.completions.last_call["messages"][1]["content"])
    assert user_msg2["planned_workout"]["workout_type"] == "easy"
    assert user_msg2["planned_workout"]["planned_duration_min"] == 30


def test_training_review_user_payload_includes_goal_context(monkeypatch):
    """Training review needs goal context to avoid recommending a brand-new
    block when the athlete is closing in on a target race."""
    fake = _FakeClient(json.dumps(_valid_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    insights_generator.generate_training_review(_fake_context(), PILLARS)
    user_msg = json.loads(fake.chat.completions.last_call["messages"][1]["content"])
    assert user_msg.get("goal", {}).get("target_time_sec") == 10800
    assert user_msg.get("race_countdown") is not None


# ---------------------------------------------------------------------------
# Tests: invalid response shape → None
# ---------------------------------------------------------------------------


def test_returns_none_on_invalid_json(monkeypatch):
    fake = _FakeClient("this is not json")
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    assert insights_generator.generate_daily_brief(_fake_context(), PILLARS) is None


def test_returns_none_when_zh_missing(monkeypatch):
    bad = {"en": _valid_bilingual_response()["en"]}  # no zh block
    fake = _FakeClient(json.dumps(bad))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    assert insights_generator.generate_daily_brief(_fake_context(), PILLARS) is None


def test_returns_none_when_finding_type_unknown(monkeypatch):
    bad = _valid_bilingual_response()
    bad["en"]["findings"][0]["type"] = "info"  # not in {positive, warning, neutral}
    fake = _FakeClient(json.dumps(bad))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    assert insights_generator.generate_daily_brief(_fake_context(), PILLARS) is None


def test_returns_none_when_findings_misaligned(monkeypatch):
    bad = _valid_bilingual_response()
    bad["zh"]["findings"].pop()  # zh has fewer findings than en
    fake = _FakeClient(json.dumps(bad))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    assert insights_generator.generate_daily_brief(_fake_context(), PILLARS) is None


def test_returns_none_when_finding_types_disagree(monkeypatch):
    bad = _valid_bilingual_response()
    bad["zh"]["findings"][0]["type"] = "warning"  # en says "positive"
    fake = _FakeClient(json.dumps(bad))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    assert insights_generator.generate_daily_brief(_fake_context(), PILLARS) is None


def test_returns_none_when_headline_empty(monkeypatch):
    bad = _valid_bilingual_response()
    bad["en"]["headline"] = ""
    fake = _FakeClient(json.dumps(bad))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    assert insights_generator.generate_daily_brief(_fake_context(), PILLARS) is None


def test_returns_none_when_recommendations_exceed_three(monkeypatch):
    """Hard cap at 3 recommendations — pad-padding diluted the signal."""
    bad = _valid_bilingual_response()
    bad["en"]["recommendations"] = ["a", "b", "c", "d"]
    bad["zh"]["recommendations"] = ["甲", "乙", "丙", "丁"]
    fake = _FakeClient(json.dumps(bad))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    assert insights_generator.generate_daily_brief(_fake_context(), PILLARS) is None


def test_returns_none_when_recommendations_contain_non_strings(monkeypatch):
    bad = _valid_bilingual_response()
    bad["zh"]["recommendations"] = ["ok", 42]  # 42 is not a string
    fake = _FakeClient(json.dumps(bad))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    assert insights_generator.generate_daily_brief(_fake_context(), PILLARS) is None


def test_validator_returns_specific_reason_for_each_failure_class():
    """Spot-check that the validator emits a useful tag per failure class —
    the rejection log relies on this to be debuggable."""
    from api.insights_generator import _validate_bilingual_shape

    valid = _valid_bilingual_response()
    ok, reason = _validate_bilingual_shape(valid)
    assert ok and reason == "ok"

    no_zh = {"en": valid["en"]}
    assert _validate_bilingual_shape(no_zh) == (False, "missing_zh")

    misaligned = {**valid}
    misaligned["zh"] = {**valid["zh"], "findings": valid["zh"]["findings"][:0]}
    assert _validate_bilingual_shape(misaligned)[1] == "findings_length_mismatch"
