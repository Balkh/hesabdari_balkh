from django.core.management.base import BaseCommand, CommandError

from security.backup_service import (
    BackupError,
    BackupKeyUnavailable,
    create_encrypted_database_backup,
    load_backup_key_provider,
)
from security.management.commands._backup_command_support import require_active_gm


class Command(BaseCommand):
    help = "Create an AES-256-GCM encrypted database backup with an Ed25519 signed audit-chain checkpoint."

    def add_arguments(self, parser):
        parser.add_argument("--destination", required=True)
        parser.add_argument(
            "--retention-class",
            choices=("daily", "pre_upgrade", "month_end"),
            default="daily",
        )
        parser.add_argument("--actor-username", required=True)

    def handle(self, *args, **options):
        actor = require_active_gm(options["actor_username"])
        try:
            provider = load_backup_key_provider()
            result = create_encrypted_database_backup(
                options["destination"],
                provider=provider,
                actor=actor,
                retention_class=options["retention_class"],
            )
        except (BackupError, BackupKeyUnavailable) as exc:
            raise CommandError(str(exc)) from None

        self.stdout.write(self.style.SUCCESS(
            f"Encrypted backup created: {result['backup_path']}\n"
            f"Backup SHA-256: {result['backup_sha256']}\n"
            f"Signed checkpoint: {result['checkpoint_path']}\n"
            f"Covered audit events: {result['covered_event_count']}\n"
            f"Covered chain head: {result['covered_head_hash']}\n"
            f"Retention class: {result['retention_class']}"
        ))
