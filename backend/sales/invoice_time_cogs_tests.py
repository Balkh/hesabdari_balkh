"""Invoice-time COGS / warehouse-allocation regression evidence (Phase 8).

Owner contract: docs/phase-8-invoice-time-cogs-allocation-contract.md
Ordinary stock issues + COGS post at invoice finalization per explicit
SaleLine warehouse allocation; Warehouse Check releases custody only.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounting.balances import account_balance
from accounting.coa import seed_chart_of_accounts
from accounting.models import Account, JournalEntry
from categories.services import create_category
from currencies.models import Currency
from customer_custody.services import custody_balance
from customer_custody.models import CustomerOwnershipEntitlement
from inventory.models import StockMovement
from inventory.services import assign_warehouse_account, receive_stock
from inventory.stock import stock_for
from parties.services import create_party
from products.services import create_product
from uom.services import create_uom
from warehouses.services import create_warehouse

from .models import PaymentMode, SalesChannel
from .services import (
    SalesValidationError, create_sale, finalize_sale,
    finalize_warehouse_check, prepare_warehouse_check,
)


class InvoiceTimeCogsAllocationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        seed_chart_of_accounts()

    def setUp(self):
        category = create_category(name="Alloc Category")
        self.unit = create_uom(name="Alloc Unit")
        self.product = create_product(code="ALLOC-1", name="Alloc Product", name_fa="محصول تخصیص", category=category, primary_uom=self.unit)
        self.customer = create_party(name="Alloc Customer", is_customer=True)
        self.wh_a = create_warehouse(name="Alloc A")
        self.wh_b = create_warehouse(name="Alloc B")
        assign_warehouse_account(warehouse=self.wh_a, account="1410")
        assign_warehouse_account(warehouse=self.wh_b, account="1420")
        self.day = date(2026, 2, 1)
        receive_stock(product=self.product, warehouse=self.wh_a, quantity=10, unit_cost="4", currency=self.afn, movement_date=self.day, reference="ALLOC-RCPT-A")
        receive_stock(product=self.product, warehouse=self.wh_b, quantity=10, unit_cost="6", currency=self.afn, movement_date=self.day, reference="ALLOC-RCPT-B")

    def balance(self, code):
        return account_balance(Account.objects.get(code=code))["balance"]

    def make_sale(self, *, allocations, quantity=10, number="SI-ALLOC-1", payment=PaymentMode.CREDIT):
        return create_sale(
            customer=self.customer, sale_date=self.day, currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=payment,
            document_number=number,
            lines=[{"product": self.product, "unit": self.unit, "quantity": quantity,
                    "unit_price": "10", "allocations": allocations}],
        )

    def test_split_allocation_posts_per_warehouse_cogs_at_invoice(self):
        sale = self.make_sale(allocations=[{"warehouse": self.wh_a, "quantity": 4},
                                           {"warehouse": self.wh_b, "quantity": 6}])
        finalize_sale(sale=sale)
        self.assertEqual(stock_for(self.product, self.wh_a), 6)
        self.assertEqual(stock_for(self.product, self.wh_b), 4)
        # COGS = 4*4 + 6*6 = 52, credited per mapped warehouse account.
        self.assertEqual(self.balance("5100"), Decimal("52.00"))
        self.assertEqual(self.balance("1410"), Decimal("-16.00"))
        self.assertEqual(self.balance("1420"), Decimal("-36.00"))
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), 2)
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 2)

    def test_cash_sale_posts_cash_and_cogs_at_invoice(self):
        sale = self.make_sale(allocations=[{"warehouse": self.wh_a, "quantity": 10}],
                              number="SI-ALLOC-CASH", payment=PaymentMode.CASH)
        finalize_sale(sale=sale)
        self.assertEqual(self.balance("1110"), Decimal("100.00"))
        self.assertEqual(self.balance("5100"), Decimal("40.00"))

    def test_missing_allocation_rolls_back_everything(self):
        sale = create_sale(
            customer=self.customer, sale_date=self.day, currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
            document_number="SI-ALLOC-NONE",
            lines=[{"product": self.product, "unit": self.unit, "quantity": 5, "unit_price": "10"}],
        )
        with self.assertRaises(SalesValidationError):
            finalize_sale(sale=sale)
        sale.refresh_from_db()
        self.assertEqual(sale.status, "DRAFT")
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 0)
        self.assertEqual(CustomerOwnershipEntitlement.objects.count(), 0)

    def test_allocation_sum_must_equal_line_quantity(self):
        with self.assertRaises(SalesValidationError):
            self.make_sale(allocations=[{"warehouse": self.wh_a, "quantity": 3}], number="SI-ALLOC-SUM")

    def test_repeated_finalization_is_idempotent(self):
        sale = self.make_sale(allocations=[{"warehouse": self.wh_a, "quantity": 10}])
        finalize_sale(sale=sale)
        finalize_sale(sale=sale)
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), 1)
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 1)
        self.assertEqual(self.balance("5100"), Decimal("40.00"))

    def test_partial_checks_release_custody_only_and_wrong_warehouse_rejected(self):
        sale = self.make_sale(allocations=[{"warehouse": self.wh_a, "quantity": 10}])
        finalize_sale(sale=sale)
        line = sale.lines.get()
        wrong = prepare_warehouse_check(sale_line=line, warehouse=self.wh_b, quantity=1, number="WC-ALLOC-WRONG")
        with self.assertRaises(SalesValidationError):
            finalize_warehouse_check(check=wrong)
        first = prepare_warehouse_check(sale_line=line, warehouse=self.wh_a, quantity=4, number="WC-ALLOC-1")
        finalize_warehouse_check(check=first)
        finalize_warehouse_check(check=first)  # duplicate request: no-op
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), 1)
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 1)
        self.assertEqual(stock_for(self.product, self.wh_a), 0)
        entitlement = CustomerOwnershipEntitlement.objects.get(sale_line=line)
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.wh_a), 0)
        second = prepare_warehouse_check(sale_line=line, warehouse=self.wh_a, quantity=6, number="WC-ALLOC-2")
        finalize_warehouse_check(check=second)
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 1)
