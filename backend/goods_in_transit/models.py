from decimal import Decimal

from django.conf import settings
from django.db import models

from accounting.models import JournalEntry, PostedImmutabilityError


class TransitLotStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"
    REVERSED = "REVERSED", "Reversed"


class GoodsInTransitLot(models.Model):
    """Immutable ownership lot for goods owned before physical receipt.

    Physical Warehouse stock remains authoritative in inventory.StockMovement.
    This model represents only company-owned quantity that is outside physical
    Warehouse stock, plus its source PurchaseLine and cost basis.
    """

    purchase = models.ForeignKey("purchases.Purchase", on_delete=models.PROTECT, related_name="transit_lots")
    purchase_line = models.OneToOneField("purchases.PurchaseLine", on_delete=models.PROTECT, related_name="transit_lot")
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT, related_name="goods_in_transit_lots")
    supplier = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="goods_in_transit_lots")
    destination_warehouse = models.ForeignKey("warehouses.Warehouse", on_delete=models.PROTECT, related_name="goods_in_transit_lots")
    currency = models.ForeignKey("currencies.Currency", on_delete=models.PROTECT, related_name="goods_in_transit_lots")
    original_quantity = models.PositiveIntegerField()
    remaining_quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=20, decimal_places=4)
    rate = models.DecimalField(max_digits=20, decimal_places=4)
    rate_date = models.DateField()
    ownership_date = models.DateField()
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, related_name="goods_in_transit_lot")
    status = models.CharField(max_length=10, choices=TransitLotStatus.choices, default=TransitLotStatus.OPEN)
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="goods_in_transit_lots_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ownership_date", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(original_quantity__gt=0), name="transit_lot_original_gt0"),
            models.CheckConstraint(condition=models.Q(remaining_quantity__lte=models.F("original_quantity")), name="transit_lot_remaining_lte_original"),
            models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="transit_lot_cost_gte0"),
            models.CheckConstraint(condition=models.Q(rate__gt=0), name="transit_lot_rate_gt0"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Goods in Transit lots are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Goods in Transit lots cannot be deleted")


class TransitReceipt(models.Model):
    """Immutable transfer of owned Transit quantity into a real Warehouse."""

    lot = models.ForeignKey(GoodsInTransitLot, on_delete=models.PROTECT, related_name="receipts")
    warehouse = models.ForeignKey("warehouses.Warehouse", on_delete=models.PROTECT, related_name="transit_receipts")
    quantity = models.PositiveIntegerField()
    receipt_date = models.DateField()
    stock_movement = models.OneToOneField("inventory.StockMovement", on_delete=models.PROTECT, related_name="transit_receipt")
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, related_name="transit_receipt")
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="transit_receipts_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["receipt_date", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="transit_receipt_qty_gt0")]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Transit receipts are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Transit receipts cannot be deleted")
