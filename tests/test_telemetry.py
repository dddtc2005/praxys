"""Tests for ``api.telemetry`` Coach signals.

Coverage strategy: stub the OTel meter and the optional events extension so
each helper can be exercised in three regimes — telemetry off, OTel-only
(counters), and events-extension on (track_event). The tests assert call
shape rather than App Insights arrival, since we don't carry the SDK in
test envs.

Also covers the integration points: ``chat_json`` forwards token usage and
operator-actionable errors, and ``run_insights_for_user`` emits one
coach_run per insight type with the right status.
"""
from __future__ import annotations

import json
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class _FakeCounter:
    def __init__(self) -> None:
        self.calls: list[tuple[float, dict]] = []

    def add(self, amount: float, attributes: dict | None = None) -> None:
        self.calls.append((amount, dict(attributes or {})))


class _FakeMeter:
    def __init__(self) -> None:
        self.counters: dict[str, _FakeCounter] = {}

    def create_counter(self, name: str, description: str = "") -> _FakeCounter:
        # OTel meters return the same instrument across repeat calls — mirror
        # that so the @lru_cache memoisation in api.telemetry doesn't have to
        # re-create on every test.
        if name not in self.counters:
            self.counters[name] = _FakeCounter()
        return self.counters[name]


def _clear_caches() -> None:
    from api import telemetry

    # Tolerate the case where a prior fixture monkeypatched these to plain
    # callables (no .cache_clear) — we only need to drop real lru_caches.
    for name in ("_meter", "_counter", "_track_event"):
        fn = getattr(telemetry, name, None)
        clear = getattr(fn, "cache_clear", None)
        if callable(clear):
            clear()


@pytest.fixture
def reset_telemetry_caches():
    """Clear all lru_caches in api.telemetry between tests."""
    _clear_caches()
    yield
    _clear_caches()


@pytest.fixture
def fake_meter(monkeypatch, reset_telemetry_caches):
    """Wire a fake OTel meter into api.telemetry; events extension off."""
    from api import telemetry

    meter = _FakeMeter()
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=fake")
    monkeypatch.setattr(telemetry, "_meter", lambda: meter, raising=True)
    # Force counter cache to use the fake meter; preserve real impl by
    # bypassing its memoisation via direct factory.
    monkeypatch.setattr(
        telemetry, "_counter",
        lambda name, description: meter.create_counter(name, description),
        raising=True,
    )
    monkeypatch.setattr(telemetry, "_track_event", lambda: None, raising=True)
    return meter


@pytest.fixture
def fake_track_event(monkeypatch, reset_telemetry_caches):
    """Wire a fake events-extension track_event into api.telemetry."""
    from api import telemetry

    calls: list[tuple[str, dict]] = []

    def _track(event_name: str, attributes: dict | None = None) -> None:
        calls.append((event_name, dict(attributes or {})))

    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=fake")
    monkeypatch.setattr(telemetry, "_track_event", lambda: _track, raising=True)
    # Even with track_event present, _meter / _counter must stay callable so
    # the unrelated coach_tokens helper still records.
    meter = _FakeMeter()
    monkeypatch.setattr(telemetry, "_meter", lambda: meter, raising=True)
    monkeypatch.setattr(
        telemetry, "_counter",
        lambda name, description: meter.create_counter(name, description),
        raising=True,
    )
    return calls, meter


# ---------------------------------------------------------------------------
# hash_user_id
# ---------------------------------------------------------------------------


def test_hash_user_id_is_stable_and_truncated():
    from api import telemetry

    a = telemetry.hash_user_id("user-1")
    b = telemetry.hash_user_id("user-1")
    c = telemetry.hash_user_id("user-2")
    assert a == b
    assert a != c
    assert len(a) == 16
    assert all(ch in "0123456789abcdef" for ch in a)


# ---------------------------------------------------------------------------
# No-op contract when telemetry is disabled
# ---------------------------------------------------------------------------


def test_helpers_noop_when_appinsights_unset(monkeypatch, reset_telemetry_caches):
    from api import telemetry

    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    # Should silently return None without raising even when the OTel SDK is
    # absent — the env-var gate short-circuits before any import.
    telemetry.record_coach_tokens(
        insight_type="daily_brief", model="gpt-5.4",
        prompt_tokens=100, completion_tokens=50,
    )
    telemetry.record_coach_run(
        insight_type="daily_brief", status="generated", user_id="u1",
    )
    telemetry.record_coach_error(error_class="Auth")


# ---------------------------------------------------------------------------
# record_coach_tokens
# ---------------------------------------------------------------------------


