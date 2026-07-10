"""One-time data migration: SQLite (trainsight.db) -> PostgreSQL (#360).

Copies every row from the legacy SQLite database into a PostgreSQL target,
preserving primary keys and the opaque Fernet-encrypted credential blobs
(``user_connections.encrypted_credentials`` / ``wrapped_dek``) byte-for-byte,
resets Postgres SERIAL sequences, and verifies row-count parity (and,
optionally, that the migrated credential blobs still decrypt).

Rows are streamed in bounded chunks (memory-safe for large tables such as
activity_samples), and orphaned user foreign keys left by SQLite's lack of FK
enforcement are cleaned during copy (nullable -> NULL, NOT NULL -> row skipped;
both reported). See praxys-run/praxys#366.

Usage:
    python -m scripts.migrate_sqlite_to_postgres \
        --sqlite /home/data/trainsight.db \
        --postgres "postgresql://user:pass@host:5432/praxys?sslmode=require" \
        [--wipe] [--no-schema] [--verify-decrypt] \
        [--skip-tables cache_revisions,dashboard_cache]

The target schema is created via Alembic (``upgrade head``) unless --no-schema.
Safe to re-run with --wipe (TRUNCATE target tables first). Regenerable cache
tables can be skipped with --skip-tables (they rebuild on first request).

Type handling: rows are read and written through the SQLAlchemy table objects
in ``db.models``, so SQLite's stored ISO date/datetime strings are parsed to
Python objects on read and bound as native types on write, and LargeBinary
blobs round-trip as raw bytes into Postgres ``bytea``.

See docs/ops/postgres-migration.md for the full cutover runbook.
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, func, insert, select

# Ensure repo root is importable when run as a file or module.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import Base  # noqa: E402

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _normalize_pg(url: str) -> str:
    """Force the psycopg3 driver on a Postgres URL (idempotent)."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _serial_id_tables() -> list[str]:
    """Names of tables whose integer ``id`` PK is a Postgres SERIAL sequence."""
    names: list[str] = []
    for table in Base.metadata.sorted_tables:
        col = table.columns.get("id")
        if (
            col is not None
            and col.primary_key
            and col.autoincrement in (True, "auto")
            and str(col.type).upper().startswith("INTEGER")
        ):
            names.append(table.name)
    return names


def _run_alembic(tgt_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    # env.py resolves the URL from db.session.get_database_url(); point it at
    # the target for the duration, then restore so we leave no global side
    # effect for the caller (or the test suite).
    prev_url = os.environ.get("PRAXYS_DATABASE_URL")
    prev_skip = os.environ.get("PRAXYS_SKIP_MIGRATIONS")
    os.environ["PRAXYS_DATABASE_URL"] = tgt_url
    os.environ["PRAXYS_SKIP_MIGRATIONS"] = ""
    try:
        cfg = Config(os.path.join(_REPO_ROOT, "alembic.ini"))
        command.upgrade(cfg, "head")
    finally:
        for key, prev in (("PRAXYS_DATABASE_URL", prev_url), ("PRAXYS_SKIP_MIGRATIONS", prev_skip)):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev
    print("target schema ensured via alembic upgrade head")


def _verify_decrypt(tgt) -> None:
    """Best-effort: confirm migrated credential blobs still decrypt.

    Requires the same encryption context as the source (PRAXYS_LOCAL_ENCRYPTION_KEY
    in dev, or Key Vault access in prod). The blobs are opaque columns, so a
    successful decrypt end-to-end proves the bytes survived the move.
    """
    from db.crypto import get_vault

    vault = get_vault()
    ok = fail = 0
    with tgt.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT id, encrypted_credentials, wrapped_dek FROM user_connections "
            "WHERE encrypted_credentials IS NOT NULL AND wrapped_dek IS NOT NULL"
        ).fetchall()
    for rid, enc, dek in rows:
        try:
            vault.decrypt(bytes(enc), bytes(dek))
            ok += 1
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"  connection id={rid}: DECRYPT FAILED: {exc}")
    print(f"decrypt verification: {ok} ok, {fail} failed (of {len(rows)} blob rows)")
    if fail:
        raise SystemExit("FAILED: some credential blobs did not decrypt after migration")


