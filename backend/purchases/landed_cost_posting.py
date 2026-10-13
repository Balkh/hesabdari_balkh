"""Phase 11 late landed-cost posting and immutable valuation reallocation.

A cost invoice is posted once to inventory / Goods-in-Transit (1430) and
supplier payable (2110). The historical Kardex and posted journals remain
immutable. This service replays the existing AVCO rule with a virtual cost
layer, then posts compensating AFN journals for downstream sales, returns,
transfers and Transit receipts/sales. Unknown/ambiguous flows fail closed.
"""
import hashlib
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounting.models import Account, JournalEntry
from accounting.services import post_journal
from core.money import quantize_half_up
from currencies.models import Currency
from documents.services import next_document_number
from fiscal_periods.services import assert_posting_date_open
from inventory.models import InventoryReturn, MovementType, StockMovement
from inventory.services import resolve_warehouse_account
from party_ledger.services import attribute_journal_line
from security.models import AuditAction
from security.services import record_audit_event

from .models import (
    LandedCostAllocation, LandedCostDocument, LandedCostStatus,
    LandedCostValuationAdjustment, LandedCostReversal, PurchaseLine, PurchaseReturn,
)


CENT = Decimal("0.01")
FOUR_DP = Decimal("0.0001")
TRANSIT_ACCOUNT = "1430"
PAYABLE_ACCOUNT = "2110"
COGS_ACCOUNT = "5100"


class LandedCostPostingError(ValueError):
    """A landed-cost post cannot be completed without violating valuation truth."""


def _q4(value):
    return quantize_half_up(Decimal(value), 4)


def _q2(value):
    return quantize_half_up(Decimal(value), 2)


def _jalali_year(day):
    from core.dates import gregorian_to_jalali
    return int(gregorian_to_jalali(day).split("/")[0])


def _base_currency():
    currency = Currency.objects.filter(is_base=True, is_active=True).first()
    if currency is None:
        raise LandedCostPostingError("An active base currency is required.")
    return currency


def _account(code):
    try:
        account = Account.objects.get(code=code)
    except Account.DoesNotExist as exc:
        raise LandedCostPostingError(f"Required account {code} is missing.") from exc
    if not account.is_active or not account.is_posting:
        raise LandedCostPostingError(f"Required account {code} is not postable.")
    return account


def _source_movement(line, *, lock=True):
    from .models import PurchaseDeliveryMode
    purchase = line.purchase
    if purchase.delivery_mode == PurchaseDeliveryMode.IN_TRANSIT:
        return None
    reference = f"{purchase.document_number}:LINE:{line.pk}"
    queryset = StockMovement.objects.filter(
        movement_type=MovementType.PURCHASE_RECEIPT,
        reference=reference, product_id=line.product_id,
        warehouse_id=purchase.warehouse_id,
    )
    if lock:
        queryset = queryset.select_for_update()
    rows = list(queryset)
    if len(rows) != 1:
        raise LandedCostPostingError(
            f"Purchase line {line.pk} must resolve to exactly one immutable receipt movement."
        )
    return rows[0]


def _lot_for(line):
    from goods_in_transit.models import GoodsInTransitLot
    try:
        return GoodsInTransitLot.objects.select_for_update().get(purchase_line=line)
    except GoodsInTransitLot.DoesNotExist as exc:
        raise LandedCostPostingError(
            f"Transit purchase line {line.pk} has no immutable Goods-in-Transit lot."
        ) from exc


def _posted_prior_allocations(line_ids):
    return list(LandedCostAllocation.objects.filter(
        purchase_line_id__in=line_ids,
        cost_document__status=LandedCostStatus.POSTED,
        cost_document__reversal__isnull=True,
    ).select_related("purchase_line", "cost_document").order_by(
        "cost_document__cost_date", "id"
    ))


def _extra_cost_map(lines, allocations, *, lock=True):
    """Map immutable warehouse movement IDs to additional AFN/unit from posted costs."""
    from goods_in_transit.models import GoodsInTransitLot, TransitReceipt
    from sales.models import SalesReturn, TransitSaleAllocation

    line_by_id = {line.pk: line for line in lines}
    per_line = defaultdict(lambda: Decimal("0"))
    for allocation in allocations:
        line = line_by_id.get(allocation.purchase_line_id)
        if line is None:
            continue
        # Sum the exact posted AFN layers first, then round once per unit.
        # Rounding each invoice separately can accumulate a false unit-cost
        # difference when several direct-cost documents target the same line.
        per_line[line.pk] += allocation.afn_amount

    extra = defaultdict(lambda: Decimal("0"))
    for line_id, allocated_afn in per_line.items():
        line = line_by_id[line_id]
        delta_per_unit = _q4(allocated_afn / Decimal(line.quantity))
        if not delta_per_unit:
            continue
        lot = GoodsInTransitLot.objects.filter(purchase_line_id=line_id).first()
        if lot is None:
            movement = _source_movement(line, lock=lock)
            extra[movement.pk] += delta_per_unit
            continue
        receipts = TransitReceipt.objects.filter(lot=lot).exclude(stock_movement__isnull=True).select_related("stock_movement")
        for receipt in receipts:
            # Only company-owned quantity creates a company inventory movement.
            if receipt.company_quantity:
                extra[receipt.stock_movement_id] += delta_per_unit
        sale_allocations = TransitSaleAllocation.objects.filter(transit_lot=lot).select_related("sale_line")
        for sale_allocation in sale_allocations:
            returns = SalesReturn.objects.filter(
                sale_line_id=sale_allocation.sale_line_id,
                return_movement__isnull=False,
            )
            for sales_return in returns:
                extra[sales_return.return_movement_id] += delta_per_unit
    return dict(extra)


