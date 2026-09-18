"""Phase 6.1 — Inventory Foundation tests (§35).

Movement truth, integer quantities, stock derivation, AVCO + zero reset,
negative stock with manual temporary cost, opening stock with 3900,
warehouse mapping, atomicity, idempotency, immutability, audit.
No purchase/sales/transfer/adjustment/report workflows (later stages).
Frozen suites untouched.
"""

from datetime import date
from decimal import Decimal
from itertools import count
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounting.coa import seed_chart_of_accounts
from accounting.models import (
    Account,
    JournalEntry,
    PostedImmutabilityError,
)
from accounting.services import JournalValidationError
from categories.services import create_category
from core.models import IdempotencyRecord
from fiscal_periods.services import (
    PeriodValidationError,
    close_period,
    create_period,
)
from currencies.models import Currency
from products.services import create_product
from security.models import AuditAction, AuditEvent
from uom.services import create_uom
from warehouses.services import create_warehouse

from .models import (
    MovementType,
    StockMovement,
    InventoryReturn,
    ShortageSettlement,
    WarehouseInventoryAccount,
)
from .services import (
    InventoryValidationError,
    assign_warehouse_account,
    issue_stock,
    open_stock,
    receive_stock,
    adjust_stock_in, adjust_stock_out, receive_with_waste, record_shortage, settle_shortage,
    purchase_return, sales_return,
    resolve_warehouse_account,
    transfer_stock,
)
from .stock import avco_for, movements_for, stock_for


