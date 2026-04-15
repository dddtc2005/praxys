"""Credential encryption using envelope encryption.

Production: Per-user DEK wrapped by Azure Key Vault master key.
Development: Per-user DEK encrypted with a local Fernet key (from env var).
"""
import logging
import os

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class CredentialVault:
    """Envelope encryption vault with Azure Key Vault or local Fernet fallback."""

    def __init__(self):
        self.key_vault_url = os.environ.get("KEY_VAULT_URL")
        self.key_name = os.environ.get("KEY_VAULT_KEY_NAME", "trainsight-master-key")
        self._crypto_client = None
        self._local_key = None

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
        local_key = os.environ.get("TRAINSIGHT_LOCAL_ENCRYPTION_KEY")
        if not local_key:
            local_key = Fernet.generate_key().decode()
            logger.warning(
                "No encryption key configured. Generated ephemeral key "
                "(credentials will NOT survive restart). "
                "Set TRAINSIGHT_LOCAL_ENCRYPTION_KEY for persistence."
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

    def decrypt(self, encrypted_data: bytes, wrapped_dek: bytes) -> str:
        """Decrypt data using wrapped DEK."""
        if self._crypto_client:
            from azure.keyvault.keys.crypto import KeyWrapAlgorithm

            result = self._crypto_client.unwrap_key(
                KeyWrapAlgorithm.rsa_oaep, wrapped_dek
            )
            dek = result.key
        else:
            dek = Fernet(self._local_key).decrypt(wrapped_dek)

        return Fernet(dek).decrypt(encrypted_data).decode()


# Module-level singleton
_vault = None


def get_vault() -> CredentialVault:
    """Get or create the module-level CredentialVault singleton."""
    global _vault
    if _vault is None:
        _vault = CredentialVault()
    return _vault
