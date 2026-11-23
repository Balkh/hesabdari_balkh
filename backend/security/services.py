"""Single chain-aware append service for every production audit event."""

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
