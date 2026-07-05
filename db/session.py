"""Database engine and session management.

Supports **SQLite** (local dev / tests) and **PostgreSQL** (production). The
engine URL is resolved from the environment (``PRAXYS_DATABASE_URL`` /
``DATABASE_URL``) with a SQLite file under ``DATA_DIR`` as the default
fallback, so existing local and CI workflows keep working unchanged.

Provides both sync (for pandas ``read_sql`` data loading) and async (for
FastAPI-Users) sessions. On PostgreSQL a single psycopg3 driver backs both
the sync and async engines.

Schema management:
- SQLite (dev / tests): ``Base.metadata.create_all`` builds the full current
  schema on boot — fast, no migration overhead.
- PostgreSQL (real deployments): Alembic owns schema evolution. ``init_db``
  runs ``alembic upgrade head`` under a Postgres advisory lock so exactly one
  worker/instance applies pending migrations.
"""
import logging
import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from db.models import Base

logger = logging.getLogger(__name__)


# SQLite tuning pragmas applied to every new connection.
#
# journal_mode is DELETE (rollback journal), NOT WAL — deliberately.
# On Azure App Service Linux the DATA_DIR (/home) is an Azure Files (SMB)
# network mount, and SQLite's WAL mode requires a shared-memory index (the
# ``-shm`` file) backed by mmap that does NOT work over a network filesystem.
# SQLite documents this explicitly ("WAL does not work over a network
# filesystem", https://www.sqlite.org/wal.html). Running WAL on /home caused
# "database disk image is malformed" corruption in production — the failure
# is amplified by multiple gunicorn worker processes acting as concurrent
# writers over SMB. A classic rollback journal works over SMB (byte-range
# locks); paired with a SINGLE writer (run the backend with one gunicorn
# worker — see docs/ops/backup-and-restore.md) and busy_timeout, writes stay
# safe.
#
# synchronous=FULL (not NORMAL): on the SMB mount a container recycle mid-write
# (every deploy/scale) is the "power loss" equivalent, and FULL fsyncs the
# rollback journal so an interrupted write can't corrupt the file. It costs
# extra SMB round-trips per commit, but on this low-traffic workload
# correctness beats throughput. The remaining pragmas are cache/locality wins.
#
# NB: migrating to PostgreSQL (#360) retires this whole failure class — the
# pragmas below no-op for non-SQLite engines.
_SQLITE_PRAGMAS = (
    ("journal_mode", "DELETE"),
    ("synchronous", "FULL"),
    # 20 MB SQLite page cache (negative value = KB; default is 2 MB).
    ("cache_size", "-20000"),
    ("temp_store", "MEMORY"),
    # Wait up to 5s on writer contention before raising "database is locked".
    ("busy_timeout", "5000"),
)

# Postgres connection-pool defaults, sized for a Burstable Flexible Server
# tier (low max_connections). Overridable via env for larger tiers.
_PG_POOL_SIZE = int(os.environ.get("PRAXYS_DB_POOL_SIZE", "5"))
_PG_MAX_OVERFLOW = int(os.environ.get("PRAXYS_DB_MAX_OVERFLOW", "5"))
_PG_POOL_RECYCLE = int(os.environ.get("PRAXYS_DB_POOL_RECYCLE", "1800"))

# AAD scope for Azure Database for PostgreSQL Entra (Managed Identity) auth.
# https://learn.microsoft.com/azure/postgresql/flexible-server/how-to-configure-sign-in-azure-ad-authentication
_AAD_DB_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
_entra_token_cache: dict[str, object] = {"token": None, "expires_on": 0.0}


def _attach_sqlite_pragmas(engine_obj) -> None:
    """Attach a connect listener that applies _SQLITE_PRAGMAS to each connection.

    No-op for non-SQLite engines (so the Postgres migration drops in without
    code changes). PRAGMA journal_mode is also a no-op against ``:memory:``
    databases used in tests, which is fine.
    """
    if engine_obj.dialect.name != "sqlite":
        return

    # AsyncEngine wraps a sync core; DBAPI events live on the sync side.
    @event.listens_for(getattr(engine_obj, "sync_engine", engine_obj), "connect")
    def _apply_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            for pragma, value in _SQLITE_PRAGMAS:
                cursor.execute(f"PRAGMA {pragma}={value}")
        finally:
            cursor.close()


