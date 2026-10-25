import os
from django.core.wsgi import get_wsgi_application


# A server process must choose its settings profile explicitly. Unlike
# manage.py, WSGI startup must never silently fall back to development.
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    raise RuntimeError(
        "DJANGO_SETTINGS_MODULE must be set explicitly before WSGI startup"
    )

application = get_wsgi_application()
