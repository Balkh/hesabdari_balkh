from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from accounting.coa import seed_chart_of_accounts
from accounting.models import Account, JournalValidationError
from categories.services import create_category
from currencies.models import Currency
from inventory.services import receive_stock
from inventory.stock import stock_for
from parties.services import create_party
from products.services import create_product
from uom.services import create_uom
from warehouses.services import assign_warehouse_account, create_warehouse

from .models import PaymentMode, SalesChannel, SalesReturnStatus
from .returns_services import (
    ReturnValidationError,
    _allocate_return_entitlement,
    _refund_amount,
    create_refund,
    create_sales_return,
    reverse_refund,
    reverse_sales_return,
)
from .services import (
    create_sale, finalize_sale, finalize_warehouse_check, prepare_warehouse_check,
)
from accounting.services import reverse_journal


class Phase11RefundMathTests(SimpleTestCase):
    def test_usd_entitlement_refunded_in_afn(self):
        usd = SimpleNamespace(pk=1, is_base=False, code="USD")
        afn = SimpleNamespace(pk=2, is_base=True, code="AFN")
        self.assertEqual(
            _refund_amount(Decimal("2000.00"), usd, afn, Decimal("65")),
            Decimal("130000.00"),
        )

    def test_afn_entitlement_refunded_in_usd(self):
        afn = SimpleNamespace(pk=2, is_base=True, code="AFN")
        usd = SimpleNamespace(pk=1, is_base=False, code="USD")
        self.assertEqual(
            _refund_amount(Decimal("130000.00"), afn, usd, Decimal("65")),
            Decimal("2000.00"),
        )

    def test_same_currency_refund_keeps_amount(self):
        usd = SimpleNamespace(pk=1, is_base=False, code="USD")
        self.assertEqual(
            _refund_amount(Decimal("2000.00"), usd, usd, Decimal("1")),
            Decimal("2000.00"),
        )

    def test_partial_returns_allocate_exact_full_line_value_without_rounding_leak(self):
        total = Decimal("1.00")
        first = _allocate_return_entitlement(
            net_total=total, sale_quantity=3, returned_quantity=0,
            prior_amount=Decimal("0.00"), quantity=1,
        )
        second = _allocate_return_entitlement(
            net_total=total, sale_quantity=3, returned_quantity=1,
            prior_amount=first, quantity=1,
        )
        third = _allocate_return_entitlement(
            net_total=total, sale_quantity=3, returned_quantity=2,
            prior_amount=first + second, quantity=1,
        )
        self.assertEqual([first, second, third], [
            Decimal("0.33"), Decimal("0.33"), Decimal("0.34")
        ])
        self.assertEqual(first + second + third, total)

    def test_return_entitlement_rejects_quantity_above_remaining_line_quantity(self):
        with self.assertRaises(ReturnValidationError):
            _allocate_return_entitlement(
                net_total=Decimal("100.00"), sale_quantity=3,
                returned_quantity=2, prior_amount=Decimal("66.66"),
                quantity=2,
            )



class Phase11WorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar", is_base=False)
        seed_chart_of_accounts()

    def setUp(self):
        category = create_category(name="Phase 11 Category")
        unit = create_uom(name="Phase 11 Unit")
        self.product = create_product(
            code="P11-RETURN-1", name="Phase 11 Product",
            name_fa="محصول فاز یازده", category=category, primary_uom=unit,
        )
        self.unit = unit
        self.customer = create_party(name="Phase 11 Customer", is_customer=True)
        self.warehouse = create_warehouse(name="Phase 11 Warehouse")
        assign_warehouse_account(warehouse=self.warehouse, account="1410")
        self.day = date(2026, 1, 10)
        receive_stock(
            product=self.product, warehouse=self.warehouse, quantity=20,
            unit_cost="4", currency=self.afn, movement_date=self.day,
            reference="P11-STOCK-RECEIPT", description="Phase 11 test stock",
        )

    def make_sale(self, *, currency, payment_mode, document_number):
        sale = create_sale(
            customer=self.customer, sale_date=self.day, currency=currency,
            channel=SalesChannel.WHOLESALE, payment_mode=payment_mode,
            document_number=document_number,
            lines=[{
                "product": self.product, "unit": self.unit,
                "quantity": 10, "unit_price": "100",
            }],
        )
        finalize_sale(sale=sale)
        line = sale.lines.get()
        check = prepare_warehouse_check(
            sale_line=line, warehouse=self.warehouse, quantity=10,
            number=f"WC-{document_number}",
        )
        finalize_warehouse_check(check=check)
        return sale, line

    def test_usd_return_refunded_in_afn_reduces_afn_cash_only(self):
        sale, line = self.make_sale(
            currency=self.usd, payment_mode=PaymentMode.CASH,
            document_number="P11-USD-CASH",
        )
        returned = create_sales_return(
            sale_line=line, warehouse=self.warehouse, quantity=2,
            return_date=self.day, reason="Customer returned two units",
            document_number="P11-SR-USD-AFN", idempotency_key="p11-sr-usd-afn",
        )
        refund = create_refund(
            sales_return=returned, refund_date=self.day,
            refund_currency=self.afn, entitlement_amount="200",
            rate="65", reason="Refund in AFN",
            document_number="P11-RF-USD-AFN", idempotency_key="p11-rf-usd-afn",
        )
        self.assertEqual(returned.entitlement_currency, self.usd)
        self.assertEqual(refund.refund_currency, self.afn)
        self.assertEqual(refund.refund_amount, Decimal("13000.00"))
        self.assertEqual(refund.journal_entry.currency, self.afn)
        cash_line = refund.journal_entry.lines.get(account__code="1110")
        self.assertEqual(cash_line.credit, Decimal("13000.00"))
        self.assertEqual(stock_for(self.product, self.warehouse), 12)

    def test_cross_currency_refund_requires_aggregate_reversal_and_return_can_then_reverse(self):
        _sale, line = self.make_sale(
            currency=self.usd, payment_mode=PaymentMode.CASH,
            document_number="P11-USD-REV",
        )
        returned = create_sales_return(
            sale_line=line, warehouse=self.warehouse, quantity=2,
            return_date=self.day, reason="Return before reversal",
            document_number="P11-SR-REV", idempotency_key="p11-sr-rev",
        )
        refund = create_refund(
            sales_return=returned, refund_date=self.day,
            refund_currency=self.afn, entitlement_amount="100",
            rate="65", reason="Partial AFN refund",
            document_number="P11-RF-REV", idempotency_key="p11-rf-rev",
        )
        cross = refund.cross_currency_refund
        with self.assertRaises(JournalValidationError):
            reverse_journal(cross.cash_journal, "Must use aggregate", None)
        reverse_refund(refund, reason="Refund correction")
        reversal = reverse_sales_return(
            returned, reversal_date=self.day, reason="Return correction",
            document_number="P11-SRV-1", idempotency_key="p11-srv-1",
        )
        returned.refresh_from_db()
        self.assertEqual(returned.status, SalesReturnStatus.REVERSED)
        self.assertEqual(reversal.sales_return_id, returned.pk)
        self.assertEqual(stock_for(self.product, self.warehouse), 10)
