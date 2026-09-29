from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from accounting.coa import seed_chart_of_accounts
from accounting.models import Account, JournalStatus
from accounting.balances import account_balance
from currencies.models import Currency
from party_ledger.models import PartyLedgerAttribution
from parties.models import Party
from payments.models import PaymentPurpose
from payments.services import create_payment
from sales.models import PaymentMode, SalesChannel, SaleStatus
from sales.services import create_sale, finalize_sale

from .models import CustomerAllocation, CustomerAllocationReversal
from .services import AllocationValidationError, allocate_payment, invoice_outstanding, payment_available, reverse_allocation


@pytest.fixture
def allocation_setup(db):
    user = get_user_model().objects.create_user(username="allocation-user")
    afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
    usd = Currency.objects.create(code="USD", name="US Dollar", is_base=False)
    seed_chart_of_accounts()
    customer = Party.objects.create(name="Ahmad", is_customer=True)
    return user, afn, usd, customer


def make_credit_sale(user, customer, currency, total=Decimal("100.00"), number="SI-ALLOC-1"):
    sale = create_sale(
        customer=customer, sale_date=date(2026, 9, 28), currency=currency,
        channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
        lines=[{"product": 1, "unit": 1, "quantity": 1, "unit_price": total}],
        rate=None if currency.is_base else "70.0000", rate_date=None if currency.is_base else date(2026, 9, 28),
        user=user, document_number=number,
    )
    finalize_sale(sale=sale, user=user)
    return sale


@pytest.fixture
def master_data(allocation_setup):
    user, afn, usd, customer = allocation_setup
    from categories.models import Category
    from products.models import Product
    from uom.models import UnitOfMeasure
    category = Category.objects.create(name="Oil")
    unit = UnitOfMeasure.objects.create(name="Piece")
    product = Product.objects.create(code="OIL-001", name="Oil", name_fa="روغن", category=category, primary_uom=unit)
    return user, afn, usd, customer, product


def make_sale(user, customer, currency, product, total=Decimal("100.00"), number="SI-ALLOC-1"):
    sale = create_sale(
        customer=customer, sale_date=date(2026, 9, 28), currency=currency,
        channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CREDIT,
        lines=[{"product": product, "unit": product.primary_uom, "quantity": 1, "unit_price": total}],
        rate=None if currency.is_base else "70.0000", rate_date=None if currency.is_base else date(2026, 9, 28),
        user=user, document_number=number,
    )
    finalize_sale(sale=sale, user=user)
    return sale


def make_payment(user, customer, currency, amount, purpose=PaymentPurpose.RECEIVABLE, number="PMT-ALLOC-1"):
    return create_payment(party=customer, payment_date=date(2026, 9, 28), currency=currency,
                          amount=amount, purpose=purpose, user=user, document_number=number,
                          rate=None if currency.is_base else "70.0000", rate_date=None if currency.is_base else date(2026, 9, 28))


def test_full_same_currency_allocation_marks_invoice_paid_without_duplicate_cash(master_data):
    user, afn, usd, customer, product = master_data
    sale = make_sale(user, customer, afn, product)
    payment = make_payment(user, customer, afn, 100)
    allocation = allocate_payment(payment=payment, sale=sale, amount=100, user=user, idempotency_key="alloc-1")
    assert allocation.amount == Decimal("100.00")
    assert invoice_outstanding(sale) == Decimal("0.00")
    assert payment_available(payment) == Decimal("0.00")
    assert account_balance(Account.objects.get(code="1110"))["balance"] == Decimal("100.00")
    assert account_balance(Account.objects.get(code="4110"))["balance"] == Decimal("100.00")
    assert sale.journal_entry.lines.filter(account__code="1310").exists()


