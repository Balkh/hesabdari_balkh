"""Password login/logout API with MFA and durable session admission."""
from __future__ import annotations

import hashlib
import logging

from django.conf import settings
from django.contrib.auth import authenticate, login as django_login, logout as django_logout
from django.db import DatabaseError, transaction
from django.utils import timezone
from django.utils.module_loading import import_string
from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from security.mfa_models import MFADeviceStatus, SecurityMFADevice
from security.mfa_policy import user_requires_mfa
from security.mfa_service import (
    consume_recovery_code,
    verify_user_totp,
)
from security.models import AuditAction, AuditEvent
from security.operation_registry import (
    OperationSpec,
    TARGET_REQUEST_USER,
    erp_operations,
)
from security.permissions import HasErpOperation, IsAuthenticatedForERP
from security.session_service import (
    SessionAdmissionError,
    register_login_session,
    revoke_login_session,
)

logger = logging.getLogger("security.authentication")


class LoginRateThrottle(AnonRateThrottle):
    scope = "security_login"


class LoginCSRFAuthentication(SessionAuthentication):
    """Enforce CSRF for anonymous password login despite DRF's csrf_exempt wrapper."""

    def authenticate(self, request):
        self.enforce_csrf(request)
        return None


def _key_provider():
    provider_path = getattr(settings, "ERP_MFA_KEY_PROVIDER", None)
    if not provider_path:
        return None
    try:
        provider_class = import_string(provider_path)
        return provider_class()
    except Exception:
        logger.exception("configured MFA key provider could not be initialized")
        return None


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def csrf_cookie(request):
    """Issue a CSRF cookie required by browser-based password login."""
    get_token(request._request)
    return Response({"csrf": "cookie-set"})


@api_view(["POST"])
@authentication_classes([LoginCSRFAuthentication])
@permission_classes([AllowAny])
@throttle_classes([LoginRateThrottle])
def login_view(request):
    """Authenticate password, require applicable MFA, then register one session."""
    username = request.data.get("username")
    password = request.data.get("password")
    if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
        return Response({"error": "invalid_credentials"}, status=status.HTTP_400_BAD_REQUEST)

    user = authenticate(
        request=request._request,
        username=username,
        password=password,
    )
    if user is None or not user.is_active:
        return Response({"error": "invalid_credentials"}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        required = user_requires_mfa(user)
    except Exception:
        logger.exception("MFA policy lookup failed closed")
        return Response({"error": "authentication_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    mfa_verified_at = None
    if required:
        if not SecurityMFADevice.objects.filter(
            user=user, status=MFADeviceStatus.ACTIVE
        ).exists():
            return Response({"error": "mfa_enrollment_required"}, status=status.HTTP_403_FORBIDDEN)

        totp_code = request.data.get("totp_code")
        recovery_code = request.data.get("recovery_code")
        if bool(totp_code) == bool(recovery_code):
            return Response({"error": "mfa_verification_required"}, status=status.HTTP_401_UNAUTHORIZED)

        now = timezone.now()
        try:
            if totp_code:
                provider = _key_provider()
                if provider is None:
                    return Response({"error": "mfa_key_provider_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
                verified = verify_user_totp(user, totp_code, provider=provider, at=now)
            else:
                verified = consume_recovery_code(user, recovery_code, at=now)
        except Exception:
            logger.exception("MFA verification failed closed")
            return Response({"error": "mfa_verification_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not verified:
            return Response({"error": "invalid_credentials"}, status=status.HTTP_401_UNAUTHORIZED)
        mfa_verified_at = now

    django_login(request._request, user)
    session = request._request.session
    try:
        session.save()
        session_key = session.session_key
        if not session_key:
            raise SessionAdmissionError("Django did not create a session key")
        now = timezone.now()
        with transaction.atomic():
            record = register_login_session(
                user,
                session_key,
                mfa_verified_at=mfa_verified_at,
                at=now,
            )
            agent = (request.META.get("HTTP_USER_AGENT") or "")[:512]
            agent_digest = hashlib.sha256(agent.encode("utf-8")).hexdigest() if agent else ""
            if agent_digest:
                record.user_agent_digest = agent_digest
                record.save(update_fields=["user_agent_digest"])
            AuditEvent.objects.create(
                user=user,
                action=AuditAction.LOGIN,
                entity="AUTH_SESSION",
                entity_id=str(user.pk),
                new_state={
                    "mfa_verified": mfa_verified_at is not None,
                    "session_slot": record.slot_number,
                },
            )
    except (SessionAdmissionError, DatabaseError):
        django_logout(request._request)
        return Response({"error": "session_limit_or_registry_unavailable"}, status=status.HTTP_409_CONFLICT)
    except Exception:
        django_logout(request._request)
        logger.exception("session registration failed closed")
        return Response({"error": "authentication_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response({
        "id": user.pk,
        "username": user.get_username(),
        "mfa_verified": mfa_verified_at is not None,
    })


@erp_operations(
    POST=OperationSpec(
        operation_id="security.auth.logout_own",
        permission_key="security.account.view_own",
        binding_kind="OBJECT",
        target_kind="SELF_USER",
        target_source=TARGET_REQUEST_USER,
    )
)
@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticatedForERP, HasErpOperation])
def logout_view(request):
    """Revoke the registered session before clearing Django's session cookie."""
    user = request.user
    session_key = getattr(request.session, "session_key", None)
    try:
        with transaction.atomic():
            if session_key:
                revoke_login_session(user, session_key, reason="LOGOUT")
            AuditEvent.objects.create(
                user=user,
                action=AuditAction.LOGOUT,
                entity="AUTH_SESSION",
                entity_id=str(user.pk),
                new_state={"session_revoked": bool(session_key)},
            )
    except Exception:
        logger.exception("logout revocation failed closed")
        return Response({"error": "logout_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    django_logout(request._request)
    return Response({"status": "logged_out"})
