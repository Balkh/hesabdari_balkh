"""Create a separate encrypted escrow artifact only under local owner authority."""
import hmac

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from security.audit_chain import assert_audit_trigger_schema, verify_audit_chain
from security.backup_service import BackupError, load_backup_key_provider
from security.emergency_owner_key_service import (
    EmergencyOwnerKeyError, get_current_gm_for_local_operation,
    validate_current_gm_emergency_owner_key, emergency_owner_key_digest,
)
from security.local_console import LocalConsoleRequiredError, require_local_console
from security.models import AuditAction
from security.offline_recovery import create_recovery_bundle, parse_recovery_secret, prompt_secret
from security.services import record_audit_event


class Command(BaseCommand):
    help = "Create encrypted backup-key escrow under local GM emergency-owner-key authority; no plaintext export."

    def add_arguments(self, parser):
        parser.add_argument("--destination", required=True)
        parser.add_argument("--encryption-id", required=True)
        parser.add_argument("--signing-id", required=True)

    def handle(self, *args, **options):
        published = False
        try:
            require_local_console()
            raw_owner_key = prompt_secret("Current offline GM emergency owner key: ").strip()
            validate_current_gm_emergency_owner_key(raw_owner_key)
            raw_recovery = prompt_secret("Independent random 256-bit recovery secret (64 hex characters): ")
            confirmation = prompt_secret("Confirm separate recovery secret: ")
            if not hmac.compare_digest(raw_recovery, confirmation):
                raise BackupError("recovery secret confirmation does not match")
            secret = parse_recovery_secret(raw_recovery)
            # The current emergency key is base64url. Reject using its raw
            # decoded bytes as the separate escrow encryption secret.
            import base64
            owner_bytes = base64.urlsafe_b64decode(raw_owner_key + "=")
            if hmac.compare_digest(secret, owner_bytes):
                raise BackupError("recovery secret must be independent of the GM emergency owner key")
            provider = load_backup_key_provider()
            with transaction.atomic():
                # Recheck under the same locks held through the audit commit.
                validate_current_gm_emergency_owner_key(raw_owner_key)
                gm = get_current_gm_for_local_operation().user
                assert_audit_trigger_schema()
                verify_audit_chain()
                result = create_recovery_bundle(
                    options["destination"], provider=provider, recovery_secret=secret,
                    encryption_id=options["encryption_id"], signing_id=options["signing_id"])
                published = True
                record_audit_event(user=gm, action=AuditAction.AUDIT_CHECKPOINT,
                    entity="BACKUP_RECOVERY_BUNDLE", entity_id=result["artifact_sha256"][:32],
                    new_state={"artifact_sha256": result["artifact_sha256"]},
                    reason="Local owner created encrypted backup recovery bundle")
        except Exception as exc:
            if published:
                raise CommandError("encrypted bundle was written but audit commit failed; retain securely and investigate") from None
            if isinstance(exc, (BackupError, EmergencyOwnerKeyError, LocalConsoleRequiredError)):
                raise CommandError(str(exc)) from None
            raise CommandError("recovery bundle creation failed; no success accepted") from None
        self.stdout.write(self.style.SUCCESS("Encrypted recovery bundle created."))
        self.stdout.write("Record this PUBLIC fingerprint independently of the bundle: " + result["trusted_public_sha256"])
        self.stdout.write("Artifact SHA-256: " + result["artifact_sha256"])
