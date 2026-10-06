from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from accounting.coa import seed_chart_of_accounts
from accounting.models import JournalEntry
from currencies.models import Currency
from inventory.models import StockMovement, WarehouseInventoryAccount
from inventory.services import InventoryValidationError
from party_ledger.ledger import party_balance
from parties.services import create_party
from categories.services import create_category
from uom.services import create_uom
from products.services import create_product
from warehouses.services import create_warehouse

from .models import PurchaseReturn, PurchaseReturnStatus
from .services import (
    PurchaseValidationError,
    create_purchase,
    post_purchase,
    post_purchase_return,
    reverse_purchase_return,
)


@pytest.fixture
def purchase_return_setup(db):
    seed_chart_of_accounts()
    user = get_user_model().objects.create_user(username="purchase-return-user", password="x")
    usd = Currency.objects.create(code="USD", name="US Dollar", is_base=False)
    supplier = create_party(name="Supplier Return", is_supplier=True, user=user)
    category = create_category(name="Return Category", user=user)
    uom = create_uom(name="Return Unit", user=user)
    product = create_product(code="RET-1", name="Return Product", category=category, primary_uom=uom, user=user)
    warehouse = create_warehouse(name="Return Warehouse", user=user)
    inventory_account = __import__("accounting.models", fromlist=["Account"]).Account.objects.get(code="1410")
    WarehouseInventoryAccount.objects.create(warehouse=warehouse, account=inventory_account)
    purchase = create_purchase(
        supplier=supplier, purchase_date=date(2026, 9, 28), currency=usd,
        warehouse=warehouse, rate="70", rate_date=date(2026, 9, 28),
        lines=[{"product": product, "quantity": 100, "unit_price": "100"}],
        user=user, document_number="PI-RETURN-1",
    )
    purchase = post_purchase(purchase=purchase, user=user, idempotency_key="purchase-return-purchase")
    source = StockMovement.objects.get(reference__startswith="PI-RETURN-1:LINE:")
    return user, usd, supplier, product, warehouse, purchase, source


def test_purchase_return_reduces_stock_and_posts_supplier_claim(purchase_return_setup):
    user, usd, supplier, product, warehouse, purchase, source = purchase_return_setup
    result = post_purchase_return(
        purchase=purchase, product=product, quantity=10, source_movement=source,
        return_date=date(2026, 9, 29), reason="Defective goods", user=user,
        document_number="PRTN-1", idempotency_key="purchase-return-1",
    )
    assert result.status == PurchaseReturnStatus.POSTED
    assert result.quantity == 10
    assert result.amount == Decimal("1000.00")
    assert result.inventory_return.quantity == 10
    assert result.inventory_return.return_movement.quantity == -10
    assert result.journal_entry.lines.get(account__code="2110").debit == Decimal("1000.00")
    assert result.journal_entry.lines.get(account__code="1410").credit == Decimal("1000.00")
    assert result.journal_entry.rate == Decimal("70.0000")
    assert result.journal_entry.rate_date == date(2026, 9, 28)
    assert party_balance(supplier, currency=usd, balance_type="PAYABLE")["balance"] == Decimal("9000.00")


def test_purchase_return_cannot_return_more_than_remaining_source_quantity(purchase_return_setup):
    user, usd, supplier, product, warehouse, purchase, source = purchase_return_setup
    with pytest.raises(InventoryValidationError):
        post_purchase_return(
            purchase=purchase, product=product, quantity=101, source_movement=source,
            return_date=date(2026, 9, 29), reason="Too much", user=user,
            document_number="PRTN-2", idempotency_key="purchase-return-2",
        )
    assert PurchaseReturn.objects.count() == 0
    assert JournalEntry.objects.filter(source_type="PURCHASE_RETURN").count() == 0


def test_purchase_return_reversal_restores_stock_and_payable(purchase_return_setup):
    user, usd, supplier, product, warehouse, purchase, source = purchase_return_setup
    result = post_purchase_return(
        purchase=purchase, product=product, quantity=10, source_movement=source,
        return_date=date(2026, 9, 29), reason="Defective goods", user=user,
        document_number="PRTN-3", idempotency_key="purchase-return-3",
    )
    reversed_result = reverse_purchase_return(
        result, reason="Supplier accepted correction", user=user,
        idempotency_key="purchase-return-reversal-3",
    )
    result.refresh_from_db()
    assert result.status == PurchaseReturnStatus.REVERSED
    assert reversed_result.pk == result.pk
    assert party_balance(supplier, currency=usd, balance_type="PAYABLE")["balance"] == Decimal("10000.00")
    assert result.journal_entry.status == "REVERSED"
    assert result.reversal.stock_movement.quantity == 10


def test_purchase_return_idempotency_returns_same_document(purchase_return_setup):
    user, usd, supplier, product, warehouse, purchase, source = purchase_return_setup
    kwargs = dict(
        purchase=purchase, product=product, quantity=5, source_movement=source,
        return_date=date(2026, 9, 29), reason="Idempotent return", user=user,
        document_number="PRTN-4", idempotency_key="purchase-return-4",
    )
    first = post_purchase_return(**kwargs)
    second = post_purchase_return(**kwargs)
    assert first.pk == second.pk
    assert PurchaseReturn.objects.count() == 1
    assert JournalEntry.objects.filter(source_type="PURCHASE_RETURN").count() == 1


def test_purchase_return_cannot_use_receipt_from_another_purchase(purchase_return_setup):
    user, usd, supplier, product, warehouse, purchase, source = purchase_return_setup
    purchase2 = create_purchase(
        supplier=supplier, purchase_date=date(2026, 9, 29), currency=usd,
        warehouse=warehouse, rate="70", rate_date=date(2026, 9, 29),
        lines=[{"product": product, "quantity": 20, "unit_price": "100"}],
        user=user, document_number="PI-RETURN-2",
    )
    purchase2 = post_purchase(purchase=purchase2, user=user, idempotency_key="purchase-return-purchase-2")
    source2 = StockMovement.objects.get(reference__startswith="PI-RETURN-2:LINE:")
    with pytest.raises(PurchaseValidationError):
        post_purchase_return(
            purchase=purchase, product=product, quantity=1, source_movement=source2,
            return_date=date(2026, 9, 30), reason="Wrong purchase", user=user,
            document_number="PRTN-5", idempotency_key="purchase-return-5",
        )
