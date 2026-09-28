from datetime import date as date_class
from decimal import Decimal, InvalidOperation

from django.db import transaction

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
from security.models import AuditAction
from security.services import record_audit_event

from .models import Payment, PaymentPurpose


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
                   rate=None, rate_date=None, idempotency_key=None):
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
    reversal = reverse_journal(payment.journal_entry, reason, actor)
    return reversal
