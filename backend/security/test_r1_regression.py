"""W0-2A / R1 — regression safety tests.

Proves R1 changes no frozen behavior: Security Batch 2/3 pins still exist
and are untouched, the DRF defaults are unchanged, the existing accounting
contracts are outside R1's diff, and the frozen security test modules still
pin their mechanisms. The full-suite green run is the behavioral proof;
these structural assertions make the frozen surface explicit.
"""
import ast
from pathlib import Path

from django.apps import apps
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

    def test_no_first_party_view_module_imports_dormant_resolver(self):
        """R1 must not create a production request path to the dormant resolver."""
        backend_root = Path(__file__).resolve().parents[1]
        offenders = []
        for app_config in apps.get_app_configs():
            app_path = Path(app_config.path).resolve()
            if not app_path.is_relative_to(backend_root):
                continue
            for source_path in app_path.rglob("*.py"):
                relative = source_path.relative_to(app_path)
                is_view_module = (
                    source_path.name == "views.py"
                    or source_path.name == "viewsets.py"
                    or source_path.stem.endswith("_views")
                    or "views" in relative.parts[:-1]
                )
                if not is_view_module:
                    continue
                tree = ast.parse(source_path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        if any(alias.name == "security.authorization" for alias in node.names):
                            offenders.append(str(source_path.relative_to(backend_root)))
                    elif isinstance(node, ast.ImportFrom):
                        if node.module == "security.authorization":
                            offenders.append(str(source_path.relative_to(backend_root)))
                        elif node.module == "security" and any(
                            alias.name == "authorization" for alias in node.names
                        ):
                            offenders.append(str(source_path.relative_to(backend_root)))
        self.assertEqual(offenders, [])

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
