"""Phase 11 Returns / Refunds service layer.

Business truth:
    Return -> financial entitlement -> optional Refund.

Physical stock is delegated to inventory.services.sales_return().
Accounting is delegated to accounting.services.post_journal()/reverse_journal().
Customer attribution is delegated to party_ledger.services.attribute_journal_line().
"""
import hashlib
from datetime import date as date_class
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum

from accounting.models import Account
from accounting.services import post_journal, reverse_journal
from core.dates import gregorian_to_jalali
from core.money import quantize_half_up, normalize_rate
from currencies.models import Currency
from documents.services import next_document_number
from fiscal_periods.services import assert_posting_date_open
from inventory.models import InventoryReturn, MovementType, StockMovement
from inventory.services import sales_return as inventory_sales_return
from inventory.services import _reverse_sales_return_stock
from inventory.services import resolve_warehouse_account
from warehouses.services import resolve_warehouse

from party_ledger.services import attribute_journal_line
from security.models import AuditAction
from security.services import record_audit_event

from .models import (
    CrossCurrencyRefund, CrossCurrencyRefundStatus, SalesReturnReversal,
    PaymentMode, Refund, RefundStatus,
    SaleStatus, SalesReturn, SalesReturnStatus,
)


RETURN_ACCOUNT = "4200"
RECEIVABLE_ACCOUNT = "1310"
CUSTOMER_CREDIT_ACCOUNT = "2200"
CASH_ACCOUNT = "1110"
CLEARING_ACCOUNT = "1910"

SALES_RETURN_OPERATION = "sales.return"
REFUND_OPERATION = "sales.refund"
CROSS_REFUND_OPERATION = "sales.cross_currency_refund"


class ReturnValidationError(ValueError):
    pass


def _actor(user):
    if user is not None and not getattr(user, "is_authenticated", False):
        raise ReturnValidationError("Authenticated user required")
    return user


def _day(value):
    if isinstance(value, date_class):
        return value
    raise ReturnValidationError("A date is required")


def _currency(ref):
    if isinstance(ref, Currency) and ref.pk:
        found = ref
    else:
        found = Currency.objects.filter(code=ref).first()
    if not found or not found.is_active:
        raise ReturnValidationError("Currency does not exist or is inactive")
    return found


def _positive_amount(value, label):
    try:
        amount = quantize_half_up(Decimal(str(value)), 2)
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise ReturnValidationError(f"{label} must be a valid positive amount") from exc
    if amount <= 0:
        raise ReturnValidationError(f"{label} must be greater than zero")
    return amount


def _validate_idempotency_key(key, label):
    if key is not None and (
        not isinstance(key, str) or not key.strip() or len(key) > 128
    ):
        raise ReturnValidationError(f"A valid {label} idempotency key is required")


def _child_idempotency_key(namespace, key):
    return f"{namespace}:{hashlib.sha256(key.encode('utf-8')).hexdigest()}"


def _usable(code):
    try:
        account = Account.objects.get(code=code)
    except Account.DoesNotExist as exc:
        raise ReturnValidationError(f"Account {code} does not exist") from exc
    if not account.is_active or not account.is_posting:
        raise ReturnValidationError(f"Account {code} is not usable for posting")
    return account


def _jalali_year(day):
    return int(gregorian_to_jalali(day).split("/")[0])


def _remaining_released_quantity(sale_line):
    """Released quantity less physical returns, never invoice custody."""
    released = StockMovement.objects.filter(
        movement_type=MovementType.SALES_ISSUE,
        source_party=sale_line.sale.customer,
        product=sale_line.product,
    ).filter(
        warehouse_checks__sale_line=sale_line,
        warehouse_checks__status="FINALIZED",
    ).exclude(warehouse_checks__reversal__isnull=False).aggregate(v=Sum("quantity"))["v"] or 0
    returned = InventoryReturn.objects.filter(
        return_type="SALES_RETURN",
        product=sale_line.product,
        party=sale_line.sale.customer,
        source_movement__warehouse_checks__sale_line=sale_line,
    ).exclude(sales_return__status=SalesReturnStatus.REVERSED).aggregate(
        v=Sum("quantity")
    )["v"] or 0
    return int(abs(released)) - int(returned)


