"""Credential encryption using envelope encryption.

Production: Per-user DEK wrapped by Azure Key Vault master key.
Development: Per-user DEK encrypted with a local Fernet key (from env var).
"""
import logging
import os
import threading
from collections import OrderedDict

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# Cap the in-memory unwrapped-DEK cache. One DEK per (user, platform) pair,
# so a couple hundred entries covers a long tail of users without leaking
# unbounded memory if wrapped_dek somehow churns. Eviction is plain LRU.
_DEK_CACHE_MAX_ENTRIES = 256


class CredentialVault:
    """Envelope encryption vault with Azure Key Vault or local Fernet fallback."""

    def __init__(self):
        self.key_vault_url = os.environ.get("KEY_VAULT_URL")
        self.key_name = os.environ.get("KEY_VAULT_KEY_NAME", "trainsight-master-key")
        self._crypto_client = None
        self._local_key = None
        # Cache of wrapped_dek bytes -> unwrapped DEK bytes. The wrapped form
        # is stable in the DB until the master key is rotated, so caching the
        # unwrap output saves a Key Vault round-trip per credential decrypt.
        # That call costs ~50ms p50 / 200ms p95 in production; the sync
        # scheduler triggers it dozens of times an hour. The DEK never
        # touches disk and lives only in this worker's memory.
        self._dek_cache: OrderedDict[bytes, bytes] = OrderedDict()
        self._dek_cache_lock = threading.Lock()

        if self.key_vault_url:
            self._init_key_vault()
        else:
            self._init_local()

    def _init_key_vault(self):
        """Initialize Azure Key Vault client for production envelope encryption."""
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.keys import KeyClient

            credential = DefaultAzureCredential()
            key_client = KeyClient(
                vault_url=self.key_vault_url, credential=credential
            )
            key = key_client.get_key(self.key_name)

            from azure.keyvault.keys.crypto import CryptographyClient

            self._crypto_client = CryptographyClient(key, credential=credential)
            logger.info("Using Azure Key Vault for credential encryption")
        except Exception as e:
            logger.warning("Key Vault init failed, falling back to local: %s", e)
            self._init_local()

    def _init_local(self):
        """Initialize local Fernet key for development envelope encryption."""
        from api.env_compat import getenv_compat
        local_key = getenv_compat("LOCAL_ENCRYPTION_KEY")
        if not local_key:
            local_key = Fernet.generate_key().decode()
            logger.warning(
                "PRAXYS_LOCAL_ENCRYPTION_KEY not set! Generated ephemeral key — "
                "platform credentials will NOT survive restart. "
                "Run: set PRAXYS_LOCAL_ENCRYPTION_KEY=<key> to persist credentials.",
            )
        self._local_key = (
            local_key.encode() if isinstance(local_key, str) else local_key
        )
        logger.info("Using local Fernet key for credential encryption")

    def encrypt(self, plaintext: str) -> tuple[bytes, bytes]:
        """Encrypt plaintext. Returns (encrypted_data, wrapped_dek)."""
        dek = Fernet.generate_key()
        encrypted_data = Fernet(dek).encrypt(plaintext.encode())

        if self._crypto_client:
            from azure.keyvault.keys.crypto import KeyWrapAlgorithm

            result = self._crypto_client.wrap_key(KeyWrapAlgorithm.rsa_oaep, dek)
            wrapped_dek = result.encrypted_key
        else:
            wrapped_dek = Fernet(self._local_key).encrypt(dek)

        return encrypted_data, wrapped_dek

    def _unwrap_dek(self, wrapped_dek: bytes) -> bytes:
        """Return the raw DEK for ``wrapped_dek``, hitting the cache first.

        The cache is keyed on the wrapped form (which the DB owns). On a
        master-key rotation the wrapped values change, so old cache entries
        simply stop being looked up — no explicit invalidation needed.
        """
        with self._dek_cache_lock:
            cached = self._dek_cache.get(wrapped_dek)
            if cached is not None:
                self._dek_cache.move_to_end(wrapped_dek)
                return cached

        if self._crypto_client:
            from azure.keyvault.keys.crypto import KeyWrapAlgorithm

            result = self._crypto_client.unwrap_key(
                KeyWrapAlgorithm.rsa_oaep, wrapped_dek
            )
            dek = result.key
        else:
            dek = Fernet(self._local_key).decrypt(wrapped_dek)

        with self._dek_cache_lock:
            self._dek_cache[wrapped_dek] = dek
            self._dek_cache.move_to_end(wrapped_dek)
            while len(self._dek_cache) > _DEK_CACHE_MAX_ENTRIES:
                self._dek_cache.popitem(last=False)
        return dek

    def decrypt(self, encrypted_data: bytes, wrapped_dek: bytes) -> str:
        """Decrypt data using wrapped DEK."""
        dek = self._unwrap_dek(wrapped_dek)
        return Fernet(dek).decrypt(encrypted_data).decode()


# Module-level singleton
_vault = None


def get_vault() -> CredentialVault:
    """Get or create the module-level CredentialVault singleton."""
    global _vault
    if _vault is None:
        _vault = CredentialVault()
    return _vault
