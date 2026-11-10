from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from security.authorization import AuthContext, DENY_MFA_REQUIRED, resolve
from security.models import GMRoleSlot, Role, UserRoleAssignment


class GMAuthContextMfaTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="mfa-required-gm")
        role, _ = Role.objects.get_or_create(
            code="GM",
            defaults={"name": "General Manager", "is_active": True},
        )
        assignment = UserRoleAssignment.objects.create(user=self.user, role=role)
        slot = GMRoleSlot.objects.get(code="GM")
        slot.assignment = assignment
        slot.save(update_fields=["assignment", "updated_at"])

    def test_basic_auth_for_active_gm_never_satisfies_mfa(self):
        from rest_framework.authentication import BasicAuthentication

        request = RequestFactory().get("/api/v1/security/me/")
        request.user = self.user
        request.successful_authenticator = BasicAuthentication()
        context = AuthContext.from_request(request)

        self.assertTrue(context.is_basic_only)
        self.assertTrue(context.requires_mfa)
        self.assertFalse(context.mfa_verified)
        decision = resolve(
            self.user,
            "security.account.view_own",
            auth_context=context,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, DENY_MFA_REQUIRED)

    def test_staff_and_superuser_flags_do_not_create_gm_mfa_identity(self):
        from rest_framework.authentication import BasicAuthentication

        ordinary = get_user_model().objects.create_user(
            username="not-the-gm", is_staff=True, is_superuser=True
        )
        request = RequestFactory().get("/api/v1/security/me/")
        request.user = ordinary
        request.successful_authenticator = BasicAuthentication()
        self.assertFalse(AuthContext.from_request(request).requires_mfa)

    def test_gm_configured_employee_mfa_denies_basic_only_access(self):
        from security.mfa_models import SecurityMFARequirement
        from rest_framework.authentication import BasicAuthentication

        employee = get_user_model().objects.create_user(username="mfa-required-employee")
        SecurityMFARequirement.objects.create(
            user=employee,
            is_required=True,
            updated_by=self.user,
            reason="owner policy test",
        )
        request = RequestFactory().get("/api/v1/security/me/")
        request.user = employee
        request.successful_authenticator = BasicAuthentication()
        context = AuthContext.from_request(request)
        self.assertTrue(context.requires_mfa)
        decision = resolve(
            employee,
            "security.account.view_own",
            auth_context=context,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, DENY_MFA_REQUIRED)

    def test_registered_session_mfa_evidence_is_user_bound(self):
        from django.contrib.sessions.backends.db import SessionStore
        from security.session_service import register_login_session

        now = timezone.now()
        store = SessionStore()
        store["_auth_user_id"] = str(self.user.pk)
        store["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
        store.save()
        register_login_session(
            self.user, store.session_key, mfa_verified_at=now, at=now
        )
        request = RequestFactory().get("/api/v1/security/me/")
        request.user = self.user
        request.session = store
        context = AuthContext.from_request(request)
        self.assertEqual(context.session_user_id, self.user.pk)
        self.assertTrue(context.requires_mfa)
        self.assertTrue(context.mfa_verified)
