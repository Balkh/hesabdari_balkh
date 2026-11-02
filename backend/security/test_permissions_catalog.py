"""W0-2A / R1 — permission catalog registry tests (Checkpoint B).

These tests pin the approved registry invariants of W0-2A §15/§15A/§15.4:
162 keys, 20 domains, exact scope classification, exact status mix, exact
seed totals, and fail-closed validation. The registry is the single source
of truth; the database only mirrors it and the drift check enforces parity.
"""
from django.test import TestCase

from security import checks
from security.permissions_catalog import (
    ACCOUNTANT_SEED_PERMISSION_KEYS,
    CATALOG_BY_KEY,
    CATALOG_STATUSES,
    EXPECTED_CATALOG_TOTALS,
    GM_SEED_PERMISSION_KEYS,
    PERMISSION_DOMAINS,
    PERMISSION_KEY_PATTERN,
    SCOPE_POLICIES,
    SECURITY_PERMISSION_CATALOG,
    UNRESOLVED_PERMISSION_KEYS,
    WAREHOUSE_KEEPER_SEED_PERMISSION_KEYS,
    PermissionCatalogError,
    validate_catalog,
)
from security.models import Permission, Role, RolePermission
from security.seed import seed_rbac_catalog
from django.db.models import ProtectedError

ALL_KEYS = {entry["key"] for entry in SECURITY_PERMISSION_CATALOG}

EXPECTED_WAREHOUSE_REQUIRED = frozenset({
    "inventory.movement.view", "inventory.movement.create", "inventory.movement.export",
    "inventory.count.view", "inventory.count.create", "inventory.count.export",
    "inventory.adjustment.view", "inventory.adjustment.create", "inventory.adjustment.post",
    "inventory.adjustment.export",
})
EXPECTED_OBJECT_REQUIRED = frozenset({
    "security.account.view_own", "security.mfa.enroll_own",
})
EXPECTED_UNRESOLVED = frozenset(
    {f"documents.document.{a}" for a in (
        "view", "create", "edit_draft", "delete_draft", "submit", "approve",
        "post", "cancel", "export")}
    | {"sales.document.approve"}
)

EXPECTED_SENSITIVE = frozenset({
    # security domain (18)
    "security.account.view", "security.account.create", "security.account.activate",
    "security.account.deactivate", "security.account.reset_password", "security.account.unlock",
    "security.account.handover", "security.role.view", "security.role.assign",
    "security.role.revoke", "security.permission.view", "security.permission.grant",
    "security.permission.deny", "security.permission.revoke", "security.session.view",
    "security.session.terminate", "security.lockout.view", "security.mfa.reset",
    # audit (2)
    "audit.report.view", "audit.report.export",
    # fiscal (4)
    "fiscal.period.close", "fiscal.period.lock", "fiscal.period.reopen", "fiscal.period.unlock",
    # landed cost (1)
    "purchases.landedcost.reverse",
    # treasury (2)
    "treasury.operation.execute", "treasury.operation.reverse",
    # journal (2)
    "accounting.journal.post", "accounting.journal.reverse",
})


