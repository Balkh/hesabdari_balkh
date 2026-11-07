from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from security.gm_slot import GM_SLOT_CODE
from security.mfa import totp_code
from security.mfa_models import MFADeviceStatus, SecurityLoginSession
from security.mfa_service import begin_mfa_enrollment, confirm_mfa_enrollment
from security.models import AuditAction, AuditEvent, GMRoleSlot, Role, UserRoleAssignment
from security.session_service import (
    SessionAdmissionError,
    register_login_session,
    session_key_digest,
)


class TestKeyProvider:
    def __init__(self):
        self.key = b"T" * 32

    def active_key_id(self):
        return "test-login-key"

    def get_key(self, key_id):
        if key_id != "test-login-key":
            raise KeyError(key_id)
        return self.key


class SecurityLoginFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="login-employee",
            password="Strong-test-password-123",
        )
        self.client = APIClient()

    def _make_gm(self):
        role, _ = Role.objects.get_or_create(
            code=GM_SLOT_CODE,
            defaults={"name": "General Manager", "is_active": True},
        )
        assignment = UserRoleAssignment.objects.create(user=self.user, role=role)
        slot = GMRoleSlot.objects.get(code=GM_SLOT_CODE)
        slot.assignment = assignment
        slot.save(update_fields=["assignment", "updated_at"])

    def test_employee_password_login_creates_registered_session_and_audit(self):
        response = self.client.post(
            "/api/v1/security/auth/login/",
            {"username": self.user.username, "password": "Strong-test-password-123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        key = self.client.cookies["sessionid"].value
        record = SecurityLoginSession.objects.get(
            user=self.user,
            session_key_hash=session_key_digest(key),
        )
        self.assertIsNone(record.mfa_verified_at)
        self.assertEqual(record.slot_number, 1)
        self.assertTrue(self.client.session.get("_auth_user_id"))
        event = AuditEvent.objects.filter(
            user=self.user, action=AuditAction.LOGIN, entity="AUTH_SESSION"
        ).latest("id")
        self.assertEqual(event.new_state["mfa_verified"], False)
        self.assertEqual(event.new_state["session_slot"], 1)

    def test_password_only_gm_login_is_refused_until_mfa_enrolled(self):
        self._make_gm()
        response = self.client.post(
            "/api/v1/security/auth/login/",
            {"username": self.user.username, "password": "Strong-test-password-123"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"], "mfa_enrollment_required")
        self.assertEqual(SecurityLoginSession.objects.filter(user=self.user).count(), 0)

    @override_settings(ERP_MFA_KEY_PROVIDER="security.test_auth_views.TestKeyProvider")
    def test_gm_login_requires_totp_and_marks_session_mfa_verified(self):
        self._make_gm()
        start = timezone.now().replace(microsecond=0)
        provider = TestKeyProvider()
        enrollment = begin_mfa_enrollment(self.user, provider=provider)
        confirm_mfa_enrollment(
            self.user,
            totp_code(enrollment["secret"], timestamp=start.timestamp()),
            provider=provider,
            at=start,
        )
        login_at = start + timedelta(seconds=30)
        code = totp_code(enrollment["secret"], timestamp=login_at.timestamp())
        with override_settings(USE_TZ=True):
            from unittest.mock import patch

            with patch("django.utils.timezone.now", return_value=login_at):
                response = self.client.post(
                    "/api/v1/security/auth/login/",
                    {
                        "username": self.user.username,
                        "password": "Strong-test-password-123",
                        "totp_code": code,
                    },
                    format="json",
                )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["mfa_verified"])
        key = self.client.cookies["sessionid"].value
        record = SecurityLoginSession.objects.get(
            user=self.user,
            session_key_hash=session_key_digest(key),
        )
        self.assertIsNotNone(record.mfa_verified_at)

    def test_third_login_denied_without_revoking_existing_sessions(self):
        first = register_login_session(self.user, "preexisting-session-1")
        second = register_login_session(self.user, "preexisting-session-2")
        response = self.client.post(
            "/api/v1/security/auth/login/",
            {"username": self.user.username, "password": "Strong-test-password-123"},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertIsNone(first.revoked_at)
        self.assertIsNone(second.revoked_at)
        self.assertEqual(
            SecurityLoginSession.objects.filter(user=self.user, revoked_at__isnull=True).count(),
            2,
        )

    def test_logout_revokes_session_registry_row(self):
        login = self.client.post(
            "/api/v1/security/auth/login/",
            {"username": self.user.username, "password": "Strong-test-password-123"},
            format="json",
        )
        self.assertEqual(login.status_code, 200, login.data)
        key = self.client.cookies["sessionid"].value
        record = SecurityLoginSession.objects.get(
            user=self.user,
            session_key_hash=session_key_digest(key),
        )
        response = self.client.post("/api/v1/security/auth/logout/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        record.refresh_from_db()
        self.assertIsNotNone(record.revoked_at)
        self.assertEqual(record.revoke_reason, "LOGOUT")


    def test_anonymous_password_login_requires_csrf_cookie_and_header(self):
        from rest_framework.test import APIClient

        client = APIClient(enforce_csrf_checks=True)
        payload = {
            "username": self.user.username,
            "password": "Strong-test-password-123",
        }
        blocked = client.post(
            "/api/v1/security/auth/login/", payload, format="json"
        )
        self.assertEqual(blocked.status_code, 403)

        csrf = client.get("/api/v1/security/csrf/")
        self.assertEqual(csrf.status_code, 200)
        self.assertIn("csrftoken", client.cookies)
        token = client.cookies["csrftoken"].value
        allowed = client.post(
            "/api/v1/security/auth/login/",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(allowed.status_code, 200, allowed.data)
