"""Phase 4.3 — golden warehouse scenarios (printed, human-verifiable).

Each scenario drives the REAL services and prints the identity/audit
trail. Run with ``-s`` to capture the trail.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from security.models import AuditEvent

from .models import Warehouse
from .services import (
    WarehouseValidationError,
    create_warehouse,
    set_warehouse_active,
    update_warehouse,
)


class GoldenFixture:
    def setUp(self):
        self.user = get_user_model().objects.create_user("g43user", password="x")

    def _show(self, tag, obj):
        print(f"  [{tag}] {obj}")

    def _audits(self):
        return list(AuditEvent.objects.filter(entity="Warehouse").order_by("id"))


class WarehouseGoldenTests(GoldenFixture, TestCase):
    def test_g43_01_create_minimal(self):
        print("G43-01 create a warehouse with defaults:")
        warehouse = create_warehouse(name="Main Godown", user=self.user)
        self._show("warehouse", f"id={warehouse.pk} name='{warehouse.name}' "
                                f"fa='{warehouse.name_fa}' "
                                f"active={warehouse.is_active}")
        (event,) = self._audits()
        self._show("audit", f"{event.action} by={event.user}")
        self.assertTrue(warehouse.is_active)
        print("PASS G43-01")

    def test_g43_02_required_and_optional_names(self):
        print("G43-02 Persian name optional, English required:")
        with_name = create_warehouse(name="With FA", name_fa="با فارسی",
                                     user=self.user)
        without_name = create_warehouse(name="Without FA", user=self.user)
        self._show("names", f"fa='{with_name.name_fa}' vs "
                            f"fa='{without_name.name_fa}'")
        with self.assertRaises(WarehouseValidationError):
            create_warehouse(name="  ", user=self.user)
        self._show("blank", "blank English name rejected")
        print("PASS G43-02")

    def test_g43_03_duplicate_names_allowed(self):
        print("G43-03 two warehouses may share one name (OD-2):")
        first = create_warehouse(name="Branch Godown", user=self.user)
        second = create_warehouse(name="Branch Godown", name_fa="شعبه دوم",
                                  user=self.user)
        self._show("duplicates", f"same name on ids {first.pk} + {second.pk} "
                                 "(no uniqueness)")
        self.assertEqual(
            Warehouse.objects.filter(name="Branch Godown").count(), 2)
        print("PASS G43-03")

    def test_g43_04_active_lifecycle(self):
        print("G43-04 inactive is a flag — history preserved:")
        warehouse = create_warehouse(name="Old Godown", user=self.user)
        set_warehouse_active(warehouse, is_active=False, user=self.user,
                             reason="relocating")
        warehouse.refresh_from_db()
        self._show("flag", f"active={warehouse.is_active} "
                           f"still_present={Warehouse.objects.filter(pk=warehouse.pk).exists()}")
        set_warehouse_active(warehouse, is_active=True, user=self.user)
        warehouse.refresh_from_db()
        self._show("reactivate", f"active={warehouse.is_active}")
        self.assertTrue(warehouse.is_active)
        print("PASS G43-04")

    def test_g43_05_rename_preserves_pk(self):
        print("G43-05 rename keeps the identity (PK stable):")
        warehouse = create_warehouse(name="Main Warehouse", user=self.user)
        renamed = update_warehouse(warehouse, name="Central Warehouse",
                                   user=self.user)
        self._show("rename", f"id={renamed.pk} "
                             f"'Main Warehouse' -> '{renamed.name}'")
        self.assertEqual(renamed.pk, warehouse.pk)
        print("PASS G43-05")

    def test_g43_06_audit_trail(self):
        print("G43-06 create + update leave a readable trail:")
        warehouse = create_warehouse(name="Audited Godown", user=self.user)
        update_warehouse(warehouse, name_fa="حسابرسی‌شده", user=self.user)
        trail = [(event.action, event.reference) for event in self._audits()]
        self._show("trail", trail)
        self.assertEqual([action for action, _ in trail],
                         ["CREATE", "UPDATE"])
        print("PASS G43-06")

    def test_g43_07_noop_silence(self):
        print("G43-07 unchanged writes stay silent (no audit):")
        warehouse = create_warehouse(name="Quiet Godown", user=self.user)
        before = len(self._audits())
        update_warehouse(warehouse, name="Quiet Godown", user=self.user)
        set_warehouse_active(warehouse, is_active=True, user=self.user)
        self._show("audits", f"before={before} after={len(self._audits())}")
        self.assertEqual(len(self._audits()), before)
        print("PASS G43-07")

    def test_g43_08_scope_boundary(self):
        print("G43-08 no code/address/type/stock/finance/relations:")
        warehouse = create_warehouse(name="Plain Godown", user=self.user)
        missing = [field for field in
                   ("code", "address", "warehouse_type", "is_default",
                    "stock", "quantity", "balance", "currency", "account",
                    "product", "uom", "party")
                   if not hasattr(warehouse, field)]
        self._show("absent", f"{len(missing)}/12 forbidden attrs missing")
        self.assertEqual(len(missing), 12)
        print("PASS G43-08")
