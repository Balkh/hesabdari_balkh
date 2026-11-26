"""Common GM guard for local backup and checkpoint management commands."""

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError

from security.mfa_policy import is_active_gm_holder


def require_active_gm(username: str):
    if not isinstance(username, str) or not username.strip():
        raise CommandError("--actor-username is required")
    user_model = get_user_model()
    try:
        user = user_model._default_manager.get(
            **{user_model.USERNAME_FIELD: username.strip()}
        )
    except user_model.DoesNotExist:
        raise CommandError("the requested ERP account does not exist") from None
    if not is_active_gm_holder(user):
        raise CommandError("this local operation is restricted to the active singleton GM")
    return user
