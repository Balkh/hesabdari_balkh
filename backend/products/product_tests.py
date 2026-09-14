"""Phase 4.1 — Product master tests.

Pins contract §4.1 + §4.2 and interpretation record R-2..R-8/U-4:
unique user-assigned code, both names required, PROTECT relations, stored
(never applied) factor/prices/thresholds, and the recorded NON-decisions
(R-4: max/min, reorder, secondary-vs-primary, price signs are NOT
validated). Frozen suites untouched.
"""

from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from categories.services import create_category
from security.models import AuditAction, AuditEvent
from uom.services import create_uom

from .models import Product
from .services import (
    ProductValidationError,
    create_product,
    resolve_product,
    set_product_active,
    update_product,
)


class ProductFixture:
    def setUp(self):
        self.user = get_user_model().objects.create_user("p41user", password="x")
        self.category = create_category(name="Grocery", user=self.user)
        self.liter = create_uom(name="Liter", user=self.user)
        self.carton = create_uom(name="Carton", user=self.user)
        self.n = 0

    def _code(self):
        self.n += 1
        return f"P41-{self.n:05d}"

    def _make(self, **kwargs):
        params = dict(
            code=self._code(), name="Cooking Oil", name_fa="روغن",
            category=self.category, primary_uom=self.liter, user=self.user,
        )
        params.update(kwargs)
        return create_product(**params)


