from base64 import b64encode
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from security.login_lockout import (
    _fingerprint,
    is_login_rate_limited,
    record_password_failure,
    request_source_fingerprint,
    username_fingerprint,
)
from security.mfa_models import (
    SecurityAccountLockout,
    SecurityLoginAttempt,
    SecurityLoginAttemptOutcome,
    SecurityLoginSession,
)
from security.models import (
    AuditAction,
    AuditEvent,
    GMRoleSlot,
    Permission,
    Role,
    RolePermission,
    UserRoleAssignment,
)
from security.session_service import register_login_session


User = get_user_model()
PASSWORD = "Strong-test-password-123"


class AccountLockoutPolicyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="lockout-employee", password=PASSWORD)
        cache.clear()  # isolate the production login throttle across TestCase instances
        self.client = APIClient()

    def _failed_login(self, username=None, password="wrong-password"):
        return self.client.post(
            "/api/v1/security/auth/login/",
            {"username": username or self.user.username, "password": password},
            format="json",
        )

    def test_five_consecutive_password_failures_lock_for_fifteen_minutes(self):
        now = timezone.now()
        from unittest.mock import patch

        with patch("django.utils.timezone.now", return_value=now):
            responses = [self._failed_login() for _ in range(5)]

        self.assertTrue(all(response.status_code == 401 for response in responses))
        state = SecurityAccountLockout.objects.get(user=self.user)
        self.assertEqual(state.failed_password_attempts, 5)
        self.assertEqual(state.locked_until, now + timedelta(minutes=15))
        self.assertEqual(
            SecurityLoginAttempt.objects.filter(
                user=self.user,
                outcome=SecurityLoginAttemptOutcome.PASSWORD_FAILED,
            ).count(),
            5,
        )
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.LOGIN_FAILED).count(), 5)
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.ACCOUNT_LOCKED).count(), 1)

    def test_active_lock_returns_same_generic_error_for_correct_password(self):
        for _ in range(5):
            self._failed_login()
        before = SecurityLoginAttempt.objects.filter(user=self.user).count()

        response = self._failed_login(password=PASSWORD)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data, {"error": "invalid_credentials"})
        self.assertEqual(
            SecurityLoginAttempt.objects.filter(
                user=self.user, outcome=SecurityLoginAttemptOutcome.LOCKED
            ).count(),
            1,
        )
        self.assertEqual(SecurityLoginAttempt.objects.filter(user=self.user).count(), before + 1)
        self.assertFalse(SecurityLoginSession.objects.filter(user=self.user).exists())

    def test_successful_login_resets_consecutive_password_failures(self):
        for _ in range(4):
            self._failed_login()

        response = self._failed_login(password=PASSWORD)

        self.assertEqual(response.status_code, 200, response.data)
        state = SecurityAccountLockout.objects.get(user=self.user)
        self.assertEqual(state.failed_password_attempts, 0)
        self.assertIsNone(state.last_failed_at)
        self.assertIsNone(state.locked_until)
        self.assertTrue(SecurityLoginAttempt.objects.filter(
            user=self.user, outcome=SecurityLoginAttemptOutcome.SUCCESS
        ).exists())

    def test_fifteen_minutes_since_last_failure_resets_counter_before_next_failure(self):
        request = RequestFactory().post("/api/v1/security/auth/login/")
        start = timezone.now()
        for minute in range(4):
            record_password_failure(
                self.user, self.user.username, request,
                at=start + timedelta(minutes=minute),
            )

        record_password_failure(
            self.user, self.user.username, request,
            at=start + timedelta(minutes=18),
        )

        state = SecurityAccountLockout.objects.get(user=self.user)
        self.assertEqual(state.failed_password_attempts, 1)
        self.assertIsNone(state.locked_until)

    def test_unknown_username_is_stored_only_as_keyed_fingerprints(self):
        from security.login_lockout import record_password_failure

        request = RequestFactory().post("/api/v1/security/auth/login/")
        record_password_failure(None, "sensitive-unknown-name", request)

        attempt = SecurityLoginAttempt.objects.latest("id")
        event = AuditEvent.objects.filter(action=AuditAction.LOGIN_FAILED).latest("id")
        self.assertIsNone(attempt.user_id)
        self.assertNotEqual(attempt.username_digest, "sensitive-unknown-name")
        self.assertNotEqual(event.entity_id, "sensitive-unknown-name")
        self.assertNotIn("sensitive-unknown-name", str(event.new_state))
        self.assertNotIn("sensitive-unknown-name", event.reason)

    def test_basic_authentication_failures_capture_the_real_local_source(self):
        token = b64encode(b"lockout-employee:wrong-password").decode("ascii")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Basic {token}")
        source = "192.0.2.44"

        for _ in range(5):
            response = client.get("/api/v1/security/me/", REMOTE_ADDR=source)
            self.assertEqual(response.status_code, 403)

        state = SecurityAccountLockout.objects.get(user=self.user)
        self.assertEqual(state.failed_password_attempts, 5)
        self.assertIsNotNone(state.locked_until)
        attempt = SecurityLoginAttempt.objects.filter(
            user=self.user,
            outcome=SecurityLoginAttemptOutcome.PASSWORD_FAILED,
        ).latest("id")
        expected = request_source_fingerprint(
            RequestFactory().get("/api/v1/security/me/", REMOTE_ADDR=source)
        )
        self.assertEqual(attempt.source_digest, expected)

    def test_password_login_is_rate_limited_by_account_using_existing_ten_per_minute_rate(self):
        now = timezone.now()
        source_request = RequestFactory().post(
            "/api/v1/security/auth/login/", REMOTE_ADDR="198.51.100.20"
        )
        name_digest = username_fingerprint(self.user.username)
        for i in range(10):
            SecurityLoginAttempt.objects.create(
                user=None,
                username_digest=name_digest,
                source_digest=_fingerprint("source", f"198.51.100.{i + 1}"),
                outcome=SecurityLoginAttemptOutcome.PASSWORD_FAILED,
                occurred_at=now - timedelta(seconds=10),
            )

        response = self.client.post(
            "/api/v1/security/auth/login/",
            {"username": self.user.username, "password": PASSWORD},
            format="json",
            REMOTE_ADDR="198.51.100.20",
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["error"], "authentication_rate_limited")
        self.assertFalse(SecurityLoginSession.objects.filter(user=self.user).exists())

    def test_basic_authentication_is_rate_limited_by_local_source(self):
        source = "203.0.113.77"
        source_request = RequestFactory().get(
            "/api/v1/security/me/", REMOTE_ADDR=source
        )
        source_digest = request_source_fingerprint(source_request)
        now = timezone.now()
        for i in range(10):
            SecurityLoginAttempt.objects.create(
                user=None,
                username_digest=username_fingerprint(f"other-account-{i}"),
                source_digest=source_digest,
                outcome=SecurityLoginAttemptOutcome.PASSWORD_FAILED,
                occurred_at=now - timedelta(seconds=5),
            )

        token = b64encode(
            f"{self.user.username}:{PASSWORD}".encode("utf-8")
        ).decode("ascii")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Basic {token}")

        response = client.get("/api/v1/security/me/", REMOTE_ADDR=source)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json(), {"error": "authentication_rate_limited"})

    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_lock_blocks_an_already_registered_employee_session(self):
        UserRoleAssignment.objects.create(
            user=self.user, role=Role.objects.get(code="ACCOUNTANT")
        )
        client = APIClient()
        self.assertTrue(client.login(username=self.user.username, password=PASSWORD))
        register_login_session(self.user, client.session.session_key)
        request = RequestFactory().post("/api/v1/security/auth/login/")
        for _ in range(5):
            record_password_failure(self.user, self.user.username, request)

        response = client.get("/api/v1/security/me/")
        self.assertEqual(response.status_code, 403)
        row = SecurityLoginSession.objects.get(user=self.user)
        self.assertIsNotNone(row.revoked_at)
        self.assertEqual(row.revoke_reason, "ACCOUNT_LOCKED")
        self.assertFalse(
            SecurityLoginSession.objects.filter(user=self.user, revoked_at__isnull=True).exists()
        )

    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_only_verified_gm_can_review_and_unlock_employee_account(self):
        gm = User.objects.create_user(username="lockout-gm", password=PASSWORD)
        gm_role = Role.objects.get(code="GM")
        assignment = UserRoleAssignment.objects.create(user=gm, role=gm_role)
        from security.gm_slot import claim_gm_slot

        claim_gm_slot(assignment)
        for key in ("security.lockout.view", "security.account.unlock"):
            RolePermission.objects.get_or_create(
                role=gm_role, permission=Permission.objects.get(key=key)
            )

        target = User.objects.create_user(username="locked-target", password=PASSWORD)
        now = timezone.now()
        SecurityAccountLockout.objects.create(
            user=target,
            failed_password_attempts=5,
            last_failed_at=now,
            locked_until=now + timedelta(minutes=15),
        )

        client = APIClient()
        client.force_login(gm)
        register_login_session(gm, client.session.session_key, mfa_verified_at=now)

        review = client.get("/api/v1/security/lockouts/")
        self.assertEqual(review.status_code, 200, review.data)
        self.assertEqual(review.data["active_lockouts"][0]["user_id"], target.pk)

        response = client.post(
            f"/api/v1/security/accounts/{target.pk}/unlock/",
            {"reason": "Employee identity verified by the GM"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        state = SecurityAccountLockout.objects.get(user=target)
        self.assertEqual(state.failed_password_attempts, 0)
        self.assertIsNone(state.locked_until)
        event = AuditEvent.objects.filter(
            action=AuditAction.ACCOUNT_UNLOCKED, user=gm, entity_id=str(target.pk)
        ).latest("id")
        self.assertEqual(event.reason, "Employee identity verified by the GM")

    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_accountant_cannot_review_or_unlock_lockouts(self):
        accountant = User.objects.create_user(username="lockout-accountant", password=PASSWORD)
        UserRoleAssignment.objects.create(
            user=accountant, role=Role.objects.get(code="ACCOUNTANT")
        )
        client = APIClient()
        self.assertTrue(client.login(username=accountant.username, password=PASSWORD))
        register_login_session(accountant, client.session.session_key)

        self.assertEqual(client.get("/api/v1/security/lockouts/").status_code, 403)

        target = User.objects.create_user(username="locked-other", password=PASSWORD)
        now = timezone.now()
        SecurityAccountLockout.objects.create(
            user=target, failed_password_attempts=5,
            last_failed_at=now, locked_until=now + timedelta(minutes=15),
        )
        response = client.post(
            f"/api/v1/security/accounts/{target.pk}/unlock/",
            {"reason": "unauthorized attempt"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertIsNotNone(SecurityAccountLockout.objects.get(user=target).locked_until)
