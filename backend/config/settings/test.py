from .base import *

DEBUG = False
SECRET_KEY = "test-only-key"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
