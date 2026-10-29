from datetime import date
import hashlib
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from accounting.models import Account
from accounting.services import post_journal
from core.money import cogs as cogs_amount, line_total, quantize_half_up, normalize_rate
from fiscal_periods.services import assert_posting_date_open
from inventory.models import InventoryReturn, StockMovement
from inventory.services import issue_stock, resolve_warehouse_account
from customer_custody.models import CustomerCustodyEvent, CustomerOwnershipEntitlement
from customer_custody.services import create_ownership_entitlement, custody_balance, place_customer_custody, release_customer_custody, reverse_customer_custody_event, unallocated_custody_balance
from party_ledger.services import attribute_journal_line
from parties.services import resolve_party
from products.services import resolve_product
from uom.models import UnitOfMeasure
from warehouses.services import resolve_warehouse
from security.models import AuditAction
from security.services import record_audit_event

from .models import (
    COGSAdjustment, CheckStatus, NegativeCOGSObligation,
    NegativeCOGSReceiptAllocation,
    PaymentMode, Sale, SaleLine, SaleLineWarehouseAllocation, SaleStatus,
    SalesChannel, SaleType, WarehouseCheck, WarehouseCheckReversal,
)


REVENUE_ACCOUNTS = {SalesChannel.WHOLESALE: "4110", SalesChannel.RETAIL: "4120"}
CASH_ACCOUNT = "1110"
RECEIVABLE_ACCOUNT = "1310"
COGS_ACCOUNT = "5100"


class SalesValidationError(ValueError):
    pass


def _date(value):
    if isinstance(value, date):
        return value
    raise SalesValidationError("A date is required")


def _actor(user):
    if user is not None and not getattr(user, "is_authenticated", False):
        raise SalesValidationError("Authenticated user required")
    return user


def _currency(ref):
    from currencies.models import Currency
    if isinstance(ref, Currency) and ref.pk:
        return ref
    found = Currency.objects.filter(code=ref).first()
    if not found or not found.is_active:
        raise SalesValidationError("Currency does not exist or is inactive")
    return found


def _rate(currency, value, rate_date, sale_date):
    if currency.is_base:
        if value is not None and normalize_rate(value) != Decimal("1.0000"):
            raise SalesValidationError("Base currency rate must be 1.0000")
        return Decimal("1.0000"), sale_date
    if value is None and rate_date is None:
        return None, None
    if value is None or rate_date is None:
        raise SalesValidationError("rate and rate_date must be supplied together")
    return normalize_rate(value), _date(rate_date)


def _customer(ref):
    party = resolve_party(ref)
    if not party.is_customer or not party.is_active:
        raise SalesValidationError("Active customer Party required")
    return party


def _line_rows(lines):
    rows = []
    from goods_in_transit.models import GoodsInTransitLot
    for row in lines:
        try:
            product = resolve_product(row["product"])
            unit = row["unit"] if isinstance(row["unit"], UnitOfMeasure) else UnitOfMeasure.objects.get(pk=row["unit"])
            warehouse = row.get("warehouse")
            transit_lot_ref = row.get("transit_lot")
            transit_lot = None
            if transit_lot_ref is not None:
                transit_lot = (
                    transit_lot_ref if isinstance(transit_lot_ref, GoodsInTransitLot)
                    else GoodsInTransitLot.objects.select_related("product").get(pk=transit_lot_ref)
                )
        except (KeyError, UnitOfMeasure.DoesNotExist, GoodsInTransitLot.DoesNotExist) as exc:
            raise SalesValidationError("Product and UOM are required") from exc
        allocations = []
        raw_allocations = row.get("allocations")
        if raw_allocations is None and warehouse is not None:
            raw_allocations = [{"warehouse": warehouse, "quantity": row.get("quantity")}]
        if raw_allocations is not None:
            if transit_lot_ref is not None:
                raise SalesValidationError("Transit SaleLines use a Transit lot, not warehouse allocations")
            if not isinstance(raw_allocations, (list, tuple)) or not raw_allocations:
                raise SalesValidationError("Warehouse allocations must be a non-empty list")
            seen_warehouses = set()
            for alloc in raw_allocations:
                try:
                    alloc_warehouse = resolve_warehouse(alloc["warehouse"])
                    alloc_qty = alloc["quantity"]
                except (KeyError, TypeError, AttributeError) as exc:
                    raise SalesValidationError("Each allocation requires a warehouse and quantity") from exc
                if not alloc_warehouse.is_active:
                    raise SalesValidationError("Warehouse is inactive")
                if isinstance(alloc_qty, bool) or not isinstance(alloc_qty, int) or alloc_qty <= 0:
                    raise SalesValidationError("Allocation quantity must be a positive integer")
                if alloc_warehouse.pk in seen_warehouses:
                    raise SalesValidationError("Duplicate warehouse in SaleLine allocations")
                seen_warehouses.add(alloc_warehouse.pk)
                allocations.append({"warehouse": alloc_warehouse, "quantity": alloc_qty})
        if transit_lot is not None and transit_lot.product_id != product.pk:
            raise SalesValidationError("Transit lot product must match SaleLine product")
        quantity = row.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise SalesValidationError("Quantity must be a positive integer")
        price = quantize_half_up(row.get("unit_price"), 4)
        discount = quantize_half_up(row.get("discount", 0), 2)
        gross = line_total(quantity, price)
        if discount < 0 or discount > gross:
            raise SalesValidationError("Invalid discount")
        if allocations and sum(a["quantity"] for a in allocations) != quantity:
            raise SalesValidationError("Warehouse allocations must sum to the SaleLine quantity")
        rows.append({"product": product, "unit": unit, "quantity": quantity,
                     "unit_price": price, "discount": discount,
                     "gross": gross, "net": gross - discount,
                     "transit_lot": transit_lot, "allocations": allocations})
    if not rows:
        raise SalesValidationError("At least one Sales Line is required")
    return rows


