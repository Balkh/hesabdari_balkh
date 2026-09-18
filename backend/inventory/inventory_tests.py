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
from currencies.models import Currency
from products.services import create_product
from security.models import AuditAction, AuditEvent
from uom.services import create_uom
from warehouses.services import create_warehouse

from .models import (
    MovementType,
    StockMovement,
    WarehouseInventoryAccount,
)
from .services import (
    InventoryValidationError,
    assign_warehouse_account,
    issue_stock,
    open_stock,
    receive_stock,
    resolve_warehouse_account,
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