def _movement_return_context(movement):
    """Resolve return source and financial return document without guessing."""
    from sales.models import SalesReturn

    inventory_return = InventoryReturn.objects.filter(
        return_movement=movement
    ).select_related("source_movement").first()
    sales_return = SalesReturn.objects.filter(
        Q(inventory_return__return_movement=movement) | Q(return_movement=movement)
    ).select_related("sale_line", "sale_line__sale").first()
    purchase_return = None
    if inventory_return is not None:
        purchase_return = PurchaseReturn.objects.filter(
            inventory_return=inventory_return
        ).select_related("journal_entry", "supplier").first()
    return inventory_return, sales_return, purchase_return


def _transfer_pairs(movements):
    groups = defaultdict(list)
    for movement in movements:
        if movement.movement_type in (MovementType.TRANSFER_IN, MovementType.TRANSFER_OUT):
            groups[(movement.reference, movement.movement_date)].append(movement)
    out_for_in = {}
    in_for_out = {}
    for key, rows in groups.items():
        outs = [m for m in rows if m.movement_type == MovementType.TRANSFER_OUT]
        ins = [m for m in rows if m.movement_type == MovementType.TRANSFER_IN]
        if len(outs) != 1 or len(ins) != 1 or outs[0].product_id != ins[0].product_id:
            raise LandedCostPostingError(
                f"Transfer {key[0]} does not have one unambiguous OUT/IN pair."
            )
        out_for_in[ins[0].pk] = outs[0]
        in_for_out[outs[0].pk] = ins[0]
    return out_for_in, in_for_out


def _simulate_product(product_id, baseline_extra_costs, revised_extra_costs, earliest_date, *, strict=True, allowed_negative_issue_ids=()):
    """Replay the existing 4dp AVCO rule without changing any posted movement."""
    movements = list(StockMovement.objects.filter(
        product_id=product_id
    ).select_related("warehouse", "currency").order_by("movement_date", "id"))
    if not movements:
        # A Transit lot may be sold or still owned entirely outside physical
        # warehouses. Its asset/COGS split is reconciled by Transit events below.
        return [], {}, {}, {}, {}, {}
    out_for_in, in_for_out = _transfer_pairs(movements)
    from sales.models import SalesReturn
    allowed_negative_issue_ids = set(allowed_negative_issue_ids)

    # The same event stream is replayed under the prior basis and the proposed basis.
    def replay(extra_unit_costs):
        state = {}  # warehouse_id -> [quantity, cost basis AFN]
        results = {}
        for movement in movements:
            wid = movement.warehouse_id
            qty, basis = state.get(wid, [0, Decimal("0")])
            signed = movement.quantity
            unit = movement.unit_cost_afn
            if strict and movement.is_temporary_cost and movement.movement_date >= earliest_date and movement.pk not in allowed_negative_issue_ids:
                raise LandedCostPostingError(
                    f"Movement {movement.reference} uses a temporary cost; late valuation is blocked until resolved."
                )
            if strict and movement.movement_type in (MovementType.ADJUSTMENT_OUT, MovementType.SHORTAGE) and movement.movement_date >= earliest_date:
                raise LandedCostPostingError(
                    f"Movement {movement.reference} has an unlinked expense/shortage valuation; resolve it before finalizing landed cost."
                )

            if movement.movement_type == MovementType.TRANSFER_IN:
                paired_out = out_for_in.get(movement.pk)
                if paired_out is None or paired_out.pk not in results:
                    raise LandedCostPostingError("Transfer-in precedes its paired transfer-out in Kardex order.")
                unit = results[paired_out.pk]["relief_unit"]
            elif movement.movement_type == MovementType.SALES_RETURN:
                inventory_return, sales_return, _purchase_return = _movement_return_context(movement)
                if inventory_return is not None:
                    source_id = inventory_return.source_movement_id
                    if source_id not in results:
                        raise LandedCostPostingError("Sales return source issue is not earlier in the valuation history.")
                    unit = results[source_id]["relief_unit"]
                elif sales_return is not None and sales_return.return_movement_id:
                    # Transit sale returns have no company issue movement; the virtual
                    # landed-cost layer is explicitly attached to this return movement.
                    unit = movement.unit_cost_afn
                else:
                    raise LandedCostPostingError(f"Sales return {movement.reference} has no traceable source.")

            if signed > 0:
                unit += extra_unit_costs.get(movement.pk, Decimal("0"))
                inbound_value = Decimal(signed) * unit
                if qty >= 0:
                    qty += signed
                    basis += inbound_value
                else:
                    qty += signed
                    if qty > 0:
                        basis = Decimal(qty) * unit
                    else:
                        basis = Decimal("0")
                relief = Decimal("0")
                relief_unit = unit
            else:
                if qty < 0 and strict and movement.pk not in allowed_negative_issue_ids:
                    raise LandedCostPostingError(
                        f"Product {product_id} has negative stock before {movement.reference}; valuation replay is ambiguous."
                    )
                taken = -signed
                if qty > 0:
                    average = _q4(basis / Decimal(qty))
                    relieved_qty = min(taken, qty)
                    relief = Decimal(relieved_qty) * average
                    relief_unit = average
                    basis -= relief
                    qty -= taken
                    if qty <= 0:
                        basis = Decimal("0")
                    elif basis < 0:
                        basis = Decimal("0")
                elif strict and movement.pk not in allowed_negative_issue_ids:
                    raise LandedCostPostingError(
                        f"Product {product_id} has an issue with no positive cost basis at {movement.reference}."
                    )
                else:
                    # A negative-stock issue is replayable only when an immutable
                    # receipt-allocation record proves which later receipt resolved it.
                    qty -= taken
                    basis = Decimal("0")
                    relief = Decimal("0")
                    relief_unit = movement.unit_cost_afn
                inbound_value = Decimal("0")
            if qty < 0 and strict and signed < 0 and movement.pk not in allowed_negative_issue_ids:
                raise LandedCostPostingError(
                    f"Product {product_id} becomes negative at {movement.reference}; late valuation is blocked."
                )
            state[wid] = [qty, basis]
            results[movement.pk] = {
                "quantity": qty, "basis": basis,
                "relief": relief, "relief_unit": relief_unit,
                "inbound": inbound_value, "unit": unit,
            }
        if strict and any(pair[0] < 0 for pair in state.values()):
            raise LandedCostPostingError(
                f"Product {product_id} still has unresolved negative stock after valuation replay."
            )
        return results, state

    baseline, baseline_state = replay(baseline_extra_costs)
    revised, revised_state = replay(revised_extra_costs)
    return movements, baseline, revised, baseline_state, revised_state, in_for_out


