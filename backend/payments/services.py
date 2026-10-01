from datetime import date as date_class
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from accounting.models import Account
from accounting.services import _as_date, post_journal, reverse_journal
from core.dates import gregorian_to_jalali
from core.idempotency import DuplicateOperationError, IdempotencyRecord, idempotent_operation
from core.money import quantize_half_up
from currencies.models import Currency
from documents.services import next_document_number
from parties.models import Party
from parties.services import PartyValidationError, resolve_party as resolve_party_frozen
from party_ledger.services import attribute_journal_line
from fiscal_periods.services import assert_posting_date_open
from allocations.models import CustomerAllocation
from security.models import AuditAction
from security.services import record_audit_event

from .models import Payment, PaymentPurpose, CrossCurrencySettlement, CrossCurrencySettlementStatus


class PaymentValidationError(ValueError):
    pass


CASH_ACCOUNT = "1110"
PURPOSE_ACCOUNTS = {
    PaymentPurpose.RECEIVABLE: "1310",
    PaymentPurpose.CUSTOMER_CREDIT: "2200",
}
OPERATION = "payment.create"


def _actor(user):
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        raise PaymentValidationError("Authorization required to create a payment.")
    return user


def _resolve_party(ref):
    try:
        party = resolve_party_frozen(ref)
    except PartyValidationError as exc:
        raise PaymentValidationError(str(exc)) from exc
    if not party.is_customer:
        raise PaymentValidationError("Party is not a customer.")
    if not party.is_active:
        raise PaymentValidationError("Customer is not active.")
    return party


def _resolve_currency(ref):
    if isinstance(ref, Currency) and ref.pk is not None:
        return ref
    if isinstance(ref, str) and ref:
        found = Currency.objects.filter(code=ref).first()
        if found is not None:
            return found
    raise PaymentValidationError("Currency does not exist.")


def _amount(value):
    try:
        amount = quantize_half_up(Decimal(str(value)), 2)
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise PaymentValidationError("Amount must be a valid positive number.") from exc
    if amount <= 0:
        raise PaymentValidationError("Amount must be greater than zero.")
    return amount


def _snapshot(payment):
    return {
        "id": payment.pk,
        "document_number": payment.document_number,
        "party_id": payment.party_id,
        "party_name": payment.party.name,
        "payment_date": payment.payment_date.isoformat(),
        "currency": payment.currency.code,
        "amount": str(payment.amount),
        "purpose": payment.purpose,
        "journal_entry_id": payment.journal_entry_id,
        "description": payment.description,
        "reference": payment.reference,
    }


def _fingerprint(*, party, payment_date, currency, amount, purpose, description, reference, number):
    return "|".join([
        str(party.pk), str(payment_date), str(currency.pk), str(amount),
        str(purpose), description, reference, number,
    ])


def _retry(key, fingerprint):
    record = IdempotencyRecord.objects.get(key=key)
    stored = record.response_body or {}
    if stored.get("fingerprint") != fingerprint:
        raise PaymentValidationError("This idempotency key was used for a different payment.")
    payment_id = stored.get("payment_id")
    if not payment_id:
        raise DuplicateOperationError("Original payment is still in progress; retry.")
    return Payment.objects.select_related("journal_entry", "party", "currency").get(pk=payment_id)


