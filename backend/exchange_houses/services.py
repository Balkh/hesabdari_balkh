"""Exchange house master services (Phase 4.4).

Validated identity + active flag + audit. Names may repeat (OD-9); no
codes of any kind (OD-7); no currency (OD-5); no contact fields (OD-13);
no relations, no balance or ledger behavior (§7/§8). Deactivation is a
flag only — it deletes nothing and enforces nothing in this phase (§11).
"""

from django.db import transaction

from security.models import AuditAction
from security.services import record_audit_event

from .models import ExchangeHouse


class ExchangeHouseValidationError(ValueError):
    """Deterministic exchange house rejection (service-error convention)."""


_UNSET = object()


def _require_actor(user, action):
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        raise ExchangeHouseValidationError(
            f"Authorization required to {action}: user must be a user."
        )
    return user


def _clean_text(value, *, field):
    if not isinstance(value, str):
        raise ExchangeHouseValidationError(
            f"Exchange house {field} must be text."
        )
    return value.strip()


def _snapshot(house):
    return {
        "id": house.id,
        "name": house.name,
        "name_fa": house.name_fa,
        "is_active": house.is_active,
    }


def resolve_exchange_house(ref):
    """Accept an ExchangeHouse instance or pk; deterministic miss error."""
    if isinstance(ref, ExchangeHouse):
        if ref.pk is None:
            raise ExchangeHouseValidationError(
                "Exchange house does not exist."
            )
        return ref
    try:
        found = ExchangeHouse.objects.filter(pk=ref).first()
    except (TypeError, ValueError):
        found = None
    if found is None:
        raise ExchangeHouseValidationError("Exchange house does not exist.")
    return found


def create_exchange_house(*, name, name_fa="", is_active=True, user=None):
    """Create an exchange house. Names may repeat (no invented uniqueness)."""
    actor = _require_actor(user, "create exchange house")
    clean_name = _clean_text(name, field="name")
    if not clean_name:
        raise ExchangeHouseValidationError(
            "Exchange house name is required."
        )
    with transaction.atomic():
        house = ExchangeHouse.objects.create(
            name=clean_name,
            name_fa=_clean_text(name_fa, field="name_fa"),
            is_active=bool(is_active),
        )
        record_audit_event(
            user=actor, action=AuditAction.CREATE, entity="ExchangeHouse",
            entity_id=house.id, reference=house.name,
            previous_state=None, new_state=_snapshot(house), reason="",
        )
    return house


def update_exchange_house(house, *, name=_UNSET, name_fa=_UNSET, user=None):
    """Partial update. No changes → idempotent no-op, no audit row.

    Rename keeps the primary key: identity is stable, name is a mutable
    attribute. Never delete-and-recreate for a rename.
    """
    actor = _require_actor(user, "update exchange house")
    current = resolve_exchange_house(house)
    previous_state = _snapshot(current)
    values = {}
    if name is not _UNSET:
        clean = _clean_text(name, field="name")
        if not clean:
            raise ExchangeHouseValidationError(
                "Exchange house name is required."
            )
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
            user=actor, action=AuditAction.UPDATE, entity="ExchangeHouse",
            entity_id=current.id, reference=current.name,
            previous_state=previous_state, new_state=_snapshot(current),
            reason="",
        )
    return current


def set_exchange_house_active(house, *, is_active, user=None, reason=""):
    """Deactivate/reactivate. Flag only — deletes nothing (§11/§13)."""
    actor = _require_actor(user, "change exchange house status")
    if not isinstance(reason, str):
        raise ExchangeHouseValidationError(
            "Exchange house reason must be text."
        )
    current = resolve_exchange_house(house)
    flag = bool(is_active)
    if current.is_active == flag:
        return current  # idempotent no-op
    previous_state = _snapshot(current)
    with transaction.atomic():
        current.is_active = flag
        current.save(update_fields=["is_active"])
        record_audit_event(
            user=actor, action=AuditAction.UPDATE, entity="ExchangeHouse",
            entity_id=current.id, reference=current.name,
            previous_state=previous_state, new_state=_snapshot(current),
            reason=reason.strip(),
        )
    return current
