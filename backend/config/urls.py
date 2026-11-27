from django.urls import include, path, re_path

from security.admin_guard import admin_temporarily_disabled


urlpatterns = [
    # W0-2B interim fail-closed guard: Django Admin remains unavailable until
    # the approved GM-only + mandatory-MFA + lockout gate is implemented.
    re_path(r"^admin(?:/.*)?$", admin_temporarily_disabled, name="admin-disabled"),
    path("api/v1/", include("core.urls")),
    path("api/v1/security/", include("security.urls")),
    path("api/v1/fiscal-periods/", include("fiscal_periods.urls")),
    path("api/v1/purchases/", include("purchases.urls")),
]
