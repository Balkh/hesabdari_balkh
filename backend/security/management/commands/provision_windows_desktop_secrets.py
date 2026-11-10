"""Provision the Windows desktop MFA and Django secrets for this user only."""
from __future__ import annotations

import os
import sys

from django.core.management.base import BaseCommand, CommandError

from security.crypto import KeyUnavailableError
from security.windows_key_provider import WindowsCredentialManagerKeyProvider


def _require_tty():
    if os.name != "nt":
        raise CommandError("Windows desktop secrets can be provisioned only on Windows")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise CommandError("Windows desktop secret provisioning requires a local interactive terminal")


class Command(BaseCommand):
    help = "Create the current Windows user's AES-256 MFA key and separate Django signing secret."

    def handle(self, *args, **options):
        _require_tty()
        try:
            key_id = WindowsCredentialManagerKeyProvider().provision()
        except KeyUnavailableError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS(
            "Windows desktop secrets provisioned and verified for the current user."
        ))
        self.stdout.write(f"Active MFA key identifier: {key_id}")
        self.stdout.write(
            "The AES key and Django signing secret remain in this user's Windows Credential Manager; neither was printed."
        )
