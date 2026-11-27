"""Request context and pre-authentication Basic login throttling (W0-2D)."""

from __future__ import annotations

import base64
import binascii
import logging
from contextvars import ContextVar

from django.http import JsonResponse

_current_request = ContextVar("security_current_request", default=None)
logger = logging.getLogger("security.login_protection")


def get_current_request():
    """Return the request currently executing in this sync/async context."""
    return _current_request.get()


def _basic_username(request):
    header = request.META.get("HTTP_AUTHORIZATION", "")
    scheme, separator, token = header.partition(" ")
    if not separator or scheme.lower() != "basic" or not token:
        return None
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    username, separator, _password = decoded.partition(":")
    return username if separator and username else None


class SecurityLoginProtectionMiddleware:
    """Bind request context to auth signals and throttle Basic failures.

    The account/source rate is read from the existing DRF security_login
    setting. No new numeric rate or external cache service is introduced.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current_request.set(request)
        try:
            if request.path.startswith("/api/v1/"):
                username = _basic_username(request)
                if username is not None:
                    try:
                        from security.login_lockout import is_login_rate_limited

                        if is_login_rate_limited(username, request):
                            return JsonResponse(
                                {"error": "authentication_rate_limited"},
                                status=429,
                            )
                    except Exception:
                        logger.exception(
                            "BasicAuthentication account/source rate state unavailable"
                        )
                        return JsonResponse(
                            {"error": "authentication_unavailable"},
                            status=503,
                        )
            return self.get_response(request)
        finally:
            _current_request.reset(token)
