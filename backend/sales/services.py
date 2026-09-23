"""Phase 8.1 commercial Sales core: no accounting or inventory effects."""

import hashlib
import json
from datetime import date as date_class
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from core.dates import gregorian_to_jalali
from core.idempotency import DuplicateOperationError, IdempotencyRecord, idempotent_operation
from core.money import normalize_rate, quantize_half_up, to_decimal
from currencies.models import Currency
from documents.services import next_document_number
from fiscal_periods.services import assert_posting_date_open
from parties.models import Party
from parties.services import PartyValidationError, resolve_party
from products.models import Product
from products.services import ProductValidationError, resolve_product
from security.models import AuditAction
from security.services import record_audit_event
from uom.models import UnitOfMeasure
from uom.services import UOMValidationError, resolve_uom
from warehouses.services import WarehouseValidationError, resolve_warehouse

from .models import Sale, SaleLine, SaleStatus, SaleType


class SaleValidationError(ValueError):
    """Deterministic Sales-domain rejection."""


SALES_FINALIZE_OPERATION = "sales.finalize"
_UNSET = object()


def _actor(user):
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        raise SaleValidationError("Authorization required for sales operations.")
    return user


def _date(value, field):
    if isinstance(value, date_class):
        return value
    if isinstance(value, str):
        from django.utils.dateparse import parse_date
        parsed = parse_date(value)
        if parsed:
            return parsed
    raise SaleValidationError(f"{field} must be a date.")


def _money(value, field):
    try:
        result = quantize_half_up(to_decimal(value), 2)
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise SaleValidationError(f"{field} must be a valid amount.") from exc
    if result < 0:
        raise SaleValidationError(f"{field} cannot be negative.")
    return result


def _price(value):
    try:
        result = quantize_half_up(to_decimal(value), 4)
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise SaleValidationError("Unit price must be a valid amount.") from exc
    if result < 0:
        raise SaleValidationError("Unit price cannot be negative.")
    return result


