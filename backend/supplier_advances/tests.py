from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from accounting.coa import seed_chart_of_accounts
from accounting.models import JournalEntry
from currencies.models import Currency
from core.idempotency import IdempotencyRecord
from inventory.models import WarehouseInventoryAccount
from inventory.stock import stock_for
from party_ledger.ledger import party_balance, reconcile_party_ledger
from parties.services import create_party
from categories.services import create_category
from uom.services import create_uom
from products.services import create_product
from warehouses.services import create_warehouse
from purchases.services import create_purchase, post_purchase

from .models import SupplierAdvance, SupplierAdvanceStatus, SupplierAdvanceAllocation
from .services import (
    SupplierAdvanceValidationError,
    advance_available,
    allocate_supplier_advance,
    create_supplier_advance,
    reverse_supplier_advance,
    reverse_supplier_advance_allocation,
)


@pytest.fixture
def setup_supplier_advance(db):
    seed_chart_of_accounts()
    user = get_user_model().objects.create_user(username="supplier-advance-user", password="x")
    afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
    usd = Currency.objects.create(code="USD", name="US Dollar")
    supplier = create_party(name="Supplier Ahmad", is_supplier=True, user=user)
    category = create_category(name="Advance Category", user=user)
    uom = create_uom(name="Advance Unit", user=user)
    product = create_product(code="ADV-1", name="Advance Product", name_fa="محصول پیش‌پرداخت", category=category, primary_uom=uom, user=user)
    warehouse = create_warehouse(name="Advance Warehouse", user=user)
    WarehouseInventoryAccount.objects.create(
        warehouse=warehouse,
        account_id=__import__("accounting.models", fromlist=["Account"]).Account.objects.get(code="1410").pk,
    )
    return user, afn, usd, supplier, product, warehouse


def _purchase(user, currency, supplier, product, warehouse, *, rate=None, rate_date=None, total="50000", document_number="PI-ADV-1"):
    kwargs = dict(
        supplier=supplier,
        purchase_date=date(2026, 9, 28),
        currency=currency,
        warehouse=warehouse,
        lines=[{"product": product, "quantity": 1, "unit_price": total}],
        user=user,
        document_number=document_number,
    )
    if rate is not None:
        kwargs["rate"] = rate
    if rate_date is not None:
        kwargs["rate_date"] = rate_date
    purchase = create_purchase(**kwargs)
    return post_purchase(purchase=purchase, user=user)


def test_foreign_supplier_advance_requires_no_historical_rate(setup_supplier_advance):
    user, afn, usd, supplier, product, warehouse = setup_supplier_advance
    advance = create_supplier_advance(
        supplier=supplier, advance_date=date(2026, 9, 28), currency=usd,
        amount="10000", user=user, document_number="SADV-TEST-1",
        idempotency_key="sadv-test-1",
    )
    assert advance.status == SupplierAdvanceStatus.POSTED
    journal = advance.journal_entry
    assert journal.currency_id == usd.pk
    assert journal.rate is None
    assert journal.rate_date is None
    assert journal.afn_total is None
    assert journal.lines.get(account__code="1500").debit == Decimal("10000.00")
    assert journal.lines.get(account__code="1110").credit == Decimal("10000.00")
    assert journal.lines.get(account__code="1500").party_ledger_attribution.party_id == supplier.pk
    assert advance_available(advance) == Decimal("10000.00")


def test_supplier_advance_allocates_partial_amount_and_reduces_payable(setup_supplier_advance):
    user, afn, usd, supplier, product, warehouse = setup_supplier_advance
    advance = create_supplier_advance(
        supplier=supplier, advance_date=date(2026, 9, 28), currency=usd,
        amount="10000", user=user, document_number="SADV-TEST-2",
        idempotency_key="sadv-test-2",
    )
    purchase = _purchase(
        user, usd, supplier, product, warehouse, rate="70", rate_date=date(2026, 9, 28),
        total="5000", document_number="PI-ADV-2",
    )
    allocation = allocate_supplier_advance(
        advance=advance, purchase=purchase, amount="3000", user=user,
        idempotency_key="sadv-alloc-2",
    )
    assert allocation.amount == Decimal("3000.00")
    assert advance_available(advance) == Decimal("7000.00")
    assert party_balance(supplier, currency=usd, balance_type="SUPPLIER_ADVANCE")["balance"] == Decimal("7000.00")
    assert party_balance(supplier, currency=usd, balance_type="PAYABLE")["balance"] == Decimal("2000.00")
    journal = allocation.journal_entry
    assert journal.rate is None
    assert journal.rate_date is None
    assert journal.lines.get(account__code="2110").debit == Decimal("3000.00")
    assert journal.lines.get(account__code="1500").credit == Decimal("3000.00")


def test_supplier_advance_can_allocate_to_multiple_purchases(setup_supplier_advance):
    user, afn, usd, supplier, product, warehouse = setup_supplier_advance
    advance = create_supplier_advance(
        supplier=supplier, advance_date=date(2026, 9, 28), currency=usd,
        amount="10000", user=user, document_number="SADV-TEST-3",
        idempotency_key="sadv-test-3",
    )
    p1 = _purchase(user, usd, supplier, product, warehouse, rate="70", rate_date=date(2026, 9, 28), total="4000", document_number="PI-ADV-3A")
    p2 = _purchase(user, usd, supplier, product, warehouse, rate="70", rate_date=date(2026, 9, 28), total="6000", document_number="PI-ADV-3B")
    allocate_supplier_advance(advance=advance, purchase=p1, amount="4000", user=user, idempotency_key="sadv-alloc-3a")
    allocate_supplier_advance(advance=advance, purchase=p2, amount="6000", user=user, idempotency_key="sadv-alloc-3b")
    assert advance_available(advance) == Decimal("0.00")
    assert SupplierAdvanceAllocation.objects.filter(advance=advance).count() == 2


