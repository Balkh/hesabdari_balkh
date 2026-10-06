from datetime import date as date_class
from decimal import Decimal, InvalidOperation
import hashlib

from django.db import models, transaction

from accounting.models import Account, JournalStatus
from accounting.services import _as_date, post_journal, reverse_journal
from core.dates import gregorian_to_jalali
from core.idempotency import DuplicateOperationError, IdempotencyRecord, idempotent_operation
from core.money import quantize_half_up
from documents.services import next_document_number
from fiscal_periods.services import assert_posting_date_open
from currencies.models import Currency
from parties.services import PartyValidationError, resolve_party
from party_ledger.services import attribute_journal_line
from security.models import AuditAction
from security.services import record_audit_event
from purchases.models import Purchase, PurchaseStatus

from .models import (
    SupplierAdvance, SupplierAdvanceStatus,
    SupplierAdvanceAllocation, SupplierAdvanceAllocationReversal,
)


class SupplierAdvanceValidationError(ValueError):
    pass


CASH_ACCOUNT = "1110"
SUPPLIER_ADVANCE_ACCOUNT = "1500"
SUPPLIER_PAYABLE_ACCOUNT = "2110"
ADVANCE_OPERATION = "supplier-advance.create"
ALLOCATION_OPERATION = "supplier-advance.allocate"
ALLOCATION_REVERSAL_OPERATION = "supplier-advance-allocation.reverse"
ADVANCE_REVERSAL_OPERATION = "supplier-advance.reverse"


def _actor(user):
    if user is not None and not getattr(user, "is_authenticated", False):
        raise SupplierAdvanceValidationError("Authenticated user required.")
    return user


def _party(ref):
    try:
        party = resolve_party(ref)
    except PartyValidationError as exc:
        raise SupplierAdvanceValidationError(str(exc)) from exc
    if not party.is_supplier:
        raise SupplierAdvanceValidationError("Party is not a supplier.")
    if not party.is_active:
        raise SupplierAdvanceValidationError("Supplier is not active.")
    return party


def _currency(ref):
    if isinstance(ref, Currency) and ref.pk is not None:
        result = ref
    elif isinstance(ref, str) and ref:
        result = Currency.objects.filter(code=ref).first()
    else:
        result = None
    if result is None:
        raise SupplierAdvanceValidationError("Currency does not exist.")
    if not result.is_active:
        raise SupplierAdvanceValidationError("Currency is not active.")
    return result


def _amount(value, field="amount"):
    try:
        value = quantize_half_up(Decimal(str(value)), 2)
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise SupplierAdvanceValidationError(f"{field} must be a valid positive number.") from exc
    if value <= 0:
        raise SupplierAdvanceValidationError(f"{field} must be greater than zero.")
    return value


def _day(value, field):
    return value if isinstance(value, date_class) else _as_date(value, field)


def _year(value):
    return int(gregorian_to_jalali(value).split("/")[0])


def _usable(code):
    try:
        account = Account.objects.get(code=code)
    except Account.DoesNotExist as exc:
        raise SupplierAdvanceValidationError(f"Account {code} does not exist.") from exc
    if not account.is_active or not account.is_posting:
        raise SupplierAdvanceValidationError(f"Account {code} is not usable for posting.")
    return account


def _active_allocations(advance):
    return SupplierAdvanceAllocation.objects.filter(advance=advance).exclude(reversal__isnull=False)


def advance_available(advance):
    used = _active_allocations(advance).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")
    return quantize_half_up(advance.amount - used, 2)


def purchase_advance_allocated(purchase):
    used = SupplierAdvanceAllocation.objects.filter(purchase=purchase).exclude(reversal__isnull=False).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")
    return quantize_half_up(used, 2)


def _advance_snapshot(advance):
    return {
        "id": advance.pk, "document_number": advance.document_number,
        "supplier_id": advance.supplier_id, "supplier_name": advance.supplier.name,
        "advance_date": advance.advance_date.isoformat(), "currency": advance.currency.code,
        "amount": str(advance.amount), "status": advance.status,
        "journal_entry_id": advance.journal_entry_id, "description": advance.description,
        "reference": advance.reference,
    }


def _allocation_snapshot(allocation):
    return {
        "id": allocation.pk, "advance_id": allocation.advance_id, "purchase_id": allocation.purchase_id,
        "amount": str(allocation.amount), "journal_entry_id": allocation.journal_entry_id,
        "idempotency_key": allocation.idempotency_key,
    }


