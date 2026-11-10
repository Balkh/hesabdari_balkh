"""Create the first GM locally, with TOTP verified before the slot is claimed.

This command is intentionally interactive and unavailable through HTTP, Admin,
or non-TTY automation. It is initial provisioning only; it cannot recover,
replace, revoke, or transfer an existing GM holder.
"""
from __future__ import annotations

import getpass
import hashlib
import hmac
import sys
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from security.crypto import KeyUnavailableError, encrypt_secret
from security.gm_slot import GM_SLOT_CODE, claim_gm_slot, inspect_slot_consistency
from security.mfa import (
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    matching_totp_counter,
)
from security.emergency_owner_key_service import (
    create_initial_gm_emergency_owner_key,
    generate_emergency_owner_key,
)
from security.mfa_models import (
    MFADeviceStatus,
    SecurityBootstrapToken,
    SecurityMFADevice,
    SecurityRecoveryCode,
)
from security.models import (
    AuditAction,
    AuditEvent,
    GMRoleSlot,
    Role,
    UserRoleAssignment,
)

TOTP_PURPOSE = "totp"


def _require_tty():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise CommandError("GM bootstrap is local-only and requires an interactive terminal")


def _load_key_provider():
    provider_path = getattr(settings, "ERP_MFA_KEY_PROVIDER", None)
    if not provider_path:
        raise CommandError(
            "No OS-backed ERP_MFA_KEY_PROVIDER is configured; no GM account was created"
        )
    try:
        provider_class = import_string(provider_path)
        provider = provider_class()
        # Probe the key before asking for the password or creating any DB state.
        key_id = provider.active_key_id()
        key = provider.get_key(key_id)
        if not isinstance(key_id, str) or not key_id or not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("provider returned invalid AES-256 key material")
        return provider
    except Exception:
        raise CommandError(
            "The configured OS-backed MFA key provider is unavailable or invalid; bootstrap denied"
        ) from None


def _token_row_is_usable(row, digest, now):
    return bool(
        row is not None
        and hmac.compare_digest(row.token_hash, digest)
        and row.consumed_at is None
        and row.revoked_at is None
        and row.expires_at > now
    )


