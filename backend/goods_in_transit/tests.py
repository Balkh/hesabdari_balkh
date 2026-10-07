from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounting.coa import seed_chart_of_accounts
from accounting.models import JournalEntry
from categories.services import create_category
from currencies.models import Currency
from inventory.models import StockMovement, WarehouseInventoryAccount
from inventory.stock import stock_for
from parties.services import create_party
from products.services import create_product
from uom.services import create_uom
from warehouses.services import create_warehouse

from purchases.models import PurchaseDeliveryMode
from purchases.services import create_purchase, post_purchase
from sales.models import PaymentMode, SalesChannel, SaleStatus, TransitSaleAllocation
from sales.services import SalesValidationError, create_sale, finalize_sale

from .models import GoodsInTransitLot, TransitCustomerCustody, TransitDestinationTransfer, TransitLotStatus, TransitReceipt
from .services import TransitValidationError, receive_transit, transfer_transit_destination


class GoodsInTransitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")
        cls.user = get_user_model().objects.create_user("transit-user", password="x")

    def setUp(self):
        category = create_category(name="Transit Category", user=self.user)
        uom = create_uom(name="Transit Unit", user=self.user)
        self.product = create_product(
            code="TR-1", name="Transit Oil", name_fa="روغن در مسیر",
            category=category, primary_uom=uom, user=self.user,
        )
        self.supplier = create_party(name="Transit Supplier", is_supplier=True, user=self.user)
        self.customer = create_party(name="Transit Customer", is_customer=True, user=self.user)
        self.warehouse = create_warehouse(name="Transit Destination", user=self.user)
        WarehouseInventoryAccount.objects.create(
            warehouse=self.warehouse,
            account_id=self._account_id("1410"),
        )
        self.day = date(2026, 2, 1)

    def _account_id(self, code):
        from accounting.models import Account
        return Account.objects.get(code=code).pk

    def _purchase(self, **kwargs):
        params = dict(
            supplier=self.supplier,
            purchase_date=self.day,
            currency=self.usd,
            warehouse=self.warehouse,
            lines=[{"product": self.product, "quantity": 100, "unit_price": "100"}],
            rate="70",
            rate_date=self.day,
            delivery_mode=PurchaseDeliveryMode.IN_TRANSIT,
            user=self.user,
        )
        params.update(kwargs)
        return create_purchase(**params)

    def test_owned_purchase_creates_transit_not_warehouse_stock(self):
        purchase = self._purchase(document_number="PI-TRANSIT-001")
        post_purchase(purchase=purchase, user=self.user)

        line = purchase.lines.get()
        lot = GoodsInTransitLot.objects.get(purchase_line=line)

        self.assertEqual(lot.original_quantity, 100)
        self.assertEqual(lot.remaining_quantity, 100)
        self.assertEqual(lot.unit_cost, Decimal("100.0000"))
        self.assertEqual(lot.rate, Decimal("70.0000"))
        self.assertEqual(lot.status, TransitLotStatus.OPEN)
        self.assertEqual(stock_for(self.product, self.warehouse), 0)

        purchase_journal = JournalEntry.objects.get(
            source_type="PURCHASE", source_id=purchase.document_number
        )
        self.assertEqual(
            purchase_journal.lines.get(account__code="1430").debit,
            Decimal("10000.00"),
        )
        self.assertEqual(
            purchase_journal.lines.get(account__code="2110").credit,
            Decimal("10000.00"),
        )
        self.assertFalse(
            StockMovement.objects.filter(
                reference=f"{purchase.document_number}:LINE:{line.pk}"
            ).exists()
        )

    def test_partial_receipt_moves_only_received_quantity_to_warehouse(self):
        purchase = self._purchase(document_number="PI-TRANSIT-002")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())

        receipt = receive_transit(
            lot=lot, quantity=60, receipt_date=date(2026, 2, 5),
            user=self.user, idempotency_key="transit-receipt-002",
        )

        lot.refresh_from_db()
        self.assertEqual(receipt.quantity, 60)
        self.assertEqual(lot.remaining_quantity, 40)
        self.assertEqual(lot.status, TransitLotStatus.OPEN)
        self.assertEqual(stock_for(self.product, self.warehouse), 60)

        movement = receipt.stock_movement
        self.assertEqual(movement.quantity, 60)
        self.assertEqual(movement.unit_cost, Decimal("100.0000"))
        self.assertEqual(movement.unit_cost_afn, Decimal("7000.0000"))

        journal = receipt.journal_entry
        self.assertEqual(journal.lines.get(account__code="1410").debit, Decimal("6000.00"))
        self.assertEqual(journal.lines.get(account__code="1430").credit, Decimal("6000.00"))

    def test_multiple_receipts_close_exactly_at_zero(self):
        purchase = self._purchase(document_number="PI-TRANSIT-003")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())

        receive_transit(
            lot=lot, quantity=30, receipt_date=date(2026, 2, 5),
            user=self.user, idempotency_key="transit-receipt-003-a",
        )
        receive_transit(
            lot=lot, quantity=20, receipt_date=date(2026, 2, 6),
            user=self.user, idempotency_key="transit-receipt-003-b",
        )
        receive_transit(
            lot=lot, quantity=50, receipt_date=date(2026, 2, 7),
            user=self.user, idempotency_key="transit-receipt-003-c",
        )

        lot.refresh_from_db()
        self.assertEqual(lot.remaining_quantity, 0)
        self.assertEqual(lot.status, TransitLotStatus.CLOSED)
        self.assertEqual(stock_for(self.product, self.warehouse), 100)

    def test_receipt_cannot_exceed_remaining_transit(self):
        purchase = self._purchase(document_number="PI-TRANSIT-004")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())

        with self.assertRaises(TransitValidationError):
            receive_transit(
                lot=lot, quantity=101, receipt_date=date(2026, 2, 5),
                user=self.user, idempotency_key="transit-receipt-004",
            )

        lot.refresh_from_db()
        self.assertEqual(lot.remaining_quantity, 100)
        self.assertEqual(stock_for(self.product, self.warehouse), 0)

    def test_receipt_idempotency_has_one_business_effect(self):
        purchase = self._purchase(document_number="PI-TRANSIT-005")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())

        first = receive_transit(
            lot=lot, quantity=25, receipt_date=date(2026, 2, 5),
            user=self.user, idempotency_key="transit-receipt-005",
        )
        second = receive_transit(
            lot=lot, quantity=25, receipt_date=date(2026, 2, 5),
            user=self.user, idempotency_key="transit-receipt-005",
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(TransitReceipt.objects.filter(lot=lot).count(), 1)
        self.assertEqual(stock_for(self.product, self.warehouse), 25)

    def test_sale_from_transit_consumes_owned_transit_and_posts_cogs(self):
        purchase = self._purchase(document_number="PI-TRANSIT-SALE-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())

        sale = create_sale(
            customer=self.customer,
            sale_date=date(2026, 2, 10),
            currency=self.usd,
            channel=SalesChannel.WHOLESALE,
            payment_mode=PaymentMode.CREDIT,
            lines=[{
                "product": self.product,
                "unit": self.product.primary_uom,
                "quantity": 20,
                "unit_price": "120",
                "transit_lot": lot,
            }],
            user=self.user,
            document_number="SI-TRANSIT-001",
        )
        finalize_sale(sale=sale, user=self.user)

        lot.refresh_from_db()
        line = sale.lines.get()
        allocation = TransitSaleAllocation.objects.get(sale_line=line)

        self.assertEqual(sale.status, SaleStatus.FINALIZED)
        self.assertEqual(lot.remaining_quantity, 80)
        self.assertEqual(allocation.quantity, 20)
        self.assertEqual(allocation.unit_cost, Decimal("100.0000"))
        self.assertEqual(
            allocation.cogs_journal.lines.get(account__code="5100").debit,
            Decimal("2000.00"),
        )
        self.assertEqual(
            allocation.cogs_journal.lines.get(account__code="1430").credit,
            Decimal("2000.00"),
        )
        self.assertEqual(stock_for(self.product, self.warehouse), 0)

    def test_sale_cannot_consume_more_transit_than_available(self):
        purchase = self._purchase(document_number="PI-TRANSIT-SALE-002")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())

        sale = create_sale(
            customer=self.customer,
            sale_date=date(2026, 2, 10),
            currency=self.usd,
            channel=SalesChannel.WHOLESALE,
            payment_mode=PaymentMode.CREDIT,
            lines=[{
                "product": self.product,
                "unit": self.product.primary_uom,
                "quantity": 101,
                "unit_price": "120",
                "transit_lot": lot,
            }],
            user=self.user,
            document_number="SI-TRANSIT-002",
        )
        with self.assertRaises(SalesValidationError):
            finalize_sale(sale=sale, user=self.user)

        lot.refresh_from_db()
        self.assertEqual(lot.remaining_quantity, 100)
        self.assertEqual(sale.status, SaleStatus.DRAFT)


    def test_sale_then_full_physical_receipt_creates_customer_custody_without_company_stock(self):
        purchase = self._purchase(document_number="PI-TRANSIT-CUSTODY-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        sale = create_sale(customer=self.customer, sale_date=date(2026, 2, 10), currency=self.usd, channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT, lines=[{"product": self.product, "unit": self.product.primary_uom, "quantity": 20, "unit_price": "120", "transit_lot": lot}], user=self.user, document_number="SI-TRANSIT-CUSTODY-001")
        finalize_sale(sale=sale, user=self.user)
        receipt = receive_transit(lot=lot, quantity=100, receipt_date=date(2026, 2, 12), user=self.user, idempotency_key="transit-custody-001")
        lot.refresh_from_db()
        self.assertEqual(receipt.company_quantity, 80)
        self.assertEqual(receipt.customer_custody_quantity, 20)
        self.assertEqual(lot.remaining_quantity, 0)
        self.assertEqual(stock_for(self.product, self.warehouse), 80)
        custody = TransitCustomerCustody.objects.get(receipt=receipt)
        self.assertEqual(custody.quantity, 20)
        self.assertEqual(custody.customer_id, self.customer.pk)
        self.assertEqual(custody.warehouse_id, self.warehouse.pk)

    def test_transit_destination_transfer_preserves_owned_quantity_and_changes_destination(self):
        purchase = self._purchase(document_number="PI-TRANSIT-MOVE-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        second = create_warehouse(name="Transit Destination 2", user=self.user)
        WarehouseInventoryAccount.objects.create(warehouse=second, account_id=self._account_id("1420"))
        row = transfer_transit_destination(lot=lot, warehouse=second, quantity=40, transfer_date=date(2026, 2, 3), user=self.user, idempotency_key="transit-move-001")
        lot.refresh_from_db()
        self.assertEqual(row.quantity, 40)
        self.assertEqual(row.from_warehouse_id, self.warehouse.pk)
        self.assertEqual(row.to_warehouse_id, second.pk)
        self.assertEqual(lot.destination_warehouse_id, second.pk)
        self.assertEqual(lot.remaining_quantity, 100)
