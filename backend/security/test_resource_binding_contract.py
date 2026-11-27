"""W0-2A / R1 correction — resource-binding contract tests (§16.1 step 9).

Pins the approved contract that per-operation resource binding is
SERVER-OWNED operation metadata, independent of the permission's
``scope_policy`` (§16.1 step 9, §16.2 pseudocode, §15A classification
framework):

- a target-bound operation resolves and validates its target from
  persisted rows REGARDLESS of scope_policy — ``NONE`` waives
  warehouse/object authorization restrictions, never target resolution;
- target resolution re-resolves from persisted rows (fresh fetch plus
  declared required parents), so unsaved instances, fabricated pks,
  wrong types, and unresolvable required parents are denied;
- explicit ALLOW candidates pass the same mandatory gate (no bypass);
- shipped WAREHOUSE_REQUIRED / OBJECT_REQUIRED behavior and protected GM
  authority are unchanged.

Target-bound NONE scenarios are exercised through the documented
server-owned registration seam (``register_operation_binding``) — the
same mechanism the owning API batch (W0-2B) uses to declare per-operation
bindings. No shipped catalog key classification, scope policy, or seed
set is modified by these tests; seam registrations are test-scoped and
always cleaned up.
"""
from django.contrib.auth import get_user_model
from django.db import OperationalError
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone

from security.authorization import (
    BINDING_TARGET_SELF_USER,
    BINDING_TARGET_WAREHOUSE,
    _ResourceBinding,
    _resolve_persisted_target,
    register_binding_target_kind,
    register_operation_binding,
    unregister_binding_target_kind,
    unregister_operation_binding,
)
from security.models import (
    OverrideEffect,
    Permission,
    Role,
    RolePermission,
    UserPermissionOverride,
    UserRoleAssignment,
    UserWarehouseScope,
)
from warehouses.models import Warehouse

from security.test_authorization_resolver import ResolverTestBase

User = get_user_model()

NONE_KEY = "reporting.dashboard.view"  # NONE policy, undeclared binding (§15A)
WR_KEY = "inventory.movement.view"  # WAREHOUSE_REQUIRED, shipped binding
OR_KEY = "security.account.view_own"  # OBJECT_REQUIRED, shipped binding


