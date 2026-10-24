"""Security/accounting-integrity regression tests for transit-loss valuation.

Finding A: a PENDING loss event could be marked POSTED (with fabricated
snapshot values) through Model.save() or QuerySet.update(), without the
valuation service ever posting journals.
Finding B: ROUNDING_RESIDUAL accepted an arbitrarily large discrepancy,
so a missing source allocation was silently absorbed into COGS.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounting.models import JournalEntry, PostedImmutabilityError

from purchases.landed_cost_posting import (
    _assert_loss_residual_within_tolerance,
    _loss_rounding_tolerance_afn, LandedCostPostingError,
)
from sales.models import PaymentMode, SalesChannel, TransitSaleAllocation
from sales.services import create_sale, finalize_sale

from .models import (
    GoodsInTransitLot, TransitLossEvent, TransitLossValuationAdjustment, TransitPurchaseCompletion,
)
from .services import TransitValidationError, receive_transit, record_transit_loss as record_transit_loss_service, complete_transit_purchase
from .transit_loss_valuation_tests import TransitLossValuationTests


class FindingAHardeningTests(TransitLossValuationTests):
    def _pending_event(self, suffix="A"):
        purchase = self._purchase(f"PI-HARD-{suffix}")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key=f"hard{suffix}-r1")
        lot.refresh_from_db()
        complete_transit_purchase(purchase=purchase, completion_date=date(2026, 2, 4), reason="All goods for this purchase invoice arrived; trip receipts consolidated.", idempotency_key=f"hard-complete-{lot.purchase_id}", user=self.user)
        event = TransitLossEvent.objects.create(
            lot=lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="hardening repro", idempotency_key=f"hard{suffix}-loss",
            created_by=self.user,
        )
        return event

    def test_purchase_completion_cannot_be_fabricated_or_bulk_created(self):
        purchase = self._purchase("PI-HARD-COMPLETE-GATE")
        lot = self._lot(purchase)
        receive_transit(
            lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
            user=self.user, idempotency_key="hard-complete-gate-r1",
        )
        with self.assertRaises(PostedImmutabilityError):
            TransitPurchaseCompletion.objects.create(
                purchase=purchase, completion_date=date(2026, 2, 4),
                reason="forged completion", idempotency_key="hard-forged-completion",
                completed_by=self.user,
            )
        candidate = TransitPurchaseCompletion(
            purchase=purchase, completion_date=date(2026, 2, 4),
            reason="bulk forged completion", idempotency_key="hard-bulk-completion",
            completed_by=self.user,
        )
        with self.assertRaises(PostedImmutabilityError):
            TransitPurchaseCompletion.objects.bulk_create([candidate])
        self.assertFalse(TransitPurchaseCompletion.objects.filter(purchase=purchase).exists())

    def test_model_save_cannot_fabricate_posted_snapshot(self):
        event = self._pending_event("A1")
        event.valuation_status = "POSTED"
        event.good_quantity = 1
        event.final_unit_cost_afn = Decimal("99999.0000")
        with self.assertRaises(PostedImmutabilityError):
            event.save(update_fields=["valuation_status", "good_quantity",
                                      "final_unit_cost_afn"])
        event.refresh_from_db()
        self.assertEqual(event.valuation_status, "PENDING")
        self.assertIsNone(event.good_quantity)

    def test_model_save_cannot_post_status_alone(self):
        event = self._pending_event("A2")
        event.valuation_status = "POSTED"
        with self.assertRaises(PostedImmutabilityError):
            event.save(update_fields=["valuation_status"])
        event.refresh_from_db()
        self.assertEqual(event.valuation_status, "PENDING")

    def test_queryset_update_cannot_bypass_immutability(self):
        event = self._pending_event("A3")
        with self.assertRaises(PostedImmutabilityError):
            TransitLossEvent.objects.filter(pk=event.pk).update(
                valuation_status="POSTED", good_quantity=3)
        with self.assertRaises(PostedImmutabilityError):
            TransitLossEvent.objects.filter(pk=event.pk).delete()
        event.refresh_from_db()
        self.assertEqual(event.valuation_status, "PENDING")

    def test_bulk_create_is_rejected_for_transit_loss_events(self):
        event = self._pending_event("A7")
        from django.utils import timezone

        candidate = TransitLossEvent(
            lot=event.lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="hardening regression", idempotency_key="hardA7-bulk",
            created_by=self.user, valuation_status="POSTED",
            good_quantity=98, final_unit_cost_afn=Decimal("99999.0000"),
            valuation_posted_at=timezone.now(),
        )
        with self.assertRaises(PostedImmutabilityError):
            TransitLossEvent.objects.bulk_create([candidate])
        self.assertFalse(
            TransitLossEvent.objects.filter(idempotency_key="hardA7-bulk").exists()
        )

    def test_event_cannot_be_created_already_posted(self):
        purchase = self._purchase("PI-HARD-A4")
        lot = self._lot(purchase)
        with self.assertRaises(ValidationError):
            TransitLossEvent.objects.create(
                lot=lot, quantity=2, loss_date=date(2026, 2, 4),
                reason="pre-posted", idempotency_key="hardA4-loss",
                created_by=self.user, valuation_status="POSTED",
                good_quantity=98, final_unit_cost_afn=Decimal("1.0000"),
            )
        self.assertEqual(TransitLossEvent.objects.filter(lot=lot).count(), 0)

    def test_posted_snapshot_cannot_be_rewritten_or_deleted(self):
        event = self._pending_event("A5")
        # Post through the real service path.
        from purchases.landed_cost_posting import post_transit_loss_valuation
        post_transit_loss_valuation(loss_event=event, user=self.user)
        event.refresh_from_db()
        self.assertEqual(event.valuation_status, "POSTED")
        original_good = event.good_quantity
        event.good_quantity = 5
        with self.assertRaises(PostedImmutabilityError):
            event.save(update_fields=["good_quantity"])
        with self.assertRaises(PostedImmutabilityError):
            event.delete()
        with self.assertRaises(PostedImmutabilityError):
            TransitLossEvent.objects.filter(pk=event.pk).update(good_quantity=5)
        event.refresh_from_db()
        self.assertEqual(event.good_quantity, original_good)

    def test_adjustment_cannot_be_created_with_unrelated_journal(self):
        event = self._pending_event("A6")
        unrelated = JournalEntry.objects.filter(
            source_type="PURCHASE").first()
        self.assertIsNotNone(unrelated)
        with self.assertRaises(ValidationError):
            TransitLossValuationAdjustment.objects.create(
                loss_event=event, source_reference="FAKE:1",
                adjustment_type="TRANSIT_SALE", movement=None,
                amount_afn=Decimal("10.00"), journal_entry=unrelated,
            )
        self.assertEqual(
            TransitLossValuationAdjustment.objects.filter(loss_event=event).count(), 0)


class FindingBHardeningTests(TransitLossValuationTests):
    def test_tolerance_derivation_from_precision_rules(self):
        # G=9,970, no 2dp credit terms: 0.0001*9970 + 0 + 0.005 = 1.002 -> 1.00
        tolerance = _loss_rounding_tolerance_afn(good_quantity=9970, credit_terms=0)
        self.assertEqual(tolerance, Decimal("1.00"))
        # Boundary: exactly at tolerance accepted, one cent beyond rejected.
        _assert_loss_residual_within_tolerance(
            residual=tolerance, tolerance_afn=tolerance, lot_id=1)
        _assert_loss_residual_within_tolerance(
            residual=-tolerance, tolerance_afn=tolerance, lot_id=1)
        with self.assertRaises(LandedCostPostingError):
            _assert_loss_residual_within_tolerance(
                residual=tolerance + Decimal("0.01"),
                tolerance_afn=tolerance, lot_id=1)
        with self.assertRaises(LandedCostPostingError):
            _assert_loss_residual_within_tolerance(
                residual=-(tolerance + Decimal("0.01")),
                tolerance_afn=tolerance, lot_id=1)

    def test_loss_completion_fails_closed_while_sold_transit_goods_are_unreceived(self):
        purchase = self._purchase("PI-HARD-B1")
        lot = self._lot(purchase)
        sale = create_sale(
            customer=self.customer, sale_date=date(2026, 2, 2), currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
            lines=[{"product": self.product, "unit": self.uom, "quantity": 40,
                    "unit_price": "120", "transit_lot": lot}],
            user=self.user, document_number="SI-HARD-B1",
        )
        finalize_sale(sale=sale, user=self.user)
        receive_transit(lot=lot, quantity=58, receipt_date=date(2026, 2, 3),
                        user=self.user, idempotency_key="hardB1-r1")
        journal_count = JournalEntry.objects.count()
        # Simulate a missing source allocation during valuation.
        with patch.object(TransitSaleAllocation.objects, "filter",
                          return_value=TransitSaleAllocation.objects.none()):
            with self.assertRaises(TransitValidationError):
                self._record_loss_after_completion(
                    lot=lot, quantity=2, loss_date=date(2026, 2, 4),
                    reason="Confirmed transport wastage",
                    idempotency_key="hardB1-loss", user=self.user,
                )
        # Whole operation rolled back: no event, no journals, lot reopened.
        self.assertEqual(TransitLossEvent.objects.filter(lot=lot).count(), 0)
        self.assertEqual(JournalEntry.objects.count(), journal_count)
        lot.refresh_from_db()
        self.assertEqual(lot.remaining_quantity, 2)
        self.assertEqual(lot.status, "OPEN")
        self.assertEqual(self._balance("1430"), Decimal("200.00"))

    def test_zero_and_small_legitimate_residuals_still_post(self):
        # Exact arithmetic case (residual 0) and the 10,000-unit case
        # (small legitimate residual) are covered by the valuation tests;
        # here a one-receipt case asserts no ROUNDING_RESIDUAL is invented
        # when the reconciliation is already exact.
        purchase = self._purchase("PI-HARD-B2")
        lot = self._lot(purchase)
        receive_transit(lot=lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="hardB2-r1")
        event = self._record_loss_after_completion(
            lot=lot, quantity=2, loss_date=date(2026, 2, 4),
            reason="Confirmed transport wastage",
            idempotency_key="hardB2-loss", user=self.user,
        )
        self.assertEqual(event.valuation_status, "POSTED")
        self.assertEqual(
            event.valuation_adjustments.filter(
                adjustment_type="ROUNDING_RESIDUAL").count(), 0)
