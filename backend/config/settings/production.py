from .base import *

if SECRET_KEY == "development-only-insecure-key":
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production")
if DEBUG:
    raise RuntimeError("DJANGO_DEBUG must be false in production")
if not ALLOWED_HOSTS:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be set in production")

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