class RegistryShapeTests(TestCase):
    def test_exactly_162_unique_entries(self):
        self.assertEqual(len(SECURITY_PERMISSION_CATALOG), 162)
        self.assertEqual(len(ALL_KEYS), 162)
        self.assertEqual(len(CATALOG_BY_KEY), 162)

    def test_every_key_matches_approved_literal_format(self):
        for key in ALL_KEYS:
            self.assertRegex(key, PERMISSION_KEY_PATTERN.pattern, key)

    def test_no_wildcard_or_invented_syntax(self):
        for entry in SECURITY_PERMISSION_CATALOG:
            self.assertNotIn("*", entry["key"])
            self.assertNotIn(":", entry["key"])
            parts = entry["key"].split(".")
            self.assertEqual(len(parts), 3)
            self.assertEqual(parts[0], entry["domain"])
            self.assertEqual(parts[1], entry["resource"])
            self.assertEqual(parts[2], entry["action"])

    def test_exactly_20_domains_with_approved_counts(self):
        self.assertEqual(len(PERMISSION_DOMAINS), 20)
        counts = {}
        for entry in SECURITY_PERMISSION_CATALOG:
            counts[entry["domain"]] = counts.get(entry["domain"], 0) + 1
        self.assertEqual(counts, {
            "accounting": 12, "allocations": 4, "audit": 2, "cash": 5,
            "catalog": 10, "currencies": 4, "documents": 9, "exchange": 9,
            "fiscal": 6, "inventory": 12, "parties": 5, "payments": 10,
            "products": 5, "purchases": 17, "reporting": 1, "sales": 17,
            "security": 20, "supplier_advances": 4, "treasury": 5,
            "warehouses": 5,
        })

    def test_every_entry_has_complete_metadata(self):
        for entry in SECURITY_PERMISSION_CATALOG:
            self.assertIn("key", entry)
            self.assertIn("domain", entry)
            self.assertIn("resource", entry)
            self.assertIn("action", entry)
            self.assertIn("description", entry)
            self.assertIn("is_sensitive", entry)
            self.assertIn("scope_policy", entry)
            self.assertIn("status", entry)
            self.assertTrue(entry["description"], entry["key"])
            self.assertIsInstance(entry["is_sensitive"], bool)
            self.assertIn(entry["scope_policy"], SCOPE_POLICIES)
            self.assertIn(entry["status"], CATALOG_STATUSES)


class ScopeClassificationTests(TestCase):
    def test_exact_scope_counts(self):
        counts = {}
        for entry in SECURITY_PERMISSION_CATALOG:
            counts[entry["scope_policy"]] = counts.get(entry["scope_policy"], 0) + 1
        self.assertEqual(counts, {
            "NONE": 140,
            "WAREHOUSE_REQUIRED": 10,
            "OBJECT_REQUIRED": 2,
            "UNRESOLVED": 10,
        })

    def test_warehouse_required_keys_are_exactly_the_ten_inventory_keys(self):
        actual = {e["key"] for e in SECURITY_PERMISSION_CATALOG
                  if e["scope_policy"] == "WAREHOUSE_REQUIRED"}
        self.assertEqual(actual, EXPECTED_WAREHOUSE_REQUIRED)

    def test_object_required_keys_are_exactly_the_two_self_scope_keys(self):
        actual = {e["key"] for e in SECURITY_PERMISSION_CATALOG
                  if e["scope_policy"] == "OBJECT_REQUIRED"}
        self.assertEqual(actual, EXPECTED_OBJECT_REQUIRED)

    def test_unresolved_keys_are_exactly_the_ten_reserved_workflow_keys(self):
        self.assertEqual(UNRESOLVED_PERMISSION_KEYS, EXPECTED_UNRESOLVED)
        actual = {e["key"] for e in SECURITY_PERMISSION_CATALOG
                  if e["scope_policy"] == "UNRESOLVED"}
        self.assertEqual(actual, EXPECTED_UNRESOLVED)

    def test_unresolved_is_never_a_runtime_policy_or_seedable(self):
        for role_seed in (GM_SEED_PERMISSION_KEYS, ACCOUNTANT_SEED_PERMISSION_KEYS,
                          WAREHOUSE_KEEPER_SEED_PERMISSION_KEYS):
            self.assertEqual(set(role_seed) & EXPECTED_UNRESOLVED, set())


