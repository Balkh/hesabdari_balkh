"""Transactional MFA enrollment, TOTP verification and recovery-code services.

This layer accepts an injected OS-backed KeyProvider. It deliberately does
not select a Windows key-storage implementation or provide a local/plaintext
fallback; authentication must fail closed until a supported provider is wired.
"""
from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from security.crypto import KeyProvider, decrypt_secret, encrypt_secret
from security.mfa import (
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    matching_totp_counter,
    verify_recovery_code,
)
from security.models import AuditAction, AuditEvent
from security.mfa_models import (
    MFADeviceStatus,
    SecurityMFADevice,
    SecurityRecoveryCode,
)

TOTP_PURPOSE = "totp"
MAX_MFA_FAILURES = 5
MFA_LOCKOUT = timedelta(minutes=5)


class MFAServiceError(RuntimeError):
    """Base class for safe, user-presentable MFA service failures."""


class MFAEnrollmentRequired(MFAServiceError):
    pass


class MFAEnrollmentLocked(MFAServiceError):
    pass


class MFAInvalidCode(MFAServiceError):
    pass


class MFAAlreadyEnrolled(MFAServiceError):
    pass


class MFAEnrollmentPolicyDenied(MFAServiceError):
    pass


def _subject_id(user) -> str:
    if getattr(user, "pk", None) is None:
        raise ValueError("a persisted user is required")
    return str(user.pk)


def _encrypted_secret_for(device: SecurityMFADevice, user, provider: KeyProvider) -> bytes:
    from security.crypto import EncryptedSecret

    envelope = EncryptedSecret(
        version=device.secret_format_version,
        key_id=device.secret_key_id,
        nonce=bytes(device.secret_nonce),
        ciphertext=bytes(device.secret_ciphertext),
    )
    return decrypt_secret(
        envelope,
        purpose=TOTP_PURPOSE,
        subject_id=_subject_id(user),
        provider=provider,
    )


def begin_mfa_enrollment(user, *, provider: KeyProvider, issuer: str = "Hesabdari Balkh") -> dict:
    """Create a pending encrypted credential; expose the secret once to caller."""
    if not issuer or len(issuer) > 64:
        raise ValueError("issuer must be between 1 and 64 characters")
    secret = generate_totp_secret()
    envelope = encrypt_secret(
        secret.encode("ascii"),
        purpose=TOTP_PURPOSE,
        subject_id=_subject_id(user),
        provider=provider,
    )
    with transaction.atomic():
        # Serialize enrollment against another enrollment/confirmation for this user.
        get_user_model()._default_manager.select_for_update().get(pk=user.pk)
        if SecurityMFADevice.objects.filter(
            user=user, status=MFADeviceStatus.ACTIVE
        ).exists():
            raise MFAAlreadyEnrolled("an active MFA device already exists")
        SecurityMFADevice.objects.filter(
            user=user, status=MFADeviceStatus.PENDING
        ).delete()
        device = SecurityMFADevice.objects.create(
            user=user,
            status=MFADeviceStatus.PENDING,
            secret_format_version=envelope.version,
            secret_key_id=envelope.key_id,
            secret_nonce=envelope.nonce,
            secret_ciphertext=envelope.ciphertext,
        )
        AuditEvent.objects.create(
            user=user,
            action=AuditAction.CREATE,
            entity="MFA_DEVICE",
            entity_id=str(device.pk),
            new_state={"status": MFADeviceStatus.PENDING},
        )
    label = quote(f"{issuer}:{user.get_username()}", safe="")
    uri = (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}"
        "&algorithm=SHA1&digits=6&period=30"
    )
    return {"device_id": device.pk, "secret": secret, "otpauth_uri": uri}