def create_sale(*, customer, sale_date, currency, channel, payment_mode,
                lines, sale_type=SaleType.AVAILABLE, rate=None, rate_date=None,
                user=None, document_number=None):
    actor = _actor(user)
    customer = _customer(customer)
    sale_day = _date(sale_date)
    currency = _currency(currency)
    try:
        channel = SalesChannel(channel)
        payment_mode = PaymentMode(payment_mode)
        sale_type = SaleType(sale_type)
    except ValueError as exc:
        raise SalesValidationError("Invalid channel, payment mode, or sale type") from exc
    rate_value, rate_day = _rate(currency, rate, rate_date, sale_day)
    rows = _line_rows(lines)
    if sale_type == SaleType.FUTURE and any(row["transit_lot"] is not None for row in rows):
        raise SalesValidationError("A Future sale cannot consume company-owned Transit goods.")
    if not document_number:
        from documents.services import next_document_number
        from core.dates import gregorian_to_jalali
        document_number = next_document_number("SI", int(gregorian_to_jalali(sale_day).split("/")[0]))
    with transaction.atomic():
        sale = Sale.objects.create(
            document_number=document_number, customer=customer, sale_date=sale_day,
            currency=currency, exchange_rate=rate_value, rate_date=rate_day,
            sale_type=sale_type, channel=channel, payment_mode=payment_mode,
            subtotal=sum((r["gross"] for r in rows), Decimal("0.00")),
            total_discount=sum((r["discount"] for r in rows), Decimal("0.00")),
            total=sum((r["net"] for r in rows), Decimal("0.00")), created_by=actor,
        )
        for row in rows:
            line = SaleLine.objects.create(sale=sale, product=row["product"], unit=row["unit"],
                                    quantity=row["quantity"], unit_price=row["unit_price"],
                                    discount=row["discount"], line_total=row["gross"], net_total=row["net"],
                                    transit_lot=row["transit_lot"])
            for alloc in row["allocations"]:
                SaleLineWarehouseAllocation.objects.create(
                    sale_line=line, warehouse=alloc["warehouse"],
                    quantity=alloc["quantity"],
                    idempotency_key=f"sale-line-intent:{line.pk}:{alloc['warehouse'].pk}",
                )
    return sale