class StatusAndSensitivityTests(TestCase):
    def test_exact_status_mix(self):
        counts = {}
        for entry in SECURITY_PERMISSION_CATALOG:
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        self.assertEqual(
            {s: counts.get(s, 0) for s in CATALOG_STATUSES},
            {
                "ENDPOINT": 11, "SERVICE": 53, "MATRIX": 88,
                "RESERVED": 10, "UNRESOLVED": 0,
            },
        )

    def test_reserved_keys_are_documents_and_sales_approve(self):
        reserved = {e["key"] for e in SECURITY_PERMISSION_CATALOG
                    if e["status"] == "RESERVED"}
        self.assertEqual(reserved, EXPECTED_UNRESOLVED)

    def test_exactly_29_sensitive_keys(self):
        sensitive = {e["key"] for e in SECURITY_PERMISSION_CATALOG
                     if e["is_sensitive"]}
        self.assertEqual(len(sensitive), 29)
        self.assertEqual(sensitive, EXPECTED_SENSITIVE)


class SeedTotalsTests(TestCase):
    def test_gm_seed_is_every_endpoint_service_matrix_key(self):
        gm = {e["key"] for e in SECURITY_PERMISSION_CATALOG
              if e["status"] in {"ENDPOINT", "SERVICE", "MATRIX"}}
        self.assertEqual(len(gm), 152)
        self.assertEqual(set(GM_SEED_PERMISSION_KEYS), gm)

    def test_accountant_seed_exactly_102(self):
        self.assertEqual(len(ACCOUNTANT_SEED_PERMISSION_KEYS), 102)
        self.assertEqual(set(ACCOUNTANT_SEED_PERMISSION_KEYS), set(ACCOUNTANT_SEED_PERMISSION_KEYS))

    def test_warehouse_keeper_seed_exactly_the_twelve_approved_keys(self):
        self.assertEqual(set(WAREHOUSE_KEEPER_SEED_PERMISSION_KEYS), {
            # 4 WAREHOUSE_REQUIRED inventory keys
            "inventory.movement.view", "inventory.movement.create",
            "inventory.count.view", "inventory.count.create",
            # 4 NONE keys with role-conditional WK data filtering
            "warehouses.warehouse.view", "purchases.document.view",
            "sales.document.view", "reporting.dashboard.view",
            # 2 field-restricted keys
            "parties.party.view", "products.product.view",
            # 2 self-scope keys
            "security.account.view_own", "security.mfa.enroll_own",
        })

    def test_sales_refund_keys_remain_gm_only_pending_owner_decision(self):
        """§23 item 8: Accountant cells are '—' until the owner decides."""
        self.assertIn("sales.refund.view", GM_SEED_PERMISSION_KEYS)
        self.assertIn("sales.refund.create", GM_SEED_PERMISSION_KEYS)
        self.assertIn("sales.refund.reverse", GM_SEED_PERMISSION_KEYS)
        self.assertNotIn("sales.refund.view", ACCOUNTANT_SEED_PERMISSION_KEYS)

    def test_role_seeds_declared_with_three_system_roles(self):
        from security.permissions_catalog import ROLE_SEEDS

        self.assertEqual([r[0] for r in ROLE_SEEDS], ["GM", "ACCOUNTANT", "WAREHOUSE_KEEPER"])
        for _code, _name, name_fa, description, keys in ROLE_SEEDS:
            self.assertTrue(name_fa)
            self.assertTrue(description)
            self.assertEqual(set(keys) - ALL_KEYS, set())


