"""Temporary fail-closed boundary for Django Admin.

The approved W0-2A contract requires Django Admin to be GM-only, with
mandatory GM MFA and account-lockout checks. Those authentication controls
are not implemented yet. Until the complete GM+MFA Admin gate is available,
the entire Admin URL namespace is deliberately unavailable to every caller.

Do not replace this with the default admin.site.urls. Re-enable Admin only
through a reviewed AdminSite implementation that checks the singleton-linked
active GM assignment, active account, current MFA assurance and lockout
state on every request.
"""

from django.http import HttpResponseNotFound


def admin_temporarily_disabled(request, *args, **kwargs):
    """Hide all Django Admin routes until the approved security gate exists."""
    return HttpResponseNotFound()
