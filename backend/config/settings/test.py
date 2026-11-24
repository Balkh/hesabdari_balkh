from .base import *
DEBUG = False
SECRET_KEY = "test-only-key"
ALLOWED_HOSTS = ["testserver", "localhost"]
ERP_TEST_ORIGINAL_DATABASE_NAMES = {"default": BASE_DIR / ".erp-test.sqlite3"}
# The test database must be FILE-BACKED (never ``:memory:``): the W0-2E
# encrypted-backup service correctly refuses to snapshot a ``:memory:``
# database (production guard), so the SQLite backup/restore integration
# tests can only exercise the real snapshot path against a file. Django
# switches ``NAME`` to ``TEST["NAME"]`` during test runs; without an
# explicit value it defaults SQLite to ``:memory:``.
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / ".erp-test.sqlite3", "TEST": {"NAME": BASE_DIR / ".erp-test-run.sqlite3"}, "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 20}}}
