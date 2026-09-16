"""Phase 4.4 — ExchangeHouse master tests (operational master, OD-5/7/9/13).

Pins the approved model: required non-unique name, optional name_fa,
single active flag, no code, no currency, no contact fields, no
relations, no balance/ledger/posting concepts. Frozen suites untouched.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase

from security.models import AuditAction, AuditEvent

from . import services
from .models import ExchangeHouse
from .services import (
    ExchangeHouseValidationError,
    create_exchange_house,
    resolve_exchange_house,
    set_exchange_house_active,
    update_exchange_house,
)


class ExchangeHouseFixture:
    def setUp(self):
        self.user = get_user_model().objects.create_user("e44user", password="x")

    def _make(self, name="Qari Sardar", **kwargs):
        params = {"user": self.user}
        params.update(kwargs)
        return create_exchange_house(name=name, **params)


class ExchangeHouseIdentityTests(ExchangeHouseFixture, TestCase):
    def test_create_valid_defaults(self):
        house = self._make()
        self.assertEqual(house.name, "Qari Sardar")
        self.assertEqual(house.name_fa, "")
        self.assertTrue(house.is_active)
        self.assertIsNotNone(house.created_at)
        self.assertFalse(hasattr(house, "code"))

    def test_blank_name_rejected_without_row_or_audit(self):
        with self.assertRaises(ExchangeHouseValidationError):
            self._make(name="   ")
        self.assertEqual(ExchangeHouse.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_non_text_name_rejected(self):
        with self.assertRaises(ExchangeHouseValidationError):
            self._make(name=42)
        self.assertEqual(ExchangeHouse.objects.count(), 0)

    def test_texts_trimmed(self):
        house = self._make(name="  Sardar  ", name_fa="  صرافی  ")
        self.assertEqual(house.name, "Sardar")
        self.assertEqual(house.name_fa, "صرافی")

    def test_name_fa_optional_and_stored(self):
        house = self._make(name_fa="صرافی سردار")
        house.refresh_from_db()
        self.assertEqual(house.name_fa, "صرافی سردار")

    def test_duplicate_names_allowed(self):
        first = self._make(name="Same Name")
        second = self._make(name="Same Name", name_fa="تکراری")
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(ExchangeHouse.objects.filter(name="Same Name").count(), 2)

    def test_case_variants_allowed(self):
        self._make(name="Sardar")
        self._make(name="sardar")
        self.assertEqual(ExchangeHouse.objects.count(), 2)

    def test_non_text_name_fa_rejected(self):
        with self.assertRaises(ExchangeHouseValidationError):
            self._make(name_fa=700111222)
        self.assertEqual(ExchangeHouse.objects.count(), 0)

    def test_user_none_allowed_anonymous_rejected(self):
        house = create_exchange_house(name="NoActor")
        event = AuditEvent.objects.get(entity="ExchangeHouse")
        self.assertIsNone(event.user)
        self.assertEqual(event.entity_id, str(house.pk))
        with self.assertRaises(ExchangeHouseValidationError):
            create_exchange_house(name="Ghost", user=AnonymousUser())
        self.assertEqual(ExchangeHouse.objects.count(), 1)

    def test_db_blank_guard(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExchangeHouse.objects.create(name="")
        self.assertEqual(ExchangeHouse.objects.count(), 0)

    def test_no_forbidden_fields_or_relations(self):
        house = self._make()
        forbidden = [
            "code", "exchange_code", "account_code", "number", "sequence",
            "currency", "currency_id", "default_currency", "base_currency",
            "account", "account_id", "party", "party_id", "customer",
            "supplier", "phone", "address", "note", "license_number",
            "contact_person", "email", "warehouse_type", "is_default",
            "balance", "ledger", "transaction", "journal", "posting",
            "fx", "remittance", "payment", "cashaccount", "cash_account",
            "product", "category", "uom", "warehouse", "updated_at",
        ]
        for field in forbidden:
            self.assertFalse(hasattr(house, field), field)
        concrete_relations = [
            f for f in ExchangeHouse._meta.get_fields()
            if f.is_relation and f.concrete
        ]
        self.assertEqual(concrete_relations, [])
        self.assertFalse(hasattr(services, "delete_exchange_house"))


class ExchangeHouseUpdateTests(ExchangeHouseFixture, TestCase):
    def test_update_partial_with_audit(self):
        house = self._make()
        updated = update_exchange_house(house, name_fa="صرافی سردار",
                                        user=self.user)
        self.assertEqual(updated.name_fa, "صرافی سردار")
        event = AuditEvent.objects.get(
            action=AuditAction.UPDATE, entity="ExchangeHouse"
        )
        self.assertEqual(event.previous_state["name_fa"], "")
        self.assertEqual(event.new_state["name_fa"], "صرافی سردار")

    def test_rename_preserves_pk(self):
        house = self._make(name="Old House")
        pk = house.pk
        renamed = update_exchange_house(house, name="New House",
                                        user=self.user)
        self.assertEqual(renamed.pk, pk)
        self.assertEqual(ExchangeHouse.objects.get(pk=pk).name, "New House")

    def test_update_noop_creates_no_audit(self):
        house = self._make()
        audits_before = AuditEvent.objects.count()
        update_exchange_house(house, name="Qari Sardar", user=self.user)
        update_exchange_house(house, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_update_blank_name_rejected(self):
        house = self._make()
        with self.assertRaises(ExchangeHouseValidationError):
            update_exchange_house(house, name=" ", user=self.user)
        house.refresh_from_db()
        self.assertEqual(house.name, "Qari Sardar")

    def test_create_audit_snapshot(self):
        house = self._make(name_fa="صرافی")
        event = AuditEvent.objects.get(
            action=AuditAction.CREATE, entity="ExchangeHouse",
            entity_id=str(house.pk),
        )
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.reference, "Qari Sardar")
        self.assertIsNone(event.previous_state)
        self.assertEqual(event.new_state["name_fa"], "صرافی")
        self.assertTrue(event.new_state["is_active"])

    def test_audit_failure_leaves_no_orphan(self):
        with mock.patch("exchange_houses.services.record_audit_event",
                        side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                self._make()
        self.assertEqual(ExchangeHouse.objects.count(), 0)

    def test_deactivate_reactivate_with_reason(self):
        house = self._make()
        set_exchange_house_active(house, is_active=False, user=self.user,
                                  reason="paused")
        house.refresh_from_db()
        self.assertFalse(house.is_active)
        event = AuditEvent.objects.filter(
            action=AuditAction.UPDATE, entity="ExchangeHouse"
        ).order_by("id").last()
        self.assertEqual(event.reason, "paused")
        set_exchange_house_active(house, is_active=True, user=self.user)
        house.refresh_from_db()
        self.assertTrue(house.is_active)

    def test_deactivate_noop_creates_no_audit(self):
        house = self._make()
        audits_before = AuditEvent.objects.count()
        set_exchange_house_active(house, is_active=True, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_inactive_house_still_maintainable(self):
        house = self._make()
        set_exchange_house_active(house, is_active=False, user=self.user)
        updated = update_exchange_house(house, name_fa="بایگانی",
                                        user=self.user)
        self.assertEqual(updated.name_fa, "بایگانی")
        self.assertTrue(
            ExchangeHouse.objects.filter(pk=house.pk).exists())

    def test_resolve_accepts_instance_or_pk(self):
        house = self._make()
        self.assertEqual(resolve_exchange_house(house).pk, house.pk)
        self.assertEqual(resolve_exchange_house(house.pk).pk, house.pk)
        with self.assertRaises(ExchangeHouseValidationError):
            resolve_exchange_house(424242)
        with self.assertRaises(ExchangeHouseValidationError):
            resolve_exchange_house("not-a-pk")
        with self.assertRaises(ExchangeHouseValidationError):
            resolve_exchange_house(ExchangeHouse(name="unsaved"))
