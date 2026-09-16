"""Cash account master services (Phase 4.4).

Validated identity + active flag + audit. Names may repeat (OD-8); no
codes of any kind (OD-6); no currency (OD-5); no relations, no balance
or ledger behavior (§7/§8). Deactivation is a flag only — it deletes
nothing and enforces nothing in this phase (§11).
"""

from django.db import transaction

from security.models import AuditAction
from security.services import record_audit_event

from .models import CashAccount


class CashAccountValidationError(ValueError):
    """Deterministic cash account rejection (service-error convention)."""


_UNSET = object()


def _require_actor(user, action):
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        raise CashAccountValidationError(
            f"Authorization required to {action}: user must be a user."
        )
    return user


def _clean_text(value, *, field):
    if not isinstance(value, str):
        raise CashAccountValidationError(
            f"Cash account {field} must be text."
        )
    return value.strip()


def _snapshot(account):
    return {
        "id": account.id,
        "name": account.name,
        "name_fa": account.name_fa,
        "is_active": account.is_active,
    }


def resolve_cash_account(ref):
    """Accept a CashAccount instance or pk; deterministic miss error."""
    if isinstance(ref, CashAccount):
        if ref.pk is None:
            raise CashAccountValidationError("Cash account does not exist.")
        return ref
    try:
        found = CashAccount.objects.filter(pk=ref).first()
    except (TypeError, ValueError):
        found = None
    if found is None:
        raise CashAccountValidationError("Cash account does not exist.")
    return found


def create_cash_account(*, name, name_fa="", is_active=True, user=None):
    """Create a cash account. Names may repeat (no invented uniqueness)."""
    actor = _require_actor(user, "create cash account")
    clean_name = _clean_text(name, field="name")
    if not clean_name:
        raise CashAccountValidationError("Cash account name is required.")
    with transaction.atomic():
        account = CashAccount.objects.create(
            name=clean_name,
            name_fa=_clean_text(name_fa, field="name_fa"),
            is_active=bool(is_active),
        )
        record_audit_event(
            user=actor, action=AuditAction.CREATE, entity="CashAccount",
            entity_id=account.id, reference=account.name,
            previous_state=None, new_state=_snapshot(account), reason="",
        )
    return account


def update_cash_account(account, *, name=_UNSET, name_fa=_UNSET, user=None):
    """Partial update. No changes → idempotent no-op, no audit row.

    Rename keeps the primary key: identity is stable, name is a mutable
    attribute. Never delete-and-recreate for a rename.
    """
    actor = _require_actor(user, "update cash account")
    current = resolve_cash_account(account)
    previous_state = _snapshot(current)
    values = {}
    if name is not _UNSET:
        clean = _clean_text(name, field="name")
        if not clean:
            raise CashAccountValidationError(
                "Cash account name is required."
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
            user=actor, action=AuditAction.UPDATE, entity="CashAccount",
            entity_id=current.id, reference=current.name,
            previous_state=previous_state, new_state=_snapshot(current),
            reason="",
        )
    return current


def set_cash_account_active(account, *, is_active, user=None, reason=""):
    """Deactivate/reactivate. Flag only — deletes nothing (§11/§13)."""
    actor = _require_actor(user, "change cash account status")
    if not isinstance(reason, str):
        raise CashAccountValidationError("Cash account reason must be text.")
    current = resolve_cash_account(account)
    flag = bool(is_active)
    if current.is_active == flag:
        return current  # idempotent no-op
    previous_state = _snapshot(current)
    with transaction.atomic():
        current.is_active = flag
        current.save(update_fields=["is_active"])
        record_audit_event(
            user=actor, action=AuditAction.UPDATE, entity="CashAccount",
            entity_id=current.id, reference=current.name,
            previous_state=previous_state, new_state=_snapshot(current),
            reason=reason.strip(),
        )
    return current