def _fingerprint(parts):
    return hashlib.sha256("|".join(str(x) for x in parts).encode("utf-8")).hexdigest()


def _retry_advance(key, fingerprint):
    record = IdempotencyRecord.objects.get(key=key)
    body = record.response_body or {}
    if body.get("fingerprint") != fingerprint:
        raise SupplierAdvanceValidationError("This idempotency key was used for a different supplier advance.")
    return SupplierAdvance.objects.select_related("supplier", "currency", "journal_entry").get(pk=body["advance_id"])


@transaction.atomic
def create_supplier_advance(*, supplier, advance_date, currency, amount, description="", reference="",
                           user=None, document_number=None, idempotency_key=None):
    actor = _actor(user)
    if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 128:
        raise SupplierAdvanceValidationError("A valid idempotency key is required.")
    supplier = _party(supplier)
    currency = _currency(currency)
    day = _day(advance_date, "advance_date")
    amount = _amount(amount)
    description = str(description).strip()
    reference = str(reference).strip()
    fingerprint = _fingerprint([supplier.pk, day, currency.pk, amount, description, reference, document_number or ""])
    try:
        with idempotent_operation(key=idempotency_key, operation=ADVANCE_OPERATION) as record:
            with transaction.atomic():
                if document_number is None:
                    document_number = next_document_number("SADV", _year(day))
                if not isinstance(document_number, str) or not document_number.strip():
                    raise SupplierAdvanceValidationError("Document number is required.")
                document_number = document_number.strip()
                assert_posting_date_open(day)
                cash = _usable(CASH_ACCOUNT)
                advance_account = _usable(SUPPLIER_ADVANCE_ACCOUNT)
                entry = post_journal(
                    number=next_document_number("JE", _year(day)), posting_date=day,
                    description=description or f"Supplier advance {document_number}",
                    lines=[
                        {"account": advance_account, "debit": amount, "reference": document_number, "description": "Supplier prepayment"},
                        {"account": cash, "credit": amount, "reference": document_number, "description": "Cash paid to supplier"},
                    ],
                    source_type="SUPPLIER_ADVANCE", source_id=document_number,
                    currency=currency, rate=None, rate_date=None, created_by=actor,
                    idempotency_key=f"{idempotency_key}:journal", allow_unvalued_foreign=True,
                )
                attribute_journal_line(entry.lines.get(account=advance_account), party=supplier, user=actor)
                advance = SupplierAdvance.objects.create(
                    document_number=document_number, supplier=supplier, advance_date=day,
                    currency=currency, amount=amount, journal_entry=entry,
                    status=SupplierAdvanceStatus.POSTED, description=description, reference=reference,
                    idempotency_key=idempotency_key, created_by=actor,
                )
                record.response_body = {"advance_id": advance.pk, "fingerprint": fingerprint}
                record.save(update_fields=["response_body"])
                record_audit_event(user=actor, action=AuditAction.CREATE, entity="SupplierAdvance",
                                   entity_id=advance.pk, reference=document_number,
                                   previous_state=None, new_state=_advance_snapshot(advance), reason="")
                return advance
    except DuplicateOperationError:
        if IdempotencyRecord.objects.filter(key=idempotency_key).exists():
            return _retry_advance(idempotency_key, fingerprint)
        raise


