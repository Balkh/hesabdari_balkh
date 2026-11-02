"""W0-2A / R1 — RBAC seed behavior tests (Checkpoint B).

Covers the migrated-database state (the Django test database is created by
running all migrations, so the 0003 seed and 0004 mapping are exercised for
real) plus idempotency, matrix exactness, non-interference with
operator-managed data, and the 0004 legacy-superuser mapping semantics.
"""
import importlib

from django.apps import apps as current_apps
from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase

from security.models import (
    Permission,
    Role,
    RolePermission,
    UserRoleAssignment,
)
from security.permissions_catalog import (
    ACCOUNTANT_SEED_PERMISSION_KEYS,
    GM_SEED_PERMISSION_KEYS,
    WAREHOUSE_KEEPER_SEED_PERMISSION_KEYS,
)
from security.seed import seed_rbac_catalog

User = get_user_model()


def _migration(name):
    return importlib.import_module(f"security.migrations.{name}")


class MigratedCatalogStateTests(TestCase):
    """State produced by migration 0003 on the test database."""

    def test_catalog_fully_seeded(self):
        self.assertEqual(Permission.objects.count(), 162)
        self.assertTrue(
            Permission.objects.filter(key="inventory.movement.view").exists()
        )
        self.assertTrue(Permission.objects.filter(key="documents.document.view").exists())

    def test_three_system_roles_seeded(self):
        roles = {role.code: role for role in Role.objects.all()}
        self.assertEqual(
            set(roles),
            {"GM", "ACCOUNTANT", "WAREHOUSE_KEEPER"},
        )
        for role in roles.values():
            self.assertTrue(role.is_system)
            self.assertTrue(role.is_active)
            self.assertTrue(role.name)
            self.assertTrue(role.name_fa)

    def test_role_permission_matrices_match_the_registry_exactly(self):
        expected = {
            "GM": set(GM_SEED_PERMISSION_KEYS),
            "ACCOUNTANT": set(ACCOUNTANT_SEED_PERMISSION_KEYS),
            "WAREHOUSE_KEEPER": set(WAREHOUSE_KEEPER_SEED_PERMISSION_KEYS),
        }
        for code, keys in expected.items():
            granted = set(
                RolePermission.objects.filter(role__code=code).values_list(
                    "permission__key", flat=True
                )
            )
            self.assertEqual(granted, keys, code)

    def test_no_role_holds_reserved_or_unresolved_keys(self):
        reserved = set(
            Permission.objects.filter(key__in=[
                "sales.document.approve",
                *{f"documents.document.{a}" for a in (
                    "view", "create", "edit_draft", "delete_draft", "submit",
                    "approve", "post", "cancel", "export")},
            ]).values_list("key", flat=True)
        )
        self.assertEqual(len(reserved), 10)
        granted = set(RolePermission.objects.values_list("permission__key", flat=True))
        self.assertEqual(granted & reserved, set())

    def test_sensitive_keys_all_reach_gm(self):
        sensitive = set(
            Permission.objects.filter(is_sensitive=True).values_list("key", flat=True)
        )
        self.assertEqual(len(sensitive), 29)
        gm = set(
            RolePermission.objects.filter(role__code="GM").values_list(
                "permission__key", flat=True
            )
        )
        self.assertEqual(sensitive - gm, set())

    def test_seed_granted_by_is_system_null(self):
        """Seeded links are system-attributed (granted_by NULL, §14.1)."""
        self.assertFalse(RolePermission.objects.exclude(granted_by=None).exists())

    def test_seed_creates_no_user_assignments(self):
        user = User.objects.create_user(username="seed-no-assignment")
        summary = seed_rbac_catalog(
            role_model=Role,
            permission_model=Permission,
            role_permission_model=RolePermission,
        )
        self.assertEqual(summary["role_permissions_created"], 0)
        self.assertFalse(UserRoleAssignment.objects.filter(user=user).exists())
        self.assertFalse(UserRoleAssignment.objects.exists())


class SeedIdempotencyTests(TestCase):
    def test_repeated_seed_is_a_noop(self):
        before = (
            Permission.objects.count(),
            Role.objects.count(),
            RolePermission.objects.count(),
        )
        self.assertEqual(before, (162, 3, 266))
        for _ in range(2):
            seed_rbac_catalog(
                role_model=Role,
                permission_model=Permission,
                role_permission_model=RolePermission,
            )
        self.assertEqual(
            (
                Permission.objects.count(),
                Role.objects.count(),
                RolePermission.objects.count(),
            ),
            before,
        )

    def test_seed_does_not_overwrite_operator_managed_rows(self):
        permission = Permission.objects.get(key="fiscal.period.close")
        permission.description = "operator-approved description"
        permission.save(update_fields=["description"])
        role = Role.objects.get(code="GM")
        role.is_active = False
        role.save(update_fields=["is_active"])

        seed_rbac_catalog(
            role_model=Role,
            permission_model=Permission,
            role_permission_model=RolePermission,
        )

        permission.refresh_from_db()
        role.refresh_from_db()
        self.assertEqual(permission.description, "operator-approved description")
        self.assertFalse(role.is_active)


