"""Database engine and session management.

Provides both sync (for pandas data loading) and async (for FastAPI-Users) sessions.
The sync engine uses plain sqlite:// and the async engine uses sqlite+aiosqlite://.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from db.models import Base


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
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Async engine (for FastAPI-Users)
    async_engine = create_async_engine(
        async_url, connect_args={"check_same_thread": False}
    )
    AsyncSessionLocal = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Create all tables (new tables only — doesn't add columns to existing tables)
    Base.metadata.create_all(bind=engine)

    # Lightweight schema migration: add missing columns to existing tables.
    # SQLAlchemy's create_all doesn't ALTER existing tables, so we handle
    # new columns here to avoid needing a full Alembic setup.
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    _migrations = [
        ("user_config", "unit_system", "VARCHAR(10) DEFAULT 'metric'"),
        ("user_config", "display_name", "VARCHAR(100) DEFAULT ''"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in _migrations:
            if table in insp.get_table_names():
                existing_cols = {c["name"] for c in insp.get_columns(table)}
                if column not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                    conn.commit()


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
