"""W0-2B/R2 operation registry tests."""

from django.test import SimpleTestCase

# Import the mounted views so their server-owned declarations are registered.
import security.views
import security.auth_views
import security.mfa_views
import fiscal_periods.views
import purchases.landed_cost_views

from security.operation_registry import (
    COLLECTION,
    OBJECT,
    OPERATION_SPECS,
    OperationSpec,
    TARGET_NONE,
    TARGET_REQUEST_USER,
    TARGET_URL_KWARG,
    erp_operations,
)

from security.checks import (
    EXPECTED_PUBLIC_API_ROUTES,
    _public_route_allowlist_errors,
    _unclassified_api_callback_errors,
)


class OperationSpecValidationTests(SimpleTestCase):
    def test_collection_rejects_any_target_metadata(self):
        with self.assertRaises(ValueError):
            OperationSpec(
                operation_id="test.collection",
                permission_key="fiscal.period.view",
                binding_kind=COLLECTION,
                target_source=TARGET_URL_KWARG,
                target_kwarg="pk",
            )

    def test_object_requires_server_side_source_and_kind(self):
        with self.assertRaises(ValueError):
            OperationSpec(
                operation_id="test.object.missing-source",
                permission_key="fiscal.period.close",
                binding_kind=OBJECT,
                target_kind="FISCAL_PERIOD",
            )

    def test_unknown_catalog_key_is_rejected(self):
        with self.assertRaises(ValueError):
            OperationSpec(
                operation_id="test.unknown",
                permission_key="not.a.permission",
                binding_kind=COLLECTION,
            )

    def test_object_required_permission_cannot_be_a_collection(self):
        with self.assertRaisesMessage(
            ValueError, "OBJECT_REQUIRED catalog operations must bind"
        ):
            OperationSpec(
                operation_id="test.security.me.collection",
                permission_key="security.account.view_own",
                binding_kind=COLLECTION,
            )

    def test_warehouse_required_permission_is_rejected_until_target_binding_exists(self):
        with self.assertRaisesMessage(
            ValueError, "no warehouse-target API operation"
        ):
            OperationSpec(
                operation_id="test.inventory.view.collection",
                permission_key="inventory.movement.view",
                binding_kind=COLLECTION,
            )

    def test_request_user_cannot_choose_another_model(self):
        with self.assertRaises(ValueError):
            OperationSpec(
                operation_id="test.user.invalid-kind",
                permission_key="security.account.view_own",
                binding_kind=OBJECT,
                target_kind="FISCAL_PERIOD",
                target_source=TARGET_REQUEST_USER,
            )

    def test_mounted_route_inventory_has_fourteen_unique_operations(self):
        expected = {
            "security.me.retrieve",
            "security.auth.logout_own",
            "security.mfa.policy.update_employee",
            "fiscal.period.collection.list",
            "fiscal.period.collection.create",
            "fiscal.period.object.close",
            "fiscal.period.object.reopen",
            "fiscal.period.object.lock",
            "fiscal.period.object.unlock",
            "purchases.landedcost.collection.list",
            "purchases.landedcost.collection.create",
            "purchases.landedcost.object.retrieve",
            "purchases.landedcost.object.post",
            "purchases.landedcost.object.reverse",
        }
        self.assertEqual(set(OPERATION_SPECS), expected)
        self.assertEqual(len(OPERATION_SPECS), 14)

    def test_shared_permission_key_can_have_distinct_collection_and_object_operations(self):
        collection = OPERATION_SPECS["purchases.landedcost.collection.list"]
        detail = OPERATION_SPECS["purchases.landedcost.object.retrieve"]
        self.assertEqual(collection.permission_key, detail.permission_key)
        self.assertEqual(collection.binding_kind, COLLECTION)
        self.assertEqual(detail.binding_kind, OBJECT)
        self.assertEqual(detail.target_source, TARGET_URL_KWARG)


    def test_operation_registry_and_view_method_maps_are_immutable(self):
        from security.views import current_user

        with self.assertRaises(TypeError):
            OPERATION_SPECS["test.mutable"] = object()
        with self.assertRaises(TypeError):
            current_user.cls.erp_operation_specs["GET"] = object()


    def test_public_allowlist_is_exact_not_count_only(self):
        self.assertEqual(
            EXPECTED_PUBLIC_API_ROUTES,
            {
                "api/v1/",
                "api/v1/health/",
                "api/v1/health/missing/",
                "api/v1/security/csrf/",
                "api/v1/security/auth/login/",
            },
        )
        # Keep the count constant, but replace a specifically-approved
        # authentication route with an arbitrary business route.
        swapped_routes = [
            "api/v1/",
            "api/v1/health/",
            "api/v1/health/missing/",
            "api/v1/security/csrf/",
            "api/v1/purchases/private-export/",
        ]
        errors = _public_route_allowlist_errors(swapped_routes)
        self.assertEqual(len(errors), 1)
        self.assertIn("api/v1/purchases/private-export/", errors[0].msg)
        self.assertIn("api/v1/security/auth/login/", errors[0].msg)

    def test_public_allowlist_accepts_only_the_five_expected_routes(self):
        self.assertEqual(
            _public_route_allowlist_errors(sorted(EXPECTED_PUBLIC_API_ROUTES)),
            [],
        )

    def test_non_drf_callback_under_api_namespace_is_rejected(self):
        errors = _unclassified_api_callback_errors("api/v1/untracked/", None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "security.E003")
        self.assertIn("not a DRF callback", errors[0].msg)

    def test_non_api_non_drf_callback_is_not_rejected_by_api_guard(self):
        self.assertEqual(
            _unclassified_api_callback_errors("admin/login/", None),
            [],
        )

    def test_every_declared_get_operation_exposes_head(self):
        from security.views import current_user
        from fiscal_periods.views import period_collection
        from purchases.landed_cost_views import (
            landed_cost_collection,
            landed_cost_detail,
        )

        for callback in (
            current_user,
            period_collection,
            landed_cost_collection,
            landed_cost_detail,
        ):
            self.assertIn("head", callback.cls.__dict__)
            self.assertIn("GET", callback.cls.erp_operation_specs)