class ResourceBindingContractTests(ResolverTestBase):
    """Contract tests for target binding independent of scope_policy."""

    def setUp(self):
        super().setUp()
        self.actor = User.objects.create_user(
            username="binding_actor", password="x", is_staff=True
        )
        self.role, _ = Role.objects.get_or_create(
            code="BINDTEST", defaults={"name": "Binding Test Role"}
        )
        UserRoleAssignment.objects.create(user=self.actor, role=self.role)
        self.warehouse = Warehouse.objects.create(name="Binding Warehouse")
        self.linked_keys = []

    def tearDown(self):
        # Seam registrations are test-scoped: always remove them.
        for key in self.linked_keys:
            unregister_operation_binding(key)
        unregister_binding_target_kind("BINDTEST_SCOPE_ROW")
        super().tearDown()

    def grant(self, key):
        permission = Permission.objects.get(key=key)
        RolePermission.objects.get_or_create(role=self.role, permission=permission)
        return permission

    def declare_target_bound_none(self, key, **binding_kwargs):
        """Declare (test-scoped) a target-bound binding on a NONE key."""
        binding = _ResourceBinding(
            is_target_bound=True,
            target_kind=binding_kwargs.pop("target_kind", BINDING_TARGET_WAREHOUSE),
            **binding_kwargs,
        )
        register_operation_binding(key, binding)
        self.linked_keys.append(key)
        return binding

    # ------------------------------------------------------------------
    # 1) target-bound + NONE denies a missing target
    # ------------------------------------------------------------------
    def test_target_bound_none_denies_missing_target(self):
        self.grant(NONE_KEY)
        self.declare_target_bound_none(NONE_KEY)

        decision = self.resolve(self.actor, NONE_KEY, resource=None)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    # ------------------------------------------------------------------
    # 2) target-bound + NONE denies non-persisted / wrong-type targets
    # ------------------------------------------------------------------
    def test_target_bound_none_denies_non_persisted_or_wrong_type_target(self):
        self.grant(NONE_KEY)
        self.declare_target_bound_none(NONE_KEY)

        unsaved = Warehouse(name="unsaved")  # pk=None — never persisted
        decision = self.resolve(self.actor, NONE_KEY, resource=unsaved)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

        fabricated = Warehouse(name="ghost", pk=10**9)  # no such persisted row
        decision = self.resolve(self.actor, NONE_KEY, resource=fabricated)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

        wrong_type = User.objects.create_user(username="not_a_warehouse")
        decision = self.resolve(self.actor, NONE_KEY, resource=wrong_type)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    # ------------------------------------------------------------------
    # 3) target-bound + NONE denies an unresolvable required parent
    # ------------------------------------------------------------------
    def test_target_bound_none_denies_unresolvable_required_parent(self):
        self.grant(NONE_KEY)
        register_binding_target_kind("BINDTEST_SCOPE_ROW", UserWarehouseScope)
        self.declare_target_bound_none(
            NONE_KEY,
            target_kind="BINDTEST_SCOPE_ROW",
            required_parent_paths=("granted_by",),
        )

        orphan = UserWarehouseScope.objects.create(
            user=self.actor, warehouse=self.warehouse
        )  # granted_by NULL — declared-required parent unresolvable
        decision = self.resolve(self.actor, NONE_KEY, resource=orphan)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

        other_warehouse = Warehouse.objects.create(name="Attributed Warehouse")
        attributed = UserWarehouseScope.objects.create(
            user=self.actor,
            warehouse=other_warehouse,
            granted_by=self.actor,
        )  # required parent resolves from persisted rows
        decision = self.resolve(self.actor, NONE_KEY, resource=attributed)
        self.assertTrue(decision.allowed, decision)

    def test_database_failure_during_target_resolution_is_fail_closed(self):
        self.grant(NONE_KEY)
        binding = self.declare_target_bound_none(NONE_KEY)

        # A missing row is an expected SCOPE_DENIED; an operational database
        # failure is unexpected and must reach the resolver's FAIL_CLOSED
        # exception boundary rather than being mislabeled as a missing row.
        with patch.object(
            Warehouse._default_manager,
            "get",
            side_effect=OperationalError("simulated database outage"),
        ):
            with self.assertRaises(OperationalError):
                _resolve_persisted_target(binding, self.warehouse)

        with patch(
            "security.authorization._resolve_persisted_target",
            side_effect=OperationalError("simulated database outage"),
        ):
            with self.assertLogs("security.authorization", level="ERROR"):
                decision = self.resolve(
                    self.actor, NONE_KEY, resource=self.warehouse
                )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "FAIL_CLOSED")

    # ------------------------------------------------------------------
    # 4) valid persisted target for NONE passes with NO warehouse
    #    restriction
    # ------------------------------------------------------------------
    def test_target_bound_none_valid_target_passes_without_warehouse_restriction(self):
        self.grant(NONE_KEY)
        self.declare_target_bound_none(NONE_KEY)
        # Deliberately NO UserWarehouseScope rows for the actor: policy NONE
        # must not impose the M6 warehouse restriction — only binding
        # validation applies.
        self.assertFalse(
            UserWarehouseScope.objects.filter(user=self.actor).exists()
        )

        decision = self.resolve(self.actor, NONE_KEY, resource=self.warehouse)

        self.assertTrue(decision.allowed, decision)
        self.assertEqual(decision.reason, "ROLE_GRANT")

    # ------------------------------------------------------------------
    # 5) a genuine collection (non-target-bound) NONE operation needs no
    #    target
    # ------------------------------------------------------------------
    def test_collection_none_passes_without_target(self):
        self.grant(NONE_KEY)
        # A collection is valid only when explicitly declared server-side.
        register_operation_binding(
            NONE_KEY, _ResourceBinding(is_target_bound=False)
        )
        self.linked_keys.append(NONE_KEY)

        decision = self.resolve(self.actor, NONE_KEY, resource=None)
        self.assertTrue(decision.allowed, decision)
        self.assertEqual(decision.reason, "ROLE_GRANT")

        # A different NONE key with a grant remains UNDECLARED and denied.
        undeclared_key = "security.account.view"
        self.grant(undeclared_key)
        decision = self.resolve(self.actor, undeclared_key, resource=None)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    # ------------------------------------------------------------------
    # UNDECLARED NONE operations are not implicit collections
    # ------------------------------------------------------------------
    def test_undeclared_none_denies_role_grant_with_or_without_resource(self):
        self.grant(NONE_KEY)

        decision = self.resolve(self.actor, NONE_KEY, resource=None)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")
        self.assertIn("9:SCOPE_DENIED:binding-undeclared", decision.trace)

        # Supplying a resource cannot implicitly declare the operation.
        decision = self.resolve(self.actor, NONE_KEY, resource=self.warehouse)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    def test_undeclared_none_denies_explicit_user_allow(self):
        permission = Permission.objects.get(key=NONE_KEY)
        UserPermissionOverride.objects.create(
            user=self.actor,
            permission=permission,
            effect=OverrideEffect.ALLOW,
        )

        decision = self.resolve(self.actor, NONE_KEY, resource=None)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")
        self.assertIn("9:SCOPE_DENIED:binding-undeclared", decision.trace)

        decision = self.resolve(self.actor, NONE_KEY, resource=self.warehouse)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    # ------------------------------------------------------------------
    # 6) explicit user ALLOW cannot bypass target binding
    # ------------------------------------------------------------------
    def test_explicit_allow_cannot_bypass_target_binding(self):
        self.grant(NONE_KEY)
        self.declare_target_bound_none(NONE_KEY)
        UserPermissionOverride.objects.create(
            user=self.actor,
            permission=Permission.objects.get(key=NONE_KEY),
            effect=OverrideEffect.ALLOW,
        )

        decision = self.resolve(self.actor, NONE_KEY, resource=None)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

        fabricated = Warehouse(name="ghost", pk=10**9)
        decision = self.resolve(self.actor, NONE_KEY, resource=fabricated)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

        decision = self.resolve(self.actor, NONE_KEY, resource=self.warehouse)
        self.assertTrue(decision.allowed, decision)
        self.assertEqual(decision.reason, "USER_ALLOW")
        self.assertEqual(decision.source, "USER")

    # ------------------------------------------------------------------
    # 7) shipped WAREHOUSE_REQUIRED / OBJECT_REQUIRED behavior unchanged
    # ------------------------------------------------------------------
    def test_warehouse_required_and_object_required_unchanged(self):
        self.grant(WR_KEY)
        self.grant(OR_KEY)

        # WAREHOUSE_REQUIRED: scope still mandatory, from the M6 registry.
        decision = self.resolve(self.actor, WR_KEY, resource=self.warehouse)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

        UserWarehouseScope.objects.create(user=self.actor, warehouse=self.warehouse)
        decision = self.resolve(self.actor, WR_KEY, resource=self.warehouse)
        self.assertTrue(decision.allowed, decision)
        self.assertEqual(decision.reason, "ROLE_GRANT")

        other = Warehouse.objects.create(name="Other Warehouse")
        decision = self.resolve(self.actor, WR_KEY, resource=other)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

        # OBJECT_REQUIRED: self-scope equality still enforced.
        decision = self.resolve(self.actor, OR_KEY, resource=self.actor)
        self.assertTrue(decision.allowed, decision)
        other_user = User.objects.create_user(username="somebody_else")
        decision = self.resolve(self.actor, OR_KEY, resource=other_user)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    # ------------------------------------------------------------------
    # 8) protected GM authority and gate position unchanged
    # ------------------------------------------------------------------
    def test_protected_gm_authority_unchanged(self):
        gm = User.objects.create_user(username="binding_gm", password="x")
        gm_role, _ = Role.objects.get_or_create(code="GM", defaults={"name": "GM"})
        gm_assignment = UserRoleAssignment.objects.create(user=gm, role=gm_role)
        # W0-2B singleton GM (owner decision): the fixture represents the
        # approved single holder by claiming the authoritative slot. The
        # pinned semantics are unchanged: GM capability applies at step 5 —
        # BEFORE the resource-binding gate — and target validation for
        # operation-aware calls still runs before a protected-GM allow.
        from security.gm_slot import claim_gm_slot

        claim_gm_slot(gm_assignment)
        # GM capability set is the seeded role grant union (0003): the WR key
        # is inside it, so GM authority applies at step 5 — BEFORE the
        # resource-binding gate — and is unchanged by this correction.
        fabricated = Warehouse(name="ghost", pk=10**9)

        decision = self.resolve(gm, WR_KEY, resource=fabricated)
        self.assertTrue(decision.allowed, decision)
        self.assertEqual(decision.reason, "GM_PROTECTED")
        self.assertEqual(decision.source, "GM")

        decision = self.resolve(gm, NONE_KEY, resource=None)
        self.assertTrue(decision.allowed, decision)
        self.assertEqual(decision.reason, "GM_PROTECTED")

    # ------------------------------------------------------------------
    # Seam contract: declarations fail loud (server-owned, explicit)
    # ------------------------------------------------------------------
    def test_binding_seam_rejects_unknown_keys_and_undeclared_kinds(self):
        with self.assertRaises(ValueError):
            register_operation_binding(
                "not.in.catalog", _ResourceBinding(is_target_bound=True)
            )
        with self.assertRaises(ValueError):
            register_operation_binding(
                NONE_KEY,
                _ResourceBinding(is_target_bound=True, target_kind="NO_SUCH_KIND"),
            )
        # The shipped registry covers every WAREHOUSE_REQUIRED /
        # OBJECT_REQUIRED key (import-time completeness validation).
        self.assertEqual(
            len(
                [
                    key
                    for key, entry in _shipped_bindings().items()
                    if entry.is_target_bound
                ]
            ),
            12,
        )


def _shipped_bindings():
    from security.authorization import _OPERATION_RESOURCE_BINDINGS

    return dict(_OPERATION_RESOURCE_BINDINGS)
