"""W0-2B/R2 operation registry tests."""

from django.test import SimpleTestCase

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

    def test_request_user_cannot_choose_another_model(self):
        with self.assertRaises(ValueError):
            OperationSpec(
                operation_id="test.user.invalid-kind",
                permission_key="security.account.view_own",
                binding_kind=OBJECT,
                target_kind="FISCAL_PERIOD",
                target_source=TARGET_REQUEST_USER,
            )

    def test_mounted_route_inventory_has_twelve_unique_operations(self):
        expected = {
            "security.me.retrieve",
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
        self.assertEqual(len(OPERATION_SPECS), 12)

    def test_shared_permission_key_can_have_distinct_collection_and_object_operations(self):
        collection = OPERATION_SPECS["purchases.landedcost.collection.list"]
        detail = OPERATION_SPECS["purchases.landedcost.object.retrieve"]
        self.assertEqual(collection.permission_key, detail.permission_key)
        self.assertEqual(collection.binding_kind, COLLECTION)
        self.assertEqual(detail.binding_kind, OBJECT)
        self.assertEqual(detail.target_source, TARGET_URL_KWARG)
