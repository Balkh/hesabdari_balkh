"""Phase 11 Returns / Refunds service layer.

Business truth:
    Return -> financial entitlement -> optional Refund.

Physical stock is delegated to inventory.services.sales_return().
Accounting is delegated to accounting.services.post_journal()/reverse_journal().
Customer attribution is delegated to party_ledger.services.attribute_journal_line().
"""
from datetime import date as date_class
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounting.models import Account, JournalStatus
from accounting.services import post_journal, reverse_journal
from core.dates import gregorian_to_jalali
from core.idempotency import DuplicateOperationError, IdempotencyRecord, idempotent_operation
from core.money import quantize_half_up, normalize_rate
from currencies.models import Currency
from documents.services import next_document_number
from fiscal_periods.services import assert_posting_date_open
from inventory.models import InventoryReturn, MovementType, StockMovement
from inventory.services import sales_return as inventory_sales_return
from party_ledger.models import BalanceType, PartyLedgerAttribution, PARTY_LEDGER_ACCOUNTS
from party_ledger.services import attribute_journal_line
from security.models import AuditAction
from security.services import record_audit_event

from .models import (
    CrossCurrencyRefund, CrossCurrencyRefundStatus,
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


def _posted_party_balance(party, currency, account_code):
    """Current posted balance for one party/account/currency.

    This deliberately reads the existing Party Ledger attribution rather than
    introducing another balance engine. Reversed journals are excluded; their
    original financial effect is therefore removed from the live balance.
    """
    qs = PartyLedgerAttribution.objects.filter(
        party=party,
        journal_line__account__code=account_code,
        journal_line__entry__currency=currency,
        journal_line__entry__status=JournalStatus.POSTED,
    )
    debit = qs.aggregate(v=Sum("journal_line__debit"))["v"] or Decimal("0")
    credit = qs.aggregate(v=Sum("journal_line__credit"))["v"] or Decimal("0")
    if account_code == RECEIVABLE_ACCOUNT:
        return debit - credit
    if account_code == CUSTOMER_CREDIT_ACCOUNT:
        return credit - debit
    raise ReturnValidationError("Unsupported party balance account")


def _remaining_released_quantity(sale_line):
    """Released quantity less physical returns, never invoice custody."""
    released = StockMovement.objects.filter(
        movement_type=MovementType.SALES_ISSUE,
        source_party=sale_line.sale.customer,
        product=sale_line.product,
    ).filter(
        warehouse_checks__sale_line=sale_line,
        warehouse_checks__status="FINALIZED",
    ).aggregate(v=Sum("quantity"))["v"] or 0
    returned = InventoryReturn.objects.filter(
        return_type="SALES_RETURN",
        product=sale_line.product,
        party=sale_line.sale.customer,
    ).filter(
        source_movement__warehouse_checks__sale_line=sale_line,
    ).aggregate(v=Sum("quantity"))["v"] or 0
    return int(abs(released)) - int(returned)


def _remaining_line_entitlement(sale_line):
    returned = SalesReturn.objects.filter(
        sale_line=sale_line, status=SalesReturnStatus.POSTED
    ).aggregate(v=Sum("entitlement_amount"))["v"] or Decimal("0.00")
    return quantize_half_up(sale_line.net_total - returned, 2)


def _returned_entitlement_amount(sale_line, quantity):
    remaining = _remaining_line_entitlement(sale_line)
    if remaining <= 0:
        raise ReturnValidationError("No financial entitlement remains for this Sale Line")
    # Allocate the line's financial value proportionally; the final return
    # receives the exact remainder, preventing rounding leakage.
    proportional = quantize_half_up(
        sale_line.net_total * Decimal(quantity) / Decimal(sale_line.quantity), 2
    )
    return min(proportional, remaining)


def _post_entitlement_journal(*, sale, customer, amount, posting_day, reference, actor):
    returns = _usable(RETURN_ACCOUNT)
    receivable = _usable(RECEIVABLE_ACCOUNT)
    credit = _usable(CUSTOMER_CREDIT_ACCOUNT)
    remaining_receivable = _posted_party_balance(customer, sale.currency, RECEIVABLE_ACCOUNT)

    receivable_amount = Decimal("0.00")
    credit_amount = amount
    if sale.payment_mode == PaymentMode.CREDIT:
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
    return entry


def create_sales_return(*, sale_line, warehouse, quantity, return_date,
                        reason, user=None, document_number=None,
                        idempotency_key=None, acknowledge_negative=False):
    actor = _actor(user)
    day = _day(return_date)
    if not isinstance(reason, str) or not reason.strip():
        raise ReturnValidationError("A return reason is required")
    reason = reason.strip()
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ReturnValidationError("Return quantity must be a positive integer")

    with transaction.atomic():
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
                    existing.sale_line_id != line.pk or existing.quantity != quantity
                    or existing.return_date != day or existing.reason != reason
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
                warehouse__in=[warehouse] if getattr(warehouse, "pk", None) else [],
                warehouse_checks__sale_line=line,
                warehouse_checks__status="FINALIZED",
            ).order_by("id")
        )
        source = None
        for candidate in source_rows:
            used = InventoryReturn.objects.filter(source_movement=candidate).aggregate(v=Sum("quantity"))["v"] or 0
            if abs(candidate.quantity) - int(used) >= quantity:
                source = candidate
                break
        if source is None:
            raise ReturnValidationError(
                "No single released warehouse issue has enough remaining quantity for this return"
            )

        warehouse_obj = source.warehouse
        inventory_key = f"{idempotency_key}:inventory" if idempotency_key else None
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

        entry = _post_entitlement_journal(
            sale=sale, customer=sale.customer, amount=amount,
            posting_day=day, reference=document_number, actor=actor
        )
        record = SalesReturn.objects.create(
            document_number=document_number, sale=sale, sale_line=line,
            inventory_return=inv, warehouse=warehouse_obj, return_date=day,
            quantity=quantity, entitlement_currency=sale.currency,
            entitlement_amount=amount, entitlement_journal=entry,
            status=SalesReturnStatus.POSTED, reason=reason, created_by=actor,
            idempotency_key=idempotency_key or f"sales-return:{document_number}",
        )
        record_audit_event(
            user=actor, action=AuditAction.CREATE, entity="SalesReturn",
            entity_id=record.pk, reference=document_number,
            previous_state=None,
            new_state={"sale_id": sale.pk, "sale_line_id": line.pk, "quantity": quantity,
                       "entitlement_amount": str(amount), "currency": sale.currency.code,
                       "inventory_return_id": inv.pk, "journal_entry_id": entry.pk},
            reason=reason,
        )
        return record


