"""GM-only employee MFA policy API."""
import logging

from django.contrib.auth import get_user_model, logout as django_logout
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from security.mfa_policy import set_employee_mfa_requirement
from security.mfa_models import SecurityLoginSession
from security.mfa_service import (
    MFAAlreadyEnrolled,
    MFAEnrollmentLocked,
    MFAEnrollmentPolicyDenied,
    MFAEnrollmentRequired,
    MFAInvalidCode,
    begin_mfa_enrollment,
    confirm_mfa_enrollment,
    disable_employee_mfa,
    rotate_recovery_codes,
)
from security.operation_registry import OBJECT, TARGET_REQUEST_USER, OperationSpec, erp_operations
logger = logging.getLogger("security.mfa_views")


from security.permissions import (
    HasErpOperation,
    IsAuthenticatedForERP,
    IsEmployeeMFAAccount,
    IsGMWithVerifiedMFA,
)


@csrf_protect
@erp_operations(
    POST=OperationSpec(
        operation_id="security.mfa.policy.update_employee",
        permission_key="security.mfa.reset",
        binding_kind="COLLECTION",
    )
)
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticatedForERP, HasErpOperation, IsGMWithVerifiedMFA])
def set_employee_mfa_policy(request, user_id):
    """Enable or disable employee MFA only from an MFA-verified GM session."""
    required = request.data.get("required")
    reason = request.data.get("reason")
    if type(required) is not bool or not isinstance(reason, str):
        return Response({"error": "invalid_policy_request"}, status=status.HTTP_400_BAD_REQUEST)
    target = get_object_or_404(get_user_model(), pk=user_id)
    try:
        policy = set_employee_mfa_requirement(
            request.user, target, required=required, reason=reason
        )
    except PermissionDenied:
        return Response({"error": "permission_denied"}, status=status.HTTP_403_FORBIDDEN)
    except ValidationError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({
        "user_id": target.pk,
        "mfa_required": policy.is_required,
        "updated_at": policy.updated_at.isoformat(),
    })


def _key_provider():
    from security.auth_views import _key_provider as get_provider
    return get_provider()


def _mark_session_mfa_verified(request, at):
    from security.session_service import session_key_digest

    session_key = getattr(request.session, "session_key", None)
    if not session_key:
        raise RuntimeError("authenticated session key is missing")
    changed = SecurityLoginSession.objects.filter(
        user=request.user,
        session_key_hash=session_key_digest(session_key),
        revoked_at__isnull=True,
    ).update(mfa_verified_at=at)
    if changed != 1:
        raise RuntimeError("registered session is unavailable")


