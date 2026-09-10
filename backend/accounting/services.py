import hashlib
import json
from datetime import date as date_class
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from core.dates import gregorian_to_jalali
from core.idempotency import DuplicateOperationError, IdempotencyRecord, idempotent_operation
from core.money import fx_equivalent, normalize_rate, quantize_half_up
from currencies.models import Currency
from documents.services import next_document_number
from security.models import AuditAction
from security.services import record_audit_event
from .models import Account, JournalEntry, JournalLine, JournalStatus


class JournalValidationError(ValueError):
    pass


IDEMPOTENT_POST_OPERATION = "journal.post"


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


def _persist_entry(*, number, posting_date, description, lines, source_type, source_id,
                   currency, debit_total, credit_total, afn_total, rate_value,
                   rate_date_value, direction, created_by, idempotency_key=None):
    """Insert one POSTED entry with its lines. Caller owns the transaction."""
    entry = JournalEntry.objects.create(
        number=number, posting_date=posting_date, description=description,
        source_type=source_type, source_id=str(source_id), status=JournalStatus.POSTED,
        posted_at=timezone.now(),
        currency=currency,
        total_debit=quantize_half_up(debit_total, 2),
        total_credit=quantize_half_up(credit_total, 2),
        afn_total=afn_total, rate=rate_value, rate_date=rate_date_value,
        rate_direction=direction, created_by=created_by,
        idempotency_key=idempotency_key,
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
        JournalLine(
            entry=entry, account=account,
            debit=Decimal(str(line.get("debit", 0))),
            credit=Decimal(str(line.get("credit", 0))),
            description=line.get("description", ""),
            reference=reference,
        ).save(allow_protected_update=True)
    return entry


def _entry_snapshot(entry):
    return {
        "id": entry.id,
        "number": entry.number,
        "status": entry.status,
        "currency": entry.currency.code if entry.currency else None,
        "total_debit": str(entry.total_debit),
        "total_credit": str(entry.total_credit),
        "afn_total": str(entry.afn_total) if entry.afn_total is not None else None,
        "lines": [
            {"account": line.account.code, "debit": str(line.debit),
             "credit": str(line.credit), "reference": line.reference}
            for line in entry.lines.all().order_by("id")
        ],
    }


def _audit_post(entry):
    record_audit_event(
        user=entry.created_by, action=AuditAction.POST, entity="JournalEntry",
        entity_id=entry.id, reference=entry.number, previous_state=None,
        new_state=_entry_snapshot(entry), reason="",
    )


def _validate_idempotency_key(key):
    if not isinstance(key, str) or not key or len(key) > 128:
        raise JournalValidationError("A valid idempotency key is required")


def _post_fingerprint(*, number, posting_date, description, source_type, source_id,
                      lines, currency, rate_value, rate_date_value, direction, created_by):
    payload = {
        "operation": IDEMPOTENT_POST_OPERATION,
        "number": number,
        "posting_date": str(_as_date(posting_date, "posting_date")),
        "description": description,
        "source_type": source_type,
        "source_id": str(source_id),
        "lines": [
            {
                "account_id": line["account"].pk if isinstance(line.get("account"), Account) else repr(line.get("account")),
                "debit": str(quantize_half_up(Decimal(str(line.get("debit", 0))), 2)),
                "credit": str(quantize_half_up(Decimal(str(line.get("credit", 0))), 2)),
                "description": line.get("description", ""),
                "reference": line.get("reference", ""),
            }
            for line in lines
        ],
        "currency_id": currency.pk,
        "rate": str(rate_value),
        "rate_date": str(rate_date_value),
        "direction": direction,
        "created_by_id": created_by.pk if created_by is not None else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _resolve_idempotent_retry(key, fingerprint):
    record = IdempotencyRecord.objects.filter(key=key).first()
    if record is None:
        raise DuplicateOperationError("Submission in progress or rolled back; retry the operation")
    stored = record.response_body or {}
    if stored.get("fingerprint") != fingerprint:
        raise JournalValidationError("This idempotency key was already used for a different operation")
    entry_id = stored.get("journal_entry_id")
    if entry_id is None:
        raise DuplicateOperationError("Original submission is still in progress; retry")
    try:
        return JournalEntry.objects.get(pk=entry_id)
    except JournalEntry.DoesNotExist:
        raise DuplicateOperationError("Original submission is still in progress; retry") from None


def post_journal(*, number, posting_date, description, lines, source_type="", source_id="",
                 currency=None, rate=None, rate_date=None, created_by=None, idempotency_key=None):
    """Create and atomically post one balanced journal entry.

    Stage 2.2 contract: transaction currency is required; the rate snapshot
    (rate + rate date + direction) is resolved and stored; totals and the AFN
    equivalent are computed once and stored; each line may carry a reference.

    Stage 2.3 contract: every post writes a POST audit event in the same
    transaction; when ``idempotency_key`` is given, an exact retry returns the
    original entry instead of posting again, and key reuse for a different
    operation is rejected.
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

    persist_kwargs = dict(
        number=number, posting_date=posting_date, description=description, lines=lines,
        source_type=source_type, source_id=source_id, currency=currency,
        debit_total=debit_total, credit_total=credit_total, afn_total=afn_total,
        rate_value=rate_value, rate_date_value=rate_date_value, direction=direction,
        created_by=created_by,
    )
    if idempotency_key is None:
        with transaction.atomic():
            entry = _persist_entry(**persist_kwargs)
            _audit_post(entry)
        return entry

    _validate_idempotency_key(idempotency_key)
    fingerprint = _post_fingerprint(
        number=number, posting_date=posting_date, description=description,
        source_type=source_type, source_id=source_id, lines=lines, currency=currency,
        rate_value=rate_value, rate_date_value=rate_date_value, direction=direction,
        created_by=created_by,
    )
    try:
        with idempotent_operation(key=idempotency_key, operation=IDEMPOTENT_POST_OPERATION) as record:
            with transaction.atomic():
                entry = _persist_entry(**persist_kwargs, idempotency_key=idempotency_key)
                record.response_body = {"journal_entry_id": entry.id, "fingerprint": fingerprint}
                record.save(update_fields=["response_body"])
                _audit_post(entry)
            return entry
    except DuplicateOperationError as dup:
        # idempotent_operation converts ANY IntegrityError inside its block into
        # DuplicateOperationError — including a duplicate journal number. Only a
        # genuinely reserved key means "retry"; otherwise re-raise the real cause.
        if IdempotencyRecord.objects.filter(key=idempotency_key).exists():
            return _resolve_idempotent_retry(idempotency_key, fingerprint)
        raise dup.__cause__ if dup.__cause__ is not None else dup


def _jalali_year(value):
    return int(gregorian_to_jalali(_as_date(value, "posting_date")).split("/")[0])


def reverse_journal(entry, reason, user):
    """Reverse a POSTED entry with a balanced mirror entry (Stage 2.3, §1.9/G4).

    The original keeps every financial field and line byte-identical; only its
    status becomes REVERSED. The reversal inherits posting date, source,
    currency and rate snapshot, swaps debit/credit per line, links back via
    ``reverses``, and is audited as one REVERSE operation — all atomically.
    """
    if not isinstance(entry, JournalEntry) or entry.pk is None:
        raise JournalValidationError("A persisted journal entry is required")
    if not isinstance(reason, str) or not reason.strip():
        raise JournalValidationError("A reversal reason is required")
    if user is not None and not isinstance(user, get_user_model()):
        raise JournalValidationError("Reversal user must be a user or None")
    with transaction.atomic():
        try:
            original = JournalEntry.objects.select_for_update().get(pk=entry.pk)
        except JournalEntry.DoesNotExist:
            raise JournalValidationError("Journal entry does not exist") from None
        if original.status == JournalStatus.DRAFT:
            raise JournalValidationError("A DRAFT entry cannot be reversed")
        if original.status == JournalStatus.REVERSED:
            raise JournalValidationError("This entry has already been reversed")
        if original.status != JournalStatus.POSTED:
            raise JournalValidationError("Only a POSTED entry can be reversed")
        if original.reverses_id is not None:
            raise JournalValidationError("A reversal entry cannot itself be reversed")
        verify_entry_totals(original)
        previous_state = {"id": original.id, "number": original.number, "status": original.status}
        reversal = JournalEntry.objects.create(
            number=next_document_number("JE", _jalali_year(original.posting_date)),
            posting_date=original.posting_date,
            description=f"Reversal of {original.number}: {reason.strip()}",
            source_type=original.source_type,
            source_id=original.source_id,
            status=JournalStatus.POSTED,
            posted_at=timezone.now(),
            currency=original.currency,
            total_debit=original.total_credit,
            total_credit=original.total_debit,
            afn_total=original.afn_total,
            rate=original.rate,
            rate_date=original.rate_date,
            rate_direction=original.rate_direction,
            created_by=user,
            reverses=original,
        )
        for line in original.lines.all().order_by("id"):
            JournalLine(
                entry=reversal, account_id=line.account_id,
                debit=line.credit, credit=line.debit,
                description=line.description, reference=line.reference,
            ).save(allow_protected_update=True)
        original.status = JournalStatus.REVERSED
        original.save(update_fields=["status"], allow_protected_update=True)
        record_audit_event(
            user=user, action=AuditAction.REVERSE, entity="JournalEntry",
            entity_id=original.id, reference=original.number,
            previous_state=previous_state,
            new_state={"id": original.id, "number": original.number,
                       "status": JournalStatus.REVERSED, "reversal_id": reversal.id,
                       "reversal_number": reversal.number},
            reason=reason.strip(),
        )
        return reversal


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
