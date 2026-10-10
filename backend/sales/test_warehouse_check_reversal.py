from datetime import date

from django.test import TestCase

from accounting.coa import seed_chart_of_accounts
from accounting.models import JournalStatus
from categories.services import create_category
from currencies.models import Currency
from inventory.services import assign_warehouse_account, receive_stock
from inventory.stock import stock_for
from parties.services import create_party
from products.services import create_product
from sales.models import PaymentMode, SalesChannel
from sales.services import (
    SalesValidationError,
    cancel_warehouse_check,
    create_sale,
    finalize_sale,
    finalize_warehouse_check,
    prepare_warehouse_check,
    remaining_quantity,
)
from uom.services import create_uom
from warehouses.services import create_warehouse


class WarehouseCheckReversalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        seed_chart_of_accounts()

    def setUp(self):
        category = create_category(name="WC Reversal Category")
        unit = create_uom(name="WC Reversal Unit")
        self.product = create_product(
            code="WC-REV-1", name="WC Reversal Product",
            name_fa="محصول آزمایشی لغو حواله",
            category=category, primary_uom=unit,
        )
        self.unit = unit
        self.customer = create_party(name="WC Reversal Customer", is_customer=True)
        self.warehouse = create_warehouse(name="WC Reversal Warehouse")
        assign_warehouse_account(warehouse=self.warehouse, account="1410")

    def _finalized_check(self, number):
        sale = create_sale(
            customer=self.customer, sale_date=date(2026, 1, 10),
            currency=self.afn, channel=SalesChannel.WHOLESALE,
            payment_mode=PaymentMode.CREDIT,
            lines=[{
                "product": self.product, "unit": self.unit,
                "quantity": 5, "unit_price": "10",
            }],
            document_number=f"SI-{number}",
        )
        finalize_sale(sale=sale)
        receive_stock(
            product=self.product, warehouse=self.warehouse, quantity=5,
            unit_cost="4", currency=self.afn, movement_date=date(2026, 1, 10),
            reference=f"RCPT-{number}",
        )
        check = prepare_warehouse_check(
            sale_line=sale.lines.get(), warehouse=self.warehouse,
            quantity=5, number=number,
        )
        check = finalize_warehouse_check(check=check)
        return sale, check

    def test_pre_delivery_cancel_compensates_custody_stock_and_cogs_idempotently(self):
        sale, check = self._finalized_check("WC-REV-CANCEL")
        self.assertEqual(stock_for(self.product, self.warehouse), 0)
        original_cogs = check.cogs_journal

        reversal = cancel_warehouse_check(
            check=check, reversal_date=date(2026, 1, 11),
            reason="Goods had not physically left the warehouse",
            idempotency_key="wc-reversal-test-key",
            confirm_not_delivered=True,
        )

        self.assertEqual(stock_for(self.product, self.warehouse), 5)
        self.assertEqual(reversal.inventory_movement.quantity, 5)
        self.assertEqual(original_cogs.status, JournalStatus.REVERSED)
        self.assertEqual(remaining_quantity(sale.lines.get()), 5)
        self.assertEqual(
            cancel_warehouse_check(
                check=check, reversal_date=date(2026, 1, 11),
                reason="Goods had not physically left the warehouse",
                idempotency_key="wc-reversal-test-key",
                confirm_not_delivered=True,
            ).pk,
            reversal.pk,
        )

    def test_pre_delivery_cancel_requires_explicit_confirmation(self):
        _, check = self._finalized_check("WC-REV-CONFIRM")
        with self.assertRaises(SalesValidationError):
            cancel_warehouse_check(
                check=check, reversal_date=date(2026, 1, 11),
                reason="No physical delivery",
                idempotency_key="wc-reversal-confirm-key",
            )
        self.assertEqual(stock_for(self.product, self.warehouse), 0)
