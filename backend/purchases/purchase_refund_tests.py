from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from accounting.coa import seed_chart_of_accounts
from accounting.models import JournalEntry
from accounting.services import JournalValidationError
from currencies.models import Currency
from inventory.models import StockMovement, WarehouseInventoryAccount
from party_ledger.ledger import party_balance
from parties.services import create_party
from categories.services import create_category
from uom.services import create_uom
from products.services import create_product
from warehouses.services import create_warehouse

from .models import (
    PurchaseReturnStatus,
    SupplierRefundStatus,
)
from .services import create_purchase, post_purchase, post_purchase_return
from .supplier_refund_services import (
    SupplierRefundValidationError,
    create_supplier_refund,
    reverse_supplier_refund,
)
from .services import reverse_purchase_return


@pytest.fixture
def supplier_refund_setup(db):
    seed_chart_of_accounts()
    user = get_user_model().objects.create_user(username="supplier-refund-user", password="x")
    afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
    usd = Currency.objects.create(code="USD", name="US Dollar", is_base=False)
    supplier = create_party(name="Supplier Refund", is_supplier=True, user=user)
    category = create_category(name="Refund Category", user=user)
    uom = create_uom(name="Refund Unit", user=user)
    product = create_product(code="SRF-1", name="Refund Product", category=category, primary_uom=uom, user=user)
    warehouse = create_warehouse(name="Refund Warehouse", user=user)
    inventory_account = __import__("accounting.models", fromlist=["Account"]).Account.objects.get(code="1410")
    WarehouseInventoryAccount.objects.create(warehouse=warehouse, account=inventory_account)
    purchase = create_purchase(
        supplier=supplier, purchase_date=date(2026, 9, 28), currency=usd,
        warehouse=warehouse, rate="70", rate_date=date(2026, 9, 28),
        lines=[{"product": product, "quantity": 100, "unit_price": "100"}],
        user=user, document_number="PI-SRF-1",
    )
    purchase = post_purchase(purchase=purchase, user=user, idempotency_key="srf-purchase")
    source = StockMovement.objects.get(reference__startswith="PI-SRF-1:LINE:")
    returned = post_purchase_return(
        purchase=purchase, product=product, quantity=10, source_movement=source,
        return_date=date(2026, 9, 29), reason="Defective goods", user=user,
        document_number="PRTN-SRF-1", idempotency_key="srf-return",
    )
    return user, afn, usd, supplier, returned


def test_usd_supplier_claim_refunded_in_afn_uses_manual_rate_without_fx_gain_loss(supplier_refund_setup):
    user, afn, usd, supplier, returned = supplier_refund_setup
    refund = create_supplier_refund(
        purchase_return=returned, refund_date=date(2026, 9, 30),
        refund_currency=afn, claim_amount="1000", rate="70",
        reason="Supplier cash refund", user=user,
        document_number="SRF-1", idempotency_key="srf-1",
    )
    assert refund.status == SupplierRefundStatus.POSTED
    assert refund.claim_amount == Decimal("1000.00")
    assert refund.refund_amount == Decimal("70000.00")
    assert refund.claim_currency_id == usd.id
    assert refund.refund_currency_id == afn.id
    assert refund.rate_direction == "USD->AFN"
    assert refund.journal_entry.currency_id == afn.id
    assert refund.journal_entry.lines.get(account__code="1110").debit == Decimal("70000.00")
    assert refund.journal_entry.lines.get(account__code="1910").credit == Decimal("70000.00")
    cross = refund.cross_currency_refund
    assert cross.claim_journal.currency_id == usd.id
    assert cross.claim_journal.lines.get(account__code="1910").debit == Decimal("1000.00")
    assert cross.claim_journal.lines.get(account__code="2110").credit == Decimal("1000.00")
    assert cross.claim_journal.lines.get(account__code="2110").party_ledger_attribution.party_id == supplier.id
    assert not JournalEntry.objects.filter(source_type="SUPPLIER_REFUND_CROSS_CURRENCY").filter(
        lines__account__code__in=["8100", "8200"]
    ).exists()
    assert party_balance(supplier, currency=usd, balance_type="PAYABLE")["balance"] == Decimal("8000.00")