@csrf_protect
@erp_operations(
    POST=OperationSpec(
        operation_id="security.mfa.enroll.start_own",
        permission_key="security.mfa.enroll_own",
        binding_kind=OBJECT,
        target_kind="SELF_USER",
        target_source=TARGET_REQUEST_USER,
    )
)
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticatedForERP, HasErpOperation, IsEmployeeMFAAccount])
def mfa_enrollment_start(request):
    """Create a pending encrypted TOTP credential; return enrollment data once."""
    provider = _key_provider()
    if provider is None:
        return Response({"error": "mfa_key_provider_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        material = begin_mfa_enrollment(request.user, provider=provider)
    except MFAAlreadyEnrolled:
        return Response({"error": "mfa_already_enrolled"}, status=status.HTTP_409_CONFLICT)
    except Exception:
        logger.exception("employee MFA enrollment start failed")
        return Response({"error": "mfa_enrollment_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(material, status=status.HTTP_201_CREATED)


@csrf_protect
@erp_operations(
    POST=OperationSpec(
        operation_id="security.mfa.enroll.confirm_own",
        permission_key="security.mfa.enroll_own",
        binding_kind=OBJECT,
        target_kind="SELF_USER",
        target_source=TARGET_REQUEST_USER,
    )
)
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticatedForERP, HasErpOperation, IsEmployeeMFAAccount])
def mfa_enrollment_confirm(request):
    """Confirm TOTP and return ten one-time recovery codes exactly once."""
    code = request.data.get("totp_code")
    if not isinstance(code, str):
        return Response({"error": "invalid_mfa_code"}, status=status.HTTP_400_BAD_REQUEST)
    provider = _key_provider()
    if provider is None:
        return Response({"error": "mfa_key_provider_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    from django.db import transaction
    from django.utils import timezone

    now = timezone.now()
    try:
        with transaction.atomic():
            codes = confirm_mfa_enrollment(
                request.user, code, provider=provider, at=now
            )
            _mark_session_mfa_verified(request, now)
    except MFAEnrollmentRequired:
        return Response({"error": "mfa_enrollment_not_started"}, status=status.HTTP_409_CONFLICT)
    except MFAEnrollmentLocked:
        return Response({"error": "mfa_enrollment_locked"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    except MFAInvalidCode:
        return Response({"error": "invalid_mfa_code"}, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        logger.exception("employee MFA enrollment confirmation failed")
        return Response({"error": "mfa_enrollment_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"status": "enrolled", "recovery_codes": codes})


@csrf_protect
@erp_operations(
    POST=OperationSpec(
        operation_id="security.mfa.recovery.rotate_own",
        permission_key="security.mfa.enroll_own",
        binding_kind=OBJECT,
        target_kind="SELF_USER",
        target_source=TARGET_REQUEST_USER,
    )
)
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticatedForERP, HasErpOperation])
def recovery_codes_rotate(request):
    """Rotate recovery codes after password plus TOTP or a single recovery code."""
    password = request.data.get("password")
    if not isinstance(password, str):
        return Response({"error": "invalid_credentials"}, status=status.HTTP_400_BAD_REQUEST)
    provider = _key_provider()
    if request.data.get("totp_code") and provider is None:
        return Response({"error": "mfa_key_provider_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    from django.db import transaction
    from django.utils import timezone

    now = timezone.now()
    try:
        with transaction.atomic():
            codes = rotate_recovery_codes(
                request.user,
                password=password,
                totp_code=request.data.get("totp_code"),
                recovery_code=request.data.get("recovery_code"),
                provider=provider,
                at=now,
            )
            _mark_session_mfa_verified(request, now)
    except MFAEnrollmentRequired:
        return Response({"error": "mfa_not_enrolled"}, status=status.HTTP_409_CONFLICT)
    except MFAInvalidCode:
        return Response({"error": "invalid_mfa_code"}, status=status.HTTP_401_UNAUTHORIZED)
    except Exception:
        logger.exception("employee recovery-code rotation failed")
        return Response({"error": "recovery_rotation_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"recovery_codes": codes})


@csrf_protect
@erp_operations(
    POST=OperationSpec(
        operation_id="security.mfa.disable_own",
        permission_key="security.mfa.enroll_own",
        binding_kind=OBJECT,
        target_kind="SELF_USER",
        target_source=TARGET_REQUEST_USER,
    )
)
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticatedForERP, HasErpOperation, IsEmployeeMFAAccount])
def mfa_disable(request):
    """Disable optional employee MFA after password and strong-factor proof."""
    provider = _key_provider()
    if request.data.get("totp_code") and provider is None:
        return Response({"error": "mfa_key_provider_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        disable_employee_mfa(
            request.user,
            password=request.data.get("password"),
            totp_code=request.data.get("totp_code"),
            recovery_code=request.data.get("recovery_code"),
            provider=provider,
        )
    except MFAEnrollmentPolicyDenied:
        return Response({"error": "mfa_disable_not_permitted"}, status=status.HTTP_403_FORBIDDEN)
    except MFAEnrollmentRequired:
        return Response({"error": "mfa_not_enrolled"}, status=status.HTTP_409_CONFLICT)
    except MFAInvalidCode:
        return Response({"error": "invalid_credentials"}, status=status.HTTP_401_UNAUTHORIZED)
    except Exception:
        logger.exception("employee MFA disable failed")
        return Response({"error": "mfa_disable_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    django_logout(request._request)
    return Response({"status": "mfa_disabled", "sessions_revoked": True})
