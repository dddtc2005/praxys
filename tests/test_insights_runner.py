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

from db.cache_revision import SCOPES
from db.models import AiInsight, Base, User
from api import insights_runner, llm


PILLARS = {
    "load": "banister_pmc",
    "recovery": "hrv_based",
    "prediction": "critical_power",
    "zones": "coggan_5zone",
}

USER_ID = "11111111-1111-1111-1111-111111111111"
SOURCE_REVISIONS = {scope: 0 for scope in SCOPES}


def _bilingual_response(headline: str = "Test headline") -> dict:
    return {

        "en": {
            "headline": headline,
            "summary": "English summary.",
            "findings": [{"type": "positive", "text": "All good"}],
            "recommendations": [],
        },
        "zh": {
            "headline": "测试标题",
            "summary": "中文摘要。",
            "findings": [{"type": "positive", "text": "状态良好"}],
            "recommendations": [],
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
    session.add(User(id=USER_ID, email="runner@example.test", hashed_password="x"))
    session.commit()
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
        "current_plan": [
            {
                "workout_type": "easy",
                "planned_duration_min": 45,
                "target_power_min": 180,
                "target_power_max": 210,
            },
        ],
        "planned_today": {
            "workout_type": "easy",
            "planned_duration_min": 45,
            "target_power_min": 180,
            "target_power_max": 210,
        },
        "today_signal": {
            "recommendation": "follow_plan",
            "reason": "Recovery signals normal. Follow plan as written.",
            "alternatives": [],
        },
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


def test_generates_both_durable_insights_when_hash_differs(
    db_session, stub_context, stub_pillars, monkeypatch,
):
    fake = _FakeClient(json.dumps(_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    result = insights_runner.run_insights_for_user(
        USER_ID, db_session, {"activities": 5}, _session=db_session,
    )

    assert result == {
        "training_review": "generated",
        "race_forecast": "generated",
    }
    rows = db_session.query(AiInsight).filter(AiInsight.user_id == USER_ID).all()
    assert len(rows) == 2
    assert {row.insight_type for row in rows} == {
        "training_review",
        "race_forecast",
    }

    for row in rows:
        assert row.translations.get("zh", {}).get("headline") == "测试标题"
        assert "dataset_hash" in row.meta
        provenance = row.meta["_generation_provenance"]
        assert provenance["model"] == llm.INSIGHT_MODEL
        assert provenance["pillars"] == PILLARS
        assert provenance["source_revisions"] == SOURCE_REVISIONS
        assert datetime.fromisoformat(provenance["run_started_at"])

def test_retries_context_when_calendar_date_changes(
    db_session, stub_context, stub_pillars, monkeypatch,
):
    from datetime import date as real_date

    dates = iter([
        real_date(2026, 7, 12),
        real_date(2026, 7, 13),
        real_date(2026, 7, 13),
        real_date(2026, 7, 13),
        real_date(2026, 7, 13),
    ])

    class _RollingDate:
        @classmethod
        def today(cls):
            return next(dates)

    context_calls = {"count": 0}

    def _build_context(**_kwargs):
        context_calls["count"] += 1
        return stub_context

    monkeypatch.setattr(insights_runner, "date", _RollingDate)
    monkeypatch.setattr("api.ai.build_training_context", _build_context)
    monkeypatch.setattr(llm, "get_client", lambda: _FakeClient(
        json.dumps(_bilingual_response())
    ))

    result = insights_runner.run_insights_for_user(
        USER_ID, db_session, {"activities": 1}, _session=db_session,
    )

    assert context_calls["count"] == 2
    assert result == {
        "training_review": "generated",
        "race_forecast": "generated",
    }

def test_discards_generation_batch_when_llm_calls_cross_midnight(
    db_session, stub_context, stub_pillars, monkeypatch,
):
    from datetime import date as real_date

    dates = iter([
        real_date(2026, 7, 12),
        real_date(2026, 7, 12),
        real_date(2026, 7, 13),
    ])

    class _RollingDate:
        @classmethod
        def today(cls):
            return next(dates)

    monkeypatch.setattr(insights_runner, "date", _RollingDate)
    monkeypatch.setattr(llm, "get_client", lambda: _FakeClient(
        json.dumps(_bilingual_response())
    ))

    result = insights_runner.run_insights_for_user(
        USER_ID, db_session, {"activities": 1}, _session=db_session,
    )

    assert all(status == "superseded" for status in result.values())
    assert db_session.query(AiInsight).count() == 0

def test_runner_never_writes_or_refreshes_daily_brief(
    db_session, stub_context, stub_pillars, monkeypatch,
):
    existing = AiInsight(
        user_id=USER_ID,
        insight_type="daily_brief",
        headline="Persisted legacy brief",
        summary="Must remain untouched and hidden.",
        findings=[],
        recommendations=[],
        meta={"dataset_hash": "legacy"},
    )
    db_session.add(existing)
    db_session.commit()
    fake = _FakeClient(json.dumps(_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    monkeypatch.setenv("PRAXYS_INSIGHT_DAILY_CAP", "2")

    result = insights_runner.run_insights_for_user(
        USER_ID, db_session, {"activities": 1}, _session=db_session,
    )

    db_session.refresh(existing)
    assert set(result) == {"training_review", "race_forecast"}
    assert existing.headline == "Persisted legacy brief"
    assert existing.meta == {"dataset_hash": "legacy"}
    assert fake.chat.completions.call_count == 2

def test_skips_when_hash_matches(db_session, stub_context, stub_pillars, monkeypatch):
    fake = _FakeClient(json.dumps(_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    # First sync: generates both durable insight types.
    insights_runner.run_insights_for_user(USER_ID, db_session, {"activities": 5}, _session=db_session)
    initial_calls = fake.chat.completions.call_count
    assert initial_calls == 2

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


def test_runner_restores_feedback_when_dataset_hash_returns(
    db_session, stub_context, stub_pillars, monkeypatch,
):
    from db.models import AiInsightFeedback

    fake = _FakeClient(json.dumps(_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    current_hash = {"value": "a" * 64}
    monkeypatch.setattr(
        "analysis.insight_hash.compute_dataset_hash",
        lambda *args, **kwargs: current_hash["value"],
    )

    insights_runner.run_insights_for_user(
        USER_ID, db_session, {"activities": 1}, _session=db_session,
    )
    daily = db_session.query(AiInsight).filter_by(
        user_id=USER_ID,
        insight_type="training_review",
    ).one()
    hash_a = daily.meta["dataset_hash"]
    submitted_a = datetime.utcnow()
    feedback_a = {
        "dataset_hash": hash_a,
        "vote": "up",
        "submitted_at": submitted_a.isoformat() + "+00:00",
    }
    daily.meta = {**daily.meta, "feedback": feedback_a}
    db_session.add(AiInsightFeedback(
        user_id=USER_ID,
        insight_type="training_review",
        dataset_hash=hash_a,
        vote="up",
        submitted_at=submitted_a,
    ))
    db_session.commit()

    current_hash["value"] = "b" * 64
    insights_runner.run_insights_for_user(
        USER_ID, db_session, {"activities": 1}, _session=db_session,
    )
    daily = db_session.query(AiInsight).filter_by(
        user_id=USER_ID,
        insight_type="training_review",
    ).one()
    hash_b = daily.meta["dataset_hash"]
    assert hash_b != hash_a
    submitted_b = datetime.utcnow()
    daily.meta = {
        **daily.meta,
        "feedback": {
            "dataset_hash": hash_b,
            "vote": "down",
            "submitted_at": submitted_b.isoformat() + "+00:00",
        },
    }
    db_session.add(AiInsightFeedback(
        user_id=USER_ID,
        insight_type="training_review",
        dataset_hash=hash_b,
        vote="down",
        submitted_at=submitted_b,
    ))
    db_session.commit()

    current_hash["value"] = "a" * 64
    insights_runner.run_insights_for_user(
        USER_ID, db_session, {"activities": 1}, _session=db_session,
    )
    db_session.expire_all()
    restored = db_session.query(AiInsight).filter_by(
        user_id=USER_ID,
        insight_type="training_review",
    ).one()
    assert restored.meta["feedback"]["dataset_hash"] == hash_a
    assert restored.meta["feedback"]["vote"] == "up"


def test_matching_hash_client_push_is_regenerated_not_trusted(
    db_session, stub_context, stub_pillars, monkeypatch,
):
    fake = _FakeClient(json.dumps(_bilingual_response("Trusted headline")))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    insights_runner.run_insights_for_user(
        USER_ID, db_session, {"activities": 1}, _session=db_session,
    )
    initial_calls = fake.chat.completions.call_count
    daily = db_session.query(AiInsight).filter_by(
        user_id=USER_ID,
        insight_type="training_review",
    ).one()
    copied_hash = daily.meta["dataset_hash"]
    daily.headline = "Client-pushed contradiction"
    daily.meta = {"dataset_hash": copied_hash}
    db_session.commit()

    result = insights_runner.run_insights_for_user(
        USER_ID, db_session, {"activities": 1}, _session=db_session,
    )

    db_session.expire_all()
    regenerated = db_session.query(AiInsight).filter_by(
        user_id=USER_ID,
        insight_type="training_review",
    ).one()
    assert result["training_review"] == "generated"
    assert fake.chat.completions.call_count == initial_calls + 1
    assert regenerated.headline == "Trusted headline"
    assert "_generation_provenance" in regenerated.meta

def test_cap_reached_skips_remaining_types(db_session, stub_context, stub_pillars, monkeypatch):
    fake = _FakeClient(json.dumps(_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    monkeypatch.setenv("PRAXYS_INSIGHT_DAILY_CAP", "1")

    result = insights_runner.run_insights_for_user(
        USER_ID, db_session, {"activities": 1}, _session=db_session,
    )

    assert result["training_review"] == "generated"
    assert result["race_forecast"] == "cap_reached"


def test_cap_reached_skips_all_generators(
    db_session, stub_context, stub_pillars, monkeypatch,
):
    fake = _FakeClient(json.dumps(_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    monkeypatch.setenv("PRAXYS_INSIGHT_DAILY_CAP", "0")

    result = insights_runner.run_insights_for_user(
        USER_ID, db_session, {"activities": 1}, _session=db_session,
    )

    assert result == {
        "training_review": "cap_reached",
        "race_forecast": "cap_reached",
    }
    assert fake.chat.completions.call_count == 0
    assert db_session.query(AiInsight).count() == 0


def test_older_run_cannot_overwrite_newer_insight(db_session):
    newer_generated_at = datetime.utcnow()
    existing = AiInsight(
        user_id=USER_ID,
        insight_type="training_review",
        headline="Newer headline",
        summary="Newer summary",
        findings=[],
        recommendations=[],
        translations={},
        meta={"dataset_hash": "b" * 64},
        generated_at=newer_generated_at,
    )
    db_session.add(existing)
    db_session.commit()

    written = insights_runner._upsert_insight(
        db_session,
        USER_ID,
        "training_review",
        {
            "headline": "Older headline",
            "summary": "Older summary",
            "findings": [],
            "recommendations": [],
            "translations": {},
            "meta_extra": {"model": "gpt-test", "pillars": PILLARS},
        },
        "a" * 64,
        SOURCE_REVISIONS,
        newer_generated_at - timedelta(seconds=1),
    )

    assert written is False
    db_session.expire_all()
    row = db_session.query(AiInsight).filter_by(
        user_id=USER_ID,
        insight_type="training_review",
    ).one()
    assert row.headline == "Newer headline"
    assert row.meta["dataset_hash"] == "b" * 64

def test_upsert_refreshes_cached_row_before_superseded_guard(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runner-refresh.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    stale_db = Session()
    fresh_db = Session()
    try:
        call_started_at = datetime.utcnow()
        cached = AiInsight(
            user_id=USER_ID,
            insight_type="training_review",
            headline="Cached older insight",
            summary="Cached summary",
            findings=[],
            recommendations=[],
            translations={},
            meta={
                "dataset_hash": "a" * 64,
                "_generation_provenance": {
                    "model": "gpt-test",
                    "pillars": PILLARS,
                    "run_started_at": (call_started_at - timedelta(seconds=1)).isoformat(),
                },
            },
            generated_at=call_started_at - timedelta(seconds=1),
        )
        stale_db.add(User(id=USER_ID, email="runner@example.test", hashed_password="x"))
        stale_db.add(cached)
        stale_db.commit()
        stale_db.query(AiInsight).filter_by(
            user_id=USER_ID,
            insight_type="training_review",
        ).one()
        stale_db.commit()

        newer = fresh_db.query(AiInsight).filter_by(
            user_id=USER_ID,
            insight_type="training_review",
        ).one()
        newer.headline = "Newer committed insight"
        newer.meta = {
            "dataset_hash": "b" * 64,
            "_generation_provenance": {
                "model": "gpt-test",
                "pillars": PILLARS,
                "run_started_at": (call_started_at + timedelta(seconds=1)).isoformat(),
            },
        }
        newer.generated_at = call_started_at + timedelta(seconds=1)
        fresh_db.commit()

        written = insights_runner._upsert_insight(
            stale_db,
            USER_ID,
            "training_review",
            {
                "headline": "Stale overwrite",
                "summary": "Stale summary",
                "findings": [],
                "recommendations": [],
                "translations": {},
                "meta_extra": {"model": "gpt-test", "pillars": PILLARS},
            },
            "c" * 64,
            SOURCE_REVISIONS,
            call_started_at,
        )

        assert written is False
        stale_db.refresh(cached)
        assert cached.headline == "Newer committed insight"
        assert cached.meta["dataset_hash"] == "b" * 64
    finally:
        stale_db.close()
        fresh_db.close()
        engine.dispose()



def test_later_started_run_overwrites_an_older_run_that_finished_late(db_session):
    newer_run_started_at = datetime.utcnow()
    older_run_started_at = newer_run_started_at - timedelta(seconds=1)
    existing = AiInsight(
        user_id=USER_ID,
        insight_type="training_review",
        headline="Older snapshot written late",
        summary="Older summary",
        findings=[],
        recommendations=[],
        translations={},
        meta={
            "dataset_hash": "a" * 64,
            "_generation_provenance": {
                "model": "gpt-test",
                "pillars": PILLARS,
                "run_started_at": older_run_started_at.isoformat(),
            },
        },
        generated_at=newer_run_started_at + timedelta(seconds=1),
    )
    db_session.add(existing)
    db_session.commit()

    written = insights_runner._upsert_insight(
        db_session,
        USER_ID,
        "training_review",
        {
            "headline": "Newer snapshot",
            "summary": "Newer summary",
            "findings": [],
            "recommendations": [],
            "translations": {},
            "meta_extra": {"model": "gpt-test", "pillars": PILLARS},
        },
        "b" * 64,
        SOURCE_REVISIONS,
        newer_run_started_at,
    )

    assert written is True
    assert existing.headline == "Newer snapshot"
    assert existing.meta["dataset_hash"] == "b" * 64

def test_upsert_rejects_snapshot_after_source_revision_advances(db_session):
    from db.models import CacheRevision

    db_session.add(CacheRevision(
        user_id=USER_ID,
        scope="activities",
        revision=1,
    ))
    db_session.commit()

    written = insights_runner._upsert_insight(
        db_session,
        USER_ID,
        "training_review",
        {
            "headline": "Stale snapshot",
            "summary": "Stale summary",
            "findings": [],
            "recommendations": [],
            "translations": {},
            "meta_extra": {"model": "gpt-test", "pillars": PILLARS},
        },
        "a" * 64,
        SOURCE_REVISIONS,
        datetime.utcnow(),
    )

    assert written is False
    assert db_session.query(AiInsight).count() == 0


def test_generator_returns_none_leaves_existing_row_intact(db_session, stub_context, stub_pillars, monkeypatch):
    """When the generator can't produce a payload (LLM returned bad JSON or
    missing endpoint), an existing AiInsight row must be preserved."""
    # Pre-existing row with stable values.
    existing = AiInsight(
        user_id=USER_ID,
        insight_type="training_review",
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

    assert result["training_review"] == "generator_returned_none"
    db_session.expire_all()
    row = db_session.query(AiInsight).filter_by(user_id=USER_ID, insight_type="training_review").one()
    assert row.headline == "Old headline"
    assert row.meta["dataset_hash"] == "old-hash"

def test_runner_serializes_write_batch_before_upserts(
    db_session,
    stub_context,
    stub_pillars,
    monkeypatch,
):
    fake = _FakeClient(json.dumps(_bilingual_response()))
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    events: list[str] = []
    monkeypatch.setattr(
        "db.session.begin_serialized_write",
        lambda _db: events.append("serialized-write"),
    )
    monkeypatch.setattr(
        insights_runner,
        "_upsert_insight",
        lambda *args, **kwargs: events.append("upsert") or True,
    )

    result = insights_runner.run_insights_for_user(
        USER_ID,
        db_session,
        {"activities": 1},
        _session=db_session,
    )

    assert set(result.values()) == {"generated"}
    assert events == ["serialized-write", "upsert", "upsert"]


def test_generation_lock_is_transaction_scoped_and_released_on_early_return(
    monkeypatch,
):
    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = _Dialect()

    class _FakeSession:
        def __init__(self):
            self.statements: list[str] = []
            self.transaction_active = True
            self.rollback_count = 0

        def get_bind(self):
            return _Bind()

        def execute(self, statement, params=None):
            self.statements.append(str(statement))

        def in_transaction(self):
            return self.transaction_active

        def rollback(self):
            self.rollback_count += 1
            self.transaction_active = False

    db = _FakeSession()
    monkeypatch.setattr(
        insights_runner,
        "_run",
        lambda _db, _user_id: {"skipped": "cap_reached"},
    )

    result = insights_runner._run_serialized(db, USER_ID)

    assert result == {"skipped": "cap_reached"}
    assert len(db.statements) == 1
    assert "pg_advisory_xact_lock" in db.statements[0]
    assert "pg_advisory_unlock" not in db.statements[0]
    assert db.rollback_count == 1


def test_upsert_takes_revision_lock_before_user_row(monkeypatch):
    from types import SimpleNamespace

    from db import cache_revision

    events: list[str] = []

    class _Dialect:
        name = "sqlite"

    class _Bind:
        dialect = _Dialect()

    class _FakeQuery:
        def __init__(self, model):
            self.model = model

        def populate_existing(self):
            return self

        def with_for_update(self):
            return self

        def filter(self, *args):
            return self

        def first(self):
            events.append(f"first:{self.model.__name__}")
            if self.model is User:
                return SimpleNamespace(is_active=True)
            return None

    class _FakeSession:
        def get_bind(self):
            return _Bind()

        def query(self, model):
            events.append(f"query:{model.__name__}")
            return _FakeQuery(model)

        def add(self, row):
            events.append(f"add:{type(row).__name__}")

    monkeypatch.setattr(
        cache_revision,
        "lock_revision_writes",
        lambda _db, _user_id: events.append("revision-lock"),
    )
    monkeypatch.setattr(
        cache_revision,
        "get_revisions",
        lambda _db, _user_id, _scopes: (
            events.append("revision-read") or SOURCE_REVISIONS
        ),
    )
    monkeypatch.setattr(
        insights_runner,
        "merge_feedback_meta",
        lambda _db, _user_id, _itype, incoming, _existing: incoming,
    )

    written = insights_runner._upsert_insight(
        _FakeSession(),
        USER_ID,
        "training_review",
        {
            "headline": "Current snapshot",
            "summary": "Current summary",
            "findings": [],
            "recommendations": [],
            "translations": {},
            "meta_extra": {"model": "gpt-test", "pillars": PILLARS},
        },
        "a" * 64,
        SOURCE_REVISIONS,
        datetime.utcnow(),
    )

    assert written is True
    assert events.index("revision-lock") < events.index("query:User")
