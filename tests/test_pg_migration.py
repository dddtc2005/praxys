"""SQLite -> PostgreSQL migration round-trip test (#360).

Skipped unless PRAXYS_TEST_POSTGRES_URL points at a scratch Postgres database
(the test TRUNCATEs it). Seeds a type-diverse SQLite source (bytes / JSON /
Date / DateTime / composite PKs / SERIAL PKs), runs the real migration
routine, and asserts row-count parity plus that encrypted credential blobs
still decrypt and JSON / date values survived the move.
"""
import importlib.util
import os
from datetime import date, datetime

import pytest
from cryptography.fernet import Fernet

pytestmark = pytest.mark.skipif(
    not os.environ.get("PRAXYS_TEST_POSTGRES_URL"),
    reason="set PRAXYS_TEST_POSTGRES_URL to a scratch Postgres DB to run the SQLite->PG migration test",
)


def _load_migrate():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "scripts", "migrate_sqlite_to_postgres.py")
    spec = importlib.util.spec_from_file_location("praxys_migrate_script", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.migrate


def _normalize_pg(url):
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def test_sqlite_to_postgres_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PRAXYS_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PRAXYS_LOCAL_ENCRYPTION_KEY", Fernet.generate_key().decode())

    from db import crypto as dbc
    from db import session as dbs

    dbs.engine = dbs.SessionLocal = dbs.async_engine = dbs.AsyncSessionLocal = None
    dbc._vault = None

    try:
        dbs.init_db()

        from db import models as m
        from db.crypto import get_vault

        enc, dek = get_vault().encrypt("garmin-secret-password")
        uid = "11111111-1111-1111-1111-111111111111"

        session = dbs.SessionLocal()
        try:
            session.add(
                m.User(
                    id=uid, email="mig@example.com", hashed_password="x",
                    is_active=True, is_superuser=True, is_verified=True,
                    created_at=datetime.utcnow(),
                )
            )
            session.flush()
            session.add_all([
                m.UserConfig(
                    user_id=uid, display_name="Mig", preferences={"k": 1},
                    thresholds={"cp": 300}, zones={}, goal={}, science={},
                    activity_routing={}, source_options={},
                ),
                m.UserConnection(
                    user_id=uid, platform="garmin", encrypted_credentials=enc,
                    wrapped_dek=dek, preferences={"activities": True},
                    status="connected", last_sync=datetime.utcnow(),
                ),
                m.Activity(
                    user_id=uid, activity_id="act-1", date=date(2026, 6, 1),
                    distance_km=10.0, duration_sec=3000.0, avg_power=250.0,
                    start_time="2026-06-01T06:00:00Z", source="garmin",
                ),
                m.ActivitySplit(
                    user_id=uid, activity_id="act-1", split_num=1,
                    distance_km=1.0, duration_sec=300.0, avg_power=255.0,
                ),
                m.ActivitySample(
                    user_id=uid, activity_id="act-1", source="stryd",
                    t_sec=0, power_watts=250.0, hr_bpm=150.0,
                ),
                m.RecoveryData(
                    user_id=uid, date=date(2026, 6, 1), readiness_score=82.0,
                    hrv_avg=65.0, source="oura",
                ),
                m.FitnessData(
                    user_id=uid, date=date(2026, 6, 1), metric_type="vo2max",
                    value=55.0, source="garmin",
                ),
                m.AiInsight(
                    user_id=uid, insight_type="daily_brief", headline="Hi",
                    summary="s", findings=[{"type": "x", "text": "y"}],
                    recommendations=["r1", "r2"], meta={"h": 1},
                    translations={"zh": {"headline": "nihao"}},
                    generated_at=datetime.utcnow(),
                ),
                m.TrainingPlan(
                    user_id=uid, date=date(2026, 6, 2), workout_type="easy",
                    planned_distance_km=8.0, source="ai",
                    start_time=datetime(2026, 6, 2, 6, 0, 0), meta={"cp": 300},
                ),
                m.Invitation(code="MIGCODE1", created_by=uid, is_active=True, note="t"),
                m.CacheRevision(user_id=uid, scope="activities", revision=3),
                m.DashboardCache(
                    user_id=uid, section="today", source_version="activities=3",
                    payload_json=b"\x00\x01\x02binary-payload",
                ),
                m.SystemAnnouncement(title="Hello", body="World", type="info", is_active=True),
            ])
            session.commit()
        finally:
            session.close()

        from sqlalchemy import create_engine, func, select

        sqlite_path = os.path.join(str(tmp_path), "trainsight.db")
        src = create_engine(f"sqlite:///{sqlite_path}")
        src_counts = {}
        with src.connect() as c:
            for t in m.Base.metadata.sorted_tables:
                src_counts[t.name] = c.execute(select(func.count()).select_from(t)).scalar()
        src.dispose()
        assert src_counts["users"] == 1
        assert src_counts["user_connections"] == 1
        assert src_counts["dashboard_cache"] == 1

        migrate = _load_migrate()
        pg_url = os.environ["PRAXYS_TEST_POSTGRES_URL"]
        migrate(sqlite_path, pg_url, wipe=True, create_schema=True, verify_decrypt=True)

        tgt = create_engine(_normalize_pg(pg_url))
        try:
            with tgt.connect() as c:
                for t in m.Base.metadata.sorted_tables:
                    n = c.execute(select(func.count()).select_from(t)).scalar()
                    assert n == src_counts[t.name], f"{t.name}: {n} != {src_counts[t.name]}"
                row = c.execute(
                    select(m.UserConnection.encrypted_credentials, m.UserConnection.wrapped_dek)
                    .where(m.UserConnection.user_id == uid)
                ).one()
                assert get_vault().decrypt(bytes(row[0]), bytes(row[1])) == "garmin-secret-password"
                ins = c.execute(
                    select(m.AiInsight.translations, m.AiInsight.recommendations)
                    .where(m.AiInsight.user_id == uid)
                ).one()
                assert ins[0]["zh"]["headline"] == "nihao"
                assert ins[1] == ["r1", "r2"]
                act_date = c.execute(
                    select(m.Activity.date).where(m.Activity.user_id == uid)
                ).scalar()
                assert str(act_date) == "2026-06-01"

            # The application read path must work on Postgres too (regression
            # guard for the pandas read_sql :name -> %(name)s paramstyle bug).
            from sqlalchemy.orm import sessionmaker
            from analysis.data_loader import load_data_from_db, load_activity_samples

            pg_session = sessionmaker(bind=tgt)()
            try:
                loaded = load_data_from_db(uid, pg_session)
                assert not loaded["activities"].empty
                assert str(loaded["activities"]["date"].iloc[0]) == "2026-06-01"
                assert len(load_activity_samples(uid, pg_session, ["act-1"])) == 1
            finally:
                pg_session.close()
        finally:
            tgt.dispose()
    finally:
        os.environ.pop("PRAXYS_DATABASE_URL", None)
        dbs.engine = dbs.SessionLocal = dbs.async_engine = dbs.AsyncSessionLocal = None
        dbc._vault = None