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

from .models import Purchase, PurchaseLine, PurchaseStatus
from .services import PurchaseValidationError, create_purchase, post_purchase, update_purchase, update_purchase_line


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
        self.assertEqual(journal.lines.get(account__code="1410").debit, Decimal("9500.00"))
        self.assertEqual(journal.lines.get(account__code="6200").debit, Decimal("1000.00"))
        self.assertEqual(journal.lines.get(account__code="2110").credit, Decimal("10500.00"))
        line = purchase.lines.get()
        movement = StockMovement.objects.get(reference=f"{purchase.document_number}:LINE:{line.pk}")
        self.assertEqual(movement.unit_cost, Decimal("95.0000"))
        self.assertEqual(movement.unit_cost_afn, Decimal("95.0000"))
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("95.0000"))
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
        self.assertEqual(movement.unit_cost, Decimal("95.0000"))
        self.assertEqual(movement.unit_cost_afn, Decimal("6650.0000"))
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
        self.assertEqual(movement.unit_cost, Decimal("87.5000"))
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
                {"product": self.product, "quantity": 10, "unit_price": "100"},
                {"product": self.product2, "quantity": 30, "unit_price": "100"},
            ],
        )
        lines = list(purchase.lines.all())
        self.assertEqual(purchase.subtotal, Decimal("4000.00"))
        self.assertEqual(sum((line.discount_allocated for line in lines), Decimal("0")), Decimal("40.00"))
        self.assertEqual([line.net_total for line in lines], [Decimal("990.00"), Decimal("2970.00")])
        self.assertEqual(purchase.total, Decimal("3985.00"))
        self.assertEqual(purchase.status, PurchaseStatus.DRAFT)
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
                {"product": self.product, "quantity": 2, "unit_price": "10"},
                {"product": self.product, "quantity": 3, "unit_price": "20"},
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
        self.assertEqual([movement.unit_cost for movement in movements], [Decimal("8.7500"), Decimal("17.5000")])
        journal = JournalEntry.objects.get(source_type="PURCHASE", source_id=purchase.document_number)
        payable_line = journal.lines.get(account__code="2110")
        self.assertEqual(payable_line.party_ledger_attribution.party_id, self.supplier.pk)
        post_event = AuditEvent.objects.get(entity="Purchase", entity_id=purchase.pk, action="POST")
        self.assertEqual(post_event.new_state["journal_entry_id"], journal.pk)
        self.assertEqual(post_event.new_state["stock_movement_ids"], [movement.pk for movement in movements])
        self.assertEqual(post_event.new_state["stock_movement_references"], [movement.reference for movement in movements])

    def test_freight_is_expense_and_not_inventory_cost(self):
        purchase = self._purchase(freight="30")
        post_purchase(purchase=purchase, user=self.user)
        journal = JournalEntry.objects.get(source_type="PURCHASE", source_id=purchase.document_number)
        self.assertEqual(journal.lines.get(account__code="6200").debit, Decimal("30.00"))
        self.assertEqual(journal.lines.get(account__code="1410").debit, Decimal("120.00"))
        self.assertEqual(stock_for(self.product, self.warehouse), 10)
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("12.0000"))

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
                {"product": self.product, "quantity": 2, "unit_price": "10"},
                {"product": self.product, "quantity": 3, "unit_price": "20"},
                {"product": self.product2, "quantity": 4, "unit_price": "5"},
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
        self.assertEqual(JournalLine.objects.count(), 3)
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