def test_partial_allocation_leaves_true_remainder(master_data):
    user, afn, usd, customer, product = master_data
    sale = make_sale(user, customer, afn, product, number="SI-ALLOC-2")
    payment = make_payment(user, customer, afn, 40, number="PMT-ALLOC-2")
    allocation = allocate_payment(payment=payment, sale=sale, amount=25, user=user, idempotency_key="alloc-2")
    assert allocation.amount == Decimal("25.00")
    assert invoice_outstanding(sale) == Decimal("75.00")
    assert payment_available(payment) == Decimal("15.00")


def test_multiple_payments_to_one_invoice(master_data):
    user, afn, usd, customer, product = master_data
    sale = make_sale(user, customer, afn, product, number="SI-ALLOC-3")
    p1 = make_payment(user, customer, afn, 40, number="PMT-ALLOC-3A")
    p2 = make_payment(user, customer, afn, 60, number="PMT-ALLOC-3B")
    allocate_payment(payment=p1, sale=sale, amount=40, user=user, idempotency_key="alloc-3a")
    allocate_payment(payment=p2, sale=sale, amount=60, user=user, idempotency_key="alloc-3b")
    assert invoice_outstanding(sale) == Decimal("0.00")


def test_one_payment_to_multiple_invoices(master_data):
    user, afn, usd, customer, product = master_data
    s1 = make_sale(user, customer, afn, product, number="SI-ALLOC-4A")
    s2 = make_sale(user, customer, afn, product, number="SI-ALLOC-4B")
    payment = make_payment(user, customer, afn, 100, number="PMT-ALLOC-4")
    allocate_payment(payment=payment, sale=s1, amount=40, user=user, idempotency_key="alloc-4a")
    allocate_payment(payment=payment, sale=s2, amount=60, user=user, idempotency_key="alloc-4b")
    assert invoice_outstanding(s1) == Decimal("60.00")
    assert invoice_outstanding(s2) == Decimal("40.00")
    assert payment_available(payment) == Decimal("0.00")


def test_overpayment_on_receivable_becomes_customer_credit(master_data):
    user, afn, usd, customer, product = master_data
    sale = make_sale(user, customer, afn, product, number="SI-ALLOC-5")
    payment = make_payment(user, customer, afn, 120, number="PMT-ALLOC-5")
    allocation = allocate_payment(payment=payment, sale=sale, amount=120, user=user, idempotency_key="alloc-5")
    assert allocation.amount == Decimal("100.00")
    assert allocation.credit_amount == Decimal("20.00")
    assert payment_available(payment) == Decimal("0.00")
    assert allocation.journal_entry.lines.get(account__code="1310").debit == Decimal("20.00")
    assert allocation.journal_entry.lines.get(account__code="2200").credit == Decimal("20.00")


def test_customer_credit_allocation_moves_2200_to_1310(master_data):
    user, afn, usd, customer, product = master_data
    sale = make_sale(user, customer, afn, product, number="SI-ALLOC-6")
    payment = make_payment(user, customer, afn, 100, purpose=PaymentPurpose.CUSTOMER_CREDIT, number="PMT-ALLOC-6")
    allocation = allocate_payment(payment=payment, sale=sale, amount=100, user=user, idempotency_key="alloc-6")
    assert allocation.journal_entry.lines.get(account__code="2200").debit == Decimal("100.00")
    assert allocation.journal_entry.lines.get(account__code="1310").credit == Decimal("100.00")
    assert invoice_outstanding(sale) == Decimal("0.00")


def test_cash_sale_rejected(master_data):
    user, afn, usd, customer, product = master_data
    sale = create_sale(customer=customer, sale_date=date(2026, 9, 28), currency=afn,
                       channel=SalesChannel.WHOLESALE, payment_mode=PaymentMode.CASH,
                       lines=[{"product": product, "unit": product.primary_uom, "quantity": 1, "unit_price": 100}],
                       user=user, document_number="SI-ALLOC-7")
    finalize_sale(sale=sale, user=user)
    payment = make_payment(user, customer, afn, 100, number="PMT-ALLOC-7")
    with pytest.raises(AllocationValidationError):
        allocate_payment(payment=payment, sale=sale, amount=100, user=user, idempotency_key="alloc-7")


