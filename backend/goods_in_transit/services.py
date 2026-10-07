"""Goods in Transit ownership and physical-receipt services (Phase 11)."""

from decimal import Decimal

from django.db import transaction

from accounting.models import Account
from accounting.services import post_journal
from core.idempotency import DuplicateOperationError, idempotent_operation
from core.models import IdempotencyRecord
from core.money import quantize_half_up
from fiscal_periods.services import assert_posting_date_open
from inventory.services import receive_stock, resolve_warehouse_account
from security.models import AuditAction
from security.services import record_audit_event

from .models import GoodsInTransitLot, TransitCustomerCustody, TransitDestinationTransfer, TransitLotStatus, TransitReceipt


class TransitValidationError(ValueError):
    """Deterministic Goods in Transit rejection."""


TRANSIT_ACCOUNT = "1430"
TRANSIT_RECEIPT_OPERATION = "goods_in_transit.receipt"


def _actor(user):
    if user is not None and not getattr(user, "is_authenticated", False):
        raise TransitValidationError("Authenticated user required.")
    return user


def create_transit_lot(*, purchase, purchase_line, unit_cost, user=None,
                       journal_entry, idempotency_key):
    actor = _actor(user)
    if purchase.delivery_mode != "IN_TRANSIT":
        raise TransitValidationError("Purchase is not configured for owned Transit.")
    if purchase_line.purchase_id != purchase.pk:
        raise TransitValidationError("Purchase line does not belong to Purchase.")
    if purchase_line.pk is None:
        raise TransitValidationError("A persisted PurchaseLine is required.")
    if journal_entry is None:
        raise TransitValidationError("Purchase journal is required.")
    if GoodsInTransitLot.objects.filter(purchase_line=purchase_line).exists():
        return GoodsInTransitLot.objects.get(purchase_line=purchase_line)
    cost = quantize_half_up(unit_cost, 4)
    if cost < 0:
        raise TransitValidationError("Transit unit cost cannot be negative.")
    source = journal_entry.lines.filter(account__code=TRANSIT_ACCOUNT).first()
    if source is None:
        raise TransitValidationError("Purchase journal has no Goods in Transit line.")
    lot = GoodsInTransitLot.objects.create(
        purchase=purchase,
        purchase_line=purchase_line,
        product=purchase_line.product,
        supplier=purchase.supplier,
        destination_warehouse=purchase.warehouse,
        currency=purchase.currency,
        original_quantity=purchase_line.quantity,
        remaining_quantity=purchase_line.quantity,
        unit_cost=cost,
        rate=purchase.exchange_rate,
        rate_date=purchase.rate_date,
        ownership_date=purchase.purchase_date,
        journal_entry=journal_entry,
        status=TransitLotStatus.OPEN,
        idempotency_key=idempotency_key,
        created_by=actor,
    )
    record_audit_event(
        user=actor, action=AuditAction.CREATE, entity="GoodsInTransitLot",
        entity_id=lot.pk, reference=purchase.document_number,
        previous_state=None,
        new_state={
            "purchase_id": purchase.pk,
            "purchase_line_id": purchase_line.pk,
            "product_id": purchase_line.product_id,
            "original_quantity": purchase_line.quantity,
            "remaining_quantity": purchase_line.quantity,
            "unit_cost": str(cost),
        },
        reason="",
    )
    return lot


