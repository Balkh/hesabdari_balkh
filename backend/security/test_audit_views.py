from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from security.models import (
    GMRoleSlot,
    Permission,
    Role,
    RolePermission,
    UserRoleAssignment,
)
from security.mfa_models import SecurityLoginSession
from security.session_service import session_key_digest


@override_settings(ERP_RBAC_ENFORCEMENT=True, ERP_RBAC_ALLOW_AUTHENTICATED_ONLY=False)
class AuditReviewAccessTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.client = APIClient()

    def _login_employee(self, username="audit-accountant"):
        user = self.User.objects.create_user(username=username, password="Strong-audit-test-2026!")
        role, _ = Role.objects.get_or_create(
            code="ACCOUNTANT",
            defaults={"name": "Accountant", "is_active": True},
        )
        UserRoleAssignment.objects.create(user=user, role=role)
        self.client.force_login(user)
        return user

    def _login_gm_with_mfa(self):
        user = self.User.objects.create_user(username="audit-gm", password="Strong-audit-test-2026!")
        role, _ = Role.objects.get_or_create(
            code="GM",
            defaults={"name": "General Manager", "is_active": True, "is_system": True},
        )
        assignment = UserRoleAssignment.objects.create(
            user=user,
            role=role,
            start_at=timezone.now() - timedelta(minutes=1),
        )
        slot = GMRoleSlot.objects.get(code="GM")
        slot.assignment = assignment
        slot.save(update_fields=["assignment", "updated_at"])

        permission, _ = Permission.objects.get_or_create(
            key="audit.report.view",
            defaults={
                "domain": "audit",
                "resource": "report",
                "action": "view",
                "description": "View audit events",
                "is_active": True,
            },
        )
        RolePermission.objects.get_or_create(role=role, permission=permission)

        self.client.force_login(user)
        django_session = self.client.session
        django_session.save()
        session_key = django_session.session_key
        now = timezone.now()
        SecurityLoginSession.objects.create(
            user=user,
            session_key_hash=session_key_digest(session_key),
            slot_number=1,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(minutes=15),
            absolute_expires_at=now + timedelta(hours=12),
            mfa_verified_at=now,
        )
        return user

    def test_accountant_and_ordinary_employee_cannot_view_or_export_audit(self):
        self._login_employee()
        for url in (
            "/api/v1/security/audit/events/",
            "/api/v1/security/audit/events/export/",
            "/api/v1/security/audit/integrity/",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, (url, response.status_code, response.content))

    def test_anonymous_user_cannot_view_audit(self):
        response = self.client.get("/api/v1/security/audit/events/")
        self.assertIn(response.status_code, (401, 403))

    def test_verified_singleton_gm_can_view_audit_and_head_reuses_get(self):
        self._login_gm_with_mfa()
        get_response = self.client.get("/api/v1/security/audit/events/")
        self.assertEqual(get_response.status_code, 200, get_response.content)
        self.assertTrue(get_response.data["integrity"]["valid"])

        head_response = self.client.head("/api/v1/security/audit/events/")
        self.assertEqual(head_response.status_code, 200, head_response.content)

    def test_verified_singleton_gm_export_requires_export_capability(self):
        self._login_gm_with_mfa()
        role = Role.objects.get(code="GM")
        permission = Permission.objects.get(key="audit.report.export")
        # The canonical GM seed includes export authority; remove it to prove
        # the route independently enforces its dedicated permission.
        RolePermission.objects.filter(role=role, permission=permission).delete()
        denied = self.client.get("/api/v1/security/audit/events/export/")
        self.assertEqual(denied.status_code, 403)

        RolePermission.objects.get_or_create(role=role, permission=permission)
        allowed = self.client.get("/api/v1/security/audit/events/export/")
        self.assertEqual(allowed.status_code, 200, allowed.content)
        self.assertIn("attachment; filename=", allowed["Content-Disposition"])
