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
