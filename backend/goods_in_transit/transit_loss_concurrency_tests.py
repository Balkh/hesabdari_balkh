"""PostgreSQL-only concurrency regression for transit loss finalization."""
import threading
from datetime import date
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from accounting.coa import seed_chart_of_accounts
from accounting.models import Account, JournalEntry
from currencies.models import Currency
from inventory.models import WarehouseInventoryAccount
from parties.services import create_party
from categories.services import create_category
from products.services import create_product
from purchases.models import PurchaseDeliveryMode
from purchases.services import create_purchase, post_purchase
from uom.services import create_uom
from warehouses.services import create_warehouse

from .models import GoodsInTransitLot, TransitLossEvent, TransitLossValuationAdjustment
from .services import receive_transit, record_transit_loss, complete_transit_purchase


@skipUnless(connection.vendor == "postgresql", "Row-lock concurrency is verified on PostgreSQL")
class TransitLossConcurrentPostingTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        seed_chart_of_accounts()
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        self.user = get_user_model().objects.create_user("loss-conc-user", password="x")
        category = create_category(name="Loss Conc Category", user=self.user)
        unit = create_uom(name="Loss Conc Unit", user=self.user)
        self.product = create_product(
            code="LV-CONC-1", name="Loss Conc Product", name_fa="محصول",
            category=category, primary_uom=unit, user=self.user,
        )
        self.supplier = create_party(name="Loss Conc Supplier", is_supplier=True, user=self.user)
        self.warehouse = create_warehouse(name="Loss Conc Warehouse", user=self.user)
        WarehouseInventoryAccount.objects.create(
            warehouse=self.warehouse, account=Account.objects.get(code="1410"),
        )
        self.day = date(2026, 2, 1)
        purchase = create_purchase(
            supplier=self.supplier, purchase_date=self.day, currency=self.afn,
            warehouse=self.warehouse,
            lines=[{"product": self.product, "quantity": 100, "unit_price": "100"}],
            rate="1", rate_date=self.day,
            delivery_mode=PurchaseDeliveryMode.IN_TRANSIT,
            user=self.user, document_number="PI-LV-CONC-001",
        )
        post_purchase(purchase=purchase, user=self.user)
        self.lot = GoodsInTransitLot.objects.get(purchase_line=purchase.lines.get())
        receive_transit(lot=self.lot, quantity=98, receipt_date=date(2026, 2, 2),
                        user=self.user, idempotency_key="lvconc-r1")
        complete_transit_purchase(purchase=purchase, completion_date=date(2026, 2, 2),
            reason="All goods for this purchase invoice arrived; trip receipts consolidated.",
            idempotency_key="lvconc-complete", user=self.user)

    def _attempt(self, key, results):
        def run():
            close_old_connections()
            try:
                event = record_transit_loss(
                    lot=self.lot, quantity=2, loss_date=date(2026, 2, 4),
                    reason="Confirmed transport wastage",
                    idempotency_key=key, user=self.user,
                )
                results.append(("ok", event.pk))
            except Exception as exc:  # noqa: BLE001 - captured for assertion
                results.append(("error", type(exc).__name__))
            finally:
                close_old_connections()
        return run

    def test_concurrent_duplicate_finalization_posts_once(self):
        results = []
        threads = [threading.Thread(target=self._attempt("lvconc-loss", results))
                   for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(sorted(kind for kind, _ in results), ["ok", "ok"])
        self.assertEqual(len({value for _, value in results}), 1)
        self.assertEqual(TransitLossEvent.objects.count(), 1)
        adjustments = TransitLossValuationAdjustment.objects.count()
        self.assertGreater(adjustments, 0)
        journals = JournalEntry.objects.filter(
            source_type="TRANSIT_LOSS_VALUATION_ADJUSTMENT").count()
        self.assertEqual(journals, adjustments)

    def test_concurrent_conflicting_finalization_posts_once(self):
        results = []
        threads = [
            threading.Thread(target=self._attempt("lvconc-loss-a", results)),
            threading.Thread(target=self._attempt("lvconc-loss-b", results)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(sorted(kind for kind, _ in results), ["error", "ok"])
        self.assertEqual(TransitLossEvent.objects.count(), 1)
