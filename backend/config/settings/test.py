from .base import *
DEBUG = False
SECRET_KEY = "test-only-key"
ALLOWED_HOSTS = ["testserver", "localhost"]
ERP_TEST_ORIGINAL_DATABASE_NAMES = {"default": BASE_DIR / ".erp-test.sqlite3"}
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / ".erp-test.sqlite3", "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 20}}}
