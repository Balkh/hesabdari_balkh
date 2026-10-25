import os

from .base import *

if SECRET_KEY == "development-only-insecure-key":
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production")
if DEBUG:
    raise RuntimeError("DJANGO_DEBUG must be false in production")
if not ALLOWED_HOSTS:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be set in production")

# Production never runs on SQLite (ADR-0002: PostgreSQL integration is
# required before any networked/production deployment). Every connection
# value must be supplied explicitly so a missing variable fails fast.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.environ["POSTGRES_PORT"],
    }
}

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# Transport hardening for the networked/production deployment path
# (ADR-0002). This module only loads when DJANGO_SETTINGS_MODULE is
# explicitly set to config.settings.production; development, test and
# the SQLite/PostgreSQL verification profiles are unaffected.
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
