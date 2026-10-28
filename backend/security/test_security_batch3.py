"""Regression tests for Security Batch 3 (owner-approved scope).

Grounded in the Batch 3 discovery findings recorded in the shared audit
worklog (Task 10) and re-verified against the source at main @ c669410
before any test was written. Scope of this module:

1. F-10 negative-path matrix: every production fail-fast contract gets a
   dedicated, isolated subprocess test — each ``POSTGRES_*`` variable
   missing individually and several missing jointly, ``DJANGO_DEBUG=true``,
   empty/unset/whitespace-only ``DJANGO_ALLOWED_HOSTS``, missing/empty/
   development-default/short ``DJANGO_SECRET_KEY``, and the Batch 3
   wildcard-host rejection.
2. Positive startup: production settings boot with a valid explicit
   configuration, and both WSGI and ASGI boot with an explicitly selected
   valid settings module (the fail-fast guard must fire only for missing
   selection, never for an explicit one).
3. B3-B-01 characterization: DRF throttle counters are stored in Django's
   default per-process local-memory cache. Pinned so any future
   shared-cache change is a conscious, owner-approved decision.
4. 403/no-side-effect: an unauthorized write to a protected endpoint is
   denied AND persists neither a domain row nor an audit event.
5. Secret hygiene: failure output never discloses configured values.

The only runtime-behavior change in this batch is the production wildcard
guard in ``config/settings/production.py`` (owner-authorized); everything
here is test-only and isolated in subprocesses where settings selection
matters.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from fiscal_periods.models import FiscalPeriod
from security.models import AuditEvent

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _isolated_env():
    """Subprocess environment containing NOTHING inherited from the
    developer's shell: no ``DJANGO_*``, no ``POSTGRES_*``, no secrets.
    Every required variable is supplied explicitly by the calling test,
    so results cannot depend on the host environment."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "C.UTF-8",
    }


def _run_python(code, extra_env):
    env = _isolated_env()
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _without(env, *names):
    return {key: value for key, value in env.items() if key not in names}


VALID_PRODUCTION_ENV = {
    "DJANGO_SETTINGS_MODULE": "config.settings.production",
    # Deterministic, test-only values. The key satisfies the Batch 2
    # >= 50-character production guard and is never a real credential.
    "DJANGO_SECRET_KEY": "batch3-test-only-production-secret-key-0123456789abcdef",
    "DJANGO_DEBUG": "false",
    "DJANGO_ALLOWED_HOSTS": "hesabdari.example,api.hesabdari.example",
    "POSTGRES_DB": "erp_afghanistan",
    "POSTGRES_USER": "erp_afghanistan",
    "POSTGRES_PASSWORD": "test-only-placeholder",
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5432",
}

# Boot script: reports only non-secret facts (a LENGTH, never the key).
_PRODUCTION_BOOT_SCRIPT = """
import django, json
django.setup()
from django.conf import settings
payload = {
    "DEBUG": settings.DEBUG,
    "ALLOWED_HOSTS": settings.ALLOWED_HOSTS,
    "SECRET_KEY_LENGTH": len(settings.SECRET_KEY),
    "DB_ENGINE": settings.DATABASES["default"]["ENGINE"],
    "STATIC_ROOT_SET": bool(settings.STATIC_ROOT),
}
print(json.dumps(payload))
"""

_BOOT_ENTRYPOINT = (
    "import importlib; "
    "module = importlib.import_module({module!r}); "
    "application = module.application; "
    "assert application is not None"
)