def _uses_entra_auth() -> bool:
    """True when the Postgres password should be a short-lived AAD token."""
    return os.environ.get("PRAXYS_DB_AUTH", "").strip().lower() == "entra"


def _entra_db_token() -> str:
    """Return a cached Azure AD access token for the Postgres AAD scope.

    Uses the App Service system-assigned managed identity in production
    (``WEBSITE_SITE_NAME`` present) and DefaultAzureCredential elsewhere, so
    no DB password lives in app settings. Tokens are cached until ~5 min
    before expiry.
    """
    import time

    now = time.time()
    tok = _entra_token_cache.get("token")
    exp = float(_entra_token_cache.get("expires_on") or 0.0)
    if tok and exp - now > 300:
        return str(tok)

    client_id = os.environ.get("AZURE_CLIENT_ID")
    if os.environ.get("WEBSITE_SITE_NAME"):
        from azure.identity import ManagedIdentityCredential

        cred = (
            ManagedIdentityCredential(client_id=client_id)
            if client_id
            else ManagedIdentityCredential()
        )
    else:
        from azure.identity import DefaultAzureCredential

        cred = DefaultAzureCredential()
    access = cred.get_token(_AAD_DB_SCOPE)
    _entra_token_cache["token"] = access.token
    _entra_token_cache["expires_on"] = float(access.expires_on)
    return access.token


def _attach_entra_token(engine_obj) -> None:
    """Inject a fresh AAD token as the DB password on each new connection."""
    if not _uses_entra_auth():
        return
    target = getattr(engine_obj, "sync_engine", engine_obj)

    @event.listens_for(target, "do_connect")
    def _provide_token(_dialect, _conn_rec, _cargs, cparams):
        cparams["password"] = _entra_db_token()


def get_data_dir() -> str:
    """Return the data directory path (configurable via DATA_DIR env var)."""
    return os.environ.get(
        "DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")
    )


_POSTGRES_DRIVER = "postgresql+psycopg"


def _normalize_db_url(raw: str) -> str:
    """Normalize a user-supplied DATABASE_URL into a SQLAlchemy URL.

    - ``postgres://`` and driver-less ``postgresql://`` become
      ``postgresql+psycopg://`` (psycopg3 backs both sync and async engines).
    - URLs that already name a driver (``postgresql+asyncpg``, ``sqlite``,
      etc.) are returned unchanged.
    """
    raw = raw.strip()
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        raw = _POSTGRES_DRIVER + "://" + raw[len("postgresql://"):]
    return raw


def _configured_db_url() -> str | None:
    """Return the normalized configured DB URL, or None to use the SQLite default."""
    for var in ("PRAXYS_DATABASE_URL", "DATABASE_URL"):
        val = os.environ.get(var)
        if val and val.strip():
            return _normalize_db_url(val)
    return None


def get_database_url() -> str:
    """Return the sync database URL (Postgres when configured, else SQLite file)."""
    configured = _configured_db_url()
    if configured:
        return configured
    data_dir = get_data_dir()
    db_path = os.path.join(data_dir, "trainsight.db")
    return f"sqlite:///{db_path}"


def get_async_database_url() -> str:
    """Return the async database URL derived from get_database_url()."""
    sync_url = get_database_url()
    if sync_url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + sync_url[len("sqlite:///"):]
    # psycopg3 supports async engines with the same driver name.
    return sync_url


def is_postgres() -> bool:
    """True when the active engine targets PostgreSQL."""
    return make_url(get_database_url()).get_backend_name() == "postgresql"


