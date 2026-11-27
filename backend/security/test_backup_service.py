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


    def test_offline_recovery_cli_real_verification_and_wrong_secret(self):
        import subprocess
        import sys
        from datetime import timedelta
        from django.contrib.auth import get_user_model
        from django.contrib.sessions.models import Session
        from django.utils import timezone
        from categories.models import Category
        from currencies.models import Currency
        from inventory.models import MovementType, StockMovement
        from products.models import Product
        from uom.models import UnitOfMeasure
        from warehouses.models import Warehouse
        from security.mfa_models import SecurityLoginSession
        from security.offline_recovery import create_recovery_bundle

        category = Category.objects.create(name="Recovery fixture")
        unit = UnitOfMeasure.objects.create(name="Piece")
        product = Product.objects.create(code="ODR-STOCK", name="Fixture", name_fa="Fixture",
                                         category=category, primary_uom=unit)
        warehouse = Warehouse.objects.create(name="Recovery fixture")
        common = dict(product=product, warehouse=warehouse, currency=Currency.objects.get(code="AFN"),
                      movement_date="2026-09-06", rate_date="2026-09-06", rate=1,
                      unit_cost=10, unit_cost_afn=10)
        StockMovement.objects.create(**common, movement_type=MovementType.OPENING, quantity=10,
                                     qty_before=0, qty_after=10, reference="ODR-in")
        StockMovement.objects.create(**common, movement_type=MovementType.SALES_ISSUE, quantity=-3,
                                     qty_before=10, qty_after=7, reference="ODR-out")
        staff = get_user_model().objects.create_user(username="odr-readiness-fixture")
        now = timezone.now()
        SecurityLoginSession.objects.create(user=staff, session_key_hash="d"*64, slot_number=1,
            created_at=now, last_seen_at=now, idle_expires_at=now+timedelta(minutes=15),
            absolute_expires_at=now+timedelta(hours=12))
        Session.objects.create(session_key="odr-readiness-fixture", session_data="synthetic",
                               expire_date=now+timedelta(hours=12))
        backup = self._backup()
        live = verify_audit_chain()
        before_dbs = self._temporary_databases()
        bundle = self.root / "cli.hbr"
        secret = b"R"*32
        metadata = create_recovery_bundle(bundle, provider=self.provider, recovery_secret=secret,
            encryption_id=self.provider.active_backup_encryption_key_id(),
            signing_id=self.provider.active_checkpoint_signing_key_id())
        args = ["--vendor", connection.vendor, "--backup", backup["backup_path"],
                "--checkpoint", backup["checkpoint_path"], "--bundle", str(bundle),
                "--trusted-public-sha256", metadata["trusted_public_sha256"],
                "--trusted-checkpoint-sha256", backup["checkpoint_sha256"], "--readiness-report"]
        password = None
        if connection.vendor == "postgresql":
            args += ["--isolated-postgres", "--pg-port", str(connection.settings_dict["PORT"]),
                     "--pg-user", str(connection.settings_dict["USER"])]
            password = str(connection.settings_dict["PASSWORD"])
        script = r"""
import json, sys
from unittest.mock import patch
from security.offline_recovery_cli import main
from security.local_console import LocalConsoleRequiredError
data = json.load(sys.stdin)
with patch("security.local_console.require_local_console", side_effect=LocalConsoleRequiredError("nonlocal")):
    assert main(data["args"]) == 1
# main configures Django before its console guard; a second invocation in
# the same process is forbidden. This branch deliberately exits here.
"""
        env = os.environ.copy()
        env.pop("DJANGO_SETTINGS_MODULE", None)
        denied = subprocess.run([sys.executable, "-c", script], input=json.dumps({"args": args}),
            env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(denied.returncode, 0, denied.stderr)
        self.assertNotIn("OFFLINE DISPOSABLE RECOVERY VERIFIED", denied.stdout)
        script = r"""
import json, sys
from unittest.mock import patch
from security.offline_recovery_cli import main
data = json.load(sys.stdin)
answers = ([data["password"]] if data["password"] is not None else []) + [data["secret"]]
with patch("security.local_console.require_local_console"), patch("getpass.getpass", side_effect=answers):
    result = main(data["args"])
from django.db import connection
assert connection.vendor == "unknown"
assert connection.connection is None
raise SystemExit(result)
"""
        for supplied, expected in ((b"X"*32, 1), (secret, 0)):
            process = subprocess.run([sys.executable, "-c", script],
                input=json.dumps({"args": args, "password": password, "secret": supplied.hex()}),
                env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(process.returncode, expected, process.stderr)
            self.assertEqual("OFFLINE DISPOSABLE RECOVERY VERIFIED" in process.stdout, expected == 0)
            self.assertEqual("Checkpoint selection pin: matched" in process.stdout, expected == 0)
            prefix = "RECOVERY READINESS REPORT (not activation approval): "
            if expected == 0:
                report = json.loads(next(line[len(prefix):] for line in process.stdout.splitlines() if line.startswith(prefix)))
                self.assertEqual(report["posted_or_reversed_journals"], 1)
                self.assertEqual(report["checked_journal_lines"], 2)
                self.assertEqual(report["checked_stock_movements"], 2)
                self.assertEqual(report["stock_product_warehouse_groups"], 1)
                self.assertEqual(report["historical_registry_sessions"], 1)
                self.assertEqual(report["django_session_rows"], 1)
                self.assertEqual(report["idempotency_records"], 1)
            else:
                self.assertNotIn(prefix, process.stdout)
            self.assertNotIn(supplied.hex(), process.stdout + process.stderr)
            self.assertEqual(self._temporary_databases(), before_dbs)
        self.assertEqual(verify_audit_chain(), live)
        print(f"ODR CLI [{connection.vendor}]: real entrypoint, nonlocal and wrong-secret denial, disposable success verified")

    def test_recovered_copy_gm_recovery_preserves_financial_history(self):
        """Use the real restored disposable DB only; no activation of an ERP DB."""
        import subprocess
        import sys
        from datetime import timedelta
        from django.contrib.auth import get_user_model
        from django.contrib.sessions.models import Session
        from django.utils import timezone
        from security.models import GMRoleSlot, Role, UserRoleAssignment
        from security.mfa_models import SecurityEmergencyOwnerKey, SecurityLoginSession, SecurityMFARequirement, SecurityMFADevice, MFADeviceStatus, SecurityRecoveryCode
        from security.emergency_owner_key_service import generate_emergency_owner_key, emergency_owner_key_digest
        from security.mfa import totp_code
        from security.mfa_service import begin_mfa_enrollment, confirm_mfa_enrollment
        from security.test_emergency_owner_key import StaticMFAKeyProvider
        from security.offline_recovery import create_recovery_bundle, verify_offline_recovery
        from security import backup_service as service
        from accounting.models import Account, AccountType
        from accounting.services import post_journal
        from categories.models import Category
        from currencies.models import Currency
        from inventory.models import MovementType, StockMovement
        from party_ledger.models import PartyLedgerAttribution
        from parties.models import Party
        from products.models import Product
        from uom.models import UnitOfMeasure
        from warehouses.models import Warehouse

        afn = Currency.objects.get(code="AFN")
        usd = Currency.objects.create(code="USD", name="Dollar")
        receivable = Account.objects.create(code="1310", name="Receivable", account_type=AccountType.ASSET)
        cash = Account.objects.create(code="1110", name="Cash in hand", account_type=AccountType.ASSET)
        party = Party.objects.create(name="Recovery report fixture", is_customer=True)
        usd_entry = post_journal(number="JE-1405-99002", posting_date="2026-09-06",
            description="Currency-separated recovery evidence", currency=usd, rate="70",
            rate_date="2026-09-06", lines=[{"account": receivable, "debit": "10.25"},
                                          {"account": cash, "credit": "10.25"}])
        PartyLedgerAttribution.objects.create(party=party, journal_line=usd_entry.lines.get(account=receivable))
        product = Product.objects.create(code="ODR-AVCO", name="Fixture", name_fa="Fixture",
            category=Category.objects.create(name="Recovery AVCO"),
            primary_uom=UnitOfMeasure.objects.create(name="Piece"))
        warehouse = Warehouse.objects.create(name="Recovery AVCO")
        common = dict(product=product, warehouse=warehouse, currency=afn,
                      movement_date="2026-09-06", rate_date="2026-09-06", rate=1,
                      unit_cost=10, unit_cost_afn=10)
        StockMovement.objects.create(**common, movement_type=MovementType.OPENING, quantity=10,
            qty_before=0, qty_after=10, reference="ODR-valuation-in")
        StockMovement.objects.create(**common, movement_type=MovementType.SALES_ISSUE, quantity=-3,
            qty_before=10, qty_after=7, reference="ODR-valuation-out")

        now = timezone.now()
        gm = get_user_model().objects.create_user(username="odr-restored-gm", password="Fixture-old-GM-Password-2026!", is_active=True)
        role, _ = Role.objects.get_or_create(code="GM", defaults={"name": "General Manager", "is_active": True, "is_system": True})
        assignment = UserRoleAssignment.objects.create(user=gm, role=role, start_at=now-timedelta(minutes=1), reason="disposable recovery test")
        slot = GMRoleSlot.objects.get(code="GM")
        slot.assignment = assignment
        slot.save(update_fields=["assignment", "updated_at"])
        owner = generate_emergency_owner_key()
        owner_row = SecurityEmergencyOwnerKey.objects.create(scope=SecurityEmergencyOwnerKey.GM_RECOVERY,
            source=SecurityEmergencyOwnerKey.SOURCE_INITIAL_BOOTSTRAP, key_hash=emergency_owner_key_digest(owner),
            issued_at=now, issued_by=gm)
        old_provider = StaticMFAKeyProvider()
        started = begin_mfa_enrollment(gm, provider=old_provider)
        confirm_mfa_enrollment(gm, totp_code(started["secret"], timestamp=now.timestamp()), provider=old_provider, at=now)
        SecurityLoginSession.objects.create(user=gm, session_key_hash="a"*64, slot_number=1,
            created_at=now, last_seen_at=now, idle_expires_at=now+timedelta(minutes=15),
            absolute_expires_at=now+timedelta(hours=12), mfa_verified_at=now)
        staff = get_user_model().objects.create_user(username="odr-restored-employee", password="Fixture-employee-Password-2026!", is_active=True)
        staff_enrollment = begin_mfa_enrollment(staff, provider=old_provider)
        confirm_mfa_enrollment(staff, totp_code(staff_enrollment["secret"], timestamp=now.timestamp()), provider=old_provider, at=now)
        SecurityMFARequirement.objects.create(user=staff, is_required=True, updated_by=gm, reason="fixture required")
        SecurityLoginSession.objects.create(user=staff, session_key_hash="b"*64, slot_number=1,
            created_at=now, last_seen_at=now, idle_expires_at=now+timedelta(minutes=15),
            absolute_expires_at=now+timedelta(hours=12), mfa_verified_at=now)
        Session.objects.create(session_key="odr-historical", session_data="synthetic", expire_date=now+timedelta(hours=12))
        snapshot = verify_audit_chain()
        backup = self._backup()
        live = verify_audit_chain()
        before_dbs = self._temporary_databases()
        bundle = self.root / "gm-recovery.hbr"
        secret = b"R"*32
        metadata = create_recovery_bundle(bundle, provider=self.provider, recovery_secret=secret,
            encryption_id=self.provider.active_backup_encryption_key_id(),
            signing_id=self.provider.active_checkpoint_signing_key_id())
        pg = None
        if connection.vendor == "postgresql":
            pg = {k: str(connection.settings_dict.get(k) or "") for k in ("NAME", "USER", "PASSWORD", "PORT")}
            pg["HOST"] = "127.0.0.1"
        child = r"""
import json, sys
from datetime import timedelta
from unittest.mock import patch
from decimal import Decimal
from django.conf import settings
from config.settings.base import INSTALLED_APPS, AUTH_PASSWORD_VALIDATORS
data = json.load(sys.stdin)
settings.configure(INSTALLED_APPS=INSTALLED_APPS, AUTH_PASSWORD_VALIDATORS=AUTH_PASSWORD_VALIDATORS,
    SECRET_KEY="synthetic-replacement-device-only", USE_TZ=True, TIME_ZONE="UTC",
    DATABASES={"default": data["database"]}, DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
    ERP_OFFLINE_REPLACEMENT_STAGING=True)
import django
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone
from security.audit_chain import verify_audit_chain, assert_audit_trigger_schema, has_verified_replacement_preparation
from security.emergency_owner_key_service import generate_emergency_owner_key, validate_current_gm_emergency_owner_key, EmergencyOwnerKeyInvalid, EmergencyOwnerKeyPolicyDenied
from security.replacement_identity import prepare_replacement_identity, reenroll_replacement_employee
from security.replacement_financial import collect_replacement_financial_report
from security.recovery_readiness import RecoveryReconciliationError
from django.contrib.sessions.models import Session
from django.test import override_settings
from security.models import GMRoleSlot, AuditEvent, AuditChainHead
from security.mfa_models import SecurityLoginSession, SecurityMFADevice, MFADeviceStatus, SecurityRecoveryCode, SecurityMFARequirement
from security.mfa_policy import user_requires_mfa
from security.mfa import generate_totp_secret, totp_code
from security.mfa_service import _encrypted_secret_for
from security.errors import KeyUnavailableError
from accounting.models import JournalEntry, JournalLine
from core.models import IdempotencyRecord
from inventory.models import StockMovement
from party_ledger.models import PartyLedgerAttribution
class ReplacementProvider:
    def active_key_id(self): return "replacement-fixture-v2"
    def get_key(self, key_id):
        if key_id != self.active_key_id(): raise KeyError(key_id)
        return b"N"*32
provider = ReplacementProvider()
gm = get_user_model().objects.get(username="odr-restored-gm")
staff = get_user_model().objects.get(username="odr-restored-employee")
old = SecurityMFADevice.objects.get(user=gm, status=MFADeviceStatus.ACTIVE)
try:
    _encrypted_secret_for(old, gm, provider)
except KeyUnavailableError:
    pass
else:
    raise AssertionError("old MFA unexpectedly decryptable on replacement")
assert_audit_trigger_schema()
before = verify_audit_chain()
assert before == data["snapshot"]
assert not has_verified_replacement_preparation(gm)
def financial():
    return [list(m.objects.order_by("pk").values()) for m in (JournalEntry, JournalLine, IdempotencyRecord, StockMovement, PartyLedgerAttribution)]
baseline = financial()
now = timezone.now()
seed = generate_totp_secret()
new_owner = generate_emergency_owner_key()
kwargs = dict(new_owner_key=new_owner, new_password="Fixture-new-GM-Password-2026!",
              new_totp_secret=seed, new_totp_code=totp_code(seed, timestamp=now.timestamp()), provider=provider, at=now,
              expected_checkpoint=before, expected_owner_record=data["owner_row"], source_isolated=True)
def prepare(**changes):
    with patch("security.replacement_identity.require_local_console"):
        return prepare_replacement_identity(data["owner"], **(kwargs | changes))
class HistoricalProvider:
    def active_key_id(self): return old.secret_key_id
    def get_key(self, key_id): raise AssertionError("historical key must be rejected before read")
for changes in ({"source_isolated": False}, {"expected_owner_record": data["owner_row"]+1},
                {"expected_checkpoint": {**before, "head_hash": "0"*64}}, {"provider": HistoricalProvider()}):
    try: prepare(**changes)
    except (EmergencyOwnerKeyInvalid, EmergencyOwnerKeyPolicyDenied): pass
    else: raise AssertionError("invalid independent recovery prerequisite accepted")
with override_settings(ERP_OFFLINE_REPLACEMENT_STAGING=False):
    try: prepare()
    except EmergencyOwnerKeyPolicyDenied: pass
    else: raise AssertionError("non-staging recovery accepted")
assert verify_audit_chain() == before
assert SecurityLoginSession.objects.filter(revoked_at__isnull=True).count() == 2
assert Session.objects.count() == 1
def reject(instance, *args, **kwargs):
    if instance.last_event.entity == "GM_EMERGENCY_RECOVERY":
        return original_save(instance, *args, **kwargs)
    assert instance.last_event.entity == "REPLACEMENT_IDENTITY_PREPARATION"
    assert AuditEvent.objects.filter(pk=instance.last_event_id).exists()
    raise RuntimeError("restored GM audit head failure")
original_save = AuditChainHead.save
with patch.object(AuditChainHead, "save", autospec=True, side_effect=reject):
    try: prepare()
    except RuntimeError as exc: assert str(exc) == "restored GM audit head failure"
    else: raise AssertionError("missing audit failure")
gm.refresh_from_db()
assert gm.check_password("Fixture-old-GM-Password-2026!")
assert SecurityLoginSession.objects.filter(user=gm, revoked_at__isnull=True).count() == 1
assert validate_current_gm_emergency_owner_key(data["owner"]) == data["owner_row"]
assert verify_audit_chain() == before
assert financial() == baseline
assert SecurityLoginSession.objects.filter(revoked_at__isnull=True).count() == 2
assert Session.objects.count() == 1
assert SecurityMFADevice.objects.filter(user=staff, status=MFADeviceStatus.ACTIVE).count() == 1
assert SecurityRecoveryCode.objects.filter(user=staff, used_at__isnull=True).count() == 10
recovered, codes = prepare()
assert recovered.pk == gm.pk and len(codes) == 10
assert has_verified_replacement_preparation(gm)
assert not has_verified_replacement_preparation(staff)
assert recovered.check_password("Fixture-new-GM-Password-2026!")
assert not recovered.check_password("Fixture-old-GM-Password-2026!")
assert GMRoleSlot.objects.get(code="GM").assignment_id == data["assignment"]
assert SecurityLoginSession.objects.filter(revoked_at__isnull=True).count() == 0
assert Session.objects.count() == 0
assert user_requires_mfa(staff)
assert not SecurityMFADevice.objects.filter(user=staff, status__in=(MFADeviceStatus.ACTIVE, MFADeviceStatus.PENDING)).exists()
assert not SecurityRecoveryCode.objects.filter(user=staff, used_at__isnull=True).exists()
active = SecurityMFADevice.objects.get(user=gm, status=MFADeviceStatus.ACTIVE)
assert active.secret_key_id == provider.active_key_id()
assert _encrypted_secret_for(active, gm, provider) == seed.encode("ascii")
assert SecurityRecoveryCode.objects.filter(user=gm, used_at__isnull=True).count() == 10
try: validate_current_gm_emergency_owner_key(data["owner"])
except EmergencyOwnerKeyInvalid: pass
else: raise AssertionError("old owner key still accepted")
assert validate_current_gm_emergency_owner_key(new_owner)
assert financial() == baseline
entry = JournalEntry.objects.get(number="JE-1405-99001")
assert entry.total_debit == entry.total_credit == Decimal("125.50")
after = verify_audit_chain()
assert after["event_count"] == before["event_count"] + 2
staff_seed = generate_totp_secret()
later = now + timedelta(seconds=60)
staff_args = dict(gm_password="Fixture-new-GM-Password-2026!",
    gm_totp_code=totp_code(seed, timestamp=later.timestamp()),
    employee_password="Fixture-employee-Password-2026!",
    new_totp_secret=staff_seed, new_totp_code=totp_code(staff_seed, timestamp=later.timestamp()),
    provider=provider, source_isolated=True, at=later)
with patch("security.replacement_identity.require_local_console"):
    try: reenroll_replacement_employee(staff.pk, **(staff_args | {"employee_password": "wrong"}))
    except EmergencyOwnerKeyInvalid: pass
    else: raise AssertionError("wrong employee password accepted")
    assert not SecurityMFADevice.objects.filter(user=staff, status=MFADeviceStatus.ACTIVE).exists()
    try: reenroll_replacement_employee(staff.pk, **staff_args)
    except EmergencyOwnerKeyInvalid: pass
    else: raise AssertionError("GM TOTP replay accepted")
    later += timedelta(seconds=60)
    staff_args.update(at=later, gm_totp_code=totp_code(seed, timestamp=later.timestamp()),
                      new_totp_code=totp_code(staff_seed, timestamp=later.timestamp()))
    staff_codes = reenroll_replacement_employee(staff.pk, **staff_args)
assert len(staff_codes) == 10 and user_requires_mfa(staff)
staff_active = SecurityMFADevice.objects.get(user=staff, status=MFADeviceStatus.ACTIVE)
assert _encrypted_secret_for(staff_active, staff, provider) == staff_seed.encode("ascii")
assert SecurityRecoveryCode.objects.filter(user=staff, used_at__isnull=True).count() == 10
assert financial() == baseline
assert SecurityLoginSession.objects.filter(revoked_at__isnull=True).count() == 0
assert Session.objects.count() == 0
after = verify_audit_chain()
assert after["event_count"] == before["event_count"] + 3
with patch("security.replacement_identity.require_local_console"):
    report = collect_replacement_financial_report(source_isolated=True)
    assert report["trial_by_currency"] == [
        {"currency": "AFN", "debit": "125.50", "credit": "125.50"},
        {"currency": "USD", "debit": "10.25", "credit": "10.25"}]
    assert report["party_balances"] == [{"currency": "USD", "party_id": data["party_id"],
        "balance_type": "RECEIVABLE", "debit": "10.25", "credit": "0.00", "balance": "10.25", "line_count": 1}]
    assert all(row["reconciled"] for row in report["party_control_totals"])
    assert report["stock_and_avco"] == [{"product_id": data["product_id"], "warehouse_id": data["warehouse_id"],
        "quantity": 7, "avco_afn": "10.0000", "rounded_avco_extension_afn": "70.00"}]
    assert next(row for row in report["account_balances"] if row["account_code"] == "1110")["balance"] == "-10.25"
    assert report["unattributed_party_lines"] == report["unknown_currency_lines"] == 0
    assert collect_replacement_financial_report(source_isolated=True, expected_report=report) == report
    try: collect_replacement_financial_report(source_isolated=True, expected_report={**report, "unknown_currency_lines": 1})
    except RecoveryReconciliationError: pass
    else: raise AssertionError("mismatched independent report accepted")
assert verify_audit_chain() == after
assert financial() == baseline
connection.close()
assert verify_audit_chain() == after
connection.close()
print("RESTORED GM: new MFA key, old session/owner revoked, rollback and financial history verified")
"""
        seen = []
        def exercise(db):
            env = os.environ.copy()
            env.pop("DJANGO_SETTINGS_MODULE", None)
            result = subprocess.run([sys.executable, "-c", child], input=json.dumps({
                "database": db, "snapshot": snapshot, "owner": owner, "owner_row": owner_row.pk,
                "assignment": assignment.pk, "party_id": party.pk, "product_id": product.pk,
                "warehouse_id": warehouse.pk}), env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("RESTORED GM:", result.stdout)
            seen.append(True)
        if connection.vendor == "sqlite":
            original = service._verify_sqlite_snapshot
            def inspect(path, payload):
                result = original(path, payload)
                exercise({"ENGINE": "django.db.backends.sqlite3", "NAME": str(path),
                          "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 20}})
                return result
            target = "_verify_sqlite_snapshot"
        else:
            original = service._read_postgresql_restore
            def inspect(cursor):
                result = original(cursor)
                name = cursor.connection.info.dbname
                self.assertTrue(name.startswith("hb_restore_verify_"))
                exercise({"ENGINE": "django.db.backends.postgresql", **pg, "NAME": name})
                return result
            target = "_read_postgresql_restore"
        with patch.object(service, target, side_effect=inspect):
            result = verify_offline_recovery(backup_path=backup["backup_path"], checkpoint_path=backup["checkpoint_path"],
                bundle_path=bundle, recovery_secret=secret, trusted_public_sha256=metadata["trusted_public_sha256"],
                vendor=connection.vendor, restore_database_config=pg)
        self.assertTrue(result["valid"])
        self.assertEqual(seen, [True])
        self.assertEqual(self._temporary_databases(), before_dbs)
        self.assertEqual(verify_audit_chain(), live)
        gm.refresh_from_db()
        owner_row.refresh_from_db()
        self.assertTrue(gm.check_password("Fixture-old-GM-Password-2026!"))
        self.assertIsNone(owner_row.consumed_at)
        self.assertEqual(SecurityLoginSession.objects.filter(user=gm, revoked_at__isnull=True).count(), 1)
        self.assertEqual(SecurityLoginSession.objects.filter(user=staff, revoked_at__isnull=True).count(), 1)
        self.assertEqual(Session.objects.filter(session_key="odr-historical").count(), 1)
        self.assertEqual(SecurityMFADevice.objects.filter(user=staff, status=MFADeviceStatus.ACTIVE).count(), 1)
        self.assertEqual(SecurityRecoveryCode.objects.filter(user=staff, used_at__isnull=True).count(), 10)
        print(f"ODR RESTORED GM [{connection.vendor}]: isolated identity, financial report comparison, failure rollback, source unchanged")



    def test_readiness_rejects_inconsistent_signed_financial_snapshot(self):
        from accounting.models import JournalEntry
        from security.offline_recovery import create_recovery_bundle, verify_offline_recovery

        # Deliberate corruption in the synthetic test DB only, bypassing model
        # guards. A valid signature is not evidence of internal journal balance.
        JournalEntry.objects.filter(pk=self.entry.pk).update(total_credit=Decimal("125.51"))
        backup = self._backup()
        live = verify_audit_chain()
        before_dbs = self._temporary_databases()
        bundle = self.root / "readiness.hbr"
        secret = b"R" * 32
        metadata = create_recovery_bundle(bundle, provider=self.provider, recovery_secret=secret,
            encryption_id=self.provider.active_backup_encryption_key_id(),
            signing_id=self.provider.active_checkpoint_signing_key_id())
        pg = None
        if connection.vendor == "postgresql":
            pg = {k: str(connection.settings_dict.get(k) or "") for k in ("NAME", "USER", "PASSWORD", "PORT")}
            pg["HOST"] = "127.0.0.1"
        kwargs = dict(backup_path=backup["backup_path"], checkpoint_path=backup["checkpoint_path"],
                      bundle_path=bundle, recovery_secret=secret, trusted_public_sha256=metadata["trusted_public_sha256"],
                      vendor=connection.vendor, restore_database_config=pg, include_readiness=True)
        with self.assertRaisesMessage(BackupError, "independently selected checkpoint"):
            verify_offline_recovery(**kwargs)
        with self.assertRaisesMessage(BackupError, "posted journal totals"):
            verify_offline_recovery(**kwargs, trusted_checkpoint_sha256=backup["checkpoint_sha256"])
        self.assertEqual(self._temporary_databases(), before_dbs)
        self.assertEqual(verify_audit_chain(), live)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.total_credit, Decimal("125.51"))
        print(f"ODR READINESS [{connection.vendor}]: authenticated inconsistent journal rejected; source unchanged and cleanup verified")
