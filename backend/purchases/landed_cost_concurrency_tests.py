"""PostgreSQL-only row-lock regression for concurrent landed-cost posting."""
import threading
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from accounting.coa import seed_chart_of_accounts
from accounting.models import Account, JournalEntry
from accounting.services import post_journal
from categories.services import create_category
from currencies.models import Currency
from inventory.models import StockMovement, WarehouseInventoryAccount
from inventory.services import issue_stock
from inventory.stock import avco_for
from parties.services import create_party
from products.services import create_product
from purchases.landed_cost_posting import post_landed_cost
from purchases.landed_cost_services import create_landed_cost_draft
from purchases.models import (
    LandedCostAllocationMethod, LandedCostDocument, LandedCostStatus,
    LandedCostValuationAdjustment,
)
from purchases.services import create_purchase, post_purchase
from uom.services import create_uom
from warehouses.services import create_warehouse


@skipUnless(connection.vendor == "postgresql", "Row-lock concurrency is verified on PostgreSQL")
class LandedCostConcurrentPostingTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        seed_chart_of_accounts()
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        self.user = get_user_model().objects.create_user("landed-cost-concurrency-user", password="x")
        category = create_category(name="Concurrency Category", user=self.user)
        unit = create_uom(name="Concurrency Unit", user=self.user)
        self.product = create_product(
            code="LC-CONC-1", name="Concurrency Product", name_fa="محصول همزمان",
            category=category, primary_uom=unit, user=self.user,
        )
        self.supplier = create_party(name="Concurrency Supplier", is_supplier=True, user=self.user)
        self.customer = create_party(name="Concurrency Customer", is_customer=True, user=self.user)
        self.warehouse = create_warehouse(name="Concurrency Warehouse", user=self.user)
        WarehouseInventoryAccount.objects.create(
            warehouse=self.warehouse, account=Account.objects.get(code="1410"),
        )
        from datetime import date
        self.day = date(2026, 1, 15)
        purchase = create_purchase(
            supplier=self.supplier, purchase_date=self.day, currency=self.afn,
            warehouse=self.warehouse,
            lines=[{"product": self.product, "quantity": 10, "unit_price": "12.00"}],
            user=self.user, document_number="PI-LC-CONC-001",
        )
        post_purchase(purchase=purchase, user=self.user)
        issue = issue_stock(
            product=self.product, warehouse=self.warehouse, quantity=4,
            movement_date=self.day, reference="ISSUE-LC-CONC-001",
            description="Concurrent landed-cost posting COGS basis",
            user=self.user, party=self.customer, idempotency_key="issue-lc-conc-001",
        )
        post_journal(
            number="JE-LC-CONC-COGS", posting_date=self.day,
            description="Original COGS for concurrency test",
            lines=[
                {"account": Account.objects.get(code="5100"), "debit": "48.00", "reference": issue.reference},
                {"account": Account.objects.get(code="1410"), "credit": "48.00", "reference": issue.reference},
            ],
            source_type="SALES_COGS", source_id=issue.reference, currency=self.afn,
            rate="1.0000", rate_date=self.day, created_by=self.user,
            idempotency_key="je-lc-conc-cogs",
        )
        self.issue = StockMovement.objects.get(pk=issue.pk)
        self.cost = create_landed_cost_draft(
            document_number="LC-CONC-001", payee=self.supplier,
            cost_date=self.day, currency=self.afn, amount="10.00",
            exchange_rate="1", rate_date=self.day, category="FREIGHT",
            purchase_line_ids=[purchase.lines.get().pk],
            allocation_method=LandedCostAllocationMethod.DIRECT,
            user=self.user, idempotency_key="lc-conc-001",
        )

    def test_concurrent_posting_creates_one_source_and_one_adjustment(self):
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        outcomes = []
        errors = []

        def post_in_worker():
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                actor = get_user_model().objects.get(pk=self.user.pk)
                result = post_landed_cost(cost_document=self.cost.pk, user=actor)
                with lock:
                    outcomes.append((result.pk, result.journal_entry_id))
            except Exception as exc:  # collected and asserted in the main thread
                with lock:
                    errors.append(repr(exc))
            finally:
                close_old_connections()

        workers = [threading.Thread(target=post_in_worker) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=90)

        self.assertFalse(any(worker.is_alive() for worker in workers), "Posting thread did not finish")
        self.assertEqual(errors, [])
        self.assertEqual(len(outcomes), 2)
        self.assertEqual({row[0] for row in outcomes}, {self.cost.pk})
        self.assertEqual(len({row[1] for row in outcomes}), 1)

        self.cost.refresh_from_db()
        self.issue.refresh_from_db()
        self.assertEqual(self.cost.status, LandedCostStatus.POSTED)
        self.assertEqual(
            JournalEntry.objects.filter(
                source_type="LANDED_COST", source_id=self.cost.document_number,
            ).count(),
            1,
        )
        self.assertEqual(
            LandedCostValuationAdjustment.objects.filter(
                cost_document=self.cost, adjustment_type="SALES_ISSUE",
            ).count(),
            1,
        )
        self.assertEqual(self.cost.valuation_adjustments.count(), 1)
        self.assertEqual(self.issue.unit_cost_afn, Decimal("12.0000"))
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("13.0000"))
