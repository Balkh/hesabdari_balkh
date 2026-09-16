from django.db import models


class PeriodStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"
    LOCKED = "LOCKED", "Locked"


class FiscalPeriod(models.Model):
    """One fiscal period controlling when financial posting is allowed.

    Phase 3.1 (Phase 0 §12). Posting-date resolution is date-based: journals
    carry no period FK, so introducing periods never rewrites history and
    needs no backfill. Status transitions are owned by ``services.py``
    (atomic + audited); this model only guarantees deterministic validity.
    """

    name = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=12, choices=PeriodStatus.choices, default=PeriodStatus.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["start_date", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_date__lte=models.F("end_date")),
                name="fiscal_period_valid_range",
            ),
        ]
        indexes = [
            models.Index(fields=["start_date", "end_date"], name="fp_start_end_idx"),
        ]

    def __str__(self):
        return f"{self.name} [{self.start_date}..{self.end_date}] {self.status}"
