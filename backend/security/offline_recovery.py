"""Versioned encrypted backup-key escrow for disposable offline verification.

A recovery bundle deliberately contains no signing private key, MFA key,
Django secret or account credential. The recovery secret is a separate
random 256-bit value, not a human-chosen password. Never log either secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import warnings
import getpass
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from security.backup_service import (
    BackupError, BackupKeyUnavailable, _atomic_write_bytes,
    _assert_backup_destination_is_external, verify_encrypted_database_backup,
)

MAGIC = b"HBR1"
DOMAIN = b"HESABDARI-OFFLINE-RECOVERY-V1\x00"
MAX_BUNDLE_BYTES = 4096
_KEY_ID = re.compile(r"[A-Za-z0-9._-]{1,80}")
_HEX_256 = re.compile(r"[0-9a-fA-F]{64}")


def parse_recovery_secret(value):
    if not isinstance(value, str) or not _HEX_256.fullmatch(value):
        raise BackupError("recovery secret must be 64 hexadecimal characters from a secure random generator")
    return bytes.fromhex(value)


def prompt_secret(prompt):
    # getpass may otherwise fall back to echoed stdin on unsupported terminals.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
            raise BackupError("secure local secret entry is required") from None


def _validate_id(value):
    if not isinstance(value, str) or not _KEY_ID.fullmatch(value):
        raise BackupError("recovery key identifier is invalid")
    return value


def _validate_secret(secret):
    if not isinstance(secret, bytes) or len(secret) != 32:
        raise BackupError("a separate random 256-bit recovery secret is required")


def _key_bytes(value):
    if not isinstance(value, bytes) or len(value) != 32:
        raise BackupKeyUnavailable("recovery material is unavailable or invalid")
    return value


@dataclass(frozen=True, repr=False)
class RecoveryVerificationProvider:
    """Decrypt and verify only; never usable as an active signing provider."""
    encryption_id: str
    signing_id: str
    _encryption: bytes
    _public: bytes

    def get_backup_encryption_key(self, key_id):
        if key_id != self.encryption_id:
            raise BackupKeyUnavailable("backup key identifier is not covered by this recovery bundle")
        return self._encryption

    def get_checkpoint_signing_public_key(self, key_id):
        if key_id != self.signing_id:
            raise BackupKeyUnavailable("checkpoint trust identifier is not covered by this recovery bundle")
        return self._public


def create_recovery_bundle(destination, *, provider, recovery_secret,
                           encryption_id, signing_id):
    """Publish encrypted material once, using explicitly selected retained keys.

    Authorization and audit belong to the local owner command. This internal
    primitive never exports signing private material or uses an active-key fallback.
    """
    _validate_secret(recovery_secret)
    encryption_id = _validate_id(encryption_id)
    signing_id = _validate_id(signing_id)
    destination = Path(destination).expanduser()
    _assert_backup_destination_is_external(destination.parent)
    try:
        encryption = _key_bytes(provider.get_backup_encryption_key(encryption_id))
        public = _key_bytes(provider.get_checkpoint_signing_public_key(signing_id))
    except Exception as exc:
        raise BackupKeyUnavailable("selected recovery material could not be loaded") from exc
    if hmac.compare_digest(encryption, recovery_secret):
        raise BackupError("recovery secret must be independent of the backup encryption key")
    payload = json.dumps({
        "encryption_id": encryption_id,
        "signing_id": signing_id,
        "encryption": base64.b64encode(encryption).decode("ascii"),
        "public": base64.b64encode(public).decode("ascii"),
    }, sort_keys=True, separators=(",", ":")).encode("ascii")
    nonce = os.urandom(12)
    header = MAGIC + nonce
    artifact = header + AESGCM(recovery_secret).encrypt(nonce, payload, DOMAIN + header)
    _atomic_write_bytes(destination, artifact)
    return {
        "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        "trusted_public_sha256": hashlib.sha256(public).hexdigest(),
        "encryption_id": encryption_id,
        "signing_id": signing_id,
    }


def open_recovery_bundle(path, *, recovery_secret, trusted_public_sha256):
    _validate_secret(recovery_secret)
    if not isinstance(trusted_public_sha256, str) or not _HEX_256.fullmatch(trusted_public_sha256):
        raise BackupError("independently recorded public-key SHA-256 fingerprint is required")
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise BackupError("recovery bundle must be a regular non-symlink file")
    try:
        with path.open("rb") as stream:
            artifact = stream.read(MAX_BUNDLE_BYTES + 1)
        if len(artifact) > MAX_BUNDLE_BYTES or len(artifact) < 33 or artifact[:4] != MAGIC:
            raise BackupError("recovery bundle format or size is invalid")
        header = artifact[:16]
        plaintext = AESGCM(recovery_secret).decrypt(header[4:], artifact[16:], DOMAIN + header)
        payload = json.loads(plaintext)
        if not isinstance(payload, dict) or set(payload) != {"encryption_id", "signing_id", "encryption", "public"}:
            raise BackupError("recovery bundle payload is invalid")
        encryption_id = _validate_id(payload["encryption_id"])
        signing_id = _validate_id(payload["signing_id"])
        encryption = _key_bytes(base64.b64decode(payload["encryption"], validate=True))
        public = _key_bytes(base64.b64decode(payload["public"], validate=True))
    except BackupError:
        raise
    except InvalidTag:
        raise BackupError("recovery bundle authentication failed") from None
    except (OSError, ValueError, TypeError):
        raise BackupError("recovery bundle cannot be decoded") from None
    if not hmac.compare_digest(hashlib.sha256(public).hexdigest(), trusted_public_sha256.lower()):
        raise BackupError("recovered checkpoint public key does not match independent trust fingerprint")
    return RecoveryVerificationProvider(encryption_id, signing_id, encryption, public)


def verify_offline_recovery(*, backup_path, checkpoint_path, bundle_path,
                            recovery_secret, trusted_public_sha256, vendor,
                            restore_database_config=None, trusted_checkpoint_sha256=None):
    """Verify into disposable storage without querying or mutating an ERP user DB.

    The PostgreSQL target must be a separately authorized isolated server.
    No database is published or activated and no credentials are changed.
    """
    if vendor not in ("sqlite", "postgresql"):
        raise BackupError("explicit recovery database engine is required")
    if vendor == "postgresql":
        if (not isinstance(restore_database_config, dict)
                or restore_database_config.get("HOST") != "127.0.0.1"
                or not all(restore_database_config.get(k) for k in ("NAME", "USER", "PASSWORD", "PORT"))):
            raise BackupError("explicit isolated loopback PostgreSQL restore configuration is required")
    elif restore_database_config is not None:
        raise BackupError("SQLite recovery does not accept a server configuration")
    provider = open_recovery_bundle(bundle_path, recovery_secret=recovery_secret,
                                    trusted_public_sha256=trusted_public_sha256)
    return verify_encrypted_database_backup(
        backup_path, checkpoint_path, provider=provider, expected_vendor=vendor,
        restore_database_config=restore_database_config,
        trusted_checkpoint_sha256=trusted_checkpoint_sha256,
    )