def migrate(
    sqlite_path: str,
    pg_url: str,
    *,
    wipe: bool = False,
    create_schema: bool = True,
    skip_tables: tuple[str, ...] = (),
    verify_decrypt: bool = False,
    batch: int = 1000,
) -> None:
    tgt_url = _normalize_pg(pg_url)
    src = create_engine(f"sqlite:///{sqlite_path}")
    tgt = create_engine(tgt_url)

    if create_schema:
        _run_alembic(tgt_url)

    tables = [t for t in Base.metadata.sorted_tables if t.name not in skip_tables]

    if wipe:
        with tgt.begin() as conn:
            names = ", ".join(t.name for t in reversed(tables))
            if names:
                conn.exec_driver_sql(f"TRUNCATE {names} RESTART IDENTITY CASCADE")
        print(f"wiped {len(tables)} target tables")

    # Referential integrity: SQLite does not enforce foreign keys, so the
    # source can hold rows whose user-FK points at a since-deleted user (e.g.
    # invitations.used_by). PostgreSQL enforces FKs, so orphans are cleaned on
    # copy: a *nullable* orphaned FK is set NULL; a NOT NULL orphaned FK row is
    # skipped. Both are reported. See praxys-run/praxys#366.
    with src.connect() as sconn:
        valid_users = {
            x[0] for x in sconn.exec_driver_sql("SELECT id FROM users").fetchall()
        }

    def _user_fk_cols(table) -> dict[str, bool]:
        """Return {col_name: is_nullable} for columns FK-referencing users.id."""
        out: dict[str, bool] = {}
        for col in table.columns:
            for fk in col.foreign_keys:
                ref = fk.column
                if ref.table.name == "users" and ref.name == "id":
                    out[col.name] = bool(col.nullable)
        return out

    print("copying rows (parent tables first)...")
    counts: dict[str, int] = {}
    nulled: dict[str, int] = {}
    skipped: dict[str, int] = {}
    with src.connect() as sconn:
        for table in tables:
            fk_cols = _user_fk_cols(table)
            inserted = 0
            # Stream in bounded chunks so a large table (e.g. ~900k
            # activity_samples) cannot exhaust memory on a small host.
            result = sconn.execute(select(table))
            while True:
                chunk = result.fetchmany(batch)
                if not chunk:
                    break
                rows = []
                for r in chunk:
                    row = dict(r._mapping)
                    drop = False
                    for col, nullable in fk_cols.items():
                        val = row.get(col)
                        if val is not None and val not in valid_users:
                            if nullable:
                                row[col] = None
                                key = f"{table.name}.{col}"
                                nulled[key] = nulled.get(key, 0) + 1
                            else:
                                drop = True
                                skipped[table.name] = skipped.get(table.name, 0) + 1
                                break
                    if not drop:
                        rows.append(row)
                if rows:
                    with tgt.begin() as tconn:
                        tconn.execute(insert(table), rows)
                    inserted += len(rows)
            counts[table.name] = inserted
            print(f"  {table.name}: {inserted} rows")
    if nulled:
        print(f"cleaned orphaned nullable FKs (set NULL): {nulled}")
    if skipped:
        print(f"skipped rows with orphaned NOT NULL FK: {skipped}")

    serial_tables = [t for t in _serial_id_tables() if t not in skip_tables]
    with tgt.begin() as conn:
        for name in serial_tables:
            conn.exec_driver_sql(
                f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                f"(SELECT COALESCE(MAX(id), 0) FROM {name}) + 1, false)"
            )
    print(f"reset {len(serial_tables)} SERIAL sequences")

    print("verifying row-count parity...")
    mismatches = 0
    with tgt.connect() as tconn:
        for table in tables:
            tgt_n = tconn.execute(select(func.count()).select_from(table)).scalar()
            src_n = counts[table.name]
            if tgt_n != src_n:
                mismatches += 1
                print(f"  {table.name}: inserted={src_n} tgt={tgt_n} MISMATCH")
            else:
                print(f"  {table.name}: inserted={src_n} tgt={tgt_n} OK")
    if mismatches:
        raise SystemExit(f"FAILED: {mismatches} table(s) row-count mismatch")

    if verify_decrypt:
        _verify_decrypt(tgt)

    print("MIGRATION COMPLETE: all tables match")


def main() -> None:
    p = argparse.ArgumentParser(description="Migrate Praxys SQLite -> PostgreSQL (#360)")
    p.add_argument("--sqlite", required=True, help="path to source trainsight.db")
    p.add_argument("--postgres", required=True, help="target Postgres DSN")
    p.add_argument("--wipe", action="store_true", help="TRUNCATE target tables before load")
    p.add_argument("--no-schema", action="store_true", help="assume target schema already migrated")
    p.add_argument("--verify-decrypt", action="store_true", help="verify credential blobs still decrypt")
    p.add_argument("--skip-tables", default="", help="comma-separated tables to skip (e.g. regenerable caches)")
    p.add_argument("--batch", type=int, default=1000)
    args = p.parse_args()

    if not os.path.exists(args.sqlite):
        raise SystemExit(f"source sqlite not found: {args.sqlite}")

    skip = tuple(s.strip() for s in args.skip_tables.split(",") if s.strip())
    migrate(
        args.sqlite,
        args.postgres,
        wipe=args.wipe,
        create_schema=not args.no_schema,
        skip_tables=skip,
        verify_decrypt=args.verify_decrypt,
        batch=args.batch,
    )


if __name__ == "__main__":
    main()