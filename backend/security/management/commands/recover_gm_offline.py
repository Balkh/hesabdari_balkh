"""Recover only the existing singleton GM using the separately held offline owner key."""
from __future__ import annotations

import getpass
import hmac
import sys
from urllib.parse import quote

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from security.management.commands.bootstrap_gm import _load_key_provider
from security.emergency_owner_key_service import (
    EmergencyOwnerKeyError,
    generate_emergency_owner_key,
    get_current_gm_for_local_operation,
    recover_existing_gm_offline,
    validate_current_gm_emergency_owner_key,
)
from security.mfa import generate_totp_secret


def _require_tty():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise CommandError("GM emergency recovery is local-only and requires an interactive terminal")


def _confirm_saved_once(stdout, raw_key):
    stdout.write("REPLACEMENT OFFLINE GM EMERGENCY OWNER KEY — shown once:")
    stdout.write(raw_key)
    stdout.write("Save this key offline and separately from this computer.")
    actual = getpass.getpass("After saving it offline, enter its last 8 characters to confirm: ").strip()
    if not hmac.compare_digest(actual, raw_key[-8:]):
        raise CommandError("owner-key confirmation failed; discard the displayed replacement key")


class Command(BaseCommand):
    help = "Recover the existing GM in place using the separate offline emergency owner key."

    def handle(self, *args, **options):
        _require_tty()
        gm = get_current_gm_for_local_operation().user
        raw_owner_key = getpass.getpass("Offline GM emergency owner key: ").strip()
        try:
            validate_current_gm_emergency_owner_key(raw_owner_key)
        except EmergencyOwnerKeyError as exc:
            raise CommandError(str(exc)) from None
        new_password = getpass.getpass("New GM password: ")
        confirm_password = getpass.getpass("Confirm new GM password: ")
        if not new_password or not hmac.compare_digest(new_password, confirm_password):
            raise CommandError("new password is empty or the confirmation does not match")
        try:
            validate_password(new_password, user=gm)
        except ValidationError as exc:
            raise CommandError("new password does not satisfy policy: " + "; ".join(exc.messages)) from None

        provider = _load_key_provider()
        new_secret = generate_totp_secret()
        new_owner_key = generate_emergency_owner_key()
        now = timezone.now()
        label = quote(f"Hesabdari Balkh:{gm.get_username()}", safe="")
        issuer = quote("Hesabdari Balkh", safe="")
        uri = (
            f"otpauth://totp/{label}?secret={new_secret}&issuer={issuer}"
            "&algorithm=SHA1&digits=6&period=30"
        )
        self.stdout.write("Configure a NEW authenticator device with this URI (shown once):")
        self.stdout.write(uri)
        totp_code = getpass.getpass("Enter the current six-digit code from the new authenticator: ").strip()
        _confirm_saved_once(self.stdout, new_owner_key)

        try:
            gm_user, recovery_codes, revoked_sessions, disabled_devices = recover_existing_gm_offline(
                raw_owner_key,
                new_owner_key=new_owner_key,
                new_password=new_password,
                new_totp_secret=new_secret,
                new_totp_code=totp_code,
                provider=provider,
                at=now,
            )
        except EmergencyOwnerKeyError as exc:
            raise CommandError(str(exc) + "; discard the displayed replacement owner key and new authenticator seed") from None
        except Exception:
            raise CommandError("offline GM recovery failed and changes were rolled back; discard the displayed replacement owner key and new authenticator seed") from None

        self.stdout.write(self.style.SUCCESS("Existing GM credentials recovered in place; singleton assignment was preserved."))
        self.stdout.write(f"Revoked sessions: {revoked_sessions}; disabled previous MFA devices: {disabled_devices}.")
        self.stdout.write("Save these ten NEW GM recovery codes offline. They are shown only once:")
        for index, raw in enumerate(recovery_codes, start=1):
            self.stdout.write(f"{index:02d}. {raw}")
        self.stdout.write("The previous owner key, TOTP device, recovery codes, and sessions must no longer be used.")