def _remaining_invoice_receivable(sale):
    """Outstanding receivable attributable to this invoice, not the whole customer.

    Phase 10A allocations are the authoritative link between payments and a
    specific credit Sale. Prior posted Returns may already have reduced that
    invoice's receivable; only the portion not converted to customer credit
    counts as a prior receivable reduction.
    """
    from allocations.services import invoice_outstanding

    outstanding = invoice_outstanding(sale)
    prior = SalesReturn.objects.filter(
        sale=sale, status=SalesReturnStatus.POSTED
    ).aggregate(
        entitlement=Sum("entitlement_amount"),
        refundable=Sum("refundable_amount"),
    )
    prior_entitlement = prior["entitlement"] or Decimal("0.00")
    prior_refundable = prior["refundable"] or Decimal("0.00")
    prior_receivable_reduction = prior_entitlement - prior_refundable
    return max(quantize_half_up(outstanding - prior_receivable_reduction, 2), Decimal("0.00"))


def _remaining_line_entitlement(sale_line):
    returned = SalesReturn.objects.filter(
        sale_line=sale_line, status=SalesReturnStatus.POSTED
    ).aggregate(v=Sum("entitlement_amount"))["v"] or Decimal("0.00")
    return quantize_half_up(sale_line.net_total - returned, 2)


def _allocate_return_entitlement(*, net_total, sale_quantity, returned_quantity,
                                  prior_amount, quantity):
    remaining_quantity = sale_quantity - returned_quantity
    remaining_amount = quantize_half_up(net_total - prior_amount, 2)
    if quantity > remaining_quantity:
        raise ReturnValidationError("Return quantity exceeds the remaining Sale Line quantity")
    if remaining_amount <= 0:
        raise ReturnValidationError("No financial entitlement remains for this Sale Line")
    # Proportional rounding is used for partial returns. The final return of
    # the entire sold line receives the exact remainder, avoiding penny leakage.
    if quantity == remaining_quantity:
        return remaining_amount
    proportional = quantize_half_up(
        net_total * Decimal(quantity) / Decimal(sale_quantity), 2
    )
    return min(proportional, remaining_amount)


def _returned_entitlement_amount(sale_line, quantity):
    prior = SalesReturn.objects.filter(
        sale_line=sale_line, status=SalesReturnStatus.POSTED
    ).aggregate(quantity=Sum("quantity"), amount=Sum("entitlement_amount"))
    return _allocate_return_entitlement(
        net_total=sale_line.net_total,
        sale_quantity=sale_line.quantity,
        returned_quantity=int(prior["quantity"] or 0),
        prior_amount=prior["amount"] or Decimal("0.00"),
        quantity=quantity,
    )


def _post_entitlement_journal(*, sale, customer, amount, posting_day, reference, actor):
    returns = _usable(RETURN_ACCOUNT)
    receivable = _usable(RECEIVABLE_ACCOUNT)
    credit = _usable(CUSTOMER_CREDIT_ACCOUNT)
    receivable_amount = Decimal("0.00")
    credit_amount = amount
    if sale.payment_mode == PaymentMode.CREDIT:
        # Never use the customer's aggregate 1310 balance here: it may include
        # unrelated invoices. Return can reduce only this Sale's outstanding amount.
        remaining_receivable = _remaining_invoice_receivable(sale)
        receivable_amount = min(amount, max(remaining_receivable, Decimal("0.00")))
        credit_amount = amount - receivable_amount

    lines = [{"account": returns, "debit": amount, "reference": reference,
              "description": f"Sales return {reference}"}]
    if receivable_amount:
        lines.append({"account": receivable, "credit": receivable_amount,
                      "reference": reference, "description": "Reduce customer receivable"})
    if credit_amount:
        lines.append({"account": credit, "credit": credit_amount,
                      "reference": reference, "description": "Customer return credit"})

    entry = post_journal(
        number=next_document_number("JE", _jalali_year(posting_day)),
        posting_date=posting_day,
        description=f"Sales return entitlement {reference}",
        lines=lines,
        source_type="SALES_RETURN",
        source_id=reference,
        currency=sale.currency,
        rate=sale.exchange_rate,
        rate_date=sale.rate_date,
        created_by=actor,
        idempotency_key=f"sales-return:{reference}:journal",
        allow_unvalued_foreign=(not sale.currency.is_base and sale.exchange_rate is None),
    )
    for code in (RECEIVABLE_ACCOUNT, CUSTOMER_CREDIT_ACCOUNT):
        if any(line.account.code == code for line in entry.lines.all()):
            attribute_journal_line(entry.lines.get(account__code=code), party=customer, user=actor)
    return entry, receivable_amount, credit_amount


