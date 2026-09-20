"""Phase 7.1 purchase foundation and atomic purchase receipt posting."""

import hashlib
import json
from datetime import date as date_class
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from accounting.coa import CANONICAL_COA
from accounting.models import Account
from accounting.services import JournalValidationError, post_journal
from core.dates import gregorian_to_jalali
from core.idempotency import DuplicateOperationError, IdempotencyRecord, idempotent_operation
from core.money import normalize_rate, quantize_half_up, to_decimal
from currencies.models import Currency
from documents.services import next_document_number
from fiscal_periods.services import assert_posting_date_open
from inventory.services import InventoryValidationError, receive_stock, resolve_currency
from inventory.stock import stock_for
from party_ledger.services import attribute_journal_line
from parties.models import Party
from parties.services import PartyValidationError, resolve_party
from products.models import Product
from products.services import ProductValidationError, resolve_product
from security.models import AuditAction
from security.services import record_audit_event
from warehouses.models import Warehouse
from warehouses.services import WarehouseValidationError, resolve_warehouse

from .models import Purchase, PurchaseLine, PurchaseStatus


class PurchaseValidationError(ValueError):
    """Deterministic purchase-domain rejection."""


PURCHASE_POST_OPERATION = "purchase.post"
FREIGHT_ACCOUNT = "6200"
PAYABLE_ACCOUNT = "2110"


def _actor(user):
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        raise PurchaseValidationError("Authorization required for purchase operations.")
    return user


def _date(value, field):
    if isinstance(value, date_class):
        return value
    if isinstance(value, str):
        from django.utils.dateparse import parse_date
        parsed = parse_date(value)
        if parsed:
            return parsed
    raise PurchaseValidationError(f"{field} must be a date.")


def _money(value, field):
    try:
        result = quantize_half_up(to_decimal(value), 2)
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise PurchaseValidationError(f"{field} must be a valid amount.") from exc
    if result < 0:
        raise PurchaseValidationError(f"{field} cannot be negative.")
    return result


def _price(value):
    try:
        result = quantize_half_up(to_decimal(value), 4)
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise PurchaseValidationError("Unit price must be a valid amount.") from exc
    if result < 0:
        raise PurchaseValidationError("Unit price cannot be negative.")
    return result


