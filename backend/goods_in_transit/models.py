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
        allow_state_transition = kwargs.pop("allow_state_transition", False)
        if self.pk is not None and not allow_state_transition:
            raise PostedImmutabilityError("Goods in Transit lots are immutable")
        if self.pk is not None and allow_state_transition:
            update_fields = set(kwargs.get("update_fields") or ())
            if update_fields not in ({"remaining_quantity", "status"}, {"destination_warehouse"}):
                raise PostedImmutabilityError("Transit state may only change through an approved receipt/disposition event")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Goods in Transit lots cannot be deleted")


class TransitReceipt(models.Model):
    """Immutable physical arrival; company-owned and customer-owned portions are separated."""

    lot = models.ForeignKey(GoodsInTransitLot, on_delete=models.PROTECT, related_name="receipts")
    warehouse = models.ForeignKey("warehouses.Warehouse", on_delete=models.PROTECT, related_name="transit_receipts")
    quantity = models.PositiveIntegerField()
    company_quantity = models.PositiveIntegerField(default=0)
    customer_custody_quantity = models.PositiveIntegerField(default=0)
    receipt_date = models.DateField()
    stock_movement = models.OneToOneField("inventory.StockMovement", null=True, blank=True, on_delete=models.PROTECT, related_name="transit_receipt")
    journal_entry = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="transit_receipt")
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



class TransitCustomerCustody(models.Model):
    """Physical customer-owned goods received into a warehouse without company inventory valuation."""
    receipt = models.ForeignKey(TransitReceipt, on_delete=models.PROTECT, related_name="customer_custody_rows")
    sale_line = models.ForeignKey("sales.SaleLine", on_delete=models.PROTECT, related_name="transit_customer_custody")
    customer = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="transit_customer_custody")
    warehouse = models.ForeignKey("warehouses.Warehouse", on_delete=models.PROTECT, related_name="transit_customer_custody")
    quantity = models.PositiveIntegerField()
    receipt_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["receipt_date", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="transit_customer_custody_qty_gt0"),
            models.UniqueConstraint(fields=["receipt", "sale_line"], name="uniq_transit_receipt_sale_line_custody"),
        ]
    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Customer custody records are immutable")
        return super().save(*args, **kwargs)
    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Customer custody records cannot be deleted")


class TransitDestinationTransfer(models.Model):
    """Immutable reassignment of remaining owned Transit quantity to another destination warehouse."""
    lot = models.ForeignKey(GoodsInTransitLot, on_delete=models.PROTECT, related_name="destination_transfers")
    from_warehouse = models.ForeignKey("warehouses.Warehouse", on_delete=models.PROTECT, related_name="transit_destination_transfers_from")
    to_warehouse = models.ForeignKey("warehouses.Warehouse", on_delete=models.PROTECT, related_name="transit_destination_transfers_to")
    quantity = models.PositiveIntegerField()
    transfer_date = models.DateField()
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="transit_destination_transfers_created")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["transfer_date", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="transit_destination_transfer_qty_gt0")]
    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Transit destination transfers are immutable")
        return super().save(*args, **kwargs)
    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Transit destination transfers cannot be deleted")