def create_sales_return(*, sale_line, warehouse, quantity, return_date,
                        reason, user=None, document_number=None,
                        idempotency_key=None, acknowledge_negative=False):
    actor = _actor(user)
    _validate_idempotency_key(idempotency_key, "sales return")
    day = _day(return_date)
    if not isinstance(reason, str) or not reason.strip():
        raise ReturnValidationError("A return reason is required")
    reason = reason.strip()
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ReturnValidationError("Return quantity must be a positive integer")

    with transaction.atomic():
        warehouse = resolve_warehouse(warehouse)
        line = sale_line.__class__.objects.select_for_update().select_related(
            "sale", "product", "unit", "sale__customer", "sale__currency"
        ).get(pk=getattr(sale_line, "pk", sale_line))
        sale = line.sale
        if sale.status != SaleStatus.FINALIZED:
            raise ReturnValidationError("Only finalized Sales can be returned")
        assert_posting_date_open(day)

        if idempotency_key:
            existing = SalesReturn.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                if (
                    existing.sale_line_id != line.pk
                    or existing.warehouse_id != warehouse.pk
                    or existing.quantity != quantity
                    or existing.return_date != day
                    or existing.reason != reason
                    or existing.created_by_id != (actor.pk if actor else None)
                    or (document_number is not None and existing.document_number != document_number)
                ):
                    raise ReturnValidationError("This idempotency key was used for a different return")
                return existing

        released_remaining = _remaining_released_quantity(line)
        if quantity > released_remaining:
            raise ReturnValidationError(
                f"Return quantity exceeds actually released quantity ({released_remaining})"
            )

        # One physical return is tied to one already-finalized Warehouse Check.
        # The selected source movement is resolved from the check with enough
        # remaining released quantity, never from invoice custody quantity.
        source_rows = list(
            StockMovement.objects.select_for_update().filter(
                movement_type=MovementType.SALES_ISSUE,
                product=line.product,
                source_party=sale.customer,
                warehouse=warehouse,
                warehouse_checks__sale_line=line,
                warehouse_checks__status="FINALIZED",
            ).exclude(warehouse_checks__reversal__isnull=False).order_by("id")
        )
        source = None
        for candidate in source_rows:
            used = InventoryReturn.objects.filter(
                source_movement=candidate
            ).exclude(sales_return__status=SalesReturnStatus.REVERSED).aggregate(
                v=Sum("quantity")
            )["v"] or 0
            if abs(candidate.quantity) - int(used) >= quantity:
                source = candidate
                break
        if source is None:
            raise ReturnValidationError(
                "No single released warehouse issue has enough remaining quantity for this return"
            )

        warehouse_obj = source.warehouse
        inventory_key = (
            _child_idempotency_key("sales-return-inventory", idempotency_key)
            if idempotency_key else None
        )
        inv = inventory_sales_return(
            product=line.product,
            warehouse=warehouse_obj,
            customer=sale.customer,
            source_movement=source,
            quantity=quantity,
            source_document=source.reference,
            movement_date=day,
            description=reason,
            user=actor,
            idempotency_key=inventory_key,
        )

        amount = _returned_entitlement_amount(line, quantity)
        if document_number is None:
            document_number = next_document_number("SR", _jalali_year(day))
        if SalesReturn.objects.filter(document_number=document_number).exists():
            raise ReturnValidationError("Sales return document number already exists")

        entry, receivable_amount, refundable_amount = _post_entitlement_journal(
            sale=sale, customer=sale.customer, amount=amount,
            posting_day=day, reference=document_number, actor=actor
        )
        base = Currency.objects.filter(is_base=True).first()
        if base is None:
            raise ReturnValidationError("No base currency is configured")
        inventory_account = resolve_warehouse_account(warehouse_obj)
        cogs_account = _usable("5100")
        cogs_value = quantize_half_up(inv.return_movement.unit_cost_afn * Decimal(quantity), 2)
        cogs_entry = post_journal(
            number=next_document_number("JE", _jalali_year(day)),
            posting_date=day,
            description=f"COGS reversal for sales return {document_number}",
            lines=[
                {"account": inventory_account, "debit": cogs_value, "reference": document_number,
                 "description": "Return inventory to warehouse"},
                {"account": cogs_account, "credit": cogs_value, "reference": document_number,
                 "description": "Reverse COGS for returned goods"},
            ],
            source_type="SALES_RETURN_COGS", source_id=document_number,
            currency=base, rate=Decimal("1.0000"), rate_date=day,
            created_by=actor, idempotency_key=f"sales-return:{document_number}:cogs",
        )
        record = SalesReturn.objects.create(
            document_number=document_number, sale=sale, sale_line=line,
            inventory_return=inv, warehouse=warehouse_obj, return_date=day,
            quantity=quantity, entitlement_currency=sale.currency,
            entitlement_amount=amount, refundable_amount=refundable_amount, entitlement_journal=entry,
            cogs_journal=cogs_entry,
            status=SalesReturnStatus.POSTED, reason=reason, created_by=actor,
            idempotency_key=idempotency_key or f"sales-return:{document_number}",
        )
        record_audit_event(
            user=actor, action=AuditAction.CREATE, entity="SalesReturn",
            entity_id=record.pk, reference=document_number,
            previous_state=None,
            new_state={"sale_id": sale.pk, "sale_line_id": line.pk, "quantity": quantity,
                       "entitlement_amount": str(amount), "refundable_amount": str(refundable_amount), "currency": sale.currency.code,
                       "inventory_return_id": inv.pk, "journal_entry_id": entry.pk},
            reason=reason,
        )
        return record


