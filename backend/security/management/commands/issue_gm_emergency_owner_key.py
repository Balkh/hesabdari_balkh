"""Rotate the separate offline GM owner key from a local interactive terminal."""
from __future__ import annotations

import getpass
import hmac
import sys

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from security.management.commands.bootstrap_gm import _load_key_provider
from security.mfa_service import MFAInvalidCode
from security.emergency_owner_key_service import (
    EmergencyOwnerKeyError,
    generate_emergency_owner_key,
    get_current_gm_for_local_operation,
    issue_gm_emergency_owner_key,
)


def _require_tty():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise CommandError("GM emergency owner-key rotation is local-only and requires an interactive terminal")


def _confirm_saved_once(stdout, raw_key):
    stdout.write("OFFLINE GM EMERGENCY OWNER KEY — shown once; store it separately from this computer:")
    stdout.write(raw_key)
    stdout.write("Do not save this key in the ERP database, shell history, cloud notes, or ordinary backup.")
    expected = raw_key[-8:]
    actual = getpass.getpass("After saving it offline, enter its last 8 characters to confirm: ").strip()
    if not hmac.compare_digest(actual, expected):
        raise CommandError("owner-key confirmation failed; discard the displayed candidate key")


class Command(BaseCommand):
    help = "Rotate the offline GM emergency owner key after local password and TOTP verification."

    def handle(self, *args, **options):
        _require_tty()
        gm = get_current_gm_for_local_operation().user
        password = getpass.getpass("Current GM password: ")
        totp_code = getpass.getpass("Current six-digit GM authenticator code: ").strip()
        provider = _load_key_provider()
        candidate = generate_emergency_owner_key()
        _confirm_saved_once(self.stdout, candidate)
        try:
            row = issue_gm_emergency_owner_key(
                gm,
                password=password,
                totp_code=totp_code,
                provider=provider,
                new_owner_key=candidate,
                at=timezone.now(),
            )
        except (EmergencyOwnerKeyError, MFAInvalidCode) as exc:
            raise CommandError(str(exc) + "; discard the displayed candidate key") from None
        self.stdout.write(self.style.SUCCESS("GM emergency owner key rotated and stored as a hash."))
        self.stdout.write(f"Owner-key record: {row.pk}. Keep the raw key offline; it cannot be displayed again.")


