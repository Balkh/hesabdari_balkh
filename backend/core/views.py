from django.db import connection
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


# The three infrastructure endpoints below are the only intentionally
# public (AllowAny) API surfaces in the system. They expose no business
# or financial data and exist for health probing and error-contract
# discovery. Every other endpoint inherits the secure DRF default
# (security.permissions.IsAuthenticatedForERP) from settings.base.
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health_check(request):
    """Minimal infrastructure endpoint; it contains no business workflow."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        database_ok = cursor.fetchone() == (1,)
    return Response({
        "status": "ok",
        "service": "hesabdari_balkh-backend",
        "database": "ok" if database_ok else "error",
    })


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def missing_resource(request):
    raise NotFound("The requested resource was not found.")


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def api_root(request):
    return Response({"api": "v1", "service": "hesabdari_balkh", "status": "available"})