def test_record_coach_tokens_emits_split_and_total(fake_meter):
    from api import telemetry

    telemetry.record_coach_tokens(
        insight_type="daily_brief", model="gpt-5.4",
        prompt_tokens=120, completion_tokens=30,
    )

    counter = fake_meter.counters["praxys.coach_tokens"]
    # One increment per token_type — sum stays correct under any
    # subsequent slice of customDimensions.
    types = sorted(c[1]["token_type"] for c in counter.calls)
    assert types == ["completion", "prompt", "total"]
    by_type = {c[1]["token_type"]: c for c in counter.calls}
    assert by_type["prompt"][0] == 120
    assert by_type["completion"][0] == 30
    assert by_type["total"][0] == 150
    for _, attrs in counter.calls:
        assert attrs["insight_type"] == "daily_brief"
        assert attrs["model"] == "gpt-5.4"


def test_record_coach_tokens_skips_zero_amounts(fake_meter):
    """Don't waste an emission slot on a zero — keeps the chart cleaner."""
    from api import telemetry

    telemetry.record_coach_tokens(
        insight_type="x", model="m", prompt_tokens=0, completion_tokens=0,
    )
    assert "praxys.coach_tokens" not in fake_meter.counters or \
        fake_meter.counters["praxys.coach_tokens"].calls == []


# ---------------------------------------------------------------------------
# record_coach_run
# ---------------------------------------------------------------------------


def test_record_coach_run_uses_track_event_when_available(fake_track_event):
    from api import telemetry

    calls, meter = fake_track_event
    telemetry.record_coach_run(
        insight_type="daily_brief", status="hash_match", user_id="user-1",
    )
    assert len(calls) == 1
    name, attrs = calls[0]
    assert name == "praxys.coach_run"
    assert attrs["insight_type"] == "daily_brief"
    assert attrs["status"] == "hash_match"
    # user_id is hashed, not raw.
    assert attrs["user_id_hash"] == telemetry.hash_user_id("user-1")
    assert "user-1" not in attrs["user_id_hash"]
    # Counter path must NOT have been used when track_event succeeded.
    assert "praxys.coach_run" not in meter.counters


def test_record_coach_run_falls_back_to_counter(fake_meter):
    from api import telemetry

    telemetry.record_coach_run(
        insight_type="training_review", status="generated", user_id="user-2",
    )
    counter = fake_meter.counters["praxys.coach_run"]
    assert len(counter.calls) == 1
    amount, attrs = counter.calls[0]
    assert amount == 1
    assert attrs["status"] == "generated"
    assert attrs["insight_type"] == "training_review"
    assert attrs["user_id_hash"] == telemetry.hash_user_id("user-2")


# ---------------------------------------------------------------------------
# record_coach_error
# ---------------------------------------------------------------------------


def test_record_coach_error_via_track_event(fake_track_event):
    from api import telemetry

    calls, _ = fake_track_event
    telemetry.record_coach_error(error_class="Auth")
    assert calls == [("praxys.coach_error", {"error_class": "Auth"})]


def test_record_coach_error_via_counter(fake_meter):
    from api import telemetry

    telemetry.record_coach_error(error_class="BadRequest")
    counter = fake_meter.counters["praxys.coach_error"]
    assert counter.calls == [(1, {"error_class": "BadRequest"})]


# ---------------------------------------------------------------------------
# chat_json integration
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, prompt: int, completion: int) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion


class _FakeMessage:
    def __init__(self, content: str) -> None: self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None: self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str, usage: _FakeUsage | None) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = usage


class _FakeCompletions:
    def __init__(self, response_or_exc: Any) -> None:
        self._payload = response_or_exc

    def create(self, **kwargs: Any) -> Any:
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


class _FakeClient:
    def __init__(self, response_or_exc: Any) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(response_or_exc)})()


def test_chat_json_records_token_usage(fake_meter):
    from api import llm

    payload = json.dumps({"ok": True})
    client = _FakeClient(_FakeResponse(payload, _FakeUsage(prompt=500, completion=120)))

    out = llm.chat_json(
        client, system="s", user="u",
        model="gpt-5.4", insight_type="daily_brief",
    )
    assert out == {"ok": True}
    counter = fake_meter.counters["praxys.coach_tokens"]
    by_type = {c[1]["token_type"]: c for c in counter.calls}
    assert by_type["prompt"][0] == 500
    assert by_type["completion"][0] == 120
    assert by_type["total"][0] == 620
    for _, attrs in counter.calls:
        assert attrs["insight_type"] == "daily_brief"
        assert attrs["model"] == "gpt-5.4"


