"""Restore the genesis head after test-database flushes; never repair history."""

from django.db import connections
from django.db.models.signals import post_migrate
from django.dispatch import receiver

GENESIS_HASH = "0" * 64


@receiver(post_migrate, dispatch_uid="security.ensure_empty_audit_chain_head")
def ensure_empty_audit_chain_head(sender, using="default", **kwargs):
    if getattr(sender, "name", None) != "security":
        return
    db = connections[using]
    tables = set(db.introspection.table_names())
    if "security_auditevent" not in tables or "security_auditchainhead" not in tables:
        # Older migration states used in migration tests intentionally lack
        # the chain table and must not be modified by this hook.
        return

    from security.models import AuditChainHead, AuditEvent

    events_exist = AuditEvent.objects.using(using).exists()
    head_exists = AuditChainHead.objects.using(using).filter(pk=1).exists()
    if events_exist and not head_exists:
        raise RuntimeError(
            "Audit events exist but the singleton chain head is missing; "
            "refusing to regenerate or guess the chain."
        )
    if not events_exist and not head_exists:
        AuditChainHead.objects.using(using).create(pk=1, head_hash=GENESIS_HASH)