def finalize_sale(*, sale, user=None, idempotency_key=None, allocations=None,
                  acknowledge_negative=False, temporary_unit_cost=None,
                  temporary_currency=None, temporary_rate=None,
                  temporary_rate_date=None):
    """Finalize a Sale: revenue, invoice-time COGS for ordinary stock, ownership.

    Ordinary AVAILABLE (non-Transit) lines require explicit warehouse
    allocations (recorded at create_sale, or supplied here keyed by SaleLine
    pk). Each allocation issues stock at that warehouse's AVCO (existing
    negative-stock acknowledgement/temporary-cost policy applies) and posts
    Dr 5100 / Cr <warehouse inventory account> exactly once. Transit lines
    keep their lot-specific COGS against 1430. Warehouse Check later only
    releases customer custody.
    """
    actor = _actor(user)
    with transaction.atomic():
        sale = Sale.objects.select_for_update().select_related("customer", "currency").get(pk=getattr(sale, "pk", sale))
        if sale.status == SaleStatus.FINALIZED:
            return sale
        if sale.status != SaleStatus.DRAFT:
            raise SalesValidationError("Only draft Sales can be finalized")
        assert_posting_date_open(sale.sale_date)
        revenue = Account.objects.get(code=REVENUE_ACCOUNTS[sale.channel])
        debit = Account.objects.get(code=CASH_ACCOUNT if sale.payment_mode == PaymentMode.CASH else RECEIVABLE_ACCOUNT)
        journal = post_journal(
            number=f"JE-{sale.document_number}", posting_date=sale.sale_date,
            description=f"Sales invoice {sale.document_number}",
            lines=[{"account": debit, "debit": sale.total, "reference": sale.document_number},
                   {"account": revenue, "credit": sale.total, "reference": sale.document_number}],
            source_type="SALE", source_id=sale.document_number, currency=sale.currency,
            rate=sale.exchange_rate, rate_date=sale.rate_date, created_by=actor,
            idempotency_key=idempotency_key or f"sale:{sale.pk}:journal",
            allow_unvalued_foreign=(not sale.currency.is_base and sale.exchange_rate is None),
        )
        if sale.payment_mode == PaymentMode.CREDIT:
            attribute_journal_line(journal.lines.get(account__code=RECEIVABLE_ACCOUNT), party=sale.customer, user=actor)

        from goods_in_transit.models import GoodsInTransitLot, TransitLotStatus, has_unvalued_transit_loss
        transit_lines = list(
            SaleLine.objects.select_for_update().filter(
                sale_id=sale.pk, transit_lot__isnull=False
            ).order_by("id")
        )
        from .models import TransitSaleAllocation
        for line in transit_lines:
            lot = GoodsInTransitLot.objects.select_for_update(of=("self",)).get(pk=line.transit_lot_id)
            if lot.status != TransitLotStatus.OPEN:
                raise SalesValidationError("Transit lot is not open.")
            if has_unvalued_transit_loss(lot.pk):
                raise SalesValidationError(
                    "Transit sale is blocked because this lot has confirmed loss without "
                    "a posted purchase-wide loss valuation replay."
                )
            if sale.sale_date < lot.ownership_date:
                raise SalesValidationError("Sale date cannot precede Transit ownership date.")
            if line.quantity > lot.remaining_quantity:
                raise SalesValidationError("Sale exceeds remaining Transit quantity.")
            if line.product_id != lot.product_id:
                raise SalesValidationError("Transit lot product does not match SaleLine.")
            cogs_value = quantize_half_up(Decimal(line.quantity) * lot.unit_cost, 2)
            cogs_journal = post_journal(
                number=f"JE-TCOGS-{hashlib.sha256(f'{sale.pk}:{line.pk}'.encode()).hexdigest()[:20]}",
                posting_date=sale.sale_date,
                description=f"COGS for Transit Sale {sale.document_number} line {line.pk}",
                lines=[
                    {"account": Account.objects.get(code=COGS_ACCOUNT), "debit": cogs_value, "reference": sale.document_number},
                    {"account": Account.objects.get(code="1430"), "credit": cogs_value, "reference": sale.document_number},
                ],
                source_type="SALES_COGS_TRANSIT",
                source_id=f"{sale.document_number}:LINE:{line.pk}",
                currency=lot.currency,
                rate=lot.rate,
                rate_date=lot.rate_date,
                created_by=actor,
                idempotency_key=f"sale:{sale.pk}:transit-cogs:{line.pk}",
            )
            remaining = lot.remaining_quantity - line.quantity
            lot.remaining_quantity = remaining
                        # A finalized Transit Sale transfers ownership, but does not mean
            # the sold goods have physically arrived. Keep the lot open until
            # receipts account for both remaining company-owned goods and sold
            # customer-owned goods still in transit.
            lot.status = TransitLotStatus.OPEN
            lot.save(allow_state_transition=True, update_fields={"remaining_quantity", "status"})
            transit_allocation = TransitSaleAllocation.objects.create(
                sale_line=line, transit_lot=lot, quantity=line.quantity,
                unit_cost=lot.unit_cost, cogs_journal=cogs_journal,
                idempotency_key=f"sale:{sale.pk}:transit-allocation:{line.pk}",
            )
            # If a late landed-cost invoice was already posted, recognize this
            # newly sold Transit quantity in COGS now (the earlier post could
            # only adjust Transit sales that already existed at that time).
            from purchases.landed_cost_posting import post_transit_sale_landed_cost_adjustments
            post_transit_sale_landed_cost_adjustments(
                lot=lot, sale_allocation=transit_allocation,
                posting_date=sale.sale_date, user=actor,
            )
        # Ordinary warehouse-stock lines: issue + COGS now, at invoice time.
        ordinary_allocations = []  # (line, allocation)
        if sale.sale_type == SaleType.AVAILABLE:
            supplied = allocations or {}
            for line in SaleLine.objects.select_for_update().filter(
                sale_id=sale.pk, transit_lot__isnull=True
            ).order_by("id"):
                intents = list(
                    SaleLineWarehouseAllocation.objects.select_for_update()
                    .filter(sale_line=line).order_by("warehouse_id")
                )
                if not intents:
                    rows = supplied.get(line.pk) or supplied.get(str(line.pk)) or []
                    for alloc in rows:
                        alloc_warehouse = resolve_warehouse(alloc["warehouse"])
                        if not alloc_warehouse.is_active:
                            raise SalesValidationError("Warehouse is inactive")
                        alloc_qty = alloc["quantity"]
                        if isinstance(alloc_qty, bool) or not isinstance(alloc_qty, int) or alloc_qty <= 0:
                            raise SalesValidationError("Allocation quantity must be a positive integer")
                        intents.append(SaleLineWarehouseAllocation.objects.create(
                            sale_line=line, warehouse=alloc_warehouse, quantity=alloc_qty,
                            idempotency_key=f"sale-line-intent:{line.pk}:{alloc_warehouse.pk}",
                        ))
                if not intents:
                    raise SalesValidationError(
                        "Every ordinary SaleLine requires an explicit warehouse allocation before finalization"
                    )
                if sum(a.quantity for a in intents) != line.quantity:
                    raise SalesValidationError("Warehouse allocations must sum to the SaleLine quantity")
                for alloc in intents:
                    if alloc.stock_movement_id is not None:
                        raise SalesValidationError("SaleLine allocation was already issued")
                    inv_account = resolve_warehouse_account(alloc.warehouse)
                    movement = issue_stock(
                        product=line.product, warehouse=alloc.warehouse,
                        quantity=alloc.quantity, movement_date=sale.sale_date,
                        reference=sale.document_number,
                        description=f"Sales invoice {sale.document_number} line {line.pk}",
                        user=actor,
                        idempotency_key=f"sale:{sale.pk}:line:{line.pk}:alloc:{alloc.warehouse_id}:issue",
                        acknowledge_negative=acknowledge_negative,
                        temporary_unit_cost=temporary_unit_cost,
                        temporary_currency=temporary_currency,
                        temporary_rate=temporary_rate,
                        temporary_rate_date=temporary_rate_date,
                        party=sale.customer,
                    )
                    cogs_value = cogs_amount(alloc.quantity, movement.unit_cost_afn)
                    base = movement.currency if movement.currency.is_base else __import__("currencies.models", fromlist=["Currency"]).Currency.objects.get(is_base=True)
                    cogs_entry = post_journal(
                        number=f"JE-COGS-{hashlib.sha256(f'{sale.pk}:{line.pk}:{alloc.warehouse_id}'.encode()).hexdigest()[:20]}",
                        posting_date=sale.sale_date,
                        description=f"COGS for Sales invoice {sale.document_number} line {line.pk}",
                        lines=[{"account": Account.objects.get(code=COGS_ACCOUNT), "debit": cogs_value, "reference": sale.document_number},
                               {"account": inv_account, "credit": cogs_value, "reference": sale.document_number}],
                        source_type="SALES_COGS",
                        source_id=f"{sale.document_number}:LINE:{line.pk}:WH:{alloc.warehouse_id}",
                        currency=base, rate=Decimal("1.0000"), rate_date=sale.sale_date,
                        created_by=actor,
                        idempotency_key=f"sale:{sale.pk}:line:{line.pk}:alloc:{alloc.warehouse_id}:cogs",
                    )
                    SaleLineWarehouseAllocation.objects.filter(pk=alloc.pk).update(
                        unit_cost_afn=movement.unit_cost_afn,
                        inventory_account=inv_account,
                        stock_movement=movement, cogs_journal=cogs_entry,
                    )
                    alloc.unit_cost_afn = movement.unit_cost_afn
                    if movement.is_temporary_cost:
                        NegativeCOGSObligation.objects.create(
                            movement=movement, sale_allocation=alloc,
                            product=line.product, warehouse=alloc.warehouse,
                            original_quantity=alloc.quantity,
                            temporary_unit_cost_afn=movement.unit_cost_afn,
                            movement_date=sale.sale_date,
                        )
                    ordinary_allocations.append((line, alloc))
        sale.status = SaleStatus.FINALIZED
        sale.finalized_at = timezone.now()
        sale.journal_entry = journal
        sale.save(update_fields=["status", "finalized_at", "journal_entry"])
        if sale.sale_type == SaleType.AVAILABLE:
            for line in SaleLine.objects.filter(sale=sale).order_by("id"):
                entitlement = create_ownership_entitlement(
                    sale_line=line,
                    user=actor,
                    idempotency_key=f"sale:{sale.pk}:line:{line.pk}:ownership",
                )
    return sale