def _quantity(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PurchaseValidationError("Quantity must be a positive integer.")
    return value


def _resolve_supplier(ref):
    try:
        party = resolve_party(ref)
    except PartyValidationError as exc:
        raise PurchaseValidationError(str(exc)) from exc
    if not party.is_supplier:
        raise PurchaseValidationError("Party is not a supplier.")
    if not party.is_active:
        raise PurchaseValidationError("Supplier is not active.")
    return party


def _resolve_product(ref):
    try:
        product = resolve_product(ref)
    except ProductValidationError as exc:
        raise PurchaseValidationError(str(exc)) from exc
    if not product.is_active:
        raise PurchaseValidationError("Product is not active.")
    return product


def _resolve_warehouse(ref):
    try:
        warehouse = resolve_warehouse(ref)
    except WarehouseValidationError as exc:
        raise PurchaseValidationError(str(exc)) from exc
    if not warehouse.is_active:
        raise PurchaseValidationError("Warehouse is not active.")
    return warehouse


def _rate(currency, rate, rate_date, purchase_date):
    if currency.is_base:
        if rate is not None and normalize_rate(to_decimal(rate)) != Decimal("1.0000"):
            raise PurchaseValidationError("A base-currency purchase must use rate 1.")
        return Decimal("1.0000"), purchase_date
    if rate is None:
        raise PurchaseValidationError("A foreign-currency purchase requires an exchange rate.")
    try:
        value = normalize_rate(to_decimal(rate))
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise PurchaseValidationError("Exchange rate must be positive.") from exc
    if value <= 0 or rate_date is None:
        raise PurchaseValidationError("A positive exchange rate and rate date are required.")
    return value, _date(rate_date, "rate_date")


def _allocate(lines, discount):
    gross = sum((row["gross"] for row in lines), Decimal("0.00"))
    if discount > gross:
        raise PurchaseValidationError("Discount cannot exceed gross purchase value.")
    allocated = Decimal("0.00")
    for index, row in enumerate(lines):
        if index == len(lines) - 1:
            share = discount - allocated
        elif gross == 0:
            share = Decimal("0.00")
        else:
            share = quantize_half_up(discount * row["gross"] / gross, 2)
        allocated += share
        row["discount"] = share
        row["net"] = row["gross"] - share
    return gross


def _snapshot(purchase):
    return {
        "id": purchase.pk,
        "document_number": purchase.document_number,
        "supplier_id": purchase.supplier_id,
        "warehouse_id": purchase.warehouse_id,
        "currency": purchase.currency.code,
        "purchase_date": purchase.purchase_date.isoformat(),
        "subtotal": str(purchase.subtotal),
        "discount": str(purchase.discount),
        "freight": str(purchase.freight),
        "total": str(purchase.total),
        "status": purchase.status,
        "line_ids": list(purchase.lines.values_list("id", flat=True)),
    }


def _prepare_lines(lines):
    if not isinstance(lines, (list, tuple)) or not lines:
        raise PurchaseValidationError("A purchase requires at least one line.")
    rows = []
    for item in lines:
        if not isinstance(item, dict):
            raise PurchaseValidationError("Each purchase line must be an object.")
        product = _resolve_product(item.get("product"))
        quantity = _quantity(item.get("quantity"))
        unit_price = _price(item.get("unit_price"))
        rows.append({"product": product, "quantity": quantity, "unit_price": unit_price,
                     "gross": quantize_half_up(unit_price * quantity, 2)})
    return rows


def _totals(rows, discount, freight):
    discount = _money(discount, "Discount")
    freight = _money(freight, "Freight")
    subtotal = sum((row["gross"] for row in rows), Decimal("0.00"))
    _allocate(rows, discount)
    return subtotal, discount, freight, subtotal - discount + freight


def create_purchase(*, supplier, purchase_date, currency, warehouse, lines,
                    discount=0, freight=0, rate=None, rate_date=None,
                    description="", user=None, document_number=None):
    actor = _actor(user)
    supplier = _resolve_supplier(supplier)
    warehouse = _resolve_warehouse(warehouse)
    purchase_day = _date(purchase_date, "purchase_date")
    currency = resolve_currency(currency)
    if not currency.is_active:
        raise PurchaseValidationError("Currency is not active.")
    rate_value, rate_day = _rate(currency, rate, rate_date, purchase_day)
    rows = _prepare_lines(lines)
    subtotal, discount, freight, total = _totals(rows, discount, freight)
    if document_number is None:
        document_number = next_document_number("PI", int(gregorian_to_jalali(purchase_day).split("/")[0]))
    if not isinstance(document_number, str) or not document_number.strip():
        raise PurchaseValidationError("Document number is required.")
    with transaction.atomic():
        purchase = Purchase.objects.create(
            document_number=document_number.strip(), supplier=supplier,
            purchase_date=purchase_day, currency=currency, exchange_rate=rate_value,
            rate_date=rate_day, warehouse=warehouse, description=str(description).strip(),
            subtotal=subtotal, discount=discount, freight=freight, total=total,
            status=PurchaseStatus.DRAFT, created_by=actor,
        )
        for row in rows:
            PurchaseLine.objects.create(
                purchase=purchase, product=row["product"], quantity=row["quantity"],
                unit_price=row["unit_price"], line_total=row["gross"],
                discount_allocated=row["discount"], net_total=row["net"],
            )
        record_audit_event(user=actor, action=AuditAction.CREATE, entity="Purchase",
                           entity_id=purchase.pk, reference=purchase.document_number,
                           previous_state=None, new_state=_snapshot(purchase), reason="")
    return purchase


_UNSET = object()


def update_purchase(purchase, *, supplier=_UNSET, purchase_date=_UNSET, currency=_UNSET,
                    warehouse=_UNSET, description=_UNSET, discount=_UNSET, freight=_UNSET,
                    rate=_UNSET, rate_date=_UNSET, lines=_UNSET, user=None):
    """Edit a commercial Purchase only while it is DRAFT and recalculate its totals."""
    actor = _actor(user)
    try:
        purchase_id = purchase.pk if isinstance(purchase, Purchase) else purchase
        with transaction.atomic():
            current = Purchase.objects.select_for_update().get(pk=purchase_id)
            if current.status != PurchaseStatus.DRAFT:
                raise PurchaseValidationError("Only a draft purchase can be edited.")
            old_state = _snapshot(current)
            supplier = current.supplier if supplier is _UNSET else _resolve_supplier(supplier)
            warehouse = current.warehouse if warehouse is _UNSET else _resolve_warehouse(warehouse)
            purchase_day = current.purchase_date if purchase_date is _UNSET else _date(purchase_date, "purchase_date")
            currency = current.currency if currency is _UNSET else resolve_currency(currency)
            if not currency.is_active:
                raise PurchaseValidationError("Currency is not active.")
            rate_input = current.exchange_rate if rate is _UNSET else rate
            rate_date_input = current.rate_date if rate_date is _UNSET else rate_date
            rate_value, rate_day = _rate(currency, rate_input, rate_date_input, purchase_day)
            new_discount = current.discount if discount is _UNSET else discount
            new_freight = current.freight if freight is _UNSET else freight
            if lines is _UNSET:
                lines = list(current.lines.order_by("id").values("product", "quantity", "unit_price"))
                lines = [{**row, "product": row["product"]} for row in lines]
            rows = _prepare_lines(lines)
            subtotal, new_discount, new_freight, total = _totals(rows, new_discount, new_freight)
            current.supplier = supplier
            current.purchase_date = purchase_day
            current.currency = currency
            current.exchange_rate = rate_value
            current.rate_date = rate_day
            current.warehouse = warehouse
            current.description = current.description if description is _UNSET else str(description).strip()
            current.subtotal = subtotal
            current.discount = new_discount
            current.freight = new_freight
            current.total = total
            current.save(update_fields=["supplier", "purchase_date", "currency", "exchange_rate",
                                        "rate_date", "warehouse", "description", "subtotal",
                                        "discount", "freight", "total"])
            current.lines.all().delete()
            for row in rows:
                PurchaseLine.objects.create(
                    purchase=current, product=row["product"], quantity=row["quantity"],
                    unit_price=row["unit_price"], line_total=row["gross"],
                    discount_allocated=row["discount"], net_total=row["net"],
                )
            record_audit_event(user=actor, action=AuditAction.UPDATE, entity="Purchase",
                               entity_id=current.pk, reference=current.document_number,
                               previous_state=old_state, new_state=_snapshot(current), reason="")
            return current
    except Purchase.DoesNotExist as exc:
        raise PurchaseValidationError("Purchase does not exist.") from exc


def update_purchase_line(line, *, product=_UNSET, quantity=_UNSET, unit_price=_UNSET, user=None):
    """Edit one draft line through the Purchase recalculation boundary."""
    try:
        current = line if isinstance(line, PurchaseLine) else PurchaseLine.objects.get(pk=line)
    except PurchaseLine.DoesNotExist as exc:
        raise PurchaseValidationError("Purchase line does not exist.") from exc
    purchase = current.purchase
    rows = []
    for item in purchase.lines.order_by("id"):
        rows.append({
            "product": item.product if item.pk != current.pk or product is _UNSET else product,
            "quantity": item.quantity if item.pk != current.pk or quantity is _UNSET else quantity,
            "unit_price": item.unit_price if item.pk != current.pk or unit_price is _UNSET else unit_price,
        })
    return update_purchase(purchase, lines=rows, user=user)


def validate_purchase(purchase):
    """Revalidate the complete draft immediately before posting."""
    if not isinstance(purchase, Purchase) or purchase.pk is None:
        raise PurchaseValidationError("A persisted Purchase is required.")
    _resolve_supplier(purchase.supplier)
    _resolve_warehouse(purchase.warehouse)
    currency = resolve_currency(purchase.currency)
    if not currency.is_active:
        raise PurchaseValidationError("Currency is not active.")
    _rate(currency, purchase.exchange_rate, purchase.rate_date, purchase.purchase_date)
    if not isinstance(purchase.description, str):
        raise PurchaseValidationError("Description must be text.")
    lines = list(purchase.lines.select_related("product").order_by("id"))
    if not lines:
        raise PurchaseValidationError("A purchase requires at least one line.")
    rows = []
    for line in lines:
        product = _resolve_product(line.product)
        quantity = _quantity(line.quantity)
        unit_price = _price(line.unit_price)
        gross = quantize_half_up(unit_price * quantity, 2)
        if line.line_total != gross:
            raise PurchaseValidationError("Purchase line total is inconsistent.")
        rows.append({"product": product, "quantity": quantity, "unit_price": unit_price, "gross": gross})
    discount = _money(purchase.discount, "Discount")
    freight = _money(purchase.freight, "Freight")
    subtotal = sum((row["gross"] for row in rows), Decimal("0.00"))
    _allocate(rows, discount)
    for row, line in zip(rows, lines):
        if line.discount_allocated != row["discount"] or line.net_total != row["net"]:
            raise PurchaseValidationError("Purchase line discount allocation is inconsistent.")
    total = subtotal - discount + freight
    if purchase.subtotal != subtotal or purchase.total != total:
        raise PurchaseValidationError("Purchase totals are inconsistent.")
    return purchase


def _fingerprint(purchase):
    payload = {
        "purchase_id": purchase.pk, "document_number": purchase.document_number,
        "status": purchase.status, "supplier_id": purchase.supplier_id,
        "purchase_date": purchase.purchase_date.isoformat(), "currency_id": purchase.currency_id,
        "rate": str(purchase.exchange_rate), "rate_date": purchase.rate_date.isoformat(),
        "warehouse_id": purchase.warehouse_id, "discount": str(purchase.discount),
        "freight": str(purchase.freight), "description": purchase.description,
        "lines": list(purchase.lines.values("product_id", "quantity", "unit_price", "net_total")),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _existing_retry(key, fingerprint):
    record = IdempotencyRecord.objects.get(key=key)
    body = record.response_body or {}
    if body.get("fingerprint") != fingerprint:
        raise PurchaseValidationError("This idempotency key was used for a different purchase.")
    purchase_id = body.get("purchase_id")
    if not purchase_id:
        raise DuplicateOperationError("Original purchase is still in progress; retry.")
    return Purchase.objects.get(pk=purchase_id)


@transaction.atomic
def _post_effects(purchase, actor, idempotency_key):
    purchase = Purchase.objects.select_for_update().select_related("supplier", "currency", "warehouse").get(pk=purchase.pk)
    if purchase.status == PurchaseStatus.POSTED:
        return purchase
    if purchase.status != PurchaseStatus.DRAFT:
        raise PurchaseValidationError("Only a draft purchase can be posted.")
    validate_purchase(purchase)
    assert_posting_date_open(purchase.purchase_date)
    inventory_account = Account.objects.filter(code__in=["1410", "1420"]).first()
    from inventory.services import resolve_warehouse_account
    inventory_account = resolve_warehouse_account(purchase.warehouse)
    payable = Account.objects.get(code=PAYABLE_ACCOUNT)
    freight_account = Account.objects.get(code=FREIGHT_ACCOUNT)
    journal_lines = [{"account": inventory_account, "debit": purchase.subtotal - purchase.discount,
                      "description": f"Inventory receipt {purchase.document_number}", "reference": purchase.document_number},
                     {"account": payable, "credit": purchase.total,
                      "description": f"Supplier payable {purchase.document_number}", "reference": purchase.document_number}]
    if purchase.freight:
        journal_lines.insert(1, {"account": freight_account, "debit": purchase.freight,
                                 "description": f"Freight {purchase.document_number}", "reference": purchase.document_number})
    journal = post_journal(
        number=next_document_number("JE", int(gregorian_to_jalali(purchase.purchase_date).split("/")[0])),
        posting_date=purchase.purchase_date, description=purchase.description or f"Purchase {purchase.document_number}",
        lines=journal_lines, source_type="PURCHASE", source_id=purchase.document_number,
        currency=purchase.currency, rate=purchase.exchange_rate, rate_date=purchase.rate_date,
        created_by=actor, idempotency_key=f"{idempotency_key}:journal" if idempotency_key else None,
    )
    payable_line = journal.lines.get(account__code=PAYABLE_ACCOUNT)
    attribute_journal_line(payable_line, party=purchase.supplier, user=actor)
    movement_ids = []
    movement_references = []
    for line in purchase.lines.select_related("product"):
        unit_cost = quantize_half_up(line.net_total / Decimal(line.quantity), 4)
        movement_reference = f"{purchase.document_number}:LINE:{line.pk}"
        movement = receive_stock(product=line.product, warehouse=purchase.warehouse, quantity=line.quantity,
                                 unit_cost=unit_cost, currency=purchase.currency,
                                 rate=purchase.exchange_rate, rate_date=purchase.rate_date,
                                 movement_date=purchase.purchase_date, reference=movement_reference,
                                 description=purchase.description, user=actor, party=purchase.supplier,
                                 idempotency_key=f"{purchase.document_number}:line:{line.pk}")
        movement_ids.append(movement.pk)
        movement_references.append(movement.reference)
    previous = _snapshot(purchase)
    purchase.status = PurchaseStatus.POSTED
    purchase.posted_at = timezone.now()
    purchase.save(update_fields=["status", "posted_at", "created_at"])
    posted_state = _snapshot(purchase)
    posted_state.update({
        "journal_entry_id": journal.pk,
        "journal_number": journal.number,
        "stock_movement_ids": movement_ids,
        "stock_movement_references": movement_references,
    })
    record_audit_event(user=actor, action=AuditAction.POST, entity="Purchase", entity_id=purchase.pk,
                       reference=purchase.document_number, previous_state=previous,
                       new_state=posted_state, reason="")
    return purchase


def post_purchase(*, purchase, user=None, idempotency_key=None):
    actor = _actor(user)
    if not isinstance(purchase, Purchase):
        try:
            purchase = Purchase.objects.get(pk=purchase)
        except Purchase.DoesNotExist as exc:
            raise PurchaseValidationError("Purchase does not exist.") from exc
    fingerprint = _fingerprint(purchase)
    if idempotency_key is None:
        return _post_effects(purchase, actor, None)
    try:
        with idempotent_operation(key=idempotency_key, operation=PURCHASE_POST_OPERATION) as record:
            with transaction.atomic():
                result = _post_effects(purchase, actor, idempotency_key)
                record.response_body = {"purchase_id": result.pk, "fingerprint": fingerprint}
                record.save(update_fields=["response_body"])
                return result
    except DuplicateOperationError:
        if IdempotencyRecord.objects.filter(key=idempotency_key).exists():
            return _existing_retry(idempotency_key, fingerprint)
        raise
