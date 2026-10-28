import os

from .base import *

if SECRET_KEY == "development-only-insecure-key":
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production")
if len(SECRET_KEY) < 50:
    raise RuntimeError("DJANGO_SECRET_KEY must be at least 50 characters in production")
if DEBUG:
    raise RuntimeError("DJANGO_DEBUG must be false in production")
if not ALLOWED_HOSTS:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be set in production")
if "*" in ALLOWED_HOSTS:
    # A wildcard host entry accepts any spoofed Host header. Production
    # must pin explicit hostnames. base.py strips whitespace and drops
    # empty entries before this check, so a `*` is rejected wherever it
    # appears as a parsed entry, not merely when the whole input is `*`.
    raise RuntimeError(
        "DJANGO_ALLOWED_HOSTS must not contain the wildcard '*' in production"
    )

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

# collectstatic writes into this directory; a production web server or
# dedicated static-file service must serve its contents.
STATIC_ROOT = BASE_DIR / "staticfiles"

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
# HSTS includeSubDomains/preload stay DISABLED: the project has no
# documented public domain or subdomain architecture yet (ADR-0002 defers
# networked deployment). Preload is effectively irreversible once a
# domain is submitted, and includeSubDomains would hard-pin undocumented
# subdomains. Re-enable only with a documented deployment contract.
