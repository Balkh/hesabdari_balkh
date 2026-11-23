from .base import *
DEBUG = False
SECRET_KEY = "test-only-key"
ALLOWED_HOSTS = ["testserver", "localhost"]
ERP_TEST_ORIGINAL_DATABASE_NAMES = {"default": ":memory:"}
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:", "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 20}}}
