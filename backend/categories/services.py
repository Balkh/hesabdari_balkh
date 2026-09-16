"""Category master services (Phase 4.1).

Identity only: validated identity + audit. No stock, no accounting, no
behavior beyond that. Interpretation record U-2/R-1/R-9/R-11.
"""

from django.db import transaction

from security.models import AuditAction
from security.services import record_audit_event

from .models import Category


class CategoryValidationError(ValueError):
    """Deterministic category rejection (service-error convention)."""


_UNSET = object()


def _require_actor(user, action):
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        raise CategoryValidationError(
            f"Authorization required to {action}: user must be a user."
        )
    return user


def _clean_text(value, *, field):
    if not isinstance(value, str):
        raise CategoryValidationError(f"Category {field} must be text.")
    return value.strip()


def _snapshot(category):
    return {
        "id": category.id,
        "name": category.name,
        "name_fa": category.name_fa,
        "is_active": category.is_active,
    }


def resolve_category(ref):
    """Accept a Category instance or pk; deterministic miss error."""
    if isinstance(ref, Category):
        if ref.pk is None:
            raise CategoryValidationError("Category does not exist.")
        return ref
    try:
        found = Category.objects.filter(pk=ref).first()
    except (TypeError, ValueError):
        found = None
    if found is None:
        raise CategoryValidationError("Category does not exist.")
    return found


def create_category(*, name, name_fa="", is_active=True, user=None):
    """Create a category. Names may repeat (U-2: non-unique by decision)."""
    actor = _require_actor(user, "create category")
    clean_name = _clean_text(name, field="name")
    if not clean_name:
        raise CategoryValidationError("Category name is required.")
    clean_fa = _clean_text(name_fa, field="name_fa")
    with transaction.atomic():
        category = Category.objects.create(
            name=clean_name, name_fa=clean_fa, is_active=bool(is_active)
        )
        record_audit_event(
            user=actor, action=AuditAction.CREATE, entity="Category",
            entity_id=category.id, reference=category.name,
            previous_state=None, new_state=_snapshot(category), reason="",
        )
    return category


def update_category(category, *, name=_UNSET, name_fa=_UNSET, user=None):
    """Partial update. No changes → idempotent no-op, no audit row."""
    actor = _require_actor(user, "update category")
    current = resolve_category(category)
    previous_state = _snapshot(current)
    changed = False
    if name is not _UNSET:
        clean = _clean_text(name, field="name")
        if not clean:
            raise CategoryValidationError("Category name is required.")
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
            user=actor, action=AuditAction.UPDATE, entity="Category",
            entity_id=current.id, reference=current.name,
            previous_state=previous_state, new_state=_snapshot(current),
            reason="",
        )
    return current


def set_category_active(category, *, is_active, user=None, reason=""):
    """Deactivate/reactivate. Reason optional (contract is silent)."""
    actor = _require_actor(user, "change category status")
    if not isinstance(reason, str):
        raise CategoryValidationError("Category reason must be text.")
    current = resolve_category(category)
    flag = bool(is_active)
    if current.is_active == flag:
        return current  # idempotent no-op
    previous_state = _snapshot(current)
    with transaction.atomic():
        current.is_active = flag
        current.save(update_fields=["is_active"])
        record_audit_event(
            user=actor, action=AuditAction.UPDATE, entity="Category",
            entity_id=current.id, reference=current.name,
            previous_state=previous_state, new_state=_snapshot(current),
            reason=reason.strip(),
        )
    return current
