"""Evidence for the approved Phase 8 Sales contract.

Authoritative contract: ``docs/phase-reports/PHASE_8_RESOLVED_CONTRACT.md``.

Every assertion here maps to a clause of that resolved contract. This file is
deliberately separate from ``sales_tests.py`` so that no file in the
``PHASE_8_FROZEN_REFERENCE.md`` §3 SHA-256 manifest is modified.
"""

from datetime import date
from decimal import Decimal

import pytest

from django.test import TestCase

from accounting.balances import account_balance
from accounting.coa import seed_chart_of_accounts
from accounting.models import Account, JournalEntry
from categories.services import create_category
from currencies.models import Currency
from customer_custody.models import CustomerCustodyEvent, CustomerOwnershipEntitlement, CustodyEventType
from customer_custody.services import custody_balance
from inventory.models import StockMovement
from inventory.services import assign_warehouse_account
from inventory.stock import stock_for
from parties.services import create_party
from products.services import create_product
from purchases.services import create_purchase, post_purchase
from uom.services import create_uom
from warehouses.services import create_warehouse

from .models import (
    COGSAdjustment, NegativeCOGSObligation, PaymentMode,
    Sale, SaleLine, SaleStatus, SalesChannel, WarehouseCheck,
)
from .services import (
    create_sale, finalize_sale, finalize_warehouse_check, prepare_warehouse_check,
)