def test_supplier_refund_partial_and_multiple_settlements_cannot_exceed_claim(supplier_refund_setup):
    user, afn, usd, supplier, returned = supplier_refund_setup
    first = create_supplier_refund(
        purchase_return=returned, refund_date=date(2026, 9, 30),
        refund_currency=afn, claim_amount="400", rate="70",
        user=user, document_number="SRF-2A", idempotency_key="srf-2a",
    )
    second = create_supplier_refund(
        purchase_return=returned, refund_date=date(2026, 10, 1),
        refund_currency=afn, claim_amount="600", rate="70",
        user=user, document_number="SRF-2B", idempotency_key="srf-2b",
    )
    assert first.refund_amount + second.refund_amount == Decimal("70000.00")
    with pytest.raises(SupplierRefundValidationError, match="remaining supplier claim"):
        create_supplier_refund(
            purchase_return=returned, refund_date=date(2026, 10, 2),
            refund_currency=afn, claim_amount="0.01", rate="70",
            user=user, document_number="SRF-2C", idempotency_key="srf-2c",
        )


def test_supplier_refund_idempotency_returns_same_document(supplier_refund_setup):
    user, afn, usd, supplier, returned = supplier_refund_setup
    kwargs = dict(
        purchase_return=returned, refund_date=date(2026, 9, 30),
        refund_currency=afn, claim_amount="1000", rate="70",
        user=user, document_number="SRF-3", idempotency_key="srf-3",
    )
    first = create_supplier_refund(**kwargs)
    second = create_supplier_refund(**kwargs)
    assert first.pk == second.pk


def test_supplier_refund_reversal_restores_supplier_claim_and_blocks_independent_cross_leg_reversal(supplier_refund_setup):
    user, afn, usd, supplier, returned = supplier_refund_setup
    refund = create_supplier_refund(
        purchase_return=returned, refund_date=date(2026, 9, 30),
        refund_currency=afn, claim_amount="1000", rate="70",
        user=user, document_number="SRF-4", idempotency_key="srf-4",
    )
    with pytest.raises(JournalValidationError, match="refund aggregate"):
        from accounting.services import reverse_journal
        reverse_journal(refund.cross_currency_refund.claim_journal, "wrong path", user)
    reverse_supplier_refund(refund, reason="Supplier refund correction", user=user, idempotency_key="srf-4-rev")
    refund.refresh_from_db()
    assert refund.status == SupplierRefundStatus.REVERSED
    refund.cross_currency_refund.claim_journal.refresh_from_db()
    refund.cross_currency_refund.cash_journal.refresh_from_db()
    assert refund.cross_currency_refund.claim_journal.status == "REVERSED"
    assert refund.cross_currency_refund.cash_journal.status == "REVERSED"
    assert party_balance(supplier, currency=usd, balance_type="PAYABLE")["balance"] == Decimal("9000.00")


def test_purchase_return_cannot_be_reversed_while_supplier_refund_is_active(supplier_refund_setup):
    user, afn, usd, supplier, returned = supplier_refund_setup
    create_supplier_refund(
        purchase_return=returned, refund_date=date(2026, 9, 30),
        refund_currency=afn, claim_amount="500", rate="70",
        user=user, document_number="SRF-5", idempotency_key="srf-5",
    )
    with pytest.raises(Exception, match="Reverse all posted Supplier Refunds"):
        reverse_purchase_return(returned, reason="Should be blocked", user=user, idempotency_key="srf-5-return-rev")


def test_purchase_return_can_be_reversed_after_supplier_refund_is_reversed(supplier_refund_setup):
    user, afn, usd, supplier, returned = supplier_refund_setup
    refund = create_supplier_refund(
        purchase_return=returned, refund_date=date(2026, 9, 30),
        refund_currency=afn, claim_amount="1000", rate="70",
        user=user, document_number="SRF-6", idempotency_key="srf-6",
    )
    reverse_supplier_refund(refund, reason="Undo refund", user=user, idempotency_key="srf-6-rev")
    result = reverse_purchase_return(returned, reason="Undo return", user=user, idempotency_key="srf-6-return-rev")
    assert result.status == PurchaseReturnStatus.REVERSED


def test_same_currency_supplier_refund_clears_claim_directly(supplier_refund_setup):
    user, afn, usd, supplier, returned = supplier_refund_setup
    refund = create_supplier_refund(
        purchase_return=returned, refund_date=date(2026, 9, 30),
        refund_currency=usd, claim_amount="1000", rate="1",
        user=user, document_number="SRF-7", idempotency_key="srf-7",
    )
    assert not hasattr(refund, "cross_currency_refund")
    assert refund.journal_entry.currency_id == usd.id
    assert refund.journal_entry.lines.get(account__code="2110").debit == Decimal("1000.00")
    assert refund.journal_entry.lines.get(account__code="1110").credit == Decimal("1000.00")
