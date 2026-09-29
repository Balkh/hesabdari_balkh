from datetime import date as date_class
from decimal import Decimal, InvalidOperation

from django.db import models, transaction
from django.utils import timezone

from accounting.models import Account
from accounting.services import _as_date, post_journal, reverse_journal
from core.dates import gregorian_to_jalali
from core.idempotency import DuplicateOperationError, IdempotencyRecord, idempotent_operation
from core.money import quantize_half_up
from fiscal_periods.services import assert_posting_date_open
from parties.models import Party
from party_ledger.services import attribute_journal_line
from security.models import AuditAction
from security.services import record_audit_event

from payments.models import Payment, PaymentPurpose
from sales.models import PaymentMode, Sale, SaleStatus

from .models import CustomerAllocation, CustomerAllocationReversal


class AllocationValidationError(ValueError):
    pass


RECEIVABLE_ACCOUNT = "1310"
CUSTOMER_CREDIT_ACCOUNT = "2200"
OPERATION = "customer-allocation.create"
REVERSAL_OPERATION = "customer-allocation.reverse"


def _actor(user):
    if user is not None and not getattr(user, "is_authenticated", False):
        raise AllocationValidationError("Authenticated user required")
    return user


def _amount(value, field="amount"):
    try:
        amount = quantize_half_up(Decimal(str(value)), 2)
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise AllocationValidationError(f"{field} must be a valid positive number") from exc
    if amount <= 0:
        raise AllocationValidationError(f"{field} must be greater than zero")
    return amount


def _resolve_payment(ref):
    try:
        return Payment.objects.select_related("party", "currency", "journal_entry").get(pk=getattr(ref, "pk", ref))
    except Payment.DoesNotExist as exc:
        raise AllocationValidationError("Payment does not exist") from exc


def _resolve_sale(ref):
    try:
        return Sale.objects.select_related("customer", "currency", "journal_entry").get(pk=getattr(ref, "pk", ref))
    except Sale.DoesNotExist as exc:
        raise AllocationValidationError("Sale does not exist") from exc


def _active_allocations(payment):
    return CustomerAllocation.objects.filter(payment=payment).exclude(reversal__isnull=False)


def payment_available(payment):
    """Remaining amount of a Payment that is still legally allocatable."""
    used = _active_allocations(payment).aggregate(total=models.Sum("amount"), credit=models.Sum("credit_amount"))
    return quantize_half_up(payment.amount - (used["total"] or Decimal("0.00")) - (used["credit"] or Decimal("0.00")), 2)


def invoice_allocated(sale):
    """Amount currently applied to one finalized credit invoice."""
    total = CustomerAllocation.objects.filter(sale=sale).exclude(reversal__isnull=False).aggregate(total=models.Sum("amount"))["total"]
    return quantize_half_up(total or Decimal("0.00"), 2)


def invoice_outstanding(sale):
    """Invoice outstanding in the invoice currency; cash Sales are always settled."""
    if sale.payment_mode == PaymentMode.CASH:
        return Decimal("0.00")
    return quantize_half_up(sale.total - invoice_allocated(sale), 2)


def _assert_same_currency(payment, sale):
    if payment.currency_id != sale.currency_id:
        raise AllocationValidationError(
            "Cross-currency customer allocation is not supported in Phase 10A; use the approved FX settlement prerequisite."
        )


def _allocation_snapshot(allocation):
    return {
        "id": allocation.pk,
        "payment_id": allocation.payment_id,
        "sale_id": allocation.sale_id,
        "currency": allocation.currency.code,
        "requested_amount": str(allocation.requested_amount),
        "amount": str(allocation.amount),
        "credit_amount": str(allocation.credit_amount),
        "journal_entry_id": allocation.journal_entry_id,
        "idempotency_key": allocation.idempotency_key,
    }


def _retry(key, fingerprint):
    record = IdempotencyRecord.objects.get(key=key)
    stored = record.response_body or {}
    if stored.get("fingerprint") != fingerprint:
        raise AllocationValidationError("This idempotency key was used for a different allocation.")
    allocation_id = stored.get("allocation_id")
    if not allocation_id:
        raise DuplicateOperationError("Original allocation is still in progress; retry.")
    return CustomerAllocation.objects.select_related("payment", "sale", "currency").get(pk=allocation_id)