def _post_adjustment(*, document, adjustment_type, reference, movement,
                     debit_account, credit_account, amount, posting_day,
                     actor, party=None):
    signed = _q2(amount)
    if signed == 0:
        return None
    if abs(signed) <= 0:
        return None
    debit = debit_account if signed > 0 else credit_account
    credit = credit_account if signed > 0 else debit_account
    value = abs(signed)
    base = _base_currency()
    fingerprint_ref = str(reference)[:200]
    existing = LandedCostValuationAdjustment.objects.filter(
        cost_document=document, source_reference=fingerprint_ref,
        adjustment_type=adjustment_type,
    ).first()
    if existing:
        if existing.amount_afn != value or existing.movement_id != getattr(movement, "pk", None):
            raise LandedCostPostingError("Existing valuation adjustment does not match the planned adjustment.")
        return existing
    number = next_document_number("JE", _jalali_year(posting_day))
    entry = post_journal(
        number=number, posting_date=posting_day,
        description=f"Landed-cost {adjustment_type.lower()} adjustment: {document.document_number}",
        lines=[
            {"account": debit, "debit": value, "reference": reference,
             "description": f"Landed cost {document.document_number}"},
            {"account": credit, "credit": value, "reference": reference,
             "description": f"Landed cost {document.document_number}"},
        ],
        source_type="LANDED_COST_VALUATION_ADJUSTMENT",
        source_id=f"{document.document_number}:{adjustment_type}:{getattr(movement, 'pk', reference)}",
        currency=base, rate=Decimal("1.0000"), rate_date=posting_day,
        created_by=actor,
        idempotency_key=f"landed-cost:{document.pk}:adjustment:{adjustment_type}:{getattr(movement, 'pk', reference)}",
    )
    if party is not None:
        attribute_journal_line(
            entry.lines.filter(account=debit).first() if debit == _account(PAYABLE_ACCOUNT)
            else entry.lines.filter(account=credit).first(),
            party=party, user=actor,
        )
    return LandedCostValuationAdjustment.objects.create(
        cost_document=document, source_reference=fingerprint_ref,
        adjustment_type=adjustment_type, movement=movement,
        amount_afn=value, journal_entry=entry,
    )


def _post_purchase_return_adjustment(*, document, reference, movement,
                                     warehouse, payable_party,
                                     inventory_delta, payable_delta,
                                     posting_day, actor):
    """Keep supplier claim at its source-receipt cost while AVCO inventory
    relief remains consistent with the Kardex. Any difference is an explicit
    COGS variance, never a silent mismatch between AP and inventory.
    """
    inventory_delta = _q2(inventory_delta)
    payable_delta = _q2(payable_delta)
    if inventory_delta == 0 and payable_delta == 0:
        return None
    inventory_account = resolve_warehouse_account(warehouse)
    payable = _account(PAYABLE_ACCOUNT)
    cogs = _account(COGS_ACCOUNT)
    lines = []
    if payable_delta > 0:
        lines.append({"account": payable, "debit": payable_delta, "reference": reference,
                      "description": "Landed-cost adjustment to supplier return claim"})
    elif payable_delta < 0:
        lines.append({"account": payable, "credit": abs(payable_delta), "reference": reference,
                      "description": "Reverse landed-cost adjustment to supplier return claim"})
    if inventory_delta > 0:
        lines.append({"account": inventory_account, "credit": inventory_delta, "reference": reference,
                      "description": "Remove adjusted AVCO from returned stock"})
    elif inventory_delta < 0:
        lines.append({"account": inventory_account, "debit": abs(inventory_delta), "reference": reference,
                      "description": "Reverse adjusted AVCO removal"})
    debit_total = sum((line.get("debit", Decimal("0")) for line in lines), Decimal("0"))
    credit_total = sum((line.get("credit", Decimal("0")) for line in lines), Decimal("0"))
    if debit_total > credit_total:
        lines.append({"account": cogs, "credit": debit_total - credit_total,
                      "reference": reference, "description": "Purchase-return cost variance"})
    elif credit_total > debit_total:
        lines.append({"account": cogs, "debit": credit_total - debit_total,
                      "reference": reference, "description": "Purchase-return cost variance"})
    if sum((line.get("debit", Decimal("0")) for line in lines), Decimal("0")) != sum(
        (line.get("credit", Decimal("0")) for line in lines), Decimal("0")
    ):
        raise LandedCostPostingError("Purchase-return adjustment journal failed to balance.")
    base = _base_currency()
    digest = hashlib.sha256(str(movement.pk).encode()).hexdigest()[:20]
    entry = post_journal(
        number=next_document_number("JE", _jalali_year(posting_day)),
        posting_date=posting_day,
        description=f"Landed-cost purchase-return adjustment: {document.document_number}",
        lines=lines, source_type="LANDED_COST_VALUATION_ADJUSTMENT",
        source_id=f"{document.document_number}:PURCHASE_RETURN:{digest}",
        currency=base, rate=Decimal("1.0000"), rate_date=posting_day,
        created_by=actor,
        idempotency_key=f"landed-cost:{document.pk}:adjustment:PURCHASE_RETURN:{movement.pk}",
    )
    payable_line = entry.lines.filter(account=payable).first()
    if payable_line is not None and payable_party is not None:
        attribute_journal_line(payable_line, party=payable_party, user=actor)
    return LandedCostValuationAdjustment.objects.create(
        cost_document=document, source_reference=reference[:200],
        adjustment_type="PURCHASE_RETURN", movement=movement,
        amount_afn=max(abs(inventory_delta), abs(payable_delta),
                       abs(inventory_delta - payable_delta)),
        journal_entry=entry,
    )