class ResolvedContractTests(TestCase):
    """Clause-by-clause evidence for PHASE_8_RESOLVED_CONTRACT.md."""

    @classmethod
    def setUpTestData(cls):
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        seed_chart_of_accounts()

    def setUp(self):
        self.category = create_category(name="Contract Category")
        self.unit = create_uom(name="Contract Unit")
        self.product = create_product(
            code="SALE-CT-1", name="Contract Product", name_fa="محصول قرارداد",
            category=self.category, primary_uom=self.unit,
        )
        self.customer = create_party(name="Contract Customer", is_customer=True)
        self.supplier = create_party(name="Contract Supplier", is_supplier=True)
        self.warehouse = create_warehouse(name="Contract Warehouse")
        assign_warehouse_account(warehouse=self.warehouse, account="1410")
        self.day = date(2026, 1, 10)

    def sale(self, *, channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
             quantity=10, unit_price="10", document_number="SI-CT-1"):
        return create_sale(
            customer=self.customer, sale_date=self.day, currency=self.afn,
            channel=channel, payment_mode=payment_mode, document_number=document_number,
            lines=[{"product": self.product, "unit": self.unit,
                    "quantity": quantity, "unit_price": unit_price}],
        )

    def balance(self, code):
        return account_balance(Account.objects.get(code=code))["balance"]

    def posted_lines(self, source_type, source_id=None):
        entries = JournalEntry.objects.filter(source_type=source_type)
        if source_id is not None:
            entries = entries.filter(source_id=source_id)
        return {line.account.code: line for line in entries.get().lines.all()}

    # Clause 1 — Warehouse belongs to WarehouseCheck, not SaleLine.

    def test_warehouse_binds_to_the_check_and_never_to_the_sale_line(self):
        self.assertNotIn("warehouse", [f.name for f in SaleLine._meta.get_fields()])
        self.assertNotIn("warehouse", [f.name for f in Sale._meta.get_fields()])
        self.assertIn("warehouse", [f.name for f in WarehouseCheck._meta.get_fields()])

        sale = self.sale()
        finalize_sale(sale=sale)
        line = sale.lines.get()
        check = prepare_warehouse_check(
            sale_line=line, warehouse=self.warehouse, quantity=10, number="WC-CT-1",
        )
        self.assertEqual(check.warehouse, self.warehouse)
        self.assertFalse(hasattr(line, "warehouse_id"))
        finalize_warehouse_check(
            check=check, acknowledge_negative=True, temporary_unit_cost="4",
        )
        movement = StockMovement.objects.get(reference="WC-CT-1")
        self.assertEqual(movement.warehouse, check.warehouse)
        self.assertEqual(stock_for(self.product, self.warehouse), -10)

    # Clause 2 — Sales Channel selects 4110 versus 4120.

    def test_sales_channel_selects_4110_wholesale_and_4120_retail(self):
        wholesale = self.sale(channel=SalesChannel.WHOLESALE, document_number="SI-CT-W")
        retail = self.sale(channel=SalesChannel.RETAIL, document_number="SI-CT-R")
        finalize_sale(sale=wholesale)
        finalize_sale(sale=retail)

        wholesale_lines = self.posted_lines("SALE", source_id="SI-CT-W")
        retail_lines = self.posted_lines("SALE", source_id="SI-CT-R")
        self.assertEqual(JournalEntry.objects.filter(source_type="SALE").count(), 2)
        self.assertEqual(wholesale_lines["4110"].credit, Decimal("100.00"))
        self.assertEqual(retail_lines["4120"].credit, Decimal("100.00"))
        self.assertEqual(wholesale_lines["1310"].debit, Decimal("100.00"))
        self.assertEqual(retail_lines["1310"].debit, Decimal("100.00"))
        self.assertNotIn("4120", wholesale_lines)
        self.assertNotIn("4110", retail_lines)

    # Clause 3 — Revenue at Sales Finalization. Clause 4 — COGS at finalized check.

    def test_revenue_posts_at_finalization_and_cogs_posts_only_at_check_finalization(self):
        sale = self.sale()
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

        finalize_sale(sale=sale)
        self.assertEqual(JournalEntry.objects.filter(source_type="SALE").count(), 1)
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), 0)
        self.assertEqual(self.balance("4110"), Decimal("100.00"))
        self.assertEqual(self.balance("5100"), Decimal("0.00"))

        check = prepare_warehouse_check(
            sale_line=sale.lines.get(), warehouse=self.warehouse, quantity=10, number="WC-CT-2",
        )
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), 0)

        finalize_warehouse_check(
            check=check, acknowledge_negative=True, temporary_unit_cost="4",
        )
        cogs = self.posted_lines("SALES_COGS")
        self.assertEqual(cogs["5100"].debit, Decimal("40.00"))
        self.assertEqual(cogs["1410"].credit, Decimal("40.00"))
        self.assertEqual(self.balance("5100"), Decimal("40.00"))
        self.assertEqual(JournalEntry.objects.filter(source_type="SALE").count(), 1)

    # Clause 7 — Sale finalization establishes ownership; Warehouse Check releases custody.

    def test_sale_finalization_creates_ownership_and_warehouse_check_releases_custody(self):
        sale = self.sale(quantity=10)
        finalize_sale(sale=sale)
        line = sale.lines.get()
        entitlement = CustomerOwnershipEntitlement.objects.get(sale_line=line)
        self.assertEqual(entitlement.quantity, 10)
        self.assertEqual(CustomerCustodyEvent.objects.count(), 0)

        first = prepare_warehouse_check(
            sale_line=line, warehouse=self.warehouse, quantity=4, number="WC-CT-3A")
        second = prepare_warehouse_check(
            sale_line=line, warehouse=self.warehouse, quantity=6, number="WC-CT-3B")
        self.assertEqual(CustomerCustodyEvent.objects.count(), 0)

        finalize_warehouse_check(
            check=first, acknowledge_negative=True, temporary_unit_cost="4")
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.warehouse), 0)
        self.assertEqual(
            CustomerCustodyEvent.objects.filter(event_type=CustodyEventType.PLACED).count(), 1)
        self.assertEqual(
            CustomerCustodyEvent.objects.filter(event_type=CustodyEventType.RELEASED).count(), 1)

        finalize_warehouse_check(
            check=second, acknowledge_negative=True, temporary_unit_cost="4")
        self.assertEqual(CustomerCustodyEvent.objects.count(), 4)
        self.assertEqual(
            CustomerCustodyEvent.objects.filter(event_type=CustodyEventType.RELEASED).count(), 2)
    # Clauses 5 and 6 — Payment separate from Sale; release separate from Payment.

    def test_payment_is_separate_from_sale_and_release_does_not_settle(self):
        sale = self.sale(quantity=10, unit_price="10")
        finalize_sale(sale=sale)
        self.assertEqual(self.balance("1310"), Decimal("100.00"))

        check = prepare_warehouse_check(
            sale_line=sale.lines.get(), warehouse=self.warehouse, quantity=10, number="WC-CT-4",
        )
        finalize_warehouse_check(
            check=check, acknowledge_negative=True, temporary_unit_cost="4")
        self.assertEqual(self.balance("1310"), Decimal("100.00"))
        self.assertEqual(self.balance("5100"), Decimal("40.00"))
        self.assertFalse(
            JournalEntry.objects.filter(source_type__in=["SALE_PAYMENT", "PAYMENT"]).exists())
        self.assertEqual(
            StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 1)

    def test_cash_sale_debits_cash_not_receivable(self):
        sale = self.sale(payment_mode=PaymentMode.CASH, document_number="SI-CT-CASH")
        finalize_sale(sale=sale)
        entry = JournalEntry.objects.get(source_type="SALE", source_id="SI-CT-CASH")
        self.assertEqual(entry.lines.get(account__code="1110").debit, Decimal("100.00"))
        self.assertEqual(self.balance("1310"), Decimal("0.00"))

    # Clause 4 / Purchase hook — negative COGS obligation resolved by receipt cost.

    def test_negative_stock_issue_registers_obligation_resolved_by_purchase_receipt(self):
        sale = self.sale(quantity=10, document_number="SI-CT-NEG")
        finalize_sale(sale=sale)
        check = prepare_warehouse_check(
            sale_line=sale.lines.get(), warehouse=self.warehouse, quantity=10, number="WC-CT-5",
        )
        finalize_warehouse_check(
            check=check, acknowledge_negative=True, temporary_unit_cost="4")

        obligation = NegativeCOGSObligation.objects.get()
        self.assertEqual(obligation.warehouse_check, check)
        self.assertEqual(obligation.product, self.product)
        self.assertEqual(obligation.warehouse, self.warehouse)
        self.assertEqual(obligation.original_quantity, 10)
        self.assertEqual(obligation.resolved_quantity, 0)
        self.assertEqual(obligation.temporary_unit_cost_afn, Decimal("4.0000"))
        self.assertEqual(self.balance("5100"), Decimal("40.00"))
        self.assertEqual(COGSAdjustment.objects.count(), 0)

        purchase = create_purchase(
            supplier=self.supplier, purchase_date=self.day, currency=self.afn,
            warehouse=self.warehouse, document_number="PI-CT-1",
            lines=[{"product": self.product, "quantity": 10, "unit_price": "6.0000"}],
        )
        post_purchase(purchase=purchase)

        obligation.refresh_from_db()
        self.assertEqual(obligation.resolved_quantity, 10)
        adjustment = COGSAdjustment.objects.get()
        self.assertEqual(adjustment.obligation, obligation)
        self.assertEqual(adjustment.quantity, 10)
        self.assertEqual(adjustment.actual_unit_cost_afn, Decimal("6.0000"))
        self.assertEqual(adjustment.temporary_unit_cost_afn, Decimal("4.0000"))
        self.assertEqual(adjustment.difference, Decimal("20.00"))
        correction = self.posted_lines("SALES_COGS_ADJUSTMENT")
        self.assertEqual(correction["5100"].debit, Decimal("20.00"))
        self.assertEqual(correction["1410"].credit, Decimal("20.00"))
        self.assertEqual(self.balance("5100"), Decimal("60.00"))
        self.assertEqual(
            JournalEntry.objects.filter(source_type="SALES_COGS").count(), 1)

    # Clause 8 / lifecycle — Sale commercial state is separate from the check.

    def test_finalized_sale_is_immutable_and_draft_sale_creates_no_journal(self):
        sale = self.sale(document_number="SI-CT-DRAFT")
        self.assertEqual(sale.status, SaleStatus.DRAFT)
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(CustomerOwnershipEntitlement.objects.count(), 0)
        self.assertEqual(COGSAdjustment.objects.count(), 0)
        with self.assertRaises(Exception):
            prepare_warehouse_check(
                sale_line=sale.lines.get(), warehouse=self.warehouse, quantity=1, number="WC-CT-6")

        finalize_sale(sale=sale)
        self.assertEqual(finalize_sale(sale=sale).status, SaleStatus.FINALIZED)
        self.assertEqual(JournalEntry.objects.filter(source_type="SALE").count(), 1)
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), 0)


