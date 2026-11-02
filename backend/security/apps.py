from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "security"

    def ready(self):
        # Register the W0-2A catalog drift check (§15.1). The import is
        # intentionally inside ready(): the check module reads models at
        # call time, not import time.
        from security import checks  # noqa: F401