@transaction.atomic
def post_landed_cost(*, cost_document, user=None):
    """Post one landed-cost invoice and all traceable AFN valuation adjustments.

    The document cost date is also the posting date and must be in an open
    fiscal period. Exact retries return the already-posted document. Posted
    purchase/movement/journal snapshots are never rewritten.
    """
    document_id = getattr(cost_document, "pk", cost_document)
    # Lock only the document row: journal_entry is nullable until posting,
    # and PostgreSQL rejects FOR UPDATE across that nullable outer join.
    document = LandedCostDocument.objects.select_for_update(of=("self",)).select_related(
        "currency", "payee", "journal_entry"
    ).get(pk=document_id)
    if document.status == LandedCostStatus.POSTED:
        if document.journal_entry_id is None:
            raise LandedCostPostingError("Posted landed-cost document has no source journal.")
        if LandedCostReversal.objects.filter(cost_document=document).exists():
            raise LandedCostPostingError("This landed-cost document has already been reversed.")
        return document
    actor = user or document.created_by
    if actor is not None and not getattr(actor, "is_authenticated", False):
        raise LandedCostPostingError("Authenticated user required.")
    day = document.cost_date
    assert_posting_date_open(day)
    allocations = list(document.allocations.select_related(
        "purchase_line", "purchase_line__purchase", "purchase_line__purchase__warehouse",
        "purchase_line__purchase__currency", "purchase_line__product",
    ).order_by("id"))
    if not allocations:
        raise LandedCostPostingError("A landed-cost document must have allocations.")
    if sum((row.amount for row in allocations), Decimal("0.00")) != document.amount:
        raise LandedCostPostingError("Transaction-currency allocations do not reconcile to the cost document.")
    if sum((row.afn_amount for row in allocations), Decimal("0.00")) != document.afn_amount:
        raise LandedCostPostingError("AFN allocations do not reconcile to the cost document.")

    lines = []
    seen = set()
    for row in allocations:
        line = row.purchase_line
        purchase = line.purchase
        if purchase.status != "POSTED":
            raise LandedCostPostingError(f"Source purchase {purchase.document_number} is not posted.")
        if day < purchase.purchase_date:
            raise LandedCostPostingError("Cost date cannot precede its source purchase.")
        if line.pk not in seen:
            seen.add(line.pk)
            lines.append(line)
    # Lock all source rows in stable primary-key order before reading the
    # prior posted cost layers. This serializes two cost documents targeting
    # the same purchase line and prevents a stale AVCO baseline on retry.
    lines.sort(key=lambda line: line.pk)
    earliest_by_product = {}
    source_movements = {}
    transit_lots = {}
    from goods_in_transit.models import TransitReceipt
    from sales.models import SalesReturn, TransitSaleAllocation
    for line in lines:
        purchase = line.purchase
        if purchase.delivery_mode == "IN_TRANSIT":
            lot = _lot_for(line)
            transit_lots[line.pk] = lot
            has_company_receipt = TransitReceipt.objects.filter(
                lot=lot, company_quantity__gt=0, stock_movement__isnull=False
            ).exists()
            transit_sale_line_ids = TransitSaleAllocation.objects.filter(
                transit_lot=lot
            ).values_list("sale_line_id", flat=True)
            has_transit_return = SalesReturn.objects.filter(
                sale_line_id__in=transit_sale_line_ids,
                return_movement__isnull=False,
            ).exists()
            # An unreceived Transit lot has no warehouse AVCO layer yet. Its
            # remaining asset and in-transit sales are reconciled separately;
            # replay warehouse Kardex only after a company receipt or physical
            # Transit return movement exists.
            if not (has_company_receipt or has_transit_return):
                continue
            earliest = lot.ownership_date
        else:
            source = _source_movement(line)
            source_movements[line.pk] = source
            earliest = source.movement_date
        current = earliest_by_product.get(line.product_id)
        earliest_by_product[line.product_id] = min(current, earliest) if current else earliest

    line_ids = [line.pk for line in lines]
    product_ids = sorted(earliest_by_product)
    # Serialize cost finalization by product, not only by purchase line: two
    # invoices for different receipts of the same product both affect AVCO.
    if lines:
        product_model = type(lines[0].product)
        list(product_model.objects.select_for_update().filter(
            pk__in=product_ids
        ).order_by("pk").values_list("pk", flat=True))

    # The baseline must include every posted cost layer for each affected
    # product, including costs attached to earlier/different purchase lines.
    # Otherwise a second late cost would replay AVCO without the first layer
    # and calculate the wrong marginal COGS/inventory/transfer adjustments.
    prior = list(LandedCostAllocation.objects.filter(
        purchase_line__product_id__in=product_ids,
        cost_document__status=LandedCostStatus.POSTED,
        cost_document__reversal__isnull=True,
    ).select_related("purchase_line", "cost_document").order_by(
        "cost_document__cost_date", "id"
    ))
    valuation_line_ids = {row.purchase_line_id for row in prior} | set(line_ids)
    valuation_lines = list(PurchaseLine.objects.filter(
        pk__in=valuation_line_ids
    ).select_related(
        "purchase", "purchase__warehouse", "purchase__currency", "product"
    ).order_by("pk"))
    # Prior layers form the baseline; this document is the only delta.
    baseline_extra = _extra_cost_map(valuation_lines, prior)
    revised_extra = _extra_cost_map(valuation_lines, prior + allocations)

    # Build one replay per affected product, sharing the complete chronology
    # so AVCO effects continue through warehouse transfers and sales returns.
    from sales.models import NegativeCOGSReceiptAllocation

    product_results = {}
    for product_id in sorted(earliest_by_product):
        # Negative-stock issue rows are replayable only when a persisted
        # receipt-allocation record proves which later receipt resolved them.
        allowed_negative_issue_ids = set(
            NegativeCOGSReceiptAllocation.objects.filter(
                obligation__product_id=product_id,
                receipt_movement__product_id=product_id,
            ).values_list("obligation__movement_id", flat=True)
        )
        product_results[product_id] = _simulate_product(
            product_id, baseline_extra, revised_extra, earliest_by_product[product_id],
            allowed_negative_issue_ids=allowed_negative_issue_ids,
        )
    # Invoice posting: capitalize full cost before reallocation. The subsequent
    # adjustment journals move the sold/returned/transferred portions out of
    # this initial asset debit; the remainder stays in inventory / 1430.
    payable = _account(PAYABLE_ACCOUNT)
    invoice_lines = []
    for row in allocations:
        line = row.purchase_line
        purchase = line.purchase
        if purchase.delivery_mode == "IN_TRANSIT":
            inventory_account = _account(TRANSIT_ACCOUNT)
        else:
            inventory_account = resolve_warehouse_account(purchase.warehouse)
        invoice_lines.append({
            "account": inventory_account, "debit": row.amount,
            "reference": f"{document.document_number}:LINE:{line.pk}",
            "description": f"Capitalized {document.category.lower()} for {purchase.document_number}",
        })
    invoice_lines.append({
        "account": payable, "credit": document.amount,
        "reference": document.document_number,
        "description": f"Payable for landed cost {document.document_number}",
    })
    journal = post_journal(
        number=next_document_number("JE", _jalali_year(day)),
        posting_date=day,
        description=f"Landed cost {document.document_number}: {document.description or document.category}",
        lines=invoice_lines, source_type="LANDED_COST",
        source_id=document.document_number, currency=document.currency,
        rate=document.exchange_rate, rate_date=document.rate_date,
        created_by=actor,
        idempotency_key=f"landed-cost:{document.pk}:source-journal",
    )
    attribute_journal_line(
        journal.lines.get(account=payable), party=document.payee, user=actor
    )
    document.journal_entry = journal
    document.status = LandedCostStatus.POSTED
    document.posted_at = timezone.now()
    document.save(update_fields=["journal_entry", "status", "posted_at"])

    # Transit allocations: invoice source is Dr 1430. Reclass cost for goods
    # already physically received; sold-in-transit goods go directly to COGS.
    transit_delta_by_line = {}
    transit_negative_cogs_delta = Decimal("0.00")
    from goods_in_transit.models import TransitReceipt
    from sales.models import NegativeCOGSReceiptAllocation, SalesReturn, TransitSaleAllocation
    for row in allocations:
        line = row.purchase_line
        if line.pk not in transit_lots:
            continue
        lot = transit_lots[line.pk]
        per_unit = _q4(row.afn_amount / Decimal(lot.original_quantity))
        transit_delta_by_line[line.pk] = per_unit
        receipts = list(TransitReceipt.objects.filter(
            lot=lot, company_quantity__gt=0, stock_movement__isnull=False
        ).select_related("stock_movement", "warehouse").order_by("id"))
        resolved_by_obligation = defaultdict(int)
        resolved_by_receipt = {}
        for receipt in receipts:
            links = list(NegativeCOGSReceiptAllocation.objects.filter(
                receipt_movement=receipt.stock_movement
            ).select_related("obligation", "obligation__movement").order_by("id"))
            consumed = sum(link.quantity for link in links)
            if consumed > receipt.company_quantity:
                raise LandedCostPostingError(
                    f"Transit receipt {receipt.stock_movement.reference} resolves more negative stock than its company quantity."
                )
            resolved_by_receipt[receipt.pk] = consumed
            for link in links:
                resolved_by_obligation[link.obligation_id] += link.quantity
        for receipt in receipts:
            remaining_company_qty = receipt.company_quantity - resolved_by_receipt[receipt.pk]
            value = _q2(per_unit * Decimal(remaining_company_qty))
            _post_adjustment(
                document=document, adjustment_type="TRANSIT_RECEIPT",
                reference=receipt.stock_movement.reference,
                movement=receipt.stock_movement,
                debit_account=resolve_warehouse_account(receipt.warehouse),
                credit_account=_account(TRANSIT_ACCOUNT), amount=value,
                posting_day=day, actor=actor,
            )
        for obligation_id, resolved_quantity in sorted(resolved_by_obligation.items()):
            link = next(
                link for receipt in receipts
                for link in NegativeCOGSReceiptAllocation.objects.filter(
                    receipt_movement=receipt.stock_movement,
                    obligation_id=obligation_id,
                ).select_related("obligation", "obligation__movement", "obligation__warehouse")
            )
            amount = _q2(per_unit * Decimal(resolved_quantity))
            if amount:
                reference = f"{link.obligation.movement.reference}:NEGATIVE-RECEIPT:{link.receipt_movement_id}"
                _post_adjustment(
                    document=document, adjustment_type="NEGATIVE_COGS_OBLIGATION",
                    reference=reference, movement=link.obligation.movement,
                    debit_account=_account(COGS_ACCOUNT),
                    credit_account=_account(TRANSIT_ACCOUNT), amount=amount,
                    posting_day=day, actor=actor,
                )
                transit_negative_cogs_delta += amount
        for sale_allocation in TransitSaleAllocation.objects.filter(
            transit_lot=lot
        ).select_related("sale_line", "cogs_journal"):
            value = _q2(per_unit * Decimal(sale_allocation.quantity))
            _post_adjustment(
                document=document, adjustment_type="TRANSIT_SALE",
                reference=f"TRANSIT-SALE:{sale_allocation.sale_line_id}",
                movement=None, debit_account=_account(COGS_ACCOUNT),
                credit_account=_account(TRANSIT_ACCOUNT), amount=value,
                posting_day=day, actor=actor,
            )

    cogs_delta = transit_negative_cogs_delta
    purchase_return_delta = Decimal("0.00")
    inventory_delta = Decimal("0.00")

    # A purchase receipt may resolve a sale that was already posted against a
    # manually entered temporary cost. The receipt allocation ledger preserves
    # that source relationship even when the original receipt needed no COGS
    # correction; a later landed cost must therefore flow to that prior COGS.
    for row in allocations:
        line = row.purchase_line
        source = source_movements.get(line.pk)
        if source is None:
            continue
        per_unit = _q4(row.afn_amount / Decimal(line.quantity))
        if not per_unit:
            continue
        for resolved in NegativeCOGSReceiptAllocation.objects.filter(
            receipt_movement=source
        ).select_related("obligation", "obligation__movement", "obligation__warehouse").order_by("id"):
            obligation = resolved.obligation
            if not JournalEntry.objects.filter(
                source_type="SALES_COGS", source_id=obligation.movement.reference
            ).exists():
                raise LandedCostPostingError(
                    f"Negative-COGS obligation {obligation.pk} has no original posted COGS journal."
                )
            amount = _q2(per_unit * Decimal(resolved.quantity))
            if amount <= 0:
                continue
            _post_adjustment(
                document=document, adjustment_type="NEGATIVE_COGS_OBLIGATION",
                reference=obligation.movement.reference,
                movement=obligation.movement,
                debit_account=_account(COGS_ACCOUNT),
                credit_account=resolve_warehouse_account(obligation.warehouse),
                amount=amount, posting_day=day, actor=actor,
            )
            cogs_delta += amount

    for product_id, result in product_results.items():
        movements, baseline, revised, base_state, revised_state, in_for_out = result
        earliest = earliest_by_product[product_id]
        for movement in movements:
            if movement.movement_date < earliest:
                continue
            delta = Decimal("0.00")
            if movement.movement_type in (
                MovementType.SALES_ISSUE, MovementType.TRANSFER_OUT,
                MovementType.PURCHASE_RETURN,
            ):
                delta = _q2(revised[movement.pk]["relief"] - baseline[movement.pk]["relief"])
            elif movement.movement_type == MovementType.SALES_RETURN:
                delta = _q2(revised[movement.pk]["inbound"] - baseline[movement.pk]["inbound"])
            if delta == 0:
                continue
            if movement.movement_type == MovementType.SALES_ISSUE:
                if not Account.objects.filter(code=COGS_ACCOUNT, is_active=True, is_posting=True).exists():
                    raise LandedCostPostingError("COGS account 5100 is unavailable.")
                if not JournalEntry.objects.filter(
                    source_type="SALES_COGS", source_id=movement.reference
                ).exists():
                    raise LandedCostPostingError(
                        f"Sales issue {movement.reference} has no matching posted COGS journal."
                    )
                _post_adjustment(
                    document=document, adjustment_type="SALES_ISSUE",
                    reference=movement.reference, movement=movement,
                    debit_account=_account(COGS_ACCOUNT),
                    credit_account=resolve_warehouse_account(movement.warehouse),
                    amount=delta, posting_day=day, actor=actor,
                )
                cogs_delta += delta
            elif movement.movement_type == MovementType.TRANSFER_OUT:
                transfer_in = in_for_out.get(movement.pk)
                if transfer_in is None:
                    raise LandedCostPostingError("Transfer-out has no paired transfer-in.")
                _post_adjustment(
                    document=document, adjustment_type="WAREHOUSE_TRANSFER",
                    reference=movement.reference, movement=movement,
                    debit_account=resolve_warehouse_account(transfer_in.warehouse),
                    credit_account=resolve_warehouse_account(movement.warehouse),
                    amount=delta, posting_day=day, actor=actor,
                )
            elif movement.movement_type == MovementType.PURCHASE_RETURN:
                inventory_return, _sales_return, purchase_return = _movement_return_context(movement)
                if inventory_return is None or purchase_return is None:
                    raise LandedCostPostingError(
                        f"Purchase return {movement.reference} has no posted supplier-claim document."
                    )
                source_result_before = baseline.get(inventory_return.source_movement_id)
                source_result_after = revised.get(inventory_return.source_movement_id)
                if source_result_before is None or source_result_after is None:
                    raise LandedCostPostingError("Purchase-return source receipt is missing from valuation replay.")
                source_unit_delta = source_result_after["unit"] - source_result_before["unit"]
                payable_delta = _q2(source_unit_delta * Decimal(abs(movement.quantity)))
                _post_purchase_return_adjustment(
                    document=document, reference=movement.reference,
                    movement=movement, warehouse=movement.warehouse,
                    payable_party=purchase_return.supplier,
                    inventory_delta=delta, payable_delta=payable_delta,
                    posting_day=day, actor=actor,
                )
                purchase_return_delta += payable_delta
                cogs_delta += delta - payable_delta
            elif movement.movement_type == MovementType.SALES_RETURN:
                _inventory_return, sales_return, _purchase_return = _movement_return_context(movement)
                if sales_return is None:
                    raise LandedCostPostingError(
                        f"Sales return {movement.reference} has no posted commercial return."
                    )
                _post_adjustment(
                    document=document, adjustment_type="SALES_RETURN",
                    reference=movement.reference, movement=movement,
                    debit_account=resolve_warehouse_account(movement.warehouse),
                    credit_account=_account(COGS_ACCOUNT),
                    amount=delta, posting_day=day, actor=actor,
                )
                cogs_delta -= delta

        # Ending stock delta is measured from the same AVCO replay, not by
        # multiplying the current quantity by a stale source unit cost.
        for warehouse_id, pair in revised_state.items():
            before = base_state.get(warehouse_id, [0, Decimal("0")])
            inventory_delta += _q2(pair[1] - before[1])

    # Current landed cost sold directly from Transit is a COGS delta even
    # though no company StockMovement exists for the sale.
    transit_sale_delta = sum(
        (_q2(_q4(row.afn_amount / Decimal(transit_lots[row.purchase_line_id].original_quantity))
             * Decimal(allocation.quantity))
         for row in allocations if row.purchase_line_id in transit_lots
         for allocation in TransitSaleAllocation.objects.filter(transit_lot=transit_lots[row.purchase_line_id])),
        Decimal("0.00"),
    )
    cogs_delta += transit_sale_delta
    transit_remaining_delta = sum(
        (_q2(_q4(row.afn_amount / Decimal(transit_lots[row.purchase_line_id].original_quantity))
             * Decimal(transit_lots[row.purchase_line_id].remaining_quantity))
         for row in allocations if row.purchase_line_id in transit_lots),
        Decimal("0.00"),
    )
    # Every allocated AFN must reconcile to current assets, COGS, and supplier
    # claims. Cent-level residuals are posted as a visible rounding adjustment.
    distributed = _q2(inventory_delta + transit_remaining_delta + cogs_delta + purchase_return_delta)
    residual = _q2(document.afn_amount - distributed)
    if residual:
        asset_account = None
        for line in lines:
            if line.pk in transit_lots and transit_lots[line.pk].remaining_quantity > 0:
                asset_account = _account(TRANSIT_ACCOUNT)
                break
            current_qty = sum(
                (pair[0] for pair in product_results[line.product_id][4].values()),
                0,
            )
            if current_qty > 0:
                asset_account = resolve_warehouse_account(line.purchase.warehouse)
                break
        if asset_account is None:
            asset_account = _account(TRANSIT_ACCOUNT) if transit_lots else resolve_warehouse_account(lines[0].purchase.warehouse)
        # Positive residual means the source invoice left a cent-level asset
        # remainder not represented by 4dp unit costs: move it into COGS.
        _post_adjustment(
            document=document, adjustment_type="ROUNDING_RESIDUAL",
            reference=f"{document.document_number}:ROUNDING",
            movement=None,
            debit_account=_account(COGS_ACCOUNT) if residual > 0 else asset_account,
            credit_account=asset_account if residual > 0 else _account(COGS_ACCOUNT),
            amount=residual, posting_day=day, actor=actor,
        )

    record_audit_event(
        user=actor, action=AuditAction.POST, entity="LandedCostDocument",
        entity_id=document.pk, reference=document.document_number,
        previous_state={"status": LandedCostStatus.DRAFT},
        new_state={
            "status": LandedCostStatus.POSTED,
            "journal_entry_id": journal.pk,
            "adjustment_ids": list(document.valuation_adjustments.order_by("id").values_list("pk", flat=True)),
            "afn_amount": str(document.afn_amount),
            "valuation_adjustment_count": document.valuation_adjustments.count(),
        },
        reason="",
    )
    return document



