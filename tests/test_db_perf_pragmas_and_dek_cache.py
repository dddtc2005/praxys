"""Perf-critical tuning: SQLite pragmas + per-DEK unwrap cache.

These two changes target the App Service / Azure Files I/O bottleneck and
the per-Key-Vault-call latency respectively. Both are easy to regress
silently (the wrong default journal mode just *works*; a stale cached DEK
produces correct ciphertext that decrypts cleanly), so we lock the
behaviour with explicit assertions.
"""
import os
import tempfile

import pytest
from sqlalchemy import create_engine, text

from db.crypto import CredentialVault
from db.session import _attach_sqlite_pragmas


@pytest.fixture
def file_backed_engine():
    """File-backed SQLite engine — required because ``:memory:`` ignores
    PRAGMA journal_mode (returns 'memory') and would mask a regression.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    eng = create_engine(f"sqlite:///{path}")
    _attach_sqlite_pragmas(eng)
    try:
        yield eng
    finally:
        eng.dispose()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except OSError:
                pass


def test_journal_mode_is_wal(file_backed_engine):
    with file_backed_engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert mode == "wal", f"Expected WAL journal mode, got {mode!r}"


def test_synchronous_is_normal(file_backed_engine):
    with file_backed_engine.connect() as conn:
        # PRAGMA synchronous returns int: 0=OFF, 1=NORMAL, 2=FULL, 3=EXTRA
        sync = conn.execute(text("PRAGMA synchronous")).scalar()
    assert sync == 1, f"Expected synchronous=NORMAL (1), got {sync}"


def test_temp_store_is_memory(file_backed_engine):
    with file_backed_engine.connect() as conn:
        # 0=DEFAULT, 1=FILE, 2=MEMORY
        ts = conn.execute(text("PRAGMA temp_store")).scalar()
    assert ts == 2, f"Expected temp_store=MEMORY (2), got {ts}"


def test_busy_timeout_is_set(file_backed_engine):
    with file_backed_engine.connect() as conn:
        bt = conn.execute(text("PRAGMA busy_timeout")).scalar()
    assert bt >= 5000, f"Expected busy_timeout >= 5000ms, got {bt}"


def test_pragmas_apply_to_every_new_connection(file_backed_engine):
    """Connection pool may hand out a fresh connection — pragmas must be
    re-applied via the listener, not relied on as session-scoped state.
    """
    for _ in range(3):
        with file_backed_engine.connect() as conn:
            assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_listener_is_no_op_for_non_sqlite(monkeypatch):
    """The function must short-circuit on non-SQLite engines so a future
    Postgres / Azure SQL migration drops in without throwing PRAGMA at the
    server. We simulate by patching the dialect name; the pragma list is
    SQLite-only syntax and would fail elsewhere.
    """
    eng = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(eng.dialect, "name", "postgresql")
    # Should not raise even though "postgresql" doesn't support our PRAGMAs.
    _attach_sqlite_pragmas(eng)


def test_unwrap_dek_is_cached(monkeypatch):
    """Second decrypt of the same wrapped_dek must not re-call unwrap_key."""
    monkeypatch.delenv("KEY_VAULT_URL", raising=False)
    monkeypatch.setenv("PRAXYS_LOCAL_ENCRYPTION_KEY", "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=")
    vault = CredentialVault()

    encrypted, wrapped = vault.encrypt("hello world")

    # Sanity: round-trip works.
    assert vault.decrypt(encrypted, wrapped) == "hello world"

    # Re-decrypt: should hit the cache. Wrap the underlying Fernet so we
    # can count calls to .decrypt(wrapped_dek) — the local-fallback's
    # equivalent of unwrap_key().
    from cryptography.fernet import Fernet
    real_fernet_decrypt = Fernet.decrypt
    call_count = {"n": 0}

    def counting_decrypt(self, token, *args, **kwargs):
        # Count only DEK unwraps — those use the master local_key, which
        # has the same value vault._local_key. Distinguish from the
        # data-payload Fernet by checking the token length: wrapped DEKs
        # are short Fernet tokens of an ~44-byte key, payloads are longer.
        if token == wrapped:
            call_count["n"] += 1
        return real_fernet_decrypt(self, token, *args, **kwargs)

    monkeypatch.setattr(Fernet, "decrypt", counting_decrypt)

    for _ in range(5):
        assert vault.decrypt(encrypted, wrapped) == "hello world"

    assert call_count["n"] == 0, (
        f"Expected 0 unwrap calls after warmup, got {call_count['n']}"
    )


def test_unwrap_dek_cache_is_per_wrapped_value(monkeypatch):
    """Different wrapped DEKs must not collide in the cache — otherwise we
    risk decrypting one user's data with another's key."""
    monkeypatch.delenv("KEY_VAULT_URL", raising=False)
    monkeypatch.setenv("PRAXYS_LOCAL_ENCRYPTION_KEY", "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=")
    vault = CredentialVault()

    enc_a, wrap_a = vault.encrypt("alice's secret")
    enc_b, wrap_b = vault.encrypt("bob's secret")

    # Different DEKs are generated per encrypt() call, so wrap_a != wrap_b.
    assert wrap_a != wrap_b
    assert vault.decrypt(enc_a, wrap_a) == "alice's secret"
    assert vault.decrypt(enc_b, wrap_b) == "bob's secret"
    # Cache populated with both.
    assert wrap_a in vault._dek_cache and wrap_b in vault._dek_cache


def test_unwrap_dek_cache_evicts_lru(monkeypatch):
    """Cap is enforced so the cache cannot grow unbounded."""
    monkeypatch.delenv("KEY_VAULT_URL", raising=False)
    monkeypatch.setenv("PRAXYS_LOCAL_ENCRYPTION_KEY", "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=")
    import db.crypto as crypto_mod
    monkeypatch.setattr(crypto_mod, "_DEK_CACHE_MAX_ENTRIES", 4)
    vault = CredentialVault()

    payloads = [vault.encrypt(f"secret-{i}") for i in range(6)]
    for enc, wrap in payloads:
        vault.decrypt(enc, wrap)

    assert len(vault._dek_cache) == 4
    # The first two should have been evicted (LRU = oldest end).
    assert payloads[0][1] not in vault._dek_cache
    assert payloads[1][1] not in vault._dek_cache
    # The most recent four should still be there.
    for enc, wrap in payloads[2:]:
        assert wrap in vault._dek_cache
