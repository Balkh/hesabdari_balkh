from django.db import models


class NumberSequence(models.Model):
    """Backend-owned sequence state for document numbers."""
    document_type = models.CharField(max_length=12, unique=True)
    jalali_year = models.PositiveIntegerField()
    next_value = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.document_type}-{self.jalali_year}"
