from rest_framework.permissions import BasePermission


class IsAuthenticatedForERP(BasePermission):
    message = "Authentication is required to access ERP resources."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)
