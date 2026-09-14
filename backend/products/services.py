"""Product master services (Phase 4.1).

Validated identity + audit. The factor, prices and thresholds stored here
are REFERENCE DATA: nothing converts, prices or plans anything in 4.1
(R-2/R-4/R-8, U-4). Money/quantity coercion reuses the ONE money engine
(`core.money`: Decimal-only, Half-Up) so SQLite and PostgreSQL behave
identically — SQLite does not enforce NUMERIC scale, the service does.
"""

from decimal import Decimal

from django.db import transaction

from categories.services import CategoryValidationError, resolve_category
from core.money import quantize_half_up, to_decimal
from security.models import AuditAction
from security.services import record_audit_event
from uom.services import UOMValidationError, resolve_uom

from .models import Product


class ProductValidationError(ValueError):
    """Deterministic product rejection (service-error convention)."""


_UNSET = object()
_PRICE_PLACES = 4  # §3.11 Unit Price
_FACTOR_PLACES = 4  # recorded neutral storage choice (R-2)
_STOCK_PLACES = 3  # recorded neutral storage choice (R-8)


def _require_actor(user, action):
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        raise ProductValidationError(
            f"Authorization required to {action}: user must be a user."
        )
    return user


def _clean_text(value, *, field):
    if not isinstance(value, str):
        raise ProductValidationError(f"Product {field} must be text.")
    return value.strip()


def _clean_number(value, *, field, places):
    """Coerce via the money engine + Half-Up to storage scale.

    Rejects float/bool/garbage deterministically. Rounding here is §3.12,
    not invention: it is what makes SQLite match PostgreSQL NUMERIC.
    """
    try:
        return quantize_half_up(to_decimal(value), places)
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise ProductValidationError(
            f"Product {field} must be a valid number."
        ) from exc


def _clean_optional_number(value, *, field, places):
    if value is None:
        return None
    return _clean_number(value, field=field, places=places)


def _resolve_category(ref):
    try:
        return resolve_category(ref)
    except CategoryValidationError as exc:
        raise ProductValidationError(str(exc)) from exc


def _resolve_uom(ref, *, field):
    try:
        return resolve_uom(ref)
    except UOMValidationError as exc:
        raise ProductValidationError(f"Product {field}: {exc}") from exc


def resolve_product(ref):
    """Accept a Product instance or pk; deterministic miss error."""
    if isinstance(ref, Product):
        if ref.pk is None:
            raise ProductValidationError("Product does not exist.")
        return ref
    try:
        found = Product.objects.filter(pk=ref).first()
    except (TypeError, ValueError):
        found = None
    if found is None:
        raise ProductValidationError("Product does not exist.")
    return found


def _snapshot(product):
    return {
        "id": product.id,
        "code": product.code,
        "name": product.name,
        "name_fa": product.name_fa,
        "category_id": product.category_id,
        "primary_uom_id": product.primary_uom_id,
        "secondary_uom_id": product.secondary_uom_id,
        "conversion_factor": str(product.conversion_factor),
        "barcode": product.barcode,
        "brand": product.brand,
        "ref_purchase_price": str(product.ref_purchase_price)
        if product.ref_purchase_price is not None else None,
        "ref_sales_price": str(product.ref_sales_price)
        if product.ref_sales_price is not None else None,
        "min_stock": str(product.min_stock),
        "max_stock": str(product.max_stock)
        if product.max_stock is not None else None,
        "reorder_point": str(product.reorder_point)
        if product.reorder_point is not None else None,
        "is_active": product.is_active,
    }


def _clean_factor(value):
    factor = _clean_number(value, field="conversion factor",
                           places=_FACTOR_PLACES)
    if factor <= 0:
        raise ProductValidationError(
            "Product conversion factor must be greater than zero."
        )
    return factor


def _clean_min_stock(value):
    minimum = _clean_number(value, field="minimum stock",
                            places=_STOCK_PLACES)
    if minimum < 0:
        raise ProductValidationError("Product minimum stock cannot be negative.")
    return minimum


