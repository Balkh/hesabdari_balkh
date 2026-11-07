from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from security.mfa import totp_code, verify_recovery_code
from security.mfa_models import (
    MFADeviceStatus,
    SecurityLoginSession,
    SecurityMFADevice,
    SecurityMFARequirement,
    SecurityRecoveryCode,
)
from security.mfa_service import begin_mfa_enrollment, confirm_mfa_enrollment
from security.models import GMRoleSlot, Role, UserRoleAssignment
from security.session_service import register_login_session, session_key_digest


class TestKeyProvider:
    def __init__(self):
        self.key = b"Q" * 32

    def active_key_id(self):
        return "test-mfa-view-key"

    def get_key(self, key_id):
        if key_id != "test-mfa-view-key":
            raise KeyError(key_id)
        return self.key


@override_settings(
    ERP_RBAC_ENFORCEMENT=True,
    ERP_MFA_KEY_PROVIDER="security.test_mfa_views.TestKeyProvider",
)
class EmployeeMFAApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="mfa-api-employee",
            password="Strong-test-password-123",
        )
        self.client = APIClient()
        self.assertTrue(self.client.login(
            username=self.user.username, password="Strong-test-password-123"
        ))
        register_login_session(self.user, self.client.session.session_key)

    def _enroll_directly(self, now):
        provider = TestKeyProvider()
        started = begin_mfa_enrollment(self.user, provider=provider)
        confirm_mfa_enrollment(
            self.user,
            totp_code(started["secret"], timestamp=now.timestamp()),
            provider=provider,
            at=now,
        )
        return started["secret"]

    def test_employee_enrollment_returns_material_then_ten_codes_once(self):
        started = self.client.post(
            "/api/v1/security/mfa/enroll/start/", {}, format="json"
        )
        self.assertEqual(started.status_code, 201, started.data)
        self.assertTrue(started.data["otpauth_uri"].startswith("otpauth://totp/"))
        device = SecurityMFADevice.objects.get(pk=started.data["device_id"])
        self.assertEqual(device.status, MFADeviceStatus.PENDING)
        self.assertNotIn(
            started.data["secret"].encode("ascii"),
            bytes(device.secret_ciphertext),
        )

        now = timezone.now().replace(microsecond=0)
        with patch("django.utils.timezone.now", return_value=now):
            confirmed = self.client.post(
                "/api/v1/security/mfa/enroll/confirm/",
                {"totp_code": totp_code(started.data["secret"], timestamp=now.timestamp())},
                format="json",
            )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(len(confirmed.data["recovery_codes"]), 10)
        self.assertNotIn("secret", confirmed.data)
        self.assertEqual(
            SecurityRecoveryCode.objects.filter(
                user=self.user, used_at__isnull=True
            ).count(),
            10,
        )
        row = SecurityLoginSession.objects.get(
            user=self.user,
            session_key_hash=session_key_digest(self.client.cookies["sessionid"].value),
        )
        self.assertIsNotNone(row.mfa_verified_at)

    def test_basic_auth_cannot_start_employee_mfa_enrollment(self):
        from base64 import b64encode

        client = APIClient()
        token = b64encode(
            b"mfa-api-employee:Strong-test-password-123"
        ).decode("ascii")
        client.credentials(HTTP_AUTHORIZATION="Basic " + token)
        response = client.post(
            "/api/v1/security/mfa/enroll/start/", {}, format="json"
        )
        self.assertIn(response.status_code, (401, 403))

    def test_recovery_rotation_retires_all_previous_codes(self):
        now = timezone.now().replace(microsecond=0)
        secret = self._enroll_directly(now)
        old_codes = [
            row.code_hash
            for row in SecurityRecoveryCode.objects.filter(user=self.user, used_at__isnull=True)
        ]
        later = now + timedelta(seconds=30)
        with patch("django.utils.timezone.now", return_value=later):
            response = self.client.post(
                "/api/v1/security/mfa/recovery/rotate/",
                {
                    "password": "Strong-test-password-123",
                    "totp_code": totp_code(secret, timestamp=later.timestamp()),
                },
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["recovery_codes"]), 10)
        self.assertEqual(
            SecurityRecoveryCode.objects.filter(user=self.user, used_at__isnull=True).count(),
            10,
        )
        self.assertTrue(all(
            SecurityRecoveryCode.objects.filter(code_hash=h, used_at__isnull=False).exists()
            for h in old_codes
        ))

    def test_optional_employee_can_disable_after_password_and_totp(self):
        now = timezone.now().replace(microsecond=0)
        secret = self._enroll_directly(now)
        later = now + timedelta(seconds=30)
        with patch("django.utils.timezone.now", return_value=later):
            response = self.client.post(
                "/api/v1/security/mfa/disable/",
                {
                    "password": "Strong-test-password-123",
                    "totp_code": totp_code(secret, timestamp=later.timestamp()),
                },
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.data)
        device = SecurityMFADevice.objects.get(user=self.user)
        self.assertEqual(device.status, MFADeviceStatus.DISABLED)
        self.assertEqual(
            SecurityLoginSession.objects.filter(
                user=self.user, revoked_at__isnull=True
            ).count(),
            0,
        )

    def test_employee_mfa_required_by_gm_cannot_be_disabled(self):
        now = timezone.now().replace(microsecond=0)
        self._enroll_directly(now)
        updater = get_user_model().objects.create_user(username="policy-owner")
        SecurityMFARequirement.objects.create(
            user=self.user, is_required=True, updated_by=updater, reason="required"
        )
        response = self.client.post(
            "/api/v1/security/mfa/disable/",
            {
                "password": "Strong-test-password-123",
                "totp_code": "000000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            SecurityMFADevice.objects.get(user=self.user).status,
            MFADeviceStatus.ACTIVE,
        )

    def test_gm_cannot_use_employee_self_enrollment_route(self):
        role, _ = Role.objects.get_or_create(
            code="GM", defaults={"name": "General Manager", "is_active": True}
        )
        assignment = UserRoleAssignment.objects.create(user=self.user, role=role)
        slot = GMRoleSlot.objects.get(code="GM")
        slot.assignment = assignment
        slot.save(update_fields=["assignment", "updated_at"])
        response = self.client.post(
            "/api/v1/security/mfa/enroll/start/", {}, format="json"
        )
        self.assertEqual(response.status_code, 403)