class CatalogRowProtectionTests(TestCase):
    def test_seeded_permission_with_role_grants_is_protected(self):
        permission = Permission.objects.get(key="accounting.report.view")
        with self.assertRaises(ProtectedError):
            permission.delete()

    def test_system_role_with_assignments_is_protected(self):
        user = User.objects.create_user(username="role-protect-user")
        role = Role.objects.get(code="ACCOUNTANT")
        UserRoleAssignment.objects.create(user=user, role=role)
        with self.assertRaises(ProtectedError):
            role.delete()


class LegacySuperuserMappingTests(TestCase):
    """0004 semantics: exact narrow rule, idempotent, reversible."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = _migration("0004_legacy_superuser_gm_mapping")

    def _run_forward(self):
        self.migration.assign_gm_to_legacy_superusers(
            current_apps, schema_editor=None
        )

    def _run_reverse(self):
        self.migration.remove_migration_created_superuser_gm_assignments(
            current_apps, schema_editor=None
        )

    def test_migration_created_no_assignments_on_empty_database(self):
        """Fresh databases have no users: 0004 must have been a no-op."""
        self.assertEqual(UserRoleAssignment.objects.count(), 0)

    def test_superuser_receives_single_gm_assignment(self):
        superuser = User.objects.create_user(
            username="legacy-super", password="Strong-test-password-123",
            is_superuser=True,
        )
        self._run_forward()
        assignments = UserRoleAssignment.objects.filter(user=superuser)
        self.assertEqual(assignments.count(), 1)
        assignment = assignments.get()
        self.assertEqual(assignment.role.code, "GM")
        self.assertIsNone(assignment.granted_by)
        self.assertIsNone(assignment.end_at)
        self.assertIn("legacy superuser compatibility mapping", assignment.reason)
        self.assertIsNone(assignment.revoked_at)

    def test_forward_run_is_idempotent(self):
        User.objects.create_user(username="legacy-super2", is_superuser=True)
        self._run_forward()
        count = UserRoleAssignment.objects.count()
        self._run_forward()
        self.assertEqual(UserRoleAssignment.objects.count(), count)

    def test_existing_live_gm_assignment_is_not_duplicated(self):
        user = User.objects.create_user(username="already-gm", is_superuser=True)
        gm = Role.objects.get(code="GM")
        UserRoleAssignment.objects.create(
            user=user, role=gm, reason="operator-created assignment",
        )
        self._run_forward()
        self.assertEqual(
            UserRoleAssignment.objects.filter(user=user, role=gm).count(), 1
        )
        self.assertEqual(
            UserRoleAssignment.objects.get(user=user, role=gm).reason,
            "operator-created assignment",
        )

    def test_non_superuser_is_never_assigned(self):
        User.objects.create_user(username="plain-employee")
        self._run_forward()
        self.assertFalse(UserRoleAssignment.objects.exists())

    def test_inactive_superuser_still_mapped_but_inert_by_resolver_contract(self):
        """Assignment rows are created for inactive superusers too; the
        resolver (§16.1 step 2) denies inactive accounts before grants, so
        the row grants nothing while the account is inactive."""
        user = User.objects.create_user(username="inactive-super", is_superuser=True)
        user.is_active = False
        user.save(update_fields=["is_active"])
        self._run_forward()
        self.assertTrue(
            UserRoleAssignment.objects.filter(user=user, role__code="GM").exists()
        )

    def test_no_privilege_escalation_beyond_superusers(self):
        """Exact narrow rule: only is_superuser=True users are mapped."""
        User.objects.create_user(username="staff-not-super", is_staff=True)
        User.objects.create_user(username="super", is_superuser=True)
        self._run_forward()
        assigned_users = set(
            UserRoleAssignment.objects.values_list("user__username", flat=True)
        )
        self.assertEqual(assigned_users, {"super"})

    def test_reverse_removes_only_migration_created_rows(self):
        superuser = User.objects.create_user(username="reverse-super", is_superuser=True)
        other_superuser = User.objects.create_user(
            username="operator-super", is_superuser=True
        )
        gm = Role.objects.get(code="GM")
        operator_row = UserRoleAssignment.objects.create(
            user=other_superuser, role=gm, reason="operator-created assignment",
        )
        self._run_forward()
        self._run_reverse()
        self.assertFalse(
            UserRoleAssignment.objects.filter(user=superuser).exists()
        )
        self.assertTrue(
            UserRoleAssignment.objects.filter(pk=operator_row.pk).exists()
        )
