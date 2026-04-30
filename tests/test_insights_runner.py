"""Tests for ``api.insights_runner.run_insights_for_user``.

Uses an in-memory SQLite DB so each test gets a clean schema. The Azure
OpenAI client is monkey-patched to return canned bilingual responses (or
None when we're testing the fallback path).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import AiInsight, Base
from api import insights_runner, llm


PILLARS = {
    "load": "banister_pmc",
    "recovery": "hrv_based",
    "prediction": "critical_power",
    "zones": "five_zone",
}

USER_ID = "11111111-1111-1111-1111-111111111111"


def _bilingual_response(headline: str = "Test headline") -> dict:
    return {
        "en": {
            "headline": headline,
            "summary": "English summary.",
            "findings": [{"type": "positive", "text": "All good"}],
            "recommendations": ["Run easy"],
        },
        "zh": {
            "headline": "测试标题",
            "summary": "中文摘要。",
            "findings": [{"type": "positive", "text": "状态良好"}],
            "recommendations": ["轻松跑"],
        },
    }


# ---------------------------------------------------------------------------
# Fake Azure OpenAI client
# ---------------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, content): self.content = content


class _FakeChoice:
    def __init__(self, content): self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content): self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content):
        self._content = content
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        return _FakeResponse(self._content)


class _FakeClient:
    def __init__(self, content):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content)})()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    """In-memory SQLite session with all tables created."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def stub_context(monkeypatch):
    """Stub build_training_context to avoid hitting get_dashboard_data."""
    fake_ctx = {
        "athlete_profile": {"goal": {"distance": "marathon"}},
        "current_fitness": {
            "ctl": 50.0, "atl": 45.0, "tsb": 5.0,
            "cp_trend": {"current": 280.0, "direction": "up", "slope_per_month": 1.5},
            "predicted_time_sec": 11000,
        },
        "recent_training": {
            "weekly_summary": [],
            "sessions": [],
        },
        "recovery_state": {"hrv_ms": 60.0, "readiness": "fresh"},
        "current_plan": [],
        "science": {
            "load": {"id": "banister_pmc", "name": "Banister PMC"},
            "recovery": {"id": "hrv_based", "name": "Plews HRV-guided"},
            "prediction": {"id": "critical_power", "name": "Critical Power"},
            "zones": {"id": "five_zone", "name": "Coggan 5-zone",
                      "target_distribution": [0.2, 0.6, 0.1, 0.05, 0.05]},
        },
    }
    # Patch the source module — insights_runner imports lazily inside the
    # function body, so we need to patch the canonical attribute that gets
    # bound on import.
    monkeypatch.setattr("api.ai.build_training_context", lambda **kw: fake_ctx)
    return fake_ctx