def test_wrong_customer_rejected(master_data):
    user, afn, usd, customer, product = master_data
    other = Party.objects.create(name="Karim", is_customer=True)
    sale = make_sale(user, customer, afn, product, number="SI-ALLOC-8")
    payment = make_payment(user, other, afn, 100, number="PMT-ALLOC-8")
    with pytest.raises(AllocationValidationError):
        allocate_payment(payment=payment, sale=sale, amount=100, user=user, idempotency_key="alloc-8")


def test_cross_currency_is_rejected_not_faked(master_data):
    user, afn, usd, customer, product = master_data
    sale = make_sale(user, customer, usd, product, number="SI-ALLOC-9")
    payment = make_payment(user, customer, afn, 7000, number="PMT-ALLOC-9")
    with pytest.raises(AllocationValidationError, match="Cross-currency"):
        allocate_payment(payment=payment, sale=sale, amount=7000, user=user, idempotency_key="alloc-9")


def test_idempotent_retry_returns_same_allocation(master_data):
    user, afn, usd, customer, product = master_data
    sale = make_sale(user, customer, afn, product, number="SI-ALLOC-10")
    payment = make_payment(user, customer, afn, 100, number="PMT-ALLOC-10")
    first = allocate_payment(payment=payment, sale=sale, amount=100, user=user, idempotency_key="alloc-10")
    second = allocate_payment(payment=payment, sale=sale, amount=100, user=user, idempotency_key="alloc-10")
    assert first.pk == second.pk
    assert CustomerAllocation.objects.count() == 1


def test_allocation_reversal_restores_invoice_and_payment_capacity(master_data):
    user, afn, usd, customer, product = master_data
    sale = make_sale(user, customer, afn, product, number="SI-ALLOC-11")
    payment = make_payment(user, customer, afn, 100, number="PMT-ALLOC-11")
    allocation = allocate_payment(payment=payment, sale=sale, amount=100, user=user, idempotency_key="alloc-11")
    reversal = reverse_allocation(allocation, reason="Correction", user=user, idempotency_key="alloc-rev-11")
    assert isinstance(reversal, CustomerAllocationReversal)
    assert invoice_outstanding(sale) == Decimal("100.00")
    assert payment_available(payment) == Decimal("100.00")


def test_customer_credit_reversal_reverses_reclassification_journal(master_data):
    user, afn, usd, customer, product = master_data
    sale = make_sale(user, customer, afn, product, number="SI-ALLOC-12")
    payment = make_payment(user, customer, afn, 100, purpose=PaymentPurpose.CUSTOMER_CREDIT, number="PMT-ALLOC-12")
    allocation = allocate_payment(payment=payment, sale=sale, amount=100, user=user, idempotency_key="alloc-12")
    reversal = reverse_allocation(allocation, reason="Correction", user=user, idempotency_key="alloc-rev-12")
    allocation.journal_entry.refresh_from_db()
    assert allocation.journal_entry.status == JournalStatus.REVERSED
    assert reversal.journal_entry.reverses_id == allocation.journal_entry_id
    assert invoice_outstanding(sale) == Decimal("100.00")


def test_closed_period_rejects_allocation(master_data):
    user, afn, usd, customer, product = master_data
    from fiscal_periods.services import close_period, create_period
    period = create_period(name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), user=user)
    close_period(period, user=user)
    sale = make_sale(user, customer, afn, product, number="SI-ALLOC-13") if False else None
    # The frozen Sale/Payment posting gates already prevent documents in a closed period;
    # this assertion protects the explicit Phase 10 allocation gate with existing posted documents.
    period.delete()
    sale = make_sale(user, customer, afn, product, number="SI-ALLOC-13")
    payment = make_payment(user, customer, afn, 100, number="PMT-ALLOC-13")
    period = create_period(name="2026-closed", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), user=user)
    close_period(period, user=user)
    with pytest.raises(Exception):
        allocate_payment(payment=payment, sale=sale, amount=100, user=user, idempotency_key="alloc-13")