@pytest.mark.django_db
def test_foreign_credit_sale_does_not_require_invoice_rate():
    from datetime import date
    from decimal import Decimal
    from django.contrib.auth import get_user_model
    from accounting.coa import seed_chart_of_accounts
    from currencies.models import Currency
    from parties.models import Party
    from categories.models import Category
    from products.models import Product
    from uom.models import UnitOfMeasure
    from .models import PaymentMode, SalesChannel
    from .services import create_sale, finalize_sale

    user = get_user_model().objects.create_user(username="sale-ccs-rate")
    afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
    usd = Currency.objects.create(code="USD", name="US Dollar", is_base=False)
    seed_chart_of_accounts()
    customer = Party.objects.create(name="Ahmad", is_customer=True)
    category = Category.objects.create(name="Oil")
    unit = UnitOfMeasure.objects.create(name="Piece")
    product = Product.objects.create(code="OIL-CCS", name="Oil", name_fa="روغن", category=category, primary_uom=unit)
    sale = create_sale(
        customer=customer, sale_date=date(2026, 9, 28), currency=usd,
        channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
        lines=[{"product": product, "unit": unit, "quantity": 1, "unit_price": Decimal("5000")}],
        rate=None, rate_date=None, user=user, document_number="SI-CCS-RATE-1",
    )
    assert sale.exchange_rate is None
    assert sale.rate_date is None
    finalized = finalize_sale(sale=sale, user=user)
    assert finalized.journal_entry.currency_id == usd.id
    assert finalized.journal_entry.rate is None
    assert finalized.journal_entry.afn_total is None
