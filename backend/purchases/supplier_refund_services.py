"""Phase 11 supplier claim/refund settlement services.

A PurchaseReturn creates the supplier claim (Dr 2110 / Cr inventory).
A SupplierRefund settles part or all of that claim. Cross-currency refunds
reuse the frozen 1910 technical clearing pattern and deliberately do not
create automatic FX gain/loss.
"""

from datetime import date as date_class
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum

from accounting.models import Account
from accounting.services import post_journal, reverse_journal
from core.dates import gregorian_to_jalali
from core.money import normalize_rate, quantize_half_up
from currencies.models import Currency
from documents.services import next_document_number
from fiscal_periods.services import assert_posting_date_open
from party_ledger.services import attribute_journal_line
from security.models import AuditAction
from security.services import record_audit_event

from .models import (
    CrossCurrencySupplierRefund,
    CrossCurrencySupplierRefundStatus,
    PurchaseReturn,
    PurchaseReturnStatus,
    SupplierRefund,
    SupplierRefundReversal,
    SupplierRefundStatus,
)


PAYABLE_ACCOUNT = "2110"
CASH_ACCOUNT = "1110"
CLEARING_ACCOUNT = "1910"


class SupplierRefundValidationError(ValueError):
    pass


def _actor(user):
    if user is not None and not getattr(user, "is_authenticated", False):
        raise SupplierRefundValidationError("Authenticated user required")
    return user


def _day(value):
    if isinstance(value, date_class):
        return value
    raise SupplierRefundValidationError("A date is required")


def _currency(ref):
    if isinstance(ref, Currency) and ref.pk:
        found = ref
    else:
        found = Currency.objects.filter(code=ref).first()
    if not found or not found.is_active:
        raise SupplierRefundValidationError("Currency does not exist or is inactive")
    return found


def _amount(value, label):
    try:
        result = quantize_half_up(Decimal(str(value)), 2)
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise SupplierRefundValidationError(f"{label} must be a valid positive amount") from exc
    if result <= 0:
        raise SupplierRefundValidationError(f"{label} must be greater than zero")
    return result


