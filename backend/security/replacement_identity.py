"""Local, unpublished replacement-database identity preparation.

Only a dedicated isolated staging process may call these services. No HTTP
route, ordinary management command, or production settings enables them.
An independent owner record and checkpoint must be supplied by the operator;
a settings flag or source-isolation assertion cannot prove physical isolation.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from security.audit_chain import assert_audit_trigger_schema, verify_audit_chain
from security.crypto import encrypt_secret
from security.emergency_owner_key_service import (
    EmergencyOwnerKeyInvalid, EmergencyOwnerKeyPolicyDenied,
    _current_gm_locked, get_current_gm_for_local_operation,
    recover_existing_gm_offline, validate_current_gm_emergency_owner_key,
)
from security.local_console import require_local_console
from security.login_lockout import is_account_locked
from security.mfa import generate_recovery_codes, hash_recovery_code, matching_totp_counter
from security.mfa_models import MFADeviceStatus, SecurityLoginSession, SecurityMFADevice, SecurityRecoveryCode
from security.mfa_service import TOTP_PURPOSE, verify_user_totp
from security.models import AuditAction, AuditEvent
from security.services import record_audit_event


def _require_staging(source_isolated):
    if getattr(settings, "ERP_OFFLINE_REPLACEMENT_STAGING", False) is not True:
        raise EmergencyOwnerKeyPolicyDenied("replacement identity changes require an isolated staging process")
    if source_isolated is not True:
        raise EmergencyOwnerKeyPolicyDenied("source isolation must be independently confirmed by the owner")
    require_local_console()
    if not transaction.get_autocommit():
        raise EmergencyOwnerKeyPolicyDenied("replacement identity operation requires an independent transaction")


def prepare_replacement_identity(raw_owner_key, *, expected_checkpoint, expected_owner_record,
                                 source_isolated, new_owner_key, new_password, new_totp_secret,
                                 new_totp_code, provider, at=None):
    """Recover GM and retire all copied credentials in one durable transaction.

    expected_checkpoint is the independently selected, already authenticated
    restored chain tuple; expected_owner_record is the latest independently
    recorded owner-key row ID. These are inputs, not self-derived trust.
    No database publication, role changes, or weakening of MFA policy.
    """
    _require_staging(source_isolated)
    now = at or timezone.now()
    if (not isinstance(expected_checkpoint, dict)
            or set(expected_checkpoint) != {"valid", "event_count", "head_hash", "last_event_id"}
            or expected_checkpoint["valid"] is not True
            or type(expected_owner_record) is not int or expected_owner_record <= 0):
        raise EmergencyOwnerKeyPolicyDenied("independent checkpoint and current owner record are required")
    with transaction.atomic(durable=True):
        assert_audit_trigger_schema()
        if verify_audit_chain() != expected_checkpoint:
            raise EmergencyOwnerKeyPolicyDenied("restored chain differs from the independently selected checkpoint")
        if validate_current_gm_emergency_owner_key(raw_owner_key, at=now) != expected_owner_record:
            raise EmergencyOwnerKeyInvalid("restored owner key differs from independently recorded current authority")
        key_id = provider.active_key_id()
        if SecurityMFADevice.objects.filter(secret_key_id=key_id).exists():
            raise EmergencyOwnerKeyPolicyDenied("replacement MFA key identifier must differ from every historical device")
        # Existing GM service validates current authority, password policy and
        # fresh TOTP, consumes the old owner key and preserves singleton identity.
        gm, codes, gm_revoked, gm_disabled = recover_existing_gm_offline(
            raw_owner_key, new_owner_key=new_owner_key, new_password=new_password,
            new_totp_secret=new_totp_secret, new_totp_code=new_totp_code,
            provider=provider, at=now,
        )
        # All restored sessions are historical, including expired Django rows.
        other_sessions = SecurityLoginSession.objects.filter(revoked_at__isnull=True).update(
            revoked_at=now, revoke_reason="DEVICE_REPLACEMENT")
        django_rows, _ = Session.objects.all().delete()
        old_devices = SecurityMFADevice.objects.exclude(user=gm).filter(
            status__in=(MFADeviceStatus.ACTIVE, MFADeviceStatus.PENDING)
        ).update(status=MFADeviceStatus.DISABLED, disabled_at=now)
        old_codes = SecurityRecoveryCode.objects.exclude(user=gm).filter(
            used_at__isnull=True).update(used_at=now)
        record_audit_event(
            user=gm, action=AuditAction.ACCOUNT_EMERGENCY_RECOVERY,
            entity="REPLACEMENT_IDENTITY_PREPARATION", entity_id=str(gm.pk),
            new_state={"registry_sessions_retired": gm_revoked + other_sessions,
                       "django_sessions_removed": django_rows,
                       "historical_mfa_devices_retired": gm_disabled + old_devices,
                       "employee_recovery_codes_retired": old_codes},
            reason="Isolated replacement preparation; source isolation attested; employee MFA policy preserved",
        )
    return gm, codes


def reenroll_replacement_employee(employee_id, *, gm_password, gm_totp_code,
                                  employee_password, new_totp_secret, new_totp_code,
                                  provider, source_isolated, at=None):
    """Re-enroll a previously retired employee locally with two-party proof.

    Requires recovered GM password + fresh GM TOTP, employee password + new
    TOTP, no active/pending target device, no live sessions, and evidence of
    replacement preparation. Never changes password, role, or MFA requirement.
    """
    _require_staging(source_isolated)
    now = at or timezone.now()
    gm = get_current_gm_for_local_operation(at=now).user
    if not AuditEvent.objects.filter(entity="REPLACEMENT_IDENTITY_PREPARATION", user=gm).exists():
        raise EmergencyOwnerKeyPolicyDenied("replacement identity has not been prepared")
    if employee_id == gm.pk:
        raise EmergencyOwnerKeyPolicyDenied("GM must use existing owner-key recovery")
    if not isinstance(gm_password, str) or not gm.check_password(gm_password) or is_account_locked(gm, at=now):
        raise EmergencyOwnerKeyInvalid("GM reauthentication failed")
    # Consume fresh GM TOTP in its own transaction, including failed-attempt
    # tracking, so subsequent employee denial cannot roll back the replay guard.
    if not verify_user_totp(gm, gm_totp_code, provider=provider, at=now):
        raise EmergencyOwnerKeyInvalid("GM reauthentication failed")
    with transaction.atomic(durable=True):
        locked_gm, _assignment, _slot = _current_gm_locked(at=now)
        if locked_gm.pk != gm.pk or not locked_gm.check_password(gm_password):
            raise EmergencyOwnerKeyPolicyDenied("GM authority changed")
        if SecurityLoginSession.objects.filter(revoked_at__isnull=True).exists() or Session.objects.exists():
            raise EmergencyOwnerKeyPolicyDenied("replacement staging must have no live sessions")
        employee = get_user_model()._default_manager.select_for_update().filter(pk=employee_id, is_active=True).first()
        if employee is None or employee.pk == gm.pk or is_account_locked(employee, at=now):
            raise EmergencyOwnerKeyInvalid("employee reauthentication failed")
        if not isinstance(employee_password, str) or not employee.check_password(employee_password):
            raise EmergencyOwnerKeyInvalid("employee reauthentication failed")
        devices = SecurityMFADevice.objects.filter(user=employee)
        if not devices.filter(status=MFADeviceStatus.DISABLED).exists() or devices.filter(
                status__in=(MFADeviceStatus.ACTIVE, MFADeviceStatus.PENDING)).exists():
            raise EmergencyOwnerKeyPolicyDenied("employee is not awaiting replacement enrollment")
        counter = matching_totp_counter(new_totp_secret, new_totp_code, timestamp=now.timestamp())
        if counter is None:
            raise EmergencyOwnerKeyInvalid("new employee TOTP confirmation failed")
        envelope = encrypt_secret(new_totp_secret.encode("ascii"), purpose=TOTP_PURPOSE,
                                  subject_id=str(employee.pk), provider=provider)
        if not SecurityMFADevice.objects.filter(user=locked_gm, status=MFADeviceStatus.ACTIVE,
                                                 secret_key_id=envelope.key_id).exists():
            raise EmergencyOwnerKeyPolicyDenied("replacement MFA provider does not match recovered GM")
        SecurityRecoveryCode.objects.filter(user=employee, used_at__isnull=True).update(used_at=now)
        device = SecurityMFADevice.objects.create(user=employee, status=MFADeviceStatus.ACTIVE,
            secret_format_version=envelope.version, secret_key_id=envelope.key_id,
            secret_nonce=envelope.nonce, secret_ciphertext=envelope.ciphertext,
            confirmed_at=now, last_used_at=now, last_accepted_counter=counter)
        codes = generate_recovery_codes()
        SecurityRecoveryCode.objects.bulk_create([
            SecurityRecoveryCode(user=employee, code_hash=hash_recovery_code(code)) for code in codes
        ])
        record_audit_event(user=locked_gm, action=AuditAction.MFA_RESET,
            entity="REPLACEMENT_EMPLOYEE_MFA", entity_id=str(employee.pk),
            new_state={"device_id": device.pk, "recovery_codes_issued": len(codes)},
            reason="Local replacement enrollment with GM and employee reauthentication; MFA policy preserved")
    return codes
