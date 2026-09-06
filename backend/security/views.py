from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from .permissions import IsAuthenticatedForERP


@api_view(["GET"])
@authentication_classes([SessionAuthentication, BasicAuthentication])
@permission_classes([IsAuthenticatedForERP])
def current_user(request):
    return Response({"id": request.user.pk, "username": request.user.get_username()})
