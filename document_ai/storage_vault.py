"""Secure Persistent Document Storage Vault for SahayAI (Step 5.4A).

Manages encrypted-at-rest storage of citizen documents in a dedicated private
vault directory outside public frontend assets using genuine Fernet authenticated
encryption (AES-128-CBC + HMAC-SHA256).
"""

import logging
import os
from pathlib import Path
from typing import Optional, Tuple
import uuid

from document_ai.extract_fields import PIIVault

logger = logging.getLogger(__name__)

DEFAULT_VAULT_DIR = "data/secure_vault/documents"


class DocumentStorageVault:
    """Manages encrypted file storage and retrieval for citizen documents."""

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        vault: Optional[PIIVault] = None,
    ):
        """Initialize the document storage vault.

        Args:
            storage_dir: Storage directory path. Defaults to data/secure_vault/documents
                         or SAHAY_DOCUMENT_STORAGE_DIR environment variable.
            vault: Optional PIIVault instance for authenticated encryption.
        """
        env_dir = os.environ.get("SAHAY_DOCUMENT_STORAGE_DIR", DEFAULT_VAULT_DIR)
        self.storage_dir = Path(storage_dir) if storage_dir else Path(env_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._vault = vault or PIIVault()

    @property
    def is_configured(self) -> bool:
        """Return True if the underlying encryption vault has an active key."""
        return self._vault.is_configured

    def _get_fernet(self):
        """Get an active Fernet instance or fail closed."""
        if not self._vault.is_configured or not self._vault._key:
            raise RuntimeError(
                "Document storage encryption unavailable: SAHAY_PII_ENCRYPTION_KEY is not configured. Failed closed."
            )
        from cryptography.fernet import Fernet
        return Fernet(self._vault._key)

    def _resolve_safe_path(self, storage_reference: str) -> Path:
        """Resolve storage reference to an absolute Path, strictly preventing path traversal."""
        if not storage_reference:
            raise ValueError("Storage reference cannot be empty.")

        # Defense-in-depth: Storage reference must be a single file component (no path separators)
        base_name = os.path.basename(storage_reference.replace("\\", "/"))
        if base_name != storage_reference or ".." in storage_reference:
            raise ValueError(f"Path traversal detected in storage reference: '{storage_reference}'")

        target_path = (self.storage_dir / base_name).resolve()
        storage_root = self.storage_dir.resolve()

        # Strict containment check
        if not str(target_path).startswith(str(storage_root)):
            raise ValueError(f"Storage path escapes vault directory: '{target_path}'")

        return target_path

    def store_file(
        self,
        file_bytes: bytes,
        original_filename: Optional[str] = None,
    ) -> Tuple[str, int]:
        """Encrypt and store an uploaded document at rest.

        Security Guarantees:
        - Fails closed if encryption key is not configured.
        - Generates a completely random UUID server-side storage filename.
        - Client filenames are never used for physical disk storage.
        - Physical file content is authenticated Fernet ciphertext.

        Args:
            file_bytes: Raw original document bytes.
            original_filename: Optional client filename (used only for metadata).

        Returns:
            Tuple of (storage_reference, raw_file_size_bytes).
        """
        if not file_bytes:
            raise ValueError("Cannot store empty file (0 bytes).")

        fernet = self._get_fernet()

        # Generate server-side random storage reference
        storage_ref = f"enc_{uuid.uuid4().hex}.vault"
        target_path = self._resolve_safe_path(storage_ref)

        try:
            # Encrypt raw file bytes using authenticated encryption
            ciphertext = fernet.encrypt(file_bytes)
            target_path.write_bytes(ciphertext)
            logger.info(
                "Encrypted and stored document in vault: ref=%s, raw_size=%d bytes, cipher_size=%d bytes",
                storage_ref,
                len(file_bytes),
                len(ciphertext),
            )
            return storage_ref, len(file_bytes)
        except Exception as exc:
            # Cleanup on failure
            if target_path.exists():
                try:
                    target_path.unlink()
                except OSError:
                    pass
            logger.error("Failed to store encrypted document: %s", exc)
            raise

    def file_exists(self, storage_reference: Optional[str]) -> bool:
        """Check if an encrypted file exists in the vault.

        Args:
            storage_reference: Stored vault reference name.

        Returns:
            True if file exists and is a regular file, False otherwise.
        """
        if not storage_reference:
            return False
        try:
            target_path = self._resolve_safe_path(storage_reference)
            return target_path.is_file()
        except Exception:
            return False

    def retrieve_file(self, storage_reference: str) -> bytes:
        """Retrieve and decrypt a stored document from the private vault.

        Args:
            storage_reference: Stored vault reference name.

        Returns:
            Decrypted raw document bytes.

        Raises:
            FileNotFoundError: If the stored file does not exist.
            RuntimeError: If encryption key is not configured or decryption fails.
        """
        target_path = self._resolve_safe_path(storage_reference)
        if not target_path.is_file():
            raise FileNotFoundError(f"Stored document file not found: {storage_reference}")

        fernet = self._get_fernet()

        try:
            ciphertext = target_path.read_bytes()
            decrypted = fernet.decrypt(ciphertext)
            return decrypted
        except Exception as exc:
            logger.error("Failed to decrypt stored document %s: %s", storage_reference, exc)
            raise RuntimeError(f"Document decryption failed: {exc}") from exc

    def delete_file(self, storage_reference: Optional[str]) -> bool:
        """Permanently delete an encrypted file from disk to prevent storage leaks.

        Args:
            storage_reference: Vault reference name.

        Returns:
            True if file existed and was deleted, False otherwise.
        """
        if not storage_reference:
            return False

        try:
            target_path = self._resolve_safe_path(storage_reference)
            if target_path.is_file():
                target_path.unlink()
                logger.info("Deleted encrypted document from vault: %s", storage_reference)
                return True
        except Exception as exc:
            logger.warning("Error deleting stored document file %s: %s", storage_reference, exc)

        return False

