from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import skipUnless

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.db import connection, transaction
from django.test import SimpleTestCase

from security.backup_service import (
    BackupError,
    create_audit_checkpoint_file,
    create_encrypted_database_backup,
    decrypt_backup_file,
    encrypt_backup_file,
    verify_encrypted_database_backup,
    verify_signed_checkpoint,
    create_signed_checkpoint,
)
from security.audit_chain import verify_audit_chain
from security.models import AuditAction
from security.services import record_audit_event
from security.test_support import AuditTriggerAwareTransactionTestCase


class StaticBackupKeyProvider:
    def __init__(self, *, encryption_key=b"E" * 32, signing_seed=b"S" * 32):
        self.encryption_key = encryption_key
        self.signing_seed = signing_seed
        self.signing_private = Ed25519PrivateKey.from_private_bytes(signing_seed)
        self.signing_public = self.signing_private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def active_backup_encryption_key_id(self):
        return "test-backup-aes-v1"

    def get_backup_encryption_key(self, key_id):
        if key_id != "test-backup-aes-v1":
            raise KeyError(key_id)
        return self.encryption_key

    def active_checkpoint_signing_key_id(self):
        return "test-audit-ed25519-v1"

    def get_checkpoint_signing_private_key(self, key_id):
        if key_id != "test-audit-ed25519-v1":
            raise KeyError(key_id)
        return self.signing_seed

    def get_checkpoint_signing_public_key(self, key_id):
        if key_id != "test-audit-ed25519-v1":
            raise KeyError(key_id)
        return self.signing_public


