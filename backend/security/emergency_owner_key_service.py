"""Local-only GM emergency owner-key lifecycle.

No HTTP endpoint imports this module. The owner key is a separate 256-bit
offline factor; only its SHA-256 digest is persisted. Recovery restores the
existing singleton-linked GM identity and never transfers or replaces it.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from security.crypto import KeyProvider, EncryptedSecret, encrypt_secret
from security.gm_slot import GM_SLOT_CODE, inspect_slot_consistency
from security.mfa import (
    generate_recovery_codes,
    hash_recovery_code,
    matching_totp_counter,
)
from security.mfa_models import (
    MFADeviceStatus,
    SecurityEmergencyOwnerKey,
    SecurityLoginSession,
    SecurityMFADevice,
    SecurityRecoveryCode,
)
from security.models import (
    AuditAction,
    AuditEvent,
    GMRoleSlot,
    UserRoleAssignment,
)

OWNER_KEY_SCOPE = SecurityEmergencyOwnerKey.GM_RECOVERY
OWNER_KEY_SOURCE_INITIAL = SecurityEmergencyOwnerKey.SOURCE_INITIAL_BOOTSTRAP
OWNER_KEY_SOURCE_ROTATION = SecurityEmergencyOwnerKey.SOURCE_ROTATION
OWNER_KEY_SOURCE_RECOVERY = SecurityEmergencyOwnerKey.SOURCE_EMERGENCY_RECOVERY
OWNER_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
TOTP_PURPOSE = "totp"


class EmergencyOwnerKeyError(RuntimeError):
    """A local GM emergency-key operation cannot safely proceed."""


class EmergencyOwnerKeyInvalid(EmergencyOwnerKeyError):
    """The offline owner key is invalid, revoked, consumed, or absent."""


class EmergencyOwnerKeyPolicyDenied(EmergencyOwnerKeyError):
    """The singleton GM state or requested operation violates owner policy."""


@dataclass(frozen=True)
class CurrentGMIdentity:
    user: object
    assignment_id: int
    slot_id: int


def generate_emergency_owner_key() -> str:
    """Generate a 256-bit base64url owner key; callers must display it once."""
    value = secrets.token_urlsafe(32)
    if not OWNER_KEY_RE.fullmatch(value):
        raise EmergencyOwnerKeyError("operating-system random owner-key generation failed")
    return value


def emergency_owner_key_digest(raw_key: str) -> str:
    if not isinstance(raw_key, str) or not OWNER_KEY_RE.fullmatch(raw_key):
        raise EmergencyOwnerKeyInvalid("offline owner key is invalid")
    return hashlib.sha256(raw_key.encode("ascii")).hexdigest()


def _current_gm_locked(*, at=None) -> tuple[object, UserRoleAssignment, GMRoleSlot]:
    """Lock and validate the existing singleton GM; never infer another holder."""
    from security.models import Role

    now = at or timezone.now()
    try:
        slot = GMRoleSlot.objects.select_for_update().get(code=GM_SLOT_CODE)
    except GMRoleSlot.DoesNotExist:
        raise EmergencyOwnerKeyPolicyDenied("GM singleton slot is missing") from None
    if slot.assignment_id is None:
        raise EmergencyOwnerKeyPolicyDenied("no existing GM holder is available for emergency recovery")

    findings = inspect_slot_consistency()
    if findings:
        raise EmergencyOwnerKeyPolicyDenied(
            "GM slot consistency check failed; offline recovery is blocked"
        )

    try:
        assignment = UserRoleAssignment.objects.select_for_update().get(pk=slot.assignment_id)
    except UserRoleAssignment.DoesNotExist:
        raise EmergencyOwnerKeyPolicyDenied("GM slot assignment is missing") from None
    try:
        role = Role.objects.get(pk=assignment.role_id)
    except Role.DoesNotExist:
        raise EmergencyOwnerKeyPolicyDenied("GM role is missing") from None

    user = get_user_model()._default_manager.select_for_update().filter(pk=assignment.user_id).first()
    if user is None or not user.is_active:
        raise EmergencyOwnerKeyPolicyDenied("existing GM account is not active")
    if role.code != GM_SLOT_CODE or not role.is_active:
        raise EmergencyOwnerKeyPolicyDenied("existing GM assignment does not point to the active GM role")
    if assignment.revoked_at is not None or assignment.start_at is None or assignment.start_at > now:
        raise EmergencyOwnerKeyPolicyDenied("existing GM assignment is not active")
    if assignment.end_at is not None and assignment.end_at <= now:
        raise EmergencyOwnerKeyPolicyDenied("existing GM assignment is not active")
    return user, assignment, slot


def get_current_gm_for_local_operation(*, at=None) -> CurrentGMIdentity:
    """Read and validate the current GM identity for a local TTY command."""
    with transaction.atomic():
        user, assignment, slot = _current_gm_locked(at=at)
        return CurrentGMIdentity(user=user, assignment_id=assignment.pk, slot_id=slot.pk)


def validate_current_gm_emergency_owner_key(raw_key: str, *, at=None):
    """Verify the currently live owner key without changing any account state."""
    now = at or timezone.now()
    digest = emergency_owner_key_digest(raw_key)
    with transaction.atomic():
        _user, _assignment, _slot = _current_gm_locked(at=now)
        live = SecurityEmergencyOwnerKey.objects.select_for_update().filter(
            scope=OWNER_KEY_SCOPE,
            consumed_at__isnull=True,
            revoked_at__isnull=True,
        ).first()
        if live is None or not hmac.compare_digest(live.key_hash, digest):
            raise EmergencyOwnerKeyInvalid("offline GM owner key is invalid, consumed, or revoked")
        return live.pk


def create_initial_gm_emergency_owner_key(user, raw_key: str, *, at=None):
    """Persist the first owner key only after initial GM slot claim in caller transaction."""
    if transaction.get_autocommit():
        raise EmergencyOwnerKeyPolicyDenied("initial owner key must be created inside GM bootstrap transaction")
    now = at or timezone.now()
    digest = emergency_owner_key_digest(raw_key)
    current_user, assignment, _slot = _current_gm_locked(at=now)
    if current_user.pk != user.pk:
        raise EmergencyOwnerKeyPolicyDenied("initial owner key target is not the singleton GM")
    if SecurityEmergencyOwnerKey.objects.filter(
        scope=OWNER_KEY_SCOPE,
    ).exists():
        raise EmergencyOwnerKeyPolicyDenied("emergency owner-key history already exists")
    row = SecurityEmergencyOwnerKey.objects.create(
        scope=OWNER_KEY_SCOPE,
        source=OWNER_KEY_SOURCE_INITIAL,
        key_hash=digest,
        issued_at=now,
        issued_by=current_user,
    )
    return row


def issue_gm_emergency_owner_key(
    gm_user,
    *,
    password: str,
    totp_code: str,
    provider: KeyProvider,
    new_owner_key: str,
    at=None,
):
    """Rotate the GM's offline owner key after local password+fresh TOTP proof."""
    from security.mfa_service import MFAInvalidCode, verify_user_totp

    now = at or timezone.now()
    digest = emergency_owner_key_digest(new_owner_key)
    if not getattr(gm_user, "is_authenticated", False) or not getattr(gm_user, "pk", None):
        raise EmergencyOwnerKeyPolicyDenied("a persisted GM account is required")
    if not isinstance(password, str) or not gm_user.check_password(password):
        raise EmergencyOwnerKeyInvalid("GM password verification failed")
    try:
        verified = verify_user_totp(gm_user, totp_code, provider=provider, at=now)
    except Exception:
        raise EmergencyOwnerKeyError("GM TOTP verification service is unavailable") from None
    if not verified:
        raise EmergencyOwnerKeyInvalid("GM TOTP verification failed")

    with transaction.atomic():
        current_user, assignment, _slot = _current_gm_locked(at=now)
        if current_user.pk != gm_user.pk:
            raise EmergencyOwnerKeyPolicyDenied("singleton GM identity changed during local key rotation")
        if not current_user.check_password(password):
            raise EmergencyOwnerKeyInvalid("GM password changed during local key rotation")

        previous = SecurityEmergencyOwnerKey.objects.select_for_update().filter(
            scope=OWNER_KEY_SCOPE,
            consumed_at__isnull=True,
            revoked_at__isnull=True,
        ).first()
        if previous is not None:
            if hmac.compare_digest(previous.key_hash, digest):
                raise EmergencyOwnerKeyInvalid("replacement owner key must differ from the current key")
            previous.revoked_at = now
            previous.revoke_reason = "ROTATED"
            previous.save(update_fields=["revoked_at", "revoke_reason"])
        if SecurityEmergencyOwnerKey.objects.filter(key_hash=digest).exists():
            raise EmergencyOwnerKeyInvalid("replacement owner key has already been used")

        row = SecurityEmergencyOwnerKey.objects.create(
            scope=OWNER_KEY_SCOPE,
            source=OWNER_KEY_SOURCE_ROTATION,
            key_hash=digest,
            issued_at=now,
            issued_by=current_user,
        )
        AuditEvent.objects.create(
            user=current_user,
            action=AuditAction.UPDATE,
            entity="GM_EMERGENCY_OWNER_KEY",
            entity_id=str(row.pk),
            previous_state={"previous_key_id": previous.pk if previous else None},
            new_state={"key_id": row.pk, "source": OWNER_KEY_SOURCE_ROTATION},
            reason="Local owner-key rotation after GM password and TOTP verification",
        )
        return row


