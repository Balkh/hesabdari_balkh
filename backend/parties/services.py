"""Party master services (Phase 4.2, Option A).

Validated identity + roles + audit. The role invariant (at least one of
customer/supplier) is enforced HERE and by the `party_has_role` database
check (FR-3). No codes, no numbering, no financial concepts, no behavior
beyond master maintenance (FR-4/FR-8/FR-9).
"""

from django.db import transaction

from security.models import AuditAction
from security.services import record_audit_event

from .models import Party


class PartyValidationError(ValueError):
    """Deterministic party rejection (service-error convention)."""


_UNSET = object()


def _require_actor(user, action):
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        raise PartyValidationError(
            f"Authorization required to {action}: user must be a user."
        )
    return user


def _clean_text(value, *, field):
    if not isinstance(value, str):
        raise PartyValidationError(f"Party {field} must be text.")
    return value.strip()


def _clean_roles(is_customer, is_supplier):
    flags = (bool(is_customer), bool(is_supplier))
    if not (flags[0] or flags[1]):
        raise PartyValidationError(
            "Party must have at least one role: customer or supplier."
        )
    return flags


def _snapshot(party):
    return {
        "id": party.id,
        "name": party.name,
        "name_fa": party.name_fa,
        "is_customer": party.is_customer,
        "is_supplier": party.is_supplier,
        "phone": party.phone,
        "address": party.address,
        "note": party.note,
        "is_active": party.is_active,
    }


def resolve_party(ref):
    """Accept a Party instance or pk; deterministic miss error."""
    if isinstance(ref, Party):
        if ref.pk is None:
            raise PartyValidationError("Party does not exist.")
        return ref
    try:
        found = Party.objects.filter(pk=ref).first()
    except (TypeError, ValueError):
        found = None
    if found is None:
        raise PartyValidationError("Party does not exist.")
    return found


def create_party(*, name, name_fa="", is_customer=False, is_supplier=False,
                 phone="", address="", note="", is_active=True, user=None):
    """Create a party. Names may repeat (no invented uniqueness)."""
    actor = _require_actor(user, "create party")
    clean_name = _clean_text(name, field="name")
    if not clean_name:
        raise PartyValidationError("Party name is required.")
    customer, supplier = _clean_roles(is_customer, is_supplier)
    with transaction.atomic():
        party = Party.objects.create(
            name=clean_name,
            name_fa=_clean_text(name_fa, field="name_fa"),
            is_customer=customer, is_supplier=supplier,
            phone=_clean_text(phone, field="phone"),
            address=_clean_text(address, field="address"),
            note=_clean_text(note, field="note"),
            is_active=bool(is_active),
        )
        record_audit_event(
            user=actor, action=AuditAction.CREATE, entity="Party",
            entity_id=party.id, reference=party.name,
            previous_state=None, new_state=_snapshot(party), reason="",
        )
    return party


def update_party(party, *, name=_UNSET, name_fa=_UNSET,
                 is_customer=_UNSET, is_supplier=_UNSET, phone=_UNSET,
                 address=_UNSET, note=_UNSET, user=None):
    """Partial update. No changes → idempotent no-op, no audit row.

    Role edits re-validate the invariant against the FINAL flags, so
    removing one role of a dual-role party succeeds while removing the
    last role is rejected.
    """
    actor = _require_actor(user, "update party")
    current = resolve_party(party)
    previous_state = _snapshot(current)
    values = {}
    if name is not _UNSET:
        clean = _clean_text(name, field="name")
        if not clean:
            raise PartyValidationError("Party name is required.")
        values["name"] = clean
    if name_fa is not _UNSET:
        values["name_fa"] = _clean_text(name_fa, field="name_fa")
    if phone is not _UNSET:
        values["phone"] = _clean_text(phone, field="phone")
    if address is not _UNSET:
        values["address"] = _clean_text(address, field="address")
    if note is not _UNSET:
        values["note"] = _clean_text(note, field="note")
    new_customer = (current.is_customer if is_customer is _UNSET
                    else bool(is_customer))
    new_supplier = (current.is_supplier if is_supplier is _UNSET
                    else bool(is_supplier))
    if is_customer is not _UNSET or is_supplier is not _UNSET:
        new_customer, new_supplier = _clean_roles(new_customer, new_supplier)
    values["is_customer"] = new_customer
    values["is_supplier"] = new_supplier
    changed = [f for f, v in values.items() if v != getattr(current, f)]
    if not changed:
        return current
    for field in changed:
        setattr(current, field, values[field])
    with transaction.atomic():
        current.save(update_fields=changed)
        record_audit_event(
            user=actor, action=AuditAction.UPDATE, entity="Party",
            entity_id=current.id, reference=current.name,
            previous_state=previous_state, new_state=_snapshot(current),
            reason="",
        )
    return current


def set_party_active(party, *, is_active, user=None, reason=""):
    """Deactivate/reactivate. Flag only — deletes nothing (FR-7)."""
    actor = _require_actor(user, "change party status")
    if not isinstance(reason, str):
        raise PartyValidationError("Party reason must be text.")
    current = resolve_party(party)
    flag = bool(is_active)
    if current.is_active == flag:
        return current  # idempotent no-op
    previous_state = _snapshot(current)
    with transaction.atomic():
        current.is_active = flag
        current.save(update_fields=["is_active"])
        record_audit_event(
            user=actor, action=AuditAction.UPDATE, entity="Party",
            entity_id=current.id, reference=current.name,
            previous_state=previous_state, new_state=_snapshot(current),
            reason=reason.strip(),
        )
    return current
