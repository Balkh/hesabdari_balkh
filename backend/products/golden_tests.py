"""Phase 4.1 — golden master-data scenarios (printed, human-verifiable).

Each scenario drives the REAL services and prints the identity/audit
trail. Run with ``-s`` to capture the trail. Examples follow contract
§3.13 (Cooking Oil: 1 Carton = 10 L).
"""

from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase

from categories.models import Category
from categories.services import (
    CategoryValidationError,
    create_category,
    set_category_active,
)
from security.models import AuditEvent
from uom.models import UnitOfMeasure
from uom.services import UOMValidationError, create_uom

from .models import Product
from .services import (
    ProductValidationError,
    create_product,
    set_product_active,
    update_product,
)


class GoldenFixture:
    def setUp(self):
        self.user = get_user_model().objects.create_user("g41user", password="x")
        self.n = 0

    def _code(self, prefix="G41"):
        self.n += 1
        return f"{prefix}-{self.n:05d}"

    def _show(self, tag, obj):
        print(f"  [{tag}] {obj}")

    def _audits(self, entity):
        return list(
            AuditEvent.objects.filter(entity=entity).order_by("id")
        )


class MasterGoldenTests(GoldenFixture, TestCase):
    def test_g41_01_category_creation(self):
        print("G41-01 create a category:")
        category = create_category(
            name="Grocery", name_fa="خواربار", user=self.user
        )
        self._show("category", f"id={category.pk} name={category.name} "
                               f"fa={category.name_fa} active={category.is_active}")
        (event,) = self._audits("Category")
        self._show("audit", f"{event.action} by={event.user} "
                            f"new={event.new_state}")
        self.assertEqual(event.new_state["name"], "Grocery")
        print("PASS G41-01")

    def test_g41_02_category_validation(self):
        print("G41-02 blank rejected, duplicate names allowed:")
        with self.assertRaises(CategoryValidationError) as raised:
            create_category(name="  ", user=self.user)
        self._show("blank", f"rejected: {raised.exception}")
        first = create_category(name="Oil", user=self.user)
        second = create_category(name="Oil", user=self.user)
        self._show("duplicates", f"ids {first.pk} + {second.pk} coexist")
        self.assertEqual(Category.objects.filter(name="Oil").count(), 2)
        print("PASS G41-02")

    def test_g41_03_uom_creation(self):
        print("G41-03 create units of measure:")
        liter = create_uom(name="Liter", name_fa="لیتر", user=self.user)
        carton = create_uom(name="Carton", name_fa="کارتن", user=self.user)
        self._show("uoms", f"{liter.pk}:{liter.name}, {carton.pk}:{carton.name}")
        self.assertEqual(UnitOfMeasure.objects.count(), 2)
        print("PASS G41-03")

    def test_g41_04_uom_validation(self):
        print("G41-04 blank UOM rejected:")
        with self.assertRaises(UOMValidationError) as raised:
            create_uom(name="", user=self.user)
        self._show("blank", f"rejected: {raised.exception}")
        self.assertEqual(UnitOfMeasure.objects.count(), 0)
        print("PASS G41-04")

    def test_g41_05_product_creation(self):
        print("G41-05 create Cooking Oil (1 Carton = 10 L):")
        category = create_category(name="Grocery", user=self.user)
        liter = create_uom(name="Liter", user=self.user)
        carton = create_uom(name="Carton", user=self.user)
        product = create_product(
            code="OIL-5L", name="Cooking Oil 5L", name_fa="روغن ۵ لیتری",
            category=category, primary_uom=liter, secondary_uom=carton,
            conversion_factor="10", brand="Hari Dunya",
            ref_purchase_price="95.50", ref_sales_price="110.00",
            min_stock="50", max_stock="500", reorder_point="100",
            user=self.user,
        )
        self._show("product", f"{product.code} factor={product.conversion_factor} "
                              f"min={product.min_stock}")
        self.assertEqual(product.conversion_factor, Decimal("10.0000"))
        print("PASS G41-05")

    def test_g41_06_product_category_uom_integrity(self):
        print("G41-06 used masters are PROTECTed:")
        category = create_category(name="Grocery", user=self.user)
        liter = create_uom(name="Liter", user=self.user)
        create_product(code=self._code(), name="n", name_fa="f",
                       category=category, primary_uom=liter, user=self.user)
        for label, obj in (("category", category), ("uom", liter)):
            with self.assertRaises(ProtectedError):
                obj.delete()
            self._show(label, "delete blocked (PROTECT)")
        print("PASS G41-06")

    def test_g41_07_product_uniqueness(self):
        print("G41-07 duplicate product code rejected:")
        category = create_category(name="Grocery", user=self.user)
        liter = create_uom(name="Liter", user=self.user)
        create_product(code="DUP-1", name="n", name_fa="f",
                       category=category, primary_uom=liter, user=self.user)
        with self.assertRaises(ProductValidationError) as raised:
            create_product(code="DUP-1", name="n2", name_fa="f2",
                           category=category, primary_uom=liter,
                           user=self.user)
        self._show("duplicate", f"rejected: {raised.exception}")
        self.assertEqual(Product.objects.count(), 1)
        print("PASS G41-07")

    def test_g41_08_inactive_master_behavior(self):
        print("G41-08 inactive is a flag, blocks nothing:")
        category = create_category(name="Grocery", user=self.user)
        liter = create_uom(name="Liter", user=self.user)
        product = create_product(
            code=self._code(), name="n", name_fa="f", category=category,
            primary_uom=liter, user=self.user,
        )
        set_product_active(product, is_active=False, user=self.user,
                           reason="seasonal")
        set_category_active(category, is_active=False, user=self.user)
        product.refresh_from_db()
        self._show("flags", f"product={product.is_active} "
                            f"category={category.is_active}")
        renamed = update_product(product, name="renamed", user=self.user)
        self._show("update", f"inactive product still editable: {renamed.name}")
        self.assertFalse(product.is_active)
        print("PASS G41-08")

    def test_g41_09_invalid_master_data_input(self):
        print("G41-09 rejection matrix:")
        category = create_category(name="Grocery", user=self.user)
        liter = create_uom(name="Liter", user=self.user)
        probes = [
            ("blank code", dict(code=" ")),
            ("blank fa name", dict(name_fa="")),
            ("missing category", dict(code=self._code(), category=999)),
            ("zero factor", dict(code=self._code(), conversion_factor="0")),
            ("float factor", dict(code=self._code(), conversion_factor=2.5)),
            ("negative min", dict(code=self._code(), min_stock="-1")),
        ]
        for label, overrides in probes:
            params = dict(code=self._code(), name="n", name_fa="f",
                          category=category, primary_uom=liter,
                          user=self.user)
            params.update(overrides)
            with self.assertRaises(ProductValidationError) as raised:
                create_product(**params)
            self._show(label, f"rejected: {raised.exception}")
        self.assertEqual(Product.objects.count(), 0)
        print("PASS G41-09")

    def test_g41_10_atomic_failure_rollback(self):
        print("G41-10 audit failure rolls back the product:")
        category = create_category(name="Grocery", user=self.user)
        liter = create_uom(name="Liter", user=self.user)
        with mock.patch("products.services.record_audit_event",
                        side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                create_product(code=self._code(), name="n", name_fa="f",
                               category=category, primary_uom=liter,
                               user=self.user)
        self._show("rows", f"products={Product.objects.count()} "
                           f"audits={AuditEvent.objects.filter(entity='Product').count()}")
        self.assertEqual(Product.objects.count(), 0)
        print("PASS G41-10")