def _validate_rate(entitlement_currency, refund_currency, rate):
    if entitlement_currency.pk == refund_currency.pk:
        if rate is not None and normalize_rate(Decimal(str(rate))) != Decimal("1.0000"):
            raise ReturnValidationError("Same-currency refund rate must be 1.0000")
        return Decimal("1.0000"), f"{entitlement_currency.code} per {refund_currency.code}"
    if rate is None:
        raise ReturnValidationError("An explicit rate is required for a cross-currency refund")
    try:
        value = normalize_rate(Decimal(str(rate)))
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise ReturnValidationError("Refund rate must be a valid positive number") from exc
    if value <= 0:
        raise ReturnValidationError("Refund rate must be positive")
    base = Currency.objects.filter(is_base=True).first()
    if base and entitlement_currency.is_base != refund_currency.is_base:
        foreign = refund_currency if entitlement_currency.is_base else entitlement_currency
        # For AFN/USD refunds, persist the familiar market quote: base-currency
        # units per one foreign-currency unit, regardless of refund direction.
        direction = f"{base.code} per {foreign.code}"
    else:
        direction = f"{refund_currency.code} per {entitlement_currency.code}"
    return value, direction


def _refund_amount(entitlement_amount, entitlement_currency, refund_currency, rate):
    if entitlement_currency.pk == refund_currency.pk:
        return entitlement_amount
    # Rate is expressed as refund-currency units per one entitlement-currency unit
    # for the canonical direction. The reverse case stores the same human rate
    # as entitlement currency units per refund currency unit.
    if entitlement_currency.is_base and not refund_currency.is_base:
        return quantize_half_up(entitlement_amount / rate, 2)
    if not entitlement_currency.is_base and refund_currency.is_base:
        return quantize_half_up(entitlement_amount * rate, 2)
    # For two non-base currencies, the explicit rate is always payment units per
    # entitlement unit. This keeps the persisted direction unambiguous.
    return quantize_half_up(entitlement_amount * rate, 2)


def _remaining_refundable(sales_return):
    used = sales_return.refunds.filter(status=RefundStatus.POSTED).aggregate(v=Sum("entitlement_amount"))["v"] or Decimal("0")
    return quantize_half_up(sales_return.refundable_amount - used, 2)


