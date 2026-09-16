"""Phase 4.2 — Party master tests (Option A: Shared Party + Roles).

Pins FR-1..FR-9: one identity, boolean roles, at-least-one-role invariant
at service + DB layers, no code, inert contact storage, single active
flag, no financial concepts. Frozen suites untouched.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase

from security.models import AuditAction, AuditEvent

from .models import Party
from .services import (
    PartyValidationError,
    create_party,
    resolve_party,
    set_party_active,
    update_party,
)


class PartyFixture:
    def setUp(self):
        self.user = get_user_model().objects.create_user("p42user", password="x")

    def _make(self, name="ABC Trading", **kwargs):
        params = {"is_customer": True, "user": self.user}
        params.update(kwargs)
        return create_party(name=name, **params)


class PartyIdentityTests(PartyFixture, TestCase):
    def test_create_valid_defaults(self):
        party = self._make()
        self.assertEqual(party.name, "ABC Trading")
        self.assertEqual(party.name_fa, "")
        self.assertTrue(party.is_customer)
        self.assertFalse(party.is_supplier)
        self.assertEqual(party.phone, "")
        self.assertEqual(party.address, "")
        self.assertEqual(party.note, "")
        self.assertTrue(party.is_active)
        self.assertIsNotNone(party.created_at)
        self.assertFalse(hasattr(party, "code"))

    def test_blank_name_rejected_without_row_or_audit(self):
        with self.assertRaises(PartyValidationError):
            self._make(name="   ")
        self.assertEqual(Party.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_non_text_name_rejected(self):
        with self.assertRaises(PartyValidationError):
            self._make(name=42)
        self.assertEqual(Party.objects.count(), 0)

    def test_texts_trimmed(self):
        party = self._make(name="  ABC  ", phone="  0700  ", note="  n  ")
        self.assertEqual(party.name, "ABC")
        self.assertEqual(party.phone, "0700")
        self.assertEqual(party.note, "n")

    def test_contact_trio_optional_and_stored(self):
        party = self._make(phone="+93-700-111222", address="Herat, Block 4",
                           note="prefers mornings")
        party.refresh_from_db()
        self.assertEqual(party.phone, "+93-700-111222")
        self.assertEqual(party.address, "Herat, Block 4")
        self.assertEqual(party.note, "prefers mornings")

    def test_duplicate_names_allowed(self):
        first = self._make(name="Same Name")
        second = self._make(name="Same Name", is_supplier=True)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(Party.objects.filter(name="Same Name").count(), 2)

    def test_non_text_contact_rejected(self):
        with self.assertRaises(PartyValidationError):
            self._make(phone=700111222)
        self.assertEqual(Party.objects.count(), 0)

    def test_user_none_allowed_anonymous_rejected(self):
        party = create_party(name="NoActor", is_supplier=True)
        event = AuditEvent.objects.get(entity="Party")
        self.assertIsNone(event.user)
        self.assertEqual(event.entity_id, str(party.pk))
        with self.assertRaises(PartyValidationError):
            create_party(name="Ghost", is_customer=True,
                         user=AnonymousUser())
        self.assertEqual(Party.objects.count(), 1)

    def test_db_blank_guard(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Party.objects.create(name="", is_customer=True)
        self.assertEqual(Party.objects.count(), 0)


class PartyRoleTests(PartyFixture, TestCase):
    def test_customer_only(self):
        party = self._make(is_customer=True, is_supplier=False)
        self.assertTrue(party.is_customer)
        self.assertFalse(party.is_supplier)

    def test_supplier_only(self):
        party = self._make(is_customer=False, is_supplier=True)
        self.assertFalse(party.is_customer)
        self.assertTrue(party.is_supplier)

    def test_dual_role_single_record(self):
        party = self._make(is_customer=True, is_supplier=True)
        self.assertTrue(party.is_customer)
        self.assertTrue(party.is_supplier)
        self.assertEqual(Party.objects.count(), 1)

    def test_neither_role_rejected_at_service(self):
        with self.assertRaises(PartyValidationError) as raised:
            self._make(is_customer=False, is_supplier=False)
        self.assertIn("at least one role", str(raised.exception))
        self.assertEqual(Party.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_bare_create_rejected_defaults_are_both_false(self):
        with self.assertRaises(PartyValidationError):
            create_party(name="Roleless", user=self.user)
        self.assertEqual(Party.objects.count(), 0)

    def test_neither_role_rejected_at_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Party.objects.create(name="Roleless")
        self.assertEqual(Party.objects.count(), 0)

    def test_create_audit_snapshot(self):
        party = self._make(name_fa="ای‌بی‌سی", is_supplier=True)
        event = AuditEvent.objects.get(
            action=AuditAction.CREATE, entity="Party",
            entity_id=str(party.pk),
        )
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.reference, "ABC Trading")
        self.assertIsNone(event.previous_state)
        self.assertTrue(event.new_state["is_customer"])
        self.assertTrue(event.new_state["is_supplier"])
        self.assertEqual(event.new_state["name_fa"], "ای‌بی‌سی")

    def test_audit_failure_leaves_no_orphan(self):
        with mock.patch("parties.services.record_audit_event",
                        side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                self._make()
        self.assertEqual(Party.objects.count(), 0)


class PartyUpdateTests(PartyFixture, TestCase):
    def test_update_partial_with_audit(self):
        party = self._make()
        updated = update_party(party, name_fa="ای‌بی‌سی", phone="0700",
                               user=self.user)
        self.assertEqual(updated.name_fa, "ای‌بی‌سی")
        event = AuditEvent.objects.get(
            action=AuditAction.UPDATE, entity="Party"
        )
        self.assertEqual(event.previous_state["phone"], "")
        self.assertEqual(event.new_state["phone"], "0700")

    def test_add_second_role(self):
        party = self._make(is_customer=True, is_supplier=False)
        updated = update_party(party, is_supplier=True, user=self.user)
        self.assertTrue(updated.is_customer)
        self.assertTrue(updated.is_supplier)

    def test_remove_one_of_two_roles(self):
        party = self._make(is_customer=True, is_supplier=True)
        updated = update_party(party, is_customer=False, user=self.user)
        self.assertFalse(updated.is_customer)
        self.assertTrue(updated.is_supplier)

    def test_remove_last_role_rejected(self):
        party = self._make(is_customer=True, is_supplier=False)
        with self.assertRaises(PartyValidationError):
            update_party(party, is_customer=False, user=self.user)
        party.refresh_from_db()
        self.assertTrue(party.is_customer)

    def test_update_noop_creates_no_audit(self):
        party = self._make()
        audits_before = AuditEvent.objects.count()
        update_party(party, name="ABC Trading", is_customer=True,
                     user=self.user)
        update_party(party, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_update_blank_name_rejected(self):
        party = self._make()
        with self.assertRaises(PartyValidationError):
            update_party(party, name=" ", user=self.user)
        party.refresh_from_db()
        self.assertEqual(party.name, "ABC Trading")

    def test_deactivate_reactivate_with_reason(self):
        party = self._make()
        set_party_active(party, is_active=False, user=self.user,
                         reason="dormant")
        party.refresh_from_db()
        self.assertFalse(party.is_active)
        event = AuditEvent.objects.filter(
            action=AuditAction.UPDATE, entity="Party"
        ).order_by("id").last()
        self.assertEqual(event.reason, "dormant")
        set_party_active(party, is_active=True, user=self.user)
        party.refresh_from_db()
        self.assertTrue(party.is_active)

    def test_deactivate_noop_creates_no_audit(self):
        party = self._make()
        audits_before = AuditEvent.objects.count()
        set_party_active(party, is_active=True, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_inactive_party_still_maintainable(self):
        party = self._make()
        set_party_active(party, is_active=False, user=self.user)
        updated = update_party(party, note="kept for history",
                               user=self.user)
        self.assertEqual(updated.note, "kept for history")
        self.assertTrue(
            Party.objects.filter(pk=party.pk).exists())

    def test_resolve_accepts_instance_or_pk(self):
        party = self._make()
        self.assertEqual(resolve_party(party).pk, party.pk)
        self.assertEqual(resolve_party(party.pk).pk, party.pk)
        with self.assertRaises(PartyValidationError):
            resolve_party(424242)
        with self.assertRaises(PartyValidationError):
            resolve_party("not-a-pk")
        with self.assertRaises(PartyValidationError):
            resolve_party(Party(name="unsaved", is_customer=True))