def test_chat_json_default_insight_type(fake_meter):
    """Non-Coach callers (e.g. translate script) still emit, dimensioned 'unknown'."""
    from api import llm

    payload = json.dumps({"x": 1})
    client = _FakeClient(_FakeResponse(payload, _FakeUsage(prompt=10, completion=2)))
    llm.chat_json(client, system="s", user="u", model="gpt-5.4-mini")
    counter = fake_meter.counters["praxys.coach_tokens"]
    assert all(c[1]["insight_type"] == "unknown" for c in counter.calls)


def _instantiate_openai_exc(name: str):
    """Build an instance of an openai>=1.0 exception class, or skip the test.

    The pinned openai version on production is >=1.0 (it ships
    ``AuthenticationError`` / ``BadRequestError`` as top-level imports).
    Older 0.x SDKs in dev environments don't expose these symbols at all;
    rather than silently passing as a no-op, we skip — the production
    behaviour is verified anywhere the right SDK is installed.
    """
    openai = pytest.importorskip("openai")
    cls = getattr(openai, name, None)
    if cls is None:
        pytest.skip(f"openai {getattr(openai, '__version__', '?')} lacks {name}; needs >=1.0")
    # Constructor signature varies across 1.x minor releases. Try the
    # widely-stable (message, response, body) shape first; fall back to
    # bare message.
    try:
        return cls("fake", response=None, body=None)
    except TypeError:
        return cls("fake")


def test_chat_json_records_auth_error(fake_meter):
    """AuthenticationError → record_coach_error('Auth') and short-circuit."""
    from api import llm

    exc = _instantiate_openai_exc("AuthenticationError")
    client = _FakeClient(exc)
    out = llm.chat_json(
        client, system="s", user="u", model="gpt-5.4",
        insight_type="daily_brief", retry=0,
    )
    assert out is None
    counter = fake_meter.counters["praxys.coach_error"]
    assert counter.calls == [(1, {"error_class": "Auth"})]


def test_chat_json_records_bad_request(fake_meter):
    from api import llm

    exc = _instantiate_openai_exc("BadRequestError")
    client = _FakeClient(exc)
    out = llm.chat_json(
        client, system="s", user="u", model="gpt-5.4",
        insight_type="training_review", retry=0,
    )
    assert out is None
    counter = fake_meter.counters["praxys.coach_error"]
    assert counter.calls == [(1, {"error_class": "BadRequest"})]


# ---------------------------------------------------------------------------
# insights_runner integration
# ---------------------------------------------------------------------------


