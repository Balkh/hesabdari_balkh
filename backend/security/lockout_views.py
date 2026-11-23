"""GM-only account lockout review and early-unlock API."""
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from security.login_lockout import unlock_account
from security.mfa_models import SecurityAccountLockout, SecurityLoginAttempt
from security.operation_registry import (
    BINDING_TARGET_USER, COLLECTION, OBJECT, TARGET_URL_KWARG,
    OperationSpec, erp_operations,
)
from security.permissions import HasErpOperation, IsAuthenticatedForERP, IsGMWithVerifiedMFA


@erp_operations(
    GET=OperationSpec(
        operation_id="security.lockout.review",
        permission_key="security.lockout.view",
        binding_kind=COLLECTION,
    )
)
@api_view(["GET", "HEAD"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticatedForERP, HasErpOperation, IsGMWithVerifiedMFA])
def lockout_collection(request):
    """Return active locks and bounded, sanitized recent authentication history."""
    try:
        limit = int(request.query_params.get("limit", "50"))
    except (TypeError, ValueError):
        return Response({"error": "invalid_limit"}, status=status.HTTP_400_BAD_REQUEST)
    if limit < 1 or limit > 100:
        return Response({"error": "invalid_limit"}, status=status.HTTP_400_BAD_REQUEST)

    now = timezone.now()
    lockouts = SecurityAccountLockout.objects.filter(
        locked_until__gt=now
    ).select_related("user").order_by("locked_until", "user_id")
    attempts = SecurityLoginAttempt.objects.select_related("user").order_by(
        "-occurred_at", "-id"
    )[:limit]
    return Response({
        "observed_at": now.isoformat(),
        "active_lockouts": [
            {
                "user_id": row.user_id,
                "username": row.user.get_username(),
                "failed_password_attempts": row.failed_password_attempts,
                "last_failed_at": row.last_failed_at.isoformat() if row.last_failed_at else None,
                "locked_until": row.locked_until.isoformat(),
            }
            for row in lockouts
        ],
        "recent_attempts": [
            {
                "id": row.pk,
                "user_id": row.user_id,
                "username": row.user.get_username() if row.user_id else None,
                "username_fingerprint": row.username_digest[:12],
                "source_fingerprint": row.source_digest[:12],
                "outcome": row.outcome,
                "occurred_at": row.occurred_at.isoformat(),
            }
            for row in attempts
        ],
    })


@csrf_protect
@erp_operations(
    POST=OperationSpec(
        operation_id="security.account.unlock",
        permission_key="security.account.unlock",
        binding_kind=OBJECT,
        target_kind=BINDING_TARGET_USER,
        target_source=TARGET_URL_KWARG,
        target_kwarg="user_id",
    )
)
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticatedForERP, HasErpOperation, IsGMWithVerifiedMFA])
def account_unlock(request, user_id):
    """Clear an active account lock with a GM-authored reason and audit event."""
    reason = request.data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return Response({"error": "unlock_reason_required"}, status=status.HTTP_400_BAD_REQUEST)
    target = get_object_or_404(get_user_model(), pk=user_id)
    state = unlock_account(target, request.user, reason=reason)
    if state is None:
        return Response({"error": "account_not_locked"}, status=status.HTTP_409_CONFLICT)
    return Response({
        "user_id": target.pk,
        "locked": False,
        "failed_password_attempts": state.failed_password_attempts,
        "locked_until": None,
    })
