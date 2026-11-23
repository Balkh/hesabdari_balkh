from django.core.management.base import BaseCommand, CommandError

from security.backup_service import (
    BackupError,
    BackupKeyUnavailable,
    load_backup_key_provider,
    verify_encrypted_database_backup,
    _record_checkpoint_event,
)
from security.management.commands._backup_command_support import require_active_gm


class Command(BaseCommand):
    help = "Decrypt to disposable storage, restore without touching the live database, and fully verify the audit chain."

    def add_arguments(self, parser):
        parser.add_argument("--backup", required=True)
        parser.add_argument("--checkpoint", required=True)
        parser.add_argument("--actor-username", required=True)

    def handle(self, *args, **options):
        actor = require_active_gm(options["actor_username"])
        try:
            provider = load_backup_key_provider()
            result = verify_encrypted_database_backup(
                options["backup"],
                options["checkpoint"],
                provider=provider,
            )
            from django.db import transaction
            from security.models import AuditAction
            from security.services import record_audit_event

            with transaction.atomic():
                record_audit_event(
                    user=actor,
                    action=AuditAction.AUDIT_CHECKPOINT,
                    entity="BACKUP_RESTORE_VERIFICATION",
                    entity_id=result["backup_sha256"][:32],
                    reference=options["backup"],
                    new_state={
                        "verified": True,
                        "event_count": result["event_count"],
                        "head_hash": result["head_hash"],
                        "last_event_id": result["last_event_id"],
                        "retention_class": result["retention_class"],
                    },
                    reason="GM completed disposable restore and full audit-chain verification",
                )
        except (BackupError, BackupKeyUnavailable) as exc:
            raise CommandError(str(exc)) from None

        self.stdout.write(self.style.SUCCESS(
            f"BACKUP RESTORE + AUDIT CHAIN VERIFIED: {result['event_count']} events\n"
            f"Head: {result['head_hash']}\n"
            f"Backup SHA-256: {result['backup_sha256']}"
        ))
