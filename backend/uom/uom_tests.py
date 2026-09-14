"""Phase 4.1 — Unit-of-measure master tests.

Pins interpretation record U-3/R-11: identity only, non-unique names, no
code, no conversion engine, deactivation via UPDATE. Frozen suites untouched.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase

from security.models import AuditAction, AuditEvent

from .models import UnitOfMeasure
from .services import (
    UOMValidationError,
    create_uom,
    resolve_uom,
    set_uom_active,
    update_uom,
)


class UomFixture:
    def setUp(self):
        self.user = get_user_model().objects.create_user("u41user", password="x")

    def _make(self, name="Liter", **kwargs):
        params = {"user": self.user}
        params.update(kwargs)
        return create_uom(name=name, **params)


class UomCreationTests(UomFixture, TestCase):
    def test_create_valid_defaults(self):
        unit = self._make()
        self.assertEqual(unit.name, "Liter")
        self.assertEqual(unit.name_fa, "")
        self.assertTrue(unit.is_active)
        self.assertIsNotNone(unit.created_at)
        event = AuditEvent.objects.get(
            action=AuditAction.CREATE, entity="UnitOfMeasure",
            entity_id=str(unit.pk),
        )
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.new_state["name"], "Liter")

    def test_create_with_farsi_name_and_inactive(self):
        unit = self._make(name="Carton", name_fa="کارتن", is_active=False)
        self.assertEqual(unit.name_fa, "کارتن")
        self.assertFalse(unit.is_active)

    def test_blank_name_rejected_without_row_or_audit(self):
        with self.assertRaises(UOMValidationError):
            self._make(name="")
        self.assertEqual(UnitOfMeasure.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_non_text_name_rejected(self):
        with self.assertRaises(UOMValidationError):
            self._make(name=None)
        self.assertEqual(UnitOfMeasure.objects.count(), 0)

    def test_duplicate_names_allowed(self):
        first = self._make(name="Bag")
        second = self._make(name="Bag")
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(UnitOfMeasure.objects.filter(name="Bag").count(), 2)

    def test_names_trimmed(self):
        unit = self._make(name="  Kg  ")
        self.assertEqual(unit.name, "Kg")

    def test_user_none_allowed_with_null_actor(self):
        unit = create_uom(name="NoActor")
        event = AuditEvent.objects.get(entity="UnitOfMeasure")
        self.assertIsNone(event.user)
        self.assertEqual(event.entity_id, str(unit.pk))

    def test_anonymous_rejected(self):
        with self.assertRaises(UOMValidationError):
            create_uom(name="Ghost", user=AnonymousUser())
        self.assertEqual(UnitOfMeasure.objects.count(), 0)

    def test_db_blank_guard(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UnitOfMeasure.objects.create(name="")
        self.assertEqual(UnitOfMeasure.objects.count(), 0)


class UomUpdateTests(UomFixture, TestCase):
    def test_update_name_with_audit(self):
        unit = self._make()
        updated = update_uom(unit, name="Litre", name_fa="لیتر", user=self.user)
        self.assertEqual(updated.name, "Litre")
        self.assertEqual(updated.name_fa, "لیتر")
        event = AuditEvent.objects.get(
            action=AuditAction.UPDATE, entity="UnitOfMeasure"
        )
        self.assertEqual(event.previous_state["name"], "Liter")
        self.assertEqual(event.new_state["name_fa"], "لیتر")

    def test_update_noop_creates_no_audit(self):
        unit = self._make()
        audits_before = AuditEvent.objects.count()
        update_uom(unit, name="Liter", user=self.user)
        update_uom(unit, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_update_blank_name_rejected(self):
        unit = self._make()
        with self.assertRaises(UOMValidationError):
            update_uom(unit, name=" ", user=self.user)
        unit.refresh_from_db()
        self.assertEqual(unit.name, "Liter")

    def test_deactivate_reactivate_with_reason(self):
        unit = self._make()
        set_uom_active(unit, is_active=False, user=self.user, reason="obsolete")
        unit.refresh_from_db()
        self.assertFalse(unit.is_active)
        event = AuditEvent.objects.filter(
            action=AuditAction.UPDATE, entity="UnitOfMeasure"
        ).order_by("id").last()
        self.assertEqual(event.reason, "obsolete")
        set_uom_active(unit, is_active=True, user=self.user)
        unit.refresh_from_db()
        self.assertTrue(unit.is_active)

    def test_deactivate_noop_creates_no_audit(self):
        unit = self._make()
        audits_before = AuditEvent.objects.count()
        set_uom_active(unit, is_active=True, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_non_text_reason_rejected(self):
        unit = self._make()
        with self.assertRaises(UOMValidationError):
            set_uom_active(unit, is_active=False, reason=["x"])
        unit.refresh_from_db()
        self.assertTrue(unit.is_active)

    def test_resolve_accepts_instance_or_pk(self):
        unit = self._make()
        self.assertEqual(resolve_uom(unit).pk, unit.pk)
        self.assertEqual(resolve_uom(unit.pk).pk, unit.pk)
        with self.assertRaises(UOMValidationError):
            resolve_uom(424242)
        with self.assertRaises(UOMValidationError):
            resolve_uom({"bad": "pk"})
        with self.assertRaises(UOMValidationError):
            resolve_uom(UnitOfMeasure(name="unsaved"))

    def test_audit_failure_leaves_no_orphan(self):
        with mock.patch("uom.services.record_audit_event",
                        side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                self._make(name="Orphan")
        self.assertEqual(UnitOfMeasure.objects.count(), 0)
