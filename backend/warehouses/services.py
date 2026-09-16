"""Warehouse master services (Phase 4.3).

Validated identity + active flag + audit. Names may repeat (OD-2); no
codes of any kind (OD-1); no address/location (OD-3); no relations, no
inventory behavior, no financial concepts (§10/§11/§12). Deactivation is
a flag only — it deletes nothing and enforces nothing in this phase (§8).
"""

from django.db import transaction

from security.models import AuditAction
from security.services import record_audit_event

from .models import Warehouse


class WarehouseValidationError(ValueError):
    """Deterministic warehouse rejection (service-error convention)."""


_UNSET = object()


def _require_actor(user, action):
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        raise WarehouseValidationError(
            f"Authorization required to {action}: user must be a user."
        )
    return user


def _clean_text(value, *, field):
    if not isinstance(value, str):
        raise WarehouseValidationError(f"Warehouse {field} must be text.")
    return value.strip()


def _snapshot(warehouse):
    return {
        "id": warehouse.id,
        "name": warehouse.name,
        "name_fa": warehouse.name_fa,
        "is_active": warehouse.is_active,
    }


def resolve_warehouse(ref):
    """Accept a Warehouse instance or pk; deterministic miss error."""
    if isinstance(ref, Warehouse):
        if ref.pk is None:
            raise WarehouseValidationError("Warehouse does not exist.")
        return ref
    try:
        found = Warehouse.objects.filter(pk=ref).first()
    except (TypeError, ValueError):
        found = None
    if found is None:
        raise WarehouseValidationError("Warehouse does not exist.")
    return found


def create_warehouse(*, name, name_fa="", is_active=True, user=None):
    """Create a warehouse. Names may repeat (no invented uniqueness)."""
    actor = _require_actor(user, "create warehouse")
    clean_name = _clean_text(name, field="name")
    if not clean_name:
        raise WarehouseValidationError("Warehouse name is required.")
    with transaction.atomic():
        warehouse = Warehouse.objects.create(
            name=clean_name,
            name_fa=_clean_text(name_fa, field="name_fa"),
            is_active=bool(is_active),
        )
        record_audit_event(
            user=actor, action=AuditAction.CREATE, entity="Warehouse",
            entity_id=warehouse.id, reference=warehouse.name,
            previous_state=None, new_state=_snapshot(warehouse), reason="",
        )
    return warehouse


def update_warehouse(warehouse, *, name=_UNSET, name_fa=_UNSET, user=None):
    """Partial update. No changes → idempotent no-op, no audit row.

    Rename keeps the primary key: identity is stable, name is a mutable
    attribute (§7). Never delete-and-recreate for a rename.
    """
    actor = _require_actor(user, "update warehouse")
    current = resolve_warehouse(warehouse)
    previous_state = _snapshot(current)
    values = {}
    if name is not _UNSET:
        clean = _clean_text(name, field="name")
        if not clean:
            raise WarehouseValidationError("Warehouse name is required.")
        values["name"] = clean
    if name_fa is not _UNSET:
        values["name_fa"] = _clean_text(name_fa, field="name_fa")
    changed = [f for f, v in values.items() if v != getattr(current, f)]
    if not changed:
        return current  # idempotent no-op
    for field in changed:
        setattr(current, field, values[field])
    with transaction.atomic():
        current.save(update_fields=changed)
        record_audit_event(
            user=actor, action=AuditAction.UPDATE, entity="Warehouse",
            entity_id=current.id, reference=current.name,
            previous_state=previous_state, new_state=_snapshot(current),
            reason="",
        )
    return current


def set_warehouse_active(warehouse, *, is_active, user=None, reason=""):
    """Deactivate/reactivate. Flag only — deletes nothing (§8/§9)."""
    actor = _require_actor(user, "change warehouse status")
    if not isinstance(reason, str):
        raise WarehouseValidationError("Warehouse reason must be text.")
    current = resolve_warehouse(warehouse)
    flag = bool(is_active)
    if current.is_active == flag:
        return current  # idempotent no-op
    previous_state = _snapshot(current)
    with transaction.atomic():
        current.is_active = flag
        current.save(update_fields=["is_active"])
        record_audit_event(
            user=actor, action=AuditAction.UPDATE, entity="Warehouse",
            entity_id=current.id, reference=current.name,
            previous_state=previous_state, new_state=_snapshot(current),
            reason=reason.strip(),
        )
    return current
