"""GM-controlled employee MFA policy and trusted GM identity predicate."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from security.gm_slot import GM_SLOT_CODE, load_singleton_slot
from security.mfa_models import MFADeviceStatus, SecurityMFADevice, SecurityMFARequirement
from security.models import AuditAction, AuditEvent


def is_active_gm_holder(user, *, at=None) -> bool:
    """Only the active assignment linked to the singleton slot is GM authority."""
    if user is None or getattr(user, "pk", None) is None or not getattr(user, "is_active", False):
        return False
    now = at or timezone.now()
    slot = load_singleton_slot()
    if slot is None or slot.assignment is None:
        return False
    assignment = slot.assignment
    role = getattr(assignment, "role", None)
    return bool(
        assignment.user_id == user.pk
        and role is not None
        and role.code == GM_SLOT_CODE
        and role.is_active
        and assignment.revoked_at is None
        and assignment.start_at is not None
        and assignment.start_at <= now
        and (assignment.end_at is None or assignment.end_at > now)
    )


def user_requires_mfa(user, *, at=None) -> bool:
    """GM is always MFA-required; employee policy is explicitly GM-controlled."""
    if is_active_gm_holder(user, at=at):
        return True
    return SecurityMFARequirement.objects.filter(
        user=user, is_required=True
    ).exists()


def set_employee_mfa_requirement(actor, target, *, required: bool, reason: str, at=None):
    """Set employee MFA policy only from a currently authenticated GM service path."""
    if type(required) is not bool:
        raise ValidationError("required must be a Boolean")
    clean_reason = reason.strip() if isinstance(reason, str) else ""
    if not clean_reason or len(clean_reason) > 500:
        raise ValidationError("a reason of 1 to 500 characters is required")
    now = at or timezone.now()
    if not is_active_gm_holder(actor, at=now):
        raise PermissionDenied("only the active singleton GM may change employee MFA policy")
    if target is None or not getattr(target, "is_active", False):
        raise ValidationError("target employee must be active")
    if is_active_gm_holder(target, at=now):
        raise ValidationError("GM MFA is mandatory and cannot be disabled or configured as employee MFA")
    if required and not SecurityMFADevice.objects.filter(
        user=target, status=MFADeviceStatus.ACTIVE
    ).exists():
        raise ValidationError("employee must complete MFA enrollment before it is required")

    user_model = type(actor)
    try:
        with transaction.atomic():
            locked_ids = sorted({actor.pk, target.pk})
            list(user_model._default_manager.select_for_update().filter(pk__in=locked_ids).order_by("pk"))
            if not is_active_gm_holder(actor, at=now) or is_active_gm_holder(target, at=now):
                raise PermissionDenied("GM or employee identity changed during MFA policy update")
            policy, created = SecurityMFARequirement.objects.select_for_update().get_or_create(
                user=target,
                defaults={
                    "is_required": required,
                    "updated_by": actor,
                    "reason": clean_reason,
                },
            )
            previous = policy.is_required if not created else False
            if not created:
                policy.is_required = required
                policy.updated_by = actor
                policy.reason = clean_reason
                policy.save(update_fields=["is_required", "updated_by", "reason", "updated_at"])
            AuditEvent.objects.create(
                user=actor,
                action=AuditAction.UPDATE,
                entity="MFA_REQUIREMENT",
                entity_id=str(target.pk),
                previous_state={"required": previous},
                new_state={"required": required},
                reason=clean_reason,
            )
            return policy
    except (PermissionDenied, ValidationError):
        raise
