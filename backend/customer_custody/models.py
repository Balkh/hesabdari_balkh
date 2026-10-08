from django.conf import settings
from django.db import models

from accounting.models import PostedImmutabilityError


class OwnershipStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    REVERSED = "REVERSED", "Reversed"


class CustodyEventType(models.TextChoices):
    PLACED = "PLACED", "Placed into Customer Custody"
    RELEASED = "RELEASED", "Released from Customer Custody"
    RELEASE_REVERSAL = "RELEASE_REVERSAL", "Release Reversal"
    PLACEMENT_REVERSAL = "PLACEMENT_REVERSAL", "Placement Reversal"


class CustomerOwnershipEntitlement(models.Model):
    """Immutable commercial ownership acquired by a customer at Sale finalization.

    This is deliberately independent from physical Inventory and Warehouse
    location. A finalized Sale creates exactly one entitlement per SaleLine.
    """
    sale_line = models.OneToOneField(
        "sales.SaleLine", on_delete=models.PROTECT,
        related_name="customer_ownership_entitlement",
    )
    customer = models.ForeignKey(
        "parties.Party", on_delete=models.PROTECT,
        related_name="customer_ownership_entitlements",
    )
    product = models.ForeignKey(
        "products.Product", on_delete=models.PROTECT,
        related_name="customer_ownership_entitlements",
    )
    quantity = models.PositiveIntegerField()
    ownership_date = models.DateField()
    status = models.CharField(
        max_length=10, choices=OwnershipStatus.choices,
        default=OwnershipStatus.ACTIVE,
    )
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="customer_ownership_entitlements_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ownership_date", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="custody_ownership_qty_gt0",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError(
                "Customer ownership entitlements are immutable; correct through a compensating event"
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError(
            "Customer ownership entitlements cannot be deleted"
        )


class CustomerCustodyEvent(models.Model):
    """Immutable custody ledger event; never a replacement for StockMovement."""
    entitlement = models.ForeignKey(
        CustomerOwnershipEntitlement, on_delete=models.PROTECT,
        related_name="custody_events",
    )
    customer = models.ForeignKey(
        "parties.Party", on_delete=models.PROTECT,
        related_name="customer_custody_events",
    )
    product = models.ForeignKey(
        "products.Product", on_delete=models.PROTECT,
        related_name="customer_custody_events",
    )
    warehouse = models.ForeignKey(
        "warehouses.Warehouse", on_delete=models.PROTECT,
        related_name="customer_custody_events",
    )
    event_type = models.CharField(max_length=20, choices=CustodyEventType.choices)
    quantity = models.PositiveIntegerField()
    event_date = models.DateField()
    reference = models.CharField(max_length=200)
    idempotency_key = models.CharField(max_length=128, unique=True)
    reversal_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="reversal_events",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="customer_custody_events_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["event_date", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="custody_event_qty_gt0",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError(
                "Customer custody events are immutable; correct through a compensating event"
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Customer custody events cannot be deleted")
