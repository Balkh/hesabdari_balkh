"""R2 operation-aware resolver tests; R1 legacy tests remain unchanged."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from fiscal_periods.models import FiscalPeriod
from security.authorization import (
    AuthContext,
    TargetReference,
    resolve_operation,
)
from security.models import Permission, Role, RolePermission, UserRoleAssignment
from security.operation_registry import (
    COLLECTION,
    OBJECT,
    OperationSpec,
    TARGET_URL_KWARG,
)


User = get_user_model()


class OperationAwareResolverTests(TestCase):
    def setUp(self):
        self.gm = User.objects.create_user(username="r2-gm")
        gm_role = Role.objects.get(code="GM")
        UserRoleAssignment.objects.create(user=self.gm, role=gm_role)
        self.ctx = AuthContext(session_user_id=self.gm.pk)

    def test_gm_object_operation_denies_missing_target(self):
        operation = OperationSpec(
            operation_id="test.fiscal.close",
            permission_key="fiscal.period.close",
            binding_kind=OBJECT,
            target_kind="FISCAL_PERIOD",
            target_source=TARGET_URL_KWARG,
            target_kwarg="pk",
        )
        decision = resolve_operation(
            self.gm,
            operation,
            auth_context=self.ctx,
            target_reference=TargetReference("FISCAL_PERIOD", 10**9),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    def test_gm_collection_operation_rejects_unexpected_target(self):
        operation = OperationSpec(
            operation_id="test.fiscal.list",
            permission_key="fiscal.period.view",
            binding_kind=COLLECTION,
        )
        decision = resolve_operation(
            self.gm,
            operation,
            auth_context=self.ctx,
            target_reference=TargetReference("FISCAL_PERIOD", 1),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    def test_gm_object_operation_allows_existing_target(self):
        period = FiscalPeriod.objects.create(
            name="R2 resolver target",
            start_date="2026-01-01",
            end_date="2026-12-31",
        )
        operation = OperationSpec(
            operation_id="test.fiscal.close.valid",
            permission_key="fiscal.period.close",
            binding_kind=OBJECT,
            target_kind="FISCAL_PERIOD",
            target_source=TARGET_URL_KWARG,
            target_kwarg="pk",
        )
        decision = resolve_operation(
            self.gm,
            operation,
            auth_context=self.ctx,
            target_reference=TargetReference("FISCAL_PERIOD", period.pk),
        )
        self.assertTrue(decision.allowed, decision)
        self.assertEqual(decision.reason, "GM_PROTECTED")

    def test_legacy_key_only_resolver_keeps_r1_entry_point(self):
        from security.authorization import resolve

        # The legacy function remains present and independently callable;
        # its exact behavior remains pinned by the original R1 test module.
        self.assertTrue(callable(resolve))
