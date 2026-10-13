"""Phase 11 late landed-cost draft creation and deterministic allocation.

Posting is intentionally separate: this module only creates auditable DRAFT
source documents and allocation snapshots. It does not post a journal or
claim valuation finalization; that requires the traceable valuation-adjustment
ledger and its reconciliation gate.
"""
from datetime import date as date_class
from decimal import Decimal, InvalidOperation

from django.db import transaction

from core.money import fx_equivalent, normalize_rate, quantize_half_up, to_decimal
from inventory.models import MovementType, StockMovement
from security.models import AuditAction
from security.services import record_audit_event
from .models import (
    LandedCostAllocation,
    LandedCostAllocationMethod,
    LandedCostDocument,
    LandedCostStatus,
    PurchaseStatus,
    PurchaseLine,
)


class LandedCostValidationError(ValueError):
    """Deterministic landed-cost domain rejection."""


def _date(value, field):
    if isinstance(value, date_class):
        return value
    if isinstance(value, str):
        from django.utils.dateparse import parse_date
        parsed = parse_date(value)
        if parsed:
            return parsed
    raise LandedCostValidationError(f"{field} must be a valid date.")


def _positive_money(value, field):
    try:
        amount = quantize_half_up(to_decimal(value), 2)
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise LandedCostValidationError(f"{field} must be a valid amount.") from exc
    if amount <= 0:
        raise LandedCostValidationError(f"{field} must be greater than zero.")
    return amount


def _allocate(total, rows, weights):
    """Allocate a positive amount to cents, assigning rounding remainder last."""
    total = quantize_half_up(total, 2)
    weight_total = sum(weights, Decimal("0"))
    if total <= 0 or not rows or weight_total <= 0:
        raise LandedCostValidationError("Allocation requires a positive total and positive weights.")
    allocations = []
    allocated = Decimal("0.00")
    for index, weight in enumerate(weights):
        if index == len(weights) - 1:
            share = total - allocated
        else:
            share = quantize_half_up(total * weight / weight_total, 2)
            allocated += share
        if share <= 0:
            raise LandedCostValidationError(
                "The amount is too small to allocate a positive cent to every selected purchase line."
            )
        allocations.append(share)
    if sum(allocations, Decimal("0.00")) != total:
        raise LandedCostValidationError("Allocation does not reconcile to the source amount.")
    return allocations


def _validate_source_line(line):
    purchase = line.purchase
    if purchase.status != PurchaseStatus.POSTED:
        raise LandedCostValidationError("Landed costs can only be allocated to lines of a posted purchase.")
    reference = f"{purchase.document_number}:LINE:{line.pk}"
    if purchase.delivery_mode == "IN_TRANSIT":
        from goods_in_transit.models import GoodsInTransitLot
        if not GoodsInTransitLot.objects.filter(purchase_line=line).exists():
            raise LandedCostValidationError("The selected purchase line has no registered Goods-in-Transit lot.")
    elif not StockMovement.objects.filter(
        movement_type=MovementType.PURCHASE_RECEIPT,
        reference=reference,
        product_id=line.product_id,
        warehouse_id=purchase.warehouse_id,
    ).exists():
        raise LandedCostValidationError("The selected purchase line has no matching posted receipt movement.")
    return purchase


