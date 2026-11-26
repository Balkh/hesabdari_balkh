"""Django authentication signal receivers for W0-2D lockout evidence."""
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver

from security.login_lockout import find_user_for_login, record_password_failure


@receiver(user_login_failed, dispatch_uid="security.w0_2d.record_failed_password_auth")
def record_failed_password_auth(sender, credentials, request, **kwargs):
    """Capture failed ModelBackend/DRF BasicAuthentication attempts without secrets."""
    User = get_user_model()
    username = credentials.get(User.USERNAME_FIELD)
    if username is None and User.USERNAME_FIELD != "username":
        username = credentials.get("username")
    user = find_user_for_login(username)
    # Never log or persist the raw credentials.
    record_password_failure(user, username, request)
