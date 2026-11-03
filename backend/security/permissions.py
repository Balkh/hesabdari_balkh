from rest_framework.permissions import BasePermission


class IsAuthenticatedForERP(BasePermission):
    message = "Authentication is required to access ERP resources."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)



class HasErpOperation(BasePermission):
    """Constructor-free RBAC permission for a server-declared view+method operation."""

    message = "You do not have permission to perform this operation."

    def has_permission(self, request, view):
        import logging

        from django.conf import settings

        logger = logging.getLogger("security.operation_permissions")
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            # IsAuthenticatedForERP is intentionally first; this is defense in depth.
            return False

        enforcement = getattr(settings, "ERP_RBAC_ENFORCEMENT", None)
        if enforcement is False:
            # Development/test compatibility only: authentication still ran first.
            return True
        if enforcement is not True:
            logger.error("ERP_RBAC_ENFORCEMENT must be a strict Boolean")
            return False

        if request.method.upper() == "OPTIONS":
            # Authenticated capability discovery only; never runs a business operation.
            return True

        method = request.method.upper()
        if method == "HEAD":
            method = "GET"

        operation_map = getattr(view.__class__, "erp_operation_specs", {})
        operation = operation_map.get(method)
        if operation is None:
            logger.warning(
                "protected DRF method has no operation declaration",
                extra={"view": view.__class__.__name__, "method": method},
            )
            return False

        try:
            from security.authorization import AuthContext, resolve_operation

            target_reference = operation.build_target_reference(request, view)
            decision = resolve_operation(
                user,
                operation,
                auth_context=AuthContext.from_request(request),
                target_reference=target_reference,
            )
        except Exception:
            logger.exception(
                "operation authorization failed closed",
                extra={
                    "operation_id": getattr(operation, "operation_id", None),
                    "user_id": getattr(user, "pk", None),
                },
            )
            return False

        if not decision.allowed:
            request._erp_authorization_denial = {
                "operation_id": operation.operation_id,
                "permission_key": operation.permission_key,
                "reason": decision.reason,
            }
            return False
        return True
