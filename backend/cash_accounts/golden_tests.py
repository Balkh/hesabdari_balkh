"""Phase 4.4 — golden cash scenarios G44-01..05 + G44-11 (printed).

Each scenario drives the REAL services and prints the identity/audit
trail. Run with ``-s`` to capture the trail.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from security.models import AuditEvent

from .models import CashAccount
from .services import (
    CashAccountValidationError,
    create_cash_account,
    set_cash_account_active,
    update_cash_account,
)


class GoldenFixture:
    def setUp(self):
        self.user = get_user_model().objects.create_user("g44user", password="x")

    def _show(self, tag, obj):
        print(f"  [{tag}] {obj}")

    def _audits(self):
        return list(AuditEvent.objects.filter(entity="CashAccount").order_by("id"))


class CashGoldenTests(GoldenFixture, TestCase):
    def test_g44_01_create_minimal(self):
        print("G44-01 create a cash account with defaults:")
        account = create_cash_account(name="Main Cashbox", user=self.user)
        self._show("cash", f"id={account.pk} name='{account.name}' "
                           f"fa='{account.name_fa}' active={account.is_active}")
        (event,) = self._audits()
        self._show("audit", f"{event.action} by={event.user}")
        self.assertTrue(account.is_active)
        print("PASS G44-01")

    def test_g44_02_required_and_optional_names(self):
        print("G44-02 Persian name optional, English required:")
        with_name = create_cash_account(name="With FA", name_fa="با فارسی",
                                        user=self.user)
        without_name = create_cash_account(name="Without FA", user=self.user)
        self._show("names", f"fa='{with_name.name_fa}' vs "
                            f"fa='{without_name.name_fa}'")
        with self.assertRaises(CashAccountValidationError):
            create_cash_account(name="  ", user=self.user)
        self._show("blank", "blank English name rejected")
        print("PASS G44-02")

    def test_g44_03_duplicate_names_allowed(self):
        print("G44-03 two cash accounts may share one name (OD-8):")
        first = create_cash_account(name="Branch Cash", user=self.user)
        second = create_cash_account(name="Branch Cash", name_fa="شعبه دوم",
                                     user=self.user)
        self._show("duplicates", f"same name on ids {first.pk} + {second.pk} "
                                 "(no uniqueness)")
        self.assertEqual(
            CashAccount.objects.filter(name="Branch Cash").count(), 2)
        print("PASS G44-03")

    def test_g44_04_active_lifecycle(self):
        print("G44-04 inactive is a flag — history preserved:")
        account = create_cash_account(name="Old Cashbox", user=self.user)
        set_cash_account_active(account, is_active=False, user=self.user,
                                reason="counting")
        account.refresh_from_db()
        self._show("flag", f"active={account.is_active} "
                           f"still_present={CashAccount.objects.filter(pk=account.pk).exists()}")
        set_cash_account_active(account, is_active=True, user=self.user)
        account.refresh_from_db()
        self._show("reactivate", f"active={account.is_active}")
        self.assertTrue(account.is_active)
        print("PASS G44-04")

    def test_g44_05_rename_preserves_pk(self):
        print("G44-05 rename keeps the identity (PK stable):")
        account = create_cash_account(name="Old Cashbox", user=self.user)
        renamed = update_cash_account(account, name="New Cashbox",
                                      user=self.user)
        self._show("rename", f"id={renamed.pk} "
                             f"'Old Cashbox' -> '{renamed.name}'")
        self.assertEqual(renamed.pk, account.pk)
        print("PASS G44-05")

    def test_g44_11_audit_trail(self):
        print("G44-11 create + update leave a readable trail:")
        account = create_cash_account(name="Audited Cash", user=self.user)
        update_cash_account(account, name_fa="حسابرسی‌شده", user=self.user)
        trail = [(event.action, event.reference) for event in self._audits()]
        self._show("trail", trail)
        self.assertEqual([action for action, _ in trail],
                         ["CREATE", "UPDATE"])
        print("PASS G44-11")
