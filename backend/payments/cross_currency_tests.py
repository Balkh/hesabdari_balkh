from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from accounting.coa import seed_chart_of_accounts
from accounting.models import Account, JournalStatus
from accounting.services import JournalValidationError, reverse_journal
from currencies.models import Currency
from parties.models import Party

from .models import CrossCurrencySettlement, CrossCurrencySettlementStatus, PaymentPurpose
from .services import (
    PaymentValidationError,
    create_cross_currency_settlement,
    reverse_cross_currency_settlement,
)


@pytest.fixture
def ccs_setup(db):
    user = get_user_model().objects.create_user(username="ccs-user")
    afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
    usd = Currency.objects.create(code="USD", name="US Dollar", is_base=False)
    seed_chart_of_accounts()
    customer = Party.objects.create(name="Ahmad", is_customer=True)
    return user, afn, usd, customer


def test_cross_currency_settlement_keeps_cash_and_debt_currencies_separate(ccs_setup):
    user, afn, usd, customer = ccs_setup
    settlement = create_cross_currency_settlement(
        party=customer, payment_date=date(2026, 9, 28),
        payment_currency=afn, payment_amount=Decimal("216000.00"),
        debt_currency=usd, debt_amount=Decimal("3000.00"),
        agreed_rate=Decimal("72"),
        user=user, document_number="PMT-CCS-1",
        idempotency_key="ccs-1",
    )
    assert settlement.payment.currency_id == afn.id
    assert settlement.debt_currency_id == usd.id
    assert settlement.payment_amount == Decimal("216000.00")
    assert settlement.debt_amount == Decimal("3000.00")
    assert settlement.agreed_rate == Decimal("72.00000000")
    assert settlement.cash_journal.currency_id == afn.id
    assert settlement.receivable_journal.currency_id == usd.id
    assert settlement.cash_journal.lines.get(account__code="1110").debit == Decimal("216000.00")
    assert settlement.cash_journal.lines.get(account__code="1910").credit == Decimal("216000.00")
    assert settlement.receivable_journal.lines.get(account__code="1910").debit == Decimal("3000.00")
    assert settlement.receivable_journal.lines.get(account__code="1310").credit == Decimal("3000.00")
    assert settlement.receivable_journal.lines.get(account__code="1310").party_ledger_attribution.party_id == customer.id
    assert settlement.cash_journal.afn_total is not None
    assert settlement.receivable_journal.afn_total is None


def test_cross_currency_settlement_is_idempotent(ccs_setup):
    user, afn, usd, customer = ccs_setup
    kwargs = dict(
        party=customer, payment_date=date(2026, 9, 28),
        payment_currency=afn, payment_amount=Decimal("216000.00"),
        debt_currency=usd, debt_amount=Decimal("3000.00"),
        agreed_rate=Decimal("72"), user=user,
        document_number="PMT-CCS-2", idempotency_key="ccs-2",
    )
    first = create_cross_currency_settlement(**kwargs)
    second = create_cross_currency_settlement(**kwargs)
    assert first.pk == second.pk
    assert CrossCurrencySettlement.objects.count() == 1


def test_cross_currency_settlement_rejects_rate_mismatch(ccs_setup):
    user, afn, usd, customer = ccs_setup
    with pytest.raises(PaymentValidationError, match="payment_amount"):
        create_cross_currency_settlement(
            party=customer, payment_date=date(2026, 9, 28),
            payment_currency=afn, payment_amount=Decimal("215000.00"),
            debt_currency=usd, debt_amount=Decimal("3000.00"),
            agreed_rate=Decimal("72"), user=user,
            document_number="PMT-CCS-3", idempotency_key="ccs-3",
        )


def test_cross_currency_settlement_reversal_is_atomic_and_blocks_independent_leg_reversal(ccs_setup):
    user, afn, usd, customer = ccs_setup
    settlement = create_cross_currency_settlement(
        party=customer, payment_date=date(2026, 9, 28),
        payment_currency=afn, payment_amount=Decimal("216000.00"),
        debt_currency=usd, debt_amount=Decimal("3000.00"),
        agreed_rate=Decimal("72"), user=user,
        document_number="PMT-CCS-4", idempotency_key="ccs-4",
    )
    with pytest.raises(JournalValidationError, match="settlement aggregate"):
        reverse_journal(settlement.receivable_journal, "wrong path", user)
    reversed_settlement = reverse_cross_currency_settlement(
        settlement, reason="Correction", user=user, idempotency_key="ccs-rev-4"
    )
    assert reversed_settlement.status == CrossCurrencySettlementStatus.REVERSED
    settlement.cash_journal.refresh_from_db()
    settlement.receivable_journal.refresh_from_db()
    assert settlement.cash_journal.status == JournalStatus.REVERSED
    assert settlement.receivable_journal.status == JournalStatus.REVERSED


def test_cross_currency_settlement_rejects_same_currency(ccs_setup):
    user, afn, usd, customer = ccs_setup
    with pytest.raises(PaymentValidationError, match="different currencies"):
        create_cross_currency_settlement(
            party=customer, payment_date=date(2026, 9, 28),
            payment_currency=afn, payment_amount=Decimal("3000.00"),
            debt_currency=afn, debt_amount=Decimal("3000.00"),
            agreed_rate=Decimal("1"), user=user,
            document_number="PMT-CCS-5", idempotency_key="ccs-5",
        )