def _same_currency_refund_journal(*, refund, actor):
    cash = _usable(CASH_ACCOUNT)
    credit = _usable(CUSTOMER_CREDIT_ACCOUNT)
    entry = post_journal(
        number=next_document_number("JE", _jalali_year(refund.refund_date)),
        posting_date=refund.refund_date,
        description=f"Customer refund {refund.document_number}",
        lines=[
            {"account": credit, "debit": refund.entitlement_amount,
             "reference": refund.document_number, "description": "Consume customer return credit"},
            {"account": cash, "credit": refund.refund_amount,
             "reference": refund.document_number, "description": "Cash refund"},
        ],
        source_type="REFUND", source_id=refund.document_number,
        currency=refund.refund_currency,
        rate=Decimal("1.0000"), rate_date=refund.refund_date,
        created_by=actor,
        idempotency_key=f"refund:{refund.document_number}:journal",
    )
    attribute_journal_line(entry.lines.get(account__code=CUSTOMER_CREDIT_ACCOUNT),
                           party=refund.sales_return.sale.customer, user=actor)
    return entry


def create_refund(*, sales_return, refund_date, refund_currency, entitlement_amount,
                  rate=None, reason="", user=None, document_number=None,
                  idempotency_key=None):
    actor = _actor(user)
    _validate_idempotency_key(idempotency_key, "refund")
    day = _day(refund_date)
    if not isinstance(reason, str):
        raise ReturnValidationError("Refund reason must be text")
    reason = reason.strip() or "Customer refund"
    with transaction.atomic():
        ret = SalesReturn.objects.select_for_update().select_related(
            "sale__customer", "entitlement_currency", "sale__currency"
        ).get(pk=getattr(sales_return, "pk", sales_return))
        if ret.status != SalesReturnStatus.POSTED:
            raise ReturnValidationError("Only a posted Sales Return can be refunded")
        assert_posting_date_open(day)
        entitlement_currency = ret.entitlement_currency
        refund_currency = _currency(refund_currency)
        amount = _positive_amount(entitlement_amount, "Refund entitlement amount")
        rate_value, direction = _validate_rate(entitlement_currency, refund_currency, rate)
        refund_amount = _refund_amount(amount, entitlement_currency, refund_currency, rate_value)
        if idempotency_key:
            existing = Refund.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                if (
                    existing.sales_return_id != ret.pk
                    or existing.refund_date != day
                    or existing.entitlement_amount != amount
                    or existing.refund_currency_id != refund_currency.pk
                    or existing.refund_amount != refund_amount
                    or existing.agreed_rate != rate_value
                    or existing.rate_direction != direction
                    or existing.reason != reason
                    or existing.created_by_id != (actor.pk if actor else None)
                    or (document_number is not None and existing.document_number != document_number)
                ):
                    raise ReturnValidationError("This idempotency key was used for a different refund")
                return existing
        remaining = _remaining_refundable(ret)
        if amount > remaining:
            raise ReturnValidationError(
                f"Refund exceeds remaining refundable entitlement ({remaining})"
            )
        if document_number is None:
            document_number = next_document_number("RF", _jalali_year(day))
        if Refund.objects.filter(document_number=document_number).exists():
            raise ReturnValidationError("Refund document number already exists")

        refund = Refund.objects.create(
            document_number=document_number, sales_return=ret, refund_date=day,
            entitlement_currency=entitlement_currency, entitlement_amount=amount,
            refund_currency=refund_currency, refund_amount=refund_amount,
            agreed_rate=rate_value, rate_direction=direction, status=RefundStatus.POSTED,
            reason=reason, created_by=actor,
            idempotency_key=idempotency_key or f"refund:{document_number}",
        )

        if entitlement_currency.pk == refund_currency.pk:
            entry = _same_currency_refund_journal(refund=refund, actor=actor)
            Refund.objects.filter(pk=refund.pk).update(journal_entry=entry)
            refund.journal_entry = entry
        else:
            clearing = _usable(CLEARING_ACCOUNT)
            credit = _usable(CUSTOMER_CREDIT_ACCOUNT)
            cash = _usable(CASH_ACCOUNT)
            entitlement_entry = post_journal(
                number=next_document_number("JE", _jalali_year(day)),
                posting_date=day,
                description=f"Cross-currency refund entitlement {document_number}",
                lines=[
                    {"account": credit, "debit": amount, "reference": document_number,
                     "description": "Consume customer return credit"},
                    {"account": clearing, "credit": amount, "reference": document_number,
                     "description": "Cross-currency refund bridge"},
                ],
                source_type="REFUND_CROSS_CURRENCY",
                source_id=document_number,
                currency=entitlement_currency,
                rate=ret.sale.exchange_rate,
                rate_date=ret.sale.rate_date,
                created_by=actor,
                idempotency_key=f"refund:{document_number}:entitlement",
                allow_unvalued_foreign=(not entitlement_currency.is_base and ret.sale.exchange_rate is None),
            )
            attribute_journal_line(entitlement_entry.lines.get(account__code=CUSTOMER_CREDIT_ACCOUNT),
                                   party=ret.sale.customer, user=actor)
            cash_entry = post_journal(
                number=next_document_number("JE", _jalali_year(day)),
                posting_date=day,
                description=f"Cross-currency refund cash {document_number}",
                lines=[
                    {"account": clearing, "debit": refund_amount, "reference": document_number,
                     "description": "Cross-currency refund bridge"},
                    {"account": cash, "credit": refund_amount, "reference": document_number,
                     "description": "Actual cash outflow"},
                ],
                source_type="REFUND_CROSS_CURRENCY",
                source_id=document_number,
                currency=refund_currency,
                rate=(
                    Decimal("1.0000") if refund_currency.is_base
                    else rate_value if entitlement_currency.is_base
                    else None
                ),
                rate_date=(
                    day if refund_currency.is_base or entitlement_currency.is_base
                    else None
                ),
                created_by=actor,
                idempotency_key=f"refund:{document_number}:cash",
                allow_unvalued_foreign=(
                    not refund_currency.is_base and not entitlement_currency.is_base
                ),
            )
            Refund.objects.filter(pk=refund.pk).update(journal_entry=cash_entry)
            refund.journal_entry = cash_entry
            CrossCurrencyRefund.objects.create(
                refund=refund, entitlement_currency=entitlement_currency,
                entitlement_amount=amount, refund_currency=refund_currency,
                refund_amount=refund_amount, agreed_rate=rate_value,
                rate_direction=direction, entitlement_journal=entitlement_entry,
                cash_journal=cash_entry, status=CrossCurrencyRefundStatus.POSTED,
                idempotency_key=idempotency_key or f"cross-refund:{document_number}",
            )
        record_audit_event(
            user=actor, action=AuditAction.CREATE, entity="Refund",
            entity_id=refund.pk, reference=document_number,
            previous_state=None,
            new_state={"sales_return_id": ret.pk, "entitlement_amount": str(amount),
                       "entitlement_currency": entitlement_currency.code,
                       "refund_amount": str(refund_amount), "refund_currency": refund_currency.code,
                       "rate": str(rate_value)},
            reason=reason,
        )
        return refund


