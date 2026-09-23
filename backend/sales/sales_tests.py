from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounting.models import JournalEntry, PostedImmutabilityError
from categories.services import create_category
from core.models import IdempotencyRecord
from currencies.models import Currency
from fiscal_periods.services import PeriodValidationError, close_period, create_period
from inventory.models import StockMovement
from inventory.stock import avco_for, stock_for
from parties.services import create_party
from products.services import create_product
from security.models import AuditEvent
from uom.services import create_uom
from warehouses.services import create_warehouse

from .models import Sale, SaleLine, SaleStatus, SaleType
from .services import SaleValidationError, create_sale, finalize_sale, update_sale, update_sale_line


class SalesCoreTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")
        cls.user = get_user_model().objects.create_user("sales-user", password="x")

    def setUp(self):
        category = create_category(name="Sales Category", user=self.user)
        self.uom = create_uom(name="Sales Unit", user=self.user)
        self.product = create_product(
            code="SAL-1", name="Sales Product", name_fa="فروش", category=category,
            primary_uom=self.uom, user=self.user,
        )
        self.customer = create_party(name="Sales Customer", is_customer=True, user=self.user)
        self.warehouse_a = create_warehouse(name="Sales Warehouse A", user=self.user)
        self.warehouse_b = create_warehouse(name="Sales Warehouse B", user=self.user)
        self.day = date(2026, 2, 10)

    def _sale(self, **kwargs):
        params = dict(
            customer=self.customer, sale_date=self.day, currency=self.afn,
            sale_type=SaleType.AVAILABLE,
            lines=[{"product": self.product, "warehouse": self.warehouse_a,
                     "unit": self.uom, "quantity": 10, "unit_price": "12.0000"}],
            user=self.user,
        )
        params.update(kwargs)
        return create_sale(**params)

    def test_draft_creation_is_commercial_only_and_audited(self):
        sale = self._sale(document_number="SI-DRAFT-001")
        self.assertEqual(sale.status, SaleStatus.DRAFT)
        self.assertEqual(sale.sale_type, SaleType.AVAILABLE)
        self.assertEqual(sale.subtotal, Decimal("120.00"))
        self.assertEqual(sale.total_discount, Decimal("0.00"))
        self.assertEqual(sale.total, Decimal("120.00"))
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertTrue(AuditEvent.objects.filter(entity="Sale", entity_id=sale.pk, action="CREATE").exists())

    def test_multiple_lines_multiple_warehouses_and_repeated_product_preserve_identity(self):
        sale = self._sale(
            document_number="SI-MULTI-001",
            lines=[
                {"product": self.product, "warehouse": self.warehouse_a,
                 "unit": self.uom, "quantity": 10, "unit_price": "12"},
                {"product": self.product, "warehouse": self.warehouse_b,
                 "unit": self.uom, "quantity": 5, "unit_price": "20", "discount": "10"},
            ],
        )
        lines = list(sale.lines.order_by("id"))
        self.assertEqual([line.warehouse_id for line in lines], [self.warehouse_a.pk, self.warehouse_b.pk])
        self.assertEqual([line.product_id for line in lines], [self.product.pk, self.product.pk])
        self.assertEqual(sale.subtotal, Decimal("220.00"))
        self.assertEqual(sale.total_discount, Decimal("10.00"))
        self.assertEqual(sale.total, Decimal("210.00"))

    def test_required_master_roles_and_line_fields_are_validated(self):
        supplier = create_party(name="Only Supplier", is_supplier=True, user=self.user)
        with self.assertRaises(SaleValidationError):
            self._sale(customer=supplier)
        with self.assertRaises(SaleValidationError):
            self._sale(lines=[{"product": self.product, "warehouse": None, "unit": self.uom,
                               "quantity": 1, "unit_price": "1"}])
        with self.assertRaises(SaleValidationError):
            self._sale(lines=[{"product": self.product, "warehouse": self.warehouse_a,
                               "unit": self.uom, "quantity": 0, "unit_price": "1"}])
        with self.assertRaises(SaleValidationError):
            self._sale(lines=[{"product": self.product, "warehouse": self.warehouse_a,
                               "unit": self.uom, "quantity": 1, "unit_price": "-1"}])
        with self.assertRaises(SaleValidationError):
            self._sale(lines=[{"product": self.product, "warehouse": self.warehouse_a,
                               "unit": self.uom, "quantity": 1, "unit_price": "10", "discount": "10.01"}])

    def test_base_and_foreign_currency_exchange_rules(self):
        sale = self._sale(document_number="SI-AFN-001")
        self.assertEqual(sale.exchange_rate, Decimal("1.0000"))
        self.assertEqual(sale.rate_date, self.day)
        foreign = self._sale(currency=self.usd, rate="70", rate_date=self.day, document_number="SI-USD-001")
        self.assertEqual(foreign.exchange_rate, Decimal("70.0000"))
        with self.assertRaises(SaleValidationError):
            self._sale(currency=self.usd, document_number="SI-USD-MISSING")

    def test_finalizes_available_without_accounting_or_inventory_effects(self):
        sale = self._sale(document_number="SI-FINAL-AVAILABLE")
        finalized = finalize_sale(sale=sale, user=self.user, idempotency_key="sale-final-available")
        self.assertEqual(finalized.status, SaleStatus.FINALIZED)
        self.assertIsNotNone(finalized.finalized_at)
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.filter(entity="Sale", entity_id=sale.pk, action="APPROVE").count(), 1)
        self.assertEqual(IdempotencyRecord.objects.filter(key="sale-final-available").count(), 1)

    def test_finalizes_future_without_inventory_avco_custody_or_release(self):
        sale = self._sale(sale_type=SaleType.FUTURE, document_number="SI-FUTURE-001")
        before_stock = stock_for(self.product, self.warehouse_a)
        before_avco = avco_for(self.product, self.warehouse_a)
        finalize_sale(sale=sale, user=self.user)
        sale.refresh_from_db()
        self.assertEqual(sale.status, SaleStatus.FINALIZED)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(stock_for(self.product, self.warehouse_a), before_stock)
        self.assertEqual(avco_for(self.product, self.warehouse_a), before_avco)
        self.assertFalse(hasattr(sale, "custody"))

    def test_finalization_is_idempotent_and_different_key_payload_is_rejected(self):
        sale = self._sale(document_number="SI-IDEMPOTENT")
        first = finalize_sale(sale=sale, user=self.user, idempotency_key="sale-idempotent")
        second = finalize_sale(sale=sale, user=self.user, idempotency_key="sale-idempotent")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(AuditEvent.objects.filter(entity="Sale", entity_id=sale.pk, action="APPROVE").count(), 1)
        self.assertEqual(IdempotencyRecord.objects.filter(key="sale-idempotent").count(), 1)
        other = self._sale(document_number="SI-IDEMPOTENT-OTHER")
        with self.assertRaises(SaleValidationError):
            finalize_sale(sale=other, user=self.user, idempotency_key="sale-idempotent")

    def test_finalized_sale_and_lines_reject_normal_and_bulk_mutation(self):
        sale = self._sale(document_number="SI-IMMUTABLE")
        finalize_sale(sale=sale, user=self.user)
        sale.refresh_from_db()
        line = sale.lines.get()
        sale.customer = create_party(name="Other Customer", is_customer=True, user=self.user)
        with self.assertRaises(PostedImmutabilityError):
            sale.save()
        with self.assertRaises(PostedImmutabilityError):
            Sale.objects.filter(pk=sale.pk).update(total=Decimal("1.00"))
        line.quantity = 99
        with self.assertRaises(PostedImmutabilityError):
            line.save()
        with self.assertRaises(PostedImmutabilityError):
            SaleLine.objects.filter(pk=line.pk).update(quantity=99)
        with self.assertRaises(PostedImmutabilityError):
            Sale.objects.filter(pk=sale.pk).delete()
        with self.assertRaises(PostedImmutabilityError):
            SaleLine.objects.filter(pk=line.pk).delete()
        self.assertEqual(Sale.objects.get(pk=sale.pk).status, SaleStatus.FINALIZED)
        self.assertEqual(SaleLine.objects.get(pk=line.pk).quantity, 10)

    def test_draft_update_recalculates_and_audits(self):
        sale = self._sale(document_number="SI-DRAFT-UPDATE")
        updated = update_sale(
            sale, sale_type=SaleType.FUTURE,
            lines=[{"product": self.product, "warehouse": self.warehouse_b,
                     "unit": self.uom, "quantity": 4, "unit_price": "100", "discount": "5"}],
            user=self.user,
        )
        self.assertEqual(updated.sale_type, SaleType.FUTURE)
        self.assertEqual(updated.subtotal, Decimal("400.00"))
        self.assertEqual(updated.total_discount, Decimal("5.00"))
        self.assertEqual(updated.total, Decimal("395.00"))
        self.assertEqual(updated.lines.get().warehouse_id, self.warehouse_b.pk)
        self.assertTrue(AuditEvent.objects.filter(entity="Sale", entity_id=sale.pk, action="UPDATE").exists())
        update_sale_line(updated.lines.get(), quantity=5, unit_price="90", user=self.user)
        updated.refresh_from_db()
        self.assertEqual(updated.lines.get().quantity, 5)
        self.assertEqual(updated.total, Decimal("445.00"))

    def test_finalization_rejects_inconsistent_totals_before_side_effects(self):
        sale = self._sale(document_number="SI-INCONSISTENT")
        line = sale.lines.get()
        line.line_total = Decimal("999.00")
        line.save(update_fields=["line_total"])
        with self.assertRaises(SaleValidationError):
            finalize_sale(sale=sale, user=self.user)
        sale.refresh_from_db()
        self.assertEqual(sale.status, SaleStatus.DRAFT)
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_closed_fiscal_period_rejects_finalization_without_side_effects(self):
        period = create_period(name="Closed Sales Period", start_date=self.day, end_date=self.day, user=self.user)
        close_period(period, user=self.user, reason="Sales Core test")
        sale = self._sale(document_number="SI-CLOSED")
        with self.assertRaises(PeriodValidationError):
            finalize_sale(sale=sale, user=self.user, idempotency_key="sale-closed")
        sale.refresh_from_db()
        self.assertEqual(sale.status, SaleStatus.DRAFT)
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertFalse(IdempotencyRecord.objects.filter(key="sale-closed").exists())

    def test_only_draft_can_be_updated(self):
        sale = self._sale(document_number="SI-NO-UPDATE")
        finalize_sale(sale=sale, user=self.user)
        with self.assertRaises(SaleValidationError):
            update_sale(sale, sale_type=SaleType.FUTURE, user=self.user)