class InventoryFixture:
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(
            code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")
        cls.user = get_user_model().objects.create_user(
            "inv6user", password="x")

    def setUp(self):
        self._numbers = count(1)
        self._keys = count(1)
        category = create_category(name="Oils", user=self.user)
        self.uom = create_uom(name="Carton", user=self.user)
        self.product = create_product(
            code="OIL-10L", name="Oil 10L", name_fa="روغن",
            category=category, primary_uom=self.uom, user=self.user)
        self.warehouse = create_warehouse(name="Omar Rahimi", user=self.user)
        self.day = date(2026, 1, 15)

    def _key(self, tag="INV61"):
        return f"{tag}-{next(self._keys):04d}"

    def _number(self, tag="INV61"):
        return f"{tag}-{next(self._numbers):04d}"

    def _map(self, warehouse=None, code="1410"):
        return assign_warehouse_account(
            warehouse=warehouse or self.warehouse, account=code,
            user=self.user)

    def _receive(self, quantity=100, unit_cost="10", currency=None,
                 rate=None, rate_date=None, product=None, warehouse=None,
                 reference="RCV-1", **kwargs):
        return receive_stock(
            product=product or self.product,
            warehouse=warehouse or self.warehouse,
            quantity=quantity, unit_cost=unit_cost,
            currency=currency or self.afn, rate=rate, rate_date=rate_date,
            movement_date=self.day, reference=reference, user=self.user,
            **kwargs)

    def _issue(self, quantity=10, reference="ISS-1", **kwargs):
        return issue_stock(
            product=self.product, warehouse=self.warehouse,
            quantity=quantity, movement_date=self.day,
            reference=reference, user=self.user, **kwargs)

    def _open(self, quantity=500, unit_cost="110", currency=None,
              rate=None, rate_date=None, reference="OP-1", **kwargs):
        if currency is None:
            currency = self.usd
            rate = Decimal("70") if rate is None else rate
            rate_date = self.day if rate_date is None else rate_date
        self._map()
        return open_stock(
            product=self.product, warehouse=self.warehouse,
            quantity=quantity, unit_cost=unit_cost, currency=currency,
            rate=rate, rate_date=rate_date, posting_date=self.day,
            reference=reference, user=self.user,
            number=self._number(), **kwargs)


class FoundationTests(InventoryFixture, TestCase):
    def test_valid_movement_creation(self):
        movement = self._receive()
        self.assertEqual(movement.movement_type, MovementType.PURCHASE_RECEIPT)
        self.assertEqual(movement.quantity, 100)
        self.assertEqual(movement.unit_cost, Decimal("10.0000"))
        self.assertEqual(movement.rate, Decimal("1.0000"))
        self.assertEqual(movement.unit_cost_afn, Decimal("10.0000"))
        self.assertFalse(movement.is_temporary_cost)
        self.assertEqual(movement.qty_before, 0)
        self.assertEqual(movement.qty_after, 100)
        self.assertEqual(movement.reference, "RCV-1")
        self.assertIsNone(movement.journal_entry_id)

    def test_invalid_product_rejected(self):
        with self.assertRaises(InventoryValidationError):
            self._receive(product=999999)

    def test_invalid_warehouse_rejected(self):
        with self.assertRaises(InventoryValidationError):
            self._receive(warehouse=999999)

    def test_inactive_masters_rejected(self):
        self.product.is_active = False
        self.product.save(update_fields=["is_active"])
        with self.assertRaises(InventoryValidationError):
            self._receive()
        self.product.is_active = True
        self.product.save(update_fields=["is_active"])
        self.warehouse.is_active = False
        self.warehouse.save(update_fields=["is_active"])
        with self.assertRaises(InventoryValidationError):
            self._receive()
        self.warehouse.is_active = True
        self.warehouse.save(update_fields=["is_active"])
        self.afn.is_active = False
        self.afn.save(update_fields=["is_active"])
        with self.assertRaises(InventoryValidationError):
            self._receive()

    def test_non_integer_quantity_rejected(self):
        for bad in (1.5, True, False, "100", None, Decimal("100")):
            with self.assertRaises(InventoryValidationError, msg=repr(bad)):
                self._receive(quantity=bad)

    def test_zero_quantity_rejected(self):
        with self.assertRaises(InventoryValidationError):
            self._receive(quantity=0)
        with self.assertRaises(InventoryValidationError):
            self._issue(quantity=0)

    def test_negative_units_rejected(self):
        with self.assertRaises(InventoryValidationError):
            self._receive(quantity=-5)
        with self.assertRaises(InventoryValidationError):
            self._issue(quantity=-5)

    def test_blank_reference_rejected(self):
        with self.assertRaises(InventoryValidationError):
            self._receive(reference="   ")

    def test_anonymous_user_rejected(self):
        with self.assertRaises(InventoryValidationError):
            receive_stock(
                product=self.product, warehouse=self.warehouse,
                quantity=10, unit_cost="10", currency=self.afn,
                movement_date=self.day, reference="RCV-X",
                user=AnonymousUser())

    def test_db_direction_backstop(self):
        kwargs = dict(
            product=self.product, warehouse=self.warehouse,
            movement_date=self.day, currency=self.afn,
            unit_cost=Decimal("10"), rate=Decimal("1"),
            rate_date=self.day, unit_cost_afn=Decimal("10"),
            qty_before=0, qty_after=0, reference="DB-1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StockMovement.objects.create(
                    movement_type=MovementType.PURCHASE_RECEIPT,
                    quantity=-5, **kwargs)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StockMovement.objects.create(
                    movement_type=MovementType.SALES_ISSUE,
                    quantity=5, **kwargs)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StockMovement.objects.create(
                    movement_type=MovementType.PURCHASE_RECEIPT,
                    quantity=0, **kwargs)

    def test_db_cost_backstop(self):
        kwargs = dict(
            movement_type=MovementType.PURCHASE_RECEIPT,
            product=self.product, warehouse=self.warehouse, quantity=5,
            movement_date=self.day, currency=self.afn,
            rate_date=self.day, unit_cost_afn=Decimal("10"),
            qty_before=0, qty_after=5, reference="DB-2")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StockMovement.objects.create(
                    unit_cost=Decimal("-1"), rate=Decimal("1"), **kwargs)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StockMovement.objects.create(
                    unit_cost=Decimal("10"), rate=Decimal("0"), **kwargs)


class StockDerivationTests(InventoryFixture, TestCase):
    def test_opening_receipt_issue_derive_stock(self):
        self._open()
        self._receive(quantity=200, unit_cost="12", reference="RCV-2")
        self._issue(quantity=150, reference="ISS-2")
        self.assertEqual(
            stock_for(self.product, self.warehouse), 550)

    def test_history_intact_and_ordered(self):
        self._receive(quantity=100, reference="RCV-A")
        self._receive(quantity=50, unit_cost="12", reference="RCV-B")
        rows = list(movements_for(self.product, self.warehouse))
        self.assertEqual([m.reference for m in rows], ["RCV-A", "RCV-B"])
        self.assertEqual(rows[1].qty_before, 100)
        self.assertEqual(rows[1].qty_after, 150)

    def test_stock_isolated_by_warehouse(self):
        other = create_warehouse(name="Mohib", user=self.user)
        self._receive(quantity=100, reference="RCV-W1")
        self._receive(quantity=7, reference="RCV-W2", warehouse=other)
        self.assertEqual(stock_for(self.product, self.warehouse), 100)
        self.assertEqual(stock_for(self.product, other), 7)

    def test_stock_isolated_by_product(self):
        category = create_category(name="Sugar", user=self.user)
        sugar = create_product(
            code="SUG-1KG", name="Sugar", name_fa="شکر",
            category=category, primary_uom=self.uom, user=self.user)
        self._receive(quantity=100, reference="RCV-P1")
        self._receive(quantity=9, reference="RCV-P2", product=sugar)
        self.assertEqual(stock_for(self.product, self.warehouse), 100)
        self.assertEqual(stock_for(sugar, self.warehouse), 9)

    def test_empty_stock_is_zero(self):
        self.assertEqual(stock_for(self.product, self.warehouse), 0)
        self.assertIsNone(avco_for(self.product, self.warehouse))


class CostTests(InventoryFixture, TestCase):
    def test_foreign_receipt_cost_context(self):
        movement = self._receive(
            quantity=100, unit_cost="110", currency=self.usd,
            rate=Decimal("70"), rate_date=self.day, reference="RCV-USD")
        self.assertEqual(movement.unit_cost, Decimal("110.0000"))
        self.assertEqual(movement.rate, Decimal("70.0000"))
        self.assertEqual(movement.rate_date, self.day)
        self.assertEqual(movement.unit_cost_afn, Decimal("7700.0000"))
        self.assertEqual(movement.currency.code, "USD")

    def test_unit_cost_quantized_half_up(self):
        movement = self._receive(unit_cost="10.12345", reference="RCV-Q")
        self.assertEqual(movement.unit_cost, Decimal("10.1235"))

    def test_foreign_requires_rate_and_rate_date(self):
        with self.assertRaises(InventoryValidationError):
            self._receive(
                unit_cost="110", currency=self.usd, reference="RCV-NR")
        with self.assertRaises(InventoryValidationError):
            self._receive(
                unit_cost="110", currency=self.usd, rate=Decimal("70"),
                reference="RCV-NRD")

    def test_base_currency_must_use_rate_one(self):
        with self.assertRaises(InventoryValidationError):
            self._receive(unit_cost="10", rate=Decimal("2"),
                          reference="RCV-BR")

    def test_avco_blend_four_decimals(self):
        self._receive(quantity=100, unit_cost="10", reference="RCV-B1")
        self._receive(quantity=50, unit_cost="20", reference="RCV-B2")
        self.assertEqual(
            avco_for(self.product, self.warehouse), Decimal("13.3333"))

    def test_issue_relief_keeps_avco(self):
        self._receive(quantity=100, unit_cost="10", reference="RCV-R1")
        issued = self._issue(quantity=40, reference="ISS-R1")
        self.assertEqual(issued.unit_cost, Decimal("10.0000"))
        self.assertEqual(issued.currency.code, "AFN")
        self.assertEqual(issued.rate, Decimal("1.0000"))
        self.assertFalse(issued.is_temporary_cost)
        self.assertEqual(
            avco_for(self.product, self.warehouse), Decimal("10.0000"))
        self.assertEqual(stock_for(self.product, self.warehouse), 60)

    def test_zero_stock_cost_reset(self):
        self._receive(quantity=100, unit_cost="110", reference="RCV-Z1")
        self._issue(quantity=100, reference="ISS-Z1")
        self.assertEqual(stock_for(self.product, self.warehouse), 0)
        self.assertIsNone(avco_for(self.product, self.warehouse))
        self._receive(quantity=50, unit_cost="125", reference="RCV-Z2")
        self.assertEqual(
            avco_for(self.product, self.warehouse), Decimal("125.0000"))

    def test_original_cost_preserved(self):
        self._receive(
            quantity=100, unit_cost="110.5000", currency=self.usd,
            rate=Decimal("70.2500"), rate_date=self.day,
            reference="RCV-ORIG")
        movement = StockMovement.objects.get(reference="RCV-ORIG")
        self.assertEqual(movement.unit_cost, Decimal("110.5000"))
        self.assertEqual(movement.rate, Decimal("70.2500"))
        self.assertEqual(
            movement.unit_cost_afn, Decimal("7762.6250"))


class NegativeStockTests(InventoryFixture, TestCase):
    def test_negative_stock_allowed(self):
        movement = self._issue(
            quantity=1000, reference="ISS-NEG",
            acknowledge_negative=True, temporary_unit_cost="5")
        self.assertEqual(stock_for(self.product, self.warehouse), -1000)
        self.assertEqual(movement.qty_before, 0)
        self.assertEqual(movement.qty_after, -1000)
        self.assertTrue(movement.is_temporary_cost)
        self.assertEqual(movement.unit_cost, Decimal("5.0000"))

    def test_acknowledgement_enforced(self):
        with self.assertRaisesRegex(InventoryValidationError, "WARNING"):
            self._issue(quantity=10, reference="ISS-NOACK")
        self.assertEqual(stock_for(self.product, self.warehouse), 0)

    def test_temporary_cost_required(self):
        with self.assertRaises(InventoryValidationError):
            self._issue(
                quantity=10, reference="ISS-NOTEMP",
                acknowledge_negative=True)

    def test_no_reference_price_substitution(self):
        self.product.ref_purchase_price = Decimal("999")
        self.product.save(update_fields=["ref_purchase_price"])
        self._receive(quantity=100, unit_cost="10", reference="RCV-S1")
        issued = self._issue(quantity=10, reference="ISS-S1")
        self.assertEqual(issued.unit_cost, Decimal("10.0000"))
        temp = self._issue(
            quantity=200, reference="ISS-S2", acknowledge_negative=True,
            temporary_unit_cost="7")
        self.assertEqual(temp.unit_cost, Decimal("7.0000"))
        self.assertTrue(temp.is_temporary_cost)

    def test_temp_cost_foreign_currency(self):
        movement = self._issue(
            quantity=10, reference="ISS-TF", acknowledge_negative=True,
            temporary_unit_cost="2", temporary_currency=self.usd,
            temporary_rate=Decimal("70"), temporary_rate_date=self.day)
        self.assertEqual(movement.currency.code, "USD")
        self.assertEqual(movement.unit_cost_afn, Decimal("140.0000"))

    def test_receipt_after_negative_uses_actual_cost(self):
        self._issue(
            quantity=100, reference="ISS-H1", acknowledge_negative=True,
            temporary_unit_cost="5")
        self._receive(quantity=100, unit_cost="7", reference="RCV-H1")
        self.assertEqual(stock_for(self.product, self.warehouse), 0)
        self.assertIsNone(avco_for(self.product, self.warehouse))
        self._receive(quantity=50, unit_cost="7", reference="RCV-H2")
        self.assertEqual(
            avco_for(self.product, self.warehouse), Decimal("7.0000"))

    def test_partial_hole_fill_establishes_receipt_basis(self):
        self._issue(
            quantity=100, reference="ISS-P1", acknowledge_negative=True,
            temporary_unit_cost="5")
        self._receive(quantity=150, unit_cost="10", reference="RCV-P1")
        self.assertEqual(stock_for(self.product, self.warehouse), 50)
        self.assertEqual(
            avco_for(self.product, self.warehouse), Decimal("10.0000"))

    def test_history_immutable_after_later_receipt(self):
        first = self._receive(
            quantity=100, unit_cost="110", currency=self.usd,
            rate=Decimal("70"), rate_date=self.day, reference="RCV-F1")
        self._receive(quantity=100, unit_cost="90", currency=self.usd,
                      rate=Decimal("72"), rate_date=self.day,
                      reference="RCV-F2")
        first.refresh_from_db()
        self.assertEqual(first.unit_cost, Decimal("110.0000"))
        self.assertEqual(first.rate, Decimal("70.0000"))
        self.assertEqual(first.unit_cost_afn, Decimal("7700.0000"))


class OpeningStockTests(InventoryFixture, TestCase):
    def test_opening_posts_balanced_journal(self):
        movement = self._open()
        entry = movement.journal_entry
        self.assertIsNotNone(entry)
        self.assertEqual(entry.status, "POSTED")
        self.assertEqual(entry.source_type, "OPENING_STOCK")
        legs = {line.account.code: line for line in entry.lines.all()}
        self.assertEqual(set(legs), {"1410", "3900"})
        self.assertEqual(legs["1410"].debit, Decimal("55000.00"))
        self.assertEqual(legs["1410"].credit, Decimal("0.00"))
        self.assertEqual(legs["3900"].credit, Decimal("55000.00"))
        self.assertEqual(legs["3900"].debit, Decimal("0.00"))
        self.assertEqual(movement.movement_type, MovementType.OPENING)
        self.assertEqual(movement.quantity, 500)
        self.assertEqual(stock_for(self.product, self.warehouse), 500)
        self.assertEqual(
            avco_for(self.product, self.warehouse), Decimal("7700.0000"))

    def test_opening_is_warehouse_specific(self):
        other = create_warehouse(name="Mohib", user=self.user)
        self._map(code="1410")
        self._map(warehouse=other, code="1420")
        first = open_stock(
            product=self.product, warehouse=self.warehouse, quantity=10,
            unit_cost="10", currency=self.afn, posting_date=self.day,
            reference="OP-W1", user=self.user, number=self._number())
        second = open_stock(
            product=self.product, warehouse=other, quantity=20,
            unit_cost="10", currency=self.afn, posting_date=self.day,
            reference="OP-W2", user=self.user, number=self._number())
        self.assertEqual(
            first.journal_entry.lines.get(debit__gt=0).account.code,
            "1410")
        self.assertEqual(
            second.journal_entry.lines.get(debit__gt=0).account.code,
            "1420")

    def test_opening_unmapped_warehouse_rejected(self):
        with self.assertRaisesRegex(
                InventoryValidationError, "No inventory GL account"):
            open_stock(
                product=self.product, warehouse=self.warehouse,
                quantity=10, unit_cost="10", currency=self.afn,
                posting_date=self.day, reference="OP-NOMAP",
                user=self.user, number=self._number())
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_opening_auto_number(self):
        self._map()
        movement = open_stock(
            product=self.product, warehouse=self.warehouse, quantity=5,
            unit_cost="10", currency=self.afn, posting_date=self.day,
            reference="OP-AUTO", user=self.user)
        self.assertTrue(
            movement.journal_entry.number.startswith("JE-"))

    def test_opening_idempotent_retry(self):
        self._map()
        kwargs = dict(
            product=self.product, warehouse=self.warehouse, quantity=5,
            unit_cost="10", currency=self.afn, posting_date=self.day,
            reference="OP-IDEM", user=self.user, number=self._number(),
            idempotency_key=self._key())
        first = open_stock(**kwargs)
        audits_before = AuditEvent.objects.count()
        second = open_stock(**kwargs)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_opening_retry_different_operation_rejected(self):
        self._map()
        key = self._key()
        number = self._number()
        open_stock(
            product=self.product, warehouse=self.warehouse, quantity=5,
            unit_cost="10", currency=self.afn, posting_date=self.day,
            reference="OP-R1", user=self.user, number=number,
            idempotency_key=key)
        with self.assertRaises(JournalValidationError):
            open_stock(
                product=self.product, warehouse=self.warehouse,
                quantity=6, unit_cost="10", currency=self.afn,
                posting_date=self.day, reference="OP-R1",
                user=self.user, number=number, idempotency_key=key)

    def test_opening_retry_different_product_rejected(self):
        self._map()
        key = self._key()
        number = self._number()
        kwargs = dict(
            warehouse=self.warehouse, quantity=5, unit_cost="10",
            currency=self.afn, posting_date=self.day, reference="OP-RP",
            description="Identical journal description",
            user=self.user, number=number, idempotency_key=key)
        open_stock(product=self.product, **kwargs)
        category = create_category(name="Sugar", user=self.user)
        sugar = create_product(
            code="SUG-1KG", name="Sugar", name_fa="شکر",
            category=category, primary_uom=self.uom, user=self.user)
        with self.assertRaises(InventoryValidationError):
            open_stock(product=sugar, **kwargs)


class MappingTests(InventoryFixture, TestCase):
    def test_assign_and_resolve(self):
        mapping = self._map()
        self.assertEqual(mapping.account.code, "1410")
        self.assertEqual(
            resolve_warehouse_account(self.warehouse).code, "1410")

    def test_rejects_non_posting_account(self):
        with self.assertRaises(InventoryValidationError):
            self._map(code="1400")

    def test_rejects_non_inventory_account(self):
        with self.assertRaises(InventoryValidationError):
            self._map(code="5100")

    def test_rejects_missing_account(self):
        with self.assertRaises(InventoryValidationError):
            self._map(code="1499")

    def test_rejects_inactive_account(self):
        Account.objects.filter(code="1420").update(is_active=False)
        with self.assertRaises(InventoryValidationError):
            self._map(code="1420")

    def test_no_pnl_accounts_in_opening(self):
        movement = self._open()
        for line in movement.journal_entry.lines.all():
            self.assertIn(line.account.account_type, ("ASSET", "EQUITY"))

    def test_remap_affects_only_future_postings(self):
        self._map(code="1410")
        first = open_stock(
            product=self.product, warehouse=self.warehouse, quantity=10,
            unit_cost="10", currency=self.afn, posting_date=self.day,
            reference="OP-M1", user=self.user, number=self._number())
        self._map(code="1420")
        second = open_stock(
            product=self.product, warehouse=self.warehouse, quantity=10,
            unit_cost="10", currency=self.afn, posting_date=self.day,
            reference="OP-M2", user=self.user, number=self._number())
        self.assertEqual(
            first.journal_entry.lines.get(debit__gt=0).account.code,
            "1410")
        self.assertEqual(
            second.journal_entry.lines.get(debit__gt=0).account.code,
            "1420")

    def test_reassign_same_account_is_noop_without_audit(self):
        self._map()
        audits_before = AuditEvent.objects.count()
        mapping = self._map()
        self.assertEqual(mapping.account.code, "1410")
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_mapping_audit_trail(self):
        self._map(code="1410")
        self._map(code="1420")
        events = AuditEvent.objects.filter(
            entity="WarehouseInventoryAccount").order_by("id")
        self.assertEqual(
            [event.action for event in events],
            [AuditAction.CREATE, AuditAction.UPDATE])
        self.assertEqual(
            events[1].previous_state, {"account_code": "1410"})
        self.assertEqual(
            events[1].new_state["account_code"], "1420")


class AtomicityIdempotencyTests(InventoryFixture, TestCase):
    def test_failed_opening_leaves_no_partial_state(self):
        self._map()
        audits_before = AuditEvent.objects.count()
        with mock.patch(
            "inventory.services.post_journal",
            side_effect=JournalValidationError("boom")
        ):
            with self.assertRaises(JournalValidationError):
                open_stock(
                    product=self.product, warehouse=self.warehouse,
                    quantity=5, unit_cost="10", currency=self.afn,
                    posting_date=self.day, reference="OP-FAIL",
                    user=self.user, number=self._number())
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_receive_retry_returns_original(self):
        key = self._key()
        first = self._receive(reference="RCV-IDEM", idempotency_key=key)
        audits_before = AuditEvent.objects.count()
        second = self._receive(reference="RCV-IDEM", idempotency_key=key)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_receive_retry_mismatch_rejected(self):
        key = self._key()
        self._receive(
            quantity=10, reference="RCV-MM", idempotency_key=key)
        with self.assertRaises(InventoryValidationError):
            self._receive(
                quantity=11, reference="RCV-MM", idempotency_key=key)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_issue_retry_returns_original(self):
        self._receive(quantity=100, reference="RCV-IR")
        key = self._key()
        first = self._issue(
            quantity=10, reference="ISS-IR", idempotency_key=key)
        second = self._issue(
            quantity=10, reference="ISS-IR", idempotency_key=key)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=MovementType.SALES_ISSUE).count(), 1)


