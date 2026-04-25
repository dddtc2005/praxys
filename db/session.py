"""Database engine and session management.

Provides both sync (for pandas data loading) and async (for FastAPI-Users) sessions.
The sync engine uses plain sqlite:// and the async engine uses sqlite+aiosqlite://.
"""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from db.models import Base


# SQLite tuning pragmas applied to every new connection.
#
# Why this matters: on Azure App Service Linux the /home volume is an Azure
# Files (SMB) mount with high per-IOP latency. Default SQLite (rollback
# journal + synchronous=FULL) issues many small fsync()s per write, so each
# of those amplifies into an SMB round-trip. Even read-mostly workloads
# pay this cost on metadata pages. WAL + synchronous=NORMAL together cut
# the fsync count substantially while keeping crash-safety: a power loss
# may lose the last in-flight transaction but the database stays
# consistent. The other pragmas are pure cache/locality wins.
_SQLITE_PRAGMAS = (
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    # 20 MB SQLite page cache (negative value = KB; default is 2 MB).
    ("cache_size", "-20000"),
    ("temp_store", "MEMORY"),
    # Wait up to 5s on writer contention before raising "database is locked".
    ("busy_timeout", "5000"),
)


def _attach_sqlite_pragmas(engine_obj) -> None:
    """Attach a connect listener that applies _SQLITE_PRAGMAS to each connection.

    No-op for non-SQLite engines (so an eventual Postgres / Azure SQL
    migration drops in without code changes). PRAGMA journal_mode is also
    a no-op against ``:memory:`` databases used in tests, which is fine.
    """
    if engine_obj.dialect.name != "sqlite":
        return

    @event.listens_for(engine_obj.sync_engine if hasattr(engine_obj, "sync_engine") else engine_obj, "connect")
    def _apply_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            for pragma, value in _SQLITE_PRAGMAS:
                cursor.execute(f"PRAGMA {pragma}={value}")
        finally:
            cursor.close()


def get_data_dir() -> str:
    """Return the data directory path (configurable via DATA_DIR env var)."""
    return os.environ.get(
        "DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")
    )


def get_database_url() -> str:
    """Return the sync SQLite database URL."""
    data_dir = get_data_dir()
    db_path = os.path.join(data_dir, "trainsight.db")
    return f"sqlite:///{db_path}"


def get_async_database_url() -> str:
    """Return the async SQLite database URL (for aiosqlite)."""
    data_dir = get_data_dir()
    db_path = os.path.join(data_dir, "trainsight.db")
    return f"sqlite+aiosqlite:///{db_path}"


# Module-level engine/session singletons (initialized lazily)
engine = None
SessionLocal = None
async_engine = None
AsyncSessionLocal = None


def init_db():
    """Initialize sync and async database engines and create tables."""
    global engine, SessionLocal, async_engine, AsyncSessionLocal

    url = get_database_url()
    async_url = get_async_database_url()

    # Ensure the data directory exists
    db_path = url.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # Sync engine (for pandas read_sql, data loading, migration)
    engine = create_engine(url, connect_args={"check_same_thread": False})
    _attach_sqlite_pragmas(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Async engine (for FastAPI-Users)
    async_engine = create_async_engine(
        async_url, connect_args={"check_same_thread": False}
    )
    _attach_sqlite_pragmas(async_engine)
    AsyncSessionLocal = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Create all tables (new tables only — doesn't add columns to existing tables)
    Base.metadata.create_all(bind=engine)

    # Lightweight schema migration: add missing columns to existing tables.
    # SQLAlchemy's create_all doesn't ALTER existing tables, so we handle
    # new columns here to avoid needing a full Alembic setup.
    import logging
    from sqlalchemy import text, inspect
    from sqlalchemy.exc import OperationalError

    _log = logging.getLogger(__name__)
    insp = inspect(engine)
    _migrations = [
        ("user_config", "unit_system", "VARCHAR(10) DEFAULT 'metric'"),
        ("user_config", "display_name", "VARCHAR(100) DEFAULT ''"),
        ("user_config", "language", "VARCHAR(10) DEFAULT NULL"),
        ("users", "is_demo", "BOOLEAN NOT NULL DEFAULT 0"),
        ("users", "demo_of", "VARCHAR(36) DEFAULT NULL"),
        ("users", "wechat_openid", "VARCHAR(64) DEFAULT NULL"),
        ("users", "wechat_unionid", "VARCHAR(64) DEFAULT NULL"),
        ("users", "wechat_nickname", "VARCHAR(100) DEFAULT NULL"),
        ("users", "wechat_avatar_url", "VARCHAR(500) DEFAULT NULL"),
    ]
    _indexes = [
        # (index_name, table, column, unique)
        ("ix_users_wechat_openid", "users", "wechat_openid", True),
        ("ix_users_wechat_unionid", "users", "wechat_unionid", False),
    ]
    with engine.connect() as conn:
        for table, column, col_type in _migrations:
            if table in insp.get_table_names():
                existing_cols = {c["name"] for c in insp.get_columns(table)}
                if column not in existing_cols:
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                        conn.commit()
                    except OperationalError:
                        # Column may already exist (concurrent worker startup)
                        conn.rollback()
                        _log.debug("Column %s.%s already exists, skipping", table, column)

        # Refresh inspector after ALTERs so get_columns sees the new columns
        # before we attempt to create indexes that reference them.
        insp_after = inspect(engine)
        for index_name, table, column, unique in _indexes:
            if table not in insp_after.get_table_names():
                continue
            existing_cols = {c["name"] for c in insp_after.get_columns(table)}
            if column not in existing_cols:
                continue
            unique_clause = "UNIQUE " if unique else ""
            try:
                conn.execute(text(
                    f"CREATE {unique_clause}INDEX IF NOT EXISTS {index_name} ON {table} ({column})"
                ))
                conn.commit()
            except OperationalError:
                conn.rollback()
                _log.debug("Index %s already exists, skipping", index_name)


def get_db():
    """FastAPI dependency that yields a sync DB session."""
    if SessionLocal is None:
        init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db():
    """FastAPI dependency that yields an async DB session (for FastAPI-Users)."""
    if AsyncSessionLocal is None:
        init_db()
    async with AsyncSessionLocal() as session:
        yield session
