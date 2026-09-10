"""Audit recording service — thin writer over the AuditEvent model (Stage 2.3)."""

from .models import AuditAction, AuditEvent


def record_audit_event(*, user=None, action, entity, entity_id="", reference="",
                       previous_state=None, new_state=None, reason=""):
    """Persist one audit event. Timestamps are UTC (USE_TZ + TIME_ZONE=UTC)."""
    if action not in AuditAction.values:
        raise ValueError(f"Unknown audit action: {action!r}")
    return AuditEvent.objects.create(
        user=user, action=action, entity=entity, entity_id=str(entity_id),
        reference=reference, previous_state=previous_state, new_state=new_state,
        reason=reason,
    )
