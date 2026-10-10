from datetime import date

from django.db import models, transaction

from core.idempotency import DuplicateOperationError, idempotent_operation
from fiscal_periods.services import assert_posting_date_open
from security.models import AuditAction
from security.services import record_audit_event

from .models import (
    CustomerCustodyEvent,
    CustomerOwnershipEntitlement,
    CustodyEventType,
    OwnershipStatus,
)

OWNERSHIP_OPERATION = "customer-custody.ownership"
CUSTODY_PLACE_OPERATION = "customer-custody.place"
CUSTODY_RELEASE_OPERATION = "customer-custody.release"
CUSTODY_REVERSAL_OPERATION = "customer-custody.reversal"


class CustomerCustodyValidationError(ValueError):
    pass


def _day(value):
    if not isinstance(value, date):
        raise CustomerCustodyValidationError("A date is required")
    return value


def _actor(user):
    if user is not None and not getattr(user, "is_authenticated", False):
        raise CustomerCustodyValidationError("Authenticated user required")
    return user


def _qty(value, label="Quantity"):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CustomerCustodyValidationError(f"{label} must be a positive integer")
    return value


def _balance(entitlement, warehouse):
    rows = CustomerCustodyEvent.objects.filter(entitlement=entitlement, warehouse=warehouse).values("event_type").annotate(total=models.Sum("quantity"))
    totals = {row["event_type"]: int(row["total"] or 0) for row in rows}
    return (
        totals.get(CustodyEventType.PLACED, 0)
        - totals.get(CustodyEventType.RELEASED, 0)
        - totals.get(CustodyEventType.PLACEMENT_REVERSAL, 0)
        + totals.get(CustodyEventType.RELEASE_REVERSAL, 0)
    )


def _total_balance(entitlement):
    rows = CustomerCustodyEvent.objects.filter(entitlement=entitlement).values("event_type").annotate(total=models.Sum("quantity"))
    totals = {row["event_type"]: int(row["total"] or 0) for row in rows}
    return (
        totals.get(CustodyEventType.PLACED, 0)
        - totals.get(CustodyEventType.RELEASED, 0)
        - totals.get(CustodyEventType.PLACEMENT_REVERSAL, 0)
        + totals.get(CustodyEventType.RELEASE_REVERSAL, 0)
    )

def create_ownership_entitlement(*, sale_line, user=None, idempotency_key=None):
    actor = _actor(user)
    line_id = getattr(sale_line, "pk", sale_line)
    if not idempotency_key:
        raise CustomerCustodyValidationError("Ownership idempotency key is required")
    try:
        with idempotent_operation(key=idempotency_key, operation=OWNERSHIP_OPERATION):
            with transaction.atomic():
                from sales.models import SaleLine, SaleStatus
                line = SaleLine.objects.select_for_update().select_related(
                    "sale__customer", "product"
                ).get(pk=line_id)
                if line.sale.status != SaleStatus.FINALIZED:
                    raise CustomerCustodyValidationError(
                        "Ownership can only be acquired from a finalized Sale"
                    )
                existing = CustomerOwnershipEntitlement.objects.filter(
                    sale_line=line
                ).first()
                if existing:
                    return existing
                entitlement = CustomerOwnershipEntitlement.objects.create(
                    sale_line=line,
                    customer=line.sale.customer,
                    product=line.product,
                    quantity=line.quantity,
                    ownership_date=line.sale.sale_date,
                    idempotency_key=idempotency_key,
                    created_by=actor,
                )
                record_audit_event(
                    user=actor, action=AuditAction.CREATE,
                    entity="CustomerOwnershipEntitlement", entity_id=entitlement.pk,
                    reference=line.sale.document_number,
                    previous_state=None,
                    new_state={
                        "sale_line_id": line.pk,
                        "customer_id": line.sale.customer_id,
                        "product_id": line.product_id,
                        "quantity": line.quantity,
                    }, reason="Sale finalization ownership acquisition",
                )
                return entitlement
    except DuplicateOperationError:
        return CustomerOwnershipEntitlement.objects.get(idempotency_key=idempotency_key)


def _event(*, entitlement, warehouse, event_type, quantity, event_date,
           reference, idempotency_key, user, reversal_of=None):
    event = CustomerCustodyEvent.objects.create(
        entitlement=entitlement,
        customer=entitlement.customer,
        product=entitlement.product,
        warehouse=warehouse,
        event_type=event_type,
        quantity=quantity,
        event_date=event_date,
        reference=reference,
        idempotency_key=idempotency_key,
        reversal_of=reversal_of,
        created_by=user,
    )
    record_audit_event(
        user=user, action=AuditAction.CREATE, entity="CustomerCustodyEvent",
        entity_id=event.pk, reference=reference, previous_state=None,
        new_state={
            "entitlement_id": entitlement.pk, "warehouse_id": warehouse.pk,
            "event_type": event_type, "quantity": quantity,
            "event_date": event_date.isoformat(), "reversal_of": getattr(reversal_of, "pk", None),
        }, reason=f"Customer custody {event_type.lower()}",
    )
    return event


