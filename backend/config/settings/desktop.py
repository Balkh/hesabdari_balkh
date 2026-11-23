"""Local Windows desktop settings profile.

The Tauri host must launch Django as the same interactive Windows user who
provisioned Credential Manager secrets, pass an absolute database path under
the app-data directory, and bind the server to loopback only. This profile is
not used by Production or by networked deployments.
"""
from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .base import *

if os.name != "nt":
    raise ImproperlyConfigured("config.settings.desktop is supported only on Windows")

from security.crypto import KeyUnavailableError
from security.windows_key_provider import WindowsCredentialManagerKeyProvider

try:
    SECRET_KEY = WindowsCredentialManagerKeyProvider().get_django_secret_key()
except KeyUnavailableError as exc:
    raise ImproperlyConfigured(
        "Windows desktop secrets are not provisioned for the current user; run provision_windows_desktop_secrets locally"
    ) from None

if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("Windows desktop Django signing secret is invalid")

DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
ERP_RBAC_ENFORCEMENT = True
ERP_RBAC_ALLOW_AUTHENTICATED_ONLY = False
ERP_MFA_KEY_PROVIDER = "security.windows_key_provider.WindowsCredentialManagerKeyProvider"

database_path = os.environ.get("HESABDARI_DESKTOP_DATABASE_PATH")
if not database_path:
    raise ImproperlyConfigured("HESABDARI_DESKTOP_DATABASE_PATH must point to the local app-data SQLite database")
database_file = Path(database_path).expanduser()
if not database_file.is_absolute():
    raise ImproperlyConfigured("HESABDARI_DESKTOP_DATABASE_PATH must be an absolute path")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(database_file),
        "OPTIONS": {"timeout": 20},
    }
}

# The local bridge must bind only to 127.0.0.1. Secure cookies are disabled
# only because the desktop bridge is loopback HTTP, not a public HTTP service.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"
SECURE_SSL_REDIRECT = False
X_FRAME_OPTIONS = "DENY"
