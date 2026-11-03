from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from .operation_registry import OperationSpec, TARGET_REQUEST_USER, erp_operations
from .permissions import HasErpOperation, IsAuthenticatedForERP


@erp_operations(
    GET=OperationSpec(
        operation_id="security.me.retrieve",
        permission_key="security.account.view_own",
        binding_kind="OBJECT",
        target_kind="SELF_USER",
        target_source=TARGET_REQUEST_USER,
    )
)
@api_view(["GET", "HEAD"])
@authentication_classes([SessionAuthentication, BasicAuthentication])
@permission_classes([IsAuthenticatedForERP, HasErpOperation])
def current_user(request):
    return Response({"id": request.user.pk, "username": request.user.get_username()})
