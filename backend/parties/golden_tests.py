"""Phase 4.2 — golden party scenarios (printed, human-verifiable).

Each scenario drives the REAL services and prints the identity/role/audit
trail. Run with ``-s`` to capture the trail.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from security.models import AuditEvent

from .models import Party
from .services import (
    PartyValidationError,
    create_party,
    set_party_active,
    update_party,
)


class GoldenFixture:
    def setUp(self):
        self.user = get_user_model().objects.create_user("g42user", password="x")

    def _show(self, tag, obj):
        print(f"  [{tag}] {obj}")

    def _audits(self):
        return list(AuditEvent.objects.filter(entity="Party").order_by("id"))


class PartyGoldenTests(GoldenFixture, TestCase):
    def test_g42_01_customer_only(self):
        print("G42-01 create a customer-only party:")
        party = create_party(name="Ahmad Trading", name_fa="احمد",
                             is_customer=True, phone="0700-111222",
                             user=self.user)
        self._show("party", f"id={party.pk} customer={party.is_customer} "
                            f"supplier={party.is_supplier}")
        (event,) = self._audits()
        self._show("audit", f"{event.action} by={event.user}")
        self.assertTrue(party.is_customer)
        print("PASS G42-01")

    def test_g42_02_supplier_only(self):
        print("G42-02 create a supplier-only party:")
        party = create_party(name="Hari Dunya Factory", is_supplier=True,
                             address="Industrial Block 9", user=self.user)
        self._show("party", f"id={party.pk} customer={party.is_customer} "
                            f"supplier={party.is_supplier}")
        self.assertTrue(party.is_supplier)
        print("PASS G42-02")

    def test_g42_03_dual_role(self):
        print("G42-03 one record, both roles (ABC Trading):")
        party = create_party(name="ABC Trading", is_customer=True,
                             is_supplier=True, user=self.user)
        self._show("party", f"id={party.pk} customer={party.is_customer} "
                            f"supplier={party.is_supplier}")
        self.assertEqual(Party.objects.count(), 1)
        print("PASS G42-03")

    def test_g42_04_roleless_rejected(self):
        print("G42-04 party without any role is rejected twice:")
        with self.assertRaises(PartyValidationError) as raised:
            create_party(name="Nobody", user=self.user)
        self._show("service", f"rejected: {raised.exception}")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Party.objects.create(name="Nobody")
        self._show("database", "CHECK party_has_role rejected direct write")
        self.assertEqual(Party.objects.count(), 0)
        print("PASS G42-04")

    def test_g42_05_bilingual_names(self):
        print("G42-05 Persian name optional, English required:")
        with_name = create_party(name="With FA", name_fa="با فارسی",
                                 is_customer=True, user=self.user)
        without_name = create_party(name="Without FA", is_customer=True,
                                    user=self.user)
        self._show("names", f"fa='{with_name.name_fa}' vs "
                            f"fa='{without_name.name_fa}'")
        with self.assertRaises(PartyValidationError):
            create_party(name="  ", is_customer=True, user=self.user)
        self._show("blank", "blank English name rejected")
        print("PASS G42-05")

    def test_g42_06_inactive_party(self):
        print("G42-06 inactive is a flag — history preserved:")
        party = create_party(name="Old Trader", is_customer=True,
                             note="since 2019", user=self.user)
        set_party_active(party, is_active=False, user=self.user,
                         reason="dormant")
        party.refresh_from_db()
        self._show("flag", f"active={party.is_active} "
                           f"still_present={Party.objects.filter(pk=party.pk).exists()}")
        renamed = update_party(party, note="kept for history",
                               user=self.user)
        self._show("update", f"inactive record still maintainable: {renamed.note}")
        self.assertFalse(party.is_active)
        print("PASS G42-06")

    def test_g42_07_contact_storage(self):
        print("G42-07 phone/address/note round-trip as plain storage:")
        party = create_party(name="Reachable Co", is_supplier=True,
                             phone="+93-799-000111",
                             address="Kabul, Street 12", note="call first",
                             user=self.user)
        party.refresh_from_db()
        self._show("contact", f"{party.phone} | {party.address} | {party.note}")
        twin = create_party(name="Twin Co", is_supplier=True,
                            phone="+93-799-000111", user=self.user)
        self._show("duplicates", f"same phone on ids {party.pk} + {twin.pk} (no uniqueness)")
        self.assertEqual(party.phone, twin.phone)
        print("PASS G42-07")

    def test_g42_08_atomic_rollback(self):
        print("G42-08 audit failure rolls back the party:")
        with mock.patch("parties.services.record_audit_event",
                        side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                create_party(name="Orphan", is_customer=True, user=self.user)
        self._show("rows", f"parties={Party.objects.count()} "
                           f"audits={len(self._audits())}")
        self.assertEqual(Party.objects.count(), 0)
        print("PASS G42-08")
