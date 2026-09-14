"""Unit-of-measure master services (Phase 4.1).

Identity only: validated identity + audit. No conversion engine, no stock,
no behavior beyond that. Interpretation record U-3/R-11.
"""

from django.db import transaction

from security.models import AuditAction
from security.services import record_audit_event

from .models import UnitOfMeasure


class UOMValidationError(ValueError):
    """Deterministic UOM rejection (service-error convention)."""


_UNSET = object()


def _require_actor(user, action):
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        raise UOMValidationError(
            f"Authorization required to {action}: user must be a user."
        )
    return user


def _clean_text(value, *, field):
    if not isinstance(value, str):
        raise UOMValidationError(f"UOM {field} must be text.")
    return value.strip()


def _snapshot(unit):
    return {
        "id": unit.id,
        "name": unit.name,
        "name_fa": unit.name_fa,
        "is_active": unit.is_active,
    }


def resolve_uom(ref):
    """Accept a UnitOfMeasure instance or pk; deterministic miss error."""
    if isinstance(ref, UnitOfMeasure):
        if ref.pk is None:
            raise UOMValidationError("UOM does not exist.")
        return ref
    try:
        found = UnitOfMeasure.objects.filter(pk=ref).first()
    except (TypeError, ValueError):
        found = None
    if found is None:
        raise UOMValidationError("UOM does not exist.")
    return found


def create_uom(*, name, name_fa="", is_active=True, user=None):
    """Create a unit of measure. Names may repeat (U-3: non-unique)."""
    actor = _require_actor(user, "create UOM")
    clean_name = _clean_text(name, field="name")
    if not clean_name:
        raise UOMValidationError("UOM name is required.")
    clean_fa = _clean_text(name_fa, field="name_fa")
    with transaction.atomic():
        unit = UnitOfMeasure.objects.create(
            name=clean_name, name_fa=clean_fa, is_active=bool(is_active)
        )
        record_audit_event(
            user=actor, action=AuditAction.CREATE, entity="UnitOfMeasure",
            entity_id=unit.id, reference=unit.name,
            previous_state=None, new_state=_snapshot(unit), reason="",
        )
    return unit


def update_uom(unit, *, name=_UNSET, name_fa=_UNSET, user=None):
    """Partial update. No changes → idempotent no-op, no audit row."""
    actor = _require_actor(user, "update UOM")
    current = resolve_uom(unit)
    previous_state = _snapshot(current)
    changed = False
    if name is not _UNSET:
        clean = _clean_text(name, field="name")
        if not clean:
            raise UOMValidationError("UOM name is required.")
        if clean != current.name:
            current.name = clean
            changed = True
    if name_fa is not _UNSET:
        clean_fa = _clean_text(name_fa, field="name_fa")
        if clean_fa != current.name_fa:
            current.name_fa = clean_fa
            changed = True
    if not changed:
        return current
    with transaction.atomic():
        current.save(update_fields=["name", "name_fa"])
        record_audit_event(
            user=actor, action=AuditAction.UPDATE, entity="UnitOfMeasure",
            entity_id=current.id, reference=current.name,
            previous_state=previous_state, new_state=_snapshot(current),
            reason="",
        )
    return current


def set_uom_active(unit, *, is_active, user=None, reason=""):
    """Deactivate/reactivate. Reason optional (contract is silent)."""
    actor = _require_actor(user, "change UOM status")
    if not isinstance(reason, str):
        raise UOMValidationError("UOM reason must be text.")
    current = resolve_uom(unit)
    flag = bool(is_active)
    if current.is_active == flag:
        return current  # idempotent no-op
    previous_state = _snapshot(current)
    with transaction.atomic():
        current.is_active = flag
        current.save(update_fields=["is_active"])
        record_audit_event(
            user=actor, action=AuditAction.UPDATE, entity="UnitOfMeasure",
            entity_id=current.id, reference=current.name,
            previous_state=previous_state, new_state=_snapshot(current),
            reason=reason.strip(),
        )
    return current
