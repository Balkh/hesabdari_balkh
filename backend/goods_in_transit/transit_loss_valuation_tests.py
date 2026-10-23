"""Phase 11 transit-loss valuation replay tests.

All amounts are AFN (base currency) so account balances can be asserted
exactly. Purchase: 100 units x 100 AFN = 10,000 AFN into 1430.
A confirmed loss of 2 leaves G=98 good units, final unit 102.0408 AFN,
delta +2.0408 AFN/unit; the lost units carry 200.00 AFN out of 1430.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounting.balances import account_balance
from accounting.coa import seed_chart_of_accounts
from accounting.models import Account, JournalEntry
from categories.services import create_category
from currencies.models import Currency
from inventory.models import WarehouseInventoryAccount
from inventory.stock import stock_for
from parties.services import create_party
from products.services import create_product
from uom.services import create_uom
from warehouses.services import create_warehouse

from purchases.landed_cost_posting import _good_quantity_for_line, post_landed_cost
from purchases.landed_cost_services import create_landed_cost_draft
from purchases.models import (
    LandedCostAllocationMethod, LandedCostDocument, PurchaseDeliveryMode,
)
from purchases.services import create_purchase, post_purchase
from sales.models import PaymentMode, SalesChannel
from sales.services import (
    create_sale, finalize_sale, finalize_warehouse_check, prepare_warehouse_check,
)

from .models import GoodsInTransitLot, TransitLossEvent, TransitLossValuationAdjustment
from .services import (TransitValidationError, receive_transit, record_transit_loss as record_transit_loss_service, complete_transit_purchase)


class TransitLossValuationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.user = get_user_model().objects.create_user("loss-val-user", password="x")

    def setUp(self):
        category = create_category(name="LossVal Category", user=self.user)
        uom = create_uom(name="LossVal Unit", user=self.user)
        self.product = create_product(
            code="LV-1", name="LossVal Oil", name_fa="روغن",
            category=category, primary_uom=uom, user=self.user,
        )
        self.uom = uom
        self.supplier = create_party(name="LossVal Supplier", is_supplier=True, user=self.user)
        self.customer = create_party(name="LossVal Customer", is_customer=True, user=self.user)
        self.warehouse = create_warehouse(name="LossVal Warehouse", user=self.user)
        WarehouseInventoryAccount.objects.create(
            warehouse=self.warehouse,
            account_id=Account.objects.get(code="1410").pk,
        )
        self.day = date(2026, 2, 1)

    # -- helpers ---------------------------------------------------------
    def _balance(self, code):
        return account_balance(Account.objects.get(code=code))["balance"]

    def _purchase(self, document_number, quantity=100, unit_price="100"):
        purchase = create_purchase(
            supplier=self.supplier, purchase_date=self.day, currency=self.afn,
            warehouse=self.warehouse,
            lines=[{"product": self.product, "quantity": quantity,
                    "unit_price": unit_price}],
            rate="1", rate_date=self.day,
            delivery_mode=PurchaseDeliveryMode.IN_TRANSIT,
            user=self.user, document_number=document_number,
        )
        post_purchase(purchase=purchase, user=self.user)
        return purchase

    def _lot(self, purchase):
        return GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())

    def _assert_journals_balanced(self):
        for entry in JournalEntry.objects.all():
            self.assertEqual(entry.total_debit, entry.total_credit, entry.number)
            self.assertGreater(entry.total_debit, Decimal("0"), entry.number)

    # -- scenarios -------------------------------------------------------
    def _record_loss_after_completion(self, *, lot, quantity, loss_date, reason, idempotency_key, user=None):
        complete_transit_purchase(
            purchase=lot.purchase, completion_date=loss_date,
            reason="All goods for this purchase invoice arrived; trip receipts consolidated.",
            idempotency_key=f"test-complete-{lot.purchase_id}", user=user or self.user,
        )
        return record_transit_loss_service(
            lot=lot, quantity=quantity, loss_date=loss_date, reason=reason,
            idempotency_key=idempotency_key, user=user or self.user,
        )

    def test_loss_is_blocked_until_whole_purchase_completion(self):
        purchase = self._purchase("PI-LV-COMPLETE-GATE")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2), user=self.user, idempotency_key="lv-complete-gate-r1")
        with self.assertRaises(TransitValidationError):
            record_transit_loss_service(lot=lot, quantity=2, loss_date=date(2026, 2, 4),
                reason="Confirmed final purchase-wide wastage", idempotency_key="lv-complete-gate-loss", user=self.user)
        completion = complete_transit_purchase(purchase=purchase, completion_date=date(2026, 2, 4),
            reason="All invoice goods arrived across the recorded trips.", idempotency_key="lv-complete-gate-complete", user=self.user)
        self.assertEqual(completion.purchase_id, purchase.pk)
        event = record_transit_loss_service(lot=lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="Confirmed final purchase-wide wastage", idempotency_key="lv-complete-gate-loss", user=self.user)
        self.assertEqual(event.valuation_status, "POSTED")
        self.assertEqual(event.good_quantity, 98)

    def test_loss_after_partial_receipts_revalues_on_hand_and_clears_1430(self):
        purchase = self._purchase("PI-LV-001")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=60, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lv1-r1")
        receive_transit(lot=lot, quantity=38, receipt_date=date(2026, 2, 3),
                        user=self.user, idempotency_key="lv1-r2")
        self.assertEqual(self._balance("1430"), Decimal("200.00"))
        self.assertEqual(self._balance("1410"), Decimal("9800.00"))

        event = self._record_loss_after_completion(
            lot=lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="Confirmed transport wastage", idempotency_key="lv1-loss",
            user=self.user,
        )

        self.assertEqual(event.valuation_status, "POSTED")
        self.assertEqual(event.good_quantity, 98)
        self.assertEqual(event.final_unit_cost_afn, Decimal("102.0408"))
        self.assertEqual(_good_quantity_for_line(purchase.lines.get(), lot=lot), 98)
        # Lost units' 200 AFN moved from 1430 onto the 98 surviving units.
        self.assertEqual(self._balance("1430"), Decimal("0.00"))
        self.assertEqual(self._balance("1410"), Decimal("10000.00"))
        self.assertEqual(stock_for(self.product, self.warehouse), 98)
        adjustments = TransitLossValuationAdjustment.objects.filter(loss_event=event)
        self.assertTrue(adjustments.exists())
        for row in adjustments:
            self.assertEqual(row.journal_entry.source_type,
                             "TRANSIT_LOSS_VALUATION_ADJUSTMENT")
        self._assert_journals_balanced()
        lot.refresh_from_db()
        self.assertEqual(lot.remaining_quantity, 0)

    def test_purchase_completion_blocks_while_sold_goods_remain_in_transit(self):
        purchase = self._purchase("PI-LV-002")
        lot = self._lot(purchase)
        sale = create_sale(
            customer=self.customer, sale_date=date(2026, 2, 2), currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
            lines=[{"product": self.product, "unit": self.uom, "quantity": 40,
                    "unit_price": "120", "transit_lot": lot}],
            user=self.user, document_number="SI-LV-002",
        )
        finalize_sale(sale=sale, user=self.user)
        receive_transit(lot=lot, quantity=58, receipt_date=date(2026, 2, 3),
                        user=self.user, idempotency_key="lv2-r1")
        with self.assertRaisesRegex(TransitValidationError, "sold goods still in transit"):
            complete_transit_purchase(
                purchase=purchase, completion_date=date(2026, 2, 4),
                reason="Attempted premature purchase completion",
                idempotency_key="lv2-premature-complete", user=self.user,
            )
        self.assertEqual(TransitLossEvent.objects.filter(lot=lot).count(), 0)
        lot.refresh_from_db()
        self.assertEqual(lot.remaining_quantity, 2)

    def test_loss_after_warehouse_sale_revalues_prior_cogs_via_avco_replay(self):
        purchase = self._purchase("PI-LV-003")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lv3-r1")
        sale = create_sale(
            customer=self.customer, sale_date=date(2026, 2, 3), currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
            lines=[{"product": self.product, "unit": self.uom, "quantity": 30,
                    "unit_price": "120"}],
            user=self.user, document_number="SI-LV-003",
        )
        finalize_sale(sale=sale, user=self.user)
        check = prepare_warehouse_check(
            sale_line=sale.lines.get(), warehouse=self.warehouse,
            quantity=30, number="WC-LV-003",
        )
        finalize_warehouse_check(check=check)
        self.assertEqual(self._balance("5100"), Decimal("3000.00"))

        self._record_loss_after_completion(
            lot=lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="Confirmed transport wastage", idempotency_key="lv3-loss",
            user=self.user,
        )

        # 30 sold at final unit; 68 on hand at final unit; 1430 cleared.
        self.assertEqual(self._balance("5100"), Decimal("3061.22"))
        self.assertEqual(self._balance("1410"), Decimal("6938.78"))
        self.assertEqual(self._balance("1430"), Decimal("0.00"))
        self._assert_journals_balanced()

    def test_landed_cost_before_and_after_loss_uses_good_quantity_once(self):
        purchase = self._purchase("PI-LV-004")
        lot = self._lot(purchase)
        line = purchase.lines.get()
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lv4-r1")
        # Direct cost posted BEFORE the loss: 980 AFN over the lot.
        cost1 = create_landed_cost_draft(
            document_number="LC-LV-004A", payee=self.supplier,
            cost_date=date(2026, 2, 3), currency=self.afn, amount="980",
            exchange_rate="1", rate_date=date(2026, 2, 3), category="FREIGHT",
            purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT,
            user=self.user, idempotency_key="lv4-lc1",
        )
        post_landed_cost(cost_document=cost1, user=self.user)

        event = self._record_loss_after_completion(
            lot=lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="Confirmed transport wastage", idempotency_key="lv4-loss",
            user=self.user,
        )
        # Pool = 10,000 base + 980 landed = 10,980 over 98 good units.
        self.assertEqual(event.final_unit_cost_afn, Decimal("112.0408"))
        self.assertEqual(event.landed_pool_afn_at_valuation, Decimal("980.00"))
        self.assertEqual(self._balance("1430"), Decimal("0.00"))
        self.assertEqual(self._balance("1410"), Decimal("10980.00"))

        # A later landed cost divides by the good quantity (98), not 100,
        # and does not double-count the loss layer.
        cost2 = create_landed_cost_draft(
            document_number="LC-LV-004B", payee=self.supplier,
            cost_date=date(2026, 2, 5), currency=self.afn, amount="490",
            exchange_rate="1", rate_date=date(2026, 2, 5), category="FREIGHT",
            purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT,
            user=self.user, idempotency_key="lv4-lc2",
        )
        post_landed_cost(cost_document=cost2, user=self.user)
        # New total pool 11,470 over 98 units, all still on hand.
        self.assertEqual(self._balance("1410"), Decimal("11470.00"))
        self.assertEqual(self._balance("1430"), Decimal("0.00"))
        self._assert_journals_balanced()

    def test_exact_retry_posts_no_duplicate_journals(self):
        purchase = self._purchase("PI-LV-005")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lv5-r1")
        first = self._record_loss_after_completion(
            lot=lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="Confirmed transport wastage", idempotency_key="lv5-loss",
            user=self.user,
        )
        journal_count = JournalEntry.objects.count()
        adjustment_count = TransitLossValuationAdjustment.objects.count()
        retry = self._record_loss_after_completion(
            lot=lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="Confirmed transport wastage", idempotency_key="lv5-loss",
            user=self.user,
        )
        self.assertEqual(first.pk, retry.pk)
        self.assertEqual(JournalEntry.objects.count(), journal_count)
        self.assertEqual(TransitLossValuationAdjustment.objects.count(), adjustment_count)

    def test_failed_replay_rolls_back_event_closure_and_journals(self):
        purchase = self._purchase("PI-LV-006")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lv6-r1")
        journal_count = JournalEntry.objects.count()
        with patch(
            "purchases.landed_cost_posting.post_transit_loss_valuation",
            side_effect=RuntimeError("simulated replay failure"),
        ):
            with self.assertRaises(RuntimeError):
                self._record_loss_after_completion(
                    lot=lot, quantity=2, loss_date=date(2026, 2, 4),
                    reason="Confirmed transport wastage",
                    idempotency_key="lv6-loss", user=self.user,
                )
        self.assertEqual(TransitLossEvent.objects.filter(lot=lot).count(), 0)
        self.assertEqual(JournalEntry.objects.count(), journal_count)
        lot.refresh_from_db()
        self.assertEqual(lot.remaining_quantity, 2)
        self.assertEqual(lot.status, "OPEN")
        self.assertEqual(self._balance("1430"), Decimal("200.00"))

    def test_no_loss_lot_denominator_and_balances_unchanged(self):
        purchase = self._purchase("PI-LV-007")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=100, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lv7-r1")
        self.assertEqual(
            _good_quantity_for_line(purchase.lines.get(), lot=lot), 100)
        self.assertEqual(self._balance("1430"), Decimal("0.00"))
        self.assertEqual(self._balance("1410"), Decimal("10000.00"))
        self.assertEqual(TransitLossEvent.objects.count(), 0)


class TransitLossValuationFlowTests(TransitLossValuationTests):
    """Loss after warehouse transfers and sales returns (AVCO replay paths)."""

    def test_loss_after_warehouse_transfer_revalues_both_warehouses(self):
        from inventory.services import transfer_stock

        warehouse_b = create_warehouse(name="LossVal Warehouse B", user=self.user)
        WarehouseInventoryAccount.objects.create(
            warehouse=warehouse_b,
            account_id=Account.objects.get(code="1420").pk,
        )
        purchase = self._purchase("PI-LV-008")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lv8-r1")
        transfer_stock(
            product=self.product, source_warehouse=self.warehouse,
            destination_warehouse=warehouse_b, quantity=20,
            movement_date=date(2026, 2, 3), reference="TR-LV-008",
            description="Move to B", user=self.user,
            idempotency_key="lv8-transfer",
        )
        self._record_loss_after_completion(
            lot=lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="Confirmed transport wastage", idempotency_key="lv8-loss",
            user=self.user,
        )
        # 78 units in A and 20 in B, both at the final unit cost.
        self.assertEqual(self._balance("1410"), Decimal("7959.18"))
        self.assertEqual(self._balance("1420"), Decimal("2040.82"))
        self.assertEqual(self._balance("1430"), Decimal("0.00"))
        self._assert_journals_balanced()

    def test_loss_after_warehouse_sales_return_nets_cogs(self):
        from sales.returns_services import create_sales_return

        purchase = self._purchase("PI-LV-009")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lv9-r1")
        sale = create_sale(
            customer=self.customer, sale_date=date(2026, 2, 3), currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
            lines=[{"product": self.product, "unit": self.uom, "quantity": 30,
                    "unit_price": "120"}],
            user=self.user, document_number="SI-LV-009",
        )
        finalize_sale(sale=sale, user=self.user)
        check = prepare_warehouse_check(
            sale_line=sale.lines.get(), warehouse=self.warehouse,
            quantity=30, number="WC-LV-009",
        )
        finalize_warehouse_check(check=check)
        create_sales_return(
            sale_line=sale.lines.get(), warehouse=self.warehouse, quantity=5,
            return_date=date(2026, 2, 4), reason="Customer return",
            document_number="SR-LV-009", idempotency_key="lv9-return",
            user=self.user,
        )
        self._record_loss_after_completion(
            lot=lot, quantity=2, loss_date=date(2026, 2, 5),
            reason="Confirmed transport wastage", idempotency_key="lv9-loss",
            user=self.user,
        )
        # Net sold 25 and on-hand 73, both at the final unit cost.
        self.assertEqual(self._balance("5100"), Decimal("2551.02"))
        self.assertEqual(self._balance("1410"), Decimal("7448.98"))
        self.assertEqual(self._balance("1430"), Decimal("0.00"))
        self.assertEqual(stock_for(self.product, self.warehouse), 73)
        self._assert_journals_balanced()


class TransitLossMasterScenarioTests(TransitLossValuationTests):
    """Master-prompt scenarios: purchase-wide scale, history, periods, retry."""

    def test_purchase_wide_loss_10000_in_multiple_trips(self):
        # Contract example: 10,000 purchased, arrivals in several trips,
        # final confirmed wastage 30 -> denominator 9,970.
        purchase = create_purchase(
            supplier=self.supplier, purchase_date=self.day, currency=self.afn,
            warehouse=self.warehouse,
            lines=[{"product": self.product, "quantity": 10000,
                    "unit_price": "10"}],
            rate="1", rate_date=self.day,
            delivery_mode=PurchaseDeliveryMode.IN_TRANSIT,
            user=self.user, document_number="PI-LV-10000",
        )
        post_purchase(purchase=purchase, user=self.user)
        lot = self._lot(purchase)
        for index, qty in enumerate([2000, 2000, 2000, 2000, 1970]):
            receive_transit(lot=lot, quantity=qty,
                            receipt_date=date(2026, 2, 2),
                            user=self.user, idempotency_key=f"lv10-r{index}")
        event = self._record_loss_after_completion(
            lot=lot, quantity=30, loss_date=date(2026, 2, 4),
            reason="Final wastage after all trips arrived",
            idempotency_key="lv10-loss", user=self.user,
        )
        self.assertEqual(event.good_quantity, 9970)
        # Pool 100,000 AFN / 9,970 = 10.0301 AFN per good unit.
        self.assertEqual(event.final_unit_cost_afn, Decimal("10.0301"))
        self.assertEqual(self._balance("1430"), Decimal("0.00"))
        # 9,970 x 10.0301 (4dp unit) = 100,000.10 on hand; the -0.10
        # rounding residual is credited to COGS so the total cost pool
        # distributed stays exactly 100,000.00 (existing residual contract).
        self.assertEqual(self._balance("1410"), Decimal("100000.10"))
        self.assertEqual(
            self._balance("1410") + self._balance("5100"), Decimal("100000.00"))
        self.assertEqual(stock_for(self.product, self.warehouse), 9970)
        self._assert_journals_balanced()

    def test_posted_history_is_never_mutated_by_loss_valuation(self):
        from accounting.models import JournalLine
        from inventory.models import StockMovement

        purchase = self._purchase("PI-LV-HIST")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lvh-r1")
        lines_before = sorted(
            JournalLine.objects.values_list("pk", "debit", "credit"))
        movements_before = sorted(
            StockMovement.objects.values_list("pk", "quantity", "unit_cost_afn"))
        entries_before = JournalEntry.objects.count()

        self._record_loss_after_completion(
            lot=lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="Confirmed transport wastage", idempotency_key="lvh-loss",
            user=self.user,
        )
        # Every pre-existing line/movement is byte-identical; only new
        # compensating journals were appended.
        self.assertEqual(
            sorted(JournalLine.objects.filter(
                pk__in=[row[0] for row in lines_before]
            ).values_list("pk", "debit", "credit")),
            lines_before,
        )
        self.assertEqual(
            sorted(StockMovement.objects.values_list(
                "pk", "quantity", "unit_cost_afn")),
            movements_before,
        )
        self.assertGreater(JournalEntry.objects.count(), entries_before)

    def test_closed_period_rejects_loss_and_rolls_back(self):
        from fiscal_periods.services import close_period, create_period

        purchase = self._purchase("PI-LV-PERIOD")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lvp-r1")
        period = create_period(
            name="LV Feb 4", start_date=date(2026, 2, 4),
            end_date=date(2026, 2, 4), user=self.user,
        )
        close_period(period, user=self.user, reason="test close")
        journal_count = JournalEntry.objects.count()
        with self.assertRaises(Exception):
            self._record_loss_after_completion(
                lot=lot, quantity=2, loss_date=date(2026, 2, 4),
                reason="Confirmed transport wastage",
                idempotency_key="lvp-loss", user=self.user,
            )
        self.assertEqual(TransitLossEvent.objects.filter(lot=lot).count(), 0)
        self.assertEqual(JournalEntry.objects.count(), journal_count)
        lot.refresh_from_db()
        self.assertEqual(lot.remaining_quantity, 2)
        self.assertEqual(lot.status, "OPEN")

    def test_failure_then_retry_succeeds_exactly_once(self):
        purchase = self._purchase("PI-LV-RETRY")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lvr-r1")
        with patch(
            "purchases.landed_cost_posting.post_transit_loss_valuation",
            side_effect=RuntimeError("simulated replay failure"),
        ):
            with self.assertRaises(RuntimeError):
                self._record_loss_after_completion(
                    lot=lot, quantity=2, loss_date=date(2026, 2, 4),
                    reason="Confirmed transport wastage",
                    idempotency_key="lvr-loss", user=self.user,
                )
        event = self._record_loss_after_completion(
            lot=lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="Confirmed transport wastage",
            idempotency_key="lvr-loss", user=self.user,
        )
        self.assertEqual(event.valuation_status, "POSTED")
        self.assertEqual(TransitLossEvent.objects.filter(lot=lot).count(), 1)
        self.assertEqual(self._balance("1430"), Decimal("0.00"))
        self.assertEqual(self._balance("1410"), Decimal("10000.00"))

    def test_direct_transit_purchase_return_fails_closed_before_loss(self):
        # A direct transit purchase return removes units through
        # 1430/payable under a separate claim contract; until that
        # revaluation contract exists, loss finalization must fail
        # closed and roll back completely (design doc limitation).
        from purchases.services import post_transit_purchase_return

        purchase = self._purchase("PI-LV-TPR")
        lot = self._lot(purchase)
        post_transit_purchase_return(
            purchase=purchase, transit_lot=lot, quantity=10,
            return_date=date(2026, 2, 2), reason="Defective in transit",
            user=self.user, document_number="PRTN-LV-TPR",
            idempotency_key="lvtpr-return",
        )
        receive_transit(lot=lot, quantity=88, receipt_date=date(2026, 2, 3),
                        user=self.user, idempotency_key="lvtpr-r1")
        journal_count = JournalEntry.objects.count()
        with self.assertRaises(TransitValidationError):
            self._record_loss_after_completion(
                lot=lot, quantity=2, loss_date=date(2026, 2, 4),
                reason="Confirmed transport wastage",
                idempotency_key="lvtpr-loss", user=self.user,
            )
        self.assertEqual(TransitLossEvent.objects.filter(lot=lot).count(), 0)
        self.assertEqual(JournalEntry.objects.count(), journal_count)
        lot.refresh_from_db()
        self.assertEqual(lot.remaining_quantity, 2)
        self.assertEqual(lot.status, "OPEN")
