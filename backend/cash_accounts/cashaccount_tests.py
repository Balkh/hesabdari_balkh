"""Phase 4.4 — CashAccount master tests (operational master, OD-5..OD-8).

Pins the approved model: required non-unique name, optional name_fa,
single active flag, no code, no currency, no relations, no contact/
balance/ledger/posting concepts. Frozen suites untouched.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase

from security.models import AuditAction, AuditEvent

from . import services
from .models import CashAccount
from .services import (
    CashAccountValidationError,
    create_cash_account,
    resolve_cash_account,
    set_cash_account_active,
    update_cash_account,
)


class CashAccountFixture:
    def setUp(self):
        self.user = get_user_model().objects.create_user("c44user", password="x")

    def _make(self, name="Main Cashbox", **kwargs):
        params = {"user": self.user}
        params.update(kwargs)
        return create_cash_account(name=name, **params)


class CashAccountIdentityTests(CashAccountFixture, TestCase):
    def test_create_valid_defaults(self):
        account = self._make()
        self.assertEqual(account.name, "Main Cashbox")
        self.assertEqual(account.name_fa, "")
        self.assertTrue(account.is_active)
        self.assertIsNotNone(account.created_at)
        self.assertFalse(hasattr(account, "code"))

    def test_blank_name_rejected_without_row_or_audit(self):
        with self.assertRaises(CashAccountValidationError):
            self._make(name="   ")
        self.assertEqual(CashAccount.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_non_text_name_rejected(self):
        with self.assertRaises(CashAccountValidationError):
            self._make(name=42)
        self.assertEqual(CashAccount.objects.count(), 0)

    def test_texts_trimmed(self):
        account = self._make(name="  Main  ", name_fa="  صندوق  ")
        self.assertEqual(account.name, "Main")
        self.assertEqual(account.name_fa, "صندوق")

    def test_name_fa_optional_and_stored(self):
        account = self._make(name_fa="صندوق اصلی")
        account.refresh_from_db()
        self.assertEqual(account.name_fa, "صندوق اصلی")

    def test_duplicate_names_allowed(self):
        first = self._make(name="Same Name")
        second = self._make(name="Same Name", name_fa="تکراری")
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(CashAccount.objects.filter(name="Same Name").count(), 2)

    def test_case_variants_allowed(self):
        self._make(name="Cash")
        self._make(name="cash")
        self.assertEqual(CashAccount.objects.count(), 2)

    def test_non_text_name_fa_rejected(self):
        with self.assertRaises(CashAccountValidationError):
            self._make(name_fa=700111222)
        self.assertEqual(CashAccount.objects.count(), 0)

    def test_user_none_allowed_anonymous_rejected(self):
        account = create_cash_account(name="NoActor")
        event = AuditEvent.objects.get(entity="CashAccount")
        self.assertIsNone(event.user)
        self.assertEqual(event.entity_id, str(account.pk))
        with self.assertRaises(CashAccountValidationError):
            create_cash_account(name="Ghost", user=AnonymousUser())
        self.assertEqual(CashAccount.objects.count(), 1)

    def test_db_blank_guard(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashAccount.objects.create(name="")
        self.assertEqual(CashAccount.objects.count(), 0)

    def test_no_forbidden_fields_or_relations(self):
        account = self._make()
        forbidden = [
            "code", "cash_code", "account_code", "number", "sequence",
            "currency", "currency_id", "default_currency", "base_currency",
            "account", "account_id", "party", "party_id", "customer",
            "supplier", "phone", "address", "note", "license_number",
            "contact_person", "email", "warehouse_type", "cash_type",
            "is_default", "default_cash_account", "balance", "ledger",
            "transaction", "journal", "posting", "fx", "remittance",
            "payment", "exchangehouse", "exchange_house", "product",
            "category", "uom", "warehouse", "updated_at",
        ]
        for field in forbidden:
            self.assertFalse(hasattr(account, field), field)
        concrete_relations = [
            f for f in CashAccount._meta.get_fields()
            if f.is_relation and f.concrete
        ]
        self.assertEqual(concrete_relations, [])
        self.assertFalse(hasattr(services, "delete_cash_account"))


class CashAccountUpdateTests(CashAccountFixture, TestCase):
    def test_update_partial_with_audit(self):
        account = self._make()
        updated = update_cash_account(account, name_fa="صندوق اصلی",
                                      user=self.user)
        self.assertEqual(updated.name_fa, "صندوق اصلی")
        event = AuditEvent.objects.get(
            action=AuditAction.UPDATE, entity="CashAccount"
        )
        self.assertEqual(event.previous_state["name_fa"], "")
        self.assertEqual(event.new_state["name_fa"], "صندوق اصلی")

    def test_rename_preserves_pk(self):
        account = self._make(name="Old Cashbox")
        pk = account.pk
        renamed = update_cash_account(account, name="New Cashbox",
                                      user=self.user)
        self.assertEqual(renamed.pk, pk)
        self.assertEqual(CashAccount.objects.get(pk=pk).name, "New Cashbox")

    def test_update_noop_creates_no_audit(self):
        account = self._make()
        audits_before = AuditEvent.objects.count()
        update_cash_account(account, name="Main Cashbox", user=self.user)
        update_cash_account(account, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_update_blank_name_rejected(self):
        account = self._make()
        with self.assertRaises(CashAccountValidationError):
            update_cash_account(account, name=" ", user=self.user)
        account.refresh_from_db()
        self.assertEqual(account.name, "Main Cashbox")

    def test_create_audit_snapshot(self):
        account = self._make(name_fa="صندوق")
        event = AuditEvent.objects.get(
            action=AuditAction.CREATE, entity="CashAccount",
            entity_id=str(account.pk),
        )
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.reference, "Main Cashbox")
        self.assertIsNone(event.previous_state)
        self.assertEqual(event.new_state["name_fa"], "صندوق")
        self.assertTrue(event.new_state["is_active"])

    def test_audit_failure_leaves_no_orphan(self):
        with mock.patch("cash_accounts.services.record_audit_event",
                        side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                self._make()
        self.assertEqual(CashAccount.objects.count(), 0)

    def test_deactivate_reactivate_with_reason(self):
        account = self._make()
        set_cash_account_active(account, is_active=False, user=self.user,
                                reason="counting")
        account.refresh_from_db()
        self.assertFalse(account.is_active)
        event = AuditEvent.objects.filter(
            action=AuditAction.UPDATE, entity="CashAccount"
        ).order_by("id").last()
        self.assertEqual(event.reason, "counting")
        set_cash_account_active(account, is_active=True, user=self.user)
        account.refresh_from_db()
        self.assertTrue(account.is_active)

    def test_deactivate_noop_creates_no_audit(self):
        account = self._make()
        audits_before = AuditEvent.objects.count()
        set_cash_account_active(account, is_active=True, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_inactive_account_still_maintainable(self):
        account = self._make()
        set_cash_account_active(account, is_active=False, user=self.user)
        updated = update_cash_account(account, name_fa="بایگانی",
                                      user=self.user)
        self.assertEqual(updated.name_fa, "بایگانی")
        self.assertTrue(
            CashAccount.objects.filter(pk=account.pk).exists())

    def test_resolve_accepts_instance_or_pk(self):
        account = self._make()
        self.assertEqual(resolve_cash_account(account).pk, account.pk)
        self.assertEqual(resolve_cash_account(account.pk).pk, account.pk)
        with self.assertRaises(CashAccountValidationError):
            resolve_cash_account(424242)
        with self.assertRaises(CashAccountValidationError):
            resolve_cash_account("not-a-pk")
        with self.assertRaises(CashAccountValidationError):
            resolve_cash_account(CashAccount(name="unsaved"))
