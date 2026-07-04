"""Alembic migration environment.

Schema target is ``db.models.Base.metadata``. The database URL is resolved
from the application config (``db.session.get_database_url``) so migrations
always run against the same database the app uses — SQLite locally,
PostgreSQL in production (#360). Engine construction is delegated to
``db.session`` so Entra (managed identity) auth and SQLite pragmas apply
identically to the app runtime.
"""
from logging.config import fileConfig

from alembic import context

from db.models import Base
from db.session import get_database_url, _make_sync_engine

config = context.config

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        # Logging config is best-effort; never fail a migration on it.
        pass

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no DBAPI connection)."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live connection built via db.session."""
    connectable = _make_sync_engine(get_database_url())
    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # Batch mode makes ALTER-heavy migrations work on SQLite (which
            # lacks a full ALTER TABLE). No-op on PostgreSQL.
            render_as_batch=is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()