def recover_existing_gm_offline(
    raw_owner_key: str,
    *,
    new_owner_key: str,
    new_password: str,
    new_totp_secret: str,
    new_totp_code: str,
    provider: KeyProvider,
    at=None,
) -> tuple[object, list[str], int, int]:
    """Recover the existing GM in place; preserve slot and assignment history."""
    now = at or timezone.now()
    old_digest = emergency_owner_key_digest(raw_owner_key)
    new_digest = emergency_owner_key_digest(new_owner_key)
    if hmac.compare_digest(old_digest, new_digest):
        raise EmergencyOwnerKeyInvalid("replacement owner key must differ from the consumed key")
    if not isinstance(new_password, str) or not new_password:
        raise EmergencyOwnerKeyInvalid("a new GM password is required")
    if SecurityEmergencyOwnerKey.objects.filter(key_hash=new_digest).exists():
        raise EmergencyOwnerKeyInvalid("replacement owner key has already been used")
    matched_counter = matching_totp_counter(
        new_totp_secret,
        new_totp_code,
        timestamp=now.timestamp(),
    )
    if matched_counter is None:
        raise EmergencyOwnerKeyInvalid("new GM TOTP confirmation failed")

    # The provider is probed/encryption is completed before destructive changes.
    # The exact user identity is bound again inside the locked transaction.
    preview = get_current_gm_for_local_operation(at=now)
    try:
        validate_password(new_password, user=preview.user)
    except ValidationError:
        raise EmergencyOwnerKeyInvalid(
            "new GM password does not satisfy the configured password policy"
        ) from None
    try:
        envelope: EncryptedSecret = encrypt_secret(
            new_totp_secret.encode("ascii"),
            purpose=TOTP_PURPOSE,
            subject_id=str(preview.user.pk),
            provider=provider,
        )
    except Exception:
        raise EmergencyOwnerKeyError("OS-backed MFA key provider is unavailable; no recovery was applied") from None
    recovery_codes = generate_recovery_codes()

    with transaction.atomic():
        gm_user, assignment, slot = _current_gm_locked(at=now)
        if gm_user.pk != preview.user.pk or assignment.pk != preview.assignment_id or slot.pk != preview.slot_id:
            raise EmergencyOwnerKeyPolicyDenied("singleton GM identity changed during emergency recovery")

        live_key = SecurityEmergencyOwnerKey.objects.select_for_update().filter(
            scope=OWNER_KEY_SCOPE,
            consumed_at__isnull=True,
            revoked_at__isnull=True,
        ).first()
        if live_key is None or not hmac.compare_digest(live_key.key_hash, old_digest):
            raise EmergencyOwnerKeyInvalid("offline GM owner key is invalid, consumed, or revoked")

        previous_devices = list(
            SecurityMFADevice.objects.select_for_update().filter(
                user=gm_user,
                status__in=[MFADeviceStatus.PENDING, MFADeviceStatus.ACTIVE],
            ).order_by("pk")
        )
        for device in previous_devices:
            device.status = MFADeviceStatus.DISABLED
            device.disabled_at = now
            device.save(update_fields=["status", "disabled_at"])

        unused_recovery_count = SecurityRecoveryCode.objects.filter(
            user=gm_user,
            used_at__isnull=True,
        ).update(used_at=now)

        active_session_count = SecurityLoginSession.objects.filter(
            user=gm_user,
            revoked_at__isnull=True,
        ).update(revoked_at=now, revoke_reason="GM_EMERGENCY_RECOVERY")

        gm_user.set_password(new_password)
        gm_user.save(update_fields=["password"])

        new_device = SecurityMFADevice.objects.create(
            user=gm_user,
            status=MFADeviceStatus.ACTIVE,
            secret_format_version=envelope.version,
            secret_key_id=envelope.key_id,
            secret_nonce=envelope.nonce,
            secret_ciphertext=envelope.ciphertext,
            confirmed_at=now,
            last_used_at=now,
            last_accepted_counter=matched_counter,
        )
        SecurityRecoveryCode.objects.bulk_create([
            SecurityRecoveryCode(user=gm_user, code_hash=hash_recovery_code(raw))
            for raw in recovery_codes
        ])

        live_key.consumed_at = now
        live_key.consumed_by = gm_user
        live_key.save(update_fields=["consumed_at", "consumed_by"])
        replacement = SecurityEmergencyOwnerKey.objects.create(
            scope=OWNER_KEY_SCOPE,
            source=OWNER_KEY_SOURCE_RECOVERY,
            key_hash=new_digest,
            issued_at=now,
            issued_by=gm_user,
        )
        AuditEvent.objects.create(
            user=gm_user,
            action=AuditAction.UPDATE,
            entity="GM_EMERGENCY_RECOVERY",
            entity_id=str(gm_user.pk),
            previous_state={
                "disabled_mfa_devices": len(previous_devices),
                "retired_recovery_codes": unused_recovery_count,
                "revoked_sessions": active_session_count,
                "consumed_owner_key_id": live_key.pk,
            },
            new_state={
                "active_mfa_device_id": new_device.pk,
                "recovery_codes_issued": len(recovery_codes),
                "replacement_owner_key_id": replacement.pk,
                "gm_assignment_preserved": assignment.pk,
                "gm_slot_preserved": slot.pk,
            },
            reason="Local offline GM emergency recovery; identity and singleton assignment preserved",
        )
    return gm_user, recovery_codes, active_session_count, len(previous_devices)
