from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from security.mfa import totp_code
from security.mfa_service import (
    MFAEnrollmentLocked,
    MFAInvalidCode,
    begin_mfa_enrollment,
    confirm_mfa_enrollment,
    consume_recovery_code,
    verify_user_totp,
)
from security.mfa_models import MFADeviceStatus, SecurityMFADevice, SecurityRecoveryCode


class StaticMFAKeyProvider:
    def __init__(self):
        self.key = b"K" * 32

    def active_key_id(self):
        return "test-key-v1"

    def get_key(self, key_id):
        if key_id != "test-key-v1":
            raise KeyError(key_id)
        return self.key


class MFALifecycleServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="mfa-lifecycle", password="Strong-test-password-123"
        )
        self.provider = StaticMFAKeyProvider()

    def test_enrollment_stores_only_ciphertext_and_activates_after_valid_totp(self):
        now = timezone.now().replace(microsecond=0)
        started = begin_mfa_enrollment(self.user, provider=self.provider)
        device = SecurityMFADevice.objects.get(pk=started["device_id"])
        self.assertEqual(device.status, MFADeviceStatus.PENDING)
        self.assertNotIn(started["secret"].encode("ascii"), bytes(device.secret_ciphertext))
        self.assertTrue(started["otpauth_uri"].startswith("otpauth://totp/"))

        codes = confirm_mfa_enrollment(
            self.user,
            totp_code(started["secret"], timestamp=now.timestamp()),
            provider=self.provider,
            at=now,
        )
        device.refresh_from_db()
        self.assertEqual(device.status, MFADeviceStatus.ACTIVE)
        self.assertEqual(len(codes), 10)
        self.assertEqual(
            SecurityRecoveryCode.objects.filter(user=self.user, used_at__isnull=True).count(),
            10,
        )

    def test_totp_counter_cannot_be_replayed(self):
        now = timezone.now().replace(microsecond=0)
        started = begin_mfa_enrollment(self.user, provider=self.provider)
        confirm_mfa_enrollment(
            self.user,
            totp_code(started["secret"], timestamp=now.timestamp()),
            provider=self.provider,
            at=now,
        )
        self.assertFalse(
            verify_user_totp(
                self.user,
                totp_code(started["secret"], timestamp=now.timestamp()),
                provider=self.provider,
                at=now,
            )
        )
        later = now + timedelta(seconds=30)
        self.assertTrue(
            verify_user_totp(
                self.user,
                totp_code(started["secret"], timestamp=later.timestamp()),
                provider=self.provider,
                at=later,
            )
        )

    def test_pending_enrollment_throttles_invalid_attempts(self):
        now = timezone.now().replace(microsecond=0)
        started = begin_mfa_enrollment(self.user, provider=self.provider)
        for _ in range(5):
            with self.assertRaises(MFAInvalidCode):
                confirm_mfa_enrollment(
                    self.user, "not-a-code", provider=self.provider, at=now
                )
        device = SecurityMFADevice.objects.get(pk=started["device_id"])
        self.assertEqual(device.failed_attempts, 5)
        self.assertGreater(device.locked_until, now)
        with self.assertRaises(MFAEnrollmentLocked):
            confirm_mfa_enrollment(
                self.user, "not-a-code", provider=self.provider, at=now
            )

    def test_recovery_code_is_consumed_once(self):
        now = timezone.now()
        code = "ABCDEFGH23456789"
        from security.mfa import hash_recovery_code

        SecurityRecoveryCode.objects.create(
            user=self.user, code_hash=hash_recovery_code(code)
        )
        self.assertTrue(consume_recovery_code(self.user, code, at=now))
        self.assertFalse(consume_recovery_code(self.user, code, at=now))