def reverse_refund(refund, *, reason, user=None):
    actor = _actor(user)
    with transaction.atomic():
        # journal_entry is nullable for a newly created Refund; lock only
        # the Refund row so PostgreSQL does not try to lock the nullable side
        # of the LEFT OUTER JOIN introduced by select_related().
        obj = Refund.objects.select_for_update(of=("self",)).select_related(
            "sales_return", "journal_entry"
        ).get(pk=getattr(refund, "pk", refund))
        if obj.status != RefundStatus.POSTED:
            raise ReturnValidationError("Only a posted Refund can be reversed")
        cross = getattr(obj, "cross_currency_refund", None)
        if cross is not None:
            if cross.status != CrossCurrencyRefundStatus.POSTED:
                raise ReturnValidationError("Cross-currency Refund is already reversed")
            reverse_journal(cross.entitlement_journal, reason, actor, _allow_cross_currency_refund=True)
            reverse_journal(cross.cash_journal, reason, actor, _allow_cross_currency_refund=True)
            CrossCurrencyRefund.objects.filter(pk=cross.pk).update(status=CrossCurrencyRefundStatus.REVERSED)
            cross.status = CrossCurrencyRefundStatus.REVERSED
        else:
            reverse_journal(obj.journal_entry, reason, actor)
        Refund.objects.filter(pk=obj.pk).update(status=RefundStatus.REVERSED)
        obj.status = RefundStatus.REVERSED
        record_audit_event(
            user=actor, action=AuditAction.REVERSE, entity="Refund",
            entity_id=obj.pk, reference=obj.document_number,
            previous_state={"status": RefundStatus.POSTED},
            new_state={"status": RefundStatus.REVERSED},
            reason=reason,
        )
        return obj