class ImmutabilityAuditTests(InventoryFixture, TestCase):
    def test_posted_movement_cannot_be_updated_or_deleted(self):
        movement = self._receive()
        movement.quantity = 999
        with self.assertRaises(PostedImmutabilityError):
            movement.save()
        with self.assertRaises(PostedImmutabilityError):
            movement.delete()
        movement.refresh_from_db()
        self.assertEqual(movement.quantity, 100)

    def test_movement_audit_recorded(self):
        movement = self._receive()
        event = AuditEvent.objects.get(
            entity="StockMovement", entity_id=str(movement.id))
        self.assertEqual(event.action, AuditAction.CREATE)
        self.assertEqual(event.reference, "RCV-1")
        state = event.new_state
        self.assertEqual(state["movement_type"], "PURCHASE_RECEIPT")
        self.assertEqual(state["product_id"], self.product.pk)
        self.assertEqual(state["warehouse_id"], self.warehouse.pk)
        self.assertEqual(state["quantity"], 100)
        self.assertEqual(state["qty_before"], 0)
        self.assertEqual(state["qty_after"], 100)
        self.assertEqual(state["unit_cost_afn"], "10.0000")

    def test_negative_acknowledgement_audited(self):
        movement = self._issue(
            quantity=10, reference="ISS-AU", acknowledge_negative=True,
            temporary_unit_cost="5")
        event = AuditEvent.objects.get(
            entity="StockMovement", entity_id=str(movement.id))
        self.assertIn("Negative stock acknowledged", event.reason)
        self.assertTrue(event.new_state["is_temporary_cost"])