@transaction.atomic
def _receive_transit_legacy(*, lot, quantity, receipt_date, user=None,
                    idempotency_key=None):
    actor = _actor(user)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise TransitValidationError("Receipt quantity must be a positive integer.")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise TransitValidationError("A valid idempotency key is required.")
    lot_id = getattr(lot, "pk", lot)
    try:
        with idempotent_operation(
            key=idempotency_key, operation=TRANSIT_RECEIPT_OPERATION
        ) as record:
            with transaction.atomic():
                lot = GoodsInTransitLot.objects.select_for_update().select_related(
                    "purchase", "purchase_line", "product", "currency",
                    "destination_warehouse"
                ).get(pk=lot_id)
                if lot.status != TransitLotStatus.OPEN:
                    raise TransitValidationError("Transit lot is not open.")
                assert_posting_date_open(receipt_date)
                if quantity > lot.remaining_quantity:
                    raise TransitValidationError("Receipt exceeds remaining Transit quantity.")
                warehouse = lot.destination_warehouse
                warehouse_account = resolve_warehouse_account(warehouse)
                base_before = lot.remaining_quantity
                movement_reference = f"TRANSIT:{lot.purchase.document_number}:LOT:{lot.pk}:RECEIPT:{idempotency_key}"
                movement = receive_stock(
                    product=lot.product, warehouse=warehouse, quantity=quantity,
                    unit_cost=lot.unit_cost, currency=lot.currency,
                    rate=lot.rate, rate_date=lot.rate_date,
                    movement_date=receipt_date, reference=movement_reference,
                    description=f"Goods in Transit receipt for {lot.purchase.document_number}",
                    user=actor, party=lot.supplier,
                    idempotency_key=f"{idempotency_key}:movement",
                )
                from sales.services import resolve_negative_obligations
                resolve_negative_obligations(receipt_movement=movement)
                amount = quantize_half_up(lot.unit_cost * quantity, 2)
                entry = post_journal(
                    number=f"JE-TRANSIT-RECEIPT-{lot.pk}-{idempotency_key[:12]}",
                    posting_date=receipt_date,
                    description=f"Goods in Transit receipt {lot.purchase.document_number}",
                    lines=[
                        {"account": warehouse_account, "debit": amount, "reference": movement_reference},
                        {"account": Account.objects.get(code=TRANSIT_ACCOUNT), "credit": amount, "reference": movement_reference},
                    ],
                    source_type="GOODS_IN_TRANSIT_RECEIPT",
                    source_id=movement_reference,
                    currency=lot.currency,
                    rate=lot.rate,
                    rate_date=lot.rate_date,
                    created_by=actor,
                    idempotency_key=f"{idempotency_key}:journal",
                )
                remaining = base_before - quantity
                lot.remaining_quantity = remaining
                lot.status = TransitLotStatus.CLOSED if remaining == 0 else TransitLotStatus.OPEN
                lot.save(allow_state_transition=True, update_fields={"remaining_quantity", "status"})
                receipt = TransitReceipt.objects.create(
                    lot=lot, warehouse=warehouse, quantity=quantity,
                    receipt_date=receipt_date, stock_movement=movement,
                    journal_entry=entry, idempotency_key=idempotency_key,
                    created_by=actor,
                )
                record.response_body = {"receipt_id": receipt.pk}
                record.save(update_fields=["response_body"])
                record_audit_event(
                    user=actor, action=AuditAction.CREATE, entity="TransitReceipt",
                    entity_id=receipt.pk, reference=movement_reference,
                    previous_state={"remaining_quantity": base_before},
                    new_state={"remaining_quantity": remaining, "stock_movement_id": movement.pk},
                    reason="",
                )
                return receipt
    except GoodsInTransitLot.DoesNotExist as exc:
        raise TransitValidationError("Goods in Transit lot does not exist.") from exc
    except DuplicateOperationError:
        record = IdempotencyRecord.objects.filter(key=idempotency_key).first()
        if record is not None and (record.response_body or {}).get("receipt_id"):
            return TransitReceipt.objects.get(pk=record.response_body["receipt_id"])
        raise


@transaction.atomic
def transfer_transit_destination(*, lot, warehouse, quantity, transfer_date, user=None, idempotency_key=None):
    actor = _actor(user)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise TransitValidationError("Transfer quantity must be a positive integer.")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise TransitValidationError("A valid idempotency key is required.")
    from warehouses.services import resolve_warehouse
    target = resolve_warehouse(warehouse)
    if not target.is_active:
        raise TransitValidationError("Destination warehouse is inactive.")
    lot_id = getattr(lot, "pk", lot)
    with idempotent_operation(key=idempotency_key, operation="goods_in_transit.destination_transfer") as record:
        with transaction.atomic():
            lot = GoodsInTransitLot.objects.select_for_update().select_related("destination_warehouse").get(pk=lot_id)
            if lot.status != TransitLotStatus.OPEN:
                raise TransitValidationError("Transit lot is not open.")
            if quantity > lot.remaining_quantity:
                raise TransitValidationError("Transfer exceeds remaining Transit quantity.")
            if target.pk == lot.destination_warehouse_id:
                raise TransitValidationError("Destination warehouse is unchanged.")
            assert_posting_date_open(transfer_date)
            old_id = lot.destination_warehouse_id
            row = TransitDestinationTransfer.objects.create(lot=lot, from_warehouse_id=old_id, to_warehouse=target, quantity=quantity, transfer_date=transfer_date, idempotency_key=idempotency_key, created_by=actor)
            lot.destination_warehouse = target
            lot.save(allow_state_transition=True, update_fields={"destination_warehouse"})
            record.response_body = {"transfer_id": row.pk}
            record.save(update_fields=["response_body"])
            return row