def reverse_sales_return(sales_return, *, reversal_date, reason, user=None,
                          document_number=None, idempotency_key=None):
    """Reverse a posted return through compensating stock and journal events.

    The original Sale, InventoryReturn, stock movements, and journals remain
    immutable. Any active refunds must be reversed before the return itself.
    """
    actor = _actor(user)
    _validate_idempotency_key(idempotency_key, "sales return reversal")
    day = _day(reversal_date)
    if not isinstance(reason, str) or not reason.strip():
        raise ReturnValidationError("A return reversal reason is required")
    reason = reason.strip()
    if len(reason) > 500:
        raise ReturnValidationError("Return reversal reason must be at most 500 characters")
    if idempotency_key is not None and (
        not isinstance(idempotency_key, str) or not idempotency_key
        or len(idempotency_key) > 128
    ):
        raise ReturnValidationError("A valid idempotency key is required")

    with transaction.atomic():
        ret = SalesReturn.objects.select_for_update().select_related(
            "sale__customer", "inventory_return", "entitlement_journal", "cogs_journal"
        ).get(pk=getattr(sales_return, "pk", sales_return))
        existing = None
        if idempotency_key:
            existing = SalesReturnReversal.objects.filter(
                idempotency_key=idempotency_key
            ).first()
        if existing:
            if (
                existing.sales_return_id != ret.pk
                or existing.reversal_date != day
                or existing.reason != reason
                or existing.created_by_id != (actor.pk if actor else None)
                or (document_number is not None and existing.document_number != document_number)
            ):
                raise ReturnValidationError(
                    "This idempotency key was used for a different return reversal"
                )
            return existing

        if ret.status != SalesReturnStatus.POSTED:
            raise ReturnValidationError("Only a posted Sales Return can be reversed")
        if ret.refunds.filter(status=RefundStatus.POSTED).exists():
            raise ReturnValidationError(
                "Reverse all posted Refunds before reversing the Sales Return"
            )
        assert_posting_date_open(day)

        if document_number is None:
            document_number = next_document_number("SRV", _jalali_year(day))
        if not isinstance(document_number, str) or not document_number.strip():
            raise ReturnValidationError("A reversal document number is required")
        document_number = document_number.strip()
        if len(document_number) > 30:
            raise ReturnValidationError("Reversal document number must be at most 30 characters")
        if SalesReturnReversal.objects.filter(document_number=document_number).exists():
            raise ReturnValidationError("Return reversal document number already exists")

        key = idempotency_key or f"sales-return-reversal:{document_number}"
        stock_key = _child_idempotency_key("sales-return-reversal-stock", key)
        movement = _reverse_sales_return_stock(
            inventory_return=ret.inventory_return,
            movement_date=day,
            reference=document_number,
            description=reason,
            user=actor,
            idempotency_key=stock_key,
        )
        entitlement_reversal = reverse_journal(
            ret.entitlement_journal, reason, actor
        )
        cogs_reversal = reverse_journal(ret.cogs_journal, reason, actor)

        reversal = SalesReturnReversal.objects.create(
            document_number=document_number,
            sales_return=ret,
            reversal_date=day,
            inventory_movement=movement,
            entitlement_reversal_journal=entitlement_reversal,
            cogs_reversal_journal=cogs_reversal,
            reason=reason,
            created_by=actor,
            idempotency_key=key,
        )
        SalesReturn.objects.filter(pk=ret.pk).update(status=SalesReturnStatus.REVERSED)
        record_audit_event(
            user=actor, action=AuditAction.REVERSE, entity="SalesReturn",
            entity_id=ret.pk, reference=ret.document_number,
            previous_state={"status": SalesReturnStatus.POSTED},
            new_state={
                "status": SalesReturnStatus.REVERSED,
                "reversal_id": reversal.pk,
                "reversal_document_number": reversal.document_number,
                "inventory_movement_id": movement.pk,
                "entitlement_reversal_journal_id": entitlement_reversal.pk,
                "cogs_reversal_journal_id": cogs_reversal.pk,
            },
            reason=reason,
        )
        return reversal