class DescriptionTests(InventoryFixture, TestCase):
    def test_receive_description_stored_and_audited(self):
        movement = self._receive(
            reference="RCV-D1", description="  Supplier packing list 42  ")
        self.assertEqual(movement.description, "Supplier packing list 42")
        event = AuditEvent.objects.get(
            entity="StockMovement", entity_id=str(movement.id))
        self.assertEqual(
            event.new_state["description"], "Supplier packing list 42")

    def test_description_defaults_to_blank(self):
        movement = self._receive(reference="RCV-D0")
        self.assertEqual(movement.description, "")

    def test_issue_description_stored(self):
        self._receive(quantity=100, reference="RCV-D2")
        movement = self._issue(
            quantity=10, reference="ISS-D1", description="Shop delivery")
        self.assertEqual(movement.description, "Shop delivery")

    def test_opening_description_on_movement(self):
        explicit = self._open(reference="OP-D1", description="Go-live count")
        self.assertEqual(explicit.description, "Go-live count")
        defaulted = self._open(reference="OP-D2")
        self.assertEqual(
            defaulted.description,
            "Opening stock: OIL-10L x 500 @ Omar Rahimi")

    def test_description_too_long_rejected(self):
        long_text = "x" * 501
        with self.assertRaises(InventoryValidationError):
            self._receive(reference="RCV-DL", description=long_text)
        with self.assertRaises(InventoryValidationError):
            self._issue(quantity=1, reference="ISS-DL",
                        description=long_text,
                        acknowledge_negative=True,
                        temporary_unit_cost="1")
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_description_must_be_text(self):
        with self.assertRaises(InventoryValidationError):
            self._receive(reference="RCV-DT", description=123)

    def test_retry_description_mismatch_rejected(self):
        key = self._key()
        self._receive(
            reference="RCV-DM", description="first",
            idempotency_key=key)
        with self.assertRaises(InventoryValidationError):
            self._receive(
                reference="RCV-DM", description="second",
                idempotency_key=key)
        self.assertEqual(StockMovement.objects.count(), 1)


class FiscalPeriodTests(InventoryFixture, TestCase):
    def _period(self):
        return create_period(
            name="FY26", start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31), user=self.user)

    def test_open_period_posting_allowed(self):
        self._period()
        movement = self._open()
        self.assertIsNotNone(movement.journal_entry_id)

    def test_closed_period_posting_rejected(self):
        period = self._period()
        close_period(period, user=self.user, reason="year-end")
        with self.assertRaises(PeriodValidationError):
            self._open()
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(
            AuditEvent.objects.filter(entity="StockMovement").count(), 0)


class AtomicityChronologyTests(InventoryFixture, TestCase):
    def test_audit_failure_rolls_back_movement(self):
        movements_before = StockMovement.objects.count()
        audits_before = AuditEvent.objects.count()
        keys_before = IdempotencyRecord.objects.count()
        with mock.patch(
            "inventory.services.record_audit_event",
            side_effect=RuntimeError("audit store down")
        ):
            with self.assertRaises(RuntimeError):
                self._receive(
                    reference="RCV-AF", idempotency_key=self._key())
        self.assertEqual(StockMovement.objects.count(), movements_before)
        self.assertEqual(AuditEvent.objects.count(), audits_before)
        self.assertEqual(IdempotencyRecord.objects.count(), keys_before)

    def test_backdated_receipt_replays_in_date_order(self):
        receive_stock(
            product=self.product, warehouse=self.warehouse, quantity=100,
            unit_cost="10", currency=self.afn,
            movement_date=date(2026, 1, 10), reference="RCV-C1",
            user=self.user)
        issue_stock(
            product=self.product, warehouse=self.warehouse, quantity=60,
            movement_date=date(2026, 1, 20), reference="ISS-C1",
            user=self.user)
        receive_stock(
            product=self.product, warehouse=self.warehouse, quantity=60,
            unit_cost="20", currency=self.afn,
            movement_date=date(2026, 1, 15), reference="RCV-C2",
            user=self.user)
        rows = list(movements_for(self.product, self.warehouse))
        self.assertEqual(
            [m.reference for m in rows], ["RCV-C1", "RCV-C2", "ISS-C1"])
        self.assertEqual(stock_for(self.product, self.warehouse), 100)
        self.assertEqual(
            avco_for(self.product, self.warehouse), Decimal("13.7500"))
        issued = StockMovement.objects.get(reference="ISS-C1")
        self.assertEqual(issued.unit_cost, Decimal("10.0000"))


class TransferFixture(InventoryFixture):
    def setUp(self):
        super().setUp()
        self.source = create_warehouse(name="Mohib", user=self.user)
        self.dest = create_warehouse(name="Omar Rahimi", user=self.user)

    def _map_pair(self, source_code="1410", dest_code="1420",
                  source=None, dest=None):
        self._map(warehouse=source or self.source, code=source_code)
        self._map(warehouse=dest or self.dest, code=dest_code)

    def _transfer(self, quantity=100, reference="TRF-1",
                  description="Restock Omar Rahimi", source=None,
                  dest=None, **kwargs):
        return transfer_stock(
            product=self.product, source_warehouse=source or self.source,
            destination_warehouse=dest or self.dest, quantity=quantity,
            movement_date=self.day, reference=reference,
            description=description, user=self.user, **kwargs)

    def _stock_source(self, quantity=500, unit_cost="10", reference="RCV-S"):
        return self._receive(
            quantity=quantity, unit_cost=unit_cost, reference=reference,
            warehouse=self.source)


class TransferBasicTests(TransferFixture, TestCase):
    def test_transfer_moves_stock(self):
        self._map_pair()
        self._stock_source()
        out, inn = self._transfer()
        self.assertEqual(out.movement_type, MovementType.TRANSFER_OUT)
        self.assertEqual(inn.movement_type, MovementType.TRANSFER_IN)
        self.assertEqual(out.quantity, -100)
        self.assertEqual(inn.quantity, 100)
        self.assertEqual(stock_for(self.product, self.source), 400)
        self.assertEqual(stock_for(self.product, self.dest), 100)
        self.assertEqual(
            stock_for(self.product, self.source)
            + stock_for(self.product, self.dest), 500)

    def test_same_warehouse_rejected(self):
        self._map_pair()
        self._stock_source()
        with self.assertRaises(InventoryValidationError):
            self._transfer(source=self.source, dest=self.source)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_zero_quantity_rejected(self):
        self._map_pair()
        with self.assertRaises(InventoryValidationError):
            self._transfer(quantity=0)

    def test_negative_quantity_rejected(self):
        self._map_pair()
        with self.assertRaises(InventoryValidationError):
            self._transfer(quantity=-5)

    def test_non_integer_quantity_rejected(self):
        self._map_pair()
        for bad in (1.5, True, "100", None):
            with self.assertRaises(InventoryValidationError, msg=repr(bad)):
                self._transfer(quantity=bad)

    def test_blank_description_rejected(self):
        self._map_pair()
        self._stock_source()
        with self.assertRaises(InventoryValidationError):
            self._transfer(description="   ")
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type__in=(MovementType.TRANSFER_OUT,
                                   MovementType.TRANSFER_IN)).count(), 0)

    def test_description_stored_and_trimmed_on_both_legs(self):
        self._map_pair()
        self._stock_source()
        out, inn = self._transfer(description="  Monthly rebalance  ")
        self.assertEqual(out.description, "Monthly rebalance")
        self.assertEqual(inn.description, "Monthly rebalance")

    def test_legs_linked_as_one_operation(self):
        self._map_pair()
        self._stock_source()
        key = self._key()
        out, inn = self._transfer(reference="TRF-LINK", idempotency_key=key)
        self.assertEqual(out.journal_entry_id, inn.journal_entry_id)
        self.assertIsNotNone(out.journal_entry_id)
        self.assertEqual(out.reference, "TRF-LINK")
        self.assertEqual(inn.reference, "TRF-LINK")
        self.assertIsNone(out.idempotency_key)
        self.assertIsNone(inn.idempotency_key)
        record = IdempotencyRecord.objects.get(key=key)
        self.assertEqual(record.operation, "inventory.transfer")
        self.assertEqual(record.response_body["out_movement_id"], out.pk)
        self.assertEqual(record.response_body["in_movement_id"], inn.pk)
        legs = set(out.journal_entry.stock_movements.values_list(
            "movement_type", flat=True))
        self.assertEqual(
            legs, {MovementType.TRANSFER_OUT, MovementType.TRANSFER_IN})

    def test_warehouses_stay_independent(self):
        self._map_pair()
        self._stock_source()
        third = create_warehouse(name="Mal Hassan", user=self.user)
        self._receive(quantity=7, reference="RCV-THIRD", warehouse=third)
        self._transfer(quantity=100)
        self.assertEqual(stock_for(self.product, self.source), 400)
        self.assertEqual(stock_for(self.product, self.dest), 100)
        self.assertEqual(stock_for(self.product, third), 7)


