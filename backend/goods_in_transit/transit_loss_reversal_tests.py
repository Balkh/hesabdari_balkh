"""Phase 11 A.4 — governed correction of a posted transit-loss valuation.

The original loss event, snapshot and adjustment journals stay immutable.
The correction posts mirror journals, restores the lot, marks the event
REVERSED, and permits a corrected loss under the same completion evidence.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounting.models import JournalEntry
from purchases.landed_cost_posting import (
    LandedCostPostingError, post_landed_cost, reverse_transit_loss_valuation,
)
from purchases.landed_cost_services import create_landed_cost_draft
from purchases.models import LandedCostAllocationMethod, PurchaseDeliveryMode
from purchases.services import create_purchase, post_purchase

from .models import (
    GoodsInTransitLot, TransitLossEvent, TransitLossValuationReversal,
)
from .services import receive_transit, record_transit_loss
from .transit_loss_valuation_tests import TransitLossValuationTests


class TransitLossReversalTests(TransitLossValuationTests):
    def _posted_loss(self, suffix="R1"):
        purchase = self._purchase(f"PI-LVR-{suffix}")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key=f"lvr{suffix}-r1")
        event = self._record_loss_after_completion(
            lot=lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="Confirmed transport wastage",
            idempotency_key=f"lvr{suffix}-loss", user=self.user,
        )
        return purchase, lot, event

    def test_reversal_restores_balances_lot_and_original_history(self):
        purchase, lot, event = self._posted_loss()
        self.assertEqual(self._balance("1430"), Decimal("0.00"))
        self.assertEqual(self._balance("1410"), Decimal("10000.00"))
        original_journal_ids = set(
            event.valuation_adjustments.values_list("journal_entry_id", flat=True))
        original_lines = sorted(
            JournalEntry.objects.filter(pk__in=original_journal_ids)
            .values_list("pk", "total_debit", "total_credit"))

        reversal = reverse_transit_loss_valuation(
            loss_event=event, reversal_date=date(2026, 2, 5),
            reason="Loss quantity was misreported",
            user=self.user, idempotency_key="lvrR1-reversal",
        )

        # GL is back to the pre-loss valuation; originals are untouched.
        self.assertEqual(self._balance("1430"), Decimal("200.00"))
        self.assertEqual(self._balance("1410"), Decimal("9800.00"))
        self.assertEqual(
            sorted(JournalEntry.objects.filter(pk__in=original_journal_ids)
                   .values_list("pk", "total_debit", "total_credit")),
            original_lines,
        )
        for row in reversal.reversal_adjustments.all():
            self.assertEqual(row.journal_entry.source_type,
                             "TRANSIT_LOSS_VALUATION_REVERSAL")
            self.assertEqual(row.journal_entry.total_debit,
                             row.journal_entry.total_credit)
        event.refresh_from_db()
        self.assertEqual(event.valuation_status, "REVERSED")
        self.assertIsNotNone(event.valuation_reversed_at)
        # Snapshot remains as immutable evidence.
        self.assertEqual(event.good_quantity, 98)
        lot.refresh_from_db()
        self.assertEqual(lot.remaining_quantity, 2)
        self.assertEqual(lot.status, "OPEN")

    def test_reversal_retry_is_idempotent_and_conflicts_rejected(self):
        _purchase, _lot, event = self._posted_loss("R2")
        first = reverse_transit_loss_valuation(
            loss_event=event, reversal_date=date(2026, 2, 5),
            reason="Wrong loss report", user=self.user,
            idempotency_key="lvrR2-reversal",
        )
        journal_count = JournalEntry.objects.count()
        retry = reverse_transit_loss_valuation(
            loss_event=event, reversal_date=date(2026, 2, 5),
            reason="Wrong loss report", user=self.user,
            idempotency_key="lvrR2-reversal",
        )
        self.assertEqual(first.pk, retry.pk)
        self.assertEqual(JournalEntry.objects.count(), journal_count)
        with self.assertRaises(LandedCostPostingError):
            reverse_transit_loss_valuation(
                loss_event=event, reversal_date=date(2026, 2, 6),
                reason="Different payload", user=self.user,
                idempotency_key="lvrR2-reversal",
            )
        with self.assertRaises(LandedCostPostingError):
            reverse_transit_loss_valuation(
                loss_event=event, reversal_date=date(2026, 2, 5),
                reason="Second reversal", user=self.user,
                idempotency_key="lvrR2-reversal-2",
            )

    def test_corrected_loss_can_be_recorded_after_reversal(self):
        purchase, lot, event = self._posted_loss("R3")
        line = purchase.lines.get()
        reverse_transit_loss_valuation(
            loss_event=event, reversal_date=date(2026, 2, 5),
            reason="Wrong loss report", user=self.user,
            idempotency_key="lvrR3-reversal",
        )
        # A late direct cost arrives after the correction; the corrected
        # loss must capitalize it over the good quantity.
        cost = create_landed_cost_draft(
            document_number="LC-LVR-R3", payee=self.supplier,
            cost_date=date(2026, 2, 6), currency=self.afn, amount="980",
            exchange_rate="1", rate_date=date(2026, 2, 6), category="FREIGHT",
            purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT,
            user=self.user, idempotency_key="lvrR3-lc",
        )
        post_landed_cost(cost_document=cost, user=self.user)
        corrected = record_transit_loss(
            lot=lot, quantity=2, loss_date=date(2026, 2, 7),
            reason="Corrected final wastage",
            idempotency_key="lvrR3-loss-corrected", user=self.user,
        )
        self.assertNotEqual(corrected.pk, event.pk)
        self.assertEqual(corrected.valuation_status, "POSTED")
        # Pool (10,000 + 980) over 98 good units; all on hand.
        self.assertEqual(corrected.final_unit_cost_afn, Decimal("112.0408"))
        self.assertEqual(self._balance("1410"), Decimal("10980.00"))
        self.assertEqual(self._balance("1430"), Decimal("0.00"))
        self.assertEqual(
            TransitLossEvent.objects.filter(lot=lot).count(), 2)

    def test_reversal_blocked_after_dependent_landed_cost(self):
        purchase, lot, event = self._posted_loss("R4")
        line = purchase.lines.get()
        cost = create_landed_cost_draft(
            document_number="LC-LVR-R4", payee=self.supplier,
            cost_date=date(2026, 2, 5), currency=self.afn, amount="490",
            exchange_rate="1", rate_date=date(2026, 2, 5), category="FREIGHT",
            purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT,
            user=self.user, idempotency_key="lvrR4-lc",
        )
        post_landed_cost(cost_document=cost, user=self.user)
        journal_count = JournalEntry.objects.count()
        with self.assertRaises(LandedCostPostingError):
            reverse_transit_loss_valuation(
                loss_event=event, reversal_date=date(2026, 2, 6),
                reason="Too late", user=self.user,
                idempotency_key="lvrR4-reversal",
            )
        self.assertEqual(JournalEntry.objects.count(), journal_count)
        self.assertEqual(TransitLossValuationReversal.objects.count(), 0)
        event.refresh_from_db()
        self.assertEqual(event.valuation_status, "POSTED")

    def test_correction_propagates_to_prior_warehouse_sale_cogs(self):
        # 4.6 scenario with a downstream (prior) warehouse sale:
        # sale of 30 at the old unit, loss posted, then the valuation is
        # reversed, a late freight cost arrives, and the corrected loss
        # revalues BOTH the prior COGS and the remaining inventory.
        from purchases.landed_cost_posting import reverse_transit_loss_valuation
        from sales.services import (
            create_sale, finalize_sale, finalize_warehouse_check,
            prepare_warehouse_check,
        )
        from sales.models import PaymentMode, SalesChannel

        purchase = self._purchase("PI-LVR-R5")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lvrR5-r1")
        sale = create_sale(
            customer=self.customer, sale_date=date(2026, 2, 3),
            currency=self.afn, channel=SalesChannel.WHOLESALE,
            payment_mode=PaymentMode.CREDIT,
            lines=[{"product": self.product, "unit": self.uom, "quantity": 30,
                    "unit_price": "120"}],
            user=self.user, document_number="SI-LVR-R5",
        )
        finalize_sale(sale=sale, user=self.user)
        check = prepare_warehouse_check(
            sale_line=sale.lines.get(), warehouse=self.warehouse,
            quantity=30, number="WC-LVR-R5")
        finalize_warehouse_check(check=check)
        event = self._record_loss_after_completion(
            lot=lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="Initial wastage report",
            idempotency_key="lvrR5-loss", user=self.user)
        # 30 sold and 68 on hand at 102.0408.
        self.assertEqual(self._balance("5100"), Decimal("3061.22"))
        self.assertEqual(self._balance("1410"), Decimal("6938.78"))

        reverse_transit_loss_valuation(
            loss_event=event, reversal_date=date(2026, 2, 5),
            reason="Freight invoice omitted from first valuation",
            user=self.user, idempotency_key="lvrR5-reversal")
        self.assertEqual(self._balance("5100"), Decimal("3000.00"))

        line = purchase.lines.get()
        cost = create_landed_cost_draft(
            document_number="LC-LVR-R5", payee=self.supplier,
            cost_date=date(2026, 2, 6), currency=self.afn, amount="980",
            exchange_rate="1", rate_date=date(2026, 2, 6), category="FREIGHT",
            purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT,
            user=self.user, idempotency_key="lvrR5-lc")
        post_landed_cost(cost_document=cost, user=self.user)
        corrected = record_transit_loss(
            lot=lot, quantity=2, loss_date=date(2026, 2, 7),
            reason="Corrected final wastage",
            idempotency_key="lvrR5-loss-corrected", user=self.user)
        # (10,000 + 980) / 98 = 112.0408: prior COGS and stock corrected.
        self.assertEqual(corrected.final_unit_cost_afn, Decimal("112.0408"))
        self.assertEqual(self._balance("5100"), Decimal("3361.22"))
        self.assertEqual(self._balance("1410"), Decimal("7618.78"))
        self.assertEqual(self._balance("1430"), Decimal("0.00"))
        self._assert_journals_balanced()


class TwoPurchaseLotIsolationTests(TransitLossValuationTests):
    def test_loss_on_one_purchase_does_not_change_other_lot_basis(self):
        # Same product, two purchases at different invoice costs.
        purchase_a = self._purchase("PI-LOT-A")
        lot_a = self._lot(purchase_a)
        purchase_b = create_purchase(
            supplier=self.supplier, purchase_date=self.day, currency=self.afn,
            warehouse=self.warehouse,
            lines=[{"product": self.product, "quantity": 100,
                    "unit_price": "200"}],
            rate="1", rate_date=self.day,
            delivery_mode=PurchaseDeliveryMode.IN_TRANSIT,
            user=self.user, document_number="PI-LOT-B",
        )
        post_purchase(purchase=purchase_b, user=self.user)
        lot_b = self._lot(purchase_b)
        receive_transit(lot=lot_a, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lotA-r1")
        receive_transit(lot=lot_b, quantity=100, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lotB-r1")
        event_a = self._record_loss_after_completion(
            lot=lot_a, quantity=2, loss_date=date(2026, 2, 4),
            reason="Lot A wastage", idempotency_key="lotA-loss",
            user=self.user)
        self.assertEqual(event_a.final_unit_cost_afn, Decimal("102.0408"))
        # Lot B keeps its own denominator and cost basis (200.00/unit).
        from purchases.landed_cost_posting import _good_quantity_for_line
        self.assertEqual(
            _good_quantity_for_line(purchase_b.lines.get(), lot=lot_b), 100)
        # Warehouse AVCO pools the product (approved architecture), while
        # purchase-level source layers stay traceable: total value is the
        # sum of both pools, and 1430 is fully cleared for both lots.
        self.assertEqual(self._balance("1410"), Decimal("30000.00"))
        self.assertEqual(self._balance("1430"), Decimal("0.00"))
        self._assert_journals_balanced()