def effective_avco_for_product_warehouse(product, warehouse):
    """Return (has_posted_landed_cost, effective_AVCO) for existing cost layers.

    This is the read-side counterpart of posting: it replays the exact same
    stock history with posted landed-cost layers included, while never editing
    StockMovement snapshots. When no landed costs exist, the caller should use
    the original lightweight AVCO implementation.
    """
    product_id = getattr(product, "pk", product)
    warehouse_id = getattr(warehouse, "pk", warehouse)
    allocations = list(LandedCostAllocation.objects.filter(
        purchase_line__product_id=product_id,
        cost_document__status=LandedCostStatus.POSTED,
        cost_document__reversal__isnull=True,
    ).select_related("purchase_line", "purchase_line__purchase").order_by(
        "cost_document__cost_date", "id"
    ))
    if not allocations:
        return False, None
    line_ids = sorted({row.purchase_line_id for row in allocations})
    lines = list(PurchaseLine.objects.filter(pk__in=line_ids).select_related(
        "purchase", "purchase__warehouse", "product"
    ))
    line_map = {line.pk: line for line in lines}
    allocations = [row for row in allocations if row.purchase_line_id in line_map]
    extra = _extra_cost_map(lines, allocations, lock=False)
    dates = []
    from .models import PurchaseDeliveryMode
    for line in lines:
        if line.purchase.delivery_mode == PurchaseDeliveryMode.IN_TRANSIT:
            lot = _lot_for_read(line)
            dates.append(lot.ownership_date)
        else:
            movement = _source_movement(line, lock=False)
            dates.append(movement.movement_date)
    if not dates:
        return True, None
    movements, _baseline, revised, _before, final_state, _pairs = _simulate_product(
        product_id, extra, extra, min(dates), strict=False
    )
    quantity, basis = final_state.get(warehouse_id, [0, Decimal("0")])
    if quantity <= 0:
        return True, None
    return True, _q4(basis / Decimal(quantity))