def _rate(value, claim_currency, refund_currency):
    if claim_currency.pk == refund_currency.pk:
        if value is not None and normalize_rate(Decimal(str(value))) != Decimal("1.0000"):
            raise SupplierRefundValidationError("Same-currency supplier refund rate must be 1.0000")
        return Decimal("1.0000"), f"{claim_currency.code}->{refund_currency.code}"
    if value is None:
        raise SupplierRefundValidationError("An explicit rate is required for a cross-currency supplier refund")
    try:
        result = normalize_rate(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise SupplierRefundValidationError("Supplier refund rate must be positive") from exc
    if result <= 0:
        raise SupplierRefundValidationError("Supplier refund rate must be positive")
    base = Currency.objects.filter(is_base=True).first()
    if base is None:
        raise SupplierRefundValidationError("No base currency is configured")
    if claim_currency.is_base == refund_currency.is_base:
        raise SupplierRefundValidationError(
            "Cross-currency supplier refund currently requires one leg in the base currency"
        )
    foreign = refund_currency if claim_currency.is_base else claim_currency
    return result, f"{foreign.code}->{base.code}" if claim_currency.is_base is False else f"{foreign.code}->{base.code}"


def _refund_amount(claim_amount, claim_currency, refund_currency, rate):
    if claim_currency.pk == refund_currency.pk:
        return claim_amount
    if not claim_currency.is_base and refund_currency.is_base:
        return quantize_half_up(claim_amount * rate, 2)
    if claim_currency.is_base and not refund_currency.is_base:
        return quantize_half_up(claim_amount / rate, 2)
    raise SupplierRefundValidationError("Cross-currency supplier refund requires one base-currency leg")


def _usable(code):
    try:
        account = Account.objects.get(code=code)
    except Account.DoesNotExist as exc:
        raise SupplierRefundValidationError(f"Account {code} does not exist") from exc
    if not account.is_active or not account.is_posting:
        raise SupplierRefundValidationError(f"Account {code} is not usable for posting")
    return account


def _year(day):
    return int(gregorian_to_jalali(day).split("/")[0])


def _remaining_claim(ret):
    used = ret.refunds.filter(status=SupplierRefundStatus.POSTED).aggregate(
        value=Sum("claim_amount")
    )["value"] or Decimal("0.00")
    return quantize_half_up(ret.amount - used, 2)


def _same_currency_journal(*, refund, actor):
    payable = _usable(PAYABLE_ACCOUNT)
    cash = _usable(CASH_ACCOUNT)
    entry = post_journal(
        number=next_document_number("JE", _year(refund.refund_date)),
        posting_date=refund.refund_date,
        description=f"Supplier refund {refund.document_number}",
        lines=[
            {"account": payable, "debit": refund.claim_amount,
             "reference": refund.document_number, "description": "Settle supplier return claim"},
            {"account": cash, "credit": refund.refund_amount,
             "reference": refund.document_number, "description": "Supplier cash refund"},
        ],
        source_type="SUPPLIER_REFUND",
        source_id=refund.document_number,
        currency=refund.claim_currency,
        rate=(
            Decimal("1.0000")
            if refund.claim_currency.is_base
            else refund.purchase_return.journal_entry.rate
        ),
        rate_date=(
            refund.refund_date
            if refund.claim_currency.is_base
            else refund.purchase_return.journal_entry.rate_date
        ),
        created_by=actor,
        idempotency_key=f"supplier-refund:{refund.document_number}:journal",
        allow_unvalued_foreign=(
            not refund.claim_currency.is_base
            and refund.purchase_return.journal_entry.rate is None
        ),
    )
    attribute_journal_line(
        entry.lines.get(account__code=PAYABLE_ACCOUNT),
        party=refund.purchase_return.supplier,
        user=actor,
    )
    return entry


def create_supplier_refund(
    *, purchase_return, refund_date, refund_currency, claim_amount,
    rate=None, reason="", user=None, document_number=None, idempotency_key=None,
):
    actor = _actor(user)
    if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 128:
        raise SupplierRefundValidationError("A valid supplier refund idempotency key is required")
    day = _day(refund_date)
    reason = str(reason).strip() or "Supplier refund"

    with transaction.atomic():
        ret = PurchaseReturn.objects.select_for_update().select_related(
            "supplier", "currency", "journal_entry", "purchase"
        ).get(pk=getattr(purchase_return, "pk", purchase_return))
        if ret.status != PurchaseReturnStatus.POSTED:
            raise SupplierRefundValidationError("Only a posted Purchase Return can be refunded")
        assert_posting_date_open(day)

        claim_currency = ret.currency
        cash_currency = _currency(refund_currency)
        amount = _amount(claim_amount, "Claim settlement amount")
        rate_value, direction = _rate(rate, claim_currency, cash_currency)
        refund_amount = _refund_amount(amount, claim_currency, cash_currency, rate_value)

        existing = SupplierRefund.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if (
                existing.purchase_return_id != ret.pk
                or existing.refund_date != day
                or existing.claim_amount != amount
                or existing.refund_currency_id != cash_currency.pk
                or existing.refund_amount != refund_amount
                or existing.agreed_rate != rate_value
                or existing.rate_direction != direction
                or existing.reason != reason
                or existing.created_by_id != (actor.pk if actor else None)
                or (document_number is not None and existing.document_number != document_number)
            ):
                raise SupplierRefundValidationError(
                    "This idempotency key was used for a different supplier refund"
                )
            return existing

        remaining = _remaining_claim(ret)
        if amount > remaining:
            raise SupplierRefundValidationError(
                f"Refund exceeds remaining supplier claim ({remaining})"
            )
        if document_number is None:
            document_number = next_document_number("SRF", _year(day))
        document_number = str(document_number).strip()
        if not document_number:
            raise SupplierRefundValidationError("Refund document number is required")
        if SupplierRefund.objects.filter(document_number=document_number).exists():
            raise SupplierRefundValidationError("Supplier refund document number already exists")

        refund = SupplierRefund.objects.create(
            document_number=document_number,
            purchase_return=ret,
            refund_date=day,
            claim_amount=amount,
            refund_amount=refund_amount,
            claim_currency=claim_currency,
            refund_currency=cash_currency,
            agreed_rate=rate_value,
            rate_direction=direction,
            status=SupplierRefundStatus.POSTED,
            reason=reason,
            idempotency_key=idempotency_key,
            created_by=actor,
        )

        if claim_currency.pk == cash_currency.pk:
            entry = _same_currency_journal(refund=refund, actor=actor)
            SupplierRefund.objects.filter(pk=refund.pk).update(journal_entry=entry)
            refund.journal_entry = entry
        else:
            clearing = _usable(CLEARING_ACCOUNT)
            payable = _usable(PAYABLE_ACCOUNT)
            cash = _usable(CASH_ACCOUNT)

            claim_entry = post_journal(
                number=next_document_number("JE", _year(day)),
                posting_date=day,
                description=f"Cross-currency supplier refund claim {document_number}",
                lines=[
                    {"account": clearing, "debit": amount, "reference": document_number,
                     "description": "Supplier claim settlement bridge"},
                    {"account": payable, "credit": amount, "reference": document_number,
                     "description": "Clear supplier return claim"},
                ],
                source_type="SUPPLIER_REFUND_CROSS_CURRENCY",
                source_id=document_number,
                currency=claim_currency,
                rate=ret.journal_entry.rate,
                rate_date=ret.journal_entry.rate_date,
                created_by=actor,
                idempotency_key=f"supplier-refund:{document_number}:claim",
                allow_unvalued_foreign=(
                    not claim_currency.is_base and ret.journal_entry.rate is None
                ),
            )
            attribute_journal_line(
                claim_entry.lines.get(account__code=PAYABLE_ACCOUNT),
                party=ret.supplier,
                user=actor,
            )

            cash_entry = post_journal(
                number=next_document_number("JE", _year(day)),
                posting_date=day,
                description=f"Cross-currency supplier refund cash {document_number}",
                lines=[
                    {"account": cash, "debit": refund_amount, "reference": document_number,
                     "description": "Supplier cash refund received"},
                    {"account": clearing, "credit": refund_amount, "reference": document_number,
                     "description": "Supplier refund bridge"},
                ],
                source_type="SUPPLIER_REFUND_CROSS_CURRENCY",
                source_id=document_number,
                currency=cash_currency,
                rate=(
                    Decimal("1.0000") if cash_currency.is_base
                    else rate_value
                ),
                rate_date=day,
                created_by=actor,
                idempotency_key=f"supplier-refund:{document_number}:cash",
            )

            SupplierRefund.objects.filter(pk=refund.pk).update(journal_entry=cash_entry)
            refund.journal_entry = cash_entry

            CrossCurrencySupplierRefund.objects.create(
                refund=refund,
                claim_currency=claim_currency,
                claim_amount=amount,
                refund_currency=cash_currency,
                refund_amount=refund_amount,
                agreed_rate=rate_value,
                rate_direction=direction,
                claim_journal=claim_entry,
                cash_journal=cash_entry,
                status=CrossCurrencySupplierRefundStatus.POSTED,
                idempotency_key=f"{idempotency_key}:cross",
            )

        record_audit_event(
            user=actor, action=AuditAction.CREATE, entity="SupplierRefund",
            entity_id=refund.pk, reference=document_number,
            previous_state=None,
            new_state={
                "purchase_return_id": ret.pk,
                "claim_amount": str(amount),
                "claim_currency": claim_currency.code,
                "refund_amount": str(refund_amount),
                "refund_currency": cash_currency.code,
                "rate": str(rate_value),
                "rate_direction": direction,
            },
            reason=reason,
        )
        return refund


def reverse_supplier_refund(refund, *, reason, user=None, idempotency_key=None):
    actor = _actor(user)
    if not isinstance(reason, str) or not reason.strip():
        raise SupplierRefundValidationError("A supplier refund reversal reason is required")
    if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 128:
        raise SupplierRefundValidationError("A valid supplier refund reversal idempotency key is required")

    with transaction.atomic():
        obj = SupplierRefund.objects.select_for_update().select_related(
            "purchase_return", "journal_entry"
        ).get(pk=getattr(refund, "pk", refund))
        if obj.status != SupplierRefundStatus.POSTED:
            raise SupplierRefundValidationError("Only a posted Supplier Refund can be reversed")
        existing = SupplierRefundReversal.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if existing.refund_id != obj.pk or existing.reason != reason or existing.created_by_id != (actor.pk if actor else None):
                raise SupplierRefundValidationError("This reversal idempotency key was used for a different refund reversal")
            return existing

        cross = getattr(obj, "cross_currency_refund", None)
        if cross is not None:
            if cross.status != CrossCurrencySupplierRefundStatus.POSTED:
                raise SupplierRefundValidationError("Cross-currency supplier refund is already reversed")
            claim_reversal = reverse_journal(
                cross.claim_journal, reason, actor, _allow_cross_currency_refund=True
            )
            cash_reversal = reverse_journal(
                cross.cash_journal, reason, actor, _allow_cross_currency_refund=True
            )
            CrossCurrencySupplierRefund.objects.filter(pk=cross.pk).update(
                status=CrossCurrencySupplierRefundStatus.REVERSED
            )
            reversal_entry = cash_reversal
            cross_reversal = cross
        else:
            reversal_entry = reverse_journal(obj.journal_entry, reason, actor)
            cross_reversal = None

        SupplierRefund.objects.filter(pk=obj.pk).update(status=SupplierRefundStatus.REVERSED)
        reversal = SupplierRefundReversal.objects.create(
            refund=obj,
            journal_entry=reversal_entry,
            cross_currency=cross_reversal,
            reason=reason,
            idempotency_key=idempotency_key,
            created_by=actor,
        )
        record_audit_event(
            user=actor, action=AuditAction.REVERSE, entity="SupplierRefund",
            entity_id=obj.pk, reference=obj.document_number,
            previous_state={"status": SupplierRefundStatus.POSTED},
            new_state={"status": SupplierRefundStatus.REVERSED, "reversal_id": reversal.pk},
            reason=reason,
        )
        return reversal