class TransferCostTests(TransferFixture, TestCase):
    def test_cost_basis_preserved(self):
        self._map_pair()
        self._receive(
            quantity=100, unit_cost="10", reference="RCV-C1",
            warehouse=self.source)
        self._receive(
            quantity=50, unit_cost="20", reference="RCV-C2",
            warehouse=self.source)
        source_qty_before = stock_for(self.product, self.source)
        source_avco_before = avco_for(self.product, self.source)
        dest_qty_before = stock_for(self.product, self.dest)
        dest_avco_before = avco_for(self.product, self.dest)
        out, inn = self._transfer(quantity=50, reference="TRF-COST")
        self.assertEqual(source_qty_before, 150)
        self.assertEqual(source_avco_before, Decimal("13.3333"))
        self.assertEqual(dest_qty_before, 0)
        self.assertIsNone(dest_avco_before)
        self.assertEqual(out.quantity, -50)
        self.assertEqual(inn.quantity, 50)
        self.assertEqual(out.unit_cost * 50, Decimal("666.6650"))
        self.assertEqual(out.unit_cost, Decimal("13.3333"))
        self.assertEqual(inn.unit_cost, Decimal("13.3333"))
        self.assertEqual(out.unit_cost_afn, Decimal("13.3333"))
        self.assertEqual(inn.unit_cost_afn, Decimal("13.3333"))
        self.assertEqual(inn.currency.code, "AFN")
        self.assertFalse(out.is_temporary_cost)
        self.assertFalse(inn.is_temporary_cost)
        self.assertEqual(
            avco_for(self.product, self.dest), Decimal("13.3333"))
        # Source relief at rounded AVCO leaves honest dust, documented.
        self.assertEqual(stock_for(self.product, self.source), 100)
        self.assertEqual(stock_for(self.product, self.dest), 50)
        self.assertEqual(
            avco_for(self.product, self.source), Decimal("13.3334"))
        self.assertEqual(
            avco_for(self.product, self.dest), Decimal("13.3333"))
        # Exact replay values conserve the original AFN value: 2000.0000.
        # The displayed source AVCO rounds 13.33335 upward to 13.3334;
        # that 0.0050 is display/replay dust, not a new movement value.
        exact_source_value = Decimal("100") * Decimal("13.33335")
        exact_destination_value = Decimal("50") * Decimal("13.3333")
        self.assertEqual(exact_source_value + exact_destination_value,
                         Decimal("2000.0000"))

    def test_no_reference_price_used(self):
        self.product.ref_purchase_price = Decimal("999")
        self.product.ref_sales_price = Decimal("888")
        self.product.save(
            update_fields=["ref_purchase_price", "ref_sales_price"])
        self._map_pair()
        self._stock_source(quantity=100, unit_cost="10")
        out, inn = self._transfer(quantity=40, reference="TRF-NOREF")
        self.assertEqual(out.unit_cost, Decimal("10.0000"))
        self.assertEqual(inn.unit_cost, Decimal("10.0000"))

    def test_later_receipt_preserves_transfer_cost(self):
        self._map_pair()
        self._receive(
            quantity=100, unit_cost="10", reference="RCV-H1",
            warehouse=self.source)
        out, inn = self._transfer(quantity=60, reference="TRF-HIST")
        self._receive(
            quantity=100, unit_cost="999", reference="RCV-H2",
            warehouse=self.source)
        self._receive(
            quantity=100, unit_cost="888", reference="RCV-H3",
            warehouse=self.dest)
        out.refresh_from_db()
        inn.refresh_from_db()
        self.assertEqual(out.unit_cost, Decimal("10.0000"))
        self.assertEqual(inn.unit_cost, Decimal("10.0000"))
        first = avco_for(self.product, self.source)
        self.assertEqual(first, avco_for(self.product, self.source))
        self.assertEqual(
            stock_for(self.product, self.source)
            + stock_for(self.product, self.dest), 300)

    def test_backdated_transfer_deterministic(self):
        self._map_pair()
        receive_stock(
            product=self.product, warehouse=self.source, quantity=100,
            unit_cost="10", currency=self.afn,
            movement_date=date(2026, 1, 10), reference="RCV-B1",
            user=self.user)
        transfer_stock(
            product=self.product, source_warehouse=self.source,
            destination_warehouse=self.dest, quantity=40,
            movement_date=date(2026, 1, 5), reference="TRF-BACK",
            description="Backdated correction", user=self.user)
        rows = list(movements_for(self.product, self.source))
        self.assertEqual(
            [m.reference for m in rows], ["TRF-BACK", "RCV-B1"])
        out = StockMovement.objects.get(
            reference="TRF-BACK",
            movement_type=MovementType.TRANSFER_OUT)
        # Basis is post-time AVCO (100@10 existed at posting); replay is by
        # date. Semantics match issue_stock; documented, deterministic.
        self.assertEqual(out.unit_cost, Decimal("10.0000"))
        self.assertEqual(stock_for(self.product, self.source), 60)
        self.assertEqual(stock_for(self.product, self.dest), 40)

    def test_transfer_after_zero_reset(self):
        self._map_pair()
        self._receive(
            quantity=100, unit_cost="10", reference="RCV-Z1",
            warehouse=self.source)
        issue_stock(
            product=self.product, warehouse=self.source, quantity=100,
            movement_date=self.day, reference="ISS-Z1", user=self.user)
        self.assertIsNone(avco_for(self.product, self.source))
        self._receive(
            quantity=50, unit_cost="20", reference="RCV-Z2",
            warehouse=self.source)
        out, inn = self._transfer(quantity=30, reference="TRF-ZR")
        self.assertEqual(out.unit_cost, Decimal("20.0000"))
        self.assertEqual(inn.unit_cost, Decimal("20.0000"))


class TransferNegativeTests(TransferFixture, TestCase):
    def test_negative_source_requires_ack_and_temp(self):
        self._map_pair()
        with self.assertRaisesRegex(InventoryValidationError, "WARNING"):
            self._transfer(quantity=10, reference="TRF-N1")
        with self.assertRaises(InventoryValidationError):
            self._transfer(
                quantity=10, reference="TRF-N1",
                acknowledge_negative=True)
        out, inn = self._transfer(
            quantity=10, reference="TRF-N1", acknowledge_negative=True,
            temporary_unit_cost="5")
        self.assertEqual(stock_for(self.product, self.source), -10)
        self.assertEqual(stock_for(self.product, self.dest), 10)
        self.assertTrue(out.is_temporary_cost)
        self.assertTrue(inn.is_temporary_cost)
        self.assertEqual(out.unit_cost, Decimal("5.0000"))
        self.assertEqual(inn.unit_cost, Decimal("5.0000"))

    def test_no_ref_price_as_temp(self):
        self.product.ref_purchase_price = Decimal("999")
        self.product.save(update_fields=["ref_purchase_price"])
        self._map_pair()
        out, _inn = self._transfer(
            quantity=10, reference="TRF-NT", acknowledge_negative=True,
            temporary_unit_cost="7")
        self.assertEqual(out.unit_cost, Decimal("7.0000"))

    def test_insufficient_source_uses_temp_for_whole_leg(self):
        self._map_pair()
        self._stock_source(quantity=50, unit_cost="10")
        out, inn = self._transfer(
            quantity=80, reference="TRF-PART", acknowledge_negative=True,
            temporary_unit_cost="12")
        self.assertEqual(stock_for(self.product, self.source), -30)
        self.assertEqual(out.unit_cost, Decimal("12.0000"))
        self.assertEqual(inn.unit_cost, Decimal("12.0000"))