@transaction.atomic
def create_payment(*, party, payment_date, currency, amount, purpose=PaymentPurpose.RECEIVABLE,
                   description="", reference="", user=None, document_number=None,
                   rate=None, rate_date=None, idempotency_key=None,
                   credit_account_code=None, allow_unvalued_foreign=False):
    """Record one customer cash receipt without invoice allocation.

    RECEIVABLE posts Dr 1110 / Cr 1310. CUSTOMER_CREDIT posts Dr 1110 / Cr 2200.
    Invoice allocation is deliberately out of scope for this phase.
    """
    actor = _actor(user)
    party = _resolve_party(party)
    currency = _resolve_currency(currency)
    if not currency.is_active:
        raise PaymentValidationError("Currency is not active.")
    payment_day = _as_date(payment_date, "payment_date") if not isinstance(payment_date, date_class) else payment_date
    amount = _amount(amount)
    if purpose not in PaymentPurpose.values:
        raise PaymentValidationError("Invalid payment purpose.")
    description = str(description).strip()
    reference = str(reference).strip()
    if document_number is None:
        document_number = next_document_number("PMT", int(gregorian_to_jalali(payment_day).split("/")[0]))
    if not isinstance(document_number, str) or not document_number.strip():
        raise PaymentValidationError("Document number is required.")
    document_number = document_number.strip()
    cash = Account.objects.get(code=CASH_ACCOUNT)
    if credit_account_code is not None:
        if purpose != PaymentPurpose.RECEIVABLE:
            raise PaymentValidationError("Cross-currency settlement payments must use RECEIVABLE purpose.")
        obligation = Account.objects.get(code=str(credit_account_code))
    else:
        obligation = Account.objects.get(code=PURPOSE_ACCOUNTS[purpose])
    if not cash.is_active or not cash.is_posting or not obligation.is_active or not obligation.is_posting:
        raise PaymentValidationError("Payment accounts are not usable for posting.")

    fingerprint = _fingerprint(party=party, payment_date=payment_day, currency=currency,
                               amount=amount, purpose=purpose, description=description,
                               reference=reference, number=document_number)
    if idempotency_key is not None:
        try:
            with idempotent_operation(key=idempotency_key, operation=OPERATION) as record:
                with transaction.atomic():
                    entry = post_journal(
                        number=next_document_number("JE", int(gregorian_to_jalali(payment_day).split("/")[0])),
                        posting_date=payment_day,
                        description=description or f"Customer payment {document_number}",
                        lines=[
                            {"account": cash, "debit": amount, "description": "Customer cash receipt", "reference": reference or document_number},
                            {"account": obligation, "credit": amount, "description": "Customer payment", "reference": reference or document_number},
                        ], source_type="PAYMENT", source_id=document_number,
                        currency=currency, rate=rate, rate_date=rate_date,
                        created_by=actor, idempotency_key=f"{idempotency_key}:journal",
                        allow_unvalued_foreign=allow_unvalued_foreign,
                    )
                    if credit_account_code is None:
                        party_line = entry.lines.get(account=obligation)
                        attribute_journal_line(party_line, party=party, user=actor)
                    payment = Payment.objects.create(
                        document_number=document_number, party=party, payment_date=payment_day,
                        currency=currency, amount=amount, purpose=purpose, journal_entry=entry,
                        description=description, reference=reference,
                    )
                    record_audit_event(user=actor, action=AuditAction.CREATE, entity="Payment",
                                       entity_id=payment.pk, reference=document_number,
                                       previous_state=None, new_state=_snapshot(payment), reason="")
                    record.response_body = {"payment_id": payment.pk, "fingerprint": fingerprint}
                    record.save(update_fields=["response_body"])
                    return payment
        except DuplicateOperationError:
            if IdempotencyRecord.objects.filter(key=idempotency_key).exists():
                return _retry(idempotency_key, fingerprint)
            raise

    entry = post_journal(
        number=next_document_number("JE", int(gregorian_to_jalali(payment_day).split("/")[0])),
        posting_date=payment_day, description=description or f"Customer payment {document_number}",
        lines=[
            {"account": cash, "debit": amount, "description": "Customer cash receipt", "reference": reference or document_number},
            {"account": obligation, "credit": amount, "description": "Customer payment", "reference": reference or document_number},
        ], source_type="PAYMENT", source_id=document_number,
        currency=currency, rate=rate, rate_date=rate_date, created_by=actor,
    )
    party_line = entry.lines.get(account=obligation)
    attribute_journal_line(party_line, party=party, user=actor)
    payment = Payment.objects.create(
        document_number=document_number, party=party, payment_date=payment_day,
        currency=currency, amount=amount, purpose=purpose, journal_entry=entry,
        description=description, reference=reference,
    )
    record_audit_event(user=actor, action=AuditAction.CREATE, entity="Payment",
                       entity_id=payment.pk, reference=document_number,
                       previous_state=None, new_state=_snapshot(payment), reason="")
    return payment


def reverse_payment(payment, *, reason, user=None):
    """Reverse the posted payment journal; the original Payment remains immutable."""
    actor = _actor(user)
    if not isinstance(payment, Payment):
        try:
            payment = Payment.objects.select_related("journal_entry").get(pk=payment)
        except Payment.DoesNotExist as exc:
            raise PaymentValidationError("Payment does not exist.") from exc
    if hasattr(payment, "cross_currency_settlement"):
        raise PaymentValidationError(
            "A cross-currency settlement payment must be reversed through the settlement aggregate."
        )
    reversal = reverse_journal(payment.journal_entry, reason, actor)
    return reversal


