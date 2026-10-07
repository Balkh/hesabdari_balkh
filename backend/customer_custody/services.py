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
    placed = CustomerCustodyEvent.objects.filter(
        entitlement=entitlement, warehouse=warehouse,
        event_type=CustodyEventType.PLACED,
    ).aggregate(v=models.Sum("quantity"))["v"] or 0
    released = CustomerCustodyEvent.objects.filter(
        entitlement=entitlement, warehouse=warehouse,
        event_type=CustodyEventType.RELEASED,
    ).aggregate(v=models.Sum("quantity"))["v"] or 0
    placement_reversals = CustomerCustodyEvent.objects.filter(
        entitlement=entitlement, warehouse=warehouse,
        event_type=CustodyEventType.PLACEMENT_REVERSAL,
    ).aggregate(v=models.Sum("quantity"))["v"] or 0
    release_reversals = CustomerCustodyEvent.objects.filter(
        entitlement=entitlement, warehouse=warehouse,
        event_type=CustodyEventType.RELEASE_REVERSAL,
    ).aggregate(v=models.Sum("quantity"))["v"] or 0
    return int(placed - released - placement_reversals + release_reversals)


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
                current_total = sum(
                    _balance(entitlement, w) for w in warehouse.__class__.objects.filter(
                        customer_custody_events__entitlement=entitlement
                    ).distinct()
                )
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
                             reference, user=None, idempotency_key=None):
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
                return _event(
                    entitlement=entitlement, warehouse=warehouse,
                    event_type=CustodyEventType.RELEASED, quantity=quantity,
                    event_date=day, reference=reference,
                    idempotency_key=idempotency_key, user=actor,
                )
    except DuplicateOperationError:
        return CustomerCustodyEvent.objects.get(idempotency_key=idempotency_key)


def custody_balance(*, entitlement, warehouse):
    return _balance(entitlement, warehouse)
