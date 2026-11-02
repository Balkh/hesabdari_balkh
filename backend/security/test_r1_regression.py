"""W0-2A / R1 — regression safety tests.

Proves R1 changes no frozen behavior: Security Batch 2/3 pins still exist
and are untouched, the DRF defaults are unchanged, the existing accounting
contracts are outside R1's diff, and the frozen security test modules still
pin their mechanisms. The full-suite green run is the behavioral proof;
these structural assertions make the frozen surface explicit.
"""
from django.test import TestCase

from security import test_security_batch2, test_security_batch3
from security.permissions import IsAuthenticatedForERP


class FrozenSecurityPinPresenceTests(TestCase):
    def test_batch2_pins_exist(self):
        self.assertTrue(hasattr(test_security_batch2, "RealBasicAuthenticationTests"))
        self.assertTrue(hasattr(test_security_batch2, "SessionAuthenticationCsrfTests"))
        self.assertTrue(hasattr(test_security_batch2, "ProductionFailFastTests"))

    def test_batch3_pins_exist(self):
        self.assertTrue(
            hasattr(test_security_batch3, "ThrottleCacheCharacterizationTests")
        )
        self.assertTrue(
            hasattr(test_security_batch3, "DeniedFinancialWriteNoSideEffectTests")
        )

    def test_default_permission_class_unchanged(self):
        from django.conf import settings

        self.assertEqual(
            settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"],
            ["security.permissions.IsAuthenticatedForERP"],
        )
        self.assertEqual(
            IsAuthenticatedForERP.message,
            "Authentication is required to access ERP resources.",
        )

    def test_authentication_stack_unchanged(self):
        from django.conf import settings

        self.assertEqual(
            list(settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]),
            [
                "rest_framework.authentication.SessionAuthentication",
                "rest_framework.authentication.BasicAuthentication",
            ],
        )

    def test_r1_introduces_no_new_authentication_mechanism(self):
        """No new authenticator classes may appear in R1 (§3 non-goals)."""
        import inspect

        import security.authorization as authorization_module

        source = inspect.getsource(authorization_module)
        self.assertNotIn("BaseAuthentication", source)
        self.assertNotIn("authenticate_header", source)

    def test_r1_does_not_touch_accounting_contracts(self):
        """The resolver and models must not import or mutate accounting
        services; accounting behavior is proven unchanged by the full
        suite (accounting tests run unmodified)."""
        import inspect

        import security.authorization as authorization_module
        import security.models as models_module
        import security.seed as seed_module

        for module in (authorization_module, models_module, seed_module):
            source = inspect.getsource(module)
            self.assertNotIn("accounting.services", source)
            self.assertNotIn("accounting.models", source)
            self.assertNotIn("journal", source.lower().replace("journal_currency", ""))
