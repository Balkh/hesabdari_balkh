"""Regression tests for Security Batch 2 startup and authentication guards."""
import base64
import os
import subprocess
import sys
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import path
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.test import APIClient


@api_view(["POST"])
def csrf_probe(request):
    return Response({"ok": True})


urlpatterns = [path("csrf-probe/", csrf_probe)]


class RealBasicAuthenticationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="batch2-basic-user",
            password="Strong-test-password-123",
        )

    def _basic_client(self, password):
        token = base64.b64encode(
            f"{self.user.username}:{password}".encode("utf-8")
        ).decode("ascii")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Basic {token}")
        return client

    def test_basic_authentication_accepts_valid_credentials(self):
        response = self._basic_client("Strong-test-password-123").get(
            "/api/v1/security/me/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], self.user.username)

    def test_basic_authentication_rejects_invalid_password(self):
        response = self._basic_client("incorrect-password").get(
            "/api/v1/security/me/"
        )
        # Deterministic 403 (not 401): DEFAULT_AUTHENTICATION_CLASSES lists
        # SessionAuthentication first and it exposes no authenticate_header,
        # so DRF cannot emit a WWW-Authenticate challenge and maps the failed
        # Basic authentication to 403 (rest_framework/views.py:461-464).
        self.assertEqual(response.status_code, 403)


class SessionAuthenticationCsrfTests(TestCase):
    def test_authenticated_session_post_without_csrf_is_rejected(self):
        user = get_user_model().objects.create_user(
            username="batch2-csrf-user",
            password="Strong-test-password-123",
        )
        client = APIClient(enforce_csrf_checks=True)
        self.assertTrue(client.login(
            username="batch2-csrf-user",
            password="Strong-test-password-123",
        ))
        from django.test import override_settings

        with override_settings(ROOT_URLCONF="security.test_security_batch2"):
            response = client.post("/csrf-probe/", {}, format="json")
        self.assertEqual(response.status_code, 403)
        # Pin the mechanism: SessionAuthentication's CSRF enforcement (not an
        # unrelated permission/URL/authentication failure) must produce the
        # rejection. An anonymous request to the same URL is also 403 but with
        # a not_authenticated detail, so the status alone is ambiguous.
        self.assertIn("CSRF Failed", response.content.decode())


class ProductionFailFastTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parents[1]

    def _run_python(self, code, env):
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=self.backend_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_wsgi_and_asgi_refuse_implicit_settings_profile(self):
        env = dict(os.environ)
        env.pop("DJANGO_SETTINGS_MODULE", None)
        env.pop("PYTHONPATH", None)
        for module in ("config.wsgi", "config.asgi"):
            with self.subTest(module=module):
                result = self._run_python(f"import {module}", env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("DJANGO_SETTINGS_MODULE must be set explicitly", result.stderr)

    def test_production_rejects_short_secret_key(self):
        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "DJANGO_SECRET_KEY": "short-key",
            "DJANGO_DEBUG": "false",
            "DJANGO_ALLOWED_HOSTS": "hesabdari.example",
            "POSTGRES_DB": "erp_afghanistan",
            "POSTGRES_USER": "erp_afghanistan",
            "POSTGRES_PASSWORD": "test-only-placeholder",
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "5432",
        }
        result = self._run_python("import django; django.setup()", env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY must be at least 50 characters", result.stderr)