@transaction.atomic
def allocate_supplier_advance(*, advance, purchase, amount, user=None, idempotency_key=None):
    actor = _actor(user)
    if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 128:
        raise SupplierAdvanceValidationError("A valid idempotency key is required.")
    amount = _amount(amount)
    advance_id = getattr(advance, "pk", advance)
    purchase_id = getattr(purchase, "pk", purchase)
    fingerprint = _fingerprint([advance_id, purchase_id, amount])
    try:
        with idempotent_operation(key=idempotency_key, operation=ALLOCATION_OPERATION) as record:
            with transaction.atomic():
                advance = SupplierAdvance.objects.select_for_update().select_related("supplier", "currency", "journal_entry").get(pk=advance_id)
                purchase = Purchase.objects.select_for_update().select_related("supplier", "currency").get(pk=purchase_id)
                if advance.status != SupplierAdvanceStatus.POSTED:
                    raise SupplierAdvanceValidationError("Only a posted supplier advance can be allocated.")
                if advance.journal_entry.status != JournalStatus.POSTED:
                    raise SupplierAdvanceValidationError("Supplier advance journal is not posted.")
                if purchase.status != PurchaseStatus.POSTED:
                    raise SupplierAdvanceValidationError("Only a posted purchase can receive an advance allocation.")
                if advance.supplier_id != purchase.supplier_id:
                    raise SupplierAdvanceValidationError("Advance supplier must match the purchase supplier.")
                if advance.currency_id != purchase.currency_id:
                    raise SupplierAdvanceValidationError("Advance and purchase currencies must match.")
                assert_posting_date_open(purchase.purchase_date)
                available = advance_available(advance)
                purchase_remaining = quantize_half_up(purchase.total - purchase_advance_allocated(purchase), 2)
                if available <= 0:
                    raise SupplierAdvanceValidationError("Supplier advance has no remaining balance.")
                if purchase_remaining <= 0:
                    raise SupplierAdvanceValidationError("Purchase has no remaining payable balance for advance allocation.")
                if amount > available:
                    raise SupplierAdvanceValidationError("Allocation exceeds the supplier advance's remaining balance.")
                if amount > purchase_remaining:
                    raise SupplierAdvanceValidationError("Allocation exceeds the purchase's remaining payable balance.")
                payable = _usable(SUPPLIER_PAYABLE_ACCOUNT)
                advance_account = _usable(SUPPLIER_ADVANCE_ACCOUNT)
                source_id = f"{advance.document_number}:{purchase.document_number}:{idempotency_key}"
                entry = post_journal(
                    number=next_document_number("JE", _year(purchase.purchase_date)), posting_date=purchase.purchase_date,
                    description=f"Apply supplier advance {advance.document_number} to {purchase.document_number}",
                    lines=[
                        {"account": payable, "debit": amount, "reference": source_id, "description": "Reduce supplier payable"},
                        {"account": advance_account, "credit": amount, "reference": source_id, "description": "Apply supplier advance"},
                    ],
                    source_type="SUPPLIER_ADVANCE_ALLOCATION", source_id=source_id,
                    currency=advance.currency, rate=None, rate_date=None, created_by=actor,
                    idempotency_key=f"{idempotency_key}:journal", allow_unvalued_foreign=True,
                )
                attribute_journal_line(entry.lines.get(account=payable), party=advance.supplier, user=actor)
                attribute_journal_line(entry.lines.get(account=advance_account), party=advance.supplier, user=actor)
                allocation = SupplierAdvanceAllocation.objects.create(
                    advance=advance, purchase=purchase, amount=amount, journal_entry=entry,
                    idempotency_key=idempotency_key, created_by=actor,
                )
                record.response_body = {"allocation_id": allocation.pk, "fingerprint": fingerprint}
                record.save(update_fields=["response_body"])
                record_audit_event(user=actor, action=AuditAction.CREATE, entity="SupplierAdvanceAllocation",
                                   entity_id=allocation.pk, reference=source_id,
                                   previous_state=None, new_state=_allocation_snapshot(allocation), reason="")
                return allocation
    except SupplierAdvance.DoesNotExist as exc:
        raise SupplierAdvanceValidationError("Supplier advance does not exist.") from exc
    except Purchase.DoesNotExist as exc:
        raise SupplierAdvanceValidationError("Purchase does not exist.") from exc
    except DuplicateOperationError:
        record = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if record is not None and (record.response_body or {}).get("fingerprint") == fingerprint:
            return SupplierAdvanceAllocation.objects.select_related("advance", "purchase", "journal_entry").get(pk=record.response_body["allocation_id"])
        if record is not None:
            raise SupplierAdvanceValidationError("This idempotency key was used for a different allocation.")
        raise