def place_customer_custody(*, entitlement, warehouse, quantity, event_date,
                           reference, user=None, idempotency_key=None):
    actor = _actor(user)
    quantity = _qty(quantity)
    day = _day(event_date)
    if not idempotency_key:
        raise CustomerCustodyValidationError("Custody placement idempotency key is required")
    assert_posting_date_open(day)
    try:
        with idempotent_operation(key=idempotency_key, operation=CUSTODY_PLACE_OPERATION):
            with transaction.atomic():
                entitlement = CustomerOwnershipEntitlement.objects.select_for_update().get(
                    pk=getattr(entitlement, "pk", entitlement)
                )
                warehouse = warehouse.__class__.objects.select_for_update().get(pk=warehouse.pk)
                if entitlement.status != OwnershipStatus.ACTIVE:
                    raise CustomerCustodyValidationError("Ownership entitlement is not active")
                current_total = _total_balance(entitlement)
                if current_total + quantity > entitlement.quantity:
                    raise CustomerCustodyValidationError("Custody placement exceeds customer ownership")
                return _event(
                    entitlement=entitlement, warehouse=warehouse,
                    event_type=CustodyEventType.PLACED, quantity=quantity,
                    event_date=day, reference=reference,
                    idempotency_key=idempotency_key, user=actor,
                )
    except DuplicateOperationError:
        return CustomerCustodyEvent.objects.get(idempotency_key=idempotency_key)


def release_customer_custody(*, entitlement, warehouse, quantity, event_date,
                             reference, user=None, idempotency_key=None, stock_issue=None):
    actor = _actor(user)
    quantity = _qty(quantity)
    day = _day(event_date)
    if not idempotency_key:
        raise CustomerCustodyValidationError("Custody release idempotency key is required")
    assert_posting_date_open(day)
    try:
        with idempotent_operation(key=idempotency_key, operation=CUSTODY_RELEASE_OPERATION):
            with transaction.atomic():
                entitlement = CustomerOwnershipEntitlement.objects.select_for_update().get(
                    pk=getattr(entitlement, "pk", entitlement)
                )
                warehouse = warehouse.__class__.objects.select_for_update().get(pk=warehouse.pk)
                if entitlement.status != OwnershipStatus.ACTIVE:
                    raise CustomerCustodyValidationError("Ownership entitlement is not active")
                available = _balance(entitlement, warehouse)
                if quantity > available:
                    raise CustomerCustodyValidationError("Release exceeds customer custody in the warehouse")
                if stock_issue is not None:
                    stock_issue(quantity=quantity, warehouse=warehouse, entitlement=entitlement)
                return _event(
                    entitlement=entitlement, warehouse=warehouse,
                    event_type=CustodyEventType.RELEASED, quantity=quantity,
                    event_date=day, reference=reference,
                    idempotency_key=idempotency_key, user=actor,
                )
    except DuplicateOperationError:
        return CustomerCustodyEvent.objects.get(idempotency_key=idempotency_key)



def reverse_customer_custody_event(*, event, reversal_date, reason, reference,
                                   user=None, idempotency_key=None,
                                   compensate=None):
    """Reverse one custody event through a new immutable compensating event.

    Reversing a release associated with a finalized Warehouse Check requires
    a caller-supplied callback that compensates the other business ledgers in
    the same transaction. A plain custody reversal is never allowed to leave
    inventory/COGS untouched for a sales release.
    """
    actor = _actor(user)
    day = _day(reversal_date)
    if not isinstance(reason, str) or not reason.strip():
        raise CustomerCustodyValidationError("A reversal reason is required")
    if not isinstance(reference, str) or not reference.strip():
        raise CustomerCustodyValidationError("A reversal reference is required")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 128:
        raise CustomerCustodyValidationError("A reversal idempotency key is required")
    assert_posting_date_open(day)
    event_id = getattr(event, "pk", event)
    try:
        with idempotent_operation(key=idempotency_key, operation=CUSTODY_REVERSAL_OPERATION):
            with transaction.atomic():
                original = CustomerCustodyEvent.objects.select_for_update().select_related(
                    "entitlement", "warehouse"
                ).get(pk=event_id)
                existing = CustomerCustodyEvent.objects.filter(reversal_of=original).first()
                if existing:
                    if existing.idempotency_key != idempotency_key:
                        raise CustomerCustodyValidationError("This custody event has already been reversed")
                    return existing
                if original.event_type not in (CustodyEventType.PLACED, CustodyEventType.RELEASED):
                    raise CustomerCustodyValidationError("Only original placement or release events can be reversed")
                entitlement = CustomerOwnershipEntitlement.objects.select_for_update().get(
                    pk=original.entitlement_id
                )
                warehouse = original.warehouse.__class__.objects.select_for_update().get(
                    pk=original.warehouse_id
                )
                if original.event_type == CustodyEventType.PLACED:
                    if _balance(entitlement, warehouse) < original.quantity:
                        raise CustomerCustodyValidationError(
                            "Placement cannot be reversed because some quantity is no longer in custody"
                        )
                    reversal_type = CustodyEventType.PLACEMENT_REVERSAL
                else:
                    from sales.models import WarehouseCheck, CheckStatus
                    is_sales_check = WarehouseCheck.objects.filter(
                        number=original.reference, status=CheckStatus.FINALIZED
                    ).exists()
                    if is_sales_check and compensate is None:
                        raise CustomerCustodyValidationError(
                            "A Warehouse Check release must be reversed through the coordinated Sales operation"
                        )
                    if compensate is not None:
                        compensate(original=original, actor=actor, reversal_date=day,
                                   reason=reason.strip(), idempotency_key=idempotency_key)
                    reversal_type = CustodyEventType.RELEASE_REVERSAL
                return _event(
                    entitlement=entitlement, warehouse=warehouse,
                    event_type=reversal_type, quantity=original.quantity,
                    event_date=day, reference=reference.strip(),
                    idempotency_key=idempotency_key, user=actor,
                    reversal_of=original,
                )
    except DuplicateOperationError:
        return CustomerCustodyEvent.objects.get(idempotency_key=idempotency_key)


def custody_balance(*, entitlement, warehouse):
    return _balance(entitlement, warehouse)


def unallocated_custody_balance(*, entitlement):
    entitlement = CustomerOwnershipEntitlement.objects.get(pk=getattr(entitlement, "pk", entitlement))
    return max(0, entitlement.quantity - _total_balance(entitlement))
