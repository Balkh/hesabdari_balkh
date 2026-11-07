"""Issue a one-time initial-GM bootstrap token on a local interactive console."""
from __future__ import annotations

import hashlib
import secrets
import sys
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from security.gm_slot import GM_SLOT_CODE, inspect_slot_consistency
from security.models import AuditAction, AuditEvent, GMRoleSlot, UserRoleAssignment
from security.mfa_models import SecurityBootstrapToken

TOKEN_LIFETIME = timedelta(minutes=10)


def _require_tty():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise CommandError("GM bootstrap is local-only and requires an interactive terminal")


class Command(BaseCommand):
    help = "Issue a one-time, 10-minute token for initial local GM provisioning."

    def handle(self, *args, **options):
        _require_tty()
        raw_token = secrets.token_urlsafe(32)  # 256 bits from the OS CSPRNG.
        digest = hashlib.sha256(raw_token.encode("ascii")).hexdigest()
        now = timezone.now()

        with transaction.atomic():
            try:
                slot = GMRoleSlot.objects.select_for_update().get(code=GM_SLOT_CODE)
            except GMRoleSlot.DoesNotExist:
                raise CommandError("GM singleton slot is missing; apply security migrations first")
            if slot.assignment_id is not None:
                raise CommandError("GM slot is already held; initial bootstrap is not permitted")
            if UserRoleAssignment.objects.filter(role__code=GM_SLOT_CODE).exists():
                raise CommandError("GM assignment history exists; initial bootstrap is permanently closed")
            if SecurityBootstrapToken.objects.filter(
                purpose=SecurityBootstrapToken.INITIAL_GM,
                consumed_at__isnull=False,
            ).exists():
                raise CommandError("initial GM bootstrap was already consumed; use only the separate offline recovery process")
            findings = inspect_slot_consistency()
            if findings:
                raise CommandError(
                    "GM slot state is inconsistent; resolve preflight findings before bootstrap: "
                    + "; ".join(code for code, _message in findings)
                )

            SecurityBootstrapToken.objects.filter(
                purpose=SecurityBootstrapToken.INITIAL_GM,
                consumed_at__isnull=True,
                revoked_at__isnull=True,
            ).update(revoked_at=now)
            record = SecurityBootstrapToken.objects.create(
                purpose=SecurityBootstrapToken.INITIAL_GM,
                token_hash=digest,
                issued_at=now,
                expires_at=now + TOKEN_LIFETIME,
            )
            AuditEvent.objects.create(
                user=None,
                action=AuditAction.CREATE,
                entity="GM_BOOTSTRAP_TOKEN",
                entity_id=str(record.pk),
                new_state={"purpose": SecurityBootstrapToken.INITIAL_GM, "expires_at": record.expires_at.isoformat()},
            )

        # The raw token is emitted exactly once to the already-validated
        # local terminal. Only its SHA-256 digest is retained in the database.
        self.stdout.write("ONE-TIME INITIAL GM BOOTSTRAP TOKEN (valid for 10 minutes):")
        self.stdout.write(raw_token)
        self.stdout.write("Enter this token only in the local bootstrap_gm command. Do not store it in logs or shell history.")