CROSS_CURRENCY_CLEARING_ACCOUNT = "1910"
CROSS_CURRENCY_OPERATION = "payment.cross_currency_settlement.create"
CROSS_CURRENCY_REVERSAL_OPERATION = "payment.cross_currency_settlement.reverse"


def _rate_8(value):
    try:
        rate_value = Decimal(str(value)).quantize(Decimal("0.00000001"))
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise PaymentValidationError("Settlement rate must be a valid positive number.") from exc
    if rate_value <= 0:
        raise PaymentValidationError("Settlement rate must be greater than zero.")
    return rate_value


def _ccs_amount(value, field):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise PaymentValidationError(f"{field} must be a valid positive number.") from exc
    if amount <= 0:
        raise PaymentValidationError(f"{field} must be greater than zero.")
    return amount


def _ccs_retry(key, fingerprint):
    record = IdempotencyRecord.objects.get(key=key)
    stored = record.response_body or {}
    if stored.get("fingerprint") != fingerprint:
        raise PaymentValidationError("This idempotency key was used for a different settlement.")
    settlement_id = stored.get("settlement_id")
    if not settlement_id:
        raise DuplicateOperationError("Original settlement is still in progress; retry.")
    return CrossCurrencySettlement.objects.select_related(
        "payment", "party", "debt_currency", "payment_currency",
        "cash_journal", "receivable_journal",
    ).get(pk=settlement_id)


@transaction.atomic
def create_cross_currency_settlement(*, party, payment_date, payment_currency,
                                      payment_amount, debt_currency, debt_amount,
                                      agreed_rate, user=None, document_number=None,
                                      description="", reference="", idempotency_key=None):
    """Record one payment whose currency differs from the customer's debt currency."""
    actor = _actor(user)
    if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 128:
        raise PaymentValidationError("A valid idempotency key is required.")
    party = _resolve_party(party)
    payment_currency = _resolve_currency(payment_currency)
    debt_currency = _resolve_currency(debt_currency)
    if payment_currency.pk == debt_currency.pk:
        raise PaymentValidationError("Cross-currency settlement requires different currencies.")
    payment_amount = _ccs_amount(payment_amount, "payment_amount")
    debt_amount = _ccs_amount(debt_amount, "debt_amount")
    rate = _rate_8(agreed_rate)
    expected_payment = (debt_amount * rate).quantize(Decimal("0.01"))
    if expected_payment != payment_amount:
        raise PaymentValidationError(
            "payment_amount must equal debt_amount multiplied by agreed_rate, rounded to 2 decimals."
        )
    payment_day = _as_date(payment_date, "payment_date") if not isinstance(payment_date, date_class) else payment_date
    fingerprint = "|".join([
        str(party.pk), str(payment_day), str(payment_currency.pk), str(payment_amount),
        str(debt_currency.pk), str(debt_amount), str(rate), str(document_number or ""),
        str(description).strip(), str(reference).strip(),
    ])
    try:
        with idempotent_operation(key=idempotency_key, operation=CROSS_CURRENCY_OPERATION) as record:
            with transaction.atomic():
                payment = create_payment(
                    party=party, payment_date=payment_day, currency=payment_currency,
                    amount=payment_amount, purpose=PaymentPurpose.RECEIVABLE,
                    description=description, reference=reference, user=actor,
                    document_number=document_number,
                    rate=None, rate_date=None,
                    idempotency_key=f"{idempotency_key}:payment",
                    credit_account_code=CROSS_CURRENCY_CLEARING_ACCOUNT,
                    allow_unvalued_foreign=True,
                )
                receivable = Account.objects.get(code=PURPOSE_ACCOUNTS[PaymentPurpose.RECEIVABLE])
                clearing = Account.objects.get(code=CROSS_CURRENCY_CLEARING_ACCOUNT)
                if not receivable.is_active or not receivable.is_posting or not clearing.is_active or not clearing.is_posting:
                    raise PaymentValidationError("Cross-currency settlement accounts are not usable for posting.")
                receivable_journal = post_journal(
                    number=next_document_number("JE", int(gregorian_to_jalali(payment_day).split("/")[0])),
                    posting_date=payment_day,
                    description=f"Cross-currency settlement {payment.document_number}",
                    lines=[
                        {"account": clearing, "debit": debt_amount, "description": "Cross-currency technical clearing", "reference": payment.document_number},
                        {"account": receivable, "credit": debt_amount, "description": "Customer receivable settlement", "reference": payment.document_number},
                    ],
                    source_type="CROSS_CURRENCY_SETTLEMENT",
                    source_id=idempotency_key,
                    currency=debt_currency,
                    rate=None, rate_date=None, created_by=actor,
                    idempotency_key=f"{idempotency_key}:receivable",
                    allow_unvalued_foreign=True,
                )
                attribute_journal_line(
                    receivable_journal.lines.get(account=receivable),
                    party=party, user=actor,
                )
                settlement = CrossCurrencySettlement.objects.create(
                    payment=payment, party=party,
                    debt_currency=debt_currency, debt_amount=debt_amount,
                    payment_currency=payment_currency, payment_amount=payment_amount,
                    agreed_rate=rate,
                    rate_direction=f"{payment_currency.code} per {debt_currency.code}",
                    settled_at=timezone.now(),
                    status=CrossCurrencySettlementStatus.POSTED,
                    idempotency_key=idempotency_key,
                    cash_journal=payment.journal_entry,
                    receivable_journal=receivable_journal,
                )
                record.response_body = {"settlement_id": settlement.pk, "fingerprint": fingerprint}
                record.save(update_fields=["response_body"])
                record_audit_event(
                    user=actor, action=AuditAction.CREATE, entity="CrossCurrencySettlement",
                    entity_id=settlement.pk, reference=idempotency_key,
                    previous_state=None,
                    new_state={"payment_id": payment.pk, "debt_currency": debt_currency.code,
                               "debt_amount": str(debt_amount), "payment_currency": payment_currency.code,
                               "payment_amount": str(payment_amount), "agreed_rate": str(rate)},
                    reason="",
                )
                return settlement
    except DuplicateOperationError:
        if IdempotencyRecord.objects.filter(key=idempotency_key).exists():
            return _ccs_retry(idempotency_key, fingerprint)
        raise


