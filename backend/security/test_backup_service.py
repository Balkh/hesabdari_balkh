from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.db import connection, transaction
from django.test import SimpleTestCase

from security.backup_service import (
    BackupError,
    BackupKeyUnavailable,
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


class BatchCKeyAndManifestTests(SimpleTestCase):
    setUp = BackupCryptographicTests.setUp
    tearDown = BackupCryptographicTests.tearDown

    def test_wrong_encryption_key_and_missing_key_fail_without_plaintext(self):
        plain = self.root / "plain"
        encrypted = self.root / "backup.hbak"
        restored = self.root / "restored"
        plain.write_bytes(b"financial backup")
        encrypt_backup_file(plain, encrypted, provider=self.provider)
        with self.assertRaisesMessage(BackupError, "authentication failed"):
            decrypt_backup_file(encrypted, restored, provider=StaticBackupKeyProvider(encryption_key=b"X" * 32))
        self.assertFalse(restored.exists())
        with patch.object(self.provider, "get_backup_encryption_key", side_effect=KeyError("missing")):
            with self.assertRaises(BackupKeyUnavailable):
                decrypt_backup_file(encrypted, restored, provider=self.provider)
        self.assertFalse(restored.exists())

    def test_truncated_envelope_cannot_publish_plaintext(self):
        plain = self.root / "plain"
        encrypted = self.root / "backup.hbak"
        restored = self.root / "restored"
        plain.write_bytes(b"financial backup")
        encrypt_backup_file(plain, encrypted, provider=self.provider)
        encrypted.write_bytes(encrypted.read_bytes()[:10])
        with self.assertRaises(BackupError):
            decrypt_backup_file(encrypted, restored, provider=self.provider)
        self.assertFalse(restored.exists())


class BatchCDatabaseRestoreTests(AuditTriggerAwareTransactionTestCase):
    def setUp(self):
        from accounting.models import Account, AccountType
        from accounting.services import post_journal
        from currencies.models import Currency

        self.provider = StaticBackupKeyProvider()
        self.temp = tempfile.TemporaryDirectory(prefix="hesabdari-batch-c-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        cash = Account.objects.create(code="1100", name="Cash", account_type=AccountType.ASSET)
        revenue = Account.objects.create(code="4100", name="Revenue", account_type=AccountType.REVENUE)
        afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        self.entry = post_journal(
            number="JE-1405-99001", posting_date="2026-09-06",
            description="Batch C restore evidence", currency=afn,
            lines=[{"account": cash, "debit": "125.50"}, {"account": revenue, "credit": "125.50"}],
            idempotency_key="batch-c-financial-restore",
        )
        with transaction.atomic():
            record_audit_event(action=AuditAction.CREATE, entity="BatchCScalar",
                               new_state="plain JSON string", previous_state="123")
        self.initial = verify_audit_chain()

    def _backup(self):
        return create_encrypted_database_backup(self.root, provider=self.provider, retention_class="pre_upgrade")

    def _assert_financial(self, cursor, placeholder):
        cursor.execute(
            "SELECT number, status, total_debit, total_credit FROM accounting_journalentry WHERE id = " + placeholder,
            [self.entry.pk],
        )
        row = cursor.fetchone()
        self.assertEqual(row[:2], (self.entry.number, "POSTED"))
        self.assertEqual(tuple(Decimal(str(value)) for value in row[2:]), (Decimal("125.50"), Decimal("125.50")))
        cursor.execute(
            "SELECT debit, credit FROM accounting_journalline WHERE entry_id = " + placeholder + " ORDER BY id",
            [self.entry.pk],
        )
        self.assertEqual([tuple(Decimal(str(value)) for value in row) for row in cursor.fetchall()],
                         [(Decimal("125.50"), Decimal("0")), (Decimal("0"), Decimal("125.50"))])
        cursor.execute("SELECT COUNT(*) FROM core_idempotencyrecord WHERE key = " + placeholder,
                       ["batch-c-financial-restore"])
        self.assertEqual(cursor.fetchone()[0], 1)

    def _temporary_databases(self):
        if connection.vendor != "postgresql":
            return set()
        with connection.cursor() as cursor:
            cursor.execute("SELECT datname FROM pg_database WHERE left(datname, 18) = 'hb_restore_verify_'")
            return {row[0] for row in cursor.fetchall()}

    def test_real_restore_financial_rows_audit_guards_and_cleanup(self):
        from security import backup_service as service

        before_dbs = self._temporary_databases()
        result = self._backup()
        live = verify_audit_chain()
        self.assertEqual(live["event_count"], self.initial["event_count"] + 1)
        observed = []
        if connection.vendor == "sqlite":
            original = service._verify_sqlite_snapshot

            def inspect(path, payload):
                db = sqlite3.connect(str(path))
                try:
                    self._assert_financial(db.cursor(), "?")
                    for sql in (
                        "UPDATE security_auditevent SET reason='forbidden'",
                        "DELETE FROM security_auditevent",
                    ):
                        with self.assertRaises(sqlite3.DatabaseError):
                            db.execute(sql)
                        db.rollback()
                    observed.append(str(path))
                finally:
                    db.close()
                return original(path, payload)

            target = "_verify_sqlite_snapshot"
        else:
            import psycopg
            original = service._read_postgresql_restore

            def inspect(cursor):
                self._assert_financial(cursor, "%s")
                for sql in (
                    "UPDATE security_auditevent SET reason='forbidden'",
                    "DELETE FROM security_auditevent",
                ):
                    with self.assertRaises(psycopg.Error):
                        with cursor.connection.transaction():
                            cursor.execute(sql)
                observed.append(cursor.connection.info.dbname)
                return original(cursor)

            target = "_read_postgresql_restore"

        with patch.object(service, target, side_effect=inspect):
            restored = verify_encrypted_database_backup(result["backup_path"], result["checkpoint_path"],
                                                        provider=self.provider)
        self.assertEqual(len(observed), 1)
        self.assertTrue(restored["valid"])
        for field in ("event_count", "head_hash", "last_event_id"):
            self.assertEqual(restored[field], self.initial[field])
        self.assertEqual(verify_audit_chain(), live)
        self.assertEqual(self._temporary_databases(), before_dbs)
        if connection.vendor == "sqlite":
            self.assertFalse(Path(observed[0]).exists())
        print(f"BATCH C RESTORE [{connection.vendor}]: balanced 125.50 AFN; chain and guards verified; temporary restore removed")

    def test_signed_manifest_key_mismatch_rejected_before_restore(self):
        result = self._backup()
        live = verify_audit_chain()
        payload = verify_signed_checkpoint(result["checkpoint_path"], provider=self.provider)
        payload["backup_encryption_key_id"] = "different-key-id"
        checkpoint = self.root / "mismatched.checkpoint.json"
        create_signed_checkpoint(payload, checkpoint, provider=self.provider)
        with self.assertRaisesMessage(BackupError, "encryption key does not match signed checkpoint"):
            verify_encrypted_database_backup(result["backup_path"], checkpoint, provider=self.provider)
        self.assertEqual(verify_audit_chain(), live)


    def test_offline_recovery_bundle_verifies_financial_restore_in_fresh_process(self):
        import subprocess
        import sys
        from security.offline_recovery import create_recovery_bundle
        backup = self._backup()
        live = verify_audit_chain()
        before_dbs = self._temporary_databases()
        bundle = self.root / "replacement-device.hbr"
        secret = b"R" * 32  # synthetic fixture only
        metadata = create_recovery_bundle(bundle, provider=self.provider, recovery_secret=secret,
            encryption_id=self.provider.active_backup_encryption_key_id(),
            signing_id=self.provider.active_checkpoint_signing_key_id())
        pg = None
        if connection.vendor == "postgresql":
            pg = {k: str(connection.settings_dict.get(k) or "") for k in ("NAME", "USER", "PASSWORD", "PORT")}
            pg["HOST"] = "127.0.0.1"
        script = r"""
import json, sys
from pathlib import Path
from unittest.mock import patch
from decimal import Decimal
from security.offline_recovery_cli import configure_offline_django
configure_offline_django()
from django.db import connection
assert connection.vendor == "unknown", connection.vendor
from security import backup_service as service
from security.offline_recovery import verify_offline_recovery
data = json.load(sys.stdin)
seen = []
def check(cursor, placeholder):
    cursor.execute("SELECT status,total_debit,total_credit FROM accounting_journalentry WHERE number="+placeholder, ["JE-1405-99001"])
    row = cursor.fetchone()
    assert row[0] == "POSTED"
    assert tuple(Decimal(str(v)) for v in row[1:]) == (Decimal("125.50"), Decimal("125.50"))
    cursor.execute("SELECT COUNT(*) FROM core_idempotencyrecord WHERE key="+placeholder, ["batch-c-financial-restore"])
    assert cursor.fetchone()[0] == 1
if data["vendor"] == "sqlite":
    original = service._verify_sqlite_snapshot
    def inspect(path, payload):
        import sqlite3
        db = sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True)
        try:
            check(db.cursor(), "?")
        finally:
            db.close()
        seen.append(str(path))
        return original(path, payload)
    target = "_verify_sqlite_snapshot"
else:
    original = service._read_postgresql_restore
    def inspect(cursor):
        check(cursor, "%s")
        seen.append(cursor.connection.info.dbname)
        return original(cursor)
    target = "_read_postgresql_restore"
with patch.object(service, target, side_effect=inspect):
    result = verify_offline_recovery(backup_path=data["backup"], checkpoint_path=data["checkpoint"],
        bundle_path=data["bundle"], recovery_secret=bytes.fromhex(data["secret"]),
        trusted_public_sha256=data["pin"], vendor=data["vendor"], restore_database_config=data["pg"])
assert len(seen) == 1
assert connection.connection is None
if data["vendor"] == "sqlite":
    assert not Path(seen[0]).exists()
print(json.dumps(result))
"""
        env = os.environ.copy()
        env.pop("DJANGO_SETTINGS_MODULE", None)
        data = {"vendor": connection.vendor, "backup": backup["backup_path"],
                "checkpoint": backup["checkpoint_path"], "bundle": str(bundle),
                "secret": secret.hex(), "pin": metadata["trusted_public_sha256"], "pg": pg}
        process = subprocess.run([sys.executable, "-c", script], input=json.dumps(data),
            env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(process.returncode, 0, process.stderr)
        restored = json.loads(process.stdout)
        self.assertTrue(restored["valid"])
        for field in ("event_count", "head_hash", "last_event_id"):
            self.assertEqual(restored[field], self.initial[field])
        self.assertEqual(self._temporary_databases(), before_dbs)
        self.assertEqual(verify_audit_chain(), live)
        print(f"OFFLINE RECOVERY [{connection.vendor}]: independent process, no ERP ORM, balanced 125.50 AFN, chain and cleanup verified")
