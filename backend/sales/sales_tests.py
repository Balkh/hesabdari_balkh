from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounting.coa import seed_chart_of_accounts
from accounting.models import JournalEntry
from currencies.models import Currency
from inventory.models import StockMovement
from inventory.services import assign_warehouse_account
from inventory.stock import stock_for
from parties.services import create_party
from products.services import create_product
from categories.services import create_category
from uom.services import create_uom
from warehouses.services import create_warehouse

from .models import CheckStatus, PaymentMode, SaleStatus, SalesChannel
from .services import (
    SalesValidationError, create_sale, finalize_sale,
    finalize_warehouse_check, prepare_warehouse_check,
)


class SalesImplementationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        seed_chart_of_accounts()
        cls.user = None

    def setUp(self):
        self.category = create_category(name="Sales Test Category")
        self.unit = create_uom(name="Sales Test Unit")
        self.product = create_product(code="SALE-IMPL-1", name="Sales Test Product", name_fa="محصول فروش", category=self.category, primary_uom=self.unit)
        self.customer = create_party(name="Sales Test Customer", is_customer=True)
        self.warehouse_a = create_warehouse(name="Sales Test A")
        self.warehouse_b = create_warehouse(name="Sales Test B")
        assign_warehouse_account(warehouse=self.warehouse_a, account="1410")
        assign_warehouse_account(warehouse=self.warehouse_b, account="1420")

    def sale(self, quantity=100):
        return create_sale(
            customer=self.customer, sale_date=date(2026, 1, 10), currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
            lines=[{"product": self.product, "unit": self.unit, "quantity": quantity, "unit_price": "10"}],
            document_number="SI-IMPL-1",
        )

    def test_sale_line_has_no_authoritative_warehouse_and_credit_posts_receivable(self):
        sale = self.sale()
        self.assertFalse(hasattr(sale.lines.get(), "warehouse_id"))
        finalize_sale(sale=sale)
        self.assertEqual(sale.__class__.objects.get(pk=sale.pk).status, SaleStatus.FINALIZED)
        self.assertEqual(JournalEntry.objects.filter(source_type="SALE").count(), 1)

    def test_multiple_partial_checks_are_limited_to_line_quantity(self):
        sale = self.sale()
        finalize_sale(sale=sale)
        line = sale.lines.get()
        first = prepare_warehouse_check(sale_line=line, warehouse=self.warehouse_a, quantity=30, number="WC-1")
        second = prepare_warehouse_check(sale_line=line, warehouse=self.warehouse_b, quantity=70, number="WC-2")
        finalize_warehouse_check(check=first, acknowledge_negative=True, temporary_unit_cost="4")
        finalize_warehouse_check(check=second, acknowledge_negative=True, temporary_unit_cost="4")
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 2)
        self.assertEqual(stock_for(self.product, self.warehouse_a), -30)
        self.assertEqual(stock_for(self.product, self.warehouse_b), -70)
        with self.assertRaises(SalesValidationError):
            prepare_warehouse_check(sale_line=line, warehouse=self.warehouse_a, quantity=1, number="WC-3")

    def test_check_requires_negative_acknowledgement(self):
        sale = self.sale()
        finalize_sale(sale=sale)
        check = prepare_warehouse_check(sale_line=sale.lines.get(), warehouse=self.warehouse_a, quantity=5, number="WC-NEG")
        with self.assertRaises(Exception):
            finalize_warehouse_check(check=check)
        finalized = finalize_warehouse_check(check=check, acknowledge_negative=True, temporary_unit_cost="4")
        self.assertEqual(finalized.status, CheckStatus.FINALIZED)
        self.assertEqual(stock_for(self.product, self.warehouse_a), -5)