@transaction.atomic
def reverse_supplier_advance_allocation(allocation, *, reason, user=None, idempotency_key=None):
    actor = _actor(user)
    if not isinstance(reason, str) or not reason.strip():
        raise SupplierAdvanceValidationError("A reversal reason is required.")
    if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 128:
        raise SupplierAdvanceValidationError("A valid idempotency key is required.")
    allocation_id = getattr(allocation, "pk", allocation)
    fingerprint = _fingerprint([allocation_id, reason.strip()])
    try:
        with idempotent_operation(key=idempotency_key, operation=ALLOCATION_REVERSAL_OPERATION) as record:
            with transaction.atomic():
                allocation = SupplierAdvanceAllocation.objects.select_for_update().select_related("advance", "purchase", "journal_entry").get(pk=allocation_id)
                if hasattr(allocation, "reversal"):
                    existing = allocation.reversal
                    if (record.response_body or {}).get("fingerprint") != fingerprint:
                        raise SupplierAdvanceValidationError("This idempotency key was used for a different reversal.")
                    return existing
                assert_posting_date_open(allocation.purchase.purchase_date)
                reversal = reverse_journal(allocation.journal_entry, reason.strip(), actor)
                supplier = allocation.advance.supplier
                for code in (SUPPLIER_PAYABLE_ACCOUNT, SUPPLIER_ADVANCE_ACCOUNT):
                    attribute_journal_line(reversal.lines.get(account__code=code), party=supplier, user=actor)
                row = SupplierAdvanceAllocationReversal.objects.create(
                    allocation=allocation, journal_entry=reversal, reason=reason.strip(),
                    idempotency_key=idempotency_key, created_by=actor,
                )
                record.response_body = {"reversal_id": row.pk, "fingerprint": fingerprint}
                record.save(update_fields=["response_body"])
                record_audit_event(user=actor, action=AuditAction.REVERSE, entity="SupplierAdvanceAllocation",
                                   entity_id=allocation.pk, reference=allocation.idempotency_key,
                                   previous_state=_allocation_snapshot(allocation),
                                   new_state={"reversal_id": row.pk, "journal_reversal_id": reversal.pk},
                                   reason=reason.strip())
                return row
    except SupplierAdvanceAllocation.DoesNotExist as exc:
        raise SupplierAdvanceValidationError("Supplier advance allocation does not exist.") from exc
    except DuplicateOperationError:
        record = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if record is not None and (record.response_body or {}).get("fingerprint") == fingerprint:
            return SupplierAdvanceAllocationReversal.objects.get(pk=record.response_body["reversal_id"])
        raise


@transaction.atomic
def reverse_supplier_advance(advance, *, reason, user=None, idempotency_key=None):
    actor = _actor(user)
    if not isinstance(reason, str) or not reason.strip():
        raise SupplierAdvanceValidationError("A reversal reason is required.")
    if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 128:
        raise SupplierAdvanceValidationError("A valid idempotency key is required.")
    advance_id = getattr(advance, "pk", advance)
    fingerprint = _fingerprint([advance_id, reason.strip()])
    try:
        with idempotent_operation(key=idempotency_key, operation=ADVANCE_REVERSAL_OPERATION) as record:
            with transaction.atomic():
                advance = SupplierAdvance.objects.select_for_update().select_related("journal_entry", "supplier", "currency").get(pk=advance_id)
                if advance.status == SupplierAdvanceStatus.REVERSED:
                    if (record.response_body or {}).get("fingerprint") == fingerprint:
                        return advance
                    raise SupplierAdvanceValidationError("Supplier advance has already been reversed.")
                if _active_allocations(advance).exists():
                    raise SupplierAdvanceValidationError("Reverse active advance allocations before reversing the supplier advance.")
                assert_posting_date_open(advance.advance_date)
                reversal = reverse_journal(advance.journal_entry, reason.strip(), actor)
                attribute_journal_line(
                    reversal.lines.get(account__code=SUPPLIER_ADVANCE_ACCOUNT),
                    party=advance.supplier, user=actor,
                )
                SupplierAdvance.objects.filter(pk=advance.pk).update(status=SupplierAdvanceStatus.REVERSED)
                advance.status = SupplierAdvanceStatus.REVERSED
                record.response_body = {"advance_id": advance.pk, "reversal_id": reversal.pk, "fingerprint": fingerprint}
                record.save(update_fields=["response_body"])
                record_audit_event(user=actor, action=AuditAction.REVERSE, entity="SupplierAdvance",
                                   entity_id=advance.pk, reference=advance.document_number,
                                   previous_state={"status": SupplierAdvanceStatus.POSTED},
                                   new_state={"status": SupplierAdvanceStatus.REVERSED, "reversal_id": reversal.pk},
                                   reason=reason.strip())
                return advance
    except SupplierAdvance.DoesNotExist as exc:
        raise SupplierAdvanceValidationError("Supplier advance does not exist.") from exc
    except DuplicateOperationError:
        record = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if record is not None and (record.response_body or {}).get("fingerprint") == fingerprint:
            return SupplierAdvance.objects.get(pk=advance_id)
        raise
