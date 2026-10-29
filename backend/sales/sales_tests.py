from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounting.coa import seed_chart_of_accounts
from accounting.models import JournalEntry
from currencies.models import Currency
from customer_custody.models import CustomerCustodyEvent, CustomerOwnershipEntitlement
from inventory.models import StockMovement
from inventory.services import assign_warehouse_account
from inventory.stock import stock_for
from parties.services import create_party
from products.services import create_product
from categories.services import create_category
from uom.services import create_uom
from warehouses.services import create_warehouse

from .models import CheckStatus, PaymentMode, SaleStatus, SaleType, SalesChannel
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

    def sale(self, quantity=100, allocations=None):
        return create_sale(
            customer=self.customer, sale_date=date(2026, 1, 10), currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
            lines=[{"product": self.product, "unit": self.unit, "quantity": quantity, "unit_price": "10",
                    "allocations": allocations or [{"warehouse": self.warehouse_a, "quantity": quantity}]}],
            document_number="SI-IMPL-1",
        )

    def test_sale_line_has_no_authoritative_warehouse_and_credit_posts_receivable(self):
        sale = self.sale()
        self.assertFalse(hasattr(sale.lines.get(), "warehouse_id"))
        finalize_sale(sale=sale, acknowledge_negative=True, temporary_unit_cost="4")
        self.assertEqual(sale.__class__.objects.get(pk=sale.pk).status, SaleStatus.FINALIZED)
        self.assertEqual(JournalEntry.objects.filter(source_type="SALE").count(), 1)
        # Invoice-time COGS: stock issued once at finalization, Dr 5100/Cr 1410.
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), 1)
        self.assertEqual(stock_for(self.product, self.warehouse_a), -100)

    def test_multiple_partial_checks_are_limited_to_line_quantity(self):
        sale = self.sale(allocations=[{"warehouse": self.warehouse_a, "quantity": 30},
                                      {"warehouse": self.warehouse_b, "quantity": 70}])
        finalize_sale(sale=sale, acknowledge_negative=True, temporary_unit_cost="4")
        line = sale.lines.get()
        first = prepare_warehouse_check(sale_line=line, warehouse=self.warehouse_a, quantity=30, number="WC-1")
        second = prepare_warehouse_check(sale_line=line, warehouse=self.warehouse_b, quantity=70, number="WC-2")
        finalize_warehouse_check(check=first)
        finalize_warehouse_check(check=second)
        # Both issues happened at invoice finalization (allocations A30/B70);
        # the checks themselves create no further stock movements.
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 2)
        self.assertEqual(stock_for(self.product, self.warehouse_a), -30)
        self.assertEqual(stock_for(self.product, self.warehouse_b), -70)
        with self.assertRaises(SalesValidationError):
            prepare_warehouse_check(sale_line=line, warehouse=self.warehouse_a, quantity=1, number="WC-3")

    def test_check_requires_negative_acknowledgement(self):
        # Negative-stock acknowledgement/cost is now required at invoice
        # finalization (where the issue + COGS post), not at Warehouse Check.
        sale = self.sale(quantity=5)
        with self.assertRaises(Exception):
            finalize_sale(sale=sale)
        finalized_sale = finalize_sale(sale=sale, acknowledge_negative=True, temporary_unit_cost="4")
        self.assertEqual(finalized_sale.status, SaleStatus.FINALIZED)
        self.assertEqual(stock_for(self.product, self.warehouse_a), -5)
        check = prepare_warehouse_check(sale_line=sale.lines.get(), warehouse=self.warehouse_a, quantity=5, number="WC-NEG")
        finalized = finalize_warehouse_check(check=check)
        self.assertEqual(finalized.status, CheckStatus.FINALIZED)
        self.assertEqual(stock_for(self.product, self.warehouse_a), -5)

    # Owner-approved revenue timing (2026-10-29): sales revenue is recognized
    # at successful invoice finalization for all supported sale types,
    # including FUTURE. Physical receipt, custody, delivery, and payment
    # remain separate events.

    def future_sale(self, *, allocations=None, document_number):
        return create_sale(
            customer=self.customer, sale_date=date(2026, 1, 10), currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
            sale_type=SaleType.FUTURE, document_number=document_number,
            lines=[{"product": self.product, "unit": self.unit, "quantity": 10,
                    "unit_price": "10",
                    "allocations": allocations}],
        )

    def test_future_sale_finalization_posts_revenue_once_without_stock_custody_or_payment(self):
        sale = self.future_sale(document_number="SI-IMPL-FUT-1")
        self.assertEqual(JournalEntry.objects.count(), 0)
        finalized = finalize_sale(sale=sale)
        self.assertEqual(finalized.status, SaleStatus.FINALIZED)
        # Revenue is recognized exactly once, at invoice finalization:
        # Dr 1310 / Cr 4110, no second revenue journal on any later event.
        self.assertEqual(JournalEntry.objects.filter(source_type="SALE").count(), 1)
        lines = {line.account.code: line for line in finalized.journal_entry.lines.all()}
        self.assertEqual(lines["1310"].debit, Decimal("100.00"))
        self.assertEqual(lines["4110"].credit, Decimal("100.00"))
        # Finalization creates no stock issue, no COGS, no customer
        # ownership/custody, and no payment receipt.
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(CustomerOwnershipEntitlement.objects.count(), 0)
        self.assertEqual(CustomerCustodyEvent.objects.count(), 0)
        self.assertFalse(
            JournalEntry.objects.filter(source_type__in=["SALE_PAYMENT", "PAYMENT"]).exists())

    def test_future_warehouse_check_without_ownership_rejects_with_domain_error(self):
        sale = self.future_sale(document_number="SI-IMPL-FUT-2")
        finalize_sale(sale=sale)
        check = prepare_warehouse_check(
            sale_line=sale.lines.get(), warehouse=self.warehouse_a, quantity=10,
            number="WC-IMPL-FUT-1",
        )
        before = {
            "journals": JournalEntry.objects.count(),
            "movements": StockMovement.objects.count(),
            "entitlements": CustomerOwnershipEntitlement.objects.count(),
            "custody_events": CustomerCustodyEvent.objects.count(),
        }
        with self.assertRaises(SalesValidationError) as rejected:
            finalize_warehouse_check(check=check)
        self.assertIn("customer ownership entitlement", str(rejected.exception))
        check.refresh_from_db()
        self.assertEqual(check.status, CheckStatus.DRAFT)
        self.assertIsNone(check.stock_movement)
        self.assertIsNone(check.cogs_journal)
        # Retrying is the same explicit rejection, never a leak of the
        # underlying CustomerOwnershipEntitlement.DoesNotExist.
        with self.assertRaises(SalesValidationError):
            finalize_warehouse_check(check=check)
        after = {
            "journals": JournalEntry.objects.count(),
            "movements": StockMovement.objects.count(),
            "entitlements": CustomerOwnershipEntitlement.objects.count(),
            "custody_events": CustomerCustodyEvent.objects.count(),
        }
        self.assertEqual(before, after)
        # The finalized sale's revenue journal is untouched by the rejection.
        self.assertEqual(JournalEntry.objects.filter(source_type="SALE").count(), 1)

    def test_future_warehouse_check_with_allocation_intent_is_rejected_without_side_effects(self):
        sale = self.future_sale(
            allocations=[{"warehouse": self.warehouse_a, "quantity": 10}],
            document_number="SI-IMPL-FUT-3",
        )
        finalize_sale(sale=sale)
        line = sale.lines.get()
        allocation = line.warehouse_allocations.get()
        check = prepare_warehouse_check(
            sale_line=line, warehouse=self.warehouse_a, quantity=10,
            number="WC-IMPL-FUT-2",
        )
        with self.assertRaises(SalesValidationError) as rejected:
            finalize_warehouse_check(check=check)
        self.assertIn("customer ownership entitlement", str(rejected.exception))
        check.refresh_from_db()
        self.assertEqual(check.status, CheckStatus.DRAFT)
        # The recorded allocation intent was never issued: no stock movement,
        # no COGS journal, no ownership or custody records appeared.
        allocation.refresh_from_db()
        self.assertIsNone(allocation.stock_movement)
        self.assertIsNone(allocation.cogs_journal)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), 0)
        self.assertEqual(CustomerOwnershipEntitlement.objects.count(), 0)
        self.assertEqual(CustomerCustodyEvent.objects.count(), 0)