def _lot_for_read(line):
    from goods_in_transit.models import GoodsInTransitLot
    return GoodsInTransitLot.objects.get(purchase_line=line)


@transaction.atomic
def post_transit_receipt_landed_cost_adjustments(*, lot, receipt, user=None):
    """Reclass already-posted landed costs when Transit goods arrive later."""
    if not receipt.company_quantity or receipt.stock_movement_id is None:
        return []
    from sales.models import NegativeCOGSReceiptAllocation

    created = []
    links = list(NegativeCOGSReceiptAllocation.objects.filter(
        receipt_movement_id=receipt.stock_movement_id
    ).select_related("obligation", "obligation__movement").order_by("id"))
    consumed_quantity = sum(link.quantity for link in links)
    if consumed_quantity > receipt.company_quantity:
        raise LandedCostPostingError(
            f"Transit receipt {receipt.stock_movement.reference} resolves more negative stock than its company quantity."
        )
    remaining_company_quantity = receipt.company_quantity - consumed_quantity
    for allocation in LandedCostAllocation.objects.filter(
        purchase_line_id=lot.purchase_line_id,
        cost_document__status=LandedCostStatus.POSTED,
        cost_document__reversal__isnull=True,
    ).select_related("cost_document").order_by("cost_document__cost_date", "id"):
        per_unit = _q4(allocation.afn_amount / Decimal(lot.original_quantity))
        amount = _q2(per_unit * Decimal(remaining_company_quantity))
        if amount:
            row = _post_adjustment(
                document=allocation.cost_document,
                adjustment_type="TRANSIT_RECEIPT",
                reference=receipt.stock_movement.reference,
                movement=receipt.stock_movement,
                debit_account=resolve_warehouse_account(receipt.warehouse),
                credit_account=_account(TRANSIT_ACCOUNT),
                amount=amount, posting_day=receipt.receipt_date, actor=user,
            )
            if row is not None:
                created.append(row)
        for link in links:
            negative_amount = _q2(per_unit * Decimal(link.quantity))
            if not negative_amount:
                continue
            reference = f"{link.obligation.movement.reference}:NEGATIVE-RECEIPT:{receipt.stock_movement_id}"
            row = _post_adjustment(
                document=allocation.cost_document,
                adjustment_type="NEGATIVE_COGS_OBLIGATION",
                reference=reference,
                movement=link.obligation.movement,
                debit_account=_account(COGS_ACCOUNT),
                credit_account=_account(TRANSIT_ACCOUNT),
                amount=negative_amount, posting_day=receipt.receipt_date, actor=user,
            )
            if row is not None:
                created.append(row)
    return created


