from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase
from django.conf import settings

from security.backup_service import BackupError, BackupKeyUnavailable, create_signed_checkpoint, verify_signed_checkpoint
from security.offline_recovery import create_recovery_bundle, open_recovery_bundle, parse_recovery_secret
from security.test_backup_service import StaticBackupKeyProvider


class OfflineRecoveryBundleTests(SimpleTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "recovery.hbr"
        self.source = StaticBackupKeyProvider()
        self.secret = b"R" * 32

    def create(self):
        return create_recovery_bundle(self.path, provider=self.source, recovery_secret=self.secret,
            encryption_id=self.source.active_backup_encryption_key_id(),
            signing_id=self.source.active_checkpoint_signing_key_id())

    def test_bundle_roundtrip_pinned_trust_no_private_signer_or_plaintext(self):
        with patch.object(self.source, "get_checkpoint_signing_private_key", side_effect=AssertionError("private key read")) as private:
            metadata = self.create()
            private.assert_not_called()
        data = self.path.read_bytes()
        self.assertNotIn(self.source.encryption_key, data)
        self.assertNotIn(self.source.signing_seed, data)
        recovered = open_recovery_bundle(self.path, recovery_secret=self.secret,
            trusted_public_sha256=metadata["trusted_public_sha256"])
        self.assertEqual(recovered.get_backup_encryption_key(metadata["encryption_id"]), self.source.encryption_key)
        self.assertFalse(hasattr(recovered, "get_checkpoint_signing_private_key"))
        with self.assertRaises(BackupKeyUnavailable):
            recovered.get_backup_encryption_key("other-version")
        with self.assertRaises(BackupKeyUnavailable):
            recovered.get_checkpoint_signing_public_key("other-version")
        checkpoint = self.path.with_suffix(".json")
        create_signed_checkpoint({"event_count": 7}, checkpoint, provider=self.source)
        self.assertEqual(verify_signed_checkpoint(checkpoint, provider=recovered)["event_count"], 7)

    def test_independent_checkpoint_pin_rejects_older_authentic_manifest(self):
        metadata = self.create()
        recovered = open_recovery_bundle(self.path, recovery_secret=self.secret,
            trusted_public_sha256=metadata["trusted_public_sha256"])
        old = self.path.with_name("old.json")
        selected = self.path.with_name("selected.json")
        create_signed_checkpoint({"event_count": 7}, old, provider=self.source)
        chosen = create_signed_checkpoint({"event_count": 8}, selected, provider=self.source)
        self.assertEqual(verify_signed_checkpoint(old, provider=recovered)["event_count"], 7)
        self.assertEqual(verify_signed_checkpoint(selected, provider=recovered,
            trusted_checkpoint_sha256=chosen["sha256"])["event_count"], 8)
        with patch.object(type(recovered), "get_checkpoint_signing_public_key", side_effect=AssertionError("provider accessed before pin check")):
            with self.assertRaisesMessage(BackupError, "independently selected SHA-256"):
                verify_signed_checkpoint(old, provider=recovered,
                    trusted_checkpoint_sha256=chosen["sha256"])
        for malformed in ("", "a"*63, "G"*64):
            with self.assertRaises(BackupError):
                verify_signed_checkpoint(selected, provider=recovered, trusted_checkpoint_sha256=malformed)
        from security.offline_recovery import verify_offline_recovery
        with patch("security.backup_service.decrypt_backup_file") as decrypt:
            with self.assertRaisesMessage(BackupError, "independently selected SHA-256"):
                verify_offline_recovery(backup_path=self.path.with_name("missing.hbak"), checkpoint_path=old,
                    bundle_path=self.path, recovery_secret=self.secret,
                    trusted_public_sha256=metadata["trusted_public_sha256"], vendor="sqlite",
                    trusted_checkpoint_sha256=chosen["sha256"])
            decrypt.assert_not_called()

    def test_wrong_secret_wrong_pin_tamper_and_collision_fail_closed(self):
        metadata = self.create()
        before = self.path.read_bytes()
        pin = metadata["trusted_public_sha256"]
        for secret, fingerprint in ((b"X"*32, pin), (self.secret, "0"*64)):
            with self.assertRaises(BackupError):
                open_recovery_bundle(self.path, recovery_secret=secret, trusted_public_sha256=fingerprint)
        with self.assertRaisesMessage(BackupError, "refusing to overwrite"):
            self.create()
        self.assertEqual(self.path.read_bytes(), before)
        damaged = bytearray(before)
        damaged[-1] ^= 1
        self.path.write_bytes(damaged)
        with self.assertRaisesMessage(BackupError, "authentication failed"):
            open_recovery_bundle(self.path, recovery_secret=self.secret, trusted_public_sha256=pin)
        self.path.write_bytes(before[:20])
        with self.assertRaises(BackupError):
            open_recovery_bundle(self.path, recovery_secret=self.secret, trusted_public_sha256=pin)

    def test_rejects_key_reuse_and_application_directory(self):
        for secret, path in ((self.source.encryption_key, self.path),
                             (self.secret, Path(settings.BASE_DIR) / "forbidden.hbr")):
            with self.assertRaises(BackupError):
                create_recovery_bundle(path, provider=self.source, recovery_secret=secret,
                    encryption_id=self.source.active_backup_encryption_key_id(),
                    signing_id=self.source.active_checkpoint_signing_key_id())
        self.assertFalse(self.path.exists())
        with self.assertRaises(BackupError):
            parse_recovery_secret("short human password")

    def test_wrong_owner_key_and_nonlocal_export_never_read_provider(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from security.emergency_owner_key_service import EmergencyOwnerKeyInvalid
        from security.local_console import LocalConsoleRequiredError
        module = "security.management.commands.create_backup_recovery_bundle"
        with patch(module + ".require_local_console", side_effect=LocalConsoleRequiredError("not local")), patch(module + ".load_backup_key_provider") as load:
            with self.assertRaises(CommandError):
                call_command("create_backup_recovery_bundle", destination=str(self.path),
                    encryption_id="test", signing_id="test", skip_checks=True)
            load.assert_not_called()
        with patch(module + ".require_local_console"), patch(module + ".prompt_secret", return_value="invalid"), patch(module + ".validate_current_gm_emergency_owner_key", side_effect=EmergencyOwnerKeyInvalid("invalid owner key")), patch(module + ".load_backup_key_provider") as load:
            with self.assertRaises(CommandError):
                call_command("create_backup_recovery_bundle", destination=str(self.path),
                    encryption_id="test", signing_id="test", skip_checks=True)
            load.assert_not_called()
        self.assertFalse(self.path.exists())


from security.test_support import AuditTriggerAwareTransactionTestCase


class OwnerRecoveryBundleIssuanceTests(AuditTriggerAwareTransactionTestCase):
    def setUp(self):
        from datetime import timedelta
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        from security.models import GMRoleSlot, Role, UserRoleAssignment
        from security.mfa_models import SecurityEmergencyOwnerKey
        from security.emergency_owner_key_service import generate_emergency_owner_key, emergency_owner_key_digest
        self.gm = get_user_model().objects.create_user(username="odr-owner-fixture", is_active=True)
        role, _ = Role.objects.get_or_create(code="GM", defaults={"name": "General Manager", "is_active": True, "is_system": True})
        assignment = UserRoleAssignment.objects.create(user=self.gm, role=role,
            start_at=timezone.now()-timedelta(minutes=1), reason="synthetic recovery fixture")
        slot = GMRoleSlot.objects.get(code="GM")
        slot.assignment = assignment
        slot.save(update_fields=["assignment", "updated_at"])
        self.owner_key = generate_emergency_owner_key()
        self.owner_row = SecurityEmergencyOwnerKey.objects.create(
            scope=SecurityEmergencyOwnerKey.GM_RECOVERY,
            source=SecurityEmergencyOwnerKey.SOURCE_INITIAL_BOOTSTRAP,
            key_hash=emergency_owner_key_digest(self.owner_key), issued_at=timezone.now(), issued_by=self.gm)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "authorized.hbr"
        self.source = StaticBackupKeyProvider()
        self.secret = b"R"*32

    def issue(self, output):
        from django.core.management import call_command
        module = "security.management.commands.create_backup_recovery_bundle"
        # Only hardware console and secure keyboard input are simulated; GM
        # singleton, owner-key checks, crypto, publication and commit are real.
        with patch(module + ".require_local_console"), patch(module + ".prompt_secret",
            side_effect=[self.owner_key, self.secret.hex(), self.secret.hex()]), patch(
            module + ".load_backup_key_provider", return_value=self.source):
            call_command("create_backup_recovery_bundle", destination=str(self.path),
                encryption_id=self.source.active_backup_encryption_key_id(),
                signing_id=self.source.active_checkpoint_signing_key_id(),
                stdout=output, skip_checks=True)

    def test_authorized_bundle_commits_audit_and_preserves_owner_key(self):
        import hashlib
        from io import StringIO
        from django.db import connection
        from security.audit_chain import verify_audit_chain
        from security.models import AuditEvent, AuditAction
        from security.emergency_owner_key_service import validate_current_gm_emergency_owner_key
        initial = verify_audit_chain()
        output = StringIO()
        self.issue(output)
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        fingerprint = hashlib.sha256(self.source.signing_public).hexdigest()
        event = AuditEvent.objects.get(entity="BACKUP_RECOVERY_BUNDLE", entity_id=digest[:32])
        self.assertEqual(event.user_id, self.gm.pk)
        self.assertEqual(event.action, AuditAction.AUDIT_CHECKPOINT)
        self.assertEqual(event.new_state, {"artifact_sha256": digest})
        connection.close()
        self.assertEqual(verify_audit_chain()["event_count"], initial["event_count"]+1)
        self.assertEqual(validate_current_gm_emergency_owner_key(self.owner_key), self.owner_row.pk)
        self.assertIn(fingerprint, output.getvalue())
        self.assertNotIn(self.owner_key, output.getvalue())
        self.assertNotIn(self.secret.hex(), output.getvalue())
        self.assertNotIn(self.source.encryption_key.hex(), output.getvalue())
        self.assertNotIn(self.source.signing_seed.hex(), output.getvalue())
        recovered = open_recovery_bundle(self.path, recovery_secret=self.secret, trusted_public_sha256=fingerprint)
        self.assertEqual(recovered.get_backup_encryption_key(self.source.active_backup_encryption_key_id()), self.source.encryption_key)
        print("ODR ISSUANCE: real singleton owner, encrypted artifact and committed audit verified")

    def test_head_save_failure_preserves_encrypted_orphan_without_success(self):
        from io import StringIO
        from django.core.management.base import CommandError
        from security.audit_chain import verify_audit_chain
        from security.models import AuditChainHead, AuditEvent
        from security.emergency_owner_key_service import validate_current_gm_emergency_owner_key
        initial = verify_audit_chain()
        output = StringIO()
        reached = []
        def fail(instance, *args, **kwargs):
            self.assertEqual(instance.last_event.entity, "BACKUP_RECOVERY_BUNDLE")
            self.assertTrue(AuditEvent.objects.filter(pk=instance.last_event_id).exists())
            reached.append(instance.last_event_id)
            raise RuntimeError("synthetic final head failure")
        with patch.object(AuditChainHead, "save", autospec=True, side_effect=fail):
            with self.assertRaisesMessage(CommandError, "encrypted bundle was written but audit commit failed"):
                self.issue(output)
        self.assertEqual(len(reached), 1)
        self.assertEqual(verify_audit_chain(), initial)
        self.assertFalse(AuditEvent.objects.filter(entity="BACKUP_RECOVERY_BUNDLE").exists())
        self.assertEqual(validate_current_gm_emergency_owner_key(self.owner_key), self.owner_row.pk)
        self.assertTrue(self.path.is_file())
        before = self.path.read_bytes()
        self.assertNotIn(self.source.encryption_key, before)
        self.assertNotIn("Encrypted recovery bundle created.", output.getvalue())
        with self.assertRaisesMessage(CommandError, "refusing to overwrite"):
            self.issue(output)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(verify_audit_chain(), initial)
        print("ODR ISSUANCE FAILURE: final audit rolled back; encrypted artifact retained without success")

    def test_ambient_transaction_refuses_publication(self):
        from io import StringIO
        from django.core.management.base import CommandError
        from django.db import transaction
        from security.audit_chain import verify_audit_chain
        initial = verify_audit_chain()
        with transaction.atomic():
            with self.assertRaisesMessage(CommandError, "independent commit boundary"):
                self.issue(StringIO())
        self.assertFalse(self.path.exists())
        self.assertEqual(verify_audit_chain(), initial)