class Command(BaseCommand):
    help = "Bootstrap the first GM with password and confirmed encrypted TOTP on a local console."

    def handle(self, *args, **options):
        _require_tty()
        User = get_user_model()
        username_field = User.USERNAME_FIELD

        raw_token = getpass.getpass("One-time initial GM bootstrap token: ").strip()
        if not raw_token:
            raise CommandError("bootstrap token is required")
        try:
            token_digest = hashlib.sha256(raw_token.encode("ascii", errors="strict")).hexdigest()
        except UnicodeEncodeError:
            raise CommandError("bootstrap token is invalid") from None
        now = timezone.now()
        token = SecurityBootstrapToken.objects.filter(
            purpose=SecurityBootstrapToken.INITIAL_GM,
            token_hash=token_digest,
        ).first()
        if not _token_row_is_usable(token, token_digest, now):
            raise CommandError("bootstrap token is invalid, expired, revoked, or already consumed")

        username = input(f"New GM {username_field}: ").strip()
        if not username or len(username) > User._meta.get_field(username_field).max_length:
            raise CommandError("GM username is invalid")
        if User._default_manager.filter(**{username_field: username}).exists():
            raise CommandError("that username already exists")

        password = getpass.getpass("New GM password: ")
        confirm = getpass.getpass("Confirm GM password: ")
        if not password or not hmac.compare_digest(password, confirm):
            raise CommandError("passwords are empty or do not match")
        candidate = User(**{username_field: username})
        try:
            validate_password(password, user=candidate)
        except ValidationError as exc:
            messages = "; ".join(str(item) for item in exc.messages)
            raise CommandError("password does not satisfy policy: " + messages)

        provider = _load_key_provider()
        secret = generate_totp_secret()
        user = None
        recovery_codes = None
        now = timezone.now()

        with transaction.atomic():
            # Lock the singleton identity first. Issuance and bootstrap use
            # the same lock order to avoid a competing local bootstrap race.
            try:
                slot = GMRoleSlot.objects.select_for_update().get(code=GM_SLOT_CODE)
            except GMRoleSlot.DoesNotExist:
                raise CommandError("GM singleton slot is missing; apply security migrations first")
            if slot.assignment_id is not None:
                raise CommandError("GM slot is already held; this command cannot recover or transfer GM")
            if UserRoleAssignment.objects.filter(role__code=GM_SLOT_CODE).exists():
                raise CommandError("GM assignment history exists; initial bootstrap is permanently closed")
            if SecurityBootstrapToken.objects.filter(
                purpose=SecurityBootstrapToken.INITIAL_GM,
                consumed_at__isnull=False,
            ).exists():
                raise CommandError("initial GM bootstrap was already consumed; local emergency recovery is separate")
            findings = inspect_slot_consistency()
            if findings:
                raise CommandError(
                    "GM slot state is inconsistent; bootstrap denied: "
                    + "; ".join(code for code, _message in findings)
                )

            token_row = (
                SecurityBootstrapToken.objects.select_for_update()
                .filter(
                    purpose=SecurityBootstrapToken.INITIAL_GM,
                    token_hash=token_digest,
                )
                .first()
            )
            now = timezone.now()
            if not _token_row_is_usable(token_row, token_digest, now):
                raise CommandError("bootstrap token expired or was consumed by another process")

            if User._default_manager.filter(**{username_field: username}).exists():
                raise CommandError("that username already exists")

            try:
                role = Role.objects.get(code=GM_SLOT_CODE, is_active=True)
            except Role.DoesNotExist:
                raise CommandError("the active GM role is not seeded; run the approved RBAC seed first")

            # Staff is only Django Admin's admission flag; this account is
            # not a superuser. /admin remains denied until its GM+MFA gate is
            # separately implemented and verified.
            create_kwargs = {
                username_field: username,
                "password": password,
                "is_active": True,
                "is_staff": True,
                "is_superuser": False,
            }
            user = User._default_manager.create_user(**create_kwargs)

            envelope = encrypt_secret(
                secret.encode("ascii"),
                purpose=TOTP_PURPOSE,
                subject_id=str(user.pk),
                provider=provider,
            )
            label = quote(f"Hesabdari Balkh:{username}", safe="")
            issuer = quote("Hesabdari Balkh", safe="")
            uri = (
                f"otpauth://totp/{label}?secret={secret}&issuer={issuer}"
                "&algorithm=SHA1&digits=6&period=30"
            )
            self.stdout.write("Scan or enter this TOTP setup URI locally (shown once):")
            self.stdout.write(uri)
            code = getpass.getpass("Enter the six-digit authenticator code to confirm GM MFA: ").strip()
            now = timezone.now()
            counter = matching_totp_counter(secret, code, timestamp=now.timestamp())
            if counter is None:
                raise CommandError("TOTP confirmation failed; no GM account or slot was committed")
            owner_key = generate_emergency_owner_key()
            self.stdout.write("OFFLINE GM EMERGENCY OWNER KEY — shown once; store it separately from this computer:")
            self.stdout.write(owner_key)
            self.stdout.write("If bootstrap fails, discard this displayed key; it is not stored until the transaction commits.")
            owner_key_confirmation = getpass.getpass(
                "After saving the key offline, enter its last 8 characters to confirm: "
            ).strip()
            if not hmac.compare_digest(owner_key_confirmation, owner_key[-8:]):
                raise CommandError("owner-key confirmation failed; no GM account or slot was committed; discard the displayed owner key and authenticator seed")

            device = SecurityMFADevice.objects.create(
                user=user,
                status=MFADeviceStatus.ACTIVE,
                secret_format_version=envelope.version,
                secret_key_id=envelope.key_id,
                secret_nonce=envelope.nonce,
                secret_ciphertext=envelope.ciphertext,
                confirmed_at=now,
                last_used_at=now,
                last_accepted_counter=counter,
            )
            recovery_codes = generate_recovery_codes()
            SecurityRecoveryCode.objects.bulk_create([
                SecurityRecoveryCode(user=user, code_hash=hash_recovery_code(raw))
                for raw in recovery_codes
            ])

            assignment = UserRoleAssignment.objects.create(
                user=user,
                role=role,
                start_at=now,
                reason="Initial local offline GM bootstrap",
            )
            claim_gm_slot(assignment)
            owner_key_row = create_initial_gm_emergency_owner_key(
                user,
                owner_key,
                at=now,
            )

            token_row.consumed_at = now
            token_row.save(update_fields=["consumed_at"])
            AuditEvent.objects.create(
                user=user,
                action=AuditAction.CREATE,
                entity="GM_BOOTSTRAP",
                entity_id=str(user.pk),
                new_state={
                    "gm_slot_claimed": True,
                    "mfa_active": True,
                    "recovery_codes_issued": 10,
                    "is_staff": True,
                    "is_superuser": False,
                    "emergency_owner_key_issued": True,
                    "emergency_owner_key_id": owner_key_row.pk,
                },
                reason="Initial local GM bootstrap with confirmed TOTP",
            )

        self.stdout.write(self.style.SUCCESS("Initial GM bootstrap succeeded."))
        self.stdout.write("The offline emergency owner key was confirmed and stored as a hash; the raw key will not be shown again.")
        self.stdout.write("Save these ten recovery codes offline. They are shown only once:")
        for index, raw in enumerate(recovery_codes, start=1):
            self.stdout.write(f"{index:02d}. {raw}")
        self.stdout.write(
            "GM recovery/transfer remains local emergency-only. Keep the separate offline owner key outside this computer."
        )
