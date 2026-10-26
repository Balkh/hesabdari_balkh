import os
from django.core.asgi import get_asgi_application


# A server process must choose its settings profile explicitly. Unlike
# manage.py, ASGI startup must never silently fall back to development.
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    raise RuntimeError(
        "DJANGO_SETTINGS_MODULE must be set explicitly before ASGI startup"
    )

application = get_asgi_application()