def remaining_quantity(line):
    line_id = getattr(line, "pk", line)
    line = SaleLine.objects.get(pk=line_id)
    used = line.warehouse_checks.filter(status=CheckStatus.FINALIZED, reversal__isnull=True).aggregate(total=models.Sum("quantity"))["total"] or 0
    return line.quantity - used


def prepare_warehouse_check(*, sale_line, warehouse, quantity=None, number=None):
    line = SaleLine.objects.select_related("sale", "product", "unit").get(pk=getattr(sale_line, "pk", sale_line))
    warehouse = resolve_warehouse(warehouse)
    if not warehouse.is_active:
        raise SalesValidationError("Warehouse is inactive")
    if line.sale.status != SaleStatus.FINALIZED:
        raise SalesValidationError("Sale must be finalized before a Warehouse Check")
    remaining = remaining_quantity(line)
    if quantity is None:
        quantity = remaining
    if not isinstance(quantity, int) or quantity <= 0 or quantity > remaining:
        raise SalesValidationError("Check quantity exceeds the remaining Invoice Line quantity")
    if not number:
        number = f"WC-{line.sale.document_number}-{line.pk}-{line.warehouse_checks.count()+1}"
    return WarehouseCheck.objects.create(number=number, sale=line.sale, sale_line=line,
                                         warehouse=warehouse, quantity=quantity)