def _validate_rate(entitlement_currency, refund_currency, rate):
    if entitlement_currency_id := getattr(entitlement_currency, "pk", None):
        pass
    if entitlement_currency.pk == refund_currency.pk:
        if rate is not None and normalize_rate(Decimal(str(rate))) != Decimal("1.0000"):
            raise ReturnValidationError("Same-currency refund rate must be 1.0000")
        return Decimal("1.0000"), f"{entitlement_currency.code}->{refund_currency.code}"
    if rate is None:
        raise ReturnValidationError("An explicit rate is required for a cross-currency refund")
    value = normalize_rate(Decimal(str(rate)))
    if value <= 0:
        raise ReturnValidationError("Refund rate must be positive")
    return value, f"{entitlement_currency.code}->{refund_currency.code}"


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
    return quantize_half_up(sales_return.entitlement_amount - used, 2)


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
        remaining = _remaining_refundable(ret)
        if amount > remaining:
            raise ReturnValidationError(
                f"Refund exceeds remaining refundable entitlement ({remaining})"
            )
        rate_value, direction = _validate_rate(entitlement_currency, refund_currency, rate)
        refund_amount = _refund_amount(amount, entitlement_currency, refund_currency, rate_value)
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
            refund.journal_entry = entry
            refund.save(update_fields=["journal_entry"])
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
                rate=Decimal("1.0000") if refund_currency.is_base else None,
                rate_date=day if refund_currency.is_base else None,
                created_by=actor,
                idempotency_key=f"refund:{document_number}:cash",
                allow_unvalued_foreign=not refund_currency.is_base,
            )
            refund.journal_entry = cash_entry
            refund.save(update_fields=["journal_entry"])
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
        obj = Refund.objects.select_for_update().select_related("sales_return", "journal_entry").get(pk=getattr(refund, "pk", refund))
        if obj.status != RefundStatus.POSTED:
            raise ReturnValidationError("Only a posted Refund can be reversed")
        cross = getattr(obj, "cross_currency_refund", None)
        if cross is not None:
            if cross.status != CrossCurrencyRefundStatus.POSTED:
                raise ReturnValidationError("Cross-currency Refund is already reversed")
            reverse_journal(cross.entitlement_journal, reason, actor, _allow_cross_currency_settlement=True)
            reverse_journal(cross.cash_journal, reason, actor, _allow_cross_currency_settlement=True)
            cross.status = CrossCurrencyRefundStatus.REVERSED
            cross.save(update_fields=["status"])
        else:
            reverse_journal(obj.journal_entry, reason, actor)
        obj.status = RefundStatus.REVERSED
        obj.save(update_fields=["status"])
        record_audit_event(
            user=actor, action=AuditAction.REVERSE, entity="Refund",
            entity_id=obj.pk, reference=obj.document_number,
            previous_state={"status": RefundStatus.POSTED},
            new_state={"status": RefundStatus.REVERSED},
            reason=reason,
        )
        return obj
