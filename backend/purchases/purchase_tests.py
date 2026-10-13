from datetime import date
from decimal import Decimal

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounting.coa import seed_chart_of_accounts
from accounting.models import JournalEntry, JournalLine, PostedImmutabilityError
from categories.services import create_category
from currencies.models import Currency
from inventory.models import MovementType, StockMovement, WarehouseInventoryAccount
from inventory.stock import avco_for, stock_for
from core.models import IdempotencyRecord
from fiscal_periods.services import PeriodValidationError, close_period, create_period
from party_ledger.ledger import party_balance
from party_ledger.models import PartyLedgerAttribution
from parties.services import create_party
from products.services import create_product
from security.models import AuditEvent
from uom.services import create_uom
from warehouses.services import create_warehouse

from .models import (
    LandedCostAllocation, LandedCostAllocationMethod, LandedCostDocument,
    LandedCostStatus, Purchase, PurchaseLine, PurchaseStatus,
)
from .services import PurchaseValidationError, create_purchase, post_purchase, update_purchase, update_purchase_line
from .landed_cost_services import LandedCostValidationError, create_landed_cost_draft


class PurchaseFoundationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")
        cls.user = get_user_model().objects.create_user("purchase-user", password="x")

    def setUp(self):
        category = create_category(name="Purchase Category", user=self.user)
        uom = create_uom(name="Purchase Unit", user=self.user)
        self.product = create_product(code="PUR-1", name="Purchase Product", name_fa="خرید", category=category, primary_uom=uom, user=self.user)
        self.product2 = create_product(code="PUR-2", name="Second Product", name_fa="دوم", category=category, primary_uom=uom, user=self.user)
        self.supplier = create_party(name="Supplier One", is_supplier=True, user=self.user)
        self.customer = create_party(name="Customer Only", is_customer=True, user=self.user)
        self.warehouse = create_warehouse(name="Purchase Warehouse", user=self.user)
        WarehouseInventoryAccount.objects.create(warehouse=self.warehouse, account_id=self._account_id("1410"))
        self.day = date(2026, 1, 15)

    def _account_id(self, code):
        from accounting.models import Account
        return Account.objects.get(code=code).pk

    def _purchase(self, **kwargs):
        params = dict(
            supplier=self.supplier, purchase_date=self.day, currency=self.afn,
            warehouse=self.warehouse,
            lines=[{"product": self.product, "quantity": 10, "unit_price": "12.0000"}],
            user=self.user,
        )
        params.update(kwargs)
        return create_purchase(**params)

    def test_stage77_draft_creation_has_only_commercial_and_create_audit_effects(self):
        purchase = self._purchase(document_number="PI-DRAFT-SAFE")
        self.assertEqual(purchase.status, PurchaseStatus.DRAFT)
        self.assertTrue(AuditEvent.objects.filter(
            entity="Purchase", entity_id=purchase.pk, action="CREATE"
        ).exists())
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(JournalLine.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(PartyLedgerAttribution.objects.count(), 0)
        self.assertFalse(AuditEvent.objects.filter(
            entity="Purchase", entity_id=purchase.pk, action="POST"
        ).exists())

    def test_stage75_afn_purchase_reconciles_inventory_freight_and_payable(self):
        purchase = self._purchase(
            lines=[{"product": self.product, "quantity": 100, "unit_price": "100"}],
            discount="500", freight="1000", document_number="PI-RECON-AFN",
        )
        post_purchase(purchase=purchase, user=self.user)
        journal = JournalEntry.objects.get(source_type="PURCHASE", source_id=purchase.document_number)
        self.assertEqual(purchase.subtotal, Decimal("10000.00"))
        self.assertEqual(purchase.total, Decimal("10500.00"))
        self.assertEqual(journal.total_debit, Decimal("10500.00"))
        self.assertEqual(journal.total_credit, Decimal("10500.00"))
        self.assertEqual(journal.lines.get(account__code="1410").debit, Decimal("10500.00"))
        self.assertFalse(journal.lines.filter(account__code="6200").exists())
        self.assertEqual(journal.lines.get(account__code="2110").credit, Decimal("10500.00"))
        line = purchase.lines.get()
        movement = StockMovement.objects.get(reference=f"{purchase.document_number}:LINE:{line.pk}")
        self.assertEqual(movement.unit_cost, Decimal("105.0000"))
        self.assertEqual(movement.unit_cost_afn, Decimal("105.0000"))
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("105.0000"))
        balance = party_balance(self.supplier, currency=self.afn, balance_type="PAYABLE")
        self.assertEqual(balance["balance"], Decimal("10500.00"))

    def test_stage75_foreign_purchase_preserves_amount_rate_and_afn_reconciliation(self):
        purchase = self._purchase(
            currency=self.usd, rate="70", rate_date=self.day,
            lines=[{"product": self.product, "quantity": 10, "unit_price": "100"}],
            discount="50", freight="20", document_number="PI-RECON-USD",
        )
        post_purchase(purchase=purchase, user=self.user)
        journal = JournalEntry.objects.get(source_type="PURCHASE", source_id=purchase.document_number)
        line = purchase.lines.get()
        movement = StockMovement.objects.get(reference=f"{purchase.document_number}:LINE:{line.pk}")
        self.assertEqual(purchase.total, Decimal("970.00"))
        self.assertEqual(journal.total_debit, Decimal("970.00"))
        self.assertEqual(journal.total_credit, Decimal("970.00"))
        self.assertEqual(journal.afn_total, Decimal("67900.00"))
        self.assertEqual(journal.currency, self.usd)
        self.assertEqual(journal.rate, Decimal("70.0000"))
        self.assertEqual(movement.currency, self.usd)
        self.assertEqual(movement.rate, Decimal("70.0000"))
        self.assertEqual(movement.unit_cost, Decimal("97.0000"))
        self.assertEqual(movement.unit_cost_afn, Decimal("6790.0000"))
        balance = party_balance(self.supplier, currency=self.usd, balance_type="PAYABLE")
        self.assertEqual(balance["balance"], Decimal("970.00"))

    def test_stage76_draft_edit_recalculates_and_posts_only_final_state(self):
        supplier_b = create_party(name="Supplier Two", is_supplier=True, user=self.user)
        warehouse_b = create_warehouse(name="Second Purchase Warehouse", user=self.user)
        WarehouseInventoryAccount.objects.create(warehouse=warehouse_b, account_id=self._account_id("1410"))
        purchase = self._purchase(document_number="PI-DRAFT-EDIT")
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(PartyLedgerAttribution.objects.count(), 0)
        updated = update_purchase(
            purchase, supplier=supplier_b, warehouse=warehouse_b, currency=self.usd,
            rate="72", rate_date=date(2026, 1, 20), discount="50", freight="20",
            description="final draft", lines=[
                {"product": self.product2, "quantity": 4, "unit_price": "100"},
            ], user=self.user,
        )
        self.assertEqual(updated.status, PurchaseStatus.DRAFT)
        self.assertEqual(updated.supplier, supplier_b)
        self.assertEqual(updated.warehouse, warehouse_b)
        self.assertEqual(updated.currency, self.usd)
        self.assertEqual(updated.exchange_rate, Decimal("72.0000"))
        self.assertEqual(updated.rate_date, date(2026, 1, 20))
        self.assertEqual(updated.subtotal, Decimal("400.00"))
        self.assertEqual(updated.discount, Decimal("50.00"))
        self.assertEqual(updated.freight, Decimal("20.00"))
        self.assertEqual(updated.total, Decimal("370.00"))
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(PartyLedgerAttribution.objects.count(), 0)
        self.assertFalse(AuditEvent.objects.filter(entity="Purchase", entity_id=updated.pk, action="POST").exists())

        post_purchase(purchase=updated, user=self.user)
        journal = JournalEntry.objects.get(source_type="PURCHASE", source_id=updated.document_number)
        movement = StockMovement.objects.get(reference=f"{updated.document_number}:LINE:{updated.lines.get().pk}")
        self.assertEqual(journal.currency, self.usd)
        self.assertEqual(journal.rate, Decimal("72.0000"))
        self.assertEqual(journal.lines.get(account__code="2110").credit, Decimal("370.00"))
        self.assertEqual(movement.product, self.product2)
        self.assertEqual(movement.warehouse, warehouse_b)
        self.assertEqual(movement.unit_cost, Decimal("92.5000"))
        self.assertEqual(movement.rate, Decimal("72.0000"))
        self.assertEqual(
            PartyLedgerAttribution.objects.get(journal_line=journal.lines.get(account__code="2110")).party,
            supplier_b,
        )
        self.assertFalse(PartyLedgerAttribution.objects.filter(party=self.supplier).exists())

    def test_stage76_line_edit_recalculates_draft_without_financial_effects(self):
        purchase = self._purchase()
        update_purchase_line(purchase.lines.get(), quantity=20, unit_price="15", user=self.user)
        purchase.refresh_from_db()
        line = purchase.lines.get()
        self.assertEqual(line.quantity, 20)
        self.assertEqual(line.unit_price, Decimal("15.0000"))
        self.assertEqual(purchase.subtotal, Decimal("300.00"))
        self.assertEqual(purchase.total, Decimal("300.00"))
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(PartyLedgerAttribution.objects.count(), 0)

    def test_create_valid_purchase_and_discount_allocation(self):
        purchase = self._purchase(
            discount="40", freight="25",
            lines=[
                {"product": self.product, "quantity": 10, "unit_price": "100", "measured_weight_kg": "10"},
                {"product": self.product2, "quantity": 30, "unit_price": "100", "measured_weight_kg": "30"},
            ],
        )
        lines = list(purchase.lines.all())
        self.assertEqual(purchase.subtotal, Decimal("4000.00"))
        self.assertEqual(sum((line.discount_allocated for line in lines), Decimal("0")), Decimal("40.00"))
        self.assertEqual([line.net_total for line in lines], [Decimal("990.00"), Decimal("2970.00")])
        self.assertEqual([line.freight_allocated for line in lines], [Decimal("6.25"), Decimal("18.75")])
        self.assertEqual(sum((line.freight_allocated for line in lines), Decimal("0.00")), purchase.freight)
        self.assertEqual(purchase.total, Decimal("3985.00"))
        self.assertEqual(purchase.status, PurchaseStatus.DRAFT)
        self.assertEqual(StockMovement.objects.count(), 0)


    def test_shared_freight_rejects_missing_measured_weight_before_posting(self):
        with self.assertRaises(PurchaseValidationError):
            self._purchase(
                lines=[
                    {"product": self.product, "quantity": 2, "unit_price": "10"},
                    {"product": self.product2, "quantity": 3, "unit_price": "20"},
                ],
                freight="7", document_number="PI-MISSING-WEIGHT",
            )
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_stage76_line_edit_preserves_measured_weight_and_reallocates_freight(self):
        purchase = self._purchase(
            lines=[
                {"product": self.product, "quantity": 10, "unit_price": "100", "measured_weight_kg": "10"},
                {"product": self.product2, "quantity": 30, "unit_price": "100", "measured_weight_kg": "30"},
            ],
            freight="25", document_number="PI-WEIGHT-EDIT",
        )
        update_purchase_line(purchase.lines.order_by("id").first(), quantity=20, user=self.user)
        lines = list(purchase.lines.order_by("id"))
        self.assertEqual([line.measured_weight_kg for line in lines], [Decimal("10.0000"), Decimal("30.0000")])
        self.assertEqual([line.freight_allocated for line in lines], [Decimal("6.25"), Decimal("18.75")])
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_full_discount_is_permitted_but_over_discount_is_rejected(self):
        purchase = self._purchase(
            discount="1000",
            lines=[{"product": self.product, "quantity": 10, "unit_price": "100"}],
            document_number="PI-FULL-DISCOUNT",
        )
        self.assertEqual(purchase.subtotal, Decimal("1000.00"))
        self.assertEqual(purchase.total, Decimal("0.00"))
        self.assertEqual(purchase.lines.get().net_total, Decimal("0.00"))
        with self.assertRaises(PurchaseValidationError):
            self._purchase(
                discount="1000.01",
                lines=[{"product": self.product, "quantity": 10, "unit_price": "100"}],
                document_number="PI-OVER-DISCOUNT",
            )

    def test_rejects_non_supplier_and_invalid_quantity(self):
        with self.assertRaises(PurchaseValidationError):
            self._purchase(supplier=self.customer)
        with self.assertRaises(PurchaseValidationError):
            self._purchase(lines=[{"product": self.product, "quantity": 1.5, "unit_price": "10"}])

    def test_post_revalidates_inconsistent_draft_totals_before_side_effects(self):
        purchase = self._purchase(document_number="PI-INVALID-DRAFT")
        line = purchase.lines.first()
        line.unit_price = Decimal("99.0000")
        line.save(update_fields=["unit_price"])
        with self.assertRaises(PurchaseValidationError):
            post_purchase(purchase=purchase, user=self.user)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, PurchaseStatus.DRAFT)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(JournalEntry.objects.filter(source_type="PURCHASE").count(), 0)

    def test_post_creates_receipts_journal_and_supplier_attribution(self):
        purchase = self._purchase(lines=[{"product": self.product, "quantity": 10, "unit_price": "12"}])
        posted = post_purchase(purchase=purchase, user=self.user)
        self.assertEqual(posted.status, PurchaseStatus.POSTED)
        self.assertEqual(stock_for(self.product, self.warehouse), 10)
        line = purchase.lines.get()
        movement = StockMovement.objects.get(reference=f"{purchase.document_number}:LINE:{line.pk}")
        self.assertEqual(movement.movement_type, MovementType.PURCHASE_RECEIPT)
        self.assertEqual(movement.unit_cost, Decimal("12.0000"))
        self.assertEqual(movement.currency, self.afn)
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("12.0000"))
        journal = JournalEntry.objects.get(source_type="PURCHASE", source_id=purchase.document_number)
        self.assertEqual(journal.total_debit, Decimal("120.00"))
        self.assertEqual(journal.total_credit, Decimal("120.00"))
        self.assertEqual(journal.lines.get(account__code="1410").debit, Decimal("120.00"))
        self.assertEqual(journal.lines.get(account__code="2110").credit, Decimal("120.00"))
        self.assertEqual(journal.lines.get(account__code="2110").party_ledger_attribution.party, self.supplier)
        self.assertTrue(AuditEvent.objects.filter(entity="Purchase", entity_id=purchase.pk).exists())

    def test_stage73_line_traceability_and_post_audit_effect_references(self):
        purchase = self._purchase(
            lines=[
                {"product": self.product, "quantity": 2, "unit_price": "10", "measured_weight_kg": "2"},
                {"product": self.product, "quantity": 3, "unit_price": "20", "measured_weight_kg": "3"},
            ],
            discount="10", freight="7",
            document_number="PI-TRACE-001",
        )
        post_purchase(purchase=purchase, user=self.user)
        lines = list(purchase.lines.order_by("id"))
        movements = [
            StockMovement.objects.get(reference=f"{purchase.document_number}:LINE:{line.pk}")
            for line in lines
        ]
        self.assertEqual([movement.product_id for movement in movements], [self.product.pk, self.product.pk])
        self.assertEqual([movement.quantity for movement in movements], [2, 3])
        self.assertEqual([movement.warehouse_id for movement in movements], [self.warehouse.pk, self.warehouse.pk])
        self.assertEqual([movement.unit_cost for movement in movements], [Decimal("10.1500"), Decimal("18.9000")])
        journal = JournalEntry.objects.get(source_type="PURCHASE", source_id=purchase.document_number)
        payable_line = journal.lines.get(account__code="2110")
        self.assertEqual(payable_line.party_ledger_attribution.party_id, self.supplier.pk)
        post_event = AuditEvent.objects.get(entity="Purchase", entity_id=purchase.pk, action="POST")
        self.assertEqual(post_event.new_state["journal_entry_id"], journal.pk)
        self.assertEqual(post_event.new_state["stock_movement_ids"], [movement.pk for movement in movements])
        self.assertEqual(post_event.new_state["stock_movement_references"], [movement.reference for movement in movements])

    def test_freight_is_capitalized_into_inventory_cost(self):
        purchase = self._purchase(freight="30")
        post_purchase(purchase=purchase, user=self.user)
        journal = JournalEntry.objects.get(source_type="PURCHASE", source_id=purchase.document_number)
        self.assertFalse(journal.lines.filter(account__code="6200").exists())
        self.assertEqual(journal.lines.get(account__code="1410").debit, Decimal("150.00"))
        movement = StockMovement.objects.get(reference=f"{purchase.document_number}:LINE:{purchase.lines.get().pk}")
        self.assertEqual(movement.unit_cost, Decimal("15.0000"))
        self.assertEqual(stock_for(self.product, self.warehouse), 10)
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("15.0000"))

    def test_foreign_currency_context_is_preserved(self):
        purchase = self._purchase(currency=self.usd, rate="70", rate_date=self.day, lines=[{"product": self.product, "quantity": 2, "unit_price": "10"}])
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        movement = StockMovement.objects.get(reference=f"{purchase.document_number}:LINE:{line.pk}")
        journal = JournalEntry.objects.get(source_type="PURCHASE", source_id=purchase.document_number)
        self.assertEqual(movement.currency, self.usd)
        self.assertEqual(movement.rate, Decimal("70.0000"))
        self.assertEqual(journal.currency, self.usd)
        self.assertEqual(journal.rate, Decimal("70.0000"))
        self.assertEqual(movement.unit_cost_afn, Decimal("700.0000"))

    def test_stage77_multiline_repeated_product_retry_preserves_line_traceability(self):
        purchase = self._purchase(
            lines=[
                {"product": self.product, "quantity": 2, "unit_price": "10", "measured_weight_kg": "2"},
                {"product": self.product, "quantity": 3, "unit_price": "20", "measured_weight_kg": "3"},
                {"product": self.product2, "quantity": 4, "unit_price": "5", "measured_weight_kg": "4"},
            ],
            discount="10", freight="7", document_number="PI-MULTI-RETRY",
        )
        first = post_purchase(purchase=purchase, user=self.user, idempotency_key="multi-retry")
        second = post_purchase(purchase=purchase, user=self.user, idempotency_key="multi-retry")
        self.assertEqual(first.pk, second.pk)
        lines = list(purchase.lines.order_by("id"))
        references = [f"{purchase.document_number}:LINE:{line.pk}" for line in lines]
        movements = list(StockMovement.objects.filter(reference__in=references).order_by("id"))
        self.assertEqual([movement.reference for movement in movements], references)
        self.assertEqual(len(set(references)), 3)
        self.assertEqual(StockMovement.objects.count(), 3)
        self.assertEqual(JournalEntry.objects.filter(source_type="PURCHASE").count(), 1)
        self.assertEqual(JournalLine.objects.count(), 2)
        self.assertEqual(PartyLedgerAttribution.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(
            entity="Purchase", entity_id=purchase.pk, action="POST"
        ).count(), 1)
        self.assertEqual(IdempotencyRecord.objects.filter(key="multi-retry").count(), 1)
        self.assertEqual(stock_for(self.product, self.warehouse), 5)
        self.assertEqual(stock_for(self.product2, self.warehouse), 4)

    def test_exact_post_retry_is_idempotent_and_changed_key_rejected(self):
        purchase = self._purchase()
        first = post_purchase(purchase=purchase, user=self.user, idempotency_key="purchase-retry-1")
        second = post_purchase(purchase=purchase, user=self.user, idempotency_key="purchase-retry-1")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(JournalEntry.objects.filter(source_type="PURCHASE").count(), 1)
        self.assertEqual(PartyLedgerAttribution.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(entity="Purchase", entity_id=purchase.pk, action="POST").count(), 1)
        other = self._purchase(document_number="PI-DIFFERENT")
        with self.assertRaises(PurchaseValidationError):
            post_purchase(purchase=other, user=self.user, idempotency_key="purchase-retry-1")

    def test_stage77_late_failure_rolls_back_all_purchase_posting_effects(self):
        purchase = self._purchase(document_number="PI-LATE-ALL")
        key = "late-all-effects"
        with mock.patch("purchases.services.receive_stock", side_effect=RuntimeError("late failure")):
            with self.assertRaises(RuntimeError):
                post_purchase(purchase=purchase, user=self.user, idempotency_key=key)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, PurchaseStatus.DRAFT)
        self.assertIsNone(purchase.posted_at)
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(JournalLine.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(PartyLedgerAttribution.objects.count(), 0)
        self.assertFalse(AuditEvent.objects.filter(
            entity="Purchase", entity_id=purchase.pk, action="POST"
        ).exists())
        self.assertFalse(IdempotencyRecord.objects.filter(key=key).exists())

    def test_late_receipt_failure_rolls_back_journal_and_stock(self):
        purchase = self._purchase()
        with mock.patch("purchases.services.receive_stock", side_effect=RuntimeError("late failure")):
            with self.assertRaises(RuntimeError):
                post_purchase(purchase=purchase, user=self.user)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, PurchaseStatus.DRAFT)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(JournalEntry.objects.filter(source_type="PURCHASE").count(), 0)

    def test_stage77_posted_purchase_rejects_draft_update_service(self):
        purchase = self._purchase(document_number="PI-POSTED-UPDATE")
        post_purchase(purchase=purchase, user=self.user)
        with self.assertRaises(PurchaseValidationError):
            update_purchase(purchase, supplier=self.customer, user=self.user)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, PurchaseStatus.POSTED)
        self.assertEqual(purchase.supplier, self.supplier)

    def test_posted_purchase_and_line_are_immutable(self):
        purchase = self._purchase()
        post_purchase(purchase=purchase, user=self.user)
        purchase.description = "changed"
        with self.assertRaises(PostedImmutabilityError):
            purchase.save()
        with self.assertRaises(PostedImmutabilityError):
            purchase.delete()
        line = purchase.lines.first()
        line.quantity = 99
        with self.assertRaises(PostedImmutabilityError):
            line.save()

    def test_stage77_posted_purchase_bulk_update_is_rejected(self):
        purchase = self._purchase(document_number="PI-BULK-UPDATE")
        post_purchase(purchase=purchase, user=self.user)
        with self.assertRaises(PostedImmutabilityError):
            Purchase.objects.filter(pk=purchase.pk).update(description="tampered")
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, PurchaseStatus.POSTED)
        self.assertEqual(purchase.description, "")

    def test_stage77_posted_purchase_bulk_delete_is_rejected(self):
        purchase = self._purchase(document_number="PI-BULK-DELETE")
        post_purchase(purchase=purchase, user=self.user)
        line_id = purchase.lines.get().pk
        with self.assertRaises(PostedImmutabilityError):
            Purchase.objects.filter(pk=purchase.pk).delete()
        self.assertTrue(Purchase.objects.filter(pk=purchase.pk).exists())
        self.assertTrue(PurchaseLine.objects.filter(pk=line_id).exists())
        self.assertEqual(
            Purchase.objects.get(pk=purchase.pk).status, PurchaseStatus.POSTED
        )

    def test_stage77_posted_purchase_line_bulk_update_is_rejected(self):
        purchase = self._purchase(document_number="PI-LINE-BULK-UPDATE")
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        with self.assertRaises(PostedImmutabilityError):
            PurchaseLine.objects.filter(pk=line.pk).update(quantity=99)
        line.refresh_from_db()
        self.assertEqual(line.quantity, 10)
        self.assertEqual(
            Purchase.objects.get(pk=purchase.pk).status, PurchaseStatus.POSTED
        )

    def test_stage77_posted_purchase_line_bulk_delete_is_rejected(self):
        purchase = self._purchase(document_number="PI-LINE-BULK-DELETE")
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        with self.assertRaises(PostedImmutabilityError):
            PurchaseLine.objects.filter(pk=line.pk).delete()
        self.assertTrue(PurchaseLine.objects.filter(pk=line.pk).exists())
        self.assertEqual(
            Purchase.objects.get(pk=purchase.pk).status, PurchaseStatus.POSTED
        )

    def test_stage74_all_posted_historical_surfaces_are_immutable(self):
        purchase = self._purchase(document_number="PI-IMMUTABLE-001")
        post_purchase(purchase=purchase, user=self.user)
        purchase.refresh_from_db()
        line = purchase.lines.get()
        movement = StockMovement.objects.get(reference=f"{purchase.document_number}:LINE:{line.pk}")
        journal = JournalEntry.objects.get(source_type="PURCHASE", source_id=purchase.document_number)
        journal_line = journal.lines.get(account__code="2110")
        attribution = PartyLedgerAttribution.objects.get(journal_line=journal_line)
        original = {
            "purchase_supplier": purchase.supplier_id,
            "line_quantity": line.quantity,
            "movement_cost": movement.unit_cost,
            "journal_description": journal.description,
            "journal_credit": journal_line.credit,
            "attribution_party": attribution.party_id,
        }

        purchase.supplier = self.customer
        with self.assertRaises(PostedImmutabilityError):
            purchase.save()
        line.quantity = 99
        with self.assertRaises(PostedImmutabilityError):
            line.save()
        with self.assertRaises(PostedImmutabilityError):
            line.delete()
        movement.unit_cost = Decimal("999.0000")
        with self.assertRaises(PostedImmutabilityError):
            movement.save()
        with self.assertRaises(PostedImmutabilityError):
            movement.delete()
        journal.description = "rewritten history"
        with self.assertRaises(PostedImmutabilityError):
            journal.save()
        with self.assertRaises(PostedImmutabilityError):
            journal.delete()
        journal_line.credit = Decimal("1.00")
        with self.assertRaises(PostedImmutabilityError):
            journal_line.save()
        with self.assertRaises(PostedImmutabilityError):
            journal_line.delete()
        attribution.party = self.customer
        with self.assertRaises(PostedImmutabilityError):
            attribution.save()
        with self.assertRaises(PostedImmutabilityError):
            attribution.delete()
        with self.assertRaises(PostedImmutabilityError):
            purchase.delete()

        purchase.refresh_from_db()
        line.refresh_from_db()
        movement.refresh_from_db()
        journal.refresh_from_db()
        journal_line.refresh_from_db()
        attribution.refresh_from_db()
        self.assertEqual(purchase.supplier_id, original["purchase_supplier"])
        self.assertEqual(line.quantity, original["line_quantity"])
        self.assertEqual(movement.unit_cost, original["movement_cost"])
        self.assertEqual(journal.description, original["journal_description"])
        self.assertEqual(journal_line.credit, original["journal_credit"])
        self.assertEqual(attribution.party_id, original["attribution_party"])

    def test_closed_fiscal_period_rejects_purchase_without_posting_side_effects(self):
        period = create_period(
            name="Closed Purchase Period", start_date=self.day, end_date=self.day,
            user=self.user,
        )
        close_period(period, user=self.user, reason="Stage 7.1 evidence")
        purchase = self._purchase(document_number="PI-CLOSED-001")
        key = "purchase-closed-period-1"
        with self.assertRaises(PeriodValidationError):
            post_purchase(purchase=purchase, user=self.user, idempotency_key=key)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, PurchaseStatus.DRAFT)
        self.assertIsNone(purchase.posted_at)
        self.assertEqual(StockMovement.objects.filter(reference=purchase.document_number).count(), 0)
        self.assertEqual(
            JournalEntry.objects.filter(source_type="PURCHASE", source_id=purchase.document_number).count(),
            0,
        )
        self.assertEqual(PartyLedgerAttribution.objects.count(), 0)
        from core.models import IdempotencyRecord
        self.assertFalse(IdempotencyRecord.objects.filter(key=key).exists())
        self.assertFalse(
            AuditEvent.objects.filter(entity="Purchase", entity_id=purchase.pk, action="POST").exists()
        )

    def test_missing_foreign_rate_rejected(self):
        with self.assertRaises(PurchaseValidationError):
            self._purchase(currency=self.usd)


    def test_landed_cost_source_and_allocation_preserve_historical_context(self):
        purchase = self._purchase(document_number="PI-LC-SCHEMA-001")
        line = purchase.lines.get()
        cost = LandedCostDocument.objects.create(
            document_number="LC-SCHEMA-001",
            payee=self.supplier,
            cost_date=self.day,
            currency=self.usd,
            amount=Decimal("25.00"),
            exchange_rate=Decimal("70.0000"),
            rate_date=self.day,
            afn_amount=Decimal("1750.00"),
            category="FREIGHT",
            description="Carrier freight",
            idempotency_key="lc-schema-idempotency-001",
            created_by=self.user,
        )
        allocation = LandedCostAllocation.objects.create(
            cost_document=cost,
            purchase_line=line,
            method=LandedCostAllocationMethod.DIRECT,
            amount=Decimal("25.00"),
            afn_amount=Decimal("1750.00"),
        )
        allocation.amount = Decimal("24.00")
        allocation.save(update_fields=["amount"])
        allocation.refresh_from_db()
        self.assertEqual(allocation.amount, Decimal("24.00"))
        self.assertEqual(cost.exchange_rate, Decimal("70.0000"))
        self.assertEqual(cost.rate_date, self.day)
        self.assertEqual(cost.payee_id, self.supplier.pk)

    def test_posted_landed_cost_and_allocations_are_immutable(self):
        purchase = self._purchase(document_number="PI-LC-SCHEMA-002")
        cost = LandedCostDocument.objects.create(
            document_number="LC-SCHEMA-002",
            payee=self.supplier,
            cost_date=self.day,
            currency=self.afn,
            amount=Decimal("100.00"),
            exchange_rate=Decimal("1.0000"),
            rate_date=self.day,
            afn_amount=Decimal("100.00"),
            category="FREIGHT",
            idempotency_key="lc-schema-idempotency-002",
            created_by=self.user,
        )
        allocation = LandedCostAllocation.objects.create(
            cost_document=cost,
            purchase_line=purchase.lines.get(),
            method=LandedCostAllocationMethod.WEIGHT,
            amount=Decimal("100.00"),
            afn_amount=Decimal("100.00"),
            measured_weight_kg=Decimal("10.0000"),
        )
        cost.status = LandedCostStatus.POSTED
        cost.save(update_fields=["status"])
        with self.assertRaises(PostedImmutabilityError):
            cost.save()
        with self.assertRaises(PostedImmutabilityError):
            LandedCostDocument.objects.filter(pk=cost.pk).update(description="rewritten")
        allocation.amount = Decimal("99.00")
        with self.assertRaises(PostedImmutabilityError):
            allocation.save(update_fields=["amount"])
        with self.assertRaises(PostedImmutabilityError):
            LandedCostAllocation.objects.filter(pk=allocation.pk).update(amount=Decimal("99.00"))
        with self.assertRaises(PostedImmutabilityError):
            allocation.delete()


    def test_late_landed_cost_draft_allocates_direct_cost_and_preserves_history(self):
        purchase = self._purchase(
            currency=self.usd, rate="70", rate_date=self.day,
            document_number="PI-LC-DRAFT-001",
        )
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        original_movement = StockMovement.objects.get(reference=f"{purchase.document_number}:LINE:{line.pk}")
        original_journal_count = JournalEntry.objects.count()
        cost = create_landed_cost_draft(
            document_number="LC-DRAFT-001", payee=self.supplier, cost_date=self.day,
            currency=self.usd, amount="25.00", exchange_rate="71.25",
            rate_date=date(2026, 1, 14), category="FREIGHT",
            description="Late carrier invoice", purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT, user=self.user,
            idempotency_key="lc-draft-direct-001",
        )
        allocation = cost.allocations.get()
        self.assertEqual(cost.status, LandedCostStatus.DRAFT)
        self.assertEqual(cost.afn_amount, Decimal("1781.25"))
        self.assertEqual(allocation.amount, Decimal("25.00"))
        self.assertEqual(allocation.afn_amount, Decimal("1781.25"))
        self.assertEqual(allocation.method, LandedCostAllocationMethod.DIRECT)
        self.assertEqual(JournalEntry.objects.count(), original_journal_count)
        original_movement.refresh_from_db()
        self.assertEqual(original_movement.unit_cost, Decimal("12.0000"))
        self.assertEqual(original_movement.unit_cost_afn, Decimal("840.0000"))

    def test_late_landed_cost_weight_allocation_reconciles_cents_and_afn(self):
        purchase = self._purchase(
            currency=self.usd, rate="70", rate_date=self.day,
            document_number="PI-LC-WEIGHT-001",
            lines=[
                {"product": self.product, "quantity": 10, "unit_price": "10", "measured_weight_kg": "10"},
                {"product": self.product2, "quantity": 10, "unit_price": "10", "measured_weight_kg": "20"},
            ],
        )
        post_purchase(purchase=purchase, user=self.user)
        lines = list(purchase.lines.order_by("id"))
        cost = create_landed_cost_draft(
            document_number="LC-WEIGHT-001", payee=self.supplier, cost_date=self.day,
            currency=self.usd, amount="10.00", exchange_rate="70.0000",
            rate_date=self.day, category="FREIGHT", purchase_line_ids=[l.pk for l in lines],
            allocation_method=LandedCostAllocationMethod.WEIGHT, user=self.user,
            idempotency_key="lc-draft-weight-001",
        )
        allocations = list(cost.allocations.order_by("id"))
        self.assertEqual([row.amount for row in allocations], [Decimal("3.33"), Decimal("6.67")])
        self.assertEqual(sum((row.amount for row in allocations), Decimal("0.00")), Decimal("10.00"))
        self.assertEqual(sum((row.afn_amount for row in allocations), Decimal("0.00")), Decimal("700.00"))
        self.assertEqual([row.measured_weight_kg for row in allocations], [Decimal("10.0000"), Decimal("20.0000")])

    def test_late_landed_cost_rejects_missing_weight_and_draft_source_atomically(self):
        draft = self._purchase(document_number="PI-LC-UNPOSTED-001")
        with self.assertRaises(LandedCostValidationError):
            create_landed_cost_draft(
                document_number="LC-UNPOSTED-001", payee=self.supplier, cost_date=self.day,
                currency=self.afn, amount="10.00", exchange_rate="1", rate_date=self.day,
                category="FREIGHT", purchase_line_ids=[draft.lines.get().pk],
                allocation_method=LandedCostAllocationMethod.DIRECT, user=self.user,
                idempotency_key="lc-draft-unposted-001",
            )
        posted = self._purchase(
            document_number="PI-LC-NOWEIGHT-001",
            lines=[
                {"product": self.product, "quantity": 10, "unit_price": "10"},
                {"product": self.product2, "quantity": 10, "unit_price": "10"},
            ],
        )
        post_purchase(purchase=posted, user=self.user)
        before = JournalEntry.objects.count()
        with self.assertRaises(LandedCostValidationError):
            create_landed_cost_draft(
                document_number="LC-NOWEIGHT-001", payee=self.supplier, cost_date=self.day,
                currency=self.afn, amount="10.00", exchange_rate="1", rate_date=self.day,
                category="FREIGHT", purchase_line_ids=list(posted.lines.values_list("pk", flat=True)),
                allocation_method=LandedCostAllocationMethod.WEIGHT, user=self.user,
                idempotency_key="lc-draft-no-weight-001",
            )
        self.assertFalse(LandedCostDocument.objects.filter(document_number="LC-NOWEIGHT-001").exists())
        self.assertEqual(JournalEntry.objects.count(), before)

    def test_late_landed_cost_idempotency_returns_exact_draft_and_rejects_changed_payload(self):
        purchase = self._purchase(document_number="PI-LC-IDEM-001")
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        args = dict(
            document_number="LC-IDEM-001", payee=self.supplier, cost_date=self.day,
            currency=self.afn, amount="10.00", exchange_rate="1", rate_date=self.day,
            category="FREIGHT", purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT, user=self.user,
            idempotency_key="lc-draft-idempotency-001",
        )
        first = create_landed_cost_draft(**args)
        retry = create_landed_cost_draft(**args)
        self.assertEqual(first.pk, retry.pk)
        args["amount"] = "11.00"
        with self.assertRaises(LandedCostValidationError):
            create_landed_cost_draft(**args)
        self.assertEqual(LandedCostDocument.objects.filter(idempotency_key=args["idempotency_key"]).count(), 1)


    def test_late_landed_cost_rejects_cost_date_before_source_purchase_atomically(self):
        purchase = self._purchase(
            document_number="PI-LC-BEFORE-COST-001",
        )
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        before_documents = LandedCostDocument.objects.count()
        before_journals = JournalEntry.objects.count()
        with self.assertRaises(LandedCostValidationError):
            create_landed_cost_draft(
                document_number="LC-BEFORE-COST-001", payee=self.supplier,
                cost_date=date(2025, 12, 31), currency=self.afn, amount="10.00",
                exchange_rate="1", rate_date=date(2025, 12, 31), category="FREIGHT",
                purchase_line_ids=[line.pk], allocation_method=LandedCostAllocationMethod.DIRECT,
                user=self.user, idempotency_key="lc-before-cost-001",
            )
        self.assertEqual(LandedCostDocument.objects.count(), before_documents)
        self.assertEqual(JournalEntry.objects.count(), before_journals)


    def test_post_landed_cost_capitalizes_cost_and_preserves_source_history(self):
        from purchases.landed_cost_services import post_landed_cost
        purchase = self._purchase(document_number="PI-LC-POST-001")
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        movement = StockMovement.objects.get(reference=f"{purchase.document_number}:LINE:{line.pk}")
        original_cost = movement.unit_cost_afn
        original_journal_count = JournalEntry.objects.count()
        cost = create_landed_cost_draft(
            document_number="LC-POST-001", payee=self.supplier, cost_date=self.day,
            currency=self.afn, amount="10.00", exchange_rate="1", rate_date=self.day,
            category="FREIGHT", purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT, user=self.user,
            idempotency_key="lc-post-001",
        )
        posted = post_landed_cost(cost_document=cost, user=self.user)
        self.assertEqual(posted.status, LandedCostStatus.POSTED)
        self.assertIsNotNone(posted.journal_entry_id)
        self.assertEqual(posted.journal_entry.total_debit, Decimal("10.00"))
        self.assertEqual(posted.journal_entry.total_credit, Decimal("10.00"))
        self.assertEqual(posted.journal_entry.lines.get(account__code="1410").debit, Decimal("10.00"))
        self.assertEqual(posted.journal_entry.lines.get(account__code="2110").credit, Decimal("10.00"))
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("13.0000"))
        movement.refresh_from_db()
        self.assertEqual(movement.unit_cost_afn, original_cost)
        self.assertEqual(JournalEntry.objects.count(), original_journal_count + 1)
        self.assertEqual(post_landed_cost(cost_document=posted, user=self.user).pk, posted.pk)

    def test_post_landed_cost_reallocates_sold_portion_to_cogs(self):
        from accounting.models import Account
        from accounting.services import post_journal
        from inventory.services import issue_stock
        from purchases.landed_cost_services import post_landed_cost
        purchase = self._purchase(document_number="PI-LC-SOLD-001")
        post_purchase(purchase=purchase, user=self.user)
        reference = "ISSUE-LC-SOLD-001"
        issue = issue_stock(
            product=self.product, warehouse=self.warehouse, quantity=4,
            movement_date=self.day, reference=reference,
            description="Evidence sale issue", user=self.user,
            party=self.customer, idempotency_key="issue-lc-sold-001",
        )
        original_cogs = post_journal(
            number="JE-LC-SOLD-COGS", posting_date=self.day,
            description="Original COGS for evidence issue",
            lines=[
                {"account": Account.objects.get(code="5100"), "debit": Decimal("48.00"), "reference": reference},
                {"account": Account.objects.get(code="1410"), "credit": Decimal("48.00"), "reference": reference},
            ],
            source_type="SALES_COGS", source_id=reference, currency=self.afn,
            rate=Decimal("1.0000"), rate_date=self.day, created_by=self.user,
            idempotency_key="je-lc-sold-cogs",
        )
        cost = create_landed_cost_draft(
            document_number="LC-SOLD-001", payee=self.supplier, cost_date=self.day,
            currency=self.afn, amount="10.00", exchange_rate="1", rate_date=self.day,
            category="FREIGHT", purchase_line_ids=[purchase.lines.get().pk],
            allocation_method=LandedCostAllocationMethod.DIRECT, user=self.user,
            idempotency_key="lc-sold-001",
        )
        posted = post_landed_cost(cost_document=cost, user=self.user)
        adjustment = posted.valuation_adjustments.get(adjustment_type="SALES_ISSUE")
        self.assertEqual(adjustment.movement_id, issue.pk)
        self.assertEqual(adjustment.amount_afn, Decimal("4.00"))
        self.assertEqual(adjustment.journal_entry.lines.get(account__code="5100").debit, Decimal("4.00"))
        self.assertEqual(adjustment.journal_entry.lines.get(account__code="1410").credit, Decimal("4.00"))
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("13.0000"))
        with self.assertRaises(PostedImmutabilityError):
            type(adjustment).objects.filter(pk=adjustment.pk).update(amount_afn=Decimal("99.00"))
        with self.assertRaises(PostedImmutabilityError):
            type(adjustment).objects.filter(pk=adjustment.pk).delete()
        original_cogs.refresh_from_db()
        self.assertEqual(original_cogs.lines.get(account__code="5100").debit, Decimal("48.00"))


    def test_post_landed_cost_reclassifies_goods_in_transit_receipt(self):
        from goods_in_transit.models import GoodsInTransitLot
        from goods_in_transit.services import receive_transit
        from purchases.landed_cost_services import post_landed_cost
        purchase = self._purchase(
            document_number="PI-LC-TRANSIT-001", delivery_mode="IN_TRANSIT",
        )
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        lot = GoodsInTransitLot.objects.get(purchase_line=line)
        receipt = receive_transit(
            lot=lot, quantity=4, receipt_date=self.day, user=self.user,
            idempotency_key="lc-transit-receipt-001",
        )
        cost = create_landed_cost_draft(
            document_number="LC-TRANSIT-001", payee=self.supplier, cost_date=self.day,
            currency=self.afn, amount="10.00", exchange_rate="1", rate_date=self.day,
            category="FREIGHT", purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT, user=self.user,
            idempotency_key="lc-transit-001",
        )
        posted = post_landed_cost(cost_document=cost, user=self.user)
        receipt_adjustment = posted.valuation_adjustments.get(
            adjustment_type="TRANSIT_RECEIPT",
        )
        self.assertEqual(receipt_adjustment.movement_id, receipt.stock_movement_id)
        self.assertEqual(receipt_adjustment.amount_afn, Decimal("4.00"))
        self.assertEqual(receipt_adjustment.journal_entry.lines.get(account__code="1410").debit, Decimal("4.00"))
        self.assertEqual(receipt_adjustment.journal_entry.lines.get(account__code="1430").credit, Decimal("4.00"))
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("13.0000"))
        lot.refresh_from_db()
        self.assertEqual(lot.remaining_quantity, 6)


    def test_landed_cost_posted_before_transit_receipt_reclassifies_when_received(self):
        from goods_in_transit.models import GoodsInTransitLot
        from goods_in_transit.services import receive_transit
        from purchases.landed_cost_services import post_landed_cost
        purchase = self._purchase(
            document_number="PI-LC-TRANSIT-LATE-001", delivery_mode="IN_TRANSIT",
        )
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        lot = GoodsInTransitLot.objects.get(purchase_line=line)
        cost = create_landed_cost_draft(
            document_number="LC-TRANSIT-LATE-001", payee=self.supplier, cost_date=self.day,
            currency=self.afn, amount="10.00", exchange_rate="1", rate_date=self.day,
            category="FREIGHT", purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT, user=self.user,
            idempotency_key="lc-transit-late-001",
        )
        posted = post_landed_cost(cost_document=cost, user=self.user)
        self.assertEqual(posted.valuation_adjustments.count(), 0)
        receipt = receive_transit(
            lot=lot, quantity=4, receipt_date=self.day, user=self.user,
            idempotency_key="lc-transit-late-receipt-001",
        )
        adjustment = posted.valuation_adjustments.get(adjustment_type="TRANSIT_RECEIPT")
        self.assertEqual(adjustment.movement_id, receipt.stock_movement_id)
        self.assertEqual(adjustment.amount_afn, Decimal("4.00"))
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("13.0000"))

    def test_landed_cost_posted_before_transit_sale_reallocates_future_sale_cogs(self):
        from goods_in_transit.models import GoodsInTransitLot
        from purchases.landed_cost_services import post_landed_cost
        from sales.services import create_sale, finalize_sale
        from uom.models import UnitOfMeasure
        purchase = self._purchase(
            document_number="PI-LC-TRANSIT-SALE-001", delivery_mode="IN_TRANSIT",
        )
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        lot = GoodsInTransitLot.objects.get(purchase_line=line)
        cost = create_landed_cost_draft(
            document_number="LC-TRANSIT-SALE-001", payee=self.supplier, cost_date=self.day,
            currency=self.afn, amount="10.00", exchange_rate="1", rate_date=self.day,
            category="FREIGHT", purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT, user=self.user,
            idempotency_key="lc-transit-sale-001",
        )
        posted = post_landed_cost(cost_document=cost, user=self.user)
        sale = create_sale(
            customer=self.customer, sale_date=self.day, currency=self.afn,
            channel="WHOLESALE", payment_mode="CREDIT",
            lines=[{
                "product": self.product, "unit": UnitOfMeasure.objects.get(name="Purchase Unit"),
                "quantity": 3, "unit_price": "20", "transit_lot": lot,
            }],
            user=self.user, document_number="SI-LC-TRANSIT-SALE-001",
        )
        finalize_sale(sale=sale, user=self.user)
        adjustment = posted.valuation_adjustments.get(adjustment_type="TRANSIT_SALE")
        self.assertEqual(adjustment.source_reference, f"TRANSIT-SALE:{sale.lines.get().pk}")
        self.assertEqual(adjustment.amount_afn, Decimal("3.00"))
        self.assertEqual(adjustment.journal_entry.lines.get(account__code="5100").debit, Decimal("3.00"))
        self.assertEqual(adjustment.journal_entry.lines.get(account__code="1430").credit, Decimal("3.00"))


    def test_post_landed_cost_replays_transfer_and_destination_cogs(self):
        from accounting.models import Account
        from accounting.services import post_journal
        from inventory.services import issue_stock, transfer_stock
        from purchases.landed_cost_services import post_landed_cost
        destination = create_warehouse(name="Landed Cost Destination", user=self.user)
        WarehouseInventoryAccount.objects.create(
            warehouse=destination, account_id=self._account_id("1420"),
        )
        purchase = self._purchase(document_number="PI-LC-TRANSFER-001")
        post_purchase(purchase=purchase, user=self.user)
        out_movement, in_movement = transfer_stock(
            product=self.product, source_warehouse=self.warehouse,
            destination_warehouse=destination, quantity=4,
            movement_date=self.day, reference="TR-LC-TRANSFER-001",
            description="Landed-cost transfer evidence", user=self.user,
            idempotency_key="tr-lc-transfer-001",
        )
        issue = issue_stock(
            product=self.product, warehouse=destination, quantity=2,
            movement_date=self.day, reference="ISSUE-LC-DEST-001",
            description="Destination sale issue", user=self.user,
            party=self.customer, idempotency_key="issue-lc-dest-001",
        )
        post_journal(
            number="JE-LC-DEST-COGS", posting_date=self.day,
            description="Original destination COGS",
            lines=[
                {"account": Account.objects.get(code="5100"), "debit": Decimal("24.00"), "reference": issue.reference},
                {"account": Account.objects.get(code="1420"), "credit": Decimal("24.00"), "reference": issue.reference},
            ],
            source_type="SALES_COGS", source_id=issue.reference, currency=self.afn,
            rate=Decimal("1.0000"), rate_date=self.day, created_by=self.user,
            idempotency_key="je-lc-dest-cogs",
        )
        cost = create_landed_cost_draft(
            document_number="LC-TRANSFER-001", payee=self.supplier, cost_date=self.day,
            currency=self.afn, amount="10.00", exchange_rate="1", rate_date=self.day,
            category="FREIGHT", purchase_line_ids=[purchase.lines.get().pk],
            allocation_method=LandedCostAllocationMethod.DIRECT, user=self.user,
            idempotency_key="lc-transfer-001",
        )
        posted = post_landed_cost(cost_document=cost, user=self.user)
        transfer_adjustment = posted.valuation_adjustments.get(adjustment_type="WAREHOUSE_TRANSFER")
        cogs_adjustment = posted.valuation_adjustments.get(
            adjustment_type="SALES_ISSUE", movement=issue,
        )
        self.assertEqual(transfer_adjustment.movement_id, out_movement.pk)
        self.assertEqual(transfer_adjustment.amount_afn, Decimal("4.00"))
        self.assertEqual(transfer_adjustment.journal_entry.lines.get(account__code="1420").debit, Decimal("4.00"))
        self.assertEqual(transfer_adjustment.journal_entry.lines.get(account__code="1410").credit, Decimal("4.00"))
        self.assertEqual(cogs_adjustment.amount_afn, Decimal("2.00"))
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("13.0000"))
        self.assertEqual(avco_for(self.product, destination), Decimal("13.0000"))
        out_movement.refresh_from_db()
        in_movement.refresh_from_db()
        self.assertEqual(out_movement.unit_cost_afn, Decimal("12.0000"))
        self.assertEqual(in_movement.unit_cost_afn, Decimal("12.0000"))


    def test_landed_cost_post_fails_closed_and_rolls_back_on_unmapped_stock_outflow(self):
        from inventory.services import adjust_stock_out
        from purchases.landed_cost_services import LandedCostPostingError, post_landed_cost
        purchase = self._purchase(document_number="PI-LC-UNMAPPED-OUT-001")
        post_purchase(purchase=purchase, user=self.user)
        adjust_stock_out(
            product=self.product, warehouse=self.warehouse, quantity=1,
            movement_date=self.day, reference="ADJ-OUT-LC-001",
            description="Unmapped adjustment outflow", user=self.user,
        )
        line = purchase.lines.get()
        cost = create_landed_cost_draft(
            document_number="LC-UNMAPPED-OUT-001", payee=self.supplier, cost_date=self.day,
            currency=self.afn, amount="10.00", exchange_rate="1", rate_date=self.day,
            category="FREIGHT", purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT, user=self.user,
            idempotency_key="lc-unmapped-out-001",
        )
        before_journals = JournalEntry.objects.count()
        with self.assertRaises(LandedCostPostingError):
            post_landed_cost(cost_document=cost, user=self.user)
        cost.refresh_from_db()
        self.assertEqual(cost.status, LandedCostStatus.DRAFT)
        self.assertIsNone(cost.journal_entry_id)
        self.assertEqual(JournalEntry.objects.count(), before_journals)
        self.assertEqual(cost.valuation_adjustments.count(), 0)


    def test_insurance_is_rejected_by_landed_cost_contract(self):
        purchase = self._purchase(document_number="PI-LC-NO-INSURANCE-001")
        post_purchase(purchase=purchase, user=self.user)
        before_documents = LandedCostDocument.objects.count()
        before_journals = JournalEntry.objects.count()
        with self.assertRaises(LandedCostValidationError):
            create_landed_cost_draft(
                document_number="LC-NO-INSURANCE-001", payee=self.supplier,
                cost_date=self.day, currency=self.afn, amount="10.00",
                exchange_rate="1", rate_date=self.day, category="Cargo Insurance",
                purchase_line_ids=[purchase.lines.get().pk],
                allocation_method=LandedCostAllocationMethod.DIRECT, user=self.user,
                idempotency_key="lc-no-insurance-001",
            )
        self.assertEqual(LandedCostDocument.objects.count(), before_documents)
        self.assertEqual(JournalEntry.objects.count(), before_journals)


    def test_sequential_late_costs_replay_prior_layers_before_reallocating_cogs(self):
        from accounting.models import Account
        from accounting.services import post_journal
        from inventory.services import issue_stock
        from purchases.landed_cost_services import post_landed_cost

        purchase = self._purchase(document_number="PI-LC-MULTI-001")
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        issue = issue_stock(
            product=self.product, warehouse=self.warehouse, quantity=4,
            movement_date=self.day, reference="ISSUE-LC-MULTI-001",
            description="Sequential landed-cost evidence", user=self.user,
            party=self.customer, idempotency_key="issue-lc-multi-001",
        )
        original_cogs = post_journal(
            number="JE-LC-MULTI-COGS", posting_date=self.day,
            description="Original COGS before late costs",
            lines=[
                {"account": Account.objects.get(code="5100"), "debit": Decimal("48.00"), "reference": issue.reference},
                {"account": Account.objects.get(code="1410"), "credit": Decimal("48.00"), "reference": issue.reference},
            ],
            source_type="SALES_COGS", source_id=issue.reference, currency=self.afn,
            rate=Decimal("1.0000"), rate_date=self.day, created_by=self.user,
            idempotency_key="je-lc-multi-cogs",
        )

        def post_cost(number, amount, key):
            draft = create_landed_cost_draft(
                document_number=number, payee=self.supplier, cost_date=self.day,
                currency=self.afn, amount=amount, exchange_rate="1",
                rate_date=self.day, category="FREIGHT",
                purchase_line_ids=[line.pk],
                allocation_method=LandedCostAllocationMethod.DIRECT, user=self.user,
                idempotency_key=key,
            )
            return post_landed_cost(cost_document=draft, user=self.user)

        first = post_cost("LC-MULTI-001", "10.00", "lc-multi-001")
        first_adjustment = first.valuation_adjustments.get(
            adjustment_type="SALES_ISSUE", movement=issue,
        )
        self.assertEqual(first_adjustment.amount_afn, Decimal("4.00"))
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("13.0000"))

        second = post_cost("LC-MULTI-002", "20.00", "lc-multi-002")
        second_adjustment = second.valuation_adjustments.get(
            adjustment_type="SALES_ISSUE", movement=issue,
        )
        self.assertEqual(second_adjustment.amount_afn, Decimal("8.00"))
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("15.0000"))

        # The original posted journal and Kardex remain immutable; adjustments
        # account for both deltas: original COGS 48 + 4 + 8 = 60, and 6 units
        # remain at the final AVCO of 15 (= 90 inventory value).
        original_cogs.refresh_from_db()
        self.assertEqual(original_cogs.lines.get(account__code="5100").debit, Decimal("48.00"))
        self.assertEqual(issue.unit_cost_afn, Decimal("12.0000"))
        self.assertEqual(
            first_adjustment.journal_entry.lines.get(account__code="5100").debit,
            Decimal("4.00"),
        )
        self.assertEqual(
            second_adjustment.journal_entry.lines.get(account__code="5100").debit,
            Decimal("8.00"),
        )
        self.assertEqual(
            first_adjustment.journal_entry.total_debit + second_adjustment.journal_entry.total_debit,
            Decimal("12.00"),
        )


    def test_late_landed_cost_reconciles_purchase_return_supplier_claim(self):
        from purchases.services import post_purchase_return
        from purchases.landed_cost_services import post_landed_cost

        purchase = self._purchase(document_number="PI-LC-RETURN-001")
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        source = StockMovement.objects.get(reference=f"{purchase.document_number}:LINE:{line.pk}")
        returned = post_purchase_return(
            purchase=purchase, product=self.product, quantity=2,
            source_movement=source, return_date=self.day,
            reason="Damaged units returned to supplier", user=self.user,
            document_number="PRTN-LC-RETURN-001",
            idempotency_key="prtn-lc-return-001",
        )

        cost = create_landed_cost_draft(
            document_number="LC-RETURN-001", payee=self.supplier,
            cost_date=self.day, currency=self.afn, amount="10.00",
            exchange_rate="1", rate_date=self.day, category="FREIGHT",
            purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT,
            user=self.user, idempotency_key="lc-return-001",
        )
        posted_cost = post_landed_cost(cost_document=cost, user=self.user)

        adjustment = posted_cost.valuation_adjustments.get(
            adjustment_type="PURCHASE_RETURN",
            movement=returned.inventory_return.return_movement,
        )
        self.assertEqual(adjustment.journal_entry.total_debit, Decimal("2.00"))
        self.assertEqual(adjustment.journal_entry.total_credit, Decimal("2.00"))
        self.assertEqual(
            adjustment.journal_entry.lines.get(account__code="2110").debit,
            Decimal("2.00"),
        )
        self.assertEqual(
            adjustment.journal_entry.lines.get(account__code="1410").credit,
            Decimal("2.00"),
        )
        # 10 units received at AFN 12, 2 returned, and AFN 10 freight
        # allocated over the original 10 units: remaining stock is 8 × 13.
        self.assertEqual(stock_for(self.product, self.warehouse), 8)
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("13.0000"))
        # Posted purchase-return journal is not rewritten by the later cost.
        returned.refresh_from_db()
        self.assertEqual(
            returned.journal_entry.lines.get(account__code="2110").debit,
            Decimal("24.00"),
        )


    def test_late_cost_isolated_to_explicit_receipt_when_product_has_multiple_receipts(self):
        from purchases.landed_cost_services import post_landed_cost

        first = self._purchase(document_number="PI-LC-MULTI-RECEIPT-A")
        post_purchase(purchase=first, user=self.user)
        first_line = first.lines.get()

        second = self._purchase(
            document_number="PI-LC-MULTI-RECEIPT-B",
            lines=[{"product": self.product, "quantity": 10, "unit_price": "20.00"}],
        )
        post_purchase(purchase=second, user=self.user)
        second_line = second.lines.get()

        cost = create_landed_cost_draft(
            document_number="LC-MULTI-RECEIPT-A", payee=self.supplier,
            cost_date=self.day, currency=self.afn, amount="10.00",
            exchange_rate="1", rate_date=self.day, category="FREIGHT",
            purchase_line_ids=[first_line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT,
            user=self.user, idempotency_key="lc-multi-receipt-a",
        )
        posted = post_landed_cost(cost_document=cost, user=self.user)

        self.assertEqual(list(posted.allocations.values_list("purchase_line_id", flat=True)), [first_line.pk])
        self.assertNotEqual(first_line.pk, second_line.pk)
        self.assertEqual(posted.allocations.get().afn_amount, Decimal("10.00"))
        # Chronological AVCO applies the extra AFN 1/unit to receipt A before
        # receipt B enters the same product/warehouse pool: (130 + 200) / 20.
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("16.5000"))
        self.assertEqual(stock_for(self.product, self.warehouse), 20)

    def test_late_cost_after_sales_return_reallocates_net_cogs_and_inventory(self):
        from purchases.landed_cost_services import post_landed_cost
        from sales.returns_services import create_sales_return
        from sales.services import (
            create_sale, finalize_sale, finalize_warehouse_check, prepare_warehouse_check,
        )

        purchase = self._purchase(document_number="PI-LC-SALES-RETURN-001")
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()

        sale = create_sale(
            customer=self.customer, sale_date=self.day, currency=self.afn,
            channel="WHOLESALE", payment_mode="CREDIT",
            lines=[{
                "product": self.product, "unit": self.product.primary_uom,
                "quantity": 4, "unit_price": "20.00",
            }],
            user=self.user, document_number="SI-LC-SALES-RETURN-001",
        )
        finalize_sale(sale=sale, user=self.user)
        sale_line = sale.lines.get()
        check = prepare_warehouse_check(
            sale_line=sale_line, warehouse=self.warehouse, quantity=4,
            number="WC-LC-SALES-RETURN-001",
        )
        finalize_warehouse_check(check=check)

        returned = create_sales_return(
            sale_line=sale_line, warehouse=self.warehouse, quantity=2,
            return_date=self.day, reason="Two units returned before freight invoice",
            user=self.user, document_number="SR-LC-SALES-RETURN-001",
            idempotency_key="sr-lc-sales-return-001",
        )
        source_issue = StockMovement.objects.get(reference="WC-LC-SALES-RETURN-001", movement_type=MovementType.SALES_ISSUE)
        original_return_cogs = returned.cogs_journal.lines.get(account__code="5100").credit

        cost = create_landed_cost_draft(
            document_number="LC-SALES-RETURN-001", payee=self.supplier,
            cost_date=self.day, currency=self.afn, amount="10.00",
            exchange_rate="1", rate_date=self.day, category="FREIGHT",
            purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT,
            user=self.user, idempotency_key="lc-sales-return-001",
        )
        posted = post_landed_cost(cost_document=cost, user=self.user)

        issue_adjustment = posted.valuation_adjustments.get(
            adjustment_type="SALES_ISSUE", movement=source_issue,
        )
        return_adjustment = posted.valuation_adjustments.get(
            adjustment_type="SALES_RETURN",
            movement=returned.inventory_return.return_movement,
        )
        self.assertEqual(issue_adjustment.amount_afn, Decimal("4.00"))
        self.assertEqual(return_adjustment.amount_afn, Decimal("2.00"))
        self.assertEqual(issue_adjustment.journal_entry.lines.get(account__code="5100").debit, Decimal("4.00"))
        self.assertEqual(return_adjustment.journal_entry.lines.get(account__code="5100").credit, Decimal("2.00"))
        self.assertEqual(original_return_cogs, Decimal("24.00"))
        self.assertEqual(stock_for(self.product, self.warehouse), 8)
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("13.0000"))

    def test_late_cost_posting_in_closed_period_is_atomic(self):
        from purchases.landed_cost_services import post_landed_cost

        purchase = self._purchase(document_number="PI-LC-CLOSED-001")
        post_purchase(purchase=purchase, user=self.user)
        period = create_period(
            name="Closed Landed Cost Period", start_date=self.day,
            end_date=self.day, user=self.user,
        )
        close_period(period, user=self.user, reason="Phase 11 closed-period evidence")
        cost = create_landed_cost_draft(
            document_number="LC-CLOSED-001", payee=self.supplier,
            cost_date=self.day, currency=self.afn, amount="10.00",
            exchange_rate="1", rate_date=self.day, category="FREIGHT",
            purchase_line_ids=[purchase.lines.get().pk],
            allocation_method=LandedCostAllocationMethod.DIRECT,
            user=self.user, idempotency_key="lc-closed-001",
        )
        before_journals = JournalEntry.objects.count()
        with self.assertRaises(PeriodValidationError):
            post_landed_cost(cost_document=cost, user=self.user)

        cost.refresh_from_db()
        self.assertEqual(cost.status, LandedCostStatus.DRAFT)
        self.assertIsNone(cost.journal_entry_id)
        self.assertEqual(cost.valuation_adjustments.count(), 0)
        self.assertEqual(JournalEntry.objects.count(), before_journals)


    def test_late_cost_after_entire_receipt_was_sold_reclassifies_all_cost_to_cogs(self):
        from accounting.models import Account
        from accounting.services import post_journal
        from inventory.services import issue_stock
        from purchases.landed_cost_services import post_landed_cost

        purchase = self._purchase(document_number="PI-LC-FULLY-SOLD-001")
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        issue = issue_stock(
            product=self.product, warehouse=self.warehouse, quantity=10,
            movement_date=self.day, reference="ISSUE-LC-FULLY-SOLD-001",
            description="Entire source receipt consumed before late freight",
            user=self.user, party=self.customer, idempotency_key="issue-lc-fully-sold-001",
        )
        original_cogs = post_journal(
            number="JE-LC-FULLY-SOLD-COGS", posting_date=self.day,
            description="Original COGS for fully consumed receipt",
            lines=[
                {"account": Account.objects.get(code="5100"), "debit": Decimal("120.00"), "reference": issue.reference},
                {"account": Account.objects.get(code="1410"), "credit": Decimal("120.00"), "reference": issue.reference},
            ],
            source_type="SALES_COGS", source_id=issue.reference, currency=self.afn,
            rate=Decimal("1.0000"), rate_date=self.day, created_by=self.user,
            idempotency_key="je-lc-fully-sold-cogs",
        )
        cost = create_landed_cost_draft(
            document_number="LC-FULLY-SOLD-001", payee=self.supplier,
            cost_date=self.day, currency=self.afn, amount="10.00",
            exchange_rate="1", rate_date=self.day, category="FREIGHT",
            purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT,
            user=self.user, idempotency_key="lc-fully-sold-001",
        )
        posted = post_landed_cost(cost_document=cost, user=self.user)
        adjustment = posted.valuation_adjustments.get(
            adjustment_type="SALES_ISSUE", movement=issue,
        )
        self.assertEqual(adjustment.amount_afn, Decimal("10.00"))
        self.assertEqual(adjustment.journal_entry.lines.get(account__code="5100").debit, Decimal("10.00"))
        self.assertEqual(stock_for(self.product, self.warehouse), 0)
        original_cogs.refresh_from_db()
        self.assertEqual(original_cogs.lines.get(account__code="5100").debit, Decimal("120.00"))
        self.assertEqual(issue.unit_cost_afn, Decimal("12.0000"))

    def test_late_cost_after_transit_sale_return_reconciles_transit_inventory_and_cogs(self):
        from goods_in_transit.models import GoodsInTransitLot
        from purchases.landed_cost_services import post_landed_cost
        from sales.returns_services import create_sales_return
        from sales.services import (
            create_sale, finalize_sale, finalize_warehouse_check, prepare_warehouse_check,
        )

        purchase = self._purchase(
            document_number="PI-LC-TRANSIT-RETURN-001", delivery_mode="IN_TRANSIT",
        )
        post_purchase(purchase=purchase, user=self.user)
        line = purchase.lines.get()
        lot = GoodsInTransitLot.objects.get(purchase_line=line)
        sale = create_sale(
            customer=self.customer, sale_date=self.day, currency=self.afn,
            channel="WHOLESALE", payment_mode="CREDIT",
            lines=[{
                "product": self.product, "unit": self.product.primary_uom,
                "quantity": 3, "unit_price": "20.00", "transit_lot": lot,
            }],
            user=self.user, document_number="SI-LC-TRANSIT-RETURN-001",
        )
        finalize_sale(sale=sale, user=self.user)
        sale_line = sale.lines.get()
        check = prepare_warehouse_check(
            sale_line=sale_line, warehouse=self.warehouse, quantity=3,
            number="WC-LC-TRANSIT-RETURN-001",
        )
        finalize_warehouse_check(check=check, user=self.user)
        returned = create_sales_return(
            sale_line=sale_line, warehouse=self.warehouse, quantity=1,
            return_date=self.day, reason="Transit goods physically returned",
            user=self.user, document_number="SR-LC-TRANSIT-RETURN-001",
            idempotency_key="sr-lc-transit-return-001",
        )

        cost = create_landed_cost_draft(
            document_number="LC-TRANSIT-RETURN-001", payee=self.supplier,
            cost_date=self.day, currency=self.afn, amount="10.00",
            exchange_rate="1", rate_date=self.day, category="FREIGHT",
            purchase_line_ids=[line.pk],
            allocation_method=LandedCostAllocationMethod.DIRECT,
            user=self.user, idempotency_key="lc-transit-return-001",
        )
        posted = post_landed_cost(cost_document=cost, user=self.user)
        sale_adjustment = posted.valuation_adjustments.get(
            adjustment_type="TRANSIT_SALE",
            source_reference=f"TRANSIT-SALE:{sale_line.pk}",
        )
        return_adjustment = posted.valuation_adjustments.get(
            adjustment_type="SALES_RETURN",
            movement=returned.return_movement,
        )
        self.assertEqual(sale_adjustment.amount_afn, Decimal("3.00"))
        self.assertEqual(return_adjustment.amount_afn, Decimal("1.00"))
        self.assertEqual(lot.remaining_quantity, 7)
        self.assertEqual(stock_for(self.product, self.warehouse), 1)
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("13.0000"))
        self.assertEqual(
            sale_adjustment.journal_entry.lines.get(account__code="5100").debit,
            Decimal("3.00"),
        )
        self.assertEqual(
            return_adjustment.journal_entry.lines.get(account__code="5100").credit,
            Decimal("1.00"),
        )
