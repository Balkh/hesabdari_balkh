from datetime import date
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from accounting.models import Account
from accounting.services import post_journal
from core.money import cogs as cogs_amount, line_total, quantize_half_up, normalize_rate
from fiscal_periods.services import assert_posting_date_open
from inventory.models import StockMovement
from inventory.services import issue_stock, resolve_warehouse_account
from party_ledger.services import attribute_journal_line
from parties.services import resolve_party
from products.services import resolve_product
from uom.models import UnitOfMeasure
from warehouses.services import resolve_warehouse

from .models import (
    COGSAdjustment, CheckStatus, NegativeCOGSObligation, OwnershipEvent,
    PaymentMode, Sale, SaleLine, SaleStatus, SalesChannel, SaleType,
    WarehouseCheck,
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
    if value is None or rate_date is None:
        raise SalesValidationError("Foreign sales require rate and rate_date")
    return normalize_rate(value), _date(rate_date)


def _customer(ref):
    party = resolve_party(ref)
    if not party.is_customer or not party.is_active:
        raise SalesValidationError("Active customer Party required")
    return party


def _line_rows(lines):
    rows = []
    for row in lines:
        try:
            product = resolve_product(row["product"])
            unit = row["unit"] if isinstance(row["unit"], UnitOfMeasure) else UnitOfMeasure.objects.get(pk=row["unit"])
            warehouse = row.get("warehouse")
        except (KeyError, UnitOfMeasure.DoesNotExist) as exc:
            raise SalesValidationError("Product and UOM are required") from exc
        if warehouse is not None:
            raise SalesValidationError("Warehouse belongs to Warehouse Check, not SaleLine")
        quantity = row.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise SalesValidationError("Quantity must be a positive integer")
        price = quantize_half_up(row.get("unit_price"), 4)
        discount = quantize_half_up(row.get("discount", 0), 2)
        gross = line_total(quantity, price)
        if discount < 0 or discount > gross:
            raise SalesValidationError("Invalid discount")
        rows.append({"product": product, "unit": unit, "quantity": quantity,
                     "unit_price": price, "discount": discount,
                     "gross": gross, "net": gross - discount})
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
            SaleLine.objects.create(sale=sale, product=row["product"], unit=row["unit"],
                                    quantity=row["quantity"], unit_price=row["unit_price"],
                                    discount=row["discount"], line_total=row["gross"], net_total=row["net"])
    return sale


def finalize_sale(*, sale, user=None, idempotency_key=None):
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
        )
        if sale.payment_mode == PaymentMode.CREDIT:
            attribute_journal_line(journal.lines.get(account__code=RECEIVABLE_ACCOUNT), party=sale.customer, user=actor)
        sale.status = SaleStatus.FINALIZED
        sale.finalized_at = timezone.now()
        sale.journal_entry = journal
        sale.save(update_fields=["status", "finalized_at", "journal_entry"])
    return sale


def remaining_quantity(line):
    line_id = getattr(line, "pk", line)
    line = SaleLine.objects.get(pk=line_id)
    used = line.warehouse_checks.filter(status=CheckStatus.FINALIZED).aggregate(total=models.Sum("quantity"))["total"] or 0
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
        if check.status == CheckStatus.FINALIZED:
            return check
        line = SaleLine.objects.select_for_update().get(pk=check.sale_line_id)
        if check.sale_id != line.sale_id:
            raise SalesValidationError("Warehouse Check must belong to its Sales Invoice Line")
        used = WarehouseCheck.objects.filter(sale_line=line, status=CheckStatus.FINALIZED).aggregate(total=models.Sum("quantity"))["total"] or 0
        if check.quantity > line.quantity - used:
            raise SalesValidationError("Warehouse Check exceeds remaining Invoice Line quantity")
        assert_posting_date_open(check.sale.sale_date)
        movement = issue_stock(
            product=line.product, warehouse=check.warehouse, quantity=check.quantity,
            movement_date=check.sale.sale_date, reference=check.number,
            description=f"Warehouse Check {check.number}", user=actor,
            idempotency_key=idempotency_key or f"warehouse-check:{check.pk}:issue",
            acknowledge_negative=acknowledge_negative, temporary_unit_cost=temporary_unit_cost,
            temporary_currency=temporary_currency, temporary_rate=temporary_rate,
            temporary_rate_date=temporary_rate_date, party=check.sale.customer,
        )
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
        OwnershipEvent.objects.create(warehouse_check=check, sale_line=line, customer=check.sale.customer,
                                      product=line.product, warehouse=check.warehouse, quantity=check.quantity)
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
            difference = cogs_amount(qty, actual - obligation.temporary_unit_cost_afn)
            if difference != 0:
                inv = resolve_warehouse_account(receipt_movement.warehouse)
                base = receipt_movement.currency if receipt_movement.currency.is_base else __import__("currencies.models", fromlist=["Currency"]).Currency.objects.get(is_base=True)
                cogs_account = Account.objects.get(code=COGS_ACCOUNT)
                if difference > 0:
                    adjustment_lines = [
                        {"account": cogs_account, "debit": difference, "reference": obligation.warehouse_check.number},
                        {"account": inv, "credit": difference, "reference": receipt_movement.reference},
                    ]
                else:
                    adjustment_lines = [
                        {"account": inv, "debit": abs(difference), "reference": receipt_movement.reference},
                        {"account": cogs_account, "credit": abs(difference), "reference": obligation.warehouse_check.number},
                    ]
                entry = post_journal(
                    number=f"JE-COGS-ADJ-{obligation.pk}-{receipt_movement.pk}",
                    posting_date=receipt_movement.movement_date,
                    description=f"Negative COGS adjustment for {obligation.warehouse_check.number}",
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
