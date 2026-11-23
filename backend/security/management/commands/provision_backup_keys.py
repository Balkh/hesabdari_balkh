from django.core.management.base import BaseCommand, CommandError

from security.backup_service import BackupKeyUnavailable, load_backup_key_provider
from security.management.commands._backup_command_support import require_active_gm


class Command(BaseCommand):
    help = "Provision separate AES-256 backup and Ed25519 checkpoint keys in the GM Windows Credential Manager vault."

    def add_arguments(self, parser):
        parser.add_argument("--actor-username", required=True)

    def handle(self, *args, **options):
        require_active_gm(options["actor_username"])
        try:
            provider = load_backup_key_provider()
            provision = getattr(provider, "provision_backup_keys", None)
            if not callable(provision):
                raise BackupKeyUnavailable(
                    "configured backup key provider does not support protected key provisioning"
                )
            result = provision()
        except BackupKeyUnavailable as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS(
            "Backup keys provisioned in the current GM OS user's protected key vault. "
            f"AES key ID: {result['backup_encryption_key_id']}; "
            f"checkpoint key ID: {result['checkpoint_signing_key_id']}. "
            "No key bytes were displayed or stored in the database."
        ))
