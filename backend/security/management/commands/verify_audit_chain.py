from django.core.management.base import BaseCommand, CommandError

from security.audit_chain import (
    AuditChainVerificationError,
    verify_audit_chain,
)


class Command(BaseCommand):
    help = "Verify the complete append-only audit hash chain and singleton head."

    def handle(self, *args, **options):
        try:
            result = verify_audit_chain()
        except AuditChainVerificationError as exc:
            raise CommandError(f"AUDIT CHAIN INVALID: {exc}") from None
        self.stdout.write(
            self.style.SUCCESS(
                "AUDIT CHAIN VERIFIED: "
                f"{result['event_count']} events; "
                f"head={result['head_hash']}; "
                f"last_event_id={result['last_event_id']}"
            )
        )
