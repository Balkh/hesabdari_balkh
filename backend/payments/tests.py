from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from accounting.balances import account_balance
from accounting.coa import seed_chart_of_accounts
from accounting.models import Account, JournalStatus
from core.idempotency import IdempotencyRecord
from currencies.models import Currency
from fiscal_periods.services import close_period, create_period
from parties.models import Party

from .models import Payment, PaymentPurpose
from .services import PaymentValidationError, create_payment, reverse_payment


@pytest.fixture
def setup_payment(db):
    user = get_user_model().objects.create_user(username="payment-user")
    afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
    seed_chart_of_accounts()
    customer = Party.objects.create(name="Ahmad", is_customer=True)
    return user, afn, customer


def test_receivable_payment_posts_cash_and_customer_ledger(setup_payment):
    user, afn, customer = setup_payment
    payment = create_payment(party=customer, payment_date=date(2026, 9, 28), currency=afn,
                             amount="1000.005", user=user, document_number="PMT-TEST-1")
    assert payment.amount == Decimal("1000.01")
    assert payment.journal_entry.status == JournalStatus.POSTED
    assert list(payment.journal_entry.lines.values_list("account__code", "debit", "credit")) == [
        ("1110", Decimal("1000.01"), Decimal("0.00")),
        ("1310", Decimal("0.00"), Decimal("1000.01")),
    ]
    assert payment.journal_entry.lines.get(account__code="1310").party_ledger_attribution.party_id == customer.pk
    assert account_balance(Account.objects.get(code="1110"))["balance"] == Decimal("1000.01")


def test_customer_credit_payment_uses_2200(setup_payment):
    user, afn, customer = setup_payment
    payment = create_payment(party=customer, payment_date=date(2026, 9, 28), currency=afn,
                             amount=500, purpose=PaymentPurpose.CUSTOMER_CREDIT,
                             user=user, document_number="PMT-TEST-2")
    assert payment.journal_entry.lines.get(account__code="2200").credit == Decimal("500.00")
    assert payment.journal_entry.lines.get(account__code="2200").party_ledger_attribution.party_id == customer.pk


def test_payment_is_independent_of_sale_and_inventory(setup_payment):
    user, afn, customer = setup_payment
    payment = create_payment(party=customer, payment_date=date(2026, 9, 28), currency=afn,
                             amount=200, user=user, document_number="PMT-TEST-3")
    assert payment.journal_entry.source_type == "PAYMENT"
    assert payment.journal_entry.lines.filter(account__code__in=["4110", "4120"]).count() == 0


def test_foreign_currency_payment_requires_and_snapshots_manual_rate(setup_payment):
    user, afn, customer = setup_payment
    usd = Currency.objects.create(code="USD", name="US Dollar", is_base=False)
    payment = create_payment(party=customer, payment_date=date(2026, 9, 28), currency=usd,
                             amount=100, rate="68.2500", rate_date=date(2026, 9, 28),
                             user=user, document_number="PMT-TEST-4")
    assert payment.journal_entry.currency_id == usd.pk
    assert payment.journal_entry.rate == Decimal("68.2500")
    assert payment.journal_entry.rate_direction == "USD->AFN"


def test_foreign_currency_payment_without_rate_is_rejected(setup_payment):
    user, afn, customer = setup_payment
    usd = Currency.objects.create(code="USD", name="US Dollar", is_base=False)
    with pytest.raises(Exception):
        create_payment(party=customer, payment_date=date(2026, 9, 28), currency=usd,
                       amount=100, user=user, document_number="PMT-TEST-5")


def test_closed_period_rejects_payment(setup_payment):
    user, afn, customer = setup_payment
    period = create_period(name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), user=user)
    close_period(period, user=user)
    with pytest.raises(Exception):
        create_payment(party=customer, payment_date=date(2026, 9, 28), currency=afn,
                       amount=100, user=user, document_number="PMT-TEST-6")
    assert Payment.objects.count() == 0


def test_idempotent_retry_returns_same_payment(setup_payment):
    user, afn, customer = setup_payment
    kwargs = dict(party=customer, payment_date=date(2026, 9, 28), currency=afn, amount=300,
                  user=user, document_number="PMT-TEST-7", idempotency_key="payment-test-key")
    first = create_payment(**kwargs)
    second = create_payment(**kwargs)
    assert second.pk == first.pk
    assert Payment.objects.count() == 1
    assert IdempotencyRecord.objects.filter(key="payment-test-key").count() == 1


def test_idempotency_key_reuse_with_different_payment_rejected(setup_payment):
    user, afn, customer = setup_payment
    create_payment(party=customer, payment_date=date(2026, 9, 28), currency=afn, amount=300,
                   user=user, document_number="PMT-TEST-8", idempotency_key="payment-test-key-2")
    with pytest.raises(PaymentValidationError):
        create_payment(party=customer, payment_date=date(2026, 9, 28), currency=afn, amount=301,
                       user=user, document_number="PMT-TEST-9", idempotency_key="payment-test-key-2")


def test_reversal_uses_frozen_journal_reversal(setup_payment):
    user, afn, customer = setup_payment
    payment = create_payment(party=customer, payment_date=date(2026, 9, 28), currency=afn,
                             amount=400, user=user, document_number="PMT-TEST-10")
    reversal = reverse_payment(payment, reason="Correction", user=user)
    payment.journal_entry.refresh_from_db()
    assert payment.journal_entry.status == JournalStatus.REVERSED
    assert reversal.reverses_id == payment.journal_entry_id
