from django.conf import settings
from django.db import models


class AuditAction(models.TextChoices):
    LOGIN = "LOGIN", "Login"
    LOGOUT = "LOGOUT", "Logout"
    CREATE = "CREATE", "Create"
    UPDATE = "UPDATE", "Update"
    POST = "POST", "Post"
    REVERSE = "REVERSE", "Reverse"
    APPROVE = "APPROVE", "Approve"


class AuditEvent(models.Model):
    """Immutable audit foundation for future financial operations."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=20, choices=AuditAction.choices)
    entity = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=100, blank=True)
    reference = models.CharField(max_length=200, blank=True)
    previous_state = models.JSONField(null=True, blank=True)
    new_state = models.JSONField(null=True, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
