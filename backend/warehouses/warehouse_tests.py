"""Phase 4.3 — Warehouse master tests (flat Warehouse, OD-1..OD-3).

Pins the approved model: required non-unique name, optional name_fa,
single active flag, no code, no address, no type/default/hierarchy, no
relations, no inventory or financial concepts. Frozen suites untouched.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase

from security.models import AuditAction, AuditEvent

from . import services
from .models import Warehouse
from .services import (
    WarehouseValidationError,
    create_warehouse,
    resolve_warehouse,
    set_warehouse_active,
    update_warehouse,
)


class WarehouseFixture:
    def setUp(self):
        self.user = get_user_model().objects.create_user("w43user", password="x")

    def _make(self, name="Main Godown", **kwargs):
        params = {"user": self.user}
        params.update(kwargs)
        return create_warehouse(name=name, **params)


class WarehouseIdentityTests(WarehouseFixture, TestCase):
    def test_create_valid_defaults(self):
        warehouse = self._make()
        self.assertEqual(warehouse.name, "Main Godown")
        self.assertEqual(warehouse.name_fa, "")
        self.assertTrue(warehouse.is_active)
        self.assertIsNotNone(warehouse.created_at)
        self.assertFalse(hasattr(warehouse, "code"))

    def test_blank_name_rejected_without_row_or_audit(self):
        with self.assertRaises(WarehouseValidationError):
            self._make(name="   ")
        self.assertEqual(Warehouse.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_non_text_name_rejected(self):
        with self.assertRaises(WarehouseValidationError):
            self._make(name=42)
        self.assertEqual(Warehouse.objects.count(), 0)

    def test_texts_trimmed(self):
        warehouse = self._make(name="  Main  ", name_fa="  گدام  ")
        self.assertEqual(warehouse.name, "Main")
        self.assertEqual(warehouse.name_fa, "گدام")

    def test_name_fa_optional_and_stored(self):
        warehouse = self._make(name_fa="گدام اصلی")
        warehouse.refresh_from_db()
        self.assertEqual(warehouse.name_fa, "گدام اصلی")

    def test_duplicate_names_allowed(self):
        first = self._make(name="Same Name")
        second = self._make(name="Same Name", name_fa="تکراری")
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(Warehouse.objects.filter(name="Same Name").count(), 2)

    def test_case_variants_allowed(self):
        self._make(name="Main")
        self._make(name="main")
        self.assertEqual(Warehouse.objects.count(), 2)

    def test_non_text_name_fa_rejected(self):
        with self.assertRaises(WarehouseValidationError):
            self._make(name_fa=700111222)
        self.assertEqual(Warehouse.objects.count(), 0)

    def test_user_none_allowed_anonymous_rejected(self):
        warehouse = create_warehouse(name="NoActor")
        event = AuditEvent.objects.get(entity="Warehouse")
        self.assertIsNone(event.user)
        self.assertEqual(event.entity_id, str(warehouse.pk))
        with self.assertRaises(WarehouseValidationError):
            create_warehouse(name="Ghost", user=AnonymousUser())
        self.assertEqual(Warehouse.objects.count(), 1)

    def test_db_blank_guard(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Warehouse.objects.create(name="")
        self.assertEqual(Warehouse.objects.count(), 0)

    def test_no_forbidden_fields_or_relations(self):
        warehouse = self._make()
        forbidden = [
            "code", "warehouse_code", "address", "location", "street",
            "city", "province", "district", "coordinates", "latitude",
            "longitude", "warehouse_type", "is_main", "is_secondary",
            "is_default", "default_warehouse", "stock", "quantity",
            "available_quantity", "reserved_quantity", "stock_value",
            "cost", "average_cost", "balance", "currency", "account",
            "product", "uom", "party", "category", "updated_at",
        ]
        for field in forbidden:
            self.assertFalse(hasattr(warehouse, field), field)
        self.assertFalse(hasattr(services, "delete_warehouse"))


class WarehouseUpdateTests(WarehouseFixture, TestCase):
    def test_update_partial_with_audit(self):
        warehouse = self._make()
        updated = update_warehouse(warehouse, name_fa="گدام اصلی",
                                   user=self.user)
        self.assertEqual(updated.name_fa, "گدام اصلی")
        event = AuditEvent.objects.get(
            action=AuditAction.UPDATE, entity="Warehouse"
        )
        self.assertEqual(event.previous_state["name_fa"], "")
        self.assertEqual(event.new_state["name_fa"], "گدام اصلی")

    def test_rename_preserves_pk(self):
        warehouse = self._make(name="Main Warehouse")
        pk = warehouse.pk
        renamed = update_warehouse(warehouse, name="Central Warehouse",
                                   user=self.user)
        self.assertEqual(renamed.pk, pk)
        self.assertEqual(Warehouse.objects.get(pk=pk).name,
                         "Central Warehouse")

    def test_update_noop_creates_no_audit(self):
        warehouse = self._make()
        audits_before = AuditEvent.objects.count()
        update_warehouse(warehouse, name="Main Godown", user=self.user)
        update_warehouse(warehouse, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_update_blank_name_rejected(self):
        warehouse = self._make()
        with self.assertRaises(WarehouseValidationError):
            update_warehouse(warehouse, name=" ", user=self.user)
        warehouse.refresh_from_db()
        self.assertEqual(warehouse.name, "Main Godown")

    def test_create_audit_snapshot(self):
        warehouse = self._make(name_fa="گدام")
        event = AuditEvent.objects.get(
            action=AuditAction.CREATE, entity="Warehouse",
            entity_id=str(warehouse.pk),
        )
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.reference, "Main Godown")
        self.assertIsNone(event.previous_state)
        self.assertEqual(event.new_state["name_fa"], "گدام")
        self.assertTrue(event.new_state["is_active"])

    def test_audit_failure_leaves_no_orphan(self):
        with mock.patch("warehouses.services.record_audit_event",
                        side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                self._make()
        self.assertEqual(Warehouse.objects.count(), 0)

    def test_deactivate_reactivate_with_reason(self):
        warehouse = self._make()
        set_warehouse_active(warehouse, is_active=False, user=self.user,
                             reason="relocating")
        warehouse.refresh_from_db()
        self.assertFalse(warehouse.is_active)
        event = AuditEvent.objects.filter(
            action=AuditAction.UPDATE, entity="Warehouse"
        ).order_by("id").last()
        self.assertEqual(event.reason, "relocating")
        set_warehouse_active(warehouse, is_active=True, user=self.user)
        warehouse.refresh_from_db()
        self.assertTrue(warehouse.is_active)

    def test_deactivate_noop_creates_no_audit(self):
        warehouse = self._make()
        audits_before = AuditEvent.objects.count()
        set_warehouse_active(warehouse, is_active=True, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_inactive_warehouse_still_maintainable(self):
        warehouse = self._make()
        set_warehouse_active(warehouse, is_active=False, user=self.user)
        updated = update_warehouse(warehouse, name_fa="بایگانی",
                                   user=self.user)
        self.assertEqual(updated.name_fa, "بایگانی")
        self.assertTrue(
            Warehouse.objects.filter(pk=warehouse.pk).exists())

    def test_resolve_accepts_instance_or_pk(self):
        warehouse = self._make()
        self.assertEqual(resolve_warehouse(warehouse).pk, warehouse.pk)
        self.assertEqual(resolve_warehouse(warehouse.pk).pk, warehouse.pk)
        with self.assertRaises(WarehouseValidationError):
            resolve_warehouse(424242)
        with self.assertRaises(WarehouseValidationError):
            resolve_warehouse("not-a-pk")
        with self.assertRaises(WarehouseValidationError):
            resolve_warehouse(Warehouse(name="unsaved"))