def _quantity(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SaleValidationError("Quantity must be a positive integer.")
    return value


def _resolve_customer(ref):
    try:
        party = resolve_party(ref)
    except PartyValidationError as exc:
        raise SaleValidationError(str(exc)) from exc
    if not party.is_customer:
        raise SaleValidationError("Party is not a customer.")
    if not party.is_active:
        raise SaleValidationError("Customer is not active.")
    return party


def _resolve_product(ref):
    try:
        product = resolve_product(ref)
    except ProductValidationError as exc:
        raise SaleValidationError(str(exc)) from exc
    if not product.is_active:
        raise SaleValidationError("Product is not active.")
    return product


def _resolve_warehouse(ref):
    try:
        warehouse = resolve_warehouse(ref)
    except WarehouseValidationError as exc:
        raise SaleValidationError(str(exc)) from exc
    if not warehouse.is_active:
        raise SaleValidationError("Warehouse is not active.")
    return warehouse


def _resolve_unit(ref, product):
    try:
        unit = resolve_uom(ref)
    except UOMValidationError as exc:
        raise SaleValidationError(str(exc)) from exc
    if not unit.is_active:
        raise SaleValidationError("Unit is not active.")
    if unit.pk != product.primary_uom_id:
        raise SaleValidationError("Sales quantity must use the Product primary unit.")
    return unit


def _rate(currency, rate, rate_date, sale_date):
    if currency.is_base:
        if rate is not None and normalize_rate(to_decimal(rate)) != Decimal("1.0000"):
            raise SaleValidationError("A base-currency sale must use rate 1.")
        return Decimal("1.0000"), sale_date
    if rate is None:
        raise SaleValidationError("A foreign-currency sale requires an exchange rate.")
    try:
        value = normalize_rate(to_decimal(rate))
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise SaleValidationError("Exchange rate must be positive.") from exc
    if value <= 0 or rate_date is None:
        raise SaleValidationError("A positive exchange rate and rate date are required.")
    return value, _date(rate_date, "rate_date")


def _prepare_lines(lines):
    if not isinstance(lines, (list, tuple)) or not lines:
        raise SaleValidationError("A sale requires at least one line.")
    rows = []
    for item in lines:
        if not isinstance(item, dict):
            raise SaleValidationError("Each sale line must be an object.")
        product = _resolve_product(item.get("product"))
        warehouse = _resolve_warehouse(item.get("warehouse"))
        unit = _resolve_unit(item.get("unit", product.primary_uom_id), product)
        quantity = _quantity(item.get("quantity"))
        unit_price = _price(item.get("unit_price"))
        discount = _money(item.get("discount", 0), "Line discount")
        gross = quantize_half_up(unit_price * quantity, 2)
        if discount > gross:
            raise SaleValidationError("Line discount cannot exceed line value.")
        rows.append({
            "product": product, "warehouse": warehouse, "unit": unit,
            "quantity": quantity, "unit_price": unit_price,
            "discount": discount, "gross": gross, "net": gross - discount,
        })
    return rows


def _totals(rows):
    subtotal = sum((row["gross"] for row in rows), Decimal("0.00"))
    discount = sum((row["discount"] for row in rows), Decimal("0.00"))
    total = subtotal - discount
    return subtotal, discount, total


def _snapshot(sale):
    return {
        "id": sale.pk,
        "document_number": sale.document_number,
        "customer_id": sale.customer_id,
        "sale_date": sale.sale_date.isoformat(),
        "currency": sale.currency.code,
        "exchange_rate": str(sale.exchange_rate),
        "rate_date": sale.rate_date.isoformat(),
        "sale_type": sale.sale_type,
        "subtotal": str(sale.subtotal),
        "total_discount": str(sale.total_discount),
        "total": str(sale.total),
        "status": sale.status,
        "line_ids": list(sale.lines.values_list("id", flat=True)),
    }


def _line_input(line):
    return {
        "product": line.product,
        "warehouse": line.warehouse,
        "unit": line.unit,
        "quantity": line.quantity,
        "unit_price": line.unit_price,
        "discount": line.discount,
    }


def create_sale(*, customer, sale_date, currency, sale_type, lines,
                rate=None, rate_date=None, user=None, document_number=None):
    actor = _actor(user)
    customer = _resolve_customer(customer)
    sale_day = _date(sale_date, "sale_date")
    currency = _resolve_currency(currency)
    if not currency.is_active:
        raise SaleValidationError("Currency is not active.")
    try:
        sale_type = SaleType(sale_type)
    except ValueError as exc:
        raise SaleValidationError("Sale Type must be AVAILABLE or FUTURE.") from exc
    rate_value, rate_day = _rate(currency, rate, rate_date, sale_day)
    rows = _prepare_lines(lines)
    subtotal, discount, total = _totals(rows)
    if document_number is None:
        document_number = next_document_number("SI", int(gregorian_to_jalali(sale_day).split("/")[0]))
    if not isinstance(document_number, str) or not document_number.strip():
        raise SaleValidationError("Document number is required.")
    with transaction.atomic():
        sale = Sale.objects.create(
            document_number=document_number.strip(), customer=customer,
            sale_date=sale_day, currency=currency, exchange_rate=rate_value,
            rate_date=rate_day, sale_type=sale_type.value,
            subtotal=subtotal, total_discount=discount, total=total,
            status=SaleStatus.DRAFT, created_by=actor,
        )
        for row in rows:
            SaleLine.objects.create(
                sale=sale, product=row["product"], warehouse=row["warehouse"],
                unit=row["unit"], quantity=row["quantity"],
                unit_price=row["unit_price"], discount=row["discount"],
                line_total=row["gross"], net_total=row["net"],
            )
        record_audit_event(user=actor, action=AuditAction.CREATE, entity="Sale",
                           entity_id=sale.pk, reference=sale.document_number,
                           previous_state=None, new_state=_snapshot(sale), reason="")
    return sale


def _resolve_currency(ref):
    if isinstance(ref, Currency):
        if ref.pk is None:
            raise SaleValidationError("Currency does not exist.")
        return ref
    if isinstance(ref, str) and ref:
        found = Currency.objects.filter(code=ref).first()
        if found:
            return found
    try:
        found = Currency.objects.filter(pk=ref).first()
    except (TypeError, ValueError):
        found = None
    if found is None:
        raise SaleValidationError("Currency does not exist.")
    return found


def _sale_or_error(sale):
    if isinstance(sale, Sale):
        if sale.pk is None:
            raise SaleValidationError("Sale does not exist.")
        return sale
    try:
        return Sale.objects.get(pk=sale)
    except (Sale.DoesNotExist, ValueError, TypeError) as exc:
        raise SaleValidationError("Sale does not exist.") from exc


def update_sale(sale, *, customer=_UNSET, sale_date=_UNSET, currency=_UNSET,
                sale_type=_UNSET, rate=_UNSET, rate_date=_UNSET,
                lines=_UNSET, user=None):
    actor = _actor(user)
    current = _sale_or_error(sale)
    with transaction.atomic():
        current = Sale.objects.select_for_update().get(pk=current.pk)
        if current.status != SaleStatus.DRAFT:
            raise SaleValidationError("Only a draft sale can be edited.")
        old_state = _snapshot(current)
        customer = current.customer if customer is _UNSET else _resolve_customer(customer)
        sale_day = current.sale_date if sale_date is _UNSET else _date(sale_date, "sale_date")
        currency = current.currency if currency is _UNSET else _resolve_currency(currency)
        if not currency.is_active:
            raise SaleValidationError("Currency is not active.")
        type_value = current.sale_type if sale_type is _UNSET else sale_type
        try:
            type_value = SaleType(type_value).value
        except ValueError as exc:
            raise SaleValidationError("Sale Type must be AVAILABLE or FUTURE.") from exc
        rate_input = current.exchange_rate if rate is _UNSET else rate
        rate_day_input = current.rate_date if rate_date is _UNSET else rate_date
        rate_value, rate_day = _rate(currency, rate_input, rate_day_input, sale_day)
        if lines is _UNSET:
            lines = [_line_input(line) for line in current.lines.select_related("product", "warehouse", "unit").order_by("id")]
        rows = _prepare_lines(lines)
        subtotal, discount, total = _totals(rows)
        current.customer = customer
        current.sale_date = sale_day
        current.currency = currency
        current.exchange_rate = rate_value
        current.rate_date = rate_day
        current.sale_type = type_value
        current.subtotal = subtotal
        current.total_discount = discount
        current.total = total
        current.save(update_fields=["customer", "sale_date", "currency", "exchange_rate",
                                    "rate_date", "sale_type", "subtotal", "total_discount", "total"])
        current.lines.all().delete()
        for row in rows:
            SaleLine.objects.create(
                sale=current, product=row["product"], warehouse=row["warehouse"],
                unit=row["unit"], quantity=row["quantity"], unit_price=row["unit_price"],
                discount=row["discount"], line_total=row["gross"], net_total=row["net"],
            )
        record_audit_event(user=actor, action=AuditAction.UPDATE, entity="Sale",
                           entity_id=current.pk, reference=current.document_number,
                           previous_state=old_state, new_state=_snapshot(current), reason="")
        return current


def update_sale_line(line, *, product=_UNSET, warehouse=_UNSET, unit=_UNSET,
                     quantity=_UNSET, unit_price=_UNSET, discount=_UNSET, user=None):
    try:
        current_line = line if isinstance(line, SaleLine) else SaleLine.objects.select_related("sale").get(pk=line)
    except SaleLine.DoesNotExist as exc:
        raise SaleValidationError("Sale line does not exist.") from exc
    sale = current_line.sale
    rows = []
    for item in sale.lines.select_related("product", "warehouse", "unit").order_by("id"):
        rows.append({
            "product": item.product if item.pk != current_line.pk or product is _UNSET else product,
            "warehouse": item.warehouse if item.pk != current_line.pk or warehouse is _UNSET else warehouse,
            "unit": item.unit if item.pk != current_line.pk or unit is _UNSET else unit,
            "quantity": item.quantity if item.pk != current_line.pk or quantity is _UNSET else quantity,
            "unit_price": item.unit_price if item.pk != current_line.pk or unit_price is _UNSET else unit_price,
            "discount": item.discount if item.pk != current_line.pk or discount is _UNSET else discount,
        })
    return update_sale(sale, lines=rows, user=user)


def validate_sale(sale):
    sale = _sale_or_error(sale)
    if sale.status != SaleStatus.DRAFT:
        raise SaleValidationError("Only a draft sale can be finalized.")
    customer = _resolve_customer(sale.customer)
    currency = _resolve_currency(sale.currency)
    if not currency.is_active:
        raise SaleValidationError("Currency is not active.")
    _rate(currency, sale.exchange_rate, sale.rate_date, sale.sale_date)
    if sale.sale_type not in SaleType.values:
        raise SaleValidationError("Sale Type must be AVAILABLE or FUTURE.")
    lines = list(sale.lines.select_related("product", "warehouse", "unit").order_by("id"))
    if not lines:
        raise SaleValidationError("A sale requires at least one line.")
    rows = []
    for line in lines:
        product = _resolve_product(line.product)
        warehouse = _resolve_warehouse(line.warehouse)
        unit = _resolve_unit(line.unit, product)
        quantity = _quantity(line.quantity)
        unit_price = _price(line.unit_price)
        discount = _money(line.discount, "Line discount")
        gross = quantize_half_up(unit_price * quantity, 2)
        if discount > gross:
            raise SaleValidationError("Line discount cannot exceed line value.")
        if line.line_total != gross or line.net_total != gross - discount:
            raise SaleValidationError("Sale line totals are inconsistent.")
        rows.append({"gross": gross, "discount": discount})
    subtotal, discount, total = _totals(rows)
    if sale.subtotal != subtotal or sale.total_discount != discount or sale.total != total:
        raise SaleValidationError("Sale totals are inconsistent.")
    return sale


def _fingerprint(sale):
    payload = {
        "sale_id": sale.pk, "document_number": sale.document_number,
        "customer_id": sale.customer_id, "sale_date": sale.sale_date.isoformat(),
        "currency_id": sale.currency_id, "exchange_rate": str(sale.exchange_rate),
        "rate_date": sale.rate_date.isoformat(), "sale_type": sale.sale_type,
        "subtotal": str(sale.subtotal), "total_discount": str(sale.total_discount),
        "total": str(sale.total),
        "lines": list(sale.lines.values("product_id", "warehouse_id", "unit_id",
                                        "quantity", "unit_price", "discount", "line_total", "net_total")),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _finalize_effects(sale, actor):
    with transaction.atomic():
        current = Sale.objects.select_for_update().get(pk=sale.pk)
        if current.status == SaleStatus.FINALIZED:
            return current
        validate_sale(current)
        assert_posting_date_open(current.sale_date)
        previous = _snapshot(current)
        current.status = SaleStatus.FINALIZED
        current.finalized_at = timezone.now()
        current.save(update_fields=["status", "finalized_at"])
        record_audit_event(user=actor, action=AuditAction.APPROVE, entity="Sale",
                           entity_id=current.pk, reference=current.document_number,
                           previous_state=previous, new_state=_snapshot(current),
                           reason="Commercial Sale finalization")
        return current


def _existing_retry(key, fingerprint):
    record = IdempotencyRecord.objects.get(key=key)
    body = record.response_body or {}
    if body.get("fingerprint") != fingerprint:
        raise SaleValidationError("This idempotency key was used for a different sale.")
    return Sale.objects.get(pk=body["sale_id"])


def finalize_sale(*, sale, user=None, idempotency_key=None):
    actor = _actor(user)
    sale = _sale_or_error(sale)
    fingerprint = _fingerprint(sale)
    if idempotency_key is None:
        return _finalize_effects(sale, actor)
    try:
        with idempotent_operation(key=idempotency_key, operation=SALES_FINALIZE_OPERATION) as record:
            result = _finalize_effects(sale, actor)
            record.response_body = {"sale_id": result.pk, "fingerprint": fingerprint}
            record.save(update_fields=["response_body"])
            return result
    except DuplicateOperationError:
        if IdempotencyRecord.objects.filter(key=idempotency_key).exists():
            return _existing_retry(idempotency_key, fingerprint)
        raise