@transaction.atomic
def reverse_cross_currency_settlement(settlement, *, reason, user=None, idempotency_key=None):
    """Atomically reverse both settlement journal legs; never one leg alone."""
    actor = _actor(user)
    if not isinstance(reason, str) or not reason.strip():
        raise PaymentValidationError("A reversal reason is required.")
    if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 128:
        raise PaymentValidationError("A valid idempotency key is required.")
    settlement_id = getattr(settlement, "pk", settlement)
    try:
        settlement = CrossCurrencySettlement.objects.select_for_update().select_related(
            "payment", "cash_journal", "receivable_journal", "party"
        ).get(pk=settlement_id)
    except CrossCurrencySettlement.DoesNotExist as exc:
        raise PaymentValidationError("Cross-currency settlement does not exist.") from exc
    if settlement.status == CrossCurrencySettlementStatus.REVERSED:
        raise PaymentValidationError("Cross-currency settlement has already been reversed.")
    if CustomerAllocation.objects.filter(settlement=settlement).exclude(reversal__isnull=False).exists():
        raise PaymentValidationError("Reverse active customer allocations before reversing the settlement.")
    fingerprint = f"{settlement.pk}|{reason.strip()}"
    try:
        with idempotent_operation(key=idempotency_key, operation=CROSS_CURRENCY_REVERSAL_OPERATION) as record:
            with transaction.atomic():
                cash_reversal = reverse_journal(settlement.cash_journal, reason.strip(), actor)
                receivable_reversal = reverse_journal(settlement.receivable_journal, reason.strip(), actor)
                CrossCurrencySettlement.objects.filter(pk=settlement.pk).update(status=CrossCurrencySettlementStatus.REVERSED)
                record.response_body = {"settlement_id": settlement.pk,
                                        "cash_reversal_id": cash_reversal.pk,
                                        "receivable_reversal_id": receivable_reversal.pk,
                                        "fingerprint": fingerprint}
                record.save(update_fields=["response_body"])
                record_audit_event(
                    user=actor, action=AuditAction.REVERSE, entity="CrossCurrencySettlement",
                    entity_id=settlement.pk, reference=settlement.idempotency_key,
                    previous_state={"status": CrossCurrencySettlementStatus.POSTED},
                    new_state={"status": CrossCurrencySettlementStatus.REVERSED,
                               "cash_reversal_id": cash_reversal.pk,
                               "receivable_reversal_id": receivable_reversal.pk},
                    reason=reason.strip(),
                )
                return settlement
    except DuplicateOperationError:
        record = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if record is not None and (record.response_body or {}).get("fingerprint") == fingerprint:
            return CrossCurrencySettlement.objects.get(pk=settlement.pk)
        raise