@pytest.fixture
def stub_pillars(monkeypatch):
    """Stub load_config_from_db to return our test pillars."""
    class _StubConfig:
        science = PILLARS

    monkeypatch.setattr(
        "analysis.config.load_config_from_db",
        lambda user_id, db: _StubConfig(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_skips_when_no_new_rows(db_session, stub_context, stub_pillars):
    """Empty counts → short-circuit, no LLM calls, no DB writes."""
    result = insights_runner.run_insights_for_user(USER_ID, db_session, {}, _session=db_session)
    assert result == {"skipped": "no_new_rows"}
    assert db_session.query(AiInsight).count() == 0


def test_generates_all_three_when_hash_differs(db_session, stub_context, stub_pillars, monkeypatch):
    fake = _FakeClient(json.dumps(_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    result = insights_runner.run_insights_for_user(USER_ID, db_session, {"activities": 5}, _session=db_session)

    assert result == {
        "daily_brief": "generated",
        "training_review": "generated",
        "race_forecast": "generated",
    }
    rows = db_session.query(AiInsight).filter(AiInsight.user_id == USER_ID).all()
    assert len(rows) == 3
    for row in rows:
        assert row.translations.get("zh", {}).get("headline") == "测试标题"
        assert "dataset_hash" in row.meta


def test_skips_when_hash_matches(db_session, stub_context, stub_pillars, monkeypatch):
    fake = _FakeClient(json.dumps(_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    # First sync: generates all three.
    insights_runner.run_insights_for_user(USER_ID, db_session, {"activities": 5}, _session=db_session)
    initial_calls = fake.chat.completions.call_count
    assert initial_calls == 3

    # Second sync with same context: hash matches, no new LLM calls.
    result = insights_runner.run_insights_for_user(USER_ID, db_session, {"activities": 5}, _session=db_session)
    assert all(v == "hash_match" for v in result.values())
    assert fake.chat.completions.call_count == initial_calls  # unchanged


def test_pillar_swap_invalidates_hash_and_regenerates(db_session, stub_context, monkeypatch):
    fake = _FakeClient(json.dumps(_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    class _Cfg:
        def __init__(self, science): self.science = science

    # First run with original pillars.
    monkeypatch.setattr("analysis.config.load_config_from_db",
                         lambda u, d: _Cfg(PILLARS))
    insights_runner.run_insights_for_user(USER_ID, db_session, {"activities": 1}, _session=db_session)

    # Swap load theory; same context but pillar set differs → hash changes.
    swapped = {**PILLARS, "load": "seiler_polarized"}
    monkeypatch.setattr("analysis.config.load_config_from_db",
                         lambda u, d: _Cfg(swapped))
    result = insights_runner.run_insights_for_user(USER_ID, db_session, {"activities": 1}, _session=db_session)

    assert all(v == "generated" for v in result.values()), result


def test_cap_reached_skips_remaining_types(db_session, stub_context, stub_pillars, monkeypatch):
    fake = _FakeClient(json.dumps(_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    monkeypatch.setenv("PRAXYS_INSIGHT_DAILY_CAP", "2")

    result = insights_runner.run_insights_for_user(USER_ID, db_session, {"activities": 1}, _session=db_session)

    # The runner generates in GENERATORS_ORDER and increments used_today only
    # after a successful generate, so with cap=2 the first two types
    # generate and the third (race_forecast) hits the cap.
    assert result["daily_brief"] == "generated"
    assert result["training_review"] == "generated"
    assert result["race_forecast"] == "cap_reached"


def test_cap_reached_short_circuits_entire_run(db_session, stub_context, stub_pillars, monkeypatch):
    fake = _FakeClient(json.dumps(_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    monkeypatch.setenv("PRAXYS_INSIGHT_DAILY_CAP", "0")

    result = insights_runner.run_insights_for_user(USER_ID, db_session, {"activities": 1}, _session=db_session)

    assert result == {"skipped": "cap_reached"}
    assert db_session.query(AiInsight).count() == 0


def test_generator_returns_none_leaves_existing_row_intact(db_session, stub_context, stub_pillars, monkeypatch):
    """When the generator can't produce a payload (LLM returned bad JSON or
    missing endpoint), an existing AiInsight row must be preserved."""
    # Pre-existing row with stable values.
    existing = AiInsight(
        user_id=USER_ID,
        insight_type="daily_brief",
        headline="Old headline",
        summary="Old summary",
        findings=[],
        recommendations=[],
        translations={"zh": {"headline": "旧标题", "summary": "旧摘要",
                              "findings": [], "recommendations": []}},
        meta={"dataset_hash": "old-hash"},
    )
    db_session.add(existing)
    db_session.commit()

    # No client → all generators return None.
    monkeypatch.setattr(llm, "get_client", lambda: None)

    result = insights_runner.run_insights_for_user(USER_ID, db_session, {"activities": 1}, _session=db_session)

    assert result["daily_brief"] == "generator_returned_none"
    db_session.expire_all()
    row = db_session.query(AiInsight).filter_by(user_id=USER_ID, insight_type="daily_brief").one()
    assert row.headline == "Old headline"
    assert row.meta["dataset_hash"] == "old-hash"
