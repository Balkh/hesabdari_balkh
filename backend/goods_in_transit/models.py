from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

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


class TransitLossValuationStatus(models.TextChoices):
    PENDING = "PENDING", "Pending purchase-wide valuation replay"
    POSTED = "POSTED", "Valuation replay posted"


class TransitLossEvent(models.Model):
    """Immutable evidence of confirmed loss from a purchase-wide transit lot."""
    lot = models.ForeignKey(
        GoodsInTransitLot, on_delete=models.PROTECT, related_name="loss_events"
    )
    quantity = models.PositiveIntegerField()
    loss_date = models.DateField()
    reason = models.TextField()
    idempotency_key = models.CharField(max_length=128, unique=True)
    # Valuation snapshot, written exactly once by the posting service in the
    # same transaction that posts the compensating journals. It freezes the
    # good-quantity denominator and final AFN unit cost so later landed-cost
    # postings can deterministically rebuild the loss layer.
    valuation_status = models.CharField(
        max_length=10, choices=TransitLossValuationStatus.choices,
        default=TransitLossValuationStatus.PENDING,
    )
    good_quantity = models.PositiveIntegerField(null=True, blank=True)
    final_unit_cost_afn = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )
    landed_pool_afn_at_valuation = models.DecimalField(
        max_digits=20, decimal_places=2, default=Decimal("0.00")
    )
    valuation_posted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="transit_loss_events_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["loss_date", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="transit_loss_qty_gt0"
            ),
        ]

    # Fields the valuation posting service may write exactly once.
    VALUATION_UPDATE_FIELDS = frozenset({
        "valuation_status", "good_quantity", "final_unit_cost_afn",
        "landed_pool_afn_at_valuation", "valuation_posted_at",
    })

    def save(self, *args, **kwargs):
        if self.pk is not None:
            update_fields = set(kwargs.get("update_fields") or ())
            if update_fields and update_fields <= self.VALUATION_UPDATE_FIELDS:
                current = type(self).objects.filter(pk=self.pk).values_list(
                    "valuation_status", flat=True
                ).first()
                if current == TransitLossValuationStatus.POSTED:
                    raise PostedImmutabilityError(
                        "A posted transit loss valuation cannot be rewritten"
                    )
                return super().save(*args, **kwargs)
            raise PostedImmutabilityError("Transit loss events are immutable")
        # Serialize aggregate validation on the source lot so direct model
        # creation cannot bypass the service's cumulative quantity guard.
        with transaction.atomic():
            lot = GoodsInTransitLot.objects.select_for_update().get(pk=self.lot_id)
            if self.loss_date < lot.ownership_date:
                raise ValidationError("Transit loss date cannot precede company ownership.")
            already_reported = sum(
                type(self).objects.filter(lot_id=lot.pk).values_list("quantity", flat=True)
            )
            if self.quantity <= 0 or already_reported + self.quantity >= lot.original_quantity:
                raise ValidationError(
                    "Cumulative transit loss must leave at least one good unit in the purchase line."
                )
            if already_reported:
                raise ValidationError(
                    "A transit lot can have only one final reconciled loss event."
                )
            if self.quantity != lot.remaining_quantity:
                raise ValidationError(
                    "Transit loss can be recorded only after all other owned goods are accounted for; "
                    "loss quantity must equal the lot's remaining transit quantity."
                )
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Transit loss events cannot be deleted")


class TransitLossValuationAdjustmentQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PostedImmutabilityError("Transit loss valuation adjustments are immutable")

    def bulk_update(self, objs, fields, batch_size=None):
        raise PostedImmutabilityError("Transit loss valuation adjustments are immutable")

    def bulk_create(self, objs, **kwargs):
        raise PostedImmutabilityError(
            "Create transit loss valuation adjustments only through the posting service"
        )

    def delete(self):
        raise PostedImmutabilityError("Transit loss valuation adjustments cannot be deleted")


class TransitLossValuationAdjustment(models.Model):
    """Immutable compensating reallocation posted for a confirmed transit loss.

    This is the durable anchor for loss valuation journals: the existing
    ``LandedCostValuationAdjustment`` requires a ``LandedCostDocument``
    parent, which a transit loss does not have. One row per posted
    compensating journal, traceable to the loss event and stock movement.
    """

    loss_event = models.ForeignKey(
        TransitLossEvent, on_delete=models.PROTECT,
        related_name="valuation_adjustments",
    )
    source_reference = models.CharField(max_length=200)
    adjustment_type = models.CharField(max_length=40)
    movement = models.ForeignKey(
        "inventory.StockMovement", null=True, blank=True,
        on_delete=models.PROTECT, related_name="transit_loss_valuation_adjustments",
    )
    amount_afn = models.DecimalField(max_digits=20, decimal_places=2)
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry", on_delete=models.PROTECT,
        related_name="transit_loss_valuation_adjustment",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TransitLossValuationAdjustmentQuerySet.as_manager()

    class Meta:
        ordering = ["loss_event_id", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_afn__gt=0),
                name="transit_loss_adjustment_afn_gt0",
            ),
            models.UniqueConstraint(
                fields=["loss_event", "source_reference", "adjustment_type"],
                name="uniq_transit_loss_valuation_adj_ref",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Transit loss valuation adjustments are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Transit loss valuation adjustments cannot be deleted")


def has_unvalued_transit_loss(lot_id):
    """True while a lot carries a loss whose valuation replay is not posted."""
    return TransitLossEvent.objects.filter(
        lot_id=lot_id,
    ).exclude(
        valuation_status=TransitLossValuationStatus.POSTED,
    ).exists()