def test_supplier_advance_over_allocation_is_rejected_atomically(setup_supplier_advance):
    user, afn, usd, supplier, product, warehouse = setup_supplier_advance
    advance = create_supplier_advance(
        supplier=supplier, advance_date=date(2026, 9, 28), currency=usd,
        amount="1000", user=user, document_number="SADV-TEST-4",
        idempotency_key="sadv-test-4",
    )
    purchase = _purchase(user, usd, supplier, product, warehouse, rate="70", rate_date=date(2026, 9, 28), total="2000", document_number="PI-ADV-4")
    with pytest.raises(SupplierAdvanceValidationError):
        allocate_supplier_advance(advance=advance, purchase=purchase, amount="1001", user=user, idempotency_key="sadv-alloc-4")
    assert SupplierAdvanceAllocation.objects.count() == 0
    assert JournalEntry.objects.filter(source_type="SUPPLIER_ADVANCE_ALLOCATION").count() == 0
    assert advance_available(advance) == Decimal("1000.00")


def test_allocation_reversal_restores_advance_capacity(setup_supplier_advance):
    user, afn, usd, supplier, product, warehouse = setup_supplier_advance
    advance = create_supplier_advance(
        supplier=supplier, advance_date=date(2026, 9, 28), currency=usd,
        amount="10000", user=user, document_number="SADV-TEST-5",
        idempotency_key="sadv-test-5",
    )
    purchase = _purchase(user, usd, supplier, product, warehouse, rate="70", rate_date=date(2026, 9, 28), total="10000", document_number="PI-ADV-5")
    allocation = allocate_supplier_advance(advance=advance, purchase=purchase, amount="4000", user=user, idempotency_key="sadv-alloc-5")
    reversal = reverse_supplier_advance_allocation(allocation, reason="Correction", user=user, idempotency_key="sadv-alloc-rev-5")
    assert reversal.journal_entry is not None
    assert advance_available(advance) == Decimal("10000.00")
    assert party_balance(supplier, currency=usd, balance_type="SUPPLIER_ADVANCE")["balance"] == Decimal("10000.00")
    assert party_balance(supplier, currency=usd, balance_type="PAYABLE")["balance"] == Decimal("10000.00")


def test_advance_cannot_reverse_while_active_allocation_exists(setup_supplier_advance):
    user, afn, usd, supplier, product, warehouse = setup_supplier_advance
    advance = create_supplier_advance(
        supplier=supplier, advance_date=date(2026, 9, 28), currency=usd,
        amount="10000", user=user, document_number="SADV-TEST-6",
        idempotency_key="sadv-test-6",
    )
    purchase = _purchase(user, usd, supplier, product, warehouse, rate="70", rate_date=date(2026, 9, 28), total="10000", document_number="PI-ADV-6")
    allocate_supplier_advance(advance=advance, purchase=purchase, amount="1000", user=user, idempotency_key="sadv-alloc-6")
    with pytest.raises(SupplierAdvanceValidationError):
        reverse_supplier_advance(advance, reason="Wrong", user=user, idempotency_key="sadv-rev-6")
    advance.refresh_from_db()
    assert advance.status == SupplierAdvanceStatus.POSTED


def test_advance_reversal_uses_frozen_journal_reversal(setup_supplier_advance):
    user, afn, usd, supplier, product, warehouse = setup_supplier_advance
    advance = create_supplier_advance(
        supplier=supplier, advance_date=date(2026, 9, 28), currency=usd,
        amount="1000", user=user, document_number="SADV-TEST-7",
        idempotency_key="sadv-test-7",
    )
    original_id = advance.journal_entry_id
    reversed = reverse_supplier_advance(advance, reason="Refunded", user=user, idempotency_key="sadv-rev-7")
    advance.refresh_from_db()
    assert advance.status == SupplierAdvanceStatus.REVERSED
    assert advance.journal_entry_id == original_id
    advance.journal_entry.refresh_from_db()
    assert advance.journal_entry.status == "REVERSED"
    assert reversed.pk == advance.pk
    assert party_balance(supplier, currency=usd, balance_type="SUPPLIER_ADVANCE")["balance"] == Decimal("0.00")
    assert reconcile_party_ledger(currency=usd)["reconciled"] is True


def test_supplier_advance_idempotency_returns_same_document(setup_supplier_advance):
    user, afn, usd, supplier, product, warehouse = setup_supplier_advance
    kwargs = dict(
        supplier=supplier, advance_date=date(2026, 9, 28), currency=usd, amount="2500",
        user=user, idempotency_key="sadv-idempotent",
    )
    first = create_supplier_advance(**kwargs)
    second = create_supplier_advance(**kwargs)
    assert second.pk == first.pk
    assert SupplierAdvance.objects.count() == 1
    assert IdempotencyRecord.objects.filter(key="sadv-idempotent").count() == 1