def confirm_mfa_enrollment(
    user,
    code: str,
    *,
    provider: KeyProvider,
    at=None,
) -> list[str]:
    """Activate pending TOTP only after a valid non-replayed code; return codes once."""
    now = at or timezone.now()
    timestamp = now.timestamp()
    error = None
    recovery_codes = None
    with transaction.atomic():
        get_user_model()._default_manager.select_for_update().get(pk=user.pk)
        device = (
            SecurityMFADevice.objects.select_for_update()
            .filter(user=user, status=MFADeviceStatus.PENDING)
            .order_by("-created_at", "-pk")
            .first()
        )
        if device is None:
            error = MFAEnrollmentRequired("no pending MFA enrollment exists")
        elif device.locked_until and device.locked_until > now:
            error = MFAEnrollmentLocked("MFA verification is temporarily locked")
        else:
            secret = _encrypted_secret_for(device, user, provider).decode("ascii")
            counter = matching_totp_counter(secret, code, timestamp=timestamp)
            if counter is None or (
                device.last_accepted_counter is not None
                and counter <= device.last_accepted_counter
            ):
                device.failed_attempts += 1
                if device.failed_attempts >= MAX_MFA_FAILURES:
                    device.locked_until = now + MFA_LOCKOUT
                device.save(update_fields=["failed_attempts", "locked_until"])
                error = MFAInvalidCode("MFA verification code is invalid")
            else:
                if SecurityMFADevice.objects.filter(
                    user=user, status=MFADeviceStatus.ACTIVE
                ).exclude(pk=device.pk).exists():
                    error = MFAAlreadyEnrolled("an active MFA device already exists")
                else:
                    device.status = MFADeviceStatus.ACTIVE
                    device.confirmed_at = now
                    device.last_used_at = now
                    device.last_accepted_counter = counter
                    device.failed_attempts = 0
                    device.locked_until = None
                    device.save(update_fields=[
                        "status", "confirmed_at", "last_used_at",
                        "last_accepted_counter", "failed_attempts", "locked_until",
                    ])
                    recovery_codes = generate_recovery_codes()
                    SecurityRecoveryCode.objects.bulk_create([
                        SecurityRecoveryCode(user=user, code_hash=hash_recovery_code(raw))
                        for raw in recovery_codes
                    ])
                    AuditEvent.objects.create(
                        user=user,
                        action=AuditAction.UPDATE,
                        entity="MFA_DEVICE",
                        entity_id=str(device.pk),
                        previous_state={"status": MFADeviceStatus.PENDING},
                        new_state={"status": MFADeviceStatus.ACTIVE, "recovery_codes_issued": 10},
                    )
    if error:
        raise error
    return recovery_codes


def verify_user_totp(user, code: str, *, provider: KeyProvider, at=None) -> bool:
    """Verify and consume a fresh TOTP counter for an active device."""
    now = at or timezone.now()
    error_or_valid = False
    with transaction.atomic():
        get_user_model()._default_manager.select_for_update().get(pk=user.pk)
        device = (
            SecurityMFADevice.objects.select_for_update()
            .filter(user=user, status=MFADeviceStatus.ACTIVE)
            .order_by("-confirmed_at", "-pk")
            .first()
        )
        if device is None or (device.locked_until and device.locked_until > now):
            return False
        secret = _encrypted_secret_for(device, user, provider).decode("ascii")
        counter = matching_totp_counter(secret, code, timestamp=now.timestamp())
        if counter is None or (
            device.last_accepted_counter is not None
            and counter <= device.last_accepted_counter
        ):
            device.failed_attempts += 1
            if device.failed_attempts >= MAX_MFA_FAILURES:
                device.locked_until = now + MFA_LOCKOUT
            device.save(update_fields=["failed_attempts", "locked_until"])
            return False
        device.last_accepted_counter = counter
        device.last_used_at = now
        device.failed_attempts = 0
        device.locked_until = None
        device.save(update_fields=[
            "last_accepted_counter", "last_used_at", "failed_attempts", "locked_until"
        ])
        error_or_valid = True
    return error_or_valid


def consume_recovery_code(user, code: str, *, at=None) -> bool:
    """Atomically consume at most one salted recovery-code hash."""
    if not isinstance(code, str) or not code:
        return False
    now = at or timezone.now()
    with transaction.atomic():
        get_user_model()._default_manager.select_for_update().get(pk=user.pk)
        candidates = (
            SecurityRecoveryCode.objects.select_for_update()
            .filter(user=user, used_at__isnull=True)
            .order_by("pk")
        )
        for row in candidates:
            if verify_recovery_code(code, row.code_hash):
                # Conditional update is the final single-use race guard,
                # including on SQLite where SELECT FOR UPDATE is a no-op.
                changed = SecurityRecoveryCode.objects.filter(
                    pk=row.pk, used_at__isnull=True
                ).update(used_at=now)
                return changed == 1
    return False