class TransferAccountingTests(TransferFixture, TestCase):
    def test_reclass_journal_balanced_and_mapped(self):
        self._map_pair()
        self._stock_source(quantity=100, unit_cost="110")
        _out, inn = self._transfer(quantity=100, reference="TRF-JE")
        entry = inn.journal_entry
        self.assertIsNotNone(entry)
        self.assertEqual(entry.status, "POSTED")
        self.assertEqual(entry.source_type, "TRANSFER")
        self.assertEqual(entry.source_id, "TRF-JE")
        legs = {line.account.code: line for line in entry.lines.all()}
        self.assertEqual(set(legs), {"1420", "1410"})
        self.assertEqual(legs["1420"].debit, Decimal("11000.00"))
        self.assertEqual(legs["1420"].credit, Decimal("0.00"))
        self.assertEqual(legs["1410"].credit, Decimal("11000.00"))
        self.assertTrue(entry.number.startswith("JE-"))

    def test_usd_costed_transfer_journal_is_afn_book_value(self):
        self._map_pair()
        self._receive(quantity=10, unit_cost="10", currency=self.usd,
                      rate="70", rate_date=self.day, reference="RCV-USD",
                      warehouse=self.source)
        _out, inn = self._transfer(quantity=10, reference="TRF-USD")
        entry = inn.journal_entry
        self.assertEqual(entry.currency.code, "AFN")
        self.assertEqual(entry.rate, Decimal("1.0000"))
        self.assertEqual(entry.rate_direction, "AFN->AFN")
        self.assertEqual(entry.total_debit, Decimal("7000.00"))
        self.assertEqual(entry.afn_total, Decimal("7000.00"))
        self.assertEqual(inn.currency.code, "AFN")
        self.assertEqual(inn.unit_cost_afn, Decimal("700.0000"))
        self.assertEqual(stock_for(self.product, self.source), 0)
        self.assertEqual(stock_for(self.product, self.dest), 10)

    def test_no_pnl_cogs_or_fx(self):
        self._map_pair()
        self._stock_source(quantity=100, unit_cost="110")
        _out, inn = self._transfer(quantity=100, reference="TRF-PNL")
        for line in inn.journal_entry.lines.all():
            self.assertEqual(line.account.account_type, "ASSET")
            self.assertNotEqual(line.account.code, "5100")

    def test_unmapped_warehouses_rejected(self):
        self._stock_source()
        with self.assertRaisesRegex(
                InventoryValidationError, "No inventory GL account"):
            self._transfer(reference="TRF-NOMAP")
        self._map(warehouse=self.source, code="1410")
        with self.assertRaisesRegex(
                InventoryValidationError, "No inventory GL account"):
            self._transfer(reference="TRF-NOMAP2")
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type__in=(MovementType.TRANSFER_OUT,
                                   MovementType.TRANSFER_IN)).count(), 0)
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_same_account_wash_journal(self):
        self._map_pair(source_code="1410", dest_code="1410")
        self._stock_source(quantity=100, unit_cost="10")
        _out, inn = self._transfer(quantity=100, reference="TRF-WASH")
        legs = list(inn.journal_entry.lines.all())
        self.assertEqual(
            [line.account.code for line in legs], ["1410", "1410"])
        self.assertEqual(legs[0].debit, Decimal("1000.00"))
        self.assertEqual(legs[1].credit, Decimal("1000.00"))
        self.assertEqual(stock_for(self.product, self.dest), 100)

    def test_closed_period_rejected(self):
        period = create_period(
            name="FY26", start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31), user=self.user)
        close_period(period, user=self.user, reason="year-end")
        self._map_pair()
        self._stock_source()
        with self.assertRaises(PeriodValidationError):
            self._transfer(reference="TRF-CLOSED")
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type__in=(MovementType.TRANSFER_OUT,
                                   MovementType.TRANSFER_IN)).count(), 0)
        self.assertEqual(JournalEntry.objects.count(), 0)