class ProductCreationTests(ProductFixture, TestCase):
    def test_create_minimal_defaults(self):
        product = self._make()
        self.assertEqual(product.conversion_factor, Decimal("1.0000"))
        self.assertEqual(product.min_stock, Decimal("0.000"))
        self.assertIsNone(product.secondary_uom)
        self.assertIsNone(product.ref_purchase_price)
        self.assertIsNone(product.ref_sales_price)
        self.assertIsNone(product.max_stock)
        self.assertIsNone(product.reorder_point)
        self.assertEqual(product.barcode, "")
        self.assertEqual(product.brand, "")
        self.assertEqual(product.description, "")
        self.assertTrue(product.is_active)
        self.assertIsNotNone(product.created_at)

    def test_create_full_valid_with_audit(self):
        product = self._make(
            secondary_uom=self.carton, conversion_factor="10",
            barcode="6261234567890", brand="Hari Dunya",
            ref_purchase_price="95.50", ref_sales_price="110.00",
            min_stock="50", max_stock="500", reorder_point="100",
            description="5-ply carton",
        )
        self.assertEqual(product.secondary_uom_id, self.carton.pk)
        self.assertEqual(product.conversion_factor, Decimal("10.0000"))
        self.assertEqual(product.ref_purchase_price, Decimal("95.5000"))
        event = AuditEvent.objects.get(
            action=AuditAction.CREATE, entity="Product",
            entity_id=str(product.pk),
        )
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.reference, product.code)
        self.assertEqual(event.new_state["conversion_factor"], "10.0000")

    def test_code_required(self):
        with self.assertRaises(ProductValidationError):
            self._make(code="  ")
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(
            AuditEvent.objects.filter(entity="Product").count(), 0)

    def test_names_required(self):
        with self.assertRaises(ProductValidationError):
            self._make(name="")
        with self.assertRaises(ProductValidationError):
            self._make(name_fa="  ")
        self.assertEqual(Product.objects.count(), 0)

    def test_code_trimmed_and_unique_at_service(self):
        first = self._make(code="  OIL-1  ")
        self.assertEqual(first.code, "OIL-1")
        with self.assertRaises(ProductValidationError) as raised:
            self._make(code="OIL-1")
        self.assertIn("already exists", str(raised.exception))
        self.assertEqual(Product.objects.count(), 1)

    def test_code_unique_at_database(self):
        self._make(code="OIL-DB")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.create(
                    code="OIL-DB", name="x", name_fa="y",
                    category=self.category, primary_uom=self.liter,
                )
        self.assertEqual(Product.objects.count(), 1)

    def test_missing_category_rejected(self):
        with self.assertRaises(ProductValidationError) as raised:
            self._make(category=424242)
        self.assertIn("Category does not exist", str(raised.exception))
        with self.assertRaises(ProductValidationError):
            self._make(category="garbage")
        self.assertEqual(Product.objects.count(), 0)

    def test_missing_uoms_rejected(self):
        with self.assertRaises(ProductValidationError) as raised:
            self._make(primary_uom=424242)
        self.assertIn("UOM does not exist", str(raised.exception))
        with self.assertRaises(ProductValidationError):
            self._make(secondary_uom=424242)
        self.assertEqual(Product.objects.count(), 0)

    def test_relations_accept_pks(self):
        product = self._make(
            category=self.category.pk, primary_uom=self.liter.pk,
            secondary_uom=self.carton.pk,
        )
        self.assertEqual(product.category_id, self.category.pk)
        self.assertEqual(product.secondary_uom_id, self.carton.pk)

    def test_factor_must_be_positive_number(self):
        for bad in ("0", "-2", "0.0000"):
            with self.subTest(bad=bad):
                with self.assertRaises(ProductValidationError):
                    self._make(code=self._code(), conversion_factor=bad)
        for bad in ("abc", 10.5, True, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ProductValidationError):
                    self._make(code=self._code(), conversion_factor=bad)
        self.assertEqual(Product.objects.count(), 0)

    def test_factor_quantized_half_up_4dp(self):
        product = self._make(conversion_factor="10.00005")
        self.assertEqual(str(product.conversion_factor), "10.0001")

    def test_min_stock_default_and_negative_rejected(self):
        self.assertEqual(self._make().min_stock, Decimal("0.000"))
        with self.assertRaises(ProductValidationError):
            self._make(min_stock="-0.001")
        self.assertEqual(Product.objects.count(), 1)

    def test_min_stock_quantized_3dp(self):
        product = self._make(min_stock="5.0005")
        self.assertEqual(str(product.min_stock), "5.001")

    def test_max_below_min_allowed(self):
        product = self._make(min_stock="100", max_stock="5")
        self.assertEqual(str(product.max_stock), "5.000")

    def test_reorder_anywhere_allowed(self):
        product = self._make(min_stock="100", max_stock="200",
                             reorder_point="999")
        self.assertEqual(str(product.reorder_point), "999.000")

    def test_secondary_equal_to_primary_allowed(self):
        product = self._make(secondary_uom=self.liter)
        self.assertEqual(product.secondary_uom_id, self.liter.pk)

    def test_negative_reference_price_allowed(self):
        product = self._make(ref_sales_price="-3.50")
        self.assertEqual(str(product.ref_sales_price), "-3.5000")

    def test_reference_price_quantized_4dp(self):
        product = self._make(ref_purchase_price="12.34565")
        self.assertEqual(str(product.ref_purchase_price), "12.3457")

    def test_user_none_allowed_anonymous_rejected(self):
        params = dict(code=self._code(), name="n", name_fa="f",
                      category=self.category, primary_uom=self.liter)
        product = create_product(**params)
        event = AuditEvent.objects.get(entity="Product")
        self.assertIsNone(event.user)
        self.assertEqual(event.entity_id, str(product.pk))
        with self.assertRaises(ProductValidationError):
            create_product(user=AnonymousUser(), **params)

    def test_db_guards_factor_min_blanks(self):
        base = dict(name="x", name_fa="y", category=self.category,
                    primary_uom=self.liter)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.create(code="F0", conversion_factor=0, **base)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.create(code="MN", min_stock=-1, **base)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.create(code="", **base)
        self.assertEqual(Product.objects.count(), 0)

    def test_audit_failure_leaves_no_orphan(self):
        with mock.patch("products.services.record_audit_event",
                        side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                self._make()
        self.assertEqual(Product.objects.count(), 0)


class ProductUpdateTests(ProductFixture, TestCase):
    def test_update_partial_with_audit(self):
        product = self._make()
        updated = update_product(
            product, name="Sunflower Oil", ref_sales_price="120",
            user=self.user,
        )
        self.assertEqual(updated.name, "Sunflower Oil")
        self.assertEqual(updated.ref_sales_price, Decimal("120.0000"))
        event = AuditEvent.objects.get(
            action=AuditAction.UPDATE, entity="Product"
        )
        self.assertEqual(event.previous_state["name"], "Cooking Oil")
        self.assertEqual(event.new_state["name"], "Sunflower Oil")

    def test_update_code_clash_rejected(self):
        self._make(code="KEEP-1")
        other = self._make(code="KEEP-2")
        with self.assertRaises(ProductValidationError):
            update_product(other, code="KEEP-1", user=self.user)
        other.refresh_from_db()
        self.assertEqual(other.code, "KEEP-2")

    def test_update_relations_by_instance_and_pk(self):
        other_cat = create_category(name="Beverage", user=self.user)
        product = self._make()
        update_product(product, category=other_cat, user=self.user)
        product.refresh_from_db()
        self.assertEqual(product.category_id, other_cat.pk)
        update_product(product, secondary_uom=self.carton.pk,
                       user=self.user)
        product.refresh_from_db()
        self.assertEqual(product.secondary_uom_id, self.carton.pk)
        update_product(product, secondary_uom=None, user=self.user)
        product.refresh_from_db()
        self.assertIsNone(product.secondary_uom)

    def test_update_noop_creates_no_audit(self):
        product = self._make()
        audits_before = AuditEvent.objects.count()
        update_product(product, name="Cooking Oil", user=self.user)
        update_product(product, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_update_unknown_field_rejected(self):
        product = self._make()
        with self.assertRaises(ProductValidationError):
            update_product(product, stock="100", user=self.user)

    def test_update_blank_name_rejected(self):
        product = self._make()
        with self.assertRaises(ProductValidationError):
            update_product(product, name=" ", user=self.user)
        product.refresh_from_db()
        self.assertEqual(product.name, "Cooking Oil")

    def test_deactivate_flag_only_nothing_blocked(self):
        product = self._make()
        set_product_active(product, is_active=False, user=self.user,
                           reason="discontinued")
        product.refresh_from_db()
        self.assertFalse(product.is_active)
        updated = update_product(product, name="Still Editable",
                                 user=self.user)
        self.assertEqual(updated.name, "Still Editable")
        event = AuditEvent.objects.filter(
            action=AuditAction.UPDATE, entity="Product"
        ).order_by("id").last()
        self.assertIn("discontinued", AuditEvent.objects.filter(
            action=AuditAction.UPDATE, entity="Product",
            reason="discontinued").values_list("reason", flat=True))

    def test_deactivate_noop_creates_no_audit(self):
        product = self._make()
        audits_before = AuditEvent.objects.count()
        set_product_active(product, is_active=True, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_category_and_uom_protected_while_used(self):
        self._make(secondary_uom=self.carton)
        with self.assertRaises(ProtectedError):
            self.category.delete()
        with self.assertRaises(ProtectedError):
            self.liter.delete()
        with self.assertRaises(ProtectedError):
            self.carton.delete()
        spare = create_uom(name="Spare", user=self.user)
        spare.delete()
        self.assertFalse(
            type(spare).objects.filter(pk=spare.pk).exists())

    def test_resolve_accepts_instance_or_pk(self):
        product = self._make()
        self.assertEqual(resolve_product(product).pk, product.pk)
        self.assertEqual(resolve_product(product.pk).pk, product.pk)
        with self.assertRaises(ProductValidationError):
            resolve_product(424242)
        with self.assertRaises(ProductValidationError):
            resolve_product(None)