def rotate_recovery_codes(user, *, password, totp_code=None, recovery_code=None, provider=None, at=None):
    """Replace recovery codes after password plus TOTP or one recovery code."""
    from security.mfa_policy import is_active_gm_holder

    now = at or timezone.now()
    if is_active_gm_holder(user, at=now):
        raise MFAEnrollmentPolicyDenied("GM recovery-code rotation is local-only")
    if bool(totp_code) == bool(recovery_code):
        raise MFAInvalidCode("exactly one MFA factor is required")
    with transaction.atomic():
        locked_user = get_user_model()._default_manager.select_for_update().get(pk=user.pk)
        if is_active_gm_holder(locked_user, at=now):
            raise MFAEnrollmentPolicyDenied("GM recovery-code rotation is local-only")
        if not isinstance(password, str) or not locked_user.check_password(password):
            raise MFAInvalidCode("MFA reauthentication failed")
        device = SecurityMFADevice.objects.select_for_update().filter(
            user=locked_user, status=MFADeviceStatus.ACTIVE
        ).order_by("-confirmed_at", "-pk").first()
        if device is None:
            raise MFAEnrollmentRequired("no active MFA device exists")
        if totp_code:
            verified = provider is not None and verify_user_totp(
                locked_user, totp_code, provider=provider, at=now
            )
        else:
            verified = consume_recovery_code(locked_user, recovery_code, at=now)
        if not verified:
            raise MFAInvalidCode("MFA reauthentication failed")
        SecurityRecoveryCode.objects.filter(
            user=locked_user, used_at__isnull=True
        ).update(used_at=now)
        codes = generate_recovery_codes()
        SecurityRecoveryCode.objects.bulk_create([
            SecurityRecoveryCode(user=locked_user, code_hash=hash_recovery_code(raw))
            for raw in codes
        ])
        AuditEvent.objects.create(
            user=locked_user,
            action=AuditAction.UPDATE,
            entity="MFA_RECOVERY_CODES",
            entity_id=str(locked_user.pk),
            new_state={"active_code_count": 10},
        )
    return codes


def disable_employee_mfa(
    user, *, password, totp_code=None, recovery_code=None, provider=None, at=None
):
    """Disable optional employee MFA after strong reauthentication.

    GM MFA is immutable through ordinary employee routes. A required employee
    MFA policy cannot be disabled by the employee. Disabling atomically closes
    the device, retires all recovery codes and revokes every active session.
    """
    from security.mfa_policy import is_active_gm_holder
    from security.mfa_models import SecurityMFARequirement
    from security.session_service import revoke_all_login_sessions

    now = at or timezone.now()
    if bool(totp_code) == bool(recovery_code):
        raise MFAInvalidCode("exactly one MFA factor is required")

    with transaction.atomic():
        locked_user = get_user_model()._default_manager.select_for_update().get(pk=user.pk)
        if not isinstance(password, str) or not locked_user.check_password(password):
            raise MFAInvalidCode("MFA reauthentication failed")
        if is_active_gm_holder(locked_user, at=now):
            raise MFAEnrollmentPolicyDenied("GM MFA requires local emergency recovery")
        if SecurityMFARequirement.objects.filter(user=locked_user, is_required=True).exists():
            raise MFAEnrollmentPolicyDenied("employee MFA is required by GM policy")
        device = SecurityMFADevice.objects.select_for_update().filter(
            user=locked_user, status=MFADeviceStatus.ACTIVE
        ).order_by("-confirmed_at", "-pk").first()
        if device is None:
            raise MFAEnrollmentRequired("no active MFA device exists")
        if totp_code:
            verified = provider is not None and verify_user_totp(
                locked_user, totp_code, provider=provider, at=now
            )
        else:
            verified = consume_recovery_code(locked_user, recovery_code, at=now)
        if not verified:
            raise MFAInvalidCode("MFA reauthentication failed")

        device.status = MFADeviceStatus.DISABLED
        device.disabled_at = now
        device.save(update_fields=["status", "disabled_at"])
        SecurityRecoveryCode.objects.filter(
            user=locked_user, used_at__isnull=True
        ).update(used_at=now)
        revoked = revoke_all_login_sessions(locked_user, reason="MFA_DISABLED", at=now)
        AuditEvent.objects.create(
            user=locked_user,
            action=AuditAction.UPDATE,
            entity="MFA_DEVICE",
            entity_id=str(device.pk),
            previous_state={"status": MFADeviceStatus.ACTIVE},
            new_state={"status": MFADeviceStatus.DISABLED, "sessions_revoked": revoked},
            reason="Employee disabled optional MFA after reauthentication",
        )
