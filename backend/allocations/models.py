from decimal import Decimal

from django.conf import settings
from django.db import models

from accounting.models import PostedImmutabilityError


class CustomerAllocation(models.Model):
    """Immutable application of a customer Payment to one finalized credit Sale."""

    payment = models.ForeignKey("payments.Payment", on_delete=models.PROTECT, related_name="allocations")
    settlement = models.ForeignKey(
        "payments.CrossCurrencySettlement", null=True, blank=True,
        on_delete=models.PROTECT, related_name="allocations",
    )
    sale = models.ForeignKey("sales.Sale", on_delete=models.PROTECT, related_name="customer_allocations")
    currency = models.ForeignKey("currencies.Currency", on_delete=models.PROTECT, related_name="customer_allocations")
    requested_amount = models.DecimalField(max_digits=20, decimal_places=2)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    payment_amount = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    credit_amount = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT,
        related_name="allocation_adjustments",
    )
    idempotency_key = models.CharField(max_length=128, unique=True)
    allocated_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="customer_allocations_created")

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(requested_amount__gt=0), name="allocation_requested_gt0"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="allocation_amount_gt0"),
            models.CheckConstraint(condition=models.Q(payment_amount__gte=0), name="allocation_payment_amount_gte0"),
            models.CheckConstraint(condition=models.Q(credit_amount__gte=0), name="allocation_credit_gte0"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Customer allocations are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Customer allocations cannot be deleted")


class CustomerAllocationReversal(models.Model):
    """Immutable append-only reversal of one CustomerAllocation."""

    allocation = models.OneToOneField(CustomerAllocation, on_delete=models.PROTECT, related_name="reversal")
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT,
        related_name="allocation_reversals",
    )
    reason = models.CharField(max_length=500)
    reversed_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="customer_allocation_reversals_created")
    idempotency_key = models.CharField(max_length=128, unique=True)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Customer allocation reversals are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Customer allocation reversals cannot be deleted")
