"""W0-2A / R1 — RBAC foundation model tests (Checkpoint A).

Contract: W0-2A_RBAC_OFFLINE_SECURITY_DESIGN_DRAFT.md §14 (M1–M6 temporal
semantics, uniqueness, deletion policies) at approved commit e0d7db4.
These tests pin the schema contract; the temporal grant SERVICES remain
CONTRACT-ONLY for W0-2B (§24.2) and are deliberately absent here.
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from security.models import (
    OverrideEffect,
    Permission,
    Role,
    RolePermission,
    RevocationKind,
    UserPermissionOverride,
    UserRoleAssignment,
    UserWarehouseScope,
)
from warehouses.models import Warehouse

User = get_user_model()


def make_permission(key="inventory.movement.view", **overrides):
    domain, resource, action = key.split(".")
    fields = {
        "key": key,
        "domain": domain,
        "resource": resource,
        "action": action,
        "description": "test permission",
    }
    fields.update(overrides)
    return Permission.objects.create(**fields)


class RoleModelTests(TestCase):
    def test_required_fields_and_defaults(self):
        role = Role.objects.create(code="GM", name="General Manager")
        self.assertTrue(role.is_active)
        self.assertFalse(role.is_system)
        self.assertIsNotNone(role.created_at)
        self.assertIsNotNone(role.updated_at)

    def test_code_is_unique_case_sensitively(self):
        Role.objects.create(code="GM", name="General Manager")
        # Same code, different case: distinct under default case-sensitive
        # collation of both supported engines.
        role2 = Role.objects.create(code="gm", name="lowercase identity")
        self.assertEqual(Role.objects.count(), 2)
        self.assertNotEqual(role2.code, "GM")

    def test_duplicate_code_rejected(self):
        Role.objects.create(code="GM", name="General Manager")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Role.objects.create(code="GM", name="duplicate")

    def test_full_clean_requires_code_and_name(self):
        role = Role(code="", name="")
        with self.assertRaises(Exception):
            role.full_clean()


class PermissionModelTests(TestCase):
    def test_field_decomposition_and_defaults(self):
        perm = make_permission("purchases.landedcost.reverse")
        self.assertEqual(perm.domain, "purchases")
        self.assertEqual(perm.resource, "landedcost")
        self.assertEqual(perm.action, "reverse")
        self.assertFalse(perm.is_sensitive)
        self.assertTrue(perm.is_active)

    def test_key_is_unique(self):
        make_permission("cash.cashaccount.view")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_permission("cash.cashaccount.view")

    def test_distinct_from_django_auth_permission(self):
        """security.Permission is the RBAC catalog row, not auth.Permission."""
        from django.contrib.auth.models import Permission as AuthPermission

        self.assertNotEqual(Permission._meta.db_table, AuthPermission._meta.db_table)

    def test_deactivation_instead_of_deletion_is_representable(self):
        perm = make_permission("audit.report.view")
        perm.is_active = False
        perm.save(update_fields=["is_active"])
        perm.refresh_from_db()
        self.assertFalse(perm.is_active)


class RolePermissionModelTests(TestCase):
    def setUp(self):
        self.role = Role.objects.create(code="ACCOUNTANT", name="Accountant")
        self.perm = make_permission("accounting.report.view")

    def test_unique_role_permission(self):
        RolePermission.objects.create(role=self.role, permission=self.perm)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RolePermission.objects.create(role=self.role, permission=self.perm)

    def test_permission_protected_from_deletion_while_granted(self):
        RolePermission.objects.create(role=self.role, permission=self.perm)
        with self.assertRaises(ProtectedError):
            self.perm.delete()

    def test_role_cascade_removes_only_structural_grant_rows(self):
        """§14.8: M3 role deletion CASCADEs grant rows; catalog rows survive."""
        RolePermission.objects.create(role=self.role, permission=self.perm)
        self.role.delete()
        self.assertFalse(RolePermission.objects.exists())
        self.assertTrue(Permission.objects.filter(pk=self.perm.pk).exists())


class TemporalGrantRowTestsMixin:
    """Shared §14.1/§14.2/§14.4 behavior for M4/M5/M6 grant tables."""

    def make_target(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def make_row(self, target, **overrides):  # pragma: no cover - overridden
        raise NotImplementedError

    def setUp(self):
        self.user = User.objects.create_user(username="grant-user")
        self.actor = User.objects.create_user(username="grant-actor")
        self.target = self.make_target()

    def test_actor_metadata_preserved_and_protected(self):
        row = self.make_row(self.target, granted_by=self.actor)
        self.assertEqual(row.granted_by, self.actor)
        with self.assertRaises(ProtectedError):
            self.actor.delete()

    def test_user_protected_from_deletion(self):
        self.make_row(self.target)
        with self.assertRaises(ProtectedError):
            self.user.delete()

    def test_indefinite_window_allowed(self):
        row = self.make_row(self.target)
        self.assertIsNone(row.end_at)
        self.assertIsNotNone(row.start_at)

    def test_bounded_window_allowed(self):
        now = timezone.now()
        row = self.make_row(self.target, start_at=now, end_at=now + timezone.timedelta(hours=1))
        self.assertGreater(row.end_at, row.start_at)

    def test_invalid_window_rejected_by_check_constraint(self):
        now = timezone.now()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_row(self.target, start_at=now, end_at=now - timezone.timedelta(hours=1))

    def test_equal_start_and_end_rejected(self):
        now = timezone.now()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_row(self.target, start_at=now, end_at=now)

    def test_one_live_row_per_slot(self):
        self.make_row(self.target)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_row(self.target)

    def test_closed_row_frees_slot_for_new_live_row(self):
        """§14.4: the partial unique covers non-closed rows only."""
        now = timezone.now()
        closed = self.make_row(
            self.target,
            start_at=now - timezone.timedelta(days=2),
            end_at=now - timezone.timedelta(days=1),
            revoked_at=now - timezone.timedelta(hours=1),
            revocation_kind=RevocationKind.MANUAL,
        )
        self.assertIsNotNone(closed.revoked_at)
        replacement = self.make_row(self.target)
        self.assertIsNone(replacement.revoked_at)
        # Both rows coexist: history preserved, one live row.
        self.assertEqual(self.row_model.objects.filter(user=self.user).count(), 2)
        self.assertEqual(
            self.row_model.objects.filter(user=self.user, revoked_at__isnull=True).count(),
            1,
        )

    def test_revocation_metadata_optional_until_closed(self):
        row = self.make_row(self.target)
        self.assertIsNone(row.revoked_at)
        self.assertIsNone(row.revoked_by)
        self.assertIsNone(row.revocation_kind)

    def test_revocation_kind_choices(self):
        self.assertEqual(
            set(RevocationKind.values), {"MANUAL", "EXPIRED", "SUPERSEDED"}
        )

    def test_temporal_state_predicate_semantics(self):
        """§14.2: only ACTIVE rows grant; SCHEDULED/EXPIRED/CLOSED do not."""
        now = timezone.now()
        active = self.make_row(self.target, start_at=now - timezone.timedelta(hours=1))
        scheduled = self.make_row(
            self.make_target(),
            start_at=now + timezone.timedelta(hours=1),
        )
        expired_unsettled = self.make_row(
            self.make_target(),
            start_at=now - timezone.timedelta(hours=2),
            end_at=now - timezone.timedelta(hours=1),
        )
        self.assertTrue(self.row_model.objects.filter(pk=active.pk).exists())
        # SCHEDULED and EXPIRED rows exist but are outside the ACTIVE predicate.
        for row in (scheduled, expired_unsettled):
            self.assertFalse(
                self.row_model.objects.filter(
                    pk=row.pk,
                    revoked_at__isnull=True,
                    start_at__lte=now,
                    end_at__isnull=True,
                ).exists()
                or self.row_model.objects.filter(
                    pk=row.pk,
                    revoked_at__isnull=True,
                    start_at__lte=now,
                    end_at__gt=now,
                ).exists()
            )


class UserRoleAssignmentTests(TemporalGrantRowTestsMixin, TestCase):
    row_model = UserRoleAssignment

    def make_target(self):
        """Create a distinct role per call so each test row owns its slot."""
        self._role_seq = getattr(self, "_role_seq", 0) + 1
        code = f"SEQ_ROLE_{self._role_seq}"
        role, _ = Role.objects.get_or_create(code=code, defaults={"name": code})
        return role

    def make_row(self, target, **overrides):
        fields = {"user": self.user, "role": target}
        fields.update(overrides)
        return UserRoleAssignment.objects.create(**fields)

    def test_multiple_different_roles_allowed_and_union_ready(self):
        """§14.5: same-slot restriction only; different roles union at resolve time."""
        UserRoleAssignment.objects.create(user=self.user, role=self.make_target())
        UserRoleAssignment.objects.create(user=self.user, role=self.make_target())
        self.assertEqual(UserRoleAssignment.objects.filter(user=self.user).count(), 2)


class UserPermissionOverrideTests(TemporalGrantRowTestsMixin, TestCase):
    row_model = UserPermissionOverride

    def make_target(self):
        """Create a distinct catalog row per call so each test row owns its slot."""
        self._perm_seq = getattr(self, "_perm_seq", 0) + 1
        n = self._perm_seq
        key = f"testseq.override{n}.view"
        perm, _ = Permission.objects.get_or_create(
            key=key,
            defaults={
                "domain": "testseq",
                "resource": f"override{n}",
                "action": "view",
                "description": "override-test row",
            },
        )
        return perm

    def make_row(self, target, **overrides):
        fields = {
            "user": self.user,
            "permission": target,
            "effect": overrides.pop("effect", OverrideEffect.ALLOW),
        }
        fields.update(overrides)
        return UserPermissionOverride.objects.create(**fields)

    def test_effect_choices(self):
        self.assertEqual(set(OverrideEffect.values), {"ALLOW", "DENY"})

    def test_live_uniqueness_is_effect_independent(self):
        """§14.4 (revised): one live row per (user, permission) across effects."""
        self.make_row(self.target, effect=OverrideEffect.ALLOW)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.make_row(self.target, effect=OverrideEffect.DENY)

    def test_closed_allow_permits_live_deny(self):
        now = timezone.now()
        self.make_row(
            self.target,
            effect=OverrideEffect.ALLOW,
            start_at=now - timezone.timedelta(hours=2),
            end_at=now - timezone.timedelta(hours=1),
            revoked_at=now,
            revocation_kind=RevocationKind.MANUAL,
        )
        deny = self.make_row(self.target, effect=OverrideEffect.DENY)
        self.assertEqual(deny.effect, OverrideEffect.DENY)


class UserWarehouseScopeTests(TemporalGrantRowTestsMixin, TestCase):
    row_model = UserWarehouseScope

    def make_target(self):
        """Create a distinct warehouse per call so each test row owns its slot."""
        self._wh_seq = getattr(self, "_wh_seq", 0) + 1
        warehouse, _ = Warehouse.objects.get_or_create(
            name=f"Scope Test Warehouse {self._wh_seq}"
        )
        return warehouse

    def make_row(self, target, **overrides):
        fields = {"user": self.user, "warehouse": target}
        fields.update(overrides)
        return UserWarehouseScope.objects.create(**fields)

    def test_warehouse_master_protected_while_scoped(self):
        self.make_row(self.target)
        with self.assertRaises(ProtectedError):
            self.target.delete()

    def test_warehouse_relationship_roundtrip(self):
        scope = self.make_row(self.target)
        self.assertEqual(scope.warehouse.name, "Scope Test Warehouse 1")
        self.assertIn(scope, self.target.user_scopes.all())
        self.assertIn(scope, self.user.warehouse_scopes.all())
