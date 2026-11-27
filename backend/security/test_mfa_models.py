from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from security.models import (
    MFADeviceStatus,
    SecurityLoginSession,
    SecurityMFADevice,
    SecurityRecoveryCode,
)


User = get_user_model()


class SecurityMFAModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mfa-user", password="not-a-real-password")

    def make_device(self, *, status=MFADeviceStatus.PENDING, confirmed_at=None):
        return SecurityMFADevice.objects.create(
            user=self.user,
            status=status,
            secret_key_id="windows-key-v1",
            secret_nonce=b"n" * 12,
            secret_ciphertext=b"encrypted-envelope",
            confirmed_at=confirmed_at,
        )

    def test_pending_device_stores_envelope_not_raw_secret(self):
        device = self.make_device()
        self.assertEqual(device.secret_nonce, b"n" * 12)
        self.assertNotIn(b"raw-totp-secret", bytes(device.secret_ciphertext))
        self.assertEqual(device.status, MFADeviceStatus.PENDING)
        self.assertIsNone(device.confirmed_at)

    def test_only_one_active_totp_device_per_user(self):
        now = timezone.now()
        self.make_device(status=MFADeviceStatus.ACTIVE, confirmed_at=now)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_device(status=MFADeviceStatus.ACTIVE, confirmed_at=now)

    def test_pending_device_cannot_claim_confirmation_timestamp(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_device(status=MFADeviceStatus.PENDING, confirmed_at=timezone.now())

    def test_recovery_codes_are_hash_records_and_can_be_consumed_once(self):
        code = SecurityRecoveryCode.objects.create(
            user=self.user,
            code_hash="pbkdf2_sha256$test-salted-one-way-hash",
        )
        self.assertNotEqual(code.code_hash, "RECOVERY-PLAINTEXT")
        self.assertIsNone(code.used_at)
        code.used_at = timezone.now()
        code.save(update_fields=["used_at"])
        code.refresh_from_db()
        self.assertIsNotNone(code.used_at)

    def test_session_registry_stores_digest_and_enforces_expiry_order(self):
        now = timezone.now()
        digest = "a" * 64
        row = SecurityLoginSession.objects.create(
            user=self.user,
            session_key_hash=digest,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(minutes=15),
            absolute_expires_at=now + timedelta(hours=12),
        )
        self.assertEqual(row.session_key_hash, digest)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SecurityLoginSession.objects.create(
                    user=self.user,
                    session_key_hash="b" * 64,
                    created_at=now,
                    last_seen_at=now,
                    idle_expires_at=now + timedelta(hours=13),
                    absolute_expires_at=now + timedelta(hours=12),
                )
