"""W0-2A / R1 — fresh-database bootstrap compatibility tests (Checkpoint D).

Contract: W0-2A §24.5 (fresh-database bootstrap compatibility requirement)
plus the implementation-mission Section 9 requirements. The Django test
database is created by running every migration, so it contains exactly the
seeded RBAC reference rows (security.0003) that a fresh migrated production
database would contain — which is what these tests reason about.
"""
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase

from accounting.coa import CANONICAL_COA
from accounting.models import Account
from categories.models import Category
from currencies.models import Currency
from security.models import (
    AuditAction,
    AuditEvent,
    Permission,
    Role,
    RolePermission,
    UserPermissionOverride,
    UserRoleAssignment,
    UserWarehouseScope,
)
from warehouses.models import Warehouse

User = get_user_model()


def bootstrap(**kwargs):
    output = StringIO()
    call_command("bootstrap_fresh_database", stdout=output, **kwargs)
    return output.getvalue()


class SeededReferenceRowsBootstrapTests(TestCase):
    def test_rbac_reference_rows_present_on_migrated_database(self):
        """The premise of these tests: the migrated test DB carries the
        canonical RBAC reference rows and nothing else."""
        self.assertEqual(Permission.objects.count(), 162)
        self.assertEqual(Role.objects.count(), 3)
        self.assertEqual(RolePermission.objects.count(), 266)
        self.assertFalse(UserRoleAssignment.objects.exists())
        self.assertFalse(UserPermissionOverride.objects.exists())
        self.assertFalse(UserWarehouseScope.objects.exists())

    def test_fresh_migrated_database_bootstraps_despite_reference_rows(self):
        output = bootstrap()
        self.assertIn("Bootstrap completed", output)
        self.assertEqual(Account.objects.count(), len(CANONICAL_COA))
        self.assertEqual(set(Currency.objects.values_list("code", flat=True)), {"AFN", "USD"})
        self.assertTrue(
            AuditEvent.objects.filter(
                entity="SystemBootstrap",
                reference="fresh-database-v1",
                action=AuditAction.CREATE,
            ).exists()
        )

    def test_second_bootstrap_run_is_idempotent_with_reference_rows(self):
        bootstrap()
        counts_before = (
            Account.objects.count(),
            Currency.objects.count(),
            AuditEvent.objects.count(),
            Role.objects.count(),
            Permission.objects.count(),
            RolePermission.objects.count(),
        )
        output = bootstrap()
        self.assertIn("no data changed", output)
        counts_after = (
            Account.objects.count(),
            Currency.objects.count(),
            AuditEvent.objects.count(),
            Role.objects.count(),
            Permission.objects.count(),
            RolePermission.objects.count(),
        )
        self.assertEqual(counts_before, counts_after)


class UserSpecificAuthorizationRowsBlockTests(TestCase):
    def test_user_role_assignment_blocks_first_bootstrap(self):
        user = User.objects.create_user(username="assignment-blocker")
        role = Role.objects.get(code="ACCOUNTANT")
        UserRoleAssignment.objects.create(user=user, role=role)

        with self.assertRaisesMessage(CommandError, "security.UserRoleAssignment"):
            bootstrap()

        self.assertEqual(Account.objects.count(), 0)
        self.assertEqual(Currency.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_user_permission_override_blocks_first_bootstrap(self):
        user = User.objects.create_user(username="override-blocker")
        permission = Permission.objects.get(key="fiscal.period.view")
        UserPermissionOverride.objects.create(
            user=user, permission=permission, effect="ALLOW"
        )

        with self.assertRaisesMessage(CommandError, "security.UserPermissionOverride"):
            bootstrap()

        self.assertEqual(Account.objects.count(), 0)
        self.assertEqual(Currency.objects.count(), 0)

    def test_user_warehouse_scope_blocks_first_bootstrap(self):
        user = User.objects.create_user(username="scope-blocker")
        warehouse = Warehouse.objects.create(name="Bootstrap Blocker WH")
        UserWarehouseScope.objects.create(user=user, warehouse=warehouse)

        with self.assertRaisesMessage(CommandError, "security.UserWarehouseScope"):
            bootstrap()

        self.assertEqual(Account.objects.count(), 0)
        self.assertEqual(Currency.objects.count(), 0)

    def test_user_row_still_blocks_bootstrap(self):
        """The existing auth.User blocker is untouched by the exemption."""
        User.objects.create_user(username="plain-user-blocker")
        with self.assertRaisesMessage(CommandError, "auth.User"):
            bootstrap()

    def test_security_reference_exemption_is_model_level_per_contract(self):
        """§24.5 approves a MODEL-level exemption for exactly
        security.Role / security.Permission / security.RolePermission (the
        same granularity as the existing ContentType/auth.Permission
        exemptions). Additional rows in those three models are therefore
        reference-data rows and do not block bootstrap; user-specific
        authorization rows always do (tests above). Stricter canonical-row
        counting would be an invention beyond the approved contract."""
        Role.objects.create(code="SHIFT_SUPERVISOR", name="Shift Supervisor")

        output = bootstrap()

        self.assertIn("Bootstrap completed", output)
        self.assertTrue(Role.objects.filter(code="SHIFT_SUPERVISOR").exists())
        self.assertEqual(Account.objects.count(), len(CANONICAL_COA))

    def test_operator_entered_erp_data_still_blocks_bootstrap(self):
        Category.objects.create(name="Pre-existing category")

        with self.assertRaisesMessage(CommandError, "categories.Category"):
            bootstrap()

        self.assertEqual(Account.objects.count(), 0)


class RollbackAndNoOverwriteTests(TestCase):
    def test_audit_failure_rolls_back_accounting_rows_but_keeps_reference_rows(self):
        with patch(
            "accounting.management.commands.bootstrap_fresh_database.record_audit_event",
            side_effect=RuntimeError("simulated audit storage failure"),
        ):
            with self.assertRaisesMessage(RuntimeError, "simulated audit storage failure"):
                bootstrap()

        self.assertEqual(Account.objects.count(), 0)
        self.assertEqual(Currency.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)
        # The seeded RBAC reference rows are outside the bootstrap
        # transaction and must be untouched by the rollback.
        self.assertEqual(Permission.objects.count(), 162)
        self.assertEqual(Role.objects.count(), 3)
        self.assertEqual(RolePermission.objects.count(), 266)

    def test_existing_financial_setup_is_never_overwritten(self):
        bootstrap()
        currency = Currency.objects.get(code="USD")
        currency.name = "Operator-approved USD label"
        currency.save(update_fields=["name"])

        with self.assertRaises(CommandError):
            bootstrap()

        currency.refresh_from_db()
        self.assertEqual(currency.name, "Operator-approved USD label")