class TransferAtomicityIdempotencyTests(TransferFixture, TestCase):
    def test_journal_failure_rolls_back_everything(self):
        self._map_pair()
        self._stock_source()
        movements_before = StockMovement.objects.count()
        journals_before = JournalEntry.objects.count()
        audits_before = AuditEvent.objects.count()
        keys_before = IdempotencyRecord.objects.count()
        with mock.patch(
            "inventory.services.post_journal",
            side_effect=JournalValidationError("boom")
        ):
            with self.assertRaises(JournalValidationError):
                self._transfer(
                    reference="TRF-FAIL", idempotency_key=self._key())
        self.assertEqual(StockMovement.objects.count(), movements_before)
        self.assertEqual(JournalEntry.objects.count(), journals_before)
        self.assertEqual(AuditEvent.objects.count(), audits_before)
        self.assertEqual(IdempotencyRecord.objects.count(), keys_before)

    def test_leg_failure_rolls_back_journal(self):
        self._map_pair()
        self._stock_source()
        real_create = StockMovement.objects.create
        calls = []
        def flaky_create(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("second leg down")
            return real_create(*args, **kwargs)
        with mock.patch.object(
            StockMovement.objects, "create", side_effect=flaky_create
        ):
            with self.assertRaises(RuntimeError):
                self._transfer(reference="TRF-LEGFAIL")
        self.assertEqual(
            StockMovement.objects.filter(reference="TRF-LEGFAIL").count(),
            0)
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(
            AuditEvent.objects.filter(reference="TRF-LEGFAIL").count(), 0)

    def test_retry_returns_original_pair(self):
        self._map_pair()
        self._stock_source()
        key = self._key()
        first_out, first_in = self._transfer(
            reference="TRF-IDEM", idempotency_key=key)
        audits_before = AuditEvent.objects.count()
        second_out, second_in = self._transfer(
            reference="TRF-IDEM", idempotency_key=key)
        self.assertEqual(first_out.pk, second_out.pk)
        self.assertEqual(first_in.pk, second_in.pk)
        self.assertEqual(
            StockMovement.objects.filter(reference="TRF-IDEM").count(), 2)
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_retry_mismatch_rejected(self):
        self._map_pair()
        self._stock_source()
        key = self._key()
        self._transfer(
            quantity=100, reference="TRF-MM", idempotency_key=key)
        with self.assertRaises(InventoryValidationError):
            self._transfer(
                quantity=150, reference="TRF-MM", idempotency_key=key)
        other = create_warehouse(name="Mal Hassan", user=self.user)
        self._map(warehouse=other, code="1420")
        with self.assertRaises(InventoryValidationError):
            transfer_stock(
                product=self.product, source_warehouse=self.source,
                destination_warehouse=other, quantity=100,
                movement_date=self.day, reference="TRF-MM",
                description="Restock Omar Rahimi", user=self.user,
                idempotency_key=key)
        self.assertEqual(JournalEntry.objects.count(), 1)


class TransferImmutabilityAuditTests(TransferFixture, TestCase):
    def test_legs_immutable(self):
        self._map_pair()
        self._stock_source()
        out, inn = self._transfer()
        out.quantity = 1
        with self.assertRaises(PostedImmutabilityError):
            out.save()
        with self.assertRaises(PostedImmutabilityError):
            inn.delete()

    def test_audit_evidence(self):
        self._map_pair()
        self._stock_source()
        out, inn = self._transfer(
            quantity=100, reference="TRF-AU",
            description="Monthly rebalance")
        out_event = AuditEvent.objects.get(
            entity="StockMovement", entity_id=str(out.id))
        in_event = AuditEvent.objects.get(
            entity="StockMovement", entity_id=str(inn.id))
        self.assertEqual(out_event.action, AuditAction.CREATE)
        state = out_event.new_state
        self.assertEqual(state["movement_type"], "TRANSFER_OUT")
        self.assertEqual(state["warehouse_id"], self.source.pk)
        self.assertEqual(state["quantity"], -100)
        self.assertEqual(state["qty_before"], 500)
        self.assertEqual(state["qty_after"], 400)
        self.assertEqual(state["description"], "Monthly rebalance")
        self.assertEqual(
            state["journal_entry_id"], out.journal_entry_id)
        self.assertEqual(
            in_event.new_state["warehouse_id"], self.dest.pk)
        post_event = AuditEvent.objects.get(
            entity="JournalEntry",
            entity_id=str(out.journal_entry_id))
        self.assertEqual(post_event.action, AuditAction.POST)

    def test_negative_acknowledgement_audited(self):
        self._map_pair()
        out, _inn = self._transfer(
            quantity=10, reference="TRF-AN", acknowledge_negative=True,
            temporary_unit_cost="5")
        event = AuditEvent.objects.get(
            entity="StockMovement", entity_id=str(out.id))
        self.assertIn("Negative stock acknowledged", event.reason)


class Stage64Tests(InventoryFixture, TestCase):
    """Focused Stage 6.4 contract tests."""

    def _adjust_in(self, quantity=5, cost="12", **kwargs):
        return adjust_stock_in(product=self.product, warehouse=self.warehouse,
            quantity=quantity, unit_cost=cost, currency=self.afn,
            movement_date=self.day, reference=self._number("ADJ"),
            description="Physical count correction", user=self.user,
            **kwargs)

    def test_positive_adjustment_stock_cost_and_audit(self):
        m = self._adjust_in()
        self.assertEqual(stock_for(self.product, self.warehouse), 5)
        self.assertEqual(m.movement_type, MovementType.ADJUSTMENT_IN)
        self.assertTrue(AuditEvent.objects.filter(entity="StockMovement", entity_id=m.id).exists())

    def test_adjustment_integer_and_reason_rules(self):
        with self.assertRaises(InventoryValidationError):
            self._adjust_in(quantity=1.5)
        with self.assertRaises(InventoryValidationError):
            adjust_stock_in(product=self.product, warehouse=self.warehouse, quantity=1,
                unit_cost="1", currency=self.afn, movement_date=self.day,
                reference="ADJ-X", description="", user=self.user)

    def test_negative_adjustment_reuses_ack_and_temporary_cost(self):
        self._adjust_in(quantity=2, cost="10")
        with self.assertRaises(InventoryValidationError):
            adjust_stock_out(product=self.product, warehouse=self.warehouse, quantity=3,
                movement_date=self.day, reference="ADJ-OUT", description="count",
                user=self.user)
        m = adjust_stock_out(product=self.product, warehouse=self.warehouse, quantity=3,
            movement_date=self.day, reference="ADJ-OUT", description="count",
            user=self.user, acknowledge_negative=True, unit_cost="11", currency=self.afn)
        self.assertTrue(m.is_temporary_cost)
        self.assertEqual(stock_for(self.product, self.warehouse), -1)

    def test_waste_allocates_total_cost_over_usable_and_is_traceable(self):
        m = receive_with_waste(product=self.product, warehouse=self.warehouse,
            gross_quantity=2000, waste_quantity=3, total_cost="370000", currency=self.usd,
            rate="1", rate_date=self.day, movement_date=self.day, reference="RCV-W",
            description="Unloading receipt; three waste", user=self.user)
        self.assertEqual(m.quantity, 1997)
        self.assertEqual(m.gross_quantity, 2000)
        self.assertEqual(m.waste_quantity, 3)
        self.assertEqual(m.unit_cost, Decimal("185.2779"))
        self.assertEqual(stock_for(self.product, self.warehouse), 1997)
        self.assertEqual(StockMovement.objects.filter(product=self.product).count(), 1)

    def test_shortage_is_new_event_and_settlement_uses_manual_rate(self):
        receipt = self._receive(quantity=1997, unit_cost="20", reference="RCV-S")
        shortage = record_shortage(product=self.product, warehouse=self.warehouse,
            quantity=7, movement_date=date(2026, 2, 1), reference="SH-1",
            description="Later count shortage", user=self.user)
        self.assertEqual(stock_for(self.product, self.warehouse), 1990)
        receipt.refresh_from_db()
        self.assertEqual(receipt.quantity, 1997)
        self.assertEqual(receipt.unit_cost, Decimal("20.0000"))
        settlement = settle_shortage(shortage=shortage, settlement_date=date(2026, 2, 2),
            actual_sales_rate="125", currency=self.usd, rate="1", rate_date=date(2026, 2, 2),
            reference="SET-1", user=self.user)
        self.assertEqual(settlement.unit_rate, Decimal("125.0000"))
        self.assertEqual(stock_for(self.product, self.warehouse), 1990)
        self.assertFalse(JournalEntry.objects.filter(description__icontains="SET-1").exists())

    def test_zero_reset_and_later_receipt(self):
        self._receive(quantity=5, unit_cost="10")
        adjust_stock_out(product=self.product, warehouse=self.warehouse, quantity=5,
            movement_date=self.day, reference="ADJ-Z", description="zero count", user=self.user)
        self.assertIsNone(avco_for(self.product, self.warehouse))
        self._receive(quantity=2, unit_cost="30", reference="RCV-NEW")
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("30.0000"))

    def test_adjustment_exact_retry_and_mismatch(self):
        kwargs = dict(product=self.product, warehouse=self.warehouse, quantity=2,
            unit_cost="10", currency=self.afn, movement_date=self.day, reference="ADJ-I",
            description="same", user=self.user, idempotency_key="adj-idem")
        first = adjust_stock_in(**kwargs)
        second = adjust_stock_in(**kwargs)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(StockMovement.objects.filter(idempotency_key="adj-idem").count(), 1)
        with self.assertRaises(InventoryValidationError):
            adjust_stock_in(**{**kwargs, "quantity": 3})

    def test_adjustment_failure_rolls_back_movement_audit_and_idempotency(self):
        before = (StockMovement.objects.count(), AuditEvent.objects.count(),
                  IdempotencyRecord.objects.count())
        with mock.patch("inventory.services.record_audit_event",
                        side_effect=RuntimeError("audit store down")):
            with self.assertRaises(RuntimeError):
                self._adjust_in(idempotency_key="ADJ-ROLLBACK")
        self.assertEqual((StockMovement.objects.count(), AuditEvent.objects.count(),
                          IdempotencyRecord.objects.count()), before)

    def test_waste_failure_rolls_back_usable_movement_audit_and_idempotency(self):
        before = (StockMovement.objects.count(), AuditEvent.objects.count(),
                  IdempotencyRecord.objects.count())
        with mock.patch("inventory.services.record_audit_event",
                        side_effect=RuntimeError("audit store down")):
            with self.assertRaises(RuntimeError):
                receive_with_waste(
                    product=self.product, warehouse=self.warehouse,
                    gross_quantity=10, waste_quantity=1, total_cost="100",
                    currency=self.afn, movement_date=self.day, reference="W-ROLLBACK",
                    description="unloading failure", user=self.user,
                    idempotency_key="WASTE-ROLLBACK")
        self.assertEqual((StockMovement.objects.count(), AuditEvent.objects.count(),
                          IdempotencyRecord.objects.count()), before)

    def test_shortage_settlement_failure_rolls_back_settlement_and_audit(self):
        shortage = record_shortage(
            product=self.product, warehouse=self.warehouse, quantity=1,
            movement_date=self.day, reference="SH-ROLLBACK",
            description="later shortage", user=self.user,
            acknowledge_negative=True, temporary_unit_cost="2",
            temporary_currency=self.afn)
        before = (ShortageSettlement.objects.count(), AuditEvent.objects.count())
        with mock.patch("inventory.services.record_audit_event",
                        side_effect=RuntimeError("audit store down")):
            with self.assertRaises(RuntimeError):
                settle_shortage(
                    shortage=shortage, settlement_date=self.day,
                    actual_sales_rate="9", currency=self.afn, reference="SET-ROLLBACK",
                    user=self.user, idempotency_key="SET-ROLLBACK")
        self.assertEqual((ShortageSettlement.objects.count(), AuditEvent.objects.count()), before)

    def test_posted_adjustment_and_settlement_are_immutable(self):
        m = self._adjust_in()
        with self.assertRaises(PostedImmutabilityError):
            m.description = "changed"
            m.save()
        with self.assertRaises(PostedImmutabilityError):
            m.delete()
        shortage = record_shortage(product=self.product, warehouse=self.warehouse,
            quantity=1, movement_date=self.day, reference="SH-I", description="later",
            user=self.user, acknowledge_negative=True, temporary_unit_cost="2", temporary_currency=self.afn)
        settlement = settle_shortage(shortage=shortage, settlement_date=self.day,
            actual_sales_rate="9", currency=self.afn, reference="SET-I", user=self.user)
        with self.assertRaises(PostedImmutabilityError):
            settlement.delete()


