from django.test import SimpleTestCase, override_settings


class EnvironmentSettingsTests(SimpleTestCase):
    @override_settings(SECRET_KEY="test-only-key")
    def test_test_settings_are_non_debug_and_have_safe_test_key(self):
        from django.conf import settings
        self.assertFalse(settings.DEBUG)
        self.assertEqual(settings.SECRET_KEY, "test-only-key")