def _fingerprint(*, payment, sale, requested_amount):
    return "|".join([str(payment.pk), str(sale.pk), str(requested_amount)])


def _post_customer_reclass(*, payment, amount, posting_date, user, source_id, idempotency_key, debit_code, credit_code, description):
    debit = Account.objects.get(code=debit_code)
    credit = Account.objects.get(code=credit_code)
    if not debit.is_active or not debit.is_posting or not credit.is_active or not credit.is_posting:
        raise AllocationValidationError("Allocation accounts are not usable for posting")
    entry = post_journal(
        number=f"JE-ALLOC-{source_id}", posting_date=posting_date, description=description,
        lines=[
            {"account": debit, "debit": amount, "reference": source_id},
            {"account": credit, "credit": amount, "reference": source_id},
        ], source_type="CUSTOMER_ALLOCATION", source_id=source_id,
        currency=payment.currency, rate=payment.journal_entry.rate,
        rate_date=payment.journal_entry.rate_date, created_by=user,
        idempotency_key=idempotency_key,
    )
    attribute_journal_line(entry.lines.get(account=debit), party=payment.party, user=user)
    attribute_journal_line(entry.lines.get(account=credit), party=payment.party, user=user)
    return entry


@transaction.atomic
def allocate_payment(*, payment, sale, amount, user=None, idempotency_key=None):
    """Apply one same-currency Payment to one finalized CREDIT Sale.

    The Sale and Payment already carry their accounting truth. This operation
    only creates the allocation relationship, except where the approved
    CUSTOMER_CREDIT or RECEIVABLE overpayment contract requires a 2200/1310
    reclassification journal. No cash, revenue, stock, or ownership journal
    is duplicated here.
    """
    actor = _actor(user)
    requested = _amount(amount)
    if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 128:
        raise AllocationValidationError("A valid idempotency key is required")

    fingerprint = _fingerprint(payment=_resolve_payment(payment), sale=_resolve_sale(sale), requested_amount=requested)
    try:
        with idempotent_operation(key=idempotency_key, operation=OPERATION) as record:
            payment = Payment.objects.select_for_update().select_related("party", "currency", "journal_entry").get(pk=getattr(payment, "pk", payment))
            sale = Sale.objects.select_for_update().select_related("customer", "currency").get(pk=getattr(sale, "pk", sale))
            if payment.journal_entry.status != "POSTED":
                raise AllocationValidationError("Only a posted Payment can be allocated")
            if sale.status != SaleStatus.FINALIZED:
                raise AllocationValidationError("Only a finalized Sale can receive an allocation")
            if sale.payment_mode != PaymentMode.CREDIT:
                raise AllocationValidationError("Cash Sales are already settled and cannot receive allocations")
            if payment.party_id != sale.customer_id:
                raise AllocationValidationError("Payment customer must match the Sale customer")
            _assert_same_currency(payment, sale)
            assert_posting_date_open(sale.sale_date)
            assert_posting_date_open(payment.payment_date)

            available = payment_available(payment)
            outstanding = invoice_outstanding(sale)
            if available <= 0:
                raise AllocationValidationError("Payment has no remaining allocation capacity")
            if outstanding <= 0:
                raise AllocationValidationError("Invoice is already fully allocated")
            if requested > available:
                raise AllocationValidationError("Allocation exceeds the Payment's remaining capacity")

            applied = min(requested, outstanding)
            excess = quantize_half_up(requested - applied, 2)
            credit_reclass = Decimal("0.00")
            journal = None
            if payment.purpose == PaymentPurpose.CUSTOMER_CREDIT:
                journal = _post_customer_reclass(
                    payment=payment, amount=applied, posting_date=payment.payment_date, user=actor,
                    source_id=f"{payment.document_number}:{sale.document_number}:{idempotency_key}",
                    idempotency_key=f"{idempotency_key}:journal", debit_code=CUSTOMER_CREDIT_ACCOUNT,
                    credit_code=RECEIVABLE_ACCOUNT,
                    description=f"Apply customer credit {payment.document_number} to {sale.document_number}",
                )
            elif excess > 0:
                credit_reclass = excess
                journal = _post_customer_reclass(
                    payment=payment, amount=excess, posting_date=payment.payment_date, user=actor,
                    source_id=f"{payment.document_number}:{sale.document_number}:{idempotency_key}",
                    idempotency_key=f"{idempotency_key}:journal", debit_code=RECEIVABLE_ACCOUNT,
                    credit_code=CUSTOMER_CREDIT_ACCOUNT,
                    description=f"Customer payment overage {payment.document_number} after {sale.document_number}",
                )
            allocation = CustomerAllocation.objects.create(
                payment=payment, sale=sale, currency=payment.currency,
                requested_amount=requested, amount=applied, credit_amount=credit_reclass,
                journal_entry=journal, idempotency_key=idempotency_key, created_by=actor,
            )
            record.response_body = {"allocation_id": allocation.pk, "fingerprint": fingerprint}
            record.save(update_fields=["response_body"])
            record_audit_event(user=actor, action=AuditAction.CREATE, entity="CustomerAllocation",
                               entity_id=allocation.pk, reference=f"{payment.document_number}:{sale.document_number}",
                               previous_state=None, new_state=_allocation_snapshot(allocation), reason="")
            return allocation
    except DuplicateOperationError:
        if IdempotencyRecord.objects.filter(key=idempotency_key).exists():
            return _retry(idempotency_key, fingerprint)
        raise


