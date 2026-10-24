"""Invoice-time COGS / warehouse-allocation regression evidence (Phase 8).

Owner contract: docs/phase-8-invoice-time-cogs-allocation-contract.md
Ordinary stock issues + COGS post at invoice finalization per explicit
SaleLine warehouse allocation; Warehouse Check releases custody only.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounting.balances import account_balance
from accounting.coa import seed_chart_of_accounts
from accounting.models import Account, JournalEntry
from categories.services import create_category
from currencies.models import Currency
from customer_custody.services import custody_balance
from customer_custody.models import CustomerOwnershipEntitlement
from inventory.models import StockMovement
from inventory.services import assign_warehouse_account, receive_stock
from inventory.stock import stock_for
from parties.services import create_party
from products.services import create_product
from uom.services import create_uom
from warehouses.services import create_warehouse

from .models import PaymentMode, SalesChannel
from .services import (
    SalesValidationError, create_sale, finalize_sale,
    finalize_warehouse_check, prepare_warehouse_check,
)


class InvoiceTimeCogsAllocationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        seed_chart_of_accounts()

    def setUp(self):
        category = create_category(name="Alloc Category")
        self.unit = create_uom(name="Alloc Unit")
        self.product = create_product(code="ALLOC-1", name="Alloc Product", name_fa="محصول تخصیص", category=category, primary_uom=self.unit)
        self.customer = create_party(name="Alloc Customer", is_customer=True)
        self.wh_a = create_warehouse(name="Alloc A")
        self.wh_b = create_warehouse(name="Alloc B")
        assign_warehouse_account(warehouse=self.wh_a, account="1410")
        assign_warehouse_account(warehouse=self.wh_b, account="1420")
        self.day = date(2026, 2, 1)
        receive_stock(product=self.product, warehouse=self.wh_a, quantity=10, unit_cost="4", currency=self.afn, movement_date=self.day, reference="ALLOC-RCPT-A")
        receive_stock(product=self.product, warehouse=self.wh_b, quantity=10, unit_cost="6", currency=self.afn, movement_date=self.day, reference="ALLOC-RCPT-B")

    def balance(self, code):
        return account_balance(Account.objects.get(code=code))["balance"]

    def make_sale(self, *, allocations, quantity=10, number="SI-ALLOC-1", payment=PaymentMode.CREDIT):
        return create_sale(
            customer=self.customer, sale_date=self.day, currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=payment,
            document_number=number,
            lines=[{"product": self.product, "unit": self.unit, "quantity": quantity,
                    "unit_price": "10", "allocations": allocations}],
        )

    def test_split_allocation_posts_per_warehouse_cogs_at_invoice(self):
        sale = self.make_sale(allocations=[{"warehouse": self.wh_a, "quantity": 4},
                                           {"warehouse": self.wh_b, "quantity": 6}])
        finalize_sale(sale=sale)
        self.assertEqual(stock_for(self.product, self.wh_a), 6)
        self.assertEqual(stock_for(self.product, self.wh_b), 4)
        # COGS = 4*4 + 6*6 = 52, credited per mapped warehouse account.
        self.assertEqual(self.balance("5100"), Decimal("52.00"))
        self.assertEqual(self.balance("1410"), Decimal("-16.00"))
        self.assertEqual(self.balance("1420"), Decimal("-36.00"))
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), 2)
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 2)

    def test_cash_sale_posts_cash_and_cogs_at_invoice(self):
        sale = self.make_sale(allocations=[{"warehouse": self.wh_a, "quantity": 10}],
                              number="SI-ALLOC-CASH", payment=PaymentMode.CASH)
        finalize_sale(sale=sale)
        self.assertEqual(self.balance("1110"), Decimal("100.00"))
        self.assertEqual(self.balance("5100"), Decimal("40.00"))

    def test_missing_allocation_rolls_back_everything(self):
        sale = create_sale(
            customer=self.customer, sale_date=self.day, currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
            document_number="SI-ALLOC-NONE",
            lines=[{"product": self.product, "unit": self.unit, "quantity": 5, "unit_price": "10"}],
        )
        with self.assertRaises(SalesValidationError):
            finalize_sale(sale=sale)
        sale.refresh_from_db()
        self.assertEqual(sale.status, "DRAFT")
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 0)
        self.assertEqual(CustomerOwnershipEntitlement.objects.count(), 0)

    def test_allocation_sum_must_equal_line_quantity(self):
        with self.assertRaises(SalesValidationError):
            self.make_sale(allocations=[{"warehouse": self.wh_a, "quantity": 3}], number="SI-ALLOC-SUM")

    def test_repeated_finalization_is_idempotent(self):
        sale = self.make_sale(allocations=[{"warehouse": self.wh_a, "quantity": 10}])
        finalize_sale(sale=sale)
        finalize_sale(sale=sale)
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), 1)
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 1)
        self.assertEqual(self.balance("5100"), Decimal("40.00"))

    def test_partial_checks_release_custody_only_and_wrong_warehouse_rejected(self):
        sale = self.make_sale(allocations=[{"warehouse": self.wh_a, "quantity": 10}])
        finalize_sale(sale=sale)
        line = sale.lines.get()
        wrong = prepare_warehouse_check(sale_line=line, warehouse=self.wh_b, quantity=1, number="WC-ALLOC-WRONG")
        with self.assertRaises(SalesValidationError):
            finalize_warehouse_check(check=wrong)
        first = prepare_warehouse_check(sale_line=line, warehouse=self.wh_a, quantity=4, number="WC-ALLOC-1")
        finalize_warehouse_check(check=first)
        finalize_warehouse_check(check=first)  # duplicate request: no-op
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), 1)
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 1)
        self.assertEqual(stock_for(self.product, self.wh_a), 0)
        entitlement = CustomerOwnershipEntitlement.objects.get(sale_line=line)
        self.assertEqual(custody_balance(entitlement=entitlement, warehouse=self.wh_a), 0)
        second = prepare_warehouse_check(sale_line=line, warehouse=self.wh_a, quantity=6, number="WC-ALLOC-2")
        finalize_warehouse_check(check=second)
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 1)


class AllocationAuditRegressionTests(TestCase):
    """Audit findings: queryset immutability, obligation XOR, rollback, guards."""

    @classmethod
    def setUpTestData(cls):
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        seed_chart_of_accounts()

    def setUp(self):
        category = create_category(name="Audit Category")
        self.unit = create_uom(name="Audit Unit")
        self.product = create_product(code="AUDIT-1", name="Audit Product", name_fa="محصول ممیزی", category=category, primary_uom=self.unit)
        self.customer = create_party(name="Audit Customer", is_customer=True)
        self.wh_a = create_warehouse(name="Audit A")
        assign_warehouse_account(warehouse=self.wh_a, account="1410")
        self.day = date(2026, 2, 2)

    def _sale(self, *, allocations, quantity=5, number="SI-AUDIT-1"):
        return create_sale(
            customer=self.customer, sale_date=self.day, currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
            document_number=number,
            lines=[{"product": self.product, "unit": self.unit, "quantity": quantity,
                    "unit_price": "10", "allocations": allocations}],
        )

    def test_completed_allocation_rejects_queryset_update_and_delete(self):
        from accounting.models import PostedImmutabilityError
        from .models import SaleLineWarehouseAllocation
        receive_stock(product=self.product, warehouse=self.wh_a, quantity=5, unit_cost="4",
                      currency=self.afn, movement_date=self.day, reference="AUDIT-RCPT")
        sale = self._sale(allocations=[{"warehouse": self.wh_a, "quantity": 5}])
        finalize_sale(sale=sale)
        alloc = SaleLineWarehouseAllocation.objects.get()
        with self.assertRaises(PostedImmutabilityError):
            SaleLineWarehouseAllocation.objects.filter(pk=alloc.pk).update(quantity=1)
        with self.assertRaises(PostedImmutabilityError):
            SaleLineWarehouseAllocation.objects.filter(pk=alloc.pk).update(unit_cost_afn="9")
        with self.assertRaises(PostedImmutabilityError):
            # Partial completion (movement without COGS journal) is not the
            # approved one-time transition and must be rejected too.
            SaleLineWarehouseAllocation.objects.filter(pk=alloc.pk).update(
                stock_movement=alloc.stock_movement)
        with self.assertRaises(PostedImmutabilityError):
            SaleLineWarehouseAllocation.objects.filter(pk=alloc.pk).delete()
        with self.assertRaises(PostedImmutabilityError):
            alloc.save()
        alloc.refresh_from_db()
        self.assertEqual(alloc.quantity, 5)

    def test_unmapped_second_warehouse_rolls_back_all_allocations(self):
        from inventory.services import InventoryValidationError
        wh_b = create_warehouse(name="Audit Unmapped")  # no GL mapping
        sale = self._sale(
            quantity=10, number="SI-AUDIT-ROLLBACK",
            allocations=[{"warehouse": self.wh_a, "quantity": 5},
                         {"warehouse": wh_b, "quantity": 5}],
        )
        with self.assertRaises(InventoryValidationError):
            finalize_sale(sale=sale, acknowledge_negative=True, temporary_unit_cost="4")
        sale.refresh_from_db()
        self.assertEqual(sale.status, "DRAFT")
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 0)

    def test_negative_obligation_requires_exactly_one_source(self):
        from django.db import IntegrityError, transaction as db_transaction
        from .models import NegativeCOGSObligation
        sale = self._sale(allocations=[{"warehouse": self.wh_a, "quantity": 5}], number="SI-AUDIT-XOR")
        finalize_sale(sale=sale, acknowledge_negative=True, temporary_unit_cost="3")
        obligation = NegativeCOGSObligation.objects.get()
        self.assertIsNotNone(obligation.sale_allocation_id)
        self.assertIsNone(obligation.warehouse_check_id)
        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                NegativeCOGSObligation.objects.create(
                    movement=obligation.movement, product=self.product,
                    warehouse=self.wh_a, original_quantity=1,
                    temporary_unit_cost_afn="3", movement_date=self.day,
                )
        # Both sources set is equally invalid.
        sale.refresh_from_db()
        check = prepare_warehouse_check(sale_line=sale.lines.get(), warehouse=self.wh_a, quantity=1, number="WC-AUDIT-XOR")
        extra_movement = receive_stock(product=self.product, warehouse=self.wh_a, quantity=1, unit_cost="4",
                                       currency=self.afn, movement_date=self.day, reference="AUDIT-XOR-MV")
        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                NegativeCOGSObligation.objects.create(
                    movement=extra_movement, warehouse_check=check,
                    sale_allocation=obligation.sale_allocation,
                    product=self.product, warehouse=self.wh_a, original_quantity=1,
                    temporary_unit_cost_afn="3", movement_date=self.day,
                )

    def test_cancel_blocked_by_unresolved_negative_obligation(self):
        from .services import cancel_warehouse_check
        sale = self._sale(allocations=[{"warehouse": self.wh_a, "quantity": 5}], number="SI-AUDIT-NEG")
        finalize_sale(sale=sale, acknowledge_negative=True, temporary_unit_cost="3")
        check = prepare_warehouse_check(sale_line=sale.lines.get(), warehouse=self.wh_a, quantity=5, number="WC-AUDIT-NEG")
        finalize_warehouse_check(check=check)
        with self.assertRaises(SalesValidationError):
            cancel_warehouse_check(
                check=check, reversal_date=self.day, reason="Not delivered",
                idempotency_key="audit-neg-cancel", confirm_not_delivered=True,
            )

    def test_return_after_check_cancellation_is_rejected(self):
        from .returns_services import ReturnValidationError, create_sales_return
        from .services import cancel_warehouse_check
        receive_stock(product=self.product, warehouse=self.wh_a, quantity=5, unit_cost="4",
                      currency=self.afn, movement_date=self.day, reference="AUDIT-RCPT-3")
        sale = self._sale(allocations=[{"warehouse": self.wh_a, "quantity": 5}], number="SI-AUDIT-RET")
        finalize_sale(sale=sale)
        line = sale.lines.get()
        check = prepare_warehouse_check(sale_line=line, warehouse=self.wh_a, quantity=5, number="WC-AUDIT-RET")
        finalize_warehouse_check(check=check)
        cancel_warehouse_check(
            check=check, reversal_date=self.day, reason="Not delivered",
            idempotency_key="audit-ret-cancel", confirm_not_delivered=True,
        )
        with self.assertRaises(ReturnValidationError):
            create_sales_return(
                sale_line=line, warehouse=self.wh_a, quantity=1,
                return_date=self.day, reason="Returned after cancelled delivery",
                idempotency_key="audit-ret-1",
            )
        self.assertEqual(stock_for(self.product, self.wh_a), 0)


import threading
from django.db import close_old_connections, connection
from django.test import TransactionTestCase


class ConcurrentFinalizationTests(TransactionTestCase):
    """PostgreSQL: concurrent finalize of one sale posts COGS exactly once."""

    def setUp(self):
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        seed_chart_of_accounts()
        category = create_category(name="ConcAlloc Category")
        unit = create_uom(name="ConcAlloc Unit")
        self.product = create_product(code="ALLOC-CONC", name="Conc Product", name_fa="همزمان", category=category, primary_uom=unit)
        self.unit = unit
        self.customer = create_party(name="Conc Customer", is_customer=True)
        self.warehouse = create_warehouse(name="Conc Warehouse")
        assign_warehouse_account(warehouse=self.warehouse, account="1410")
        self.day = date(2026, 2, 3)
        receive_stock(product=self.product, warehouse=self.warehouse, quantity=10, unit_cost="4",
                      currency=self.afn, movement_date=self.day, reference="ALLOC-CONC-RCPT")

    def test_concurrent_finalize_posts_once(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL row-level locking semantics")
        sale = create_sale(
            customer=self.customer, sale_date=self.day, currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
            document_number="SI-ALLOC-CONC",
            lines=[{"product": self.product, "unit": self.unit, "quantity": 5, "unit_price": "10",
                    "allocations": [{"warehouse": self.warehouse, "quantity": 5}]}],
        )
        outcomes = []
        barrier = threading.Barrier(3)

        def worker(index):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                finalize_sale(sale=sale.pk)
                outcomes.append((index, "ok"))
            except Exception as exc:  # noqa: BLE001
                outcomes.append((index, "error", type(exc).__name__, str(exc)))
            finally:
                close_old_connections()

        workers = [threading.Thread(target=worker, args=(i,)) for i in (1, 2)]
        for w in workers:
            w.start()
        barrier.wait(timeout=5)
        for w in workers:
            w.join(timeout=20)
            self.assertFalse(w.is_alive())
        self.assertEqual([o for o in outcomes if o[1] == "ok"].__len__(), 2, outcomes)
        self.assertEqual(JournalEntry.objects.filter(source_type="SALES_COGS").count(), 1)
        self.assertEqual(StockMovement.objects.filter(movement_type="SALES_ISSUE").count(), 1)
        self.assertEqual(stock_for(self.product, self.warehouse), 5)


class ConcurrentReturnTests(TransactionTestCase):
    """PostgreSQL: concurrent returns cannot over-return one source issue."""

    def setUp(self):
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        seed_chart_of_accounts()
        category = create_category(name="ConcRet Category")
        self.unit = create_uom(name="ConcRet Unit")
        self.product = create_product(code="RET-CONC", name="ConcRet Product", name_fa="برگشت همزمان", category=category, primary_uom=self.unit)
        self.customer = create_party(name="ConcRet Customer", is_customer=True)
        self.warehouse = create_warehouse(name="ConcRet Warehouse")
        assign_warehouse_account(warehouse=self.warehouse, account="1410")
        self.day = date(2026, 2, 4)
        receive_stock(product=self.product, warehouse=self.warehouse, quantity=10, unit_cost="4",
                      currency=self.afn, movement_date=self.day, reference="RET-CONC-RCPT")
        sale = create_sale(
            customer=self.customer, sale_date=self.day, currency=self.afn,
            channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
            document_number="SI-RET-CONC",
            lines=[{"product": self.product, "unit": self.unit, "quantity": 5, "unit_price": "10",
                    "allocations": [{"warehouse": self.warehouse, "quantity": 5}]}],
        )
        finalize_sale(sale=sale)
        self.line = sale.lines.get()
        check = prepare_warehouse_check(sale_line=self.line, warehouse=self.warehouse, quantity=5, number="WC-RET-CONC")
        finalize_warehouse_check(check=check)

    def test_concurrent_returns_cannot_over_return(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL row-level locking semantics")
        from .returns_services import create_sales_return
        from .returns_models import SalesReturn
        outcomes = []
        barrier = threading.Barrier(3)

        def worker(index):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                create_sales_return(
                    sale_line=self.line.pk, warehouse=self.warehouse, quantity=4,
                    return_date=self.day, reason=f"Concurrent return {index}",
                    document_number=f"SR-CONC-{index}", idempotency_key=f"ret-conc-{index}",
                )
                outcomes.append((index, "ok"))
            except Exception as exc:  # noqa: BLE001
                outcomes.append((index, "error", type(exc).__name__))
            finally:
                close_old_connections()

        workers = [threading.Thread(target=worker, args=(i,)) for i in (1, 2)]
        for w in workers:
            w.start()
        barrier.wait(timeout=5)
        for w in workers:
            w.join(timeout=20)
            self.assertFalse(w.is_alive())
        self.assertEqual(len([o for o in outcomes if o[1] == "ok"]), 1, outcomes)
        self.assertEqual(SalesReturn.objects.filter(status="POSTED").count(), 1)
        self.assertEqual(stock_for(self.product, self.warehouse), 9)
