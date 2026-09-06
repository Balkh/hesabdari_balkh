from .base import *
DEBUG = True
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-development-only-key")
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if host.strip()]
