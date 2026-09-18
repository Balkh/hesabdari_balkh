"""Inventory foundation services (Phase 6.1).

Posting primitives (6.1 §1/§12/§15/§18; transfer added Stage 6.3):

- ``receive_stock``: movement-only receipt at an authoritative unit cost
  supplied by the caller (the future Purchase domain owns cost
  aggregation and its journals). No journal is posted here.
- ``issue_stock``: movement-only issue at running AVCO, or at a manually
  entered temporary cost when the issue drives stock negative. The
  negative-stock warning is enforced at this service boundary via the
  required ``acknowledge_negative`` flag. No COGS journal here (Sales
  owns it later).
- ``open_stock``: opening movement + its Dr Inventory / Cr 3900 journal
  through the frozen pipeline, atomically (mirror of
  ``open_party_balance``).
- ``transfer_stock`` (Stage 6.3): TRANSFER_OUT + TRANSFER_IN pair at the
  preserved cost basis plus the neutral Dr-dest/Cr-source reclass
  journal, atomically and idempotently as one operation.
- Stage 6.4: ``adjust_stock_in`` / ``adjust_stock_out`` (ADJUSTMENT_IN /
  OUT), ``receive_with_waste`` (usable receipt + waste annotation),
  ``record_shortage`` (SHORTAGE leg), ``settle_shortage`` (manual-rate
  compensation record). No journals: no approved adjustment mapping
  exists, so accounting is explicitly deferred, never invented.

Plus the explicit Warehouse → Inventory GL mapping (§19):
``assign_warehouse_account`` / ``resolve_warehouse_account``.

Everything else is reused, never duplicated: posting, money/rounding,
currency, audit, idempotency, period gate, numbering (§24–§29).
"""

import hashlib
from datetime import date as date_class
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum

from accounting.models import Account
from accounting.services import _as_date, post_journal
from core.dates import gregorian_to_jalali
from core.idempotency import DuplicateOperationError, idempotent_operation
from core.models import IdempotencyRecord
from core.money import line_total, normalize_rate, quantize_half_up, to_decimal
from currencies.models import Currency
from documents.services import next_document_number
from fiscal_periods.services import assert_posting_date_open
from products.services import ProductValidationError
from products.services import resolve_product as _resolve_product_frozen
from security.models import AuditAction
from security.services import record_audit_event
from warehouses.services import WarehouseValidationError
from warehouses.services import resolve_warehouse as _resolve_warehouse_frozen

from .models import (
    INVENTORY_MOVEMENT_OPERATION,
    INVENTORY_TRANSFER_OPERATION,
    SHORTAGE_SETTLEMENT_OPERATION,
    PURCHASE_RETURN_OPERATION,
    SALES_RETURN_OPERATION,
    INVENTORY_ROOT_CODE,
    OPENING_EQUITY_ACCOUNT,
    OPENING_SOURCE_TYPE,
    TRANSFER_SOURCE_TYPE,
    MovementType,
    ShortageSettlement,
    InventoryReturn,
    StockMovement,
    WarehouseInventoryAccount,
)
from .stock import avco_for, stock_for


class InventoryValidationError(ValueError):
    """Deterministic inventory rejection (service-error convention)."""


def _require_actor(user, action):
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        raise InventoryValidationError(
            f"Authorization required to {action}: user must be a user."
        )
    return user


def resolve_product(ref):
    """Resolve via the frozen Product resolver; translate the domain error."""
    try:
        return _resolve_product_frozen(ref)
    except ProductValidationError as exc:
        raise InventoryValidationError(str(exc)) from exc


def resolve_warehouse(ref):
    """Resolve via the frozen Warehouse resolver; translate the domain error."""
    try:
        return _resolve_warehouse_frozen(ref)
    except WarehouseValidationError as exc:
        raise InventoryValidationError(str(exc)) from exc


def resolve_currency(ref):
    """Accept a Currency instance or exact code; deterministic miss error.

    Minimal local resolver (same shape as party_ledger's): a Currency
    resolver exists in no shared layer, and importing a peer domain's
    service for it would couple the two domains.
    """
    if isinstance(ref, Currency):
        if ref.pk is None:
            raise InventoryValidationError("Currency does not exist.")
        return ref
    if isinstance(ref, str) and ref:
        found = Currency.objects.filter(code=ref).first()
        if found is not None:
            return found
    raise InventoryValidationError("Currency does not exist.")


def _base_currency():
    base = Currency.objects.filter(is_base=True).first()
    if base is None:
        raise InventoryValidationError("No base currency is configured.")
    return base


def _require_usable_account(ref):
    if isinstance(ref, Account):
        if ref.pk is None:
            raise InventoryValidationError("Account does not exist.")
        account = ref
    elif isinstance(ref, str) and ref:
        account = Account.objects.filter(code=ref).first()
        if account is None:
            raise InventoryValidationError(
                f"Account {ref} does not exist; seed the canonical COA."
            )
    else:
        raise InventoryValidationError("Account does not exist.")
    if not account.is_active or not account.is_posting:
        raise InventoryValidationError(
            f"Account {account.code} is not usable for posting."
        )
    return account


def _is_under_inventory_root(account):
    node = account
    seen = set()
    while node is not None and node.pk not in seen:
        if node.code == INVENTORY_ROOT_CODE:
            return True
        seen.add(node.pk)
        node = node.parent
    return False


def assign_warehouse_account(*, warehouse, account, user=None):
    """Map one Warehouse to its Inventory GL account (§19), audited.

    The mapped account must be posting/active under 1400. Remapping is
    allowed: it changes only FUTURE postings, never history.
    Re-assigning the same account is an idempotent no-op (no audit row).
    """
    actor = _require_actor(user, "assign warehouse inventory account")
    resolved_warehouse = resolve_warehouse(warehouse)
    resolved_account = _require_usable_account(account)
    if not _is_under_inventory_root(resolved_account):
        raise InventoryValidationError(
            f"Account {resolved_account.code} is not an Inventory "
            f"account under {INVENTORY_ROOT_CODE}."
        )
    with transaction.atomic():
        mapping, created = WarehouseInventoryAccount.objects.get_or_create(
            warehouse=resolved_warehouse,
            defaults={"account": resolved_account},
        )
        if not created and mapping.account_id == resolved_account.pk:
            return mapping  # idempotent no-op, no audit row
        previous = None
        if not created:
            previous = {"account_code": mapping.account.code}
            mapping.account = resolved_account
            mapping.save(update_fields=["account"])
        record_audit_event(
            user=actor,
            action=AuditAction.CREATE if created else AuditAction.UPDATE,
            entity="WarehouseInventoryAccount",
            entity_id=mapping.id,
            reference=resolved_warehouse.name,
            previous_state=previous,
            new_state={
                "warehouse_id": resolved_warehouse.pk,
                "account_code": resolved_account.code,
            },
            reason="",
        )
    return mapping