class BackupCryptographicTests(SimpleTestCase):
    def setUp(self):
        self.provider = StaticBackupKeyProvider()
        self.temp = tempfile.TemporaryDirectory(prefix="hesabdari-backup-crypto-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_aes_gcm_backup_round_trip_and_key_metadata(self):
        plain = self.root / "database.dump"
        encrypted = self.root / "database.hbak"
        restored = self.root / "restored.dump"
        plain.write_bytes(b"confidential ERP backup payload" * 100)

        metadata = encrypt_backup_file(plain, encrypted, provider=self.provider)
        decrypt_metadata = decrypt_backup_file(
            encrypted, restored, provider=self.provider
        )

        self.assertEqual(restored.read_bytes(), plain.read_bytes())
        self.assertEqual(metadata["key_id"], "test-backup-aes-v1")
        self.assertEqual(decrypt_metadata["key_id"], "test-backup-aes-v1")
        self.assertEqual(metadata["sha256"], __import__("hashlib").sha256(encrypted.read_bytes()).hexdigest())
        self.assertEqual(os.stat(encrypted).st_mode & 0o777, 0o600)

    def test_gcm_rejects_ciphertext_tampering(self):
        plain = self.root / "database.dump"
        encrypted = self.root / "database.hbak"
        restored = self.root / "restored.dump"
        plain.write_bytes(b"confidential")
        encrypt_backup_file(plain, encrypted, provider=self.provider)

        data = bytearray(encrypted.read_bytes())
        data[len(data) // 2] ^= 0x01
        encrypted.write_bytes(data)

        with self.assertRaisesMessage(BackupError, "authentication failed"):
            decrypt_backup_file(encrypted, restored, provider=self.provider)
        self.assertFalse(restored.exists())

    def test_signed_checkpoint_round_trip_and_payload_tampering(self):
        checkpoint = self.root / "checkpoint.json"
        signed = create_signed_checkpoint(
            {
                "schema": "hesabdari.test-checkpoint.v1",
                "event_count": 17,
                "head_hash": "a" * 64,
            },
            checkpoint,
            provider=self.provider,
        )
        payload = verify_signed_checkpoint(checkpoint, provider=self.provider)
        self.assertEqual(payload["event_count"], 17)
        self.assertEqual(signed["signing_key_id"], "test-audit-ed25519-v1")

        envelope = json.loads(checkpoint.read_text(encoding="utf-8"))
        envelope["payload"]["event_count"] = 18
        checkpoint.write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaisesMessage(BackupError, "signature verification failed"):
            verify_signed_checkpoint(checkpoint, provider=self.provider)

    def test_checkpoint_from_untrusted_public_key_is_rejected(self):
        checkpoint = self.root / "checkpoint.json"
        create_signed_checkpoint(
            {"schema": "hesabdari.test-checkpoint.v1", "event_count": 1},
            checkpoint,
            provider=self.provider,
        )
        other_provider = StaticBackupKeyProvider(signing_seed=b"X" * 32)
        with self.assertRaisesMessage(BackupError, "public key is not trusted"):
            verify_signed_checkpoint(checkpoint, provider=other_provider)


@skipUnless(connection.vendor == "sqlite", "SQLite snapshot integration test")
class SQLiteDatabaseBackupTests(AuditTriggerAwareTransactionTestCase):
    def setUp(self):
        self.provider = StaticBackupKeyProvider()
        with transaction.atomic():
            record_audit_event(
                user=None,
                action=AuditAction.CREATE,
                entity="BackupFixture",
                entity_id="fixture-1",
                new_state={"amount": "25.50", "currency": "AFN"},
                reason="Initial backup test event",
            )
        self.temp = tempfile.TemporaryDirectory(prefix="hesabdari-backup-db-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_encrypted_backup_restores_and_verifies_full_chain(self):
        initial = verify_audit_chain()
        result = create_encrypted_database_backup(
            self.root,
            provider=self.provider,
            actor=None,
            retention_class="daily",
        )
        restored = verify_encrypted_database_backup(
            result["backup_path"],
            result["checkpoint_path"],
            provider=self.provider,
        )

        self.assertTrue(restored["valid"])
        self.assertEqual(restored["event_count"], initial["event_count"])
        self.assertEqual(restored["head_hash"], initial["head_hash"])
        self.assertEqual(restored["last_event_id"], initial["last_event_id"])
        self.assertEqual(result["retention_class"], "daily")
        self.assertTrue(Path(result["backup_path"]).is_file())
        self.assertTrue(Path(result["checkpoint_path"]).is_file())
        # The live database receives a separate AUDIT_CHECKPOINT record only
        # after its pre-backup head has been captured and signed.
        self.assertEqual(verify_audit_chain()["event_count"], initial["event_count"] + 1)

    def test_backup_verification_rejects_changed_encrypted_artifact(self):
        result = create_encrypted_database_backup(
            self.root,
            provider=self.provider,
            actor=None,
            retention_class="pre_upgrade",
        )
        backup_path = Path(result["backup_path"])
        data = bytearray(backup_path.read_bytes())
        data[len(data) // 2] ^= 0x01
        backup_path.write_bytes(data)

        with self.assertRaisesMessage(BackupError, "digest does not match"):
            verify_encrypted_database_backup(
                backup_path,
                result["checkpoint_path"],
                provider=self.provider,
            )

    def test_daily_and_shift_checkpoints_are_signed_and_audited(self):
        daily_path = self.root / "audit-daily.json"
        shift_path = self.root / "audit-shift.json"

        daily = create_audit_checkpoint_file(
            daily_path,
            provider=self.provider,
            actor=None,
            cadence="daily",
            reason="Daily checkpoint test",
        )
        shift = create_audit_checkpoint_file(
            shift_path,
            provider=self.provider,
            actor=None,
            cadence="shift",
            reason="High-activity shift checkpoint test",
        )
        daily_payload = verify_signed_checkpoint(daily_path, provider=self.provider)
        shift_payload = verify_signed_checkpoint(shift_path, provider=self.provider)

        self.assertEqual(daily_payload["cadence"], "daily")
        self.assertEqual(shift_payload["cadence"], "shift")
        self.assertEqual(daily["signing_key_id"], "test-audit-ed25519-v1")
        self.assertEqual(shift["signing_key_id"], "test-audit-ed25519-v1")
        self.assertEqual(verify_audit_chain()["event_count"], 3)