@transaction.atomic
def receive_transit(*, lot, quantity, receipt_date, user=None, idempotency_key=None):
    actor = _actor(user)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise TransitValidationError("Receipt quantity must be a positive integer.")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise TransitValidationError("A valid idempotency key is required.")
    from django.db.models import Sum
    from sales.models import TransitSaleAllocation
    lot_id = getattr(lot, "pk", lot)
    with idempotent_operation(key=idempotency_key, operation=TRANSIT_RECEIPT_OPERATION) as record:
        with transaction.atomic():
            lot = GoodsInTransitLot.objects.select_for_update().select_related("purchase", "product", "currency", "destination_warehouse").get(pk=lot_id)
            if lot.status != TransitLotStatus.OPEN:
                raise TransitValidationError("Transit lot is not open.")
            assert_posting_date_open(receipt_date)
            allocations = list(TransitSaleAllocation.objects.select_related("sale_line__sale__customer").filter(transit_lot=lot).order_by("id"))
            custody_by_line = {x["sale_line_id"]: x["total"] or 0 for x in TransitCustomerCustody.objects.filter(sale_line__in=[a.sale_line_id for a in allocations]).values("sale_line_id").annotate(total=Sum("quantity"))}
            outstanding = sum(a.quantity - custody_by_line.get(a.sale_line_id, 0) for a in allocations)
            if quantity > lot.remaining_quantity + outstanding:
                raise TransitValidationError("Physical receipt exceeds remaining owned Transit plus sold customer custody.")
            company_qty = min(quantity, lot.remaining_quantity)
            custody_qty = quantity - company_qty
            if custody_qty > outstanding:
                raise TransitValidationError("Customer custody receipt exceeds sold Transit quantity.")
            warehouse = lot.destination_warehouse
            movement = None
            entry = None
            reference = f"TRANSIT:{lot.purchase.document_number}:LOT:{lot.pk}:RECEIPT:{idempotency_key}"
            if company_qty:
                movement = receive_stock(product=lot.product, warehouse=warehouse, quantity=company_qty, unit_cost=lot.unit_cost, currency=lot.currency, rate=lot.rate, rate_date=lot.rate_date, movement_date=receipt_date, reference=reference, description=f"Goods in Transit receipt for {lot.purchase.document_number}", user=actor, party=lot.supplier, idempotency_key=f"{idempotency_key}:movement")
                from sales.services import resolve_negative_obligations
                resolve_negative_obligations(receipt_movement=movement)
                amount = quantize_half_up(lot.unit_cost * company_qty, 2)
                entry = post_journal(number=f"JE-TRANSIT-RECEIPT-{lot.pk}-{idempotency_key[:12]}", posting_date=receipt_date, description=f"Goods in Transit receipt {lot.purchase.document_number}", lines=[{"account": resolve_warehouse_account(warehouse), "debit": amount, "reference": reference}, {"account": Account.objects.get(code=TRANSIT_ACCOUNT), "credit": amount, "reference": reference}], source_type="GOODS_IN_TRANSIT_RECEIPT", source_id=reference, currency=lot.currency, rate=lot.rate, rate_date=lot.rate_date, created_by=actor, idempotency_key=f"{idempotency_key}:journal")
            before = lot.remaining_quantity
            lot.remaining_quantity = before - company_qty
            lot.status = TransitLotStatus.CLOSED if lot.remaining_quantity == 0 else TransitLotStatus.OPEN
            lot.save(allow_state_transition=True, update_fields={"remaining_quantity", "status"})
            receipt = TransitReceipt.objects.create(lot=lot, warehouse=warehouse, quantity=quantity, company_quantity=company_qty, customer_custody_quantity=custody_qty, receipt_date=receipt_date, stock_movement=movement, journal_entry=entry, idempotency_key=idempotency_key, created_by=actor)
            left = custody_qty
            for allocation in allocations:
                available = allocation.quantity - custody_by_line.get(allocation.sale_line_id, 0)
                take = min(available, left)
                if take:
                    TransitCustomerCustody.objects.create(receipt=receipt, sale_line=allocation.sale_line, customer=allocation.sale_line.sale.customer, warehouse=warehouse, quantity=take, receipt_date=receipt_date)
                    left -= take
                if left == 0:
                    break
            if left:
                raise TransitValidationError("Customer custody allocation could not be completed.")
            record.response_body = {"receipt_id": receipt.pk}
            record.save(update_fields=["response_body"])
            record_audit_event(user=actor, action=AuditAction.CREATE, entity="TransitReceipt", entity_id=receipt.pk, reference=reference, previous_state={"remaining_quantity": before}, new_state={"remaining_quantity": lot.remaining_quantity, "company_quantity": company_qty, "customer_custody_quantity": custody_qty}, reason="")
            return receipt
