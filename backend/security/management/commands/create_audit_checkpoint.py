from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from security.backup_service import (
    BackupError,
    BackupKeyUnavailable,
    create_audit_checkpoint_file,
    load_backup_key_provider,
    _assert_backup_destination_is_external,
)
from security.management.commands._backup_command_support import require_active_gm


class Command(BaseCommand):
    help = "Create a signed daily or high-activity shift audit-chain checkpoint on separate offline storage."

    def add_arguments(self, parser):
        parser.add_argument("--destination", required=True)
        parser.add_argument("--cadence", choices=("daily", "shift"), default="daily")
        parser.add_argument("--reason", required=True)
        parser.add_argument("--actor-username", required=True)

    def handle(self, *args, **options):
        actor = require_active_gm(options["actor_username"])
        target = Path(options["destination"]).expanduser()
        try:
            _assert_backup_destination_is_external(target.parent)
            provider = load_backup_key_provider()
            result = create_audit_checkpoint_file(
                target,
                provider=provider,
                actor=actor,
                cadence=options["cadence"],
                reason=options["reason"],
            )
        except (BackupError, BackupKeyUnavailable) as exc:
            raise CommandError(str(exc)) from None

        self.stdout.write(self.style.SUCCESS(
            f"Signed {options['cadence']} checkpoint created: {result['path']}\n"
            f"SHA-256: {result['sha256']}\n"
            f"Signing key ID: {result['signing_key_id']}"
        ))