@transaction.atomic
def reverse_allocation(allocation, *, reason, user=None, idempotency_key=None):
    """Reverse an allocation without reversing the original Payment."""
    actor = _actor(user)
    if not isinstance(reason, str) or not reason.strip():
        raise AllocationValidationError("A reversal reason is required")
    if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 128:
        raise AllocationValidationError("A valid idempotency key is required")
    try:
        allocation_id = getattr(allocation, "pk", allocation)
        allocation = CustomerAllocation.objects.select_for_update().select_related(
            "payment__journal_entry", "payment__party", "payment__currency", "sale", "currency", "journal_entry"
        ).get(pk=allocation_id)
    except CustomerAllocation.DoesNotExist as exc:
        raise AllocationValidationError("Allocation does not exist") from exc
    fingerprint = f"{allocation.pk}|{reason.strip()}"
    try:
        with idempotent_operation(key=idempotency_key, operation=REVERSAL_OPERATION) as record:
            if hasattr(allocation, "reversal"):
                existing = allocation.reversal
                stored = record.response_body or {}
                if stored.get("fingerprint") != fingerprint:
                    raise AllocationValidationError("This idempotency key was used for a different reversal")
                return existing
            journal_reversal = None
            if allocation.journal_entry_id:
                journal_reversal = reverse_journal(allocation.journal_entry, reason.strip(), actor)
            reversal = CustomerAllocationReversal.objects.create(
                allocation=allocation, journal_entry=journal_reversal, reason=reason.strip(),
                created_by=actor, idempotency_key=idempotency_key,
            )
            record.response_body = {"reversal_id": reversal.pk, "fingerprint": fingerprint}
            record.save(update_fields=["response_body"])
            record_audit_event(user=actor, action=AuditAction.REVERSE, entity="CustomerAllocation",
                               entity_id=allocation.pk, reference=allocation.idempotency_key,
                               previous_state=_allocation_snapshot(allocation),
                               new_state={"reversed": True, "reversal_id": reversal.pk,
                                          "journal_reversal_id": getattr(journal_reversal, "pk", None)},
                               reason=reason.strip())
            return reversal
    except DuplicateOperationError:
        record = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if record is not None and (record.response_body or {}).get("fingerprint") == fingerprint:
            reversal_id = (record.response_body or {}).get("reversal_id")
            if reversal_id:
                return CustomerAllocationReversal.objects.get(pk=reversal_id)
        raise