def resolve_warehouse_account(warehouse):
    """Return the mapped, still-usable Inventory GL account, or reject loudly.

    Always read fresh from the database: the reverse OneToOne accessor
    caches on the instance, which would serve a stale account after a
    remap within the same process.
    """
    resolved_warehouse = resolve_warehouse(warehouse)
    mapping = WarehouseInventoryAccount.objects.filter(
        warehouse=resolved_warehouse
    ).select_related("account").first()
    if mapping is None:
        raise InventoryValidationError(
            f"No inventory GL account is mapped to warehouse "
            f"'{resolved_warehouse.name}'; map one before posting."
        )
    return _require_usable_account(mapping.account)


def _coerce_units(value, *, what, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, int):
        raise InventoryValidationError(
            f"{what} must be an integer count of units."
        )
    if value < 0 or (value == 0 and not allow_zero):
        raise InventoryValidationError(
            f"{what} must be a positive integer." if not allow_zero else
            f"{what} must be a non-negative integer."
        )
    return value


def _coerce_unit_cost(value):
    try:
        cost = quantize_half_up(to_decimal(value), 4)
    except (InvalidOperation, ValueError, TypeError, ArithmeticError) as exc:
        raise InventoryValidationError(
            "Unit cost must be a non-negative number."
        ) from exc
    if cost < 0:
        raise InventoryValidationError("Unit cost must be a non-negative number.")
    return cost


def _coerce_rate(currency, rate):
    if currency.is_base:
        if rate is None:
            return Decimal("1.0000")
        try:
            given = normalize_rate(to_decimal(rate))
        except (InvalidOperation, ValueError, TypeError, ArithmeticError) as exc:
            raise InventoryValidationError(
                "Rate must be a positive number."
            ) from exc
        if given != 1:
            raise InventoryValidationError(
                "A base-currency movement must use rate 1."
            )
        return Decimal("1.0000")
    if rate is None:
        raise InventoryValidationError(
            "A rate is required for a foreign-currency movement."
        )
    try:
        value = normalize_rate(to_decimal(rate))
    except (InvalidOperation, ValueError, TypeError, ArithmeticError) as exc:
        raise InventoryValidationError(
            "Rate must be a positive number."
        ) from exc
    if value <= 0:
        raise InventoryValidationError("Rate must be a positive number.")
    return value


def _coerce_rate_date(currency, rate_date, movement_day):
    if currency.is_base:
        return movement_day
    if rate_date is None:
        raise InventoryValidationError(
            "rate_date is required for a foreign-currency movement."
        )
    return _as_date(rate_date, "rate_date")


def _clean_reference(reference):
    if not isinstance(reference, str) or not reference.strip():
        raise InventoryValidationError("A movement reference is required.")
    return reference.strip()


# Free-form transaction annotation (Stage 6.2 §7/§11). The service
# enforces the length so SQLite and PostgreSQL behave identically.
DESCRIPTION_MAX_LENGTH = 500


def _clean_description(description):
    if not isinstance(description, str):
        raise InventoryValidationError("Description must be text.")
    clean = description.strip()
    if len(clean) > DESCRIPTION_MAX_LENGTH:
        raise InventoryValidationError(
            "Description must be at most 500 characters."
        )
    return clean


def _coerce_day(value):
    if isinstance(value, date_class):
        return value
    return _as_date(value, "movement_date")


