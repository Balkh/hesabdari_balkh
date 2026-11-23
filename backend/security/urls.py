from django.urls import path

from . import audit_views, auth_views, lockout_views, mfa_views, views

urlpatterns = [
    path("audit/events/", audit_views.audit_events, name="security-audit-events"),
    path("audit/integrity/", audit_views.audit_integrity, name="security-audit-integrity"),
    path("me/", views.current_user, name="current-user"),
    path("csrf/", auth_views.csrf_cookie, name="security-csrf"),
    path("auth/login/", auth_views.login_view, name="security-login"),
    path("auth/logout/", auth_views.logout_view, name="security-logout"),
    path("lockouts/", lockout_views.lockout_collection, name="security-lockout-collection"),
    path("accounts/<int:user_id>/unlock/", lockout_views.account_unlock, name="security-account-unlock"),
    path("mfa/policy/<int:user_id>/", mfa_views.set_employee_mfa_policy, name="mfa-employee-policy"),
    path("mfa/enroll/start/", mfa_views.mfa_enrollment_start, name="mfa-enrollment-start"),
    path("mfa/enroll/confirm/", mfa_views.mfa_enrollment_confirm, name="mfa-enrollment-confirm"),
    path("mfa/recovery/rotate/", mfa_views.recovery_codes_rotate, name="mfa-recovery-rotate"),
    path("mfa/disable/", mfa_views.mfa_disable, name="mfa-disable"),
]
