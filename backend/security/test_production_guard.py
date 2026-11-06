from django.test import SimpleTestCase

from security.production_guard import require_rbac_enforcement_from_env


class ProductionRbacStartupGuardTests(SimpleTestCase):
    def test_only_explicit_true_enables_production_rbac(self):
        for value in ("true", "TRUE", " True "):
            with self.subTest(value=value):
                self.assertIs(
                    require_rbac_enforcement_from_env(value),
                    True,
                )

    def test_missing_false_and_malformed_values_refuse_startup(self):
        for value in (None, "", "false", "FALSE", "0", "yes", "enabled", 1):
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError, "ERP_RBAC_ENFORCEMENT"):
                    require_rbac_enforcement_from_env(value)
