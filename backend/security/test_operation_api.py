"""R2 endpoint-level permission ordering and operation selection tests."""

import base64

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from security.models import AuditEvent, Role, UserRoleAssignment
from security.permissions import HasErpOperation, IsAuthenticatedForERP
from security.views import current_user
from fiscal_periods.views import period_collection
from purchases.landed_cost_views import landed_cost_collection


User = get_user_model()


class OperationApiEnforcementTests(TestCase):
    def make_user_with_role(self, username, role_code):
        user = User.objects.create_user(username=username, password="strong-test-password")
        role = Role.objects.get(code=role_code)
        UserRoleAssignment.objects.create(user=user, role=role)
        return user

    def logged_in_client(self, user):
        client = APIClient()
        self.assertTrue(client.login(username=user.username, password="strong-test-password"))
        return client

    def test_authentication_guard_is_first_on_every_r2_view(self):
        for callback in (current_user, period_collection, landed_cost_collection):
            self.assertEqual(
                callback.cls.permission_classes,
                [IsAuthenticatedForERP, HasErpOperation],
            )

    @override_settings(ERP_RBAC_ENFORCEMENT=False)
    def test_flag_off_keeps_authentication_required_but_allows_authenticated_dev_user(self):
        user = User.objects.create_user(username="dev-auth-only", password="strong-test-password")
        client = self.logged_in_client(user)
        self.assertEqual(client.get("/api/v1/fiscal-periods/").status_code, 200)

        anonymous = APIClient()
        before = AuditEvent.objects.count()
        self.assertEqual(anonymous.get("/api/v1/fiscal-periods/").status_code, 403)
        self.assertEqual(AuditEvent.objects.count(), before)

    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_accountant_can_list_fiscal_periods_and_landed_costs(self):
        user = self.make_user_with_role("r2-accountant", "ACCOUNTANT")
        client = self.logged_in_client(user)
        self.assertEqual(client.get("/api/v1/fiscal-periods/").status_code, 200)
        self.assertEqual(client.get("/api/v1/purchases/landed-costs/").status_code, 200)

    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_authenticated_user_without_grant_is_denied(self):
        user = User.objects.create_user(username="r2-no-role", password="strong-test-password")
        client = self.logged_in_client(user)
        before = AuditEvent.objects.count()
        self.assertEqual(client.get("/api/v1/fiscal-periods/").status_code, 403)
        self.assertEqual(AuditEvent.objects.count(), before)

    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_gm_missing_landed_cost_object_is_uniformly_denied_before_view(self):
        user = self.make_user_with_role("r2-gm-missing-target", "GM")
        client = self.logged_in_client(user)
        response = client.get("/api/v1/purchases/landed-costs/999999999/")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("target-resolution", str(response.data))
        self.assertNotIn("SCOPE_DENIED", str(response.data))

    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_head_uses_get_operation_and_options_stays_authenticated(self):
        user = self.make_user_with_role("r2-head-accountant", "ACCOUNTANT")
        client = self.logged_in_client(user)
        from fiscal_periods.models import FiscalPeriod

        before = FiscalPeriod.objects.count()
        self.assertEqual(client.head("/api/v1/fiscal-periods/").status_code, 200)
        self.assertEqual(FiscalPeriod.objects.count(), before)
        self.assertEqual(client.options("/api/v1/fiscal-periods/").status_code, 200)

        anonymous = APIClient()
        self.assertEqual(anonymous.options("/api/v1/fiscal-periods/").status_code, 403)


    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_basic_authentication_uses_the_same_operation_permission(self):
        user = self.make_user_with_role("r2-basic-accountant", "ACCOUNTANT")
        token = base64.b64encode(
            b"r2-basic-accountant:strong-test-password"
        ).decode("ascii")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Basic {token}")

        response = client.get("/api/v1/fiscal-periods/")

        self.assertEqual(response.status_code, 200)

    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_me_endpoint_uses_the_authenticated_users_self_binding(self):
        user = self.make_user_with_role("r2-self-accountant", "ACCOUNTANT")
        client = self.logged_in_client(user)

        response = client.get("/api/v1/security/me/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], user.pk)
        self.assertEqual(response.json()["username"], user.username)

    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_collection_get_and_post_keep_distinct_permission_keys(self):
        user = self.make_user_with_role("r2-method-accountant", "ACCOUNTANT")
        client = self.logged_in_client(user)

        # ACCOUNTANT has fiscal.period.view, but not fiscal.period.create.
        self.assertEqual(client.get("/api/v1/fiscal-periods/").status_code, 200)
        before = AuditEvent.objects.count()
        self.assertEqual(
            client.post("/api/v1/fiscal-periods/", data={}, format="json").status_code,
            403,
        )
        self.assertEqual(AuditEvent.objects.count(), before)

    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_unauthorized_business_posts_are_denied_before_domain_writes(self):
        from fiscal_periods.models import FiscalPeriod
        from purchases.models import LandedCostDocument

        user = User.objects.create_user(
            username="r2-no-role-post", password="strong-test-password"
        )
        client = self.logged_in_client(user)
        period_count = FiscalPeriod.objects.count()
        landed_count = LandedCostDocument.objects.count()
        audit_count = AuditEvent.objects.count()

        self.assertEqual(
            client.post("/api/v1/fiscal-periods/", data={}, format="json").status_code,
            403,
        )
        self.assertEqual(
            client.post("/api/v1/purchases/landed-costs/", data={}, format="json").status_code,
            403,
        )
        self.assertEqual(FiscalPeriod.objects.count(), period_count)
        self.assertEqual(LandedCostDocument.objects.count(), landed_count)
        self.assertEqual(AuditEvent.objects.count(), audit_count)
