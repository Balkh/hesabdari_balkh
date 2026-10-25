"""Regression tests for the Batch 1 secure DRF defaults.

Pins the security contract introduced alongside main @ 12d78fb:

1. DRF defaults require an authenticated ERP user.
2. A view that forgets explicit permission classes is NOT public.
3. The three core infrastructure endpoints stay intentionally public.
4. The anonymous throttle rate is enforced at runtime (behavioral), and
   permission-rejected requests never consume the throttle budget.
5. Production settings carry transport hardening; non-production
   profiles do not inherit it (local runs stay untouched). HSTS
   includeSubDomains/preload stay disabled until a documented domain
   architecture exists (see config/settings/production.py).
"""
import os
import sys
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView
from rest_framework.decorators import api_view


# Module-level urlconf used to exercise the DRF defaults exactly as a
# new endpoint would be written: no explicit permission classes.
from django.urls import path


@api_view(["GET"])
def unannotated_endpoint(request):
    return Response({"ok": True})


urlpatterns = [path("unannotated/", unannotated_endpoint)]


class SecureDefaultPermissionTests(TestCase):
    def test_drf_default_permission_is_secure(self):
        self.assertEqual(
            settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"],
            ["security.permissions.IsAuthenticatedForERP"],
        )

    def test_drf_default_authentication_is_session_and_basic(self):
        self.assertEqual(
            settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"],
            [
                "rest_framework.authentication.SessionAuthentication",
                "rest_framework.authentication.BasicAuthentication",
            ],
        )

    @override_settings(ROOT_URLCONF="security.test_security_defaults")
    def test_view_without_explicit_permissions_rejects_anonymous(self):
        response = APIClient().get("/unannotated/")
        self.assertIn(response.status_code, (401, 403))

    @override_settings(ROOT_URLCONF="security.test_security_defaults")
    def test_view_without_explicit_permissions_allows_authenticated(self):
        user = get_user_model().objects.create_user(
            username="erp-user", password="Strong-test-password-123"
        )
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get("/unannotated/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})


class ThrottleDefaultTests(SimpleTestCase):
    def test_throttling_is_configured_by_default(self):
        classes = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"]
        self.assertIn("rest_framework.throttling.AnonRateThrottle", classes)
        self.assertIn("rest_framework.throttling.UserRateThrottle", classes)
        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        self.assertEqual(rates["anon"], "60/min")
        self.assertEqual(rates["user"], "600/min")


class AnonymousThrottleBehaviorTests(TestCase):
    """Behavioral proof that the anon throttle is enforced at runtime:
    with a 2/min anon rate the third anonymous request to a public
    endpoint is rejected with 429, while permission-rejected requests on
    protected endpoints never reach the throttle (DRF checks permissions
    before throttles), so they never consume the anonymous budget.

    The rate is injected on AnonRateThrottle.THROTTLE_RATES because DRF
    freezes that class attribute at import time (override_settings on
    REST_FRAMEWORK does not affect it in-process); identification, cache
    counting and the 429 response are exercised for real. An isolated
    locmem cache keeps the test deterministic and prevents budget leaks
    between tests. TestCase (not SimpleTestCase) because the real health
    probe touches the DB through connection.cursor()."""

    _ISOLATED_CACHE = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "security-throttle-behavior-tests",
        }
    }

    _REDUCED_RATES = {"anon": "2/min", "user": "600/min"}

    @override_settings(CACHES=_ISOLATED_CACHE)
    def test_anonymous_throttle_rate_is_enforced_on_public_endpoint(self):
        from django.core.cache import cache
        from rest_framework.throttling import AnonRateThrottle

        cache.clear()
        client = APIClient()
        with mock.patch.object(AnonRateThrottle, "THROTTLE_RATES", self._REDUCED_RATES):
            codes = [client.get("/api/v1/health/").status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 429, 429])

    @override_settings(CACHES=_ISOLATED_CACHE)
    def test_permission_rejected_requests_do_not_consume_throttle_budget(self):
        from django.core.cache import cache
        from rest_framework.throttling import AnonRateThrottle

        cache.clear()
        client = APIClient()
        with mock.patch.object(AnonRateThrottle, "THROTTLE_RATES", self._REDUCED_RATES):
            # Six permission rejections (403) must not consume the anon budget...
            for _ in range(6):
                self.assertEqual(client.get("/api/v1/fiscal-periods/").status_code, 403)
            # ...so the next public request is only the FIRST counted hit (not 429).
            self.assertEqual(client.get("/api/v1/health/").status_code, 200)


class PublicInfrastructureEndpointsTests(TestCase):
    def test_health_api_root_and_missing_probe_stay_anonymous(self):
        client = APIClient()
        self.assertEqual(client.get("/api/v1/health/").status_code, 200)
        self.assertEqual(client.get("/api/v1/").status_code, 200)
        self.assertEqual(client.get("/api/v1/health/missing/").status_code, 404)


PRODUCTION_ENV = {
    "DJANGO_SECRET_KEY": "production-settings-test-key",
    "DJANGO_DEBUG": "false",
    "DJANGO_ALLOWED_HOSTS": "hesabdari.example",
    "POSTGRES_DB": "erp_afghanistan",
    "POSTGRES_USER": "erp_afghanistan",
    "POSTGRES_PASSWORD": "replace-me",
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5432",
}

_PRODUCTION_BOOT_SCRIPT = """
import django, json
django.setup()
from django.conf import settings
payload = {
    "SECURE_SSL_REDIRECT": settings.SECURE_SSL_REDIRECT,
    "SECURE_PROXY_SSL_HEADER": list(settings.SECURE_PROXY_SSL_HEADER),
    "SESSION_COOKIE_SECURE": settings.SESSION_COOKIE_SECURE,
    "CSRF_COOKIE_SECURE": settings.CSRF_COOKIE_SECURE,
    "SECURE_HSTS_SECONDS": settings.SECURE_HSTS_SECONDS,
    "SECURE_HSTS_INCLUDE_SUBDOMAINS": settings.SECURE_HSTS_INCLUDE_SUBDOMAINS,
    "SECURE_HSTS_PRELOAD": settings.SECURE_HSTS_PRELOAD,
    "DEBUG": settings.DEBUG,
    "DB_ENGINE": settings.DATABASES["default"]["ENGINE"],
}
print(json.dumps(payload))
"""


class ProductionSettingsHardeningTests(SimpleTestCase):
    def _boot_production_settings(self):
        """Boot the real production settings module in a clean subprocess
        (the same way a production process would) and return its flags.
        Subprocess isolation keeps the active test settings untouched."""
        import json
        import subprocess
        from pathlib import Path

        backend_dir = Path(__file__).resolve().parents[1]
        env = {**os.environ, **PRODUCTION_ENV,
               "DJANGO_SETTINGS_MODULE": "config.settings.production"}
        result = subprocess.run(
            [sys.executable, "-c", _PRODUCTION_BOOT_SCRIPT],
            env=env, cwd=backend_dir, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(
            result.returncode, 0,
            f"production settings failed to boot:\n{result.stderr}",
        )
        return json.loads(result.stdout)

    def test_production_settings_carry_transport_hardening(self):
        flags = self._boot_production_settings()
        self.assertTrue(flags["SECURE_SSL_REDIRECT"])
        self.assertEqual(
            flags["SECURE_PROXY_SSL_HEADER"], ["HTTP_X_FORWARDED_PROTO", "https"]
        )
        self.assertTrue(flags["SESSION_COOKIE_SECURE"])
        self.assertTrue(flags["CSRF_COOKIE_SECURE"])
        self.assertEqual(flags["SECURE_HSTS_SECONDS"], 31536000)
        # includeSubDomains/preload stay disabled: no documented public
        # domain or subdomain architecture exists yet (see production.py).
        self.assertFalse(flags["SECURE_HSTS_INCLUDE_SUBDOMAINS"])
        self.assertFalse(flags["SECURE_HSTS_PRELOAD"])
        # Fail-fast guards from the pre-existing production contract hold.
        self.assertFalse(flags["DEBUG"])
        self.assertEqual(flags["DB_ENGINE"], "django.db.backends.postgresql")

    def test_non_production_profiles_do_not_inherit_hardening(self):
        # Django 5.2 exposes global_settings defaults on the settings object,
        # so the correct tripwire is "equal to the Django default": the
        # active test/development profiles must keep running with Django's
        # unhardened defaults so local runs are never broken.
        from django.conf import global_settings

        self.assertEqual(settings.SECURE_SSL_REDIRECT, global_settings.SECURE_SSL_REDIRECT)
        self.assertEqual(settings.SESSION_COOKIE_SECURE, global_settings.SESSION_COOKIE_SECURE)
        self.assertEqual(settings.CSRF_COOKIE_SECURE, global_settings.CSRF_COOKIE_SECURE)
        self.assertEqual(settings.SECURE_HSTS_SECONDS, global_settings.SECURE_HSTS_SECONDS)
