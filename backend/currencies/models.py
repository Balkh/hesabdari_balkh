from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class Currency(models.Model):
    """Configurable currency master; transaction amounts belong to later domains."""

    code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=100)
    symbol = models.CharField(max_length=10, blank=True)
    decimal_places = models.PositiveSmallIntegerField(
        default=2,
        validators=[MinValueValidator(0), MaxValueValidator(6)],
    )
    is_base = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_base"],
                condition=models.Q(is_base=True),
                name="one_base_currency",
            )
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class ExchangeRate(models.Model):
    """Historical, directional rate: one unit of source equals X target units."""

    source_currency = models.ForeignKey(
        Currency, on_delete=models.PROTECT, related_name="rates_as_source"
    )
    target_currency = models.ForeignKey(
        Currency, on_delete=models.PROTECT, related_name="rates_as_target"
    )
    rate = models.DecimalField(max_digits=20, decimal_places=8)
    effective_date = models.DateField()
    source = models.CharField(max_length=20, default="MANUAL")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_date", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(rate__gt=0), name="positive_exchange_rate"),
            models.CheckConstraint(condition=~models.Q(source_currency=models.F("target_currency")), name="different_exchange_currencies"),
            models.UniqueConstraint(
                fields=["source_currency", "target_currency", "effective_date"],
                name="unique_rate_per_pair_date",
            ),
        ]

    def __str__(self):
        return f"1 {self.source_currency.code} = {self.rate} {self.target_currency.code}"