class ProductionFixtureGuardTests(SimpleTestCase):
    """The positive-path fixture itself must stay inside the production
    contract — the same coupling that regressed Batch 2 CI when the
    50-character guard landed (pinned there too; repeated here for this
    batch's independent fixture)."""

    def test_production_env_fixture_meets_secret_minimum(self):
        self.assertGreaterEqual(len(VALID_PRODUCTION_ENV["DJANGO_SECRET_KEY"]), 50)
        self.assertNotEqual(
            VALID_PRODUCTION_ENV["DJANGO_SECRET_KEY"], "development-only-insecure-key"
        )

    def test_production_env_fixture_uses_explicit_hosts(self):
        self.assertNotIn("*", VALID_PRODUCTION_ENV["DJANGO_ALLOWED_HOSTS"])
        self.assertTrue(VALID_PRODUCTION_ENV["DJANGO_ALLOWED_HOSTS"])


class ProductionNegativePathTests(SimpleTestCase):
    """F-10 matrix: every required production variable and guard value
    fails startup deterministically, naming the offending variable and
    never echoing configured values. Each case runs the real production
    settings module in a subprocess with a fully isolated environment."""

    def _boot_fails_with(self, env, expected_fragment, code="import django; django.setup()"):
        result = _run_python(code, env)
        self.assertNotEqual(
            result.returncode, 0, f"production settings booted unexpectedly:\n{result.stdout}"
        )
        self.assertIn(expected_fragment, result.stderr)
        return result

    def test_production_rejects_each_missing_postgres_variable(self):
        for name in (
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_HOST",
            "POSTGRES_PORT",
        ):
            with self.subTest(variable=name):
                self._boot_fails_with(
                    _without(VALID_PRODUCTION_ENV, name), name
                )

    def test_production_rejects_simultaneously_missing_postgres_variables(self):
        result = self._boot_fails_with(
            _without(VALID_PRODUCTION_ENV, "POSTGRES_DB", "POSTGRES_HOST", "POSTGRES_PORT"),
            "KeyError",
        )
        # The failure names a required variable (the first missing one in
        # evaluation order) without echoing any configured value.
        self.assertIn("POSTGRES_", result.stderr)

    def test_production_rejects_debug_true(self):
        self._boot_fails_with(
            {**VALID_PRODUCTION_ENV, "DJANGO_DEBUG": "true"},
            "DJANGO_DEBUG must be false in production",
        )

    def test_production_rejects_empty_or_unset_allowed_hosts(self):
        cases = {
            "unset": _without(VALID_PRODUCTION_ENV, "DJANGO_ALLOWED_HOSTS"),
            "empty-string": {**VALID_PRODUCTION_ENV, "DJANGO_ALLOWED_HOSTS": ""},
            "whitespace-only": {**VALID_PRODUCTION_ENV, "DJANGO_ALLOWED_HOSTS": " , , "},
        }
        for label, env in cases.items():
            with self.subTest(case=label):
                self._boot_fails_with(
                    env, "DJANGO_ALLOWED_HOSTS must be set in production"
                )

    def test_production_rejects_missing_empty_default_and_short_secret_key(self):
        dev_default = "development-only-insecure-key"
        cases = {
            "unset": (
                _without(VALID_PRODUCTION_ENV, "DJANGO_SECRET_KEY"),
                "DJANGO_SECRET_KEY must be set in production",
            ),
            "development-default": (
                {**VALID_PRODUCTION_ENV, "DJANGO_SECRET_KEY": dev_default},
                "DJANGO_SECRET_KEY must be set in production",
            ),
            "empty-string": (
                {**VALID_PRODUCTION_ENV, "DJANGO_SECRET_KEY": ""},
                "DJANGO_SECRET_KEY must be at least 50 characters in production",
            ),
            "too-short": (
                {**VALID_PRODUCTION_ENV, "DJANGO_SECRET_KEY": "short-key"},
                "DJANGO_SECRET_KEY must be at least 50 characters in production",
            ),
        }
        for label, (env, expected) in cases.items():
            with self.subTest(case=label):
                self._boot_fails_with(env, expected)

    def test_production_rejects_wildcard_allowed_hosts_entry(self):
        # The Batch 3 guard: `*` must be rejected wherever it appears as a
        # parsed entry — alone, mixed with valid hosts, or padded — while
        # the existing parser (strip + drop empty) still feeds it.
        cases = {
            "alone": "*",
            "with-valid-host": "hesabdari.example,*",
            "whitespace-padded": "hesabdari.example , * ",
        }
        for label, hosts in cases.items():
            with self.subTest(case=label):
                self._boot_fails_with(
                    {**VALID_PRODUCTION_ENV, "DJANGO_ALLOWED_HOSTS": hosts},
                    "DJANGO_ALLOWED_HOSTS must not contain the wildcard",
                )

    def test_failure_output_does_not_disclose_configured_secret_values(self):
        secret = VALID_PRODUCTION_ENV["DJANGO_SECRET_KEY"]
        password = VALID_PRODUCTION_ENV["POSTGRES_PASSWORD"]
        cases = {
            "debug-guard": {**VALID_PRODUCTION_ENV, "DJANGO_DEBUG": "true"},
            "missing-postgres-db": _without(VALID_PRODUCTION_ENV, "POSTGRES_DB"),
        }
        for label, env in cases.items():
            with self.subTest(case=label):
                result = _run_python("import django; django.setup()", env)
                self.assertNotEqual(result.returncode, 0)
                output = result.stdout + result.stderr
                self.assertNotIn(secret, output)
                self.assertNotIn(password, output)

    def test_wsgi_and_asgi_fail_before_serving_on_wildcard_hosts(self):
        # Interaction case: the guard must fire through the real server
        # entrypoints — before `application` exists, i.e. before the
        # process can serve any request. Each subprocess imports the
        # actual entrypoint module (config.wsgi / config.asgi) via the
        # same _BOOT_ENTRYPOINT script the positive boot tests use. A
        # pass here therefore cannot come from a settings-only boot or
        # an unrelated startup failure: the pinned fragment is produced
        # only by the production wildcard guard, and the traceback must
        # show the entrypoint file itself.
        for module in ("config.wsgi", "config.asgi"):
            with self.subTest(module=module):
                result = self._boot_fails_with(
                    {**VALID_PRODUCTION_ENV, "DJANGO_ALLOWED_HOSTS": "*"},
                    "DJANGO_ALLOWED_HOSTS must not contain the wildcard",
                    code=_BOOT_ENTRYPOINT.format(module=module),
                )
                # The failure surfaced through the real entrypoint import
                # chain (config/wsgi.py, config/asgi.py), not before it.
                self.assertIn(f"{module.replace('.', '/')}.py", result.stderr)


