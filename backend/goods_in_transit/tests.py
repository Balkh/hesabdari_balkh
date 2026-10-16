from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from unittest.mock import patch

from accounting.coa import seed_chart_of_accounts
from accounting.models import JournalEntry, PostedImmutabilityError
from customer_custody.models import CustomerCustodyEvent, CustodyEventType
from customer_custody.services import custody_balance
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
from purchases.landed_cost_posting import _good_quantity_for_line, LandedCostPostingError
from sales.models import PaymentMode, SalesChannel, SaleStatus, TransitSaleAllocation
from sales.services import (
    SalesValidationError, create_sale, finalize_sale,
    finalize_warehouse_check, prepare_warehouse_check,
)
from sales.returns_services import create_sales_return, reverse_sales_return

from .models import GoodsInTransitLot, TransitCustomerCustody, TransitDestinationTransfer, TransitLotStatus, TransitReceipt, TransitLossEvent
from .services import TransitValidationError, receive_transit, transfer_transit_destination, record_transit_loss


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
        sale = finalize_sale(sale=sale, user=self.user)

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

    def test_fully_sold_transit_lot_stays_open_until_customer_goods_arrive(self):
        purchase = self._purchase(document_number="PI-TR-FULL-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        sale = create_sale(
            customer=self.customer, sale_date=date(2026, 2, 10),
            currency=self.usd, channel=SalesChannel.WHOLESALE,
            payment_mode=PaymentMode.CREDIT,
            lines=[{
                "product": self.product, "unit": self.product.primary_uom,
                "quantity": 100, "unit_price": "120", "transit_lot": lot,
            }],
            user=self.user, document_number="SI-TR-FULL-001",
        )

        finalize_sale(sale=sale, user=self.user)
        lot.refresh_from_db()
        self.assertEqual(lot.remaining_quantity, 0)
        self.assertEqual(lot.status, TransitLotStatus.OPEN)

        receipt = receive_transit(
            lot=lot, quantity=100, receipt_date=date(2026, 2, 12),
            user=self.user, idempotency_key="transit-full-sale-receipt-001",
        )
        lot.refresh_from_db()
        entitlement = sale.lines.get().customer_ownership_entitlement
        self.assertEqual(receipt.company_quantity, 0)
        self.assertEqual(receipt.customer_custody_quantity, 100)
        self.assertIsNone(receipt.stock_movement_id)
        self.assertIsNone(receipt.journal_entry_id)
        self.assertEqual(lot.status, TransitLotStatus.CLOSED)
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.warehouse), 100)
        self.assertEqual(stock_for(self.product, self.warehouse), 0)
        self.assertEqual(
            JournalEntry.objects.filter(source_type="SALES_COGS_TRANSIT").count(), 1
        )
        self.assertEqual(
            JournalEntry.objects.filter(source_type="SALES_COGS").count(), 0
        )

    def test_fully_sold_transit_lot_supports_partial_receipts_until_closed(self):
        purchase = self._purchase(document_number="PI-TR-FULL-PART-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        sale = create_sale(
            customer=self.customer, sale_date=date(2026, 2, 10),
            currency=self.usd, channel=SalesChannel.WHOLESALE,
            payment_mode=PaymentMode.CREDIT,
            lines=[{
                "product": self.product, "unit": self.product.primary_uom,
                "quantity": 100, "unit_price": "120", "transit_lot": lot,
            }],
            user=self.user, document_number="SI-TR-FULL-PART-001",
        )
        finalize_sale(sale=sale, user=self.user)

        first = receive_transit(
            lot=lot, quantity=60, receipt_date=date(2026, 2, 12),
            user=self.user, idempotency_key="transit-full-part-receipt-001a",
        )
        lot.refresh_from_db()
        self.assertEqual(first.company_quantity, 0)
        self.assertEqual(first.customer_custody_quantity, 60)
        self.assertEqual(lot.remaining_quantity, 0)
        self.assertEqual(lot.status, TransitLotStatus.OPEN)
        entitlement = sale.lines.get().customer_ownership_entitlement
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.warehouse), 60)
        self.assertEqual(stock_for(self.product, self.warehouse), 0)

        second = receive_transit(
            lot=lot, quantity=40, receipt_date=date(2026, 2, 13),
            user=self.user, idempotency_key="transit-full-part-receipt-001b",
        )
        lot.refresh_from_db()
        self.assertEqual(second.company_quantity, 0)
        self.assertEqual(second.customer_custody_quantity, 40)
        self.assertEqual(lot.status, TransitLotStatus.CLOSED)
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.warehouse), 100)
        self.assertEqual(stock_for(self.product, self.warehouse), 0)
        self.assertEqual(
            JournalEntry.objects.filter(source_type="SALES_COGS_TRANSIT").count(), 1
        )
        self.assertEqual(
            JournalEntry.objects.filter(source_type="SALES_COGS").count(), 0
        )

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
        entitlement = sale.lines.get().customer_ownership_entitlement
        custody = CustomerCustodyEvent.objects.get(
            entitlement=entitlement, event_type=CustodyEventType.PLACED
        )
        self.assertEqual(custody.quantity, 20)
        self.assertEqual(custody.customer_id, self.customer.pk)
        self.assertEqual(custody.warehouse_id, self.warehouse.pk)
        self.assertEqual(TransitCustomerCustody.objects.filter(receipt=receipt).count(), 0)

        check = prepare_warehouse_check(
            sale_line=sale.lines.get(), warehouse=self.warehouse,
            quantity=20, number="WC-TRANSIT-CUSTODY-001",
        )
        finalized_check = finalize_warehouse_check(check=check, user=self.user)
        self.assertEqual(finalized_check.status, "FINALIZED")
        self.assertIsNone(finalized_check.stock_movement_id)
        self.assertIsNone(finalized_check.cogs_journal_id)
        self.assertEqual(stock_for(self.product, self.warehouse), 80)
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.warehouse), 0)
        self.assertEqual(
            JournalEntry.objects.filter(source_type="SALES_COGS_TRANSIT").count(), 1
        )
        self.assertEqual(
            JournalEntry.objects.filter(source_type="SALES_COGS").count(), 0
        )


    def test_partial_receipts_keep_transit_open_until_sold_customer_goods_arrive(self):
        purchase = self._purchase(document_number="PI-TR-CUST-PART-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        sale = create_sale(
            customer=self.customer, sale_date=date(2026, 2, 10),
            currency=self.usd, channel=SalesChannel.WHOLESALE,
            payment_mode=PaymentMode.CREDIT,
            lines=[{
                "product": self.product, "unit": self.product.primary_uom,
                "quantity": 20, "unit_price": "120", "transit_lot": lot,
            }],
            user=self.user, document_number="SI-TR-CUST-PART-001",
        )
        finalize_sale(sale=sale, user=self.user)

        first = receive_transit(
            lot=lot, quantity=90, receipt_date=date(2026, 2, 12),
            user=self.user, idempotency_key="transit-custody-partial-001a",
        )
        lot.refresh_from_db()
        self.assertEqual(first.company_quantity, 80)
        self.assertEqual(first.customer_custody_quantity, 10)
        self.assertEqual(lot.remaining_quantity, 0)
        self.assertEqual(lot.status, TransitLotStatus.OPEN)

        second = receive_transit(
            lot=lot, quantity=10, receipt_date=date(2026, 2, 13),
            user=self.user, idempotency_key="transit-custody-partial-001b",
        )
        lot.refresh_from_db()
        self.assertEqual(second.company_quantity, 0)
        self.assertEqual(second.customer_custody_quantity, 10)
        self.assertIsNone(second.stock_movement_id)
        self.assertIsNone(second.journal_entry_id)
        self.assertEqual(lot.status, TransitLotStatus.CLOSED)
        entitlement = sale.lines.get().customer_ownership_entitlement
        self.assertEqual(
            CustomerCustodyEvent.objects.filter(
                entitlement=entitlement, event_type=CustodyEventType.PLACED
            ).count(), 2
        )
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.warehouse), 20)
        self.assertEqual(stock_for(self.product, self.warehouse), 80)


    def test_released_transit_custody_does_not_allow_duplicate_physical_receipt(self):
        purchase = self._purchase(document_number="PI-TR-RELEASE-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        sale = create_sale(
            customer=self.customer, sale_date=date(2026, 2, 10),
            currency=self.usd, channel=SalesChannel.WHOLESALE,
            payment_mode=PaymentMode.CREDIT,
            lines=[{
                "product": self.product, "unit": self.product.primary_uom,
                "quantity": 20, "unit_price": "120", "transit_lot": lot,
            }],
            user=self.user, document_number="SI-TR-RELEASE-001",
        )
        finalize_sale(sale=sale, user=self.user)

        first = receive_transit(
            lot=lot, quantity=90, receipt_date=date(2026, 2, 12),
            user=self.user, idempotency_key="transit-release-receipt-001a",
        )
        self.assertEqual(first.company_quantity, 80)
        self.assertEqual(first.customer_custody_quantity, 10)
        entitlement = sale.lines.get().customer_ownership_entitlement

        check = prepare_warehouse_check(
            sale_line=sale.lines.get(), warehouse=self.warehouse,
            quantity=10, number="WC-TR-RELEASE-001",
        )
        finalize_warehouse_check(check=check, user=self.user)
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.warehouse), 0)

        # Released custody remains physically received; it must not be counted
        # as unreceived Transit quantity again.
        with self.assertRaises(TransitValidationError):
            receive_transit(
                lot=lot, quantity=20, receipt_date=date(2026, 2, 13),
                user=self.user, idempotency_key="transit-release-overreceipt-001",
            )

        second = receive_transit(
            lot=lot, quantity=10, receipt_date=date(2026, 2, 13),
            user=self.user, idempotency_key="transit-release-receipt-001b",
        )
        lot.refresh_from_db()
        self.assertEqual(second.company_quantity, 0)
        self.assertEqual(second.customer_custody_quantity, 10)
        self.assertEqual(lot.remaining_quantity, 0)
        self.assertEqual(lot.status, TransitLotStatus.CLOSED)
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.warehouse), 10)
        self.assertEqual(stock_for(self.product, self.warehouse), 80)

    def test_legacy_custody_bridge_is_not_double_counted_as_transit_receipt(self):
        purchase = self._purchase(document_number="PI-TR-LEGACY-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        sale = create_sale(
            customer=self.customer, sale_date=date(2026, 2, 10),
            currency=self.usd, channel=SalesChannel.WHOLESALE,
            payment_mode=PaymentMode.CREDIT,
            lines=[{
                "product": self.product, "unit": self.product.primary_uom,
                "quantity": 20, "unit_price": "120", "transit_lot": lot,
            }],
            user=self.user, document_number="SI-TR-LEGACY-001",
        )
        finalize_sale(sale=sale, user=self.user)

        # Simulate an older partial receipt recorded in the legacy custody table.
        receipt = TransitReceipt.objects.create(
            lot=lot, warehouse=self.warehouse, quantity=90,
            company_quantity=80, customer_custody_quantity=10,
            receipt_date=date(2026, 2, 12),
            idempotency_key="legacy-transit-receipt-001", created_by=self.user,
        )
        TransitCustomerCustody.objects.create(
            receipt=receipt, sale_line=sale.lines.get(), customer=self.customer,
            warehouse=self.warehouse, quantity=10, receipt_date=date(2026, 2, 12),
        )
        lot.remaining_quantity = 0
        lot.status = TransitLotStatus.OPEN
        lot.save(allow_state_transition=True, update_fields={"remaining_quantity", "status"})

        check = prepare_warehouse_check(
            sale_line=sale.lines.get(), warehouse=self.warehouse,
            quantity=5, number="WC-TR-LEGACY-001",
        )
        finalize_warehouse_check(check=check, user=self.user)
        entitlement = sale.lines.get().customer_ownership_entitlement
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.warehouse), 5)

        # Ten of the twenty sold units have physically arrived. Releasing five
        # must not make the ten already received count twice or hide the other ten.
        second = receive_transit(
            lot=lot, quantity=10, receipt_date=date(2026, 2, 13),
            user=self.user, idempotency_key="legacy-transit-receipt-002",
        )
        lot.refresh_from_db()
        self.assertEqual(second.company_quantity, 0)
        self.assertEqual(second.customer_custody_quantity, 10)
        self.assertEqual(lot.status, TransitLotStatus.CLOSED)
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.warehouse), 15)

    def test_transit_destination_transfer_rejects_partial_quantity_for_single_destination_lot(self):
        purchase = self._purchase(document_number="PI-TRANSIT-MOVE-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        second = create_warehouse(name="Transit Destination 2", user=self.user)
        WarehouseInventoryAccount.objects.create(warehouse=second, account_id=self._account_id("1420"))

        with self.assertRaisesRegex(TransitValidationError, "full remaining Transit quantity"):
            transfer_transit_destination(
                lot=lot, warehouse=second, quantity=40,
                transfer_date=date(2026, 2, 3), user=self.user,
                idempotency_key="transit-move-partial-001",
            )
        lot.refresh_from_db()
        self.assertEqual(lot.destination_warehouse_id, self.warehouse.pk)
        self.assertEqual(lot.remaining_quantity, 100)
        self.assertEqual(TransitDestinationTransfer.objects.filter(lot=lot).count(), 0)

        row = transfer_transit_destination(
            lot=lot, warehouse=second, quantity=100,
            transfer_date=date(2026, 2, 3), user=self.user,
            idempotency_key="transit-move-full-001",
        )
        lot.refresh_from_db()
        self.assertEqual(row.quantity, 100)
        self.assertEqual(row.from_warehouse_id, self.warehouse.pk)
        self.assertEqual(row.to_warehouse_id, second.pk)
        self.assertEqual(lot.destination_warehouse_id, second.pk)
        self.assertEqual(lot.remaining_quantity, 100)

    def test_transit_sale_return_uses_historical_cost_and_reverses_without_fake_issue(self):
        purchase = self._purchase(document_number="PI-TR-RETURN-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        sale = create_sale(
            customer=self.customer, sale_date=date(2026, 2, 10),
            currency=self.usd, channel=SalesChannel.WHOLESALE,
            payment_mode=PaymentMode.CREDIT,
            lines=[{
                "product": self.product, "unit": self.product.primary_uom,
                "quantity": 20, "unit_price": "120", "transit_lot": lot,
            }],
            user=self.user, document_number="SI-TR-RETURN-001",
        )
        finalize_sale(sale=sale, user=self.user)
        receive_transit(
            lot=lot, quantity=100, receipt_date=date(2026, 2, 12),
            user=self.user, idempotency_key="transit-return-receipt-001",
        )
        line = sale.lines.get()
        check = prepare_warehouse_check(
            sale_line=line, warehouse=self.warehouse, quantity=20,
            number="WC-TR-RETURN-001",
        )
        finalize_warehouse_check(check=check, user=self.user)
        self.assertEqual(stock_for(self.product, self.warehouse), 80)

        returned = create_sales_return(
            sale_line=line, warehouse=self.warehouse, quantity=2,
            return_date=date(2026, 2, 13), reason="Transit customer return",
            document_number="SR-TR-RETURN-001",
            idempotency_key="sales-return-transit-001", user=self.user,
        )
        self.assertIsNone(returned.inventory_return_id)
        self.assertEqual(returned.return_movement.movement_type, "SALES_RETURN")
        self.assertEqual(returned.return_movement.quantity, 2)
        self.assertEqual(returned.return_movement.unit_cost_afn, Decimal("7000.0000"))
        self.assertEqual(stock_for(self.product, self.warehouse), 82)
        self.assertEqual(
            returned.cogs_journal.lines.get(account__code="1410").debit,
            Decimal("14000.00"),
        )
        self.assertEqual(
            returned.cogs_journal.lines.get(account__code="5100").credit,
            Decimal("14000.00"),
        )
        self.assertEqual(
            JournalEntry.objects.filter(source_type="SALES_COGS_TRANSIT").count(), 1
        )
        self.assertEqual(
            StockMovement.objects.filter(
                product=self.product, movement_type="SALES_ISSUE"
            ).count(), 0
        )

        reversal = reverse_sales_return(
            returned, reversal_date=date(2026, 2, 14),
            reason="Reverse transit return", document_number="SRV-TR-RETURN-001",
            idempotency_key="sales-return-transit-reversal-001", user=self.user,
        )
        self.assertEqual(reversal.inventory_movement.movement_type, "SALES_ISSUE")
        self.assertEqual(reversal.inventory_movement.quantity, -2)
        self.assertEqual(stock_for(self.product, self.warehouse), 80)


    def test_transit_loss_evidence_is_immutable(self):
        purchase = self._purchase(document_number="PI-TRANSIT-LOSS-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        loss = TransitLossEvent.objects.create(
            lot=lot, quantity=2, loss_date=date(2026, 2, 2),
            reason="Confirmed transport loss",
            idempotency_key="transit-loss-evidence-001", created_by=self.user,
        )
        self.assertEqual(loss.lot_id, lot.pk)
        self.assertEqual(loss.quantity, 2)
        with self.assertRaises(PostedImmutabilityError):
            loss.save()
        with self.assertRaises(PostedImmutabilityError):
            loss.delete()

    def test_confirmed_loss_blocks_transit_sale_and_receipt_until_revaluation(self):
        purchase = self._purchase(document_number="PI-TRANSIT-LOSS-BLOCK-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        sale = create_sale(
            customer=self.customer, sale_date=date(2026, 2, 3),
            currency=self.usd, channel=SalesChannel.WHOLESALE,
            payment_mode=PaymentMode.CREDIT,
            lines=[{
                "product": self.product, "unit": self.product.primary_uom,
                "quantity": 5, "unit_price": "120", "transit_lot": lot,
            }],
            user=self.user, document_number="SI-TRANSIT-LOSS-BLOCK-001",
        )
        TransitLossEvent.objects.create(
            lot=lot, quantity=2, loss_date=date(2026, 2, 2),
            reason="Confirmed loss awaiting valuation replay",
            idempotency_key="transit-loss-block-001", created_by=self.user,
        )

        with self.assertRaisesRegex(SalesValidationError, "purchase-wide loss valuation replay"):
            finalize_sale(sale=sale, user=self.user)
        with self.assertRaisesRegex(TransitValidationError, "purchase-wide loss valuation replay"):
            receive_transit(
                lot=lot, quantity=10, receipt_date=date(2026, 2, 4),
                user=self.user, idempotency_key="transit-loss-block-receipt-001",
            )

        sale.refresh_from_db()
        lot.refresh_from_db()
        self.assertEqual(sale.status, SaleStatus.DRAFT)
        self.assertEqual(lot.remaining_quantity, lot.original_quantity)
        self.assertEqual(TransitSaleAllocation.objects.filter(sale_line__sale=sale).count(), 0)
        self.assertEqual(TransitReceipt.objects.filter(lot=lot).count(), 0)

    def test_landed_cost_allocation_uses_confirmed_good_transit_quantity(self):
        purchase = self._purchase(document_number="PI-TRANSIT-LOSS-COST-001")
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        lot = GoodsInTransitLot.objects.get(purchase_line=line)
        self.assertEqual(_good_quantity_for_line(line, lot=lot), 100)

        TransitLossEvent.objects.create(
            lot=lot, quantity=2, loss_date=date(2026, 2, 2),
            reason="Confirmed transport loss",
            idempotency_key="transit-loss-cost-001", created_by=self.user,
        )
        with self.assertRaisesRegex(LandedCostPostingError, "purchase-wide loss valuation replay"):
            _good_quantity_for_line(line, lot=lot)

    def test_transit_loss_rejects_loss_of_entire_purchase_line(self):
        purchase = self._purchase(document_number="PI-TRANSIT-LOSS-COST-002")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        with self.assertRaisesRegex(ValidationError, "leave at least one good unit"):
            TransitLossEvent.objects.create(
                lot=lot, quantity=100, loss_date=date(2026, 2, 2),
                reason="Entire lot confirmed lost",
                idempotency_key="transit-loss-cost-002", created_by=self.user,
            )


    def test_transit_loss_guard_is_scoped_to_its_own_purchase_line(self):
        first_purchase = self._purchase(document_number="PI-TRANSIT-LOSS-SCOPE-001")
        second_purchase = self._purchase(document_number="PI-TRANSIT-LOSS-SCOPE-002")
        post_purchase(purchase=first_purchase, user=self.user)
        post_purchase(purchase=second_purchase, user=self.user)

        first_line = first_purchase.lines.get()
        second_line = second_purchase.lines.get()
        first_lot = GoodsInTransitLot.objects.get(purchase_line=first_line)
        second_lot = GoodsInTransitLot.objects.get(purchase_line=second_line)
        self.assertEqual(first_lot.product_id, second_lot.product_id)
        self.assertNotEqual(first_lot.purchase_line_id, second_lot.purchase_line_id)

        TransitLossEvent.objects.create(
            lot=first_lot, quantity=2, loss_date=date(2026, 2, 2),
            reason="Loss belongs only to first purchase",
            idempotency_key="transit-loss-scope-001", created_by=self.user,
        )

        with self.assertRaisesRegex(LandedCostPostingError, "purchase-wide loss valuation replay"):
            _good_quantity_for_line(first_line, lot=first_lot)
        # A loss on one purchase must not contaminate another purchase line's
        # good-quantity denominator, even for the same product.
        self.assertEqual(_good_quantity_for_line(second_line, lot=second_lot), second_line.quantity)


    def test_record_transit_loss_is_idempotent_and_reconciles_cumulative_quantity(self):
        purchase = self._purchase(document_number="PI-TRANSIT-LOSS-SERVICE-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())

        first = record_transit_loss(
            lot=lot, quantity=30, loss_date=date(2026, 2, 2),
            reason="First confirmed shortage", idempotency_key="loss-service-001",
            user=self.user,
        )
        # A retry must return the immutable event even if its original
        # posting period has since closed; no new posting occurs on retry.
        with patch(
            "goods_in_transit.services.assert_posting_date_open",
            side_effect=TransitValidationError("period is closed"),
        ):
            retry = record_transit_loss(
                lot=lot, quantity=30, loss_date=date(2026, 2, 2),
                reason="First confirmed shortage", idempotency_key="loss-service-001",
                user=self.user,
            )
        self.assertEqual(first.pk, retry.pk)
        self.assertEqual(TransitLossEvent.objects.filter(lot=lot).count(), 1)

        record_transit_loss(
            lot=lot, quantity=69, loss_date=date(2026, 2, 3),
            reason="Second confirmed shortage", idempotency_key="loss-service-002",
            user=self.user,
        )
        with self.assertRaisesRegex(TransitValidationError, "leave at least one good unit"):
            record_transit_loss(
                lot=lot, quantity=1, loss_date=date(2026, 2, 4),
                reason="Excess shortage", idempotency_key="loss-service-003",
                user=self.user,
            )
        self.assertEqual(
            sum(TransitLossEvent.objects.filter(lot=lot).values_list("quantity", flat=True)),
            lot.original_quantity - 1,
        )

    def test_record_transit_loss_rejects_conflicting_idempotency_and_pre_ownership_date(self):
        purchase = self._purchase(document_number="PI-TRANSIT-LOSS-SERVICE-002")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        record_transit_loss(
            lot=lot, quantity=2, loss_date=date(2026, 2, 2),
            reason="Confirmed shortage", idempotency_key="loss-service-conflict-001",
            user=self.user,
        )
        with self.assertRaisesRegex(TransitValidationError, "different loss evidence"):
            record_transit_loss(
                lot=lot, quantity=3, loss_date=date(2026, 2, 2),
                reason="Confirmed shortage", idempotency_key="loss-service-conflict-001",
                user=self.user,
            )
        with self.assertRaisesRegex(TransitValidationError, "cannot precede company ownership"):
            record_transit_loss(
                lot=lot, quantity=1, loss_date=date(2026, 1, 31),
                reason="Invalid historical date", idempotency_key="loss-service-date-001",
                user=self.user,
            )


    def test_transit_loss_model_cannot_bypass_lot_quantity_invariants(self):
        purchase = self._purchase(document_number="PI-TRANSIT-LOSS-MODEL-001")
        post_purchase(purchase=purchase, user=self.user)
        lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        TransitLossEvent.objects.create(
            lot=lot, quantity=60, loss_date=date(2026, 2, 2),
            reason="First part of confirmed loss", idempotency_key="loss-model-001",
            created_by=self.user,
        )
        with self.assertRaisesRegex(ValidationError, "Cumulative transit loss"):
            TransitLossEvent.objects.create(
                lot=lot, quantity=41, loss_date=date(2026, 2, 3),
                reason="Would exceed purchased quantity", idempotency_key="loss-model-002",
                created_by=self.user,
            )
        with self.assertRaisesRegex(ValidationError, "cannot precede company ownership"):
            TransitLossEvent.objects.create(
                lot=lot, quantity=1, loss_date=date(2026, 1, 31),
                reason="Before ownership", idempotency_key="loss-model-003",
                created_by=self.user,
            )
