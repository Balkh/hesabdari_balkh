from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from accounting.models import Account, JournalStatus
from accounting.balances import account_balance
from core.idempotency import IdempotencyRecord
from currencies.models import Currency
from parties.models import Party
from party_ledger.models import BalanceType

from .models import Payment, PaymentPurpose
from .services import PaymentValidationError, create_payment, reverse_payment


@pytest.fixture
def setup_payment(db):
    user = get_user_model().objects.create_user(username="payment-user")
    afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
    customer = Party.objects.create(name="Ahmad", is_customer=True)
    Account.objects.create(code="1110", name="Cash", account_type="ASSET")
    Account.objects.create(code="1310", name="Trade Receivables", account_type="ASSET")
    Account.objects.create(code="2200", name="Customer Credit", account_type="LIABILITY")
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


def test_idempotent_retry_returns_same_payment(setup_payment):
    user, afn, customer = setup_payment
    kwargs = dict(party=customer, payment_date=date(2026, 9, 28), currency=afn, amount=300,
                  user=user, document_number="PMT-TEST-4", idempotency_key="payment-test-key")
    first = create_payment(**kwargs)
    second = create_payment(**kwargs)
    assert second.pk == first.pk
    assert Payment.objects.count() == 1
    assert IdempotencyRecord.objects.filter(key="payment-test-key").count() == 1


def test_idempotency_key_reuse_with_different_payment_rejected(setup_payment):
    user, afn, customer = setup_payment
    create_payment(party=customer, payment_date=date(2026, 9, 28), currency=afn, amount=300,
                   user=user, document_number="PMT-TEST-5", idempotency_key="payment-test-key-2")
    with pytest.raises(PaymentValidationError):
        create_payment(party=customer, payment_date=date(2026, 9, 28), currency=afn, amount=301,
                       user=user, document_number="PMT-TEST-6", idempotency_key="payment-test-key-2")


def test_reversal_uses_frozen_journal_reversal(setup_payment):
    user, afn, customer = setup_payment
    payment = create_payment(party=customer, payment_date=date(2026, 9, 28), currency=afn,
                             amount=400, user=user, document_number="PMT-TEST-7")
    reversal = reverse_payment(payment, reason="Correction", user=user)
    payment.journal_entry.refresh_from_db()
    assert payment.journal_entry.status == JournalStatus.REVERSED
    assert reversal.reverses_id == payment.journal_entry_id