class ProductionPositiveBootTests(SimpleTestCase):
    """Positive complements: a fully valid, explicit production
    configuration boots (flags verified without ever printing the
    secret), and the WSGI/ASGI entrypoints construct their application."""

    def test_production_boots_with_valid_explicit_configuration(self):
        result = _run_python(_PRODUCTION_BOOT_SCRIPT, VALID_PRODUCTION_ENV)
        self.assertEqual(
            result.returncode, 0, f"valid production settings failed to boot:\n{result.stderr}"
        )
        payload = json.loads(result.stdout)
        self.assertFalse(payload["DEBUG"])
        self.assertEqual(
            payload["ALLOWED_HOSTS"], ["hesabdari.example", "api.hesabdari.example"]
        )
        self.assertGreaterEqual(payload["SECRET_KEY_LENGTH"], 50)
        self.assertEqual(payload["DB_ENGINE"], "django.db.backends.postgresql")
        self.assertTrue(payload["STATIC_ROOT_SET"])

    def test_production_wsgi_and_asgi_boot_with_valid_explicit_hosts(self):
        for module in ("config.wsgi", "config.asgi"):
            with self.subTest(module=module):
                result = _run_python(
                    _BOOT_ENTRYPOINT.format(module=module), VALID_PRODUCTION_ENV
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    f"{module} failed to boot with valid production settings:\n{result.stderr}",
                )

    def test_wsgi_and_asgi_boot_with_explicit_test_settings(self):
        # A valid, explicitly selected non-production module boots both
        # entrypoints: the missing-selection fail-fast guard never fires
        # for explicit selection. Uses the test profile, so no production
        # secrets or infrastructure are required.
        for module in ("config.wsgi", "config.asgi"):
            with self.subTest(module=module):
                result = _run_python(
                    _BOOT_ENTRYPOINT.format(module=module),
                    {"DJANGO_SETTINGS_MODULE": "config.settings.test"},
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    f"{module} failed to boot with explicit test settings:\n{result.stderr}",
                )


