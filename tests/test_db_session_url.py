"""URL resolution for the dual SQLite/PostgreSQL engine (#360).

Pure-function tests (no DB connection) covering the DATABASE_URL /
PRAXYS_DATABASE_URL resolution and psycopg-driver normalization added in
db/session.py.
"""
import pytest


@pytest.fixture
def dbs(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PRAXYS_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from db import session as s
    return s


def test_default_is_sqlite_under_data_dir(dbs):
    url = dbs.get_database_url()
    assert url.startswith("sqlite:///")
    assert "trainsight.db" in url
    assert dbs.get_async_database_url().startswith("sqlite+aiosqlite:///")
    assert dbs.is_postgres() is False


def test_postgres_scheme_normalized_to_psycopg(dbs, monkeypatch):
    monkeypatch.setenv("PRAXYS_DATABASE_URL", "postgres://u:p@host:5432/db")
    assert dbs.get_database_url() == "postgresql+psycopg://u:p@host:5432/db"
    # Async reuses the same psycopg driver.
    assert dbs.get_async_database_url() == "postgresql+psycopg://u:p@host:5432/db"
    assert dbs.is_postgres() is True


def test_postgresql_scheme_normalized(dbs, monkeypatch):
    monkeypatch.setenv("PRAXYS_DATABASE_URL", "postgresql://u:p@host/db")
    assert dbs.get_database_url() == "postgresql+psycopg://u:p@host/db"


def test_explicit_driver_preserved(dbs, monkeypatch):
    monkeypatch.setenv("PRAXYS_DATABASE_URL", "postgresql+asyncpg://u:p@host/db")
    assert dbs.get_database_url() == "postgresql+asyncpg://u:p@host/db"


def test_database_url_fallback_var(dbs, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    assert dbs.get_database_url() == "postgresql+psycopg://u:p@host/db"


def test_praxys_url_takes_precedence(dbs, monkeypatch):
    monkeypatch.setenv("PRAXYS_DATABASE_URL", "postgresql://a/db1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://b/db2")
    assert "db1" in dbs.get_database_url()


def test_blank_url_falls_back_to_sqlite(dbs, monkeypatch):
    monkeypatch.setenv("PRAXYS_DATABASE_URL", "   ")
    assert dbs.get_database_url().startswith("sqlite:///")