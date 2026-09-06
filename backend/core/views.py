from django.db import connection
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["GET"])
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