def finalize_warehouse_check(*, check, user=None, acknowledge_negative=False,
                             temporary_unit_cost=None, temporary_currency=None,
                             temporary_rate=None, temporary_rate_date=None,
                             idempotency_key=None):
    actor = _actor(user)
    with transaction.atomic():
        check = WarehouseCheck.objects.select_for_update().select_related(
            "sale", "sale_line__product", "sale_line__unit", "sale__customer"
        ).get(pk=getattr(check, "pk", check))
        if WarehouseCheckReversal.objects.filter(warehouse_check=check).exists():
            raise SalesValidationError("A reversed Warehouse Check cannot be finalized again")
        if check.status == CheckStatus.FINALIZED:
            return check
        line = SaleLine.objects.select_for_update().get(pk=check.sale_line_id)
        if check.sale_id != line.sale_id:
            raise SalesValidationError("Warehouse Check must belong to its Sales Invoice Line")
        used = WarehouseCheck.objects.filter(sale_line=line, status=CheckStatus.FINALIZED, reversal__isnull=True).aggregate(total=models.Sum("quantity"))["total"] or 0
        if check.quantity > line.quantity - used:
            raise SalesValidationError("Warehouse Check exceeds remaining Invoice Line quantity")
        assert_posting_date_open(check.sale.sale_date)
        # A Warehouse Check releases customer-owned goods from custody, so it
        # is valid only when this SaleLine's customer ownership entitlement
        # exists: created at AVAILABLE sale finalization, or only after
        # actual fulfillment for FUTURE sales (approved Type B ownership
        # trigger). Without ownership there is nothing customer-owned to
        # receive into custody or release, and the check must not proceed.
        entitlement = CustomerOwnershipEntitlement.objects.filter(sale_line=line).first()
        if entitlement is None:
            raise SalesValidationError(
                "Warehouse Check finalization requires a customer ownership entitlement "
                "for the invoice line; none exists. Customer ownership is established "
                "at AVAILABLE sale finalization, or after actual fulfillment for "
                "FUTURE sales."
            )
        from sales.models import TransitSaleAllocation
        if TransitSaleAllocation.objects.filter(sale_line=line).exists():
            # Transit-sale COGS was posted against 1430 at Sale finalization.
            # A Warehouse Check only releases physical customer custody.
            from goods_in_transit.models import TransitCustomerCustody
            from django.db.models import Sum
            legacy_total = TransitCustomerCustody.objects.filter(
                sale_line=line, warehouse=check.warehouse
            ).aggregate(total=Sum("quantity"))["total"] or 0
            previously_released = WarehouseCheck.objects.filter(
                sale_line=line, warehouse=check.warehouse,
                status=CheckStatus.FINALIZED, reversal__isnull=True,
            ).aggregate(total=Sum("quantity"))["total"] or 0
            legacy_outstanding = max(0, int(legacy_total) - int(previously_released))
            legacy_key = f"legacy-transit-custody:{line.pk}:{check.warehouse_id}"
            if legacy_outstanding and not CustomerCustodyEvent.objects.filter(
                idempotency_key=legacy_key
            ).exists():
                place_customer_custody(
                    entitlement=entitlement, warehouse=check.warehouse,
                    quantity=legacy_outstanding, event_date=check.sale.sale_date,
                    reference=f"LEGACY-TRANSIT:{line.pk}:{check.warehouse_id}",
                    user=actor, idempotency_key=legacy_key,
                )
            if custody_balance(entitlement=entitlement, warehouse=check.warehouse) < check.quantity:
                raise SalesValidationError(
                    "Warehouse Check exceeds customer-owned Transit quantity physically received into this warehouse"
                )
            release_customer_custody(
                entitlement=entitlement, warehouse=check.warehouse,
                quantity=check.quantity, event_date=check.sale.sale_date,
                reference=check.number, user=actor,
                idempotency_key=idempotency_key or f"warehouse-check:{check.pk}:custody-release",
            )
            check.status = CheckStatus.FINALIZED
            check.finalized_at = timezone.now()
            check.save(update_fields=["status", "finalized_at"])
            return check

        if SaleLineWarehouseAllocation.objects.filter(sale_line=line).exists():
            # Invoice-time COGS already issued this stock and credited the
            # warehouse inventory account. Physical check only releases the
            # customer custody placed at finalization; no stock/COGS again.
            allocated_here = SaleLineWarehouseAllocation.objects.filter(
                sale_line=line, warehouse=check.warehouse
            ).aggregate(total=models.Sum("quantity"))["total"] or 0
            released_here = WarehouseCheck.objects.filter(
                sale_line=line, warehouse=check.warehouse,
                status=CheckStatus.FINALIZED, reversal__isnull=True,
            ).aggregate(total=models.Sum("quantity"))["total"] or 0
            if check.quantity > allocated_here - released_here:
                raise SalesValidationError(
                    "Warehouse Check exceeds the quantity allocated to this warehouse at invoice finalization"
                )
            available_here = custody_balance(entitlement=entitlement, warehouse=check.warehouse)
            if available_here < check.quantity:
                needed = check.quantity - available_here
                if needed > unallocated_custody_balance(entitlement=entitlement):
                    raise SalesValidationError(
                        "Warehouse Check exceeds customer-owned custody allocated to this warehouse"
                    )
                place_customer_custody(
                    entitlement=entitlement, warehouse=check.warehouse,
                    quantity=needed, event_date=check.sale.sale_date,
                    reference=check.number, user=actor,
                    idempotency_key=idempotency_key or f"warehouse-check:{check.pk}:custody-place",
                )
            release_customer_custody(
                entitlement=entitlement, warehouse=check.warehouse,
                quantity=check.quantity, event_date=check.sale.sale_date,
                reference=check.number, user=actor,
                idempotency_key=idempotency_key or f"warehouse-check:{check.pk}:custody-release",
            )
            check.status = CheckStatus.FINALIZED
            check.finalized_at = timezone.now()
            check.save(update_fields=["status", "finalized_at"])
            return check

        movement_holder = {}
        def _issue_customer_owned_stock(*, quantity, warehouse, entitlement):
            movement_holder["movement"] = issue_stock(
                product=line.product, warehouse=warehouse, quantity=quantity,
                movement_date=check.sale.sale_date, reference=check.number,
                description=f"Warehouse Check {check.number}", user=actor,
                idempotency_key=idempotency_key or f"warehouse-check:{check.pk}:issue",
                acknowledge_negative=acknowledge_negative, temporary_unit_cost=temporary_unit_cost,
                temporary_currency=temporary_currency, temporary_rate=temporary_rate,
                temporary_rate_date=temporary_rate_date, party=check.sale.customer,
            )
        available_here = custody_balance(entitlement=entitlement, warehouse=check.warehouse)
        if available_here < check.quantity:
            unallocated = unallocated_custody_balance(entitlement=entitlement)
            needed = check.quantity - available_here
            if needed > unallocated:
                raise SalesValidationError("Warehouse Check exceeds customer custody available for this warehouse")
            place_customer_custody(
                entitlement=entitlement, warehouse=check.warehouse, quantity=needed,
                event_date=check.sale.sale_date, reference=check.number, user=actor,
                idempotency_key=idempotency_key or f"warehouse-check:{check.pk}:custody-place",
            )
        release_event = release_customer_custody(
            entitlement=entitlement, warehouse=check.warehouse, quantity=check.quantity,
            event_date=check.sale.sale_date, reference=check.number, user=actor,
            idempotency_key=idempotency_key or f"warehouse-check:{check.pk}:custody-release",
            stock_issue=_issue_customer_owned_stock,
        )
        movement = movement_holder.get("movement")
        if movement is None:
            raise SalesValidationError("Customer custody release did not create the required stock issue")
        base = movement.currency if movement.currency.is_base else __import__("currencies.models", fromlist=["Currency"]).Currency.objects.get(is_base=True)
        inv_account = resolve_warehouse_account(check.warehouse)
        cogs_value = cogs_amount(check.quantity, movement.unit_cost_afn)
        cogs_entry = post_journal(
            number=f"JE-COGS-{check.number}", posting_date=check.sale.sale_date,
            description=f"COGS for Warehouse Check {check.number}",
            lines=[{"account": Account.objects.get(code=COGS_ACCOUNT), "debit": cogs_value, "reference": check.number},
                   {"account": inv_account, "credit": cogs_value, "reference": check.number}],
            source_type="SALES_COGS", source_id=check.number, currency=base,
            rate=Decimal("1.0000"), rate_date=check.sale.sale_date, created_by=actor,
            idempotency_key=idempotency_key or f"warehouse-check:{check.pk}:cogs",
        )
        check.stock_movement = movement
        check.cogs_journal = cogs_entry
        check.status = CheckStatus.FINALIZED
        check.finalized_at = timezone.now()
        check.save(update_fields=["stock_movement", "cogs_journal", "status", "finalized_at"])
        if movement.is_temporary_cost:
            NegativeCOGSObligation.objects.create(
                movement=movement, warehouse_check=check, product=line.product,
                warehouse=check.warehouse, original_quantity=check.quantity,
                temporary_unit_cost_afn=movement.unit_cost_afn, movement_date=check.sale.sale_date,
            )
    return check