def _movement_fingerprint(*, movement_type, product_id, warehouse_id,
                          signed_quantity, movement_day, currency_code,
                          unit_cost, rate, rate_day, reference, description,
                          is_temporary_cost, journal_entry_id, actor_id,
                          gross_quantity=None, waste_quantity=None,
                          source_party_id=None):
    canonical = "|".join([
        str(movement_type), str(product_id), str(warehouse_id),
        str(signed_quantity), movement_day.isoformat(), currency_code,
        str(unit_cost), str(rate), rate_day.isoformat(), reference,
        description,
        str(gross_quantity), str(waste_quantity), str(source_party_id),
        str(is_temporary_cost), str(journal_entry_id), str(actor_id),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _snapshot(movement):
    return {
        "id": movement.id,
        "movement_type": movement.movement_type,
        "product_id": movement.product_id,
        "warehouse_id": movement.warehouse_id,
        "quantity": movement.quantity,
        "qty_before": movement.qty_before,
        "qty_after": movement.qty_after,
        "movement_date": movement.movement_date.isoformat(),
        "currency": movement.currency.code,
        "unit_cost": str(movement.unit_cost),
        "rate": str(movement.rate),
        "rate_date": movement.rate_date.isoformat(),
        "unit_cost_afn": str(movement.unit_cost_afn),
        "is_temporary_cost": movement.is_temporary_cost,
        "journal_entry_id": movement.journal_entry_id,
        "reference": movement.reference,
        "description": movement.description,
        "source_party_id": movement.source_party_id,
        "gross_quantity": movement.gross_quantity,
        "waste_quantity": movement.waste_quantity,
    }


def _create_movement(*, movement_type, product, warehouse, signed_quantity,
                     movement_day, currency, unit_cost, rate_value,
                     rate_day, reference, description, actor, journal_entry,
                     is_temporary_cost, idempotency_key, audit_reason,
                     gross_quantity=None, waste_quantity=None, source_party=None):
    before = stock_for(product, warehouse)
    after = before + signed_quantity
    movement = StockMovement.objects.create(
        movement_type=movement_type,
        product=product,
        warehouse=warehouse,
        quantity=signed_quantity,
        movement_date=movement_day,
        currency=currency,
        unit_cost=unit_cost,
        rate=rate_value,
        rate_date=rate_day,
        unit_cost_afn=quantize_half_up(unit_cost * rate_value, 4),
        is_temporary_cost=is_temporary_cost,
        qty_before=before,
        qty_after=after,
        reference=reference,
        description=description,
        source_party=source_party,
        gross_quantity=gross_quantity,
        waste_quantity=waste_quantity,
        journal_entry=journal_entry,
        idempotency_key=idempotency_key,
    )
    record_audit_event(
        user=actor, action=AuditAction.CREATE, entity="StockMovement",
        entity_id=movement.id, reference=reference,
        previous_state=None, new_state=_snapshot(movement),
        reason=audit_reason,
    )
    return movement


def _resolve_movement_retry(idempotency_key, fingerprint):
    stored = IdempotencyRecord.objects.get(key=idempotency_key)
    body = stored.response_body or {}
    if body.get("fingerprint") != fingerprint:
        raise InventoryValidationError(
            "This idempotency key was already used for a different operation."
        )
    movement_id = body.get("movement_id")
    if movement_id is None:
        raise DuplicateOperationError(
            "Original submission is still in progress; retry."
        )
    try:
        return StockMovement.objects.get(pk=movement_id)
    except StockMovement.DoesNotExist:
        raise DuplicateOperationError(
            "Original submission is still in progress; retry."
        ) from None


def _post_movement(*, movement_type, product, warehouse, signed_quantity,
                   movement_day, currency, unit_cost, rate_value, rate_day,
                   reference, description, actor, journal_entry=None,
                   is_temporary_cost=False, idempotency_key=None,
                   audit_reason="", gross_quantity=None,
                   waste_quantity=None, source_party=None):
    """Create one movement + its audit atomically, idempotently on retry."""
    if idempotency_key is not None and (
        not isinstance(idempotency_key, str)
        or not idempotency_key
        or len(idempotency_key) > 128
    ):
        raise InventoryValidationError("A valid idempotency key is required.")
    create_kwargs = dict(
        movement_type=movement_type, product=product, warehouse=warehouse,
        signed_quantity=signed_quantity, movement_day=movement_day,
        currency=currency, unit_cost=unit_cost, rate_value=rate_value,
        rate_day=rate_day, reference=reference, description=description,
        actor=actor,
        journal_entry=journal_entry, is_temporary_cost=is_temporary_cost,
        idempotency_key=idempotency_key, audit_reason=audit_reason,
        gross_quantity=gross_quantity, waste_quantity=waste_quantity,
        source_party=source_party,
    )
    if idempotency_key is None:
        with transaction.atomic():
            return _create_movement(**create_kwargs)
    fingerprint = _movement_fingerprint(
        movement_type=movement_type, product_id=product.pk,
        warehouse_id=warehouse.pk, signed_quantity=signed_quantity,
        movement_day=movement_day, currency_code=currency.code,
        unit_cost=unit_cost, rate=rate_value, rate_day=rate_day,
        reference=reference, description=description,
        gross_quantity=gross_quantity, waste_quantity=waste_quantity,
        source_party_id=source_party.pk if source_party else None,
        is_temporary_cost=is_temporary_cost,
        journal_entry_id=journal_entry.pk if journal_entry else None,
        actor_id=actor.pk if actor else None,
    )
    try:
        with idempotent_operation(
            key=idempotency_key, operation=INVENTORY_MOVEMENT_OPERATION
        ) as record:
            with transaction.atomic():
                movement = _create_movement(**create_kwargs)
                record.response_body = {
                    "movement_id": movement.id, "fingerprint": fingerprint
                }
                record.save(update_fields=["response_body"])
            return movement
    except DuplicateOperationError as dup:
        # idempotent_operation converts ANY IntegrityError inside its block
        # into DuplicateOperationError. Only a genuinely reserved key means
        # "retry"; otherwise re-raise the real cause (post_journal pattern).
        if IdempotencyRecord.objects.filter(key=idempotency_key).exists():
            return _resolve_movement_retry(idempotency_key, fingerprint)
        raise dup.__cause__ if dup.__cause__ is not None else dup


def _require_active_masters(product, warehouse, currency):
    if not product.is_active:
        raise InventoryValidationError("Product is not active.")
    if not warehouse.is_active:
        raise InventoryValidationError("Warehouse is not active.")
    if not currency.is_active:
        raise InventoryValidationError("Currency is not active.")


def receive_stock(*, product, warehouse, quantity, unit_cost, currency,
                  rate=None, rate_date=None, movement_date, reference,
                  description="", user=None, idempotency_key=None,
                  gross_quantity=None, waste_quantity=None, party=None):
    """Post one movement-only receipt at a caller-supplied unit cost (§12).

    No journal is posted: the future Purchase domain owns cost aggregation
    and its journals, and calls this primitive for the stock leg.
    """
    actor = _require_actor(user, "receive stock")
    resolved_product = resolve_product(product)
    resolved_warehouse = resolve_warehouse(warehouse)
    resolved_currency = resolve_currency(currency)
    _require_active_masters(
        resolved_product, resolved_warehouse, resolved_currency)
    units = _coerce_units(quantity, what="Receipt quantity")
    clean_cost = _coerce_unit_cost(unit_cost)
    clean_rate = _coerce_rate(resolved_currency, rate)
    day = _coerce_day(movement_date)
    clean_reference = _clean_reference(reference)
    clean_description = _clean_description(description)
    return _post_movement(
        movement_type=MovementType.PURCHASE_RECEIPT,
        product=resolved_product, warehouse=resolved_warehouse,
        signed_quantity=units, movement_day=day,
        currency=resolved_currency, unit_cost=clean_cost,
        rate_value=clean_rate,
        rate_day=_coerce_rate_date(resolved_currency, rate_date, day),
        reference=clean_reference, description=clean_description,
        actor=actor, idempotency_key=idempotency_key,
        gross_quantity=gross_quantity, waste_quantity=waste_quantity,
        source_party=party,
    )


def issue_stock(*, product, warehouse, quantity, movement_date, reference,
                description="", user=None, idempotency_key=None,
                acknowledge_negative=False,
                temporary_unit_cost=None, temporary_currency=None,
                temporary_rate=None, temporary_rate_date=None, party=None):
    """Post one movement-only issue at AVCO — or at manual temp cost (§18).

    When the issue keeps stock at/above zero, the running AVCO is the
    cost basis (AFN, rate 1). When the issue drives stock negative, the
    caller must pass ``acknowledge_negative=True`` (the warning is this
    boundary's loud rejection without it) AND a manually entered
    ``temporary_unit_cost``; nothing is ever auto-substituted (no
    reference price, no last price, no invented standard cost). No COGS
    journal is posted here: Sales owns it later.
    """
    actor = _require_actor(user, "issue stock")
    resolved_product = resolve_product(product)
    resolved_warehouse = resolve_warehouse(warehouse)
    units = _coerce_units(quantity, what="Issue quantity")
    day = _coerce_day(movement_date)
    clean_reference = _clean_reference(reference)
    clean_description = _clean_description(description)
    current = stock_for(resolved_product, resolved_warehouse)
    resulting = current - units
    if resulting < 0:
        if not acknowledge_negative:
            raise InventoryValidationError(
                "WARNING: this issue drives stock negative "
                f"({current} -> {resulting}); explicit acknowledgement "
                "is required."
            )
        if temporary_unit_cost is None:
            raise InventoryValidationError(
                "A manually entered temporary unit cost is required when "
                "stock is negative or insufficient."
            )
        if temporary_currency is None:
            temp_currency = _base_currency()
        else:
            temp_currency = resolve_currency(temporary_currency)
        _require_active_masters(
            resolved_product, resolved_warehouse, temp_currency)
        clean_cost = _coerce_unit_cost(temporary_unit_cost)
        clean_rate = _coerce_rate(temp_currency, temporary_rate)
        clean_rate_day = _coerce_rate_date(temp_currency, temporary_rate_date, day)
        temporary = True
        reason = (
            f"Negative stock acknowledged: {current} -> {resulting}; "
            "temporary cost entered manually."
        )
    else:
        _require_active_masters(
            resolved_product, resolved_warehouse, _base_currency())
        average = avco_for(resolved_product, resolved_warehouse)
        if average is None:  # pragma: no cover - defensive; qty > 0 here
            raise InventoryValidationError(
                "No cost basis is available for this issue."
            )
        temp_currency = _base_currency()
        clean_cost = average
        clean_rate = Decimal("1.0000")
        clean_rate_day = day
        temporary = False
        reason = ""
    return _post_movement(
        movement_type=MovementType.SALES_ISSUE,
        product=resolved_product, warehouse=resolved_warehouse,
        signed_quantity=-units, movement_day=day,
        currency=temp_currency, unit_cost=clean_cost,
        rate_value=clean_rate, rate_day=clean_rate_day,
        reference=clean_reference, description=clean_description,
        actor=actor, is_temporary_cost=temporary,
        idempotency_key=idempotency_key, audit_reason=reason,
        source_party=party,
    )


def _jalali_year(value):
    return int(gregorian_to_jalali(value).split("/")[0])


def open_stock(*, product, warehouse, quantity, unit_cost, currency,
               rate=None, rate_date=None, posting_date, reference,
               description="", user=None, number=None,
               idempotency_key=None):
    """Post one opening movement + its Dr Inventory / Cr 3900 journal (§15).

    The journal goes through ``post_journal`` (period gate + validation +
    POST audit + idempotency all automatic) with the "JE" system-number
    precedent and source OPENING_STOCK; the movement links to it. One
    atomic transaction covers both (mirror of ``open_party_balance``).
    No one-shot restriction is invented. Returns the movement.
    """
    actor = _require_actor(user, "open stock")
    resolved_product = resolve_product(product)
    resolved_warehouse = resolve_warehouse(warehouse)
    resolved_currency = resolve_currency(currency)
    _require_active_masters(
        resolved_product, resolved_warehouse, resolved_currency)
    units = _coerce_units(quantity, what="Opening quantity")
    clean_cost = _coerce_unit_cost(unit_cost)
    clean_rate = _coerce_rate(resolved_currency, rate)
    day = _coerce_day(posting_date)
    clean_reference = _clean_reference(reference)
    if not isinstance(description, str):
        raise InventoryValidationError("Opening description must be text.")
    account = resolve_warehouse_account(resolved_warehouse)
    equity = _require_usable_account(OPENING_EQUITY_ACCOUNT)
    if number is None:
        number = next_document_number("JE", _jalali_year(day))
    elif not isinstance(number, str) or not number.strip():
        raise InventoryValidationError("Journal number must be text.")
    else:
        number = number.strip()
    label = (
        f"Opening stock: {resolved_product.code} x {units} "
        f"@ {resolved_warehouse.name}"
    )
    line_description = description.strip() or label
    amount = line_total(units, clean_cost)
    inventory_leg = {
        "account": account, "debit": amount,
        "description": line_description, "reference": clean_reference,
    }
    equity_leg = {
        "account": equity, "credit": amount,
        "description": line_description, "reference": clean_reference,
    }
    with transaction.atomic():
        entry = post_journal(
            number=number, posting_date=day,
            description=line_description,
            lines=[inventory_leg, equity_leg],
            source_type=OPENING_SOURCE_TYPE, source_id=number,
            currency=resolved_currency, rate=clean_rate,
            rate_date=_coerce_rate_date(resolved_currency, rate_date, day),
            created_by=actor, idempotency_key=idempotency_key,
        )
        existing = StockMovement.objects.filter(journal_entry=entry).first()
        if existing is not None:
            # Idempotent retry: post_journal returned the ORIGINAL entry.
            # The original movement must match this request exactly.
            if (
                existing.movement_type != MovementType.OPENING
                or existing.product_id != resolved_product.pk
                or existing.warehouse_id != resolved_warehouse.pk
                or existing.quantity != units
                or existing.movement_date != day
                or existing.currency_id != resolved_currency.pk
                or existing.unit_cost != clean_cost
                or existing.rate != clean_rate
                or existing.reference != clean_reference
                or existing.description != line_description
            ):
                raise InventoryValidationError(
                    "This idempotency key was already used for a "
                    "different operation."
                )
            return existing
        return _create_movement(
            movement_type=MovementType.OPENING,
            product=resolved_product, warehouse=resolved_warehouse,
            signed_quantity=units, movement_day=day,
            currency=resolved_currency, unit_cost=clean_cost,
            rate_value=clean_rate,
            rate_day=_coerce_rate_date(resolved_currency, rate_date, day),
            reference=clean_reference, description=line_description,
            actor=actor, journal_entry=entry, is_temporary_cost=False,
            idempotency_key=idempotency_key, audit_reason="",
        )


# ---------------------------------------------------------------------------
# Warehouse transfer (Stage 6.3)
# ---------------------------------------------------------------------------

def _transfer_fingerprint(*, product_id, source_id, dest_id, units,
                          movement_day, currency_code, unit_cost, rate,
                          rate_day, reference, description,
                          is_temporary_cost, actor_id):
    canonical = "|".join([
        "transfer", str(product_id), str(source_id), str(dest_id),
        str(units), movement_day.isoformat(), currency_code,
        str(unit_cost), str(rate), rate_day.isoformat(), reference,
        description, str(is_temporary_cost), str(actor_id),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolve_transfer_retry(idempotency_key, fingerprint):
    stored = IdempotencyRecord.objects.get(key=idempotency_key)
    body = stored.response_body or {}
    if body.get("fingerprint") != fingerprint:
        raise InventoryValidationError(
            "This idempotency key was already used for a different operation."
        )
    out_id = body.get("out_movement_id")
    in_id = body.get("in_movement_id")
    if out_id is None or in_id is None:
        raise DuplicateOperationError(
            "Original submission is still in progress; retry."
        )
    try:
        return (
            StockMovement.objects.get(pk=out_id),
            StockMovement.objects.get(pk=in_id),
        )
    except StockMovement.DoesNotExist:
        raise DuplicateOperationError(
            "Original submission is still in progress; retry."
        ) from None


def _execute_transfer(*, product, source, dest, units, day, currency,
                      unit_cost, rate_value, rate_day, reference,
                      description, actor, src_account, dst_account,
                      is_temporary_cost, idempotency_key, audit_reason):
    """Post the reclass journal + both legs inside the caller's atomic block."""
    number = next_document_number("JE", _jalali_year(day))
    amount = line_total(units, unit_cost)
    journal_description = (
        f"Transfer {reference}: {product.code} x {units} "
        f"({source.name} -> {dest.name})"
    )
    dest_leg = {
        "account": dst_account, "debit": amount,
        "description": journal_description, "reference": reference,
    }
    source_leg = {
        "account": src_account, "credit": amount,
        "description": journal_description, "reference": reference,
    }
    entry = post_journal(
        number=number, posting_date=day, description=journal_description,
        lines=[dest_leg, source_leg],
        source_type=TRANSFER_SOURCE_TYPE, source_id=reference,
        currency=currency, rate=rate_value, rate_date=rate_day,
        created_by=actor, idempotency_key=None,
    )
    out_movement = _create_movement(
        movement_type=MovementType.TRANSFER_OUT,
        product=product, warehouse=source, signed_quantity=-units,
        movement_day=day, currency=currency, unit_cost=unit_cost,
        rate_value=rate_value, rate_day=rate_day, reference=reference,
        description=description, actor=actor, journal_entry=entry,
        is_temporary_cost=is_temporary_cost,
        idempotency_key=idempotency_key, audit_reason=audit_reason,
    )
    in_movement = _create_movement(
        movement_type=MovementType.TRANSFER_IN,
        product=product, warehouse=dest, signed_quantity=units,
        movement_day=day, currency=currency, unit_cost=unit_cost,
        rate_value=rate_value, rate_day=rate_day, reference=reference,
        description=description, actor=actor, journal_entry=entry,
        is_temporary_cost=is_temporary_cost,
        idempotency_key=idempotency_key, audit_reason="",
    )
    return out_movement, in_movement, entry


def transfer_stock(*, product, source_warehouse, destination_warehouse,
                   quantity, movement_date, reference, description,
                   user=None, idempotency_key=None,
                   acknowledge_negative=False, temporary_unit_cost=None,
                   temporary_currency=None, temporary_rate=None,
                   temporary_rate_date=None):
    """Move stock between two warehouses, atomically (Stage 6.3).

    Posts one TRANSFER_OUT leg (source, at the existing cost-basis rule
    mirrored from ``issue_stock``) plus one TRANSFER_IN leg (destination,
    same basis — no FX, no new cost) plus the P&L-neutral reclass journal
    Dr destination-account / Cr source-account through ``post_journal``.
    Both legs share reference, description, cost context, and journal, so
    the pair is traceable as one business operation with no new entity or
    numbering. The transfer idempotency key lives on the operation record
    (one key per operation); legs keep idempotency_key NULL because that
    column is unique per movement row. The journal number is always
    system-assigned; callers identify the transfer by idempotency key /
    reference. Same-account mappings post a balanced wash journal (uniform
    rule, complete trail). Returns (out_movement, in_movement).
    """
    actor = _require_actor(user, "transfer stock")
    if idempotency_key is not None and (
        not isinstance(idempotency_key, str)
        or not idempotency_key
        or len(idempotency_key) > 128
    ):
        raise InventoryValidationError("A valid idempotency key is required.")
    resolved_product = resolve_product(product)
    resolved_source = resolve_warehouse(source_warehouse)
    resolved_dest = resolve_warehouse(destination_warehouse)
    if resolved_source.pk == resolved_dest.pk:
        raise InventoryValidationError(
            "Source and destination warehouses must differ."
        )
    units = _coerce_units(quantity, what="Transfer quantity")
    day = _coerce_day(movement_date)
    clean_reference = _clean_reference(reference)
    clean_description = _clean_description(description)
    if not clean_description:
        raise InventoryValidationError(
            "A transfer description/reason is required."
        )
    src_account = resolve_warehouse_account(resolved_source)
    dst_account = resolve_warehouse_account(resolved_dest)
    # Cost basis mirrors the issue_stock rule exactly (positive stock ->
    # running AVCO; otherwise manual temp + ack). issue_stock itself is
    # not called: it posts SALES_ISSUE rows, which is the wrong type.
    current = stock_for(resolved_product, resolved_source)
    resulting = current - units
    if resulting < 0:
        if not acknowledge_negative:
            raise InventoryValidationError(
                "WARNING: this transfer drives source stock negative "
                f"({current} -> {resulting}); explicit acknowledgement "
                "is required."
            )
        if temporary_unit_cost is None:
            raise InventoryValidationError(
                "A manually entered temporary unit cost is required when "
                "source stock is negative or insufficient."
            )
        if temporary_currency is None:
            basis_currency = _base_currency()
        else:
            basis_currency = resolve_currency(temporary_currency)
        _require_active_masters(
            resolved_product, resolved_source, basis_currency)
        _require_active_masters(
            resolved_product, resolved_dest, basis_currency)
        clean_cost = _coerce_unit_cost(temporary_unit_cost)
        clean_rate = _coerce_rate(basis_currency, temporary_rate)
        clean_rate_day = _coerce_rate_date(
            basis_currency, temporary_rate_date, day)
        temporary = True
        reason = (
            f"Negative stock acknowledged: {current} -> {resulting}; "
            "temporary cost entered manually."
        )
    else:
        basis_currency = _base_currency()
        _require_active_masters(
            resolved_product, resolved_source, basis_currency)
        _require_active_masters(
            resolved_product, resolved_dest, basis_currency)
        average = avco_for(resolved_product, resolved_source)
        if average is None:  # pragma: no cover - defensive; qty > 0 here
            raise InventoryValidationError(
                "No cost basis is available for this transfer."
            )
        clean_cost = average
        clean_rate = Decimal("1.0000")
        clean_rate_day = day
        temporary = False
        reason = ""
    execute_kwargs = dict(
        product=resolved_product, source=resolved_source,
        dest=resolved_dest, units=units, day=day, currency=basis_currency,
        unit_cost=clean_cost, rate_value=clean_rate, rate_day=clean_rate_day,
        reference=clean_reference, description=clean_description,
        actor=actor, src_account=src_account, dst_account=dst_account,
        is_temporary_cost=temporary, idempotency_key=None,
        audit_reason=reason,
    )
    if idempotency_key is None:
        with transaction.atomic():
            out_movement, in_movement, _entry = _execute_transfer(
                **execute_kwargs)
            return out_movement, in_movement
    fingerprint = _transfer_fingerprint(
        product_id=resolved_product.pk, source_id=resolved_source.pk,
        dest_id=resolved_dest.pk, units=units, movement_day=day,
        currency_code=basis_currency.code, unit_cost=clean_cost,
        rate=clean_rate, rate_day=clean_rate_day,
        reference=clean_reference, description=clean_description,
        is_temporary_cost=temporary, actor_id=actor.pk if actor else None,
    )
    try:
        with idempotent_operation(
            key=idempotency_key, operation=INVENTORY_TRANSFER_OPERATION
        ) as record:
            with transaction.atomic():
                out_movement, in_movement, entry = _execute_transfer(
                    **execute_kwargs)
                record.response_body = {
                    "out_movement_id": out_movement.id,
                    "in_movement_id": in_movement.id,
                    "journal_entry_id": entry.id,
                    "fingerprint": fingerprint,
                }
                record.save(update_fields=["response_body"])
            return out_movement, in_movement
    except DuplicateOperationError as dup:
        # Same post_journal pattern: only a genuinely reserved key means
        # "retry"; otherwise re-raise the real cause.
        if IdempotencyRecord.objects.filter(key=idempotency_key).exists():
            return _resolve_transfer_retry(idempotency_key, fingerprint)
        raise dup.__cause__ if dup.__cause__ is not None else dup

# ---------------------------------------------------------------------------
# Stage 6.4 — adjustments, receiving waste, and later shortage
# ---------------------------------------------------------------------------

def _adjustment_operation(*, movement_type, product, warehouse, quantity,
                          movement_date, reference, description, user,
                          idempotency_key=None, acknowledge_negative=False,
                          unit_cost=None, currency=None, rate=None, rate_date=None,
                          reason_label):
    actor = _require_actor(user, reason_label)
    day = _coerce_day(movement_date)
    assert_posting_date_open(day)
    resolved_product = resolve_product(product)
    resolved_warehouse = resolve_warehouse(warehouse)
    units = _coerce_units(quantity, what="Adjustment quantity")
    clean_reference = _clean_reference(reference)
    clean_description = _clean_description(description)
    if not clean_description:
        raise InventoryValidationError("A reason/description is required.")
    if movement_type == MovementType.ADJUSTMENT_IN:
        resolved_currency = resolve_currency(currency)
        _require_active_masters(resolved_product, resolved_warehouse, resolved_currency)
        cost = _coerce_unit_cost(unit_cost)
        rate_value = _coerce_rate(resolved_currency, rate)
        rate_day = _coerce_rate_date(resolved_currency, rate_date, day)
        temporary = False
        audit_reason = reason_label
        signed = units
    else:
        current = stock_for(resolved_product, resolved_warehouse)
        resulting = current - units
        if resulting < 0 and not acknowledge_negative:
            raise InventoryValidationError(
                f"WARNING: this adjustment drives stock negative ({current} -> {resulting}); "
                "explicit acknowledgement is required."
            )
        if resulting < 0 and unit_cost is None:
            raise InventoryValidationError(
                "A manually entered temporary unit cost is required when stock is negative."
            )
        if resulting < 0:
            resolved_currency = resolve_currency(currency) if currency is not None else _base_currency()
            cost = _coerce_unit_cost(unit_cost)
            rate_value = _coerce_rate(resolved_currency, rate)
            rate_day = _coerce_rate_date(resolved_currency, rate_date, day)
            temporary = True
            audit_reason = f"{reason_label}; negative stock acknowledged; temporary cost entered manually"
        else:
            resolved_currency = _base_currency()
            _require_active_masters(resolved_product, resolved_warehouse, resolved_currency)
            average = avco_for(resolved_product, resolved_warehouse)
            if average is None:
                raise InventoryValidationError("No cost basis is available for this adjustment.")
            cost, rate_value, rate_day, temporary = average, Decimal("1.0000"), day, False
            audit_reason = reason_label
        signed = -units
    return _post_movement(
        movement_type=movement_type, product=resolved_product,
        warehouse=resolved_warehouse, signed_quantity=signed, movement_day=day,
        currency=resolved_currency, unit_cost=cost, rate_value=rate_value,
        rate_day=rate_day, reference=clean_reference, description=clean_description,
        actor=actor, is_temporary_cost=temporary, idempotency_key=idempotency_key,
        audit_reason=audit_reason,
    )


def adjust_stock_in(**kwargs):
    """Post a positive, explicitly costed physical inventory adjustment."""
    return _adjustment_operation(movement_type=MovementType.ADJUSTMENT_IN,
                                 reason_label="Positive inventory adjustment",
                                 **kwargs)


def adjust_stock_out(**kwargs):
    """Post a negative physical adjustment under the existing issue policy."""
    return _adjustment_operation(movement_type=MovementType.ADJUSTMENT_OUT,
                                 reason_label="Negative inventory adjustment",
                                 **kwargs)


def receive_with_waste(*, product, warehouse, gross_quantity, waste_quantity,
                       total_cost, currency, rate=None, rate_date=None,
                       movement_date, reference, description, user=None,
                       idempotency_key=None):
    """Receive usable quantity while retaining receiving-waste facts.

    ``total_cost`` is allocated over gross minus waste; waste is not a later
    shortage and no separate stock leg is created.
    """
    gross = _coerce_units(gross_quantity, what="Gross receipt quantity")
    waste = _coerce_units(waste_quantity, what="Waste quantity", allow_zero=True)
    if waste >= gross:
        raise InventoryValidationError("Waste must be less than gross quantity.")
    usable = gross - waste
    assert_posting_date_open(_coerce_day(movement_date))
    total = to_decimal(total_cost)
    if total < 0:
        raise InventoryValidationError("Total shipment cost cannot be negative.")
    unit = quantize_half_up(total / usable, 4)
    movement = receive_stock(
        product=product, warehouse=warehouse, quantity=usable, unit_cost=unit,
        currency=currency, rate=rate, rate_date=rate_date,
        movement_date=movement_date, reference=reference, description=description,
        user=user, idempotency_key=idempotency_key,
        gross_quantity=gross, waste_quantity=waste,
    )
    return movement


def record_shortage(*, product, warehouse, quantity, movement_date, reference,
                    description, user=None, idempotency_key=None,
                    acknowledge_negative=False, temporary_unit_cost=None,
                    temporary_currency=None, temporary_rate=None,
                    temporary_rate_date=None):
    """Record a later shortage as a new immutable outbound movement."""
    return _adjustment_operation(
        movement_type=MovementType.SHORTAGE, product=product, warehouse=warehouse,
        quantity=quantity, movement_date=movement_date, reference=reference,
        description=description, user=user, idempotency_key=idempotency_key,
        acknowledge_negative=acknowledge_negative, unit_cost=temporary_unit_cost,
        currency=temporary_currency, rate=temporary_rate, rate_date=temporary_rate_date,
        reason_label="Warehouse shortage",
    )


def settle_shortage(*, shortage, settlement_date, actual_sales_rate,
                    currency, rate=None, rate_date=None, reference,
                    user=None, idempotency_key=None):
    """Store manual actual-sales-rate compensation without changing stock."""
    actor = _require_actor(user, "settle shortage")
    if not isinstance(shortage, StockMovement):
        try:
            shortage = StockMovement.objects.get(pk=shortage)
        except (StockMovement.DoesNotExist, ValueError, TypeError):
            raise InventoryValidationError("Shortage movement does not exist.") from None
    if shortage.movement_type != MovementType.SHORTAGE:
        raise InventoryValidationError("Settlement must reference a shortage movement.")
    day = _coerce_day(settlement_date)
    assert_posting_date_open(day)
    clean_ref = _clean_reference(reference)
    cur = resolve_currency(currency)
    _require_active_masters(shortage.product, shortage.warehouse, cur)
    rate_value = _coerce_rate(cur, rate)
    rate_day_value = _coerce_rate_date(cur, rate_date, day)
    manual = _coerce_unit_cost(actual_sales_rate)
    amount = quantize_half_up(manual * abs(shortage.quantity), 4)
    fingerprint = hashlib.sha256("|".join(map(str, [shortage.pk, day, manual, cur.code,
        rate_value, rate_day_value, clean_ref, actor.pk if actor else None])).encode()).hexdigest()
    if idempotency_key is None:
        with transaction.atomic():
            record = ShortageSettlement.objects.create(
                shortage=shortage, settlement_date=day, unit_rate=manual,
                currency=cur, rate=rate_value, rate_date=rate_day_value,
                compensation_amount=amount, reference=clean_ref,
            )
            record._compensation_amount = amount
            record._reference = clean_ref
            record_audit_event(user=actor, action=AuditAction.CREATE,
                entity="ShortageSettlement", entity_id=record.id, reference=clean_ref,
                previous_state=None, new_state={"shortage_id": shortage.pk,
                "settlement_date": day.isoformat(), "actual_sales_rate": str(manual),
                "currency": cur.code, "compensation_amount": str(amount)},
                reason="Manual actual sales rate; no reference price used")
            return record
    try:
        with idempotent_operation(key=idempotency_key, operation=SHORTAGE_SETTLEMENT_OPERATION) as idem:
            with transaction.atomic():
                record = ShortageSettlement.objects.create(
                    shortage=shortage, settlement_date=day, unit_rate=manual,
                    currency=cur, rate=rate_value, rate_date=rate_day_value,
                    compensation_amount=amount, reference=clean_ref,
                    idempotency_key=idempotency_key)
                idem.response_body = {"settlement_id": record.id, "fingerprint": fingerprint,
                                      "compensation_amount": str(amount)}
                idem.save(update_fields=["response_body"])
                record_audit_event(user=actor, action=AuditAction.CREATE,
                    entity="ShortageSettlement", entity_id=record.id, reference=clean_ref,
                    previous_state=None, new_state={"shortage_id": shortage.pk,
                    "settlement_date": day.isoformat(), "actual_sales_rate": str(manual),
                    "currency": cur.code, "compensation_amount": str(amount)},
                    reason="Manual actual sales rate; no reference price used")
                return record
    except DuplicateOperationError as dup:
        # A failed atomic body rolls back the reservation. Only an existing
        # record represents a genuine retry; preserve the original failure.
        if not IdempotencyRecord.objects.filter(key=idempotency_key).exists():
            raise dup.__cause__ if dup.__cause__ is not None else dup
        stored = IdempotencyRecord.objects.get(key=idempotency_key)
        body = stored.response_body or {}
        if body.get("fingerprint") != fingerprint:
            raise InventoryValidationError("This idempotency key was already used for a different operation.")
        return ShortageSettlement.objects.get(pk=body["settlement_id"])

# ---------------------------------------------------------------------------
# Stage 6.5 — purchase and sales returns
# ---------------------------------------------------------------------------

def _resolve_party(ref, *, role):
    from parties.models import Party
    if isinstance(ref, Party):
        party = ref
    else:
        try:
            party = Party.objects.get(pk=ref)
        except (Party.DoesNotExist, ValueError, TypeError):
            raise InventoryValidationError("Party does not exist.") from None
    if not party.is_active:
        raise InventoryValidationError("Party is not active.")
    if not getattr(party, role):
        raise InventoryValidationError(f"Party is not a {role[3:]}.")
    return party


def _resolve_source_movement(ref):
    if isinstance(ref, StockMovement):
        if ref.pk is None:
            raise InventoryValidationError("Source movement does not exist.")
        return ref
    try:
        return StockMovement.objects.get(pk=ref)
    except (StockMovement.DoesNotExist, ValueError, TypeError):
        raise InventoryValidationError("Source movement does not exist.") from None


def _return_fingerprint(*, return_type, source_id, party_id, product_id,
                        warehouse_id, quantity, source_document, movement_day,
                        description, actor_id):
    canonical = "|".join([
        return_type, str(source_id), str(party_id), str(product_id),
        str(warehouse_id), str(quantity), source_document,
        movement_day.isoformat(), description, str(actor_id),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolve_return_retry(idempotency_key, fingerprint):
    stored = IdempotencyRecord.objects.get(key=idempotency_key)
    body = stored.response_body or {}
    if body.get("fingerprint") != fingerprint:
        raise InventoryValidationError(
            "This idempotency key was already used for a different operation."
        )
    return InventoryReturn.objects.get(pk=body["return_id"])


def _post_return(*, return_type, source_type, movement_type, party_role,
                 source_movement, party, product, warehouse, quantity,
                 source_document, movement_date, description, actor,
                 idempotency_key, acknowledge_negative):
    day = _coerce_day(movement_date)
    assert_posting_date_open(day)
    units = _coerce_units(quantity, what="Return quantity")
    clean_document = _clean_reference(source_document)
    clean_description = _clean_description(description)
    if not clean_description:
        raise InventoryValidationError("A return reason/description is required.")
    source = _resolve_source_movement(source_movement)
    resolved_party = _resolve_party(party, role=party_role)
    resolved_product = resolve_product(product)
    resolved_warehouse = resolve_warehouse(warehouse)
    if source.movement_type != source_type:
        raise InventoryValidationError("Source movement type is invalid for this return.")
    if source.reference != clean_document:
        raise InventoryValidationError(
            "Source document must match the original source movement reference."
        )
    if source.product_id != resolved_product.pk:
        raise InventoryValidationError("Return product does not match the source movement.")
    if source.warehouse_id != resolved_warehouse.pk:
        raise InventoryValidationError("Return warehouse does not match the source movement.")
    if source.source_party_id != resolved_party.pk:
        raise InventoryValidationError("Return party does not match the source movement.")
    if source.movement_type == MovementType.PURCHASE_RECEIPT and not resolved_party.is_supplier:
        raise InventoryValidationError("Purchase return party must be a supplier.")
    if source.movement_type == MovementType.SALES_ISSUE and not resolved_party.is_customer:
        raise InventoryValidationError("Sales return party must be a customer.")
    if units > source.quantity.__abs__():
        raise InventoryValidationError("Return quantity exceeds the source quantity.")
    already = InventoryReturn.objects.filter(source_movement=source).aggregate(
        total=Sum("quantity")
    )["total"] or 0
    remaining = abs(source.quantity) - int(already)
    if units > remaining:
        raise InventoryValidationError(
            f"Return quantity exceeds remaining returnable quantity ({remaining})."
        )
    _require_active_masters(resolved_product, resolved_warehouse, source.currency)
    resulting = stock_for(resolved_product, resolved_warehouse) + (
        units if movement_type == MovementType.SALES_RETURN else -units
    )
    if resulting < 0 and not acknowledge_negative:
        raise InventoryValidationError(
            f"WARNING: this return drives stock negative; explicit acknowledgement is required."
        )
    signed = units if movement_type == MovementType.SALES_RETURN else -units
    movement = _create_movement(
        movement_type=movement_type, product=resolved_product,
        warehouse=resolved_warehouse, signed_quantity=signed, movement_day=day,
        currency=source.currency, unit_cost=source.unit_cost,
        rate_value=source.rate, rate_day=source.rate_date,
        reference=clean_document, description=clean_description, actor=actor,
        journal_entry=None, is_temporary_cost=source.is_temporary_cost,
        idempotency_key=None,
        audit_reason=("Purchase return" if return_type == "PURCHASE_RETURN"
                      else "Sales return"),
    )
    record = InventoryReturn.objects.create(
        return_type=return_type, source_movement=source,
        return_movement=movement, party=resolved_party,
        product=resolved_product, warehouse=resolved_warehouse,
        source_document=clean_document, quantity=units,
        description=clean_description, idempotency_key=None,
    )
    record_audit_event(
        user=actor, action=AuditAction.CREATE, entity="InventoryReturn",
        entity_id=record.id, reference=clean_document,
        previous_state=None,
        new_state={
            "return_type": return_type, "source_movement_id": source.id,
            "return_movement_id": movement.id, "party_id": resolved_party.id,
            "product_id": resolved_product.id, "warehouse_id": resolved_warehouse.id,
            "quantity": units, "original_unit_cost": str(source.unit_cost),
            "currency": source.currency.code, "rate": str(source.rate),
            "qty_before": movement.qty_before, "qty_after": movement.qty_after,
            "description": clean_description,
        },
        reason="Immutable inventory return posted",
    )
    return record


def _return_operation(*, return_type, source_type, movement_type, party_role,
                      product, warehouse, party, source_movement, quantity,
                      source_document, movement_date, description, user,
                      idempotency_key, acknowledge_negative):
    actor = _require_actor(user, "post inventory return")
    if idempotency_key is not None and (
        not isinstance(idempotency_key, str) or not idempotency_key
        or len(idempotency_key) > 128
    ):
        raise InventoryValidationError("A valid idempotency key is required.")
    day = _coerce_day(movement_date)
    source = _resolve_source_movement(source_movement)
    resolved_party = _resolve_party(party, role=party_role)
    resolved_product = resolve_product(product)
    resolved_warehouse = resolve_warehouse(warehouse)
    clean_document = _clean_reference(source_document)
    clean_description = _clean_description(description)
    units = _coerce_units(quantity, what="Return quantity")
    fingerprint = _return_fingerprint(
        return_type=return_type, source_id=source.pk, party_id=resolved_party.pk,
        product_id=resolved_product.pk, warehouse_id=resolved_warehouse.pk,
        quantity=units, source_document=clean_document, movement_day=day,
        description=clean_description, actor_id=actor.pk if actor else None,
    )
    kwargs = dict(
        return_type=return_type, source_type=source_type,
        movement_type=movement_type, party_role=party_role,
        source_movement=source, party=resolved_party, product=resolved_product,
        warehouse=resolved_warehouse, quantity=units,
        source_document=clean_document, movement_date=day,
        description=clean_description, actor=actor,
        idempotency_key=None, acknowledge_negative=acknowledge_negative,
    )
    operation = (PURCHASE_RETURN_OPERATION if return_type == "PURCHASE_RETURN"
                 else SALES_RETURN_OPERATION)
    if idempotency_key is None:
        with transaction.atomic():
            return _post_return(**kwargs)
    try:
        with idempotent_operation(key=idempotency_key, operation=operation) as idem:
            with transaction.atomic():
                # Lock the source and derive returnable quantity from records
                # inside the same transaction, preventing concurrent over-return.
                kwargs["source_movement"] = StockMovement.objects.select_for_update().get(pk=source.pk)
                kwargs["idempotency_key"] = idempotency_key
                record = _post_return(**kwargs)
                idem.response_body = {"return_id": record.id, "fingerprint": fingerprint}
                idem.save(update_fields=["response_body"])
            return record
    except DuplicateOperationError as dup:
        if IdempotencyRecord.objects.filter(key=idempotency_key).exists():
            return _resolve_return_retry(idempotency_key, fingerprint)
        raise dup.__cause__ if dup.__cause__ is not None else dup


def purchase_return(*, product, warehouse, supplier, source_movement,
                    quantity, source_document, movement_date, description,
                    user=None, idempotency_key=None,
                    acknowledge_negative=False):
    return _return_operation(
        return_type="PURCHASE_RETURN", source_type=MovementType.PURCHASE_RECEIPT,
        movement_type=MovementType.PURCHASE_RETURN, party_role="is_supplier",
        product=product, warehouse=warehouse, party=supplier,
        source_movement=source_movement, quantity=quantity,
        source_document=source_document, movement_date=movement_date,
        description=description, user=user, idempotency_key=idempotency_key,
        acknowledge_negative=acknowledge_negative,
    )


def sales_return(*, product, warehouse, customer, source_movement,
                 quantity, source_document, movement_date, description,
                 user=None, idempotency_key=None):
    return _return_operation(
        return_type="SALES_RETURN", source_type=MovementType.SALES_ISSUE,
        movement_type=MovementType.SALES_RETURN, party_role="is_customer",
        product=product, warehouse=warehouse, party=customer,
        source_movement=source_movement, quantity=quantity,
        source_document=source_document, movement_date=movement_date,
        description=description, user=user, idempotency_key=idempotency_key,
        acknowledge_negative=True,
    )

# ---------------------------------------------------------------------------
# Stage 6.6 — customer dispatch / sales issue foundation
# ---------------------------------------------------------------------------

def customer_dispatch(*, product, warehouse, customer, quantity,
                      movement_date, reference, description, user=None,
                      idempotency_key=None, acknowledge_negative=False,
                      temporary_unit_cost=None, temporary_currency=None,
                      temporary_rate=None, temporary_rate_date=None):
    """Post a customer-attributed SALES_ISSUE through the existing primitive.

    This is inventory-side dispatch context only. It deliberately does not
    create a Sales Invoice, price, receivable, revenue, COGS, or payment
    workflow. The existing issue_stock() remains the sole cost/stock engine.
    """
    resolved_customer = _resolve_party(customer, role="is_customer")
    assert_posting_date_open(_coerce_day(movement_date))
    clean_description = _clean_description(description)
    if not clean_description:
        raise InventoryValidationError("A dispatch reason/description is required.")
    return issue_stock(
        product=product, warehouse=warehouse, quantity=quantity,
        movement_date=movement_date, reference=reference,
        description=clean_description, user=user,
        idempotency_key=idempotency_key,
        acknowledge_negative=acknowledge_negative,
        temporary_unit_cost=temporary_unit_cost,
        temporary_currency=temporary_currency,
        temporary_rate=temporary_rate,
        temporary_rate_date=temporary_rate_date,
        party=resolved_customer,
    )
