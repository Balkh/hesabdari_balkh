from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIClient

from security.models import (
    AuditAction,
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


    def test_gm_without_verified_mfa_cannot_read_or_export(self):
        self._login_gm_with_mfa()
        SecurityLoginSession.objects.filter(user__username="audit-gm").update(mfa_verified_at=None)
        for url in (
            "/api/v1/security/audit/events/",
            "/api/v1/security/audit/events/export/",
            "/api/v1/security/audit/integrity/",
        ):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_non_gm_even_with_audit_permissions_and_superuser_flag_is_denied(self):
        user = self._login_employee()
        user.is_superuser = True
        user.save(update_fields=["is_superuser"])
        role = Role.objects.get(code="ACCOUNTANT")
        for key in ("audit.report.view", "audit.report.export"):
            RolePermission.objects.get_or_create(role=role, permission=Permission.objects.get(key=key))
        for url in (
            "/api/v1/security/audit/events/",
            "/api/v1/security/audit/events/export/",
            "/api/v1/security/audit/integrity/",
        ):
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.head(url).status_code, 403)

    def test_invalid_filters_do_not_scan_ledger(self):
        self._login_gm_with_mfa()
        for query in ("limit=0", "limit=1001", "before_id=-1", "action=unknown"):
            with patch("security.audit_views.verify_audit_chain") as verify:
                response = self.client.get("/api/v1/security/audit/events/?" + query)
                self.assertEqual(response.status_code, 400)
                verify.assert_not_called()

    def test_integrity_failure_withholds_review_export_and_diagnostic(self):
        from security.audit_chain import AuditChainVerificationError
        self._login_gm_with_mfa()
        for target in ("assert_audit_trigger_schema", "verify_audit_chain"):
            with patch("security.audit_views." + target, side_effect=AuditChainVerificationError("synthetic failure")):
                for url in (
                    "/api/v1/security/audit/events/",
                    "/api/v1/security/audit/events/export/",
                    "/api/v1/security/audit/integrity/",
                ):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 503)
                    self.assertNotIn("events", response.json())
                    self.assertNotIn("synthetic failure", response.content.decode())

    def test_new_metadata_and_review_export_mask_network_and_credentials(self):
        from security.services import record_audit_event
        from security.audit_chain import canonical_json_bytes, immutable_event_payload, verify_audit_chain
        self._login_gm_with_mfa()
        secrets = ("198.51.100.27", "2001:db8::2", "private-agent-value",
                   "private-forwarded-value", "private-auth-value", "private-cookie-value",
                   "private-key-value")
        with transaction.atomic():
            event = record_audit_event(
                action=AuditAction.CREATE, entity="BatchD",
                entity_id="198.51.100.27", reference="user-agent: private-agent-value",
                reason="remote IP: 2001:db8::2",
                new_state={
                    "REMOTE_ADDR": secrets[0],
                    "nested": [{"HTTP_USER_AGENT": secrets[2], "HTTP_X_FORWARDED_FOR": secrets[3]}],
                    "headers": {"Authorization": secrets[4], "Cookie": secrets[5]},
                    "backup_encryption_key": secrets[6],
                    "amount": "125.50", "description": "سند مالی",
                },
                authorization_context={"client_ip": secrets[0], "operation_id": "batch.d"},
            )
        event.refresh_from_db()
        persisted = canonical_json_bytes(immutable_event_payload(event)).decode()
        self.assertEqual(event.new_state["amount"], "125.50")
        self.assertEqual(event.new_state["description"], "سند مالی")
        for secret in secrets:
            self.assertNotIn(secret, persisted)
        self.assertTrue(verify_audit_chain()["valid"])
        for url in (
            "/api/v1/security/audit/events/?entity=BatchD",
            "/api/v1/security/audit/events/export/?entity=BatchD",
            "/api/v1/security/audit/integrity/",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertIn("no-store", response["Cache-Control"])
            for secret in secrets:
                self.assertNotIn(secret, response.content.decode())

    def test_source_fingerprint_uses_only_hmac_not_raw_request_headers(self):
        from security.audit_chain import canonical_json_bytes, immutable_event_payload, verify_audit_chain
        from security.services import record_audit_event
        request = SimpleNamespace(META={
            "REMOTE_ADDR": "198.51.100.77",
            "HTTP_USER_AGENT": "untrusted-agent",
            "HTTP_X_FORWARDED_FOR": "untrusted-forwarded",
            "HTTP_AUTHORIZATION": "untrusted-authorization",
        })
        with patch("security.audit_chain._request_context", return_value=request):
            with transaction.atomic():
                event = record_audit_event(action=AuditAction.CREATE, entity="BatchD")
        event.refresh_from_db()
        self.assertRegex(event.source_fingerprint, r"^[0-9a-f]{64}$")
        payload = canonical_json_bytes(immutable_event_payload(event)).decode()
        for secret in request.META.values():
            self.assertNotIn(secret, payload)
        self.assertTrue(verify_audit_chain()["valid"])

    def test_legacy_display_masks_fields_without_rewriting_hash(self):
        from security.audit_views import _build_audit_events_payload
        from security.audit_chain import verify_audit_chain, calculate_event_hash, immutable_event_payload
        from security.models import AuditEvent, AuditChainHead
        from uuid import uuid4

        # Synthetic historic representation, only in the disposable TestCase.
        head = AuditChainHead.objects.get(pk=1)
        event = AuditEvent(
            action=AuditAction.CREATE, entity="BatchDLegacy",
            entity_id="198.51.100.88", reference="user-agent: legacy-agent",
            reason="remote IP: 198.51.100.88",
            new_state={"HTTP_USER_AGENT": "legacy-agent", "amount": "125.50"},
            event_uuid=uuid4(), prev_event_hash=head.head_hash,
            actor_snapshot={}, authorization_context={},
        )
        event.event_hash = calculate_event_hash(head.head_hash, immutable_event_payload(event))
        event.save(force_insert=True)
        head.head_hash = event.event_hash
        head.last_event = event
        head.save(update_fields=["head_hash", "last_event", "updated_at"])
        initial = verify_audit_chain()
        payload, error = _build_audit_events_payload(SimpleNamespace(query_params={"entity": "BatchDLegacy"}))
        self.assertIsNone(error)
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("198.51.100.88", rendered)
        self.assertNotIn("legacy-agent", rendered)
        self.assertIn("125.50", rendered)
        event.refresh_from_db()
        self.assertEqual(event.entity_id, "198.51.100.88")
        self.assertEqual(verify_audit_chain(), initial)
