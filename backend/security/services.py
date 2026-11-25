"""Single chain-aware append service for every production audit event."""

from django.db import connection, transaction

from security.audit_chain import append_audit_event
from security.models import AuditAction


def record_audit_event(
    *,
    user=None,
    action,
    entity,
    entity_id="",
    reference="",
    previous_state=None,
    new_state=None,
    reason="",
    authorization_context=None,
):
    """Append one immutable audit event inside the caller's business transaction."""
    try:
        if action not in AuditAction.values:
            raise ValueError(f"Unknown audit action: {action!r}")
        return append_audit_event(
            user=user,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            reference=reference,
            previous_state=previous_state,
            new_state=new_state,
            reason=reason,
            authorization_context=authorization_context,
        )
    except Exception:
        # A Python validation/serialization/head-save failure does not
        # necessarily mark Django's transaction for rollback. A caller that
        # catches it inside the same atomic block must not commit its partial
        # business/audit changes. Mark that block rollback-only and preserve
        # the original error. Callers must still propagate across any outer
        # business boundary that contains earlier work.
        if connection.in_atomic_block:
            transaction.set_rollback(True)
        raise