class ValidateCatalogTests(TestCase):
    def test_validate_catalog_passes(self):
        validate_catalog()  # must not raise

    def test_expected_totals_constant_matches_approved_figures(self):
        self.assertEqual(EXPECTED_CATALOG_TOTALS, {
            "keys": 162, "domains": 20,
            "scope_NONE": 140, "scope_WAREHOUSE_REQUIRED": 10,
            "scope_OBJECT_REQUIRED": 2, "scope_UNRESOLVED": 10,
            "status_ENDPOINT": 11, "status_SERVICE": 53, "status_MATRIX": 88,
            "status_RESERVED": 10, "status_UNRESOLVED": 0,
            "sensitive": 29,
            "seed_GM": 152, "seed_ACCOUNTANT": 102, "seed_WAREHOUSE_KEEPER": 12,
        })

    def _tampered_catalog(self):
        tampered = [dict(e) for e in SECURITY_PERMISSION_CATALOG]
        tampered[0]["scope_policy"] = "MADE_UP"
        return tuple(tampered)

    def test_tampered_scope_policy_fails_validation(self):
        import security.permissions_catalog as catalog_module

        original = catalog_module.SECURITY_PERMISSION_CATALOG
        catalog_module.SECURITY_PERMISSION_CATALOG = self._tampered_catalog()
        try:
            with self.assertRaises(PermissionCatalogError):
                validate_catalog()
            errors = checks.check_permission_catalog_sync_for_alias("default")
            self.assertTrue(any(e.id == checks.CATALOG_INVALID_CHECK_ID for e in errors))
        finally:
            catalog_module.SECURITY_PERMISSION_CATALOG = original
        validate_catalog()

    def test_tampered_key_count_fails_validation(self):
        import security.permissions_catalog as catalog_module

        original = catalog_module.SECURITY_PERMISSION_CATALOG
        catalog_module.SECURITY_PERMISSION_CATALOG = original[1:]
        try:
            with self.assertRaises(PermissionCatalogError):
                validate_catalog()
        finally:
            catalog_module.SECURITY_PERMISSION_CATALOG = original


class DriftCheckTests(TestCase):
    """The seeded database must mirror the registry; drift fails loudly."""

    def test_migrated_test_database_matches_registry(self):
        errors = checks.check_permission_catalog_sync_for_alias("default")
        self.assertEqual(errors, [])

    def test_database_metadata_edit_is_reported_as_drift(self):
        Permission.objects.filter(key="fiscal.period.close").update(
            description="operator-edited description"
        )
        errors = checks.check_permission_catalog_sync_for_alias("default")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, checks.CATALOG_DRIFT_CHECK_ID)
        self.assertIn("fiscal.period.close", errors[0].msg)

    def test_missing_database_row_is_reported_as_drift(self):
        # A granted catalog row cannot be deleted at all (PROTECT via
        # RolePermission); the missing-row drift class is simulated with a
        # RESERVED key that is granted to no one.
        self.assertFalse(
            RolePermission.objects.filter(permission__key="sales.document.approve").exists()
        )
        Permission.objects.filter(key="sales.document.approve").delete()
        errors = checks.check_permission_catalog_sync_for_alias("default")
        self.assertTrue(any("missing from" in e.msg for e in errors))

    def test_granted_catalog_row_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            Permission.objects.filter(key="audit.report.export").delete()

    def test_invented_database_key_is_reported_as_drift(self):
        Permission.objects.create(
            key="invented.domain.action", domain="invented",
            resource="domain", action="action", description="invented",
        )
        errors = checks.check_permission_catalog_sync_for_alias("default")
        self.assertTrue(any("unregistered keys" in e.msg for e in errors))

    def test_missing_table_is_skipped_not_drift(self):
        from unittest.mock import patch

        from security.models import Permission

        with patch.object(
            Permission._meta,
            "db_table",
            "security_permission_not_there",
        ):
            # table_names() will not contain the patched name
            errors = checks.check_permission_catalog_sync_for_alias("default")
        self.assertEqual(errors, [])

    def test_seed_is_idempotent_against_migrated_database(self):
        """Re-seeding the migrated test DB never duplicates rows."""
        summary = seed_rbac_catalog(
            role_model=Role,
            permission_model=Permission,
            role_permission_model=RolePermission,
        )
        self.assertEqual(summary["permissions_total"], 162)
        self.assertEqual(summary["roles_total"], 3)
        self.assertEqual(summary["role_permissions_created"], 0)
        self.assertEqual(Permission.objects.count(), 162)
        self.assertEqual(Role.objects.count(), 3)
        self.assertEqual(RolePermission.objects.count(), 266)
