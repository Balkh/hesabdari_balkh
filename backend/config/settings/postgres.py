"""PostgreSQL verification settings.

Used to execute the full foundation test suite against a real PostgreSQL
server. Values come from the same POSTGRES_* variables documented in
``.env.example``; the defaults match that file so a local/CI server created
with those values works without extra export lines.

This module is a development/CI verification profile only. Production must
use ``config.settings.production``, which never falls back to SQLite.
"""
import os

from .base import *

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "erp_afghanistan"),
        "USER": os.getenv("POSTGRES_USER", "erp_afghanistan"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "replace-me"),
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}
