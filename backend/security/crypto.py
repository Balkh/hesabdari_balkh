"""Authenticated encryption for sensitive security credentials.

W0-2C contract: AES-256-GCM, 96-bit nonce, key material supplied by an
OS-backed KeyProvider and never persisted in the application database.
This module deliberately contains no filesystem, environment-variable,
or plaintext-key fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


NONCE_BYTES = 12
KEY_BYTES = 32
FORMAT_VERSION = 1


from security.errors import KeyUnavailableError, SecretDecryptionError


class KeyProvider(Protocol):
    """OS-backed provider contract; implementations must fail closed."""

    def active_key_id(self) -> str: ...
    def get_key(self, key_id: str) -> bytes: ...


@dataclass(frozen=True)
class EncryptedSecret:
    version: int
    key_id: str
    nonce: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)


def _aad(version: int, key_id: str, purpose: str, subject_id: str) -> bytes:
    if not purpose or not subject_id or not key_id:
        raise ValueError("purpose, subject_id and key_id are required")
    # Length-prefixed components avoid ambiguous delimiter concatenation.
    parts = (str(version), key_id, purpose, subject_id)
    return b"hesabdari-balkh|w0-2c|" + b"".join(
        len(part.encode("utf-8")).to_bytes(4, "big") + part.encode("utf-8")
        for part in parts
    )


def _validated_key(provider: KeyProvider, key_id: str) -> bytes:
    try:
        key = provider.get_key(key_id)
    except Exception:
        raise KeyUnavailableError("security encryption key is unavailable") from None
    if not isinstance(key, bytes) or len(key) != KEY_BYTES:
        raise KeyUnavailableError("security encryption key is invalid") from None
    return key


def encrypt_secret(
    plaintext: bytes,
    *,
    purpose: str,
    subject_id: str,
    provider: KeyProvider,
) -> EncryptedSecret:
    """Encrypt bytes using the provider's active AES-256 key."""
    if not isinstance(plaintext, bytes):
        raise TypeError("plaintext must be bytes")
    key_id = provider.active_key_id()
    if not isinstance(key_id, str) or not key_id:
        raise KeyUnavailableError("active security encryption key is unavailable")
    key = _validated_key(provider, key_id)
    nonce = os.urandom(NONCE_BYTES)
    if len(nonce) != NONCE_BYTES:
        raise RuntimeError("operating-system nonce generation failed")
    aad = _aad(FORMAT_VERSION, key_id, purpose, subject_id)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    return EncryptedSecret(FORMAT_VERSION, key_id, nonce, ciphertext)


def decrypt_secret(
    envelope: EncryptedSecret,
    *,
    purpose: str,
    subject_id: str,
    provider: KeyProvider,
) -> bytes:
    """Decrypt only when key, version, identity binding and GCM tag validate."""
    if not isinstance(envelope, EncryptedSecret):
        raise SecretDecryptionError("encrypted credential envelope is invalid")
    if envelope.version != FORMAT_VERSION:
        raise SecretDecryptionError("encrypted credential version is unsupported")
    if len(envelope.nonce) != NONCE_BYTES or len(envelope.ciphertext) < 16:
        raise SecretDecryptionError("encrypted credential envelope is malformed")
    key = _validated_key(provider, envelope.key_id)
    aad = _aad(envelope.version, envelope.key_id, purpose, subject_id)
    try:
        return AESGCM(key).decrypt(envelope.nonce, envelope.ciphertext, aad)
    except InvalidTag:
        raise SecretDecryptionError(
            "encrypted credential authentication failed"
        ) from None