class Stage65ReturnTests(InventoryFixture, TestCase):
    """Focused Stage 6.5 return contract tests."""

    def setUp(self):
        super().setUp()
        from parties.models import Party
        self.supplier = Party.objects.create(name="Supplier 65", is_supplier=True)
        self.customer = Party.objects.create(name="Customer 65", is_customer=True)

    def _purchase_source(self):
        return self._receive(quantity=100, unit_cost="10", currency=self.afn,
            reference="PI-65", warehouse=self.warehouse, party=self.supplier)

    def _sale_source(self):
        self._receive(quantity=100, unit_cost="12", reference="RCV-SALE-65")
        return self._issue(quantity=20, reference="SI-65", party=self.customer)

    def test_purchase_return_uses_original_cost_and_reduces_stock(self):
        source = self._purchase_source()
        self._receive(quantity=100, unit_cost="30", currency=self.afn,
                      reference="RCV-LATER-65")
        self.assertEqual(avco_for(self.product, self.warehouse), Decimal("20.0000"))
        result = purchase_return(product=self.product, warehouse=self.warehouse,
            supplier=self.supplier, source_movement=source, quantity=20,
            source_document="PI-65", movement_date=date(2026, 2, 1),
            description="Damaged goods returned to supplier", user=self.user)
        self.assertEqual(result.return_movement.movement_type, MovementType.PURCHASE_RETURN)
        self.assertEqual(result.return_movement.quantity, -20)
        self.assertEqual(result.return_movement.unit_cost, Decimal("10.0000"))
        self.assertEqual(result.return_movement.currency.code, "AFN")
        self.assertEqual(result.return_movement.rate, Decimal("1.0000"))
        self.assertEqual(result.return_movement.qty_before, 200)
        self.assertEqual(result.return_movement.qty_after, 180)
        self.assertEqual(stock_for(self.product, self.warehouse), 180)
        event = AuditEvent.objects.get(entity="InventoryReturn", entity_id=result.id)
        self.assertEqual(event.new_state["source_movement_id"], source.id)
        self.assertEqual(event.new_state["return_movement_id"], result.return_movement_id)
        source.refresh_from_db()
        self.assertEqual(source.quantity, 100)

    def test_foreign_purchase_return_preserves_historical_rate(self):
        source = self._receive(quantity=10, unit_cost="10", currency=self.usd,
            rate="70", rate_date=self.day, reference="PI-USD-65",
            warehouse=self.warehouse, party=self.supplier)
        result = purchase_return(product=self.product, warehouse=self.warehouse,
            supplier=self.supplier, source_movement=source, quantity=2,
            source_document="PI-USD-65", movement_date=date(2026, 2, 1),
            description="Foreign currency return", user=self.user)
        self.assertEqual(result.return_movement.currency.code, "USD")
        self.assertEqual(result.return_movement.unit_cost, Decimal("10.0000"))
        self.assertEqual(result.return_movement.rate, Decimal("70.0000"))
        self.assertEqual(result.return_movement.rate_date, self.day)

    def test_sales_return_uses_original_sale_cost_not_current_avco(self):
        source = self._sale_source()
        # The sale is at 12; a later receipt changes current AVCO to 30.
        self._receive(quantity=100, unit_cost="30", reference="RCV-LATER")
        result = sales_return(product=self.product, warehouse=self.warehouse,
            customer=self.customer, source_movement=source, quantity=10,
            source_document="SI-65", movement_date=date(2026, 2, 1),
            description="Customer returned defective cartons", user=self.user)
        self.assertEqual(result.return_movement.quantity, 10)
        self.assertEqual(result.return_movement.unit_cost, Decimal("12.0000"))
        self.assertNotEqual(avco_for(self.product, self.warehouse), Decimal("12.0000"))
        source.refresh_from_db()
        self.assertEqual(source.quantity, -20)

    def test_partial_full_and_over_return(self):
        source = self._purchase_source()
        first = purchase_return(product=self.product, warehouse=self.warehouse,
            supplier=self.supplier, source_movement=source, quantity=20,
            source_document="PI-65", movement_date=self.day, description="first", user=self.user)
        second = purchase_return(product=self.product, warehouse=self.warehouse,
            supplier=self.supplier, source_movement=source, quantity=80,
            source_document="PI-65", movement_date=self.day, description="full", user=self.user)
        self.assertEqual(100, first.quantity + second.quantity)
        before = (StockMovement.objects.count(), InventoryReturn.objects.count(), AuditEvent.objects.count())
        with self.assertRaises(InventoryValidationError):
            purchase_return(product=self.product, warehouse=self.warehouse,
                supplier=self.supplier, source_movement=source, quantity=1,
                source_document="PI-65", movement_date=self.day, description="over", user=self.user)
        self.assertEqual((StockMovement.objects.count(), InventoryReturn.objects.count(), AuditEvent.objects.count()), before)

    def test_source_party_product_warehouse_and_document_mismatch_rejected(self):
        source = self._purchase_source()
        from parties.models import Party
        other_supplier = Party.objects.create(name="Other Supplier 65", is_supplier=True)
        for kwargs in (
            {"supplier": other_supplier},
            {"product": create_product(code="OTHER-65", name="Other 65", name_fa="دیگر", category=self.product.category, primary_uom=self.uom, user=self.user)},
            {"warehouse": create_warehouse(name="Other Warehouse 65", user=self.user)},
            {"source_document": "WRONG-65"},
        ):
            params = dict(product=self.product, warehouse=self.warehouse, supplier=self.supplier,
                source_movement=source, quantity=1, source_document="PI-65",
                movement_date=self.day, description="mismatch", user=self.user)
            params.update(kwargs)
            with self.assertRaises(InventoryValidationError):
                purchase_return(**params)
        self.assertEqual(InventoryReturn.objects.count(), 0)

    def test_returns_are_idempotent_and_mismatch_rejected(self):
        source = self._purchase_source()
        params = dict(product=self.product, warehouse=self.warehouse, supplier=self.supplier,
            source_movement=source, quantity=10, source_document="PI-65",
            movement_date=self.day, description="same", user=self.user,
            idempotency_key="RET-65")
        first = purchase_return(**params)
        second = purchase_return(**params)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(InventoryReturn.objects.count(), 1)
        self.assertEqual(StockMovement.objects.filter(reference="PI-65").count(), 2)
        with self.assertRaises(InventoryValidationError):
            purchase_return(**{**params, "quantity": 11})

    def test_return_and_audit_roll_back_on_late_failure(self):
        source = self._purchase_source()
        before = (StockMovement.objects.count(), InventoryReturn.objects.count(), AuditEvent.objects.count(), IdempotencyRecord.objects.count())
        with mock.patch("inventory.services.record_audit_event", side_effect=RuntimeError("audit down")):
            with self.assertRaises(RuntimeError):
                purchase_return(product=self.product, warehouse=self.warehouse,
                    supplier=self.supplier, source_movement=source, quantity=10,
                    source_document="PI-65", movement_date=self.day, description="fail",
                    user=self.user, idempotency_key="RET-ROLLBACK")
        self.assertEqual((StockMovement.objects.count(), InventoryReturn.objects.count(), AuditEvent.objects.count(), IdempotencyRecord.objects.count()), before)

    def test_return_and_source_are_immutable(self):
        source = self._purchase_source()
        result = purchase_return(product=self.product, warehouse=self.warehouse,
            supplier=self.supplier, source_movement=source, quantity=10,
            source_document="PI-65", movement_date=self.day, description="immutable", user=self.user)
        with self.assertRaises(PostedImmutabilityError):
            result.save()
        with self.assertRaises(PostedImmutabilityError):
            result.delete()
        with self.assertRaises(PostedImmutabilityError):
            source.quantity = 1
            source.save()

    def test_closed_period_rejects_return(self):
        source = self._purchase_source()
        period = create_period(name="FY65", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), user=self.user)
        close_period(period, user=self.user, reason="year end")
        with self.assertRaises(PeriodValidationError):
            purchase_return(product=self.product, warehouse=self.warehouse,
                supplier=self.supplier, source_movement=source, quantity=1,
                source_document="PI-65", movement_date=self.day, description="closed", user=self.user)
