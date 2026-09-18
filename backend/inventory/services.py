"""Inventory foundation services (Phase 6.1).

Three posting primitives only (§1/§12/§15/§18):

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

Plus the explicit Warehouse → Inventory GL mapping (§19):
``assign_warehouse_account`` / ``resolve_warehouse_account``.

Everything else is reused, never duplicated: posting, money/rounding,
currency, audit, idempotency, period gate, numbering (§24–§29).
"""

import hashlib
from datetime import date as date_class
from decimal import Decimal, InvalidOperation

from django.db import transaction

from accounting.models import Account
from accounting.services import _as_date, post_journal
from core.dates import gregorian_to_jalali
from core.idempotency import DuplicateOperationError, idempotent_operation
from core.models import IdempotencyRecord
from core.money import line_total, normalize_rate, quantize_half_up, to_decimal
from currencies.models import Currency
from documents.services import next_document_number
from products.services import ProductValidationError
from products.services import resolve_product as _resolve_product_frozen
from security.models import AuditAction
from security.services import record_audit_event
from warehouses.services import WarehouseValidationError
from warehouses.services import resolve_warehouse as _resolve_warehouse_frozen

from .models import (
    INVENTORY_MOVEMENT_OPERATION,
    INVENTORY_ROOT_CODE,
    OPENING_EQUITY_ACCOUNT,
    OPENING_SOURCE_TYPE,
    MovementType,
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


def _coerce_units(value, *, what):
    if isinstance(value, bool) or not isinstance(value, int):
        raise InventoryValidationError(
            f"{what} must be an integer count of units."
        )
    if value <= 0:
        raise InventoryValidationError(
            f"{what} must be a positive integer."
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
                          is_temporary_cost, journal_entry_id, actor_id):
    canonical = "|".join([
        str(movement_type), str(product_id), str(warehouse_id),
        str(signed_quantity), movement_day.isoformat(), currency_code,
        str(unit_cost), str(rate), rate_day.isoformat(), reference,
        description,
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
    }


def _create_movement(*, movement_type, product, warehouse, signed_quantity,
                     movement_day, currency, unit_cost, rate_value,
                     rate_day, reference, description, actor, journal_entry,
                     is_temporary_cost, idempotency_key, audit_reason):
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
                   audit_reason=""):
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
                  description="", user=None, idempotency_key=None):
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
    )


def issue_stock(*, product, warehouse, quantity, movement_date, reference,
                description="", user=None, idempotency_key=None,
                acknowledge_negative=False,
                temporary_unit_cost=None, temporary_currency=None,
                temporary_rate=None, temporary_rate_date=None):
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