def cancel_warehouse_check(*, check, reversal_date, reason, user=None,
                           idempotency_key=None, confirm_not_delivered=False):
    """Cancel a finalized check only when the caller confirms no physical delivery.

    The original Warehouse Check, sale, ownership, revenue, stock movement,
    and COGS remain unchanged. Only the customer-custody release is reversed,
    restoring the goods to customer-owned custody. Delivered goods must use Sales Return.
    """
    actor = _actor(user)
    day = _date(reversal_date)
    if confirm_not_delivered is not True:
        raise SalesValidationError(
            "Explicit confirmation that goods were not physically delivered is required"
        )
    if not isinstance(reason, str) or not reason.strip():
        raise SalesValidationError("A cancellation reason is required")
    reason = reason.strip()
    if len(reason) > 500:
        raise SalesValidationError("Cancellation reason must be at most 500 characters")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 128:
        raise SalesValidationError("A valid cancellation idempotency key is required")
    assert_posting_date_open(day)

    with transaction.atomic():
        locked = WarehouseCheck.objects.select_for_update().select_related(
            "sale", "sale_line__product", "sale__customer", "warehouse"
        ).get(pk=getattr(check, "pk", check))
        existing = WarehouseCheckReversal.objects.filter(
            idempotency_key=idempotency_key
        ).first()
        if existing:
            if (existing.warehouse_check_id != locked.pk or
                    existing.reversal_date != day or existing.reason != reason):
                raise SalesValidationError("This idempotency key was used for a different cancellation")
            return existing
        already = WarehouseCheckReversal.objects.filter(warehouse_check=locked).first()
        if already:
            raise SalesValidationError("This Warehouse Check has already been cancelled")
        if locked.status != CheckStatus.FINALIZED:
            raise SalesValidationError("Only a finalized Warehouse Check can be cancelled")
        # Serialize cancellation with check finalization and Sales Return creation.
        SaleLine.objects.select_for_update().get(pk=locked.sale_line_id)

        from sales.models import TransitSaleAllocation
        _source_movement_ids = list(
            SaleLineWarehouseAllocation.objects.filter(
                sale_line_id=locked.sale_line_id, stock_movement__isnull=False
            ).values_list("stock_movement_id", flat=True)
        )
        if locked.stock_movement_id:
            _source_movement_ids.append(locked.stock_movement_id)
        if _source_movement_ids and InventoryReturn.objects.filter(
            source_movement_id__in=_source_movement_ids
        ).exists():
            raise SalesValidationError(
                "This issue has Sales Return history; use the Sales Return workflow, not pre-delivery cancellation"
            )
        if NegativeCOGSObligation.objects.filter(warehouse_check=locked).exists():
            raise SalesValidationError(
                "This check has a negative-cost obligation; coordinated reversal is not supported until that obligation is resolved"
            )
        if NegativeCOGSObligation.objects.filter(
            sale_allocation__sale_line_id=locked.sale_line_id,
            resolved_quantity__lt=models.F("original_quantity"),
        ).exists():
            raise SalesValidationError(
                "This sale has an unresolved negative-cost obligation; cancellation is blocked until that obligation is resolved"
            )

        release = CustomerCustodyEvent.objects.select_for_update().filter(
            event_type="RELEASED",
            reference=locked.number,
            entitlement__sale_line_id=locked.sale_line_id,
            warehouse_id=locked.warehouse_id,
        ).first()
        if release is None:
            raise SalesValidationError("The original custody release event was not found")
        if release.reversal_events.exists():
            raise SalesValidationError("The original custody release has already been reversed")

        is_transit = TransitSaleAllocation.objects.filter(
            sale_line_id=locked.sale_line_id
        ).exists()

        def _coordinate_approved_cancellation(*, original, actor, reversal_date, reason, idempotency_key):
            if is_transit or SaleLineWarehouseAllocation.objects.filter(sale_line_id=locked.sale_line_id).exists():
                # COGS was posted at Sale finalization (Transit 1430 or the
                # allocated warehouse account). Cancelling the check restores
                # customer custody without touching stock or COGS.
                return
            if locked.stock_movement_id is None or locked.cogs_journal_id is None:
                raise SalesValidationError("A normal Warehouse Check lacks its stock/COGS source records")
            # Ownership transferred at Sale finalization. These goods remain
            # customer-owned while physically held here, so do not restore them
            # to company inventory or reverse the posted COGS journal.
            if locked.cogs_journal.status != "POSTED":
                raise SalesValidationError("The original COGS journal is not posted; cancellation is blocked")

        reversal_event = reverse_customer_custody_event(
            event=release, reversal_date=day, reason=reason,
            reference=f"REV-{locked.number}", user=actor,
            idempotency_key=f"wc-cancel-custody:{hashlib.sha256(idempotency_key.encode()).hexdigest()}",
            compensate=_coordinate_approved_cancellation,
        )
        reversal = WarehouseCheckReversal.objects.create(
            warehouse_check=locked, reversal_date=day, reason=reason,
            created_by=actor, idempotency_key=idempotency_key,
        )
        record_audit_event(
            user=actor, action=AuditAction.REVERSE,
            entity="WarehouseCheck", entity_id=locked.pk,
            reference=locked.number,
            previous_state={"status": locked.status, "quantity": locked.quantity},
            new_state={
                "reversal_id": reversal.pk,
                "custody_reversal_event_id": reversal_event.pk,
                "status": "CANCELLED",
            },
            reason=reason,
        )
        return reversal


