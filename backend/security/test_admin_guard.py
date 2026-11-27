"""W0-2B interim Admin deny-all regression tests.

The approved Admin contract is GM-only with mandatory MFA. Until the
GM+MFA+lockout gate is implemented, no account may use Django Admin.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve

User = get_user_model()


class AdminTemporarilyDisabledTests(TestCase):
    ADMIN_PATHS = (
        "/admin/",
        "/admin/login/",
        "/admin/logout/",
        "/admin/auth/user/",
        "/admin/jsi18n/",
        "/admin/security/role/",
        "/admin/anything/nested/",
    )

    def test_anonymous_requests_cannot_reach_any_admin_route(self):
        for path in self.ADMIN_PATHS:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(b"Log in", response.content)

    def test_staff_superuser_and_gm_candidate_cannot_reach_admin(self):
        # None of these account flags is a substitute for the not-yet-built
        # singleton-GM + MFA + lockout Admin gate.
        users = (
            User.objects.create_user(
                username="admin-disabled-staff",
                password="strong-test-password",
                is_staff=True,
            ),
            User.objects.create_user(
                username="admin-disabled-superuser",
                password="strong-test-password",
                is_staff=True,
                is_superuser=True,
            ),
        )
        for user in users:
            with self.subTest(username=user.username):
                self.client.force_login(user)
                for path in self.ADMIN_PATHS:
                    with self.subTest(path=path):
                        response = self.client.get(path)
                        self.assertEqual(response.status_code, 404)
                self.client.logout()

    def test_admin_namespace_is_not_mounted_to_default_admin_site(self):
        match = resolve("/admin/auth/user/")
        self.assertEqual(match.func.__module__, "security.admin_guard")
        self.assertEqual(match.func.__name__, "admin_temporarily_disabled")
