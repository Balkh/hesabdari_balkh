"""Encrypted offline database backups and signed audit-chain checkpoints.

The service never invents or persists key material. It accepts a separate
OS-backed provider, encrypts backup snapshots with AES-256-GCM, signs
checkpoints with Ed25519, and restores only into disposable verification
databases. Missing key custody or database utilities fail closed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.module_loading import import_string

from security.audit_chain import (
    AuditChainVerificationError,
    assert_audit_trigger_schema,
    sqlite_replacement_guard_matches,
    verify_audit_chain,
    verify_audit_chain_records,
)
from security.models import AuditAction
from security.services import record_audit_event


BACKUP_MAGIC = b"HBK1"
BACKUP_FORMAT_VERSION = 1
GCM_NONCE_BYTES = 12
GCM_TAG_BYTES = 16
AES256_KEY_BYTES = 32
ED25519_KEY_BYTES = 32
MAX_KEY_ID_BYTES = 80
CHECKPOINT_SCHEMA = "hesabdari.audit-checkpoint.v1"
BACKUP_SCHEMA = "hesabdari.encrypted-database-backup.v1"
CHUNK_SIZE = 1024 * 1024


class BackupError(RuntimeError):
    """A backup, checkpoint, or disposable restore operation failed safely."""


class BackupKeyUnavailable(BackupError):
    """The independent backup/checkpoint key provider is unavailable."""


class BackupKeyProvider(Protocol):
    """Key contract; key material must live outside the database and employee profile."""

    def active_backup_encryption_key_id(self) -> str: ...
    def get_backup_encryption_key(self, key_id: str) -> bytes: ...
    def active_checkpoint_signing_key_id(self) -> str: ...
    def get_checkpoint_signing_private_key(self, key_id: str) -> bytes: ...
    def get_checkpoint_signing_public_key(self, key_id: str) -> bytes: ...


def load_backup_key_provider() -> BackupKeyProvider:
    """Load an explicitly configured provider; Windows defaults to Credential Manager."""
    provider_path = getattr(settings, "ERP_BACKUP_KEY_PROVIDER", None)
    if not provider_path and os.name == "nt":
        provider_path = "security.windows_key_provider.WindowsCredentialManagerKeyProvider"
    if not provider_path:
        raise BackupKeyUnavailable(
            "no independent backup key provider is configured; refusing plaintext or local-key fallback"
        )
    try:
        provider_type = import_string(provider_path)
        provider = provider_type()
        required = (
            "active_backup_encryption_key_id",
            "get_backup_encryption_key",
            "active_checkpoint_signing_key_id",
            "get_checkpoint_signing_private_key",
            "get_checkpoint_signing_public_key",
        )
        if any(not callable(getattr(provider, name, None)) for name in required):
            raise TypeError("provider does not implement the backup key contract")
        return provider
    except Exception as exc:
        if isinstance(exc, BackupKeyUnavailable):
            raise
        raise BackupKeyUnavailable(
            "independent backup key provider could not be loaded"
        ) from exc


def _key_id_bytes(key_id: str) -> bytes:
    if not isinstance(key_id, str) or not key_id:
        raise BackupKeyUnavailable("key identifier is missing")
    try:
        raw = key_id.encode("ascii")
    except UnicodeEncodeError:
        raise BackupKeyUnavailable("key identifier must be ASCII") from None
    if len(raw) > MAX_KEY_ID_BYTES:
        raise BackupKeyUnavailable("key identifier is too long")
    return raw


def _canonical_json_bytes(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _utc_now_text() -> str:
    return timezone.now().astimezone(dt_timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_bytes(path: str | Path, content: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def encrypt_backup_file(
    source_path: str | Path,
    destination_path: str | Path,
    *,
    provider: BackupKeyProvider,
) -> dict:
    """Encrypt a database dump as a versioned AES-256-GCM streaming envelope."""
    try:
        key_id = provider.active_backup_encryption_key_id()
        key = provider.get_backup_encryption_key(key_id)
    except Exception as exc:
        raise BackupKeyUnavailable("backup encryption key is unavailable") from exc
    if not isinstance(key, bytes) or len(key) != AES256_KEY_BYTES:
        raise BackupKeyUnavailable("backup encryption key must be exactly 32 bytes")

    key_id_raw = _key_id_bytes(key_id)
    nonce = os.urandom(GCM_NONCE_BYTES)
    header = (
        BACKUP_MAGIC
        + bytes([BACKUP_FORMAT_VERSION])
        + len(key_id_raw).to_bytes(2, "big")
        + key_id_raw
        + nonce
    )
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)

    target = Path(destination_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise BackupError("backup destination already exists; refusing to overwrite")
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output, Path(source_path).open("rb") as source:
            output.write(header)
            for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
                encrypted = encryptor.update(chunk)
                if encrypted:
                    output.write(encrypted)
            final = encryptor.finalize()
            if final:
                output.write(final)
            output.write(encryptor.tag)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise

    return {
        "path": str(target),
        "key_id": key_id,
        "sha256": sha256_file(target),
        "size": target.stat().st_size,
    }


def decrypt_backup_file(
    source_path: str | Path,
    destination_path: str | Path,
    *,
    provider: BackupKeyProvider,
) -> dict:
    """Authenticate and decrypt a backup to a private temporary restore file."""
    source_path = Path(source_path)
    destination_path = Path(destination_path)
    with source_path.open("rb") as source:
        prefix = source.read(7)
        if len(prefix) != 7 or prefix[:4] != BACKUP_MAGIC:
            raise BackupError("encrypted backup header is invalid")
        if prefix[4] != BACKUP_FORMAT_VERSION:
            raise BackupError("encrypted backup format version is unsupported")
        key_id_length = int.from_bytes(prefix[5:7], "big")
        if not 1 <= key_id_length <= MAX_KEY_ID_BYTES:
            raise BackupError("encrypted backup key identifier length is invalid")
        key_id_raw = source.read(key_id_length)
        nonce = source.read(GCM_NONCE_BYTES)
        if len(key_id_raw) != key_id_length or len(nonce) != GCM_NONCE_BYTES:
            raise BackupError("encrypted backup header is truncated")
        try:
            key_id = key_id_raw.decode("ascii")
        except UnicodeDecodeError:
            raise BackupError("encrypted backup key identifier is malformed") from None
        header = prefix + key_id_raw + nonce
        source.seek(0, os.SEEK_END)
        total_size = source.tell()
        payload_start = len(header)
        payload_end = total_size - GCM_TAG_BYTES
        if payload_end < payload_start:
            raise BackupError("encrypted backup is truncated")
        source.seek(payload_end)
        tag = source.read(GCM_TAG_BYTES)
        if len(tag) != GCM_TAG_BYTES:
            raise BackupError("encrypted backup authentication tag is missing")
        source.seek(payload_start)

    try:
        key = provider.get_backup_encryption_key(key_id)
    except Exception as exc:
        raise BackupKeyUnavailable("backup decryption key is unavailable") from exc
    if not isinstance(key, bytes) or len(key) != AES256_KEY_BYTES:
        raise BackupKeyUnavailable("backup decryption key must be exactly 32 bytes")

    decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
    decryptor.authenticate_additional_data(header)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        destination_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with source_path.open("rb") as source, os.fdopen(descriptor, "wb") as output:
            source.seek(payload_start)
            remaining = payload_end - payload_start
            while remaining:
                chunk = source.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise BackupError("encrypted backup ciphertext is truncated")
                remaining -= len(chunk)
                plaintext = decryptor.update(chunk)
                if plaintext:
                    output.write(plaintext)
            try:
                final = decryptor.finalize()
            except InvalidTag:
                raise BackupError("encrypted backup authentication failed") from None
            if final:
                output.write(final)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        try:
            destination_path.unlink()
        except FileNotFoundError:
            pass
        raise

    return {"path": str(destination_path), "key_id": key_id}


def create_signed_checkpoint(
    payload: dict,
    destination_path: str | Path,
    *,
    provider: BackupKeyProvider,
) -> dict:
    """Write a detached Ed25519 signature over canonical checkpoint JSON."""
    try:
        key_id = provider.active_checkpoint_signing_key_id()
        private_bytes = provider.get_checkpoint_signing_private_key(key_id)
        public_bytes = provider.get_checkpoint_signing_public_key(key_id)
    except Exception as exc:
        raise BackupKeyUnavailable("audit checkpoint signing key is unavailable") from exc
    if len(private_bytes) != ED25519_KEY_BYTES or len(public_bytes) != ED25519_KEY_BYTES:
        raise BackupKeyUnavailable("Ed25519 checkpoint keys must be exactly 32 bytes")

    private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
    expected_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    if not hmac.compare_digest(expected_public, public_bytes):
        raise BackupKeyUnavailable("checkpoint signing key pair is inconsistent")

    signed_payload = {
        **payload,
        "schema": payload.get("schema", CHECKPOINT_SCHEMA),
        "signing_key_id": key_id,
        "signing_public_key_sha256": hashlib.sha256(public_bytes).hexdigest(),
    }
    payload_bytes = _canonical_json_bytes(signed_payload)
    signature = private_key.sign(payload_bytes)
    envelope = {
        "payload": signed_payload,
        "public_key": base64.b64encode(public_bytes).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    envelope_bytes = _canonical_json_bytes(envelope)
    _atomic_write_bytes(destination_path, envelope_bytes)
    return {
        "path": str(destination_path),
        "sha256": hashlib.sha256(envelope_bytes).hexdigest(),
        "size": len(envelope_bytes),
        "signing_key_id": key_id,
        "payload": signed_payload,
    }


def verify_signed_checkpoint(
    checkpoint_path: str | Path,
    *,
    provider: BackupKeyProvider,
) -> dict:
    """Verify both the Ed25519 signature and the independently trusted public key."""
    try:
        envelope = json.loads(Path(checkpoint_path).read_text(encoding="utf-8"))
        payload = envelope["payload"]
        public_bytes = base64.b64decode(envelope["public_key"], validate=True)
        signature = base64.b64decode(envelope["signature"], validate=True)
        key_id = payload["signing_key_id"]
        trusted_public = provider.get_checkpoint_signing_public_key(key_id)
    except Exception as exc:
        raise BackupError("audit checkpoint is malformed or its trust key is unavailable") from exc
    if len(public_bytes) != ED25519_KEY_BYTES or len(signature) != 64:
        raise BackupError("audit checkpoint signature envelope has invalid lengths")
    if not hmac.compare_digest(public_bytes, trusted_public):
        raise BackupError("audit checkpoint public key is not trusted by this key provider")
    if hashlib.sha256(public_bytes).hexdigest() != payload.get("signing_public_key_sha256"):
        raise BackupError("audit checkpoint public key fingerprint is invalid")

    try:
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(
            signature, _canonical_json_bytes(payload)
        )
    except InvalidSignature:
        raise BackupError("audit checkpoint signature verification failed") from None
    return payload


def _pgpass_escape(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise BackupError("PostgreSQL connection fields contain an invalid newline")
    return value.replace("\\", "\\\\").replace(":", "\\:")


@contextmanager
def _postgres_password_file(settings_dict: dict):
    """Supply pg tools a mode-0600 temporary passfile; never put secrets on argv."""
    password = str(settings_dict.get("PASSWORD") or "")
    if not password:
        raise BackupError("PostgreSQL password is not configured")
    host = str(settings_dict.get("HOST") or "localhost")
    port = str(settings_dict.get("PORT") or "5432")
    # Wildcard database applies the short-lived credential only to this exact
    # host/port/user. It is needed because pg_dump/pg_restore also connect to
    # maintenance and disposable restore databases, not only the live DB.
    name = "*"
    user = str(settings_dict["USER"])
    descriptor, path = tempfile.mkstemp(prefix="hesabdari-pgpass-")
    try:
        os.chmod(path, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(":".join(_pgpass_escape(v) for v in (host, port, name, user, password)))
            stream.write("\n")
        env = os.environ.copy()
        # An inherited PGPASSWORD takes precedence over the private passfile.
        env.pop("PGPASSWORD", None)
        env.update({
            "PGHOST": host,
            "PGPORT": port,
            "PGUSER": user,
            "PGDATABASE": name,
            "PGPASSFILE": path,
        })
        yield env
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def _database_fingerprint() -> str:
    settings_dict = connection.settings_dict
    material = (
        str(settings_dict.get("ENGINE", ""))
        + "\x00"
        + str(settings_dict.get("NAME", ""))
    ).encode("utf-8")
    return hmac.new(
        str(settings.SECRET_KEY).encode("utf-8"),
        b"backup-database\x00" + material,
        hashlib.sha256,
    ).hexdigest()


def _assert_backup_destination_is_external(destination: Path) -> None:
    root = destination.resolve()
    base = Path(settings.BASE_DIR).resolve()
    if root == base or base in root.parents:
        raise BackupError(
            "backup destination must be outside the application/project directory; use separate offline storage"
        )
    if root == Path(connection.settings_dict.get("NAME", "")).resolve().parent:
        raise BackupError("backup destination must not be the live database directory")


def _snapshot_sqlite(destination: Path) -> None:
    database_name = connection.settings_dict.get("NAME")
    if not database_name or str(database_name) == ":memory:" or str(database_name).startswith("file:"):
        raise BackupError("SQLite backup requires a file-backed database")
    source_path = Path(database_name).expanduser().resolve()
    if not source_path.is_file():
        raise BackupError("SQLite database file is not present")
    source = sqlite3.connect(str(source_path), timeout=20)
    target = sqlite3.connect(str(destination), timeout=20)
    try:
        source.execute("PRAGMA query_only=ON")
        source.backup(target, pages=256, sleep=0.05)
        check = target.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise BackupError("SQLite snapshot integrity check failed")
    finally:
        target.close()
        source.close()
    os.chmod(destination, 0o600)


def _snapshot_postgresql(destination: Path) -> None:
    executable = getattr(settings, "ERP_PG_DUMP_COMMAND", None) or shutil.which("pg_dump")
    if not executable:
        raise BackupError("pg_dump is unavailable; refusing an unverified PostgreSQL backup")
    db = connection.settings_dict
    args = [
        str(executable),
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(destination),
        "--host",
        str(db.get("HOST") or "localhost"),
        "--port",
        str(db.get("PORT") or "5432"),
        "--username",
        str(db["USER"]),
        str(db["NAME"]),
    ]
    with _postgres_password_file(db) as env:
        try:
            subprocess.run(
                args,
                env=env,
                check=True,
                capture_output=True,
                timeout=int(getattr(settings, "ERP_BACKUP_TOOL_TIMEOUT_SECONDS", 7200)),
            )
        except Exception as exc:
            raise BackupError(
                "pg_dump failed; the encrypted backup was not published"
            ) from exc
    if not destination.is_file() or destination.stat().st_size == 0:
        raise BackupError("pg_dump produced an empty or missing database snapshot")
    os.chmod(destination, 0o600)


def _require_same_chain(before: dict, after: dict) -> None:
    fields = ("event_count", "head_hash", "last_event_id")
    if any(before[field] != after[field] for field in fields):
        raise BackupError(
            "audit chain changed while the database snapshot was created; discard and retry the complete backup"
        )


def _record_checkpoint_event(*, actor, entity: str, reference: str, digest: str, chain: dict, reason: str):
    with transaction.atomic():
        return record_audit_event(
            user=actor,
            action=AuditAction.AUDIT_CHECKPOINT,
            entity=entity,
            entity_id=digest[:32],
            reference=reference,
            new_state={
                "artifact_sha256": digest,
                "covered_event_count": chain["event_count"],
                "covered_head_hash": chain["head_hash"],
                "covered_last_event_id": chain["last_event_id"],
            },
            reason=reason,
        )


def create_audit_checkpoint_file(
    destination_path: str | Path,
    *,
    provider: BackupKeyProvider,
    actor=None,
    cadence: str = "daily",
    reason: str = "Scheduled audit-chain checkpoint",
) -> dict:
    if cadence not in {"daily", "shift"}:
        raise BackupError("checkpoint cadence must be 'daily' or 'shift'")
    if connection.in_atomic_block:
        raise BackupError("checkpoint creation must start outside an existing transaction")
    try:
        chain = verify_audit_chain()
    except AuditChainVerificationError as exc:
        raise BackupError("audit chain must verify before a checkpoint can be created") from exc
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "checkpoint_type": "audit_chain",
        "cadence": cadence,
        "created_at": _utc_now_text(),
        "database_vendor": connection.vendor,
        "database_fingerprint": _database_fingerprint(),
        "event_count": chain["event_count"],
        "head_hash": chain["head_hash"],
        "last_event_id": chain["last_event_id"],
    }
    result = create_signed_checkpoint(payload, destination_path, provider=provider)
    _record_checkpoint_event(
        actor=actor,
        entity="AUDIT_CHECKPOINT",
        reference=Path(destination_path).name,
        digest=result["sha256"],
        chain=chain,
        reason=reason,
    )
    return result


def create_encrypted_database_backup(
    destination_directory: str | Path,
    *,
    provider: BackupKeyProvider,
    actor=None,
    retention_class: str = "daily",
) -> dict:
    """Create a consistent snapshot, encrypt it, sign its chain checkpoint and audit it."""
    if connection.in_atomic_block:
        raise BackupError("database backup must start outside an existing transaction")
    if retention_class not in {"daily", "pre_upgrade", "month_end"}:
        raise BackupError("retention class must be daily, pre_upgrade, or month_end")

    destination_directory = Path(destination_directory).expanduser()
    _assert_backup_destination_is_external(destination_directory)
    destination_directory.mkdir(parents=True, exist_ok=True)

    try:
        assert_audit_trigger_schema()
        before = verify_audit_chain()
    except AuditChainVerificationError as exc:
        raise BackupError("audit chain must verify before a database backup can be created") from exc
    stamp = timezone.now().astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{retention_class}-{stamp}-{uuid.uuid4().hex[:8]}.hbak"
    encrypted_path = destination_directory / filename
    checkpoint_path = destination_directory / f"{filename}.checkpoint.json"

    with tempfile.TemporaryDirectory(prefix="hesabdari-backup-") as temp_dir:
        snapshot_path = Path(temp_dir) / (
            "database.sqlite3" if connection.vendor == "sqlite" else "database.pgdump"
        )
        if connection.vendor == "sqlite":
            _snapshot_sqlite(snapshot_path)
        elif connection.vendor == "postgresql":
            _snapshot_postgresql(snapshot_path)
        else:
            raise BackupError(f"unsupported database engine for backup: {connection.vendor}")

        try:
            assert_audit_trigger_schema()
            after = verify_audit_chain()
        except AuditChainVerificationError as exc:
            raise BackupError("audit chain became invalid during database backup") from exc
        _require_same_chain(before, after)

        encrypted = encrypt_backup_file(
            snapshot_path,
            encrypted_path,
            provider=provider,
        )
        checkpoint_payload = {
            "schema": BACKUP_SCHEMA,
            "artifact_type": "encrypted_database_backup",
            "created_at": _utc_now_text(),
            "database_vendor": connection.vendor,
            "database_fingerprint": _database_fingerprint(),
            "backup_filename": filename,
            "backup_sha256": encrypted["sha256"],
            "backup_size": encrypted["size"],
            "backup_encryption_key_id": encrypted["key_id"],
            "retention_class": retention_class,
            "chain_event_count": before["event_count"],
            "chain_head_hash": before["head_hash"],
            "chain_last_event_id": before["last_event_id"],
        }
        checkpoint = create_signed_checkpoint(
            checkpoint_payload,
            checkpoint_path,
            provider=provider,
        )

    try:
        _record_checkpoint_event(
            actor=actor,
            entity="DATABASE_BACKUP",
            reference=filename,
            digest=encrypted["sha256"],
            chain=before,
            reason=f"Encrypted {retention_class} database backup created with signed checkpoint",
        )
    except Exception as exc:
        raise BackupError(
            "encrypted backup and signed checkpoint were written, but the required audit event failed; keep the artifacts and investigate"
        ) from exc

    return {
        "backup_path": str(encrypted_path),
        "backup_sha256": encrypted["sha256"],
        "backup_size": encrypted["size"],
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_sha256": checkpoint["sha256"],
        "covered_event_count": before["event_count"],
        "covered_head_hash": before["head_hash"],
        "retention_class": retention_class,
    }


def _json_field(value):
    if value is None or isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return value


def _event_namespace(row: dict):
    if isinstance(row["created_at"], str):
        created_at = parse_datetime(row["created_at"])
        if created_at is None:
            raise BackupError("restored audit event has an invalid timestamp")
        if timezone.is_naive(created_at):
            created_at = timezone.make_aware(created_at, dt_timezone.utc)
    else:
        created_at = row["created_at"]
    return SimpleNamespace(
        pk=row["id"],
        # Django's SQLite UUIDField persists UUIDs as undashed 32-char hex
        # text; the ORM re-hydrates them into uuid.UUID objects whose str()
        # is the dashed canonical form the write-path hash committed to.
        # Raw restored rows must be normalized the same way, or the restored
        # chain verification would see a different canonical payload and
        # reject every legitimate SQLite backup.
        event_uuid=str(uuid.UUID(str(row["event_uuid"]))),
        user_id=row["user_id"],
        action=row["action"],
        entity=row["entity"],
        entity_id=row["entity_id"],
        reference=row["reference"],
        previous_state=_json_field(row["previous_state"]),
        new_state=_json_field(row["new_state"]),
        reason=row["reason"],
        created_at=created_at,
        actor_snapshot=_json_field(row["actor_snapshot"]),
        authorization_context=_json_field(row["authorization_context"]),
        source_fingerprint=row["source_fingerprint"],
        prev_event_hash=row["prev_event_hash"],
        event_hash=row["event_hash"],
    )


_AUDIT_SELECT = (
    "SELECT id, event_uuid, user_id, action, entity, entity_id, reference, "
    "previous_state, new_state, reason, created_at, actor_snapshot, "
    "authorization_context, source_fingerprint, prev_event_hash, event_hash "
    "FROM security_auditevent ORDER BY id"
)


def _verify_restored_rows(events, head_row, expected_payload: dict) -> dict:
    if head_row is None:
        raise AuditChainVerificationError("restored database has no audit-chain head")
    namespace_events = [_event_namespace(row) for row in events]
    try:
        result = verify_audit_chain_records(
            namespace_events,
            head_hash=head_row["head_hash"],
            last_event_id=head_row["last_event_id"],
        )
    except AuditChainVerificationError as exc:
        raise BackupError(
            f"restored database audit chain failed full verification: {exc}"
        ) from exc
    expected = (
        expected_payload["chain_event_count"],
        expected_payload["chain_head_hash"],
        expected_payload["chain_last_event_id"],
    )
    actual = (
        result["event_count"],
        result["head_hash"],
        result["last_event_id"],
    )
    if actual != expected:
        raise BackupError("restored database chain does not match the signed backup checkpoint")
    return result


def _assert_sqlite_restore_guards(db):
    definitions = dict(db.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
        ("security_auditevent",),
    ).fetchall())
    for operation in ("update", "delete"):
        name = f"security_auditevent_no_{operation}"
        expected = (
            f"CREATE TRIGGER {name} BEFORE {operation.upper()} ON security_auditevent "
            "BEGIN SELECT RAISE(ABORT, 'security_auditevent is append-only'); END"
        )
        if " ".join((definitions.get(name) or "").split()) != " ".join(expected.split()):
            raise BackupError(f"restored SQLite audit guard missing or unexpected: {name}")
    if not sqlite_replacement_guard_matches(definitions):
        raise BackupError("restored SQLite replacement guard missing or unexpected")


def _read_postgresql_restore(cursor):
    # psycopg decodes JSONB into Python objects; JSON scalar strings would
    # otherwise be mistaken for raw JSON text by the shared row adapter.
    cursor.execute(
        "SELECT id, event_uuid, user_id, action, entity, entity_id, reference, "
        "previous_state::text AS previous_state, new_state::text AS new_state, "
        "reason, created_at, actor_snapshot::text AS actor_snapshot, "
        "authorization_context::text AS authorization_context, source_fingerprint, "
        "prev_event_hash, event_hash FROM security_auditevent ORDER BY id"
    )
    names = [item.name for item in cursor.description]
    events = [dict(zip(names, row)) for row in cursor.fetchall()]
    cursor.execute(
        "SELECT id, head_hash, last_event_id FROM security_auditchainhead WHERE id = 1"
    )
    row = cursor.fetchone()
    head = dict(zip([item.name for item in cursor.description], row)) if row else None
    cursor.execute(
        "SELECT t.tgtype, t.tgenabled, p.proname FROM pg_trigger t "
        "JOIN pg_proc p ON p.oid=t.tgfoid WHERE t.tgrelid=to_regclass(%s) "
        "AND t.tgname=%s AND NOT t.tgisinternal",
        ("security_auditevent", "security_auditevent_no_update_delete"),
    )
    guard = cursor.fetchone()
    if guard is None or guard[0] != 27 or guard[1] not in ("O", "A") or guard[2] != "security_reject_audit_mutation":
        raise BackupError("restored PostgreSQL audit guard missing, disabled or unexpected")
    cursor.execute(
        "SELECT t.tgtype, t.tgenabled, p.proname FROM pg_trigger t "
        "JOIN pg_proc p ON p.oid=t.tgfoid WHERE t.tgrelid=to_regclass(%s) "
        "AND t.tgname=%s AND NOT t.tgisinternal",
        ("security_auditevent", "security_auditevent_no_truncate"),
    )
    guard = cursor.fetchone()
    if guard is None or guard[0] != 34 or guard[1] not in ("O", "A") or guard[2] != "security_reject_audit_truncate":
        raise BackupError("restored PostgreSQL truncate guard missing, disabled or unexpected")
    return events, head


def _verify_sqlite_snapshot(snapshot_path: Path, expected_payload: dict) -> dict:
    db = sqlite3.connect(snapshot_path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        check = db.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise BackupError("restored SQLite database failed PRAGMA integrity_check")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise BackupError("restored SQLite database has foreign-key violations")
        _assert_sqlite_restore_guards(db)
        events = [dict(row) for row in db.execute(_AUDIT_SELECT).fetchall()]
        head_rows = db.execute(
            "SELECT id, head_hash, last_event_id FROM security_auditchainhead WHERE id = 1"
        ).fetchall()
        if len(head_rows) != 1:
            raise BackupError("restored SQLite database has an invalid audit-chain head row")
        return _verify_restored_rows(events, dict(head_rows[0]), expected_payload)
    except sqlite3.DatabaseError as exc:
        raise BackupError("restored SQLite database schema or audit tables are invalid") from exc
    finally:
        db.close()


def _verify_postgresql_snapshot(snapshot_path: Path, expected_payload: dict) -> dict:
    db = connection.settings_dict
    for tool_name in ("createdb", "pg_restore", "dropdb"):
        if not shutil.which(tool_name):
            raise BackupError(f"{tool_name} is required for isolated PostgreSQL restore verification")

    temporary_db = f"hb_restore_verify_{uuid.uuid4().hex[:20]}"
    with _postgres_password_file({**db, "NAME": str(db["NAME"])}) as env:
        created = False
        try:
            subprocess.run(
                [
                    "createdb", "--template=template0",
                    "--host", str(db.get("HOST") or "localhost"),
                    "--port", str(db.get("PORT") or "5432"),
                    "--username", str(db["USER"]),
                    temporary_db,
                ],
                env=env,
                check=True,
                capture_output=True,
                timeout=300,
            )
            created = True
            subprocess.run(
                [
                    "pg_restore", "--exit-on-error", "--no-owner", "--no-privileges",
                    "--dbname", temporary_db, str(snapshot_path),
                ],
                env={**env, "PGDATABASE": temporary_db},
                check=True,
                capture_output=True,
                timeout=int(getattr(settings, "ERP_BACKUP_RESTORE_TIMEOUT_SECONDS", 7200)),
            )
            import psycopg

            with psycopg.connect(
                dbname=temporary_db,
                user=str(db["USER"]),
                password=str(db.get("PASSWORD") or ""),
                host=str(db.get("HOST") or "localhost"),
                port=int(db.get("PORT") or 5432),
            ) as restored:
                with restored.cursor() as cursor:
                    events, head = _read_postgresql_restore(cursor)
            return _verify_restored_rows(events, head, expected_payload)
        except BackupError:
            raise
        except Exception as exc:
            raise BackupError(
                "PostgreSQL disposable restore or audit-chain verification failed"
            ) from exc
        finally:
            if created:
                try:
                    subprocess.run(
                        [
                            "dropdb", "--if-exists",
                            "--host", str(db.get("HOST") or "localhost"),
                            "--port", str(db.get("PORT") or "5432"),
                            "--username", str(db["USER"]),
                            temporary_db,
                        ],
                        env=env,
                        check=True,
                        capture_output=True,
                        timeout=300,
                    )
                except Exception as exc:
                    raise BackupError(
                        f"disposable restore database {temporary_db!r} could not be dropped"
                    ) from exc


def verify_encrypted_database_backup(
    backup_path: str | Path,
    checkpoint_path: str | Path,
    *,
    provider: BackupKeyProvider,
) -> dict:
    """Verify signature, ciphertext and a full restore-chain check on a disposable DB."""
    raw_backup_path = Path(backup_path)
    if raw_backup_path.is_symlink():
        raise BackupError("symbolic-link backup paths are not accepted")
    backup_path = raw_backup_path.resolve()
    raw_checkpoint_path = Path(checkpoint_path)
    if raw_checkpoint_path.is_symlink():
        raise BackupError("symbolic-link checkpoint paths are not accepted")
    checkpoint_path = raw_checkpoint_path.resolve()
    payload = verify_signed_checkpoint(checkpoint_path, provider=provider)
    if payload.get("schema") != BACKUP_SCHEMA:
        raise BackupError("signed checkpoint is not a database-backup manifest")
    if (
        payload.get("database_vendor") not in {"sqlite", "postgresql"}
        or payload.get("artifact_type") != "encrypted_database_backup"
        or type(payload.get("backup_size")) is not int
        or payload["backup_size"] <= 0
        or type(payload.get("chain_event_count")) is not int
        or payload["chain_event_count"] < 0
        or payload.get("retention_class") not in {"daily", "pre_upgrade", "month_end"}
        or not isinstance(payload.get("backup_encryption_key_id"), str)
        or not payload["backup_encryption_key_id"]
        or any(not isinstance(payload.get(field), str)
               or len(payload[field]) != 64
               or any(c not in "0123456789abcdef" for c in payload[field])
               for field in ("backup_sha256", "chain_head_hash"))
        or "chain_last_event_id" not in payload
        or (payload["chain_last_event_id"] is not None
            and (type(payload["chain_last_event_id"]) is not int or payload["chain_last_event_id"] <= 0))
        or (payload["chain_event_count"] == 0) != (payload["chain_last_event_id"] is None)
    ):
        raise BackupError("signed database backup manifest has invalid fields")
    backup_filename = payload.get("backup_filename", "")
    if (
        not isinstance(backup_filename, str)
        or not backup_filename
        or Path(backup_filename).name != backup_filename
        or not backup_filename.endswith(".hbak")
    ):
        raise BackupError("signed checkpoint backup filename is unsafe")
    expected_path = checkpoint_path.parent / payload["backup_filename"]
    if expected_path != backup_path:
        raise BackupError("backup path does not match the signed checkpoint")
    if not backup_path.is_file():
        raise BackupError("encrypted backup file is missing")
    if backup_path.stat().st_size != payload.get("backup_size"):
        raise BackupError("encrypted backup size does not match signed checkpoint")
    with tempfile.TemporaryDirectory(prefix="hesabdari-restore-verify-") as temp_dir:
        # Authenticate a private stable copy, not a path that can be replaced
        # between digest verification and decryption.
        private_backup = Path(temp_dir) / "authenticated.hbak"
        with backup_path.open("rb") as source, private_backup.open("xb") as output:
            shutil.copyfileobj(source, output, length=CHUNK_SIZE)
        if private_backup.stat().st_size != payload["backup_size"]:
            raise BackupError("encrypted backup size does not match signed checkpoint")
        if not hmac.compare_digest(sha256_file(private_backup), payload["backup_sha256"]):
            raise BackupError("encrypted backup digest does not match signed checkpoint")
        snapshot_path = Path(temp_dir) / (
            "restored.sqlite3"
            if payload["database_vendor"] == "sqlite"
            else "restored.pgdump"
        )
        decrypted = decrypt_backup_file(private_backup, snapshot_path, provider=provider)
        if decrypted["key_id"] != payload["backup_encryption_key_id"]:
            raise BackupError("backup encryption key does not match signed checkpoint")
        if payload["database_vendor"] == "sqlite":
            result = _verify_sqlite_snapshot(snapshot_path, payload)
        elif payload["database_vendor"] == "postgresql":
            result = _verify_postgresql_snapshot(snapshot_path, payload)
        else:
            raise BackupError("signed backup declares an unsupported database engine")

    return {
        "valid": True,
        "backup_sha256": payload["backup_sha256"],
        "event_count": result["event_count"],
        "head_hash": result["head_hash"],
        "last_event_id": result["last_event_id"],
        "retention_class": payload["retention_class"],
    }
