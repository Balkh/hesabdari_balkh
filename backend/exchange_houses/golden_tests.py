"""Phase 4.4 — golden exchange scenarios G44-06..10 + G44-12/13 (printed).

Each scenario drives the REAL services and prints the identity/audit
trail. Run with ``-s`` to capture the trail.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from security.models import AuditEvent

from cash_accounts.models import CashAccount

from .models import ExchangeHouse
from .services import (
    ExchangeHouseValidationError,
    create_exchange_house,
    set_exchange_house_active,
    update_exchange_house,
)


class GoldenFixture:
    def setUp(self):
        self.user = get_user_model().objects.create_user("g44user", password="x")

    def _show(self, tag, obj):
        print(f"  [{tag}] {obj}")

    def _audits(self):
        return list(AuditEvent.objects.filter(entity="ExchangeHouse").order_by("id"))


class ExchangeGoldenTests(GoldenFixture, TestCase):
    def test_g44_06_create_minimal(self):
        print("G44-06 create an exchange house with defaults:")
        house = create_exchange_house(name="Qari Sardar", user=self.user)
        self._show("house", f"id={house.pk} name='{house.name}' "
                            f"fa='{house.name_fa}' active={house.is_active}")
        (event,) = self._audits()
        self._show("audit", f"{event.action} by={event.user}")
        self.assertTrue(house.is_active)
        print("PASS G44-06")

    def test_g44_07_required_and_optional_names(self):
        print("G44-07 Persian name optional, English required:")
        with_name = create_exchange_house(name="With FA", name_fa="با فارسی",
                                          user=self.user)
        without_name = create_exchange_house(name="Without FA",
                                             user=self.user)
        self._show("names", f"fa='{with_name.name_fa}' vs "
                            f"fa='{without_name.name_fa}'")
        with self.assertRaises(ExchangeHouseValidationError):
            create_exchange_house(name="  ", user=self.user)
        self._show("blank", "blank English name rejected")
        print("PASS G44-07")

    def test_g44_08_duplicate_names_allowed(self):
        print("G44-08 two houses may share one name (OD-9):")
        first = create_exchange_house(name="City Exchange", user=self.user)
        second = create_exchange_house(name="City Exchange",
                                       name_fa="شعبه دوم", user=self.user)
        self._show("duplicates", f"same name on ids {first.pk} + {second.pk} "
                                 "(no uniqueness)")
        self.assertEqual(
            ExchangeHouse.objects.filter(name="City Exchange").count(), 2)
        print("PASS G44-08")

    def test_g44_09_active_lifecycle(self):
        print("G44-09 inactive is a flag — history preserved:")
        house = create_exchange_house(name="Old House", user=self.user)
        set_exchange_house_active(house, is_active=False, user=self.user,
                                  reason="paused")
        house.refresh_from_db()
        self._show("flag", f"active={house.is_active} "
                           f"still_present={ExchangeHouse.objects.filter(pk=house.pk).exists()}")
        set_exchange_house_active(house, is_active=True, user=self.user)
        house.refresh_from_db()
        self._show("reactivate", f"active={house.is_active}")
        self.assertTrue(house.is_active)
        print("PASS G44-09")

    def test_g44_10_rename_preserves_pk(self):
        print("G44-10 rename keeps the identity (PK stable):")
        house = create_exchange_house(name="Old House", user=self.user)
        renamed = update_exchange_house(house, name="New House",
                                        user=self.user)
        self._show("rename", f"id={renamed.pk} "
                             f"'Old House' -> '{renamed.name}'")
        self.assertEqual(renamed.pk, house.pk)
        print("PASS G44-10")

    def test_g44_12_noop_silence(self):
        print("G44-12 unchanged writes stay silent (no audit):")
        house = create_exchange_house(name="Quiet House", user=self.user)
        before = len(self._audits())
        update_exchange_house(house, name="Quiet House", user=self.user)
        set_exchange_house_active(house, is_active=True, user=self.user)
        self._show("audits", f"before={before} after={len(self._audits())}")
        self.assertEqual(len(self._audits()), before)
        print("PASS G44-12")

    def test_g44_13_scope_boundary(self):
        print("G44-13 no code/currency/party/account/contact/finance on either:")
        cash = CashAccount(name="probe")
        house = ExchangeHouse(name="probe")
        forbidden = ("code", "currency", "currency_id", "account",
                     "account_id", "party", "party_id", "phone", "address",
                     "license_number", "balance", "ledger", "transaction",
                     "journal", "posting", "fx", "remittance", "payment")
        missing_cash = [f for f in forbidden if not hasattr(cash, f)]
        missing_house = [f for f in forbidden if not hasattr(house, f)]
        self._show("absent", f"cash {len(missing_cash)}/{len(forbidden)}, "
                             f"house {len(missing_house)}/{len(forbidden)}")
        self.assertEqual(len(missing_cash), len(forbidden))
        self.assertEqual(len(missing_house), len(forbidden))
        print("PASS G44-13")