_FAKE_CTX = {
    "athlete_profile": {"goal": {"distance": "marathon"}},
    "current_fitness": {"ctl": 50.0, "atl": 45.0, "tsb": 5.0,
                         "cp_trend": {"current": 280.0, "direction": "up", "slope_per_month": 1.5},
                         "predicted_time_sec": 11000},
    "recent_training": {"weekly_summary": [], "sessions": []},
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

_FAKE_PILLARS = {
    "load": "banister_pmc",
    "recovery": "hrv_based",
    "prediction": "critical_power",
    "zones": "five_zone",
}


def _runner_session(monkeypatch):
    """Build an in-memory session and stub the context + pillars used by
    ``insights_runner._run``. Returns the session — caller closes it."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.models import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    monkeypatch.setattr("api.ai.build_training_context", lambda **kw: _FAKE_CTX)

    class _Cfg:
        science = _FAKE_PILLARS

    monkeypatch.setattr("analysis.config.load_config_from_db", lambda u, d: _Cfg())
    return session


def test_run_insights_emits_coach_run_per_type(fake_meter, monkeypatch):
    """All three generators return None → three coach_run with that status."""
    from api import insights_runner, llm, telemetry

    session = _runner_session(monkeypatch)
    monkeypatch.setattr(llm, "get_client", lambda: None)

    insights_runner.run_insights_for_user(
        "user-1", session, {"activities": 1}, _session=session,
    )

    counter = fake_meter.counters["praxys.coach_run"]
    statuses = sorted(c[1]["status"] for c in counter.calls)
    assert statuses == ["generator_returned_none"] * 3
    types = sorted(c[1]["insight_type"] for c in counter.calls)
    assert types == ["daily_brief", "race_forecast", "training_review"]
    for _, attrs in counter.calls:
        assert attrs["user_id_hash"] == telemetry.hash_user_id("user-1")

    session.close()


def test_run_insights_emits_hash_match_status(fake_meter, monkeypatch):
    """Pre-seeded rows with matching dataset_hash → three coach_run('hash_match').

    Anchors the cache hit rate signal: removing the hash_match telemetry
    call would silently flatten the cache effectiveness chart, and this
    test would catch it.
    """
    from analysis.insight_hash import compute_dataset_hash
    from db.models import AiInsight
    from api import insights_runner, llm

    session = _runner_session(monkeypatch)

    # Pre-seed a row per insight_type whose meta.dataset_hash matches the
    # one the runner will compute for the same context+pillars. This forces
    # the loop into the hash_match branch for every itype.
    for itype in insights_runner.GENERATORS_ORDER:
        h = compute_dataset_hash(_FAKE_CTX, itype, science_pillars=_FAKE_PILLARS)
        session.add(AiInsight(
            user_id="user-2",
            insight_type=itype,
            headline="cached", summary="cached",
            findings=[], recommendations=[],
            translations={},
            meta={"dataset_hash": h},
        ))
    session.commit()

    # Generator client need not be reachable — the hash_match branch
    # short-circuits before any LLM call.
    monkeypatch.setattr(llm, "get_client", lambda: None)
    insights_runner.run_insights_for_user(
        "user-2", session, {"activities": 1}, _session=session,
    )

    counter = fake_meter.counters["praxys.coach_run"]
    statuses = sorted(c[1]["status"] for c in counter.calls)
    assert statuses == ["hash_match"] * 3

    session.close()


def test_run_insights_emits_cap_reached_status(fake_meter, monkeypatch):
    """Cap=1 + zero pre-seeded rows → first generates, next two cap_reached.

    Anchors the per-iteration cap-pressure branch in ``insights_runner._run``
    (NOT the early-return branch — see test below). Removing the
    cap_reached telemetry call silently masks the signal that paying users
    are running into the daily limit; this test makes that regression
    observable.
    """
    import json
    from db.models import AiInsight
    from api import insights_runner, llm

    session = _runner_session(monkeypatch)

    # Cap=1 → first generate succeeds (used_today goes 0→1), then the next
    # two iterations hit the per-iteration cap branch.
    monkeypatch.setenv("PRAXYS_INSIGHT_DAILY_CAP", "1")

    # A working fake client so the first iteration's generate path is real.
    bilingual = {
        "en": {"headline": "h", "summary": "s",
               "findings": [{"type": "neutral", "text": "f"}],
               "recommendations": ["r"]},
        "zh": {"headline": "标题", "summary": "摘要",
               "findings": [{"type": "neutral", "text": "调查"}],
               "recommendations": ["建议"]},
    }
    payload = json.dumps(bilingual)
    client = _FakeClient(_FakeResponse(payload, _FakeUsage(prompt=10, completion=5)))
    monkeypatch.setattr(llm, "get_client", lambda: client)

    insights_runner.run_insights_for_user(
        "user-3", session, {"activities": 1}, _session=session,
    )

    counter = fake_meter.counters["praxys.coach_run"]
    statuses = [c[1]["status"] for c in counter.calls]
    # Order matches GENERATORS_ORDER: first generated, next two cap_reached.
    assert statuses == ["generated", "cap_reached", "cap_reached"]
    # And only one row was actually written.
    assert session.query(AiInsight).filter(AiInsight.user_id == "user-3").count() == 1

    session.close()


def test_run_insights_no_telemetry_on_short_circuit_cap(fake_meter, monkeypatch):
    """Documented gap: when the cap is exhausted before the loop even
    starts (early return at runner._run line ~77), no coach_run events
    fire. This test pins that contract — flipping the behavior to emit
    one event per itype before the early return would fail this and force
    a deliberate revisit of the observability tradeoff.
    """
    from datetime import datetime
    from db.models import AiInsight
    from api import insights_runner, llm

    session = _runner_session(monkeypatch)
    monkeypatch.setenv("PRAXYS_INSIGHT_DAILY_CAP", "0")
    monkeypatch.setattr(llm, "get_client", lambda: None)

    # Seed a row from "today" so used_today >= cap on entry.
    session.add(AiInsight(
        user_id="user-4", insight_type="daily_brief",
        headline="x", summary="x", findings=[], recommendations=[],
        translations={}, meta={}, generated_at=datetime.utcnow(),
    ))
    session.commit()

    result = insights_runner.run_insights_for_user(
        "user-4", session, {"activities": 1}, _session=session,
    )

    assert result == {"skipped": "cap_reached"}
    # No coach_run counter should have been touched at all.
    assert "praxys.coach_run" not in fake_meter.counters

    session.close()
