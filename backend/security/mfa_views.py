"""GM-only employee MFA policy API."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from security.authorization import AuthContext
from security.mfa_policy import is_active_gm_holder, set_employee_mfa_requirement
from security.operation_registry import OperationSpec, erp_operations
from security.permissions import HasErpOperation, IsAuthenticatedForERP


class IsGMWithVerifiedMFA(BasePermission):
    message = "An active GM session with verified MFA is required."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        try:
            context = AuthContext.from_request(request)
            return bool(
                is_active_gm_holder(user)
                and context.requires_mfa
                and context.mfa_verified
                and context.session_user_id == user.pk
                and context.is_valid_for(user, timezone.now())
            )
        except Exception:
            return False


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
