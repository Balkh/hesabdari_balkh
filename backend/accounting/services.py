from datetime import date as date_class
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from core.money import fx_equivalent, normalize_rate, quantize_half_up
from currencies.models import Currency
from .models import Account, JournalEntry, JournalLine, JournalStatus


class JournalValidationError(ValueError):
    pass


def _as_date(value, field_name):
    if isinstance(value, date_class):
        return value
    if isinstance(value, str):
        parsed = parse_date(value)
        if parsed is not None:
            return parsed
    raise JournalValidationError(f"{field_name} must be a date or ISO date string")


def _coerce_rate(rate):
    try:
        return normalize_rate(rate)
    except (TypeError, ArithmeticError, ValueError) as exc:
        raise JournalValidationError("rate must be a positive number") from exc


def post_journal(*, number, posting_date, description, lines, source_type="", source_id="",
                 currency=None, rate=None, rate_date=None, created_by=None):
    """Create and atomically post one balanced journal entry.

    Stage 2.2 contract: transaction currency is required; the rate snapshot
    (rate + rate date + direction) is resolved and stored; totals and the AFN
    equivalent are computed once and stored; each line may carry a reference.
    """
    if not lines:
        raise JournalValidationError("A journal entry requires at least one line")
    debit_total = sum((Decimal(str(line.get("debit", 0))) for line in lines), Decimal("0"))
    credit_total = sum((Decimal(str(line.get("credit", 0))) for line in lines), Decimal("0"))
    if debit_total != credit_total:
        raise JournalValidationError("Total debit must equal total credit")
    if debit_total <= 0:
        raise JournalValidationError("A posted journal entry must have a positive total")

    if not isinstance(currency, Currency):
        raise JournalValidationError("A transaction currency is required")
    if not currency.is_active:
        raise JournalValidationError("Transaction currency is not active")

    if created_by is not None and not isinstance(created_by, get_user_model()):
        raise JournalValidationError("created_by must be a user or None")

    posting_day = _as_date(posting_date, "posting_date")
    if currency.is_base:
        if rate is not None and _coerce_rate(rate) != 1:
            raise JournalValidationError("A base-currency journal must use rate 1")
        rate_value = Decimal("1.0000")
        rate_date_value = _as_date(rate_date, "rate_date") if rate_date is not None else posting_day
        direction = f"{currency.code}->{currency.code}"
        afn_total = quantize_half_up(debit_total, 2)
    else:
        base = Currency.objects.filter(is_base=True).first()
        if base is None:
            raise JournalValidationError("No base currency is configured")
        if rate is None:
            raise JournalValidationError("A rate is required for a foreign-currency journal")
        rate_value = _coerce_rate(rate)
        if rate_value <= 0:
            raise JournalValidationError("rate must be positive")
        if rate_date is None:
            raise JournalValidationError("rate_date is required for a foreign-currency journal")
        rate_date_value = _as_date(rate_date, "rate_date")
        direction = f"{currency.code}->{base.code}"
        afn_total = fx_equivalent(debit_total, rate_value)

    with transaction.atomic():
        entry = JournalEntry.objects.create(
            number=number, posting_date=posting_date, description=description,
            source_type=source_type, source_id=str(source_id), status=JournalStatus.POSTED,
            posted_at=timezone.now(),
            currency=currency,
            total_debit=quantize_half_up(debit_total, 2),
            total_credit=quantize_half_up(credit_total, 2),
            afn_total=afn_total, rate=rate_value, rate_date=rate_date_value,
            rate_direction=direction, created_by=created_by,
        )
        for line in lines:
            account = line["account"]
            if not isinstance(account, Account):
                raise JournalValidationError("Journal line account must be an Account")
            if not account.is_active or not account.is_posting:
                raise JournalValidationError("Journal line account is not usable for posting")
            reference = line.get("reference", "")
            if not isinstance(reference, str):
                raise JournalValidationError("Journal line reference must be text")
            JournalLine.objects.create(
                entry=entry, account=account,
                debit=Decimal(str(line.get("debit", 0))),
                credit=Decimal(str(line.get("credit", 0))),
                description=line.get("description", ""),
                reference=reference,
            )
        return entry


def verify_entry_totals(entry):
    """Recompute journal-line sums and reject any stored-total mismatch.

    Returns the recomputed {"total_debit", "total_credit"} when they agree.
    """
    if entry.total_debit is None or entry.total_credit is None:
        raise JournalValidationError("Stored journal totals are missing")
    lines = list(entry.lines.all())
    debit = sum((line.debit for line in lines), Decimal("0"))
    credit = sum((line.credit for line in lines), Decimal("0"))
    if entry.total_debit != debit or entry.total_credit != credit:
        raise JournalValidationError("Stored journal totals do not match journal lines")
    return {"total_debit": debit, "total_credit": credit}