@transaction.atomic
def create_landed_cost_draft(
    *, document_number, payee, cost_date, currency, amount, exchange_rate,
    rate_date, category, description="", purchase_line_ids=(),
    allocation_method=LandedCostAllocationMethod.DIRECT,
    user=None, idempotency_key,
):
    """Create a DRAFT later-cost document and reconciled allocation snapshots.

    DIRECT must select exactly one source line. WEIGHT uses measured kg on all
    selected source lines. No journals or valuation effects are posted here.
    An exact retry returns the existing draft; key reuse with changed payload
    is rejected.
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 128:
        raise LandedCostValidationError("A valid idempotency key is required.")
    if not isinstance(document_number, str) or not document_number.strip() or len(document_number) > 30:
        raise LandedCostValidationError("A valid document number is required.")
    if not isinstance(category, str) or not category.strip() or len(category) > 40:
        raise LandedCostValidationError("A cost category is required.")
    if not isinstance(description, str) or len(description) > 500:
        raise LandedCostValidationError("Description must be text up to 500 characters.")
    if user is not None and not getattr(user, "is_authenticated", False):
        raise LandedCostValidationError("Authenticated user required.")
    day = _date(cost_date, "cost_date")
    fx_day = _date(rate_date, "rate_date")
    amount_value = _positive_money(amount, "amount")
    try:
        rate_value = normalize_rate(exchange_rate)
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise LandedCostValidationError("A positive historical exchange rate is required.") from exc
    if rate_value <= 0:
        raise LandedCostValidationError("A positive historical exchange rate is required.")
    if currency is None or not getattr(currency, "is_active", False):
        raise LandedCostValidationError("An active transaction currency is required.")
    if currency.is_base and rate_value != Decimal("1.0000"):
        raise LandedCostValidationError("Base-currency landed costs must use rate 1.0000.")
    if fx_day > day:
        raise LandedCostValidationError("Historical rate date cannot be after the cost date.")
    if payee is None or not getattr(payee, "is_supplier", False) or not getattr(payee, "is_active", False):
        raise LandedCostValidationError("The payee must be an active supplier/creditor party.")
    afn_total = amount_value if currency.is_base else fx_equivalent(amount_value, rate_value)

    try:
        line_ids = [int(value) for value in purchase_line_ids]
    except (TypeError, ValueError) as exc:
        raise LandedCostValidationError("Purchase line IDs must be integers.") from exc
    if not line_ids or len(line_ids) != len(set(line_ids)):
        raise LandedCostValidationError("Select one or more distinct purchase lines.")
    if allocation_method not in (
        LandedCostAllocationMethod.DIRECT, LandedCostAllocationMethod.WEIGHT
    ):
        raise LandedCostValidationError("Unsupported landed-cost allocation method.")
    if allocation_method == LandedCostAllocationMethod.DIRECT and len(line_ids) != 1:
        raise LandedCostValidationError("Direct allocation must target exactly one purchase line.")

    lines = list(
        PurchaseLine.objects.select_for_update()
        .filter(pk__in=line_ids)
        .select_related("purchase", "purchase__currency", "product")
        .order_by("pk")
    )
    if len(lines) != len(line_ids):
        raise LandedCostValidationError("One or more selected purchase lines do not exist.")
    by_id = {line.pk: line for line in lines}
    lines = [by_id[line_id] for line_id in line_ids]
    for line in lines:
        _validate_source_line(line)

    if allocation_method == LandedCostAllocationMethod.WEIGHT:
        weights = []
        for line in lines:
            weight = line.measured_weight_kg
            if weight is None or weight <= 0:
                raise LandedCostValidationError(
                    "Weight allocation requires a positive measured weight on every selected purchase line."
                )
            weights.append(weight)
    else:
        weights = [Decimal("1")]

    amount_shares = _allocate(amount_value, lines, weights)
    afn_shares = _allocate(afn_total, lines, weights)
    payload = {
        "document_number": document_number.strip(), "payee_id": getattr(payee, "pk", None),
        "cost_date": day, "currency_id": getattr(currency, "pk", None),
        "amount": amount_value, "exchange_rate": rate_value, "rate_date": fx_day,
        "afn_amount": afn_total, "category": category.strip(),
        "description": description.strip(), "purchase_line_ids": line_ids,
        "allocation_method": allocation_method, "weights": [str(w) for w in weights],
        "created_by_id": getattr(user, "pk", None),
    }
    existing = LandedCostDocument.objects.select_for_update().filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        old_allocations = list(existing.allocations.order_by("id").values_list(
            "purchase_line_id", "method", "amount", "afn_amount", "measured_weight_kg"
        ))
        expected_allocations = [
            (line.pk, allocation_method, amount_shares[i], afn_shares[i],
             weights[i] if allocation_method == LandedCostAllocationMethod.WEIGHT else None)
            for i, line in enumerate(lines)
        ]
        same_header = (
            existing.document_number == payload["document_number"]
            and existing.payee_id == payload["payee_id"]
            and existing.cost_date == day
            and existing.currency_id == payload["currency_id"]
            and existing.amount == amount_value
            and existing.exchange_rate == rate_value
            and existing.rate_date == fx_day
            and existing.afn_amount == afn_total
            and existing.category == payload["category"]
            and existing.description == payload["description"]
        )
        if same_header and old_allocations == expected_allocations:
            return existing
        raise LandedCostValidationError("Idempotency key was already used for a different landed-cost request.")

    if LandedCostDocument.objects.filter(document_number=document_number.strip()).exists():
        raise LandedCostValidationError("Landed-cost document number already exists.")

    document = LandedCostDocument.objects.create(
        document_number=document_number.strip(), payee=payee, cost_date=day,
        currency=currency, amount=amount_value, exchange_rate=rate_value,
        rate_date=fx_day, afn_amount=afn_total, category=category.strip(),
        description=description.strip(), status=LandedCostStatus.DRAFT,
        idempotency_key=idempotency_key, created_by=user,
    )
    LandedCostAllocation.objects.bulk_create([
        LandedCostAllocation(
            cost_document=document, purchase_line=line,
            method=allocation_method, amount=amount_shares[index],
            afn_amount=afn_shares[index],
            measured_weight_kg=weights[index] if allocation_method == LandedCostAllocationMethod.WEIGHT else None,
        )
        for index, line in enumerate(lines)
    ])
    record_audit_event(
        user=user, action=AuditAction.CREATE, entity="LandedCostDocument",
        entity_id=document.pk, reference=document.document_number,
        previous_state=None,
        new_state={
            "document_number": document.document_number,
            "payee_id": document.payee_id,
            "cost_date": document.cost_date.isoformat(),
            "currency": document.currency.code,
            "amount": str(document.amount),
            "exchange_rate": str(document.exchange_rate),
            "rate_date": document.rate_date.isoformat(),
            "afn_amount": str(document.afn_amount),
            "category": document.category,
            "status": document.status,
            "allocations": [
                {
                    "purchase_line_id": row.purchase_line_id,
                    "method": row.method,
                    "amount": str(row.amount),
                    "afn_amount": str(row.afn_amount),
                    "measured_weight_kg": str(row.measured_weight_kg) if row.measured_weight_kg is not None else None,
                }
                for row in document.allocations.order_by("id")
            ],
        },
        reason="",
    )
    return document
