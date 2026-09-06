import logging
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API exception", exc_info=exc)
        return Response(
            {"error": {"code": "internal_error", "message": "An unexpected error occurred."}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    detail = response.data
    if isinstance(detail, dict):
        message = detail.get("detail") or "Request validation failed."
    else:
        message = "Request validation failed."
    return Response(
        {"error": {"code": f"http_{response.status_code}", "message": str(message), "details": detail}},
        status=response.status_code,
        headers=response.headers,
    )