def _make_sync_engine(url: str):
    """Build a sync Engine appropriate for the URL's dialect."""
    backend = make_url(url).get_backend_name()
    if backend == "sqlite":
        eng = create_engine(url, connect_args={"check_same_thread": False})
        _attach_sqlite_pragmas(eng)
        return eng
    eng = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=_PG_POOL_SIZE,
        max_overflow=_PG_MAX_OVERFLOW,
        pool_recycle=_PG_POOL_RECYCLE,
    )
    _attach_entra_token(eng)
    return eng


def _make_async_engine(url: str):
    """Build an async Engine appropriate for the URL's dialect."""
    backend = make_url(url).get_backend_name()
    if backend == "sqlite":
        eng = create_async_engine(url, connect_args={"check_same_thread": False})
        _attach_sqlite_pragmas(eng)
        return eng
    eng = create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=_PG_POOL_SIZE,
        max_overflow=_PG_MAX_OVERFLOW,
        pool_recycle=_PG_POOL_RECYCLE,
    )
    _attach_entra_token(eng)
    return eng


# Module-level engine/session singletons (initialized lazily)
engine = None
SessionLocal = None
async_engine = None
AsyncSessionLocal = None


def _skip_migrations() -> bool:
    return os.environ.get("PRAXYS_SKIP_MIGRATIONS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def dispose_engines() -> None:
    """Dispose the sync + async engine pools and clear the singletons.

    Closes every pooled DB connection so PostgreSQL frees the backend at once,
    instead of leaving it idle until TCP-keepalive reap. Called before any
    re-initialization (so a forced init cannot orphan a live pool). For the
    await-correct shutdown path use dispose_engines_async(). Best-effort;
    never raises.

    Background: abandoned pools accumulated as idle "zombie" backends across
    container recycles and per-tick init_db() calls, exhausting the Burstable
    server's small max_connections and 500ing every data endpoint (2026-07-05
    outage). See docs/ops/incident-response.md.
    """
    global engine, SessionLocal, async_engine, AsyncSessionLocal
    if engine is not None:
        try:
            engine.dispose()
        except Exception:
            logger.debug("sync engine dispose failed", exc_info=True)
    if async_engine is not None:
        try:
            # AsyncEngine wraps a sync core; disposing that core closes the
            # pool synchronously (fine from sync callers and tests).
            async_engine.sync_engine.dispose()
        except Exception:
            logger.debug("async engine dispose failed", exc_info=True)
    engine = None
    SessionLocal = None
    async_engine = None
    AsyncSessionLocal = None


async def dispose_engines_async() -> None:
    """Await-correct pool disposal for the FastAPI lifespan shutdown.

    Uses ``await async_engine.dispose()`` so the async (psycopg3) pool closes
    on the running event loop, then disposes the sync pool. Releasing pools on
    shutdown stops abandoned connections from lingering as idle "zombie"
    backends after a container recycle (2026-07-05 outage).
    """
    global engine, SessionLocal, async_engine, AsyncSessionLocal
    if async_engine is not None:
        try:
            await async_engine.dispose()
        except Exception:
            logger.debug("async engine dispose failed", exc_info=True)
    if engine is not None:
        try:
            engine.dispose()
        except Exception:
            logger.debug("sync engine dispose failed", exc_info=True)
    engine = None
    SessionLocal = None
    async_engine = None
    AsyncSessionLocal = None


def init_db(force: bool = False):
    """Initialize sync and async database engines and ensure the schema exists.

    Idempotent: once the engines exist this is a no-op, so hot paths that only
    need to guarantee initialization (the sync scheduler's per-tick call, the
    get_db / get_async_db fallbacks) do not rebuild the pools or re-run
    migrations. Rebuilding on every scheduler tick orphaned a pool each time
    and was a root cause of the 2026-07-05 connection-exhaustion outage. Pass
    ``force=True`` to rebuild (disposing the previous pools first); tests that
    repoint DATA_DIR at a fresh database null the module globals, same effect.
    """
    global engine, SessionLocal, async_engine, AsyncSessionLocal

    if not force and SessionLocal is not None and engine is not None:
        return

    # Drop any previous / half-initialized pool before rebuilding so a forced
    # re-init cannot leak the old connections.
    dispose_engines()

    url = get_database_url()
    async_url = get_async_database_url()
    backend = make_url(url).get_backend_name()

    # Ensure the SQLite data directory exists.
    if backend == "sqlite":
        db_path = url.split("sqlite:///", 1)[-1]
        if db_path and db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    # Sync engine (for pandas read_sql, data loading, migration)
    engine = _make_sync_engine(url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Async engine (for FastAPI-Users)
    async_engine = _make_async_engine(async_url)
    AsyncSessionLocal = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    _ensure_schema(engine, backend)
    _run_startup_db_check(engine, backend)


def _ensure_schema(engine_obj, backend: str) -> None:
    """Create / migrate the schema for the active backend.

    SQLite (dev / tests) uses ``create_all`` — fast and dependency-free. On
    PostgreSQL, Alembic owns schema evolution (baseline + future revisions),
    replacing the legacy hand-maintained ``ALTER TABLE`` list.
    """
    if _skip_migrations():
        return
    if backend == "sqlite":
        Base.metadata.create_all(bind=engine_obj)
        return
    _run_alembic_upgrade(engine_obj)


def _run_alembic_upgrade(engine_obj) -> None:
    """Run ``alembic upgrade head`` under a Postgres advisory lock.

    The advisory lock serializes concurrent workers/instances so only one
    applies pending migrations; the rest block briefly, then no-op.
    """
    from alembic import command
    from alembic.config import Config

    ini_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini")
    cfg = Config(ini_path)
    # Advisory-lock key: arbitrary constant shared by all workers ("prax").
    lock_key = 0x70726178
    lock_conn = engine_obj.connect()
    try:
        lock_conn.exec_driver_sql(f"SELECT pg_advisory_lock({lock_key})")
        logger.info("Running Alembic migrations (upgrade head)")
        command.upgrade(cfg, "head")
        logger.info("Alembic migrations up to date")
    finally:
        try:
            lock_conn.exec_driver_sql(f"SELECT pg_advisory_unlock({lock_key})")
        except Exception:
            logger.debug("pg_advisory_unlock failed", exc_info=True)
        lock_conn.close()


def _run_startup_db_check(engine_obj, backend: str) -> None:
    """Cheap DB integrity / connectivity check at startup (issue #351).

    - SQLite: ``PRAGMA quick_check`` (bounded; not full integrity_check on the
      ~230 MB file) catches ``database disk image is malformed`` before reads
      start 500ing.
    - PostgreSQL: ``SELECT 1`` confirms the connection is live.

    Non-fatal by design: a failure logs ERROR + emits telemetry (so it pages
    oncall) and lets the readiness probe report unhealthy, rather than
    crashing the process — which would remove our ability to serve the
    readiness signal at all.
    """
    detail = ""
    try:
        with engine_obj.connect() as conn:
            if backend == "sqlite":
                row = conn.exec_driver_sql("PRAGMA quick_check").fetchone()
                detail = (row[0] if row else "") or ""
                ok = detail.strip().lower() == "ok"
            else:
                conn.exec_driver_sql("SELECT 1")
                ok = True
    except Exception as exc:
        logger.error("Database startup check errored (%s): %s", backend, exc, exc_info=True)
        _emit_db_health(status="check_error", backend=backend)
        return

    if ok:
        logger.info("Database startup check OK (%s)", backend)
    else:
        logger.error("Database integrity check FAILED (%s): quick_check=%r", backend, detail)
        _emit_db_health(status="integrity_failed", backend=backend)


def _emit_db_health(*, status: str, backend: str) -> None:
    """Best-effort telemetry emit; never raises."""
    try:
        from api.telemetry import record_db_health

        record_db_health(status=status, backend=backend)
    except Exception:
        logger.debug("record_db_health emit failed", exc_info=True)


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