class ThrottleCacheCharacterizationTests(SimpleTestCase):
    """B3-B-01 characterization (Batch 3 discovery, Workstream B).

    Current behavior: no settings profile configures ``CACHES``, so DRF's
    request throttles count against Django's default local-memory cache.
    That cache is per-process: counters are NOT shared between workers or
    servers, which makes the throttle a local safeguard rather than a
    complete brute-force defense. The owner has deferred the shared-cache
    (Redis) decision — this test pins the current behavior so any future
    change is conscious. It changes no behavior itself.
    """

    def test_throttle_counters_use_the_default_per_process_locmem_cache(self):
        from django.conf import global_settings
        from django.core.cache import cache
        from django.core.cache.backends.locmem import LocMemCache
        from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

        # The test profile leaves CACHES at the Django default.
        self.assertEqual(settings.CACHES, global_settings.CACHES)
        self.assertEqual(
            settings.CACHES["default"]["BACKEND"],
            "django.core.cache.backends.locmem.LocMemCache",
        )
        # DRF's throttles count against django.core.cache.cache:
        # rest_framework/throttling.py imports `cache as default_cache`
        # and binds `cache = default_cache` on SimpleRateThrottle.
        for throttle_cls in (AnonRateThrottle, UserRateThrottle):
            with self.subTest(throttle=throttle_cls.__name__):
                throttle = throttle_cls()
                self.assertIs(throttle.cache, cache)
        # The default alias resolves, in this process, to the per-process
        # local-memory backend instance.
        from django.core.cache import caches

        self.assertIsInstance(caches["default"], LocMemCache)


class DeniedFinancialWriteNoSideEffectTests(TestCase):
    """The 403/no-side-effect case (Batch 3 discovery, Workstream C/F).

    An anonymous POST to a protected financial write endpoint must be
    denied by the existing authentication model (no role policy is
    invented here — role granularity is owner-deferred), and the denial
    must persist NOTHING: neither a domain row nor an audit event. The
    database state is checked directly, not just the HTTP status.

    Complements the existing ``fiscal_periods.api_tests`` anonymous
    rejection test, which asserts only that no ``FiscalPeriod`` row is
    created and does not pin the denial mechanism (a bare 403 is
    ambiguous — the same lesson as the Batch 2 CSRF pin).
    """

    def test_anonymous_fiscal_period_create_denied_without_persisted_state(self):
        self.assertEqual(FiscalPeriod.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)
        response = APIClient().post(
            "/api/v1/fiscal-periods/",
            {"name": "FY 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        # Mechanism pin: the denial is DRF's not_authenticated path —
        # authenticators are configured but none succeeded, so
        # rest_framework/views.py:178-180 raises NotAuthenticated() and
        # the SessionAuthentication-first chain (no authenticate_header)
        # maps it to 403, exactly as in the Batch 2 Basic-auth pin. This
        # rules out throttling (429), CSRF ("CSRF Failed"), and domain
        # (400) rejections.
        body = response.json()
        self.assertEqual(body["error"]["code"], "http_403")
        self.assertEqual(
            body["error"]["message"], "Authentication credentials were not provided."
        )
        # Protected state invariant: nothing persisted anywhere.
        self.assertEqual(FiscalPeriod.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)
