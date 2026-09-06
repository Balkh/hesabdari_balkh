from django.db import models


class IdempotencyRecord(models.Model):
    """Reusable request-level guard for critical future operations."""
    key = models.CharField(max_length=128, unique=True)
    operation = models.CharField(max_length=100)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