def create_product(*, code, name, name_fa, category, primary_uom,
                   secondary_uom=None, conversion_factor=Decimal("1"),
                   barcode="", brand="", ref_purchase_price=None,
                   ref_sales_price=None, min_stock=Decimal("0"), max_stock=None,
                   reorder_point=None, is_active=True, description="",
                   user=None):
    """Create a product. Uniqueness: code only (R-4: nothing else).

    Deliberately NOT validated (R-4, contract silent): max vs min,
    reorder position, secondary-vs-primary, price signs.
    """
    actor = _require_actor(user, "create product")
    clean_code = _clean_text(code, field="code")
    if not clean_code:
        raise ProductValidationError("Product code is required.")
    if Product.objects.filter(code=clean_code).exists():
        raise ProductValidationError(
            f"Product code already exists: {clean_code}."
        )
    clean_name = _clean_text(name, field="name")
    if not clean_name:
        raise ProductValidationError("Product name is required.")
    clean_name_fa = _clean_text(name_fa, field="name_fa")
    if not clean_name_fa:
        raise ProductValidationError("Product Persian/Dari name is required.")
    resolved_category = _resolve_category(category)
    resolved_primary = _resolve_uom(primary_uom, field="primary UOM")
    resolved_secondary = (
        None if secondary_uom is None
        else _resolve_uom(secondary_uom, field="secondary UOM")
    )
    factor = _clean_factor(conversion_factor)
    minimum = _clean_min_stock(min_stock)
    with transaction.atomic():
        product = Product.objects.create(
            code=clean_code, name=clean_name, name_fa=clean_name_fa,
            category=resolved_category, primary_uom=resolved_primary,
            secondary_uom=resolved_secondary, conversion_factor=factor,
            barcode=_clean_text(barcode, field="barcode"),
            brand=_clean_text(brand, field="brand"),
            ref_purchase_price=_clean_optional_number(
                ref_purchase_price, field="reference purchase price",
                places=_PRICE_PLACES),
            ref_sales_price=_clean_optional_number(
                ref_sales_price, field="reference sales price",
                places=_PRICE_PLACES),
            min_stock=minimum,
            max_stock=_clean_optional_number(
                max_stock, field="maximum stock", places=_STOCK_PLACES),
            reorder_point=_clean_optional_number(
                reorder_point, field="reorder point", places=_STOCK_PLACES),
            is_active=bool(is_active),
            description=_clean_text(description, field="description"),
        )
        record_audit_event(
            user=actor, action=AuditAction.CREATE, entity="Product",
            entity_id=product.id, reference=product.code,
            previous_state=None, new_state=_snapshot(product), reason="",
        )
    return product


_UPDATE_FIELDS = [
    "code", "name", "name_fa", "category", "primary_uom", "secondary_uom",
    "conversion_factor", "barcode", "brand", "ref_purchase_price",
    "ref_sales_price", "min_stock", "max_stock", "reorder_point",
    "description",
]


def update_product(product, *, user=None, **kwargs):
    """Partial update over _UPDATE_FIELDS. No changes → no-op, no audit."""
    actor = _require_actor(user, "update product")
    unknown = sorted(set(kwargs) - set(_UPDATE_FIELDS))
    if unknown:
        raise ProductValidationError(
            f"Unknown product fields: {', '.join(unknown)}."
        )
    current = resolve_product(product)
    previous_state = _snapshot(current)
    changed = []

    def _recode(value):
        clean = _clean_text(value, field="code")
        if not clean:
            raise ProductValidationError("Product code is required.")
        if (Product.objects.filter(code=clean)
                .exclude(pk=current.pk).exists()):
            raise ProductValidationError(
                f"Product code already exists: {clean}."
            )
        return clean

    def _rename(value, *, field, message):
        clean = _clean_text(value, field=field)
        if not clean:
            raise ProductValidationError(message)
        return clean

    cleaners = {
        "code": _recode,
        "name": lambda v: _rename(v, field="name",
                                  message="Product name is required."),
        "name_fa": lambda v: _rename(v, field="name_fa",
                                     message="Product Persian/Dari name is required."),
        "category": _resolve_category,
        "primary_uom": lambda v: _resolve_uom(v, field="primary UOM"),
        "secondary_uom": lambda v: (
            None if v is None else _resolve_uom(v, field="secondary UOM")),
        "conversion_factor": _clean_factor,
        "barcode": lambda v: _clean_text(v, field="barcode"),
        "brand": lambda v: _clean_text(v, field="brand"),
        "ref_purchase_price": lambda v: _clean_optional_number(
            v, field="reference purchase price", places=_PRICE_PLACES),
        "ref_sales_price": lambda v: _clean_optional_number(
            v, field="reference sales price", places=_PRICE_PLACES),
        "min_stock": _clean_min_stock,
        "max_stock": lambda v: _clean_optional_number(
            v, field="maximum stock", places=_STOCK_PLACES),
        "reorder_point": lambda v: _clean_optional_number(
            v, field="reorder point", places=_STOCK_PLACES),
        "description": lambda v: _clean_text(v, field="description"),
    }
    for field, raw in kwargs.items():
        cleaned = cleaners[field](raw)
        if field in ("category", "primary_uom", "secondary_uom"):
            new_id = None if cleaned is None else cleaned.pk
            if new_id != getattr(current, f"{field}_id"):
                setattr(current, field, cleaned)
                changed.append(field)
        elif cleaned != getattr(current, field):
            setattr(current, field, cleaned)
            changed.append(field)
    if not changed:
        return current
    with transaction.atomic():
        current.save(update_fields=changed)
        record_audit_event(
            user=actor, action=AuditAction.UPDATE, entity="Product",
            entity_id=current.id, reference=current.code,
            previous_state=previous_state, new_state=_snapshot(current),
            reason="",
        )
    return current


def set_product_active(product, *, is_active, user=None, reason=""):
    """Deactivate/reactivate. Flag only — blocks nothing (R-4)."""
    actor = _require_actor(user, "change product status")
    if not isinstance(reason, str):
        raise ProductValidationError("Product reason must be text.")
    current = resolve_product(product)
    flag = bool(is_active)
    if current.is_active == flag:
        return current  # idempotent no-op
    previous_state = _snapshot(current)
    with transaction.atomic():
        current.is_active = flag
        current.save(update_fields=["is_active"])
        record_audit_event(
            user=actor, action=AuditAction.UPDATE, entity="Product",
            entity_id=current.id, reference=current.code,
            previous_state=previous_state, new_state=_snapshot(current),
            reason=reason.strip(),
        )
    return current