@transaction.atomic
def post_transit_sale_landed_cost_adjustments(*, lot, sale_allocation, posting_date, user=None):
    """Recognize posted landed costs in COGS for a later Transit sale."""
    created = []
    for allocation in LandedCostAllocation.objects.filter(
        purchase_line_id=lot.purchase_line_id,
        cost_document__status=LandedCostStatus.POSTED,
        cost_document__reversal__isnull=True,
    ).select_related("cost_document").order_by("cost_document__cost_date", "id"):
        per_unit = _q4(allocation.afn_amount / Decimal(lot.original_quantity))
        amount = _q2(per_unit * Decimal(sale_allocation.quantity))
        if not amount:
            continue
        row = _post_adjustment(
            document=allocation.cost_document,
            adjustment_type="TRANSIT_SALE",
            reference=f"TRANSIT-SALE:{sale_allocation.sale_line_id}",
            movement=None,
            debit_account=_account(COGS_ACCOUNT),
            credit_account=_account(TRANSIT_ACCOUNT),
            amount=amount, posting_day=posting_date, actor=user,
        )
        if row is not None:
            created.append(row)
    return created


@transaction.atomic
def post_transit_sales_return_landed_cost_adjustments(*, lot, sales_return, user=None):
    """Reverse the landed-cost COGS portion when Transit-sold goods are returned."""
    from goods_in_transit.models import GoodsInTransitLot
    lot = GoodsInTransitLot.objects.select_for_update().get(pk=lot.pk)
    movement = sales_return.return_movement
    if movement is None:
        return []
    created = []
    for allocation in LandedCostAllocation.objects.filter(
        purchase_line_id=lot.purchase_line_id,
        cost_document__status=LandedCostStatus.POSTED,
        cost_document__reversal__isnull=True,
    ).select_related("cost_document").order_by("cost_document__cost_date", "id"):
        per_unit = _q4(allocation.afn_amount / Decimal(lot.original_quantity))
        amount = _q2(per_unit * Decimal(sales_return.quantity))
        if not amount:
            continue
        row = _post_adjustment(
            document=allocation.cost_document,
            adjustment_type="SALES_RETURN",
            reference=movement.reference,
            movement=movement,
            debit_account=resolve_warehouse_account(sales_return.warehouse),
            credit_account=_account(COGS_ACCOUNT),
            amount=amount, posting_day=sales_return.return_date, actor=user,
        )
        if row is not None:
            created.append(row)
    return created