def resolve_negative_obligations(*, receipt_movement):
    """Resolve receipt cost against oldest unresolved negative Sales COGS."""
    with transaction.atomic():
        remaining = receipt_movement.quantity
        if remaining <= 0:
            return []
        obligations = list(NegativeCOGSObligation.objects.select_for_update().filter(
            product_id=receipt_movement.product_id, warehouse_id=receipt_movement.warehouse_id,
            resolved_quantity__lt=models.F("original_quantity"),
        ).order_by("movement_date", "id"))
        created = []
        for obligation in obligations:
            if remaining <= 0:
                break
            open_qty = obligation.original_quantity - obligation.resolved_quantity
            qty = min(open_qty, remaining)
            actual = receipt_movement.unit_cost_afn
            # Persist the quantity/source relationship even when the receipt
            # exactly matches the temporary cost and no COGS journal is needed.
            # A later landed-cost invoice must still trace this consumed layer.
            NegativeCOGSReceiptAllocation.objects.create(
                obligation=obligation, receipt_movement=receipt_movement,
                quantity=qty,
            )
            difference = cogs_amount(qty, actual - obligation.temporary_unit_cost_afn)
            if difference != 0:
                inv = resolve_warehouse_account(receipt_movement.warehouse)
                base = receipt_movement.currency if receipt_movement.currency.is_base else __import__("currencies.models", fromlist=["Currency"]).Currency.objects.get(is_base=True)
                cogs_account = Account.objects.get(code=COGS_ACCOUNT)
                obligation_ref = (
                    obligation.warehouse_check.number if obligation.warehouse_check_id
                    else obligation.movement.reference
                )
                if difference > 0:
                    adjustment_lines = [
                        {"account": cogs_account, "debit": difference, "reference": obligation_ref},
                        {"account": inv, "credit": difference, "reference": receipt_movement.reference},
                    ]
                else:
                    adjustment_lines = [
                        {"account": inv, "debit": abs(difference), "reference": receipt_movement.reference},
                        {"account": cogs_account, "credit": abs(difference), "reference": obligation_ref},
                    ]
                entry = post_journal(
                    number=f"JE-COGS-ADJ-{obligation.pk}-{receipt_movement.pk}",
                    posting_date=receipt_movement.movement_date,
                    description=f"Negative COGS adjustment for {obligation_ref}",
                    lines=adjustment_lines,
                    source_type="SALES_COGS_ADJUSTMENT", source_id=f"{obligation.pk}:{receipt_movement.pk}",
                    currency=base, rate=Decimal("1.0000"), rate_date=receipt_movement.movement_date,
                    idempotency_key=f"cogs-adjustment:{obligation.pk}:{receipt_movement.pk}",
                )
                created.append(COGSAdjustment.objects.create(
                    obligation=obligation, receipt_movement=receipt_movement, quantity=qty,
                    actual_unit_cost_afn=actual, temporary_unit_cost_afn=obligation.temporary_unit_cost_afn,
                    difference=difference, journal_entry=entry,
                ))
            obligation.resolved_quantity += qty
            obligation.save(update_fields=["resolved_quantity"])
            remaining -= qty
        return created
