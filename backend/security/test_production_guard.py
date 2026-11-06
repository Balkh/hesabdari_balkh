import os
import subprocess
import sys
from pathlib import Path

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

    def test_production_settings_import_requires_explicit_true(self):
        backend_dir = Path(__file__).resolve().parents[1]
        base_env = os.environ.copy()
        base_env.update(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.production",
                "DJANGO_SECRET_KEY": "production-test-secret-" + ("x" * 64),
                "DJANGO_DEBUG": "false",
                "DJANGO_ALLOWED_HOSTS": "localhost",
                "POSTGRES_DB": "test_db",
                "POSTGRES_USER": "test_user",
                "POSTGRES_PASSWORD": "test_password",
                "POSTGRES_HOST": "127.0.0.1",
                "POSTGRES_PORT": "5432",
            }
        )
        script = (
            "import config.settings.production as settings; "
            "assert settings.ERP_RBAC_ENFORCEMENT is True; "
            "assert settings.ERP_RBAC_ALLOW_AUTHENTICATED_ONLY is False"
        )

        for value in (None, "false", "yes"):
            with self.subTest(value=value):
                env = base_env.copy()
                if value is None:
                    env.pop("ERP_RBAC_ENFORCEMENT", None)
                else:
                    env["ERP_RBAC_ENFORCEMENT"] = value
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    cwd=backend_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERP_RBAC_ENFORCEMENT", result.stderr)

        env = base_env.copy()
        env["ERP_RBAC_ENFORCEMENT"] = "true"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=backend_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_false_and_malformed_values_refuse_startup(self):
        for value in (None, "", "false", "FALSE", "0", "yes", "enabled", 1):
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError, "ERP_RBAC_ENFORCEMENT"):
                    require_rbac_enforcement_from_env(value)
