"""Inventory foundation models (Phase 6.1 — movement truth + warehouse mapping).

Design record (approved Phase 6 rules, Stage 6.1 scope):

- ONE movement table + explicit type (ID-6-03). The full V1 family of 9
  types exists as choices, but Stage 6.1 services only post OPENING,
  PURCHASE_RECEIPT, and SALES_ISSUE; the rest are future stages.
- Signed integer quantity: IN types > 0, OUT types < 0, never 0 (V1
  integer rule §5). Stock = SUM(quantity) per (Product, Warehouse).
- Every movement carries full cost context: transaction currency,
  per-unit cost in that currency (4dp), historical rate snapshot (4dp),
  and per-unit AFN cost (4dp). Issues at AVCO store AFN currency +
  rate 1; temporary-cost issues store the manually entered context.
- Posted movements are immutable (mirror ``PartyLedgerAttribution``):
  updates and deletes raise the reused ``PostedImmutabilityError``.
- Quantity is recorded in the product's PRIMARY UOM in Stage 6.1;
  secondary-UOM conversion at transaction time is a later-stage concern.
- The Warehouse → Inventory GL mapping lives HERE (never on Warehouse:
  warehouses/models.py §10 forbids the reverse reference). The mapping
  is configuration (remappable; history keeps its posted accounts), not
  truth. Mapped accounts must be posting/active descendants of 1400.
"""

from django.db import models

from accounting.models import PostedImmutabilityError


class MovementType(models.TextChoices):
    """V1 movement family (§10, + SHORTAGE in Stage 6.4)."""

    PURCHASE_RECEIPT = "PURCHASE_RECEIPT", "Purchase Receipt"
    SALES_ISSUE = "SALES_ISSUE", "Sales Issue"
    SALES_RETURN = "SALES_RETURN", "Sales Return"
    PURCHASE_RETURN = "PURCHASE_RETURN", "Purchase Return"
    TRANSFER_IN = "TRANSFER_IN", "Transfer In"
    TRANSFER_OUT = "TRANSFER_OUT", "Transfer Out"
    ADJUSTMENT_IN = "ADJUSTMENT_IN", "Adjustment In"
    ADJUSTMENT_OUT = "ADJUSTMENT_OUT", "Adjustment Out"
    SHORTAGE = "SHORTAGE", "Shortage"
    OPENING = "OPENING", "Opening"


# THE authoritative direction mapping. Import this; do not duplicate it
# in services, derivation, or tests.
IN_MOVEMENT_TYPES = frozenset({
    MovementType.PURCHASE_RECEIPT,
    MovementType.SALES_RETURN,
    MovementType.TRANSFER_IN,
    MovementType.ADJUSTMENT_IN,
    MovementType.OPENING,
})
OUT_MOVEMENT_TYPES = frozenset({
    MovementType.SALES_ISSUE,
    MovementType.PURCHASE_RETURN,
    MovementType.TRANSFER_OUT,
    MovementType.ADJUSTMENT_OUT,
    MovementType.SHORTAGE,
})

# Canonical COA identities (G2 stable codes, cf. accounting/coa.py).
INVENTORY_ROOT_CODE = "1400"
OPENING_EQUITY_ACCOUNT = "3900"
OPENING_SOURCE_TYPE = "OPENING_STOCK"
INVENTORY_MOVEMENT_OPERATION = "inventory.movement"
TRANSFER_SOURCE_TYPE = "TRANSFER"
INVENTORY_TRANSFER_OPERATION = "inventory.transfer"
SHORTAGE_SETTLEMENT_OPERATION = "inventory.shortage_settlement"
PURCHASE_RETURN_OPERATION = "inventory.purchase_return"
SALES_RETURN_OPERATION = "inventory.sales_return"


class StockMovement(models.Model):
    """One immutable posted inventory movement (§8/§9).

    ``quantity`` is signed (IN positive, OUT negative). ``qty_before``
    and ``qty_after`` are the derived stock snapshots computed inside
    the posting transaction (§11). ``journal_entry`` is set only when
    the movement posts together with a journal (Stage 6.1: opening).
    """

    movement_type = models.CharField(
        max_length=20, choices=MovementType.choices
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    warehouse = models.ForeignKey(
        "warehouses.Warehouse",
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    quantity = models.IntegerField()
    movement_date = models.DateField()
    currency = models.ForeignKey(
        "currencies.Currency",
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    unit_cost = models.DecimalField(max_digits=20, decimal_places=4)
    rate = models.DecimalField(max_digits=20, decimal_places=4)
    rate_date = models.DateField()
    unit_cost_afn = models.DecimalField(max_digits=20, decimal_places=4)
    is_temporary_cost = models.BooleanField(default=False)
    qty_before = models.IntegerField()
    qty_after = models.IntegerField()
    reference = models.CharField(max_length=200)
    description = models.CharField(max_length=500, blank=True, default="")
    source_party = models.ForeignKey(
        "parties.Party", null=True, blank=True, on_delete=models.PROTECT,
        related_name="source_stock_movements",
    )
    gross_quantity = models.IntegerField(null=True, blank=True)
    waste_quantity = models.IntegerField(null=True, blank=True)
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    idempotency_key = models.CharField(
        max_length=128, unique=True, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["movement_date", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(quantity__gt=0)
                    | models.Q(quantity__lt=0)
                ),
                name="inv_movement_qty_nonzero",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(movement_type__in=IN_MOVEMENT_TYPES)
                        & models.Q(quantity__gt=0)
                    )
                    | (
                        models.Q(movement_type__in=OUT_MOVEMENT_TYPES)
                        & models.Q(quantity__lt=0)
                    )
                ),
                name="inv_movement_direction",
            ),
            models.CheckConstraint(
                condition=~models.Q(reference=""),
                name="inv_movement_reference_nonblank",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_cost__gte=0),
                name="inv_movement_unit_cost_gte0",
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gt=0),
                name="inv_movement_rate_gt0",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError(
                "Posted inventory movements are immutable; correct "
                "through a compensating movement"
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError(
            "Posted inventory movements cannot be deleted; correct "
            "through a compensating movement"
        )

    def __str__(self):
        return (
            f"{self.movement_type} {self.quantity} "
            f"(product={self.product_id}, warehouse={self.warehouse_id})"
        )


class WarehouseInventoryAccount(models.Model):
    """Explicit Warehouse → Inventory GL account mapping (§19).

    Configuration, not truth: remapping changes only FUTURE postings;
    posted journals keep their accounts. The mapped account must be a
    posting/active descendant of 1400 (validated in services).
    """

    warehouse = models.OneToOneField(
        "warehouses.Warehouse",
        on_delete=models.PROTECT,
        related_name="inventory_account",
    )
    account = models.ForeignKey(
        "accounting.Account",
        on_delete=models.PROTECT,
        related_name="warehouse_inventory_links",
    )

    class Meta:
        ordering = ["warehouse_id"]

    def __str__(self):
        return f"warehouse={self.warehouse_id} -> {self.account.code}"


class ShortageSettlement(models.Model):
    """One immutable shortage-compensation record (Stage 6.4).

    The manually entered actual-sales-rate settlement for one SHORTAGE
    leg. A separate row (not columns on the movement) because settlement
    postdates the immutable event. Never stock truth (no quantity here —
    compensation quantity derives from the linked shortage leg) and never
    a valuation rewrite. One settlement per shortage.
    """

    shortage = models.OneToOneField(
        StockMovement,
        on_delete=models.PROTECT,
        related_name="settlement",
    )
    settlement_date = models.DateField()
    unit_rate = models.DecimalField(max_digits=20, decimal_places=4)
    currency = models.ForeignKey(
        "currencies.Currency",
        on_delete=models.PROTECT,
        related_name="shortage_settlements",
    )
    rate = models.DecimalField(max_digits=20, decimal_places=4)
    rate_date = models.DateField()
    compensation_amount = models.DecimalField(max_digits=20, decimal_places=4)
    reference = models.CharField(max_length=200)
    idempotency_key = models.CharField(
        max_length=128, unique=True, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["settlement_date", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(unit_rate__gte=0),
                name="inv_settle_rate_gte0",
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gt=0),
                name="inv_settle_rate_gt0",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError(
                "Posted shortage settlements are immutable"
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError(
            "Posted shortage settlements cannot be deleted"
        )

    def __str__(self):
        return f"settlement for shortage={self.shortage_id}"


class InventoryReturnType(models.TextChoices):
    PURCHASE = "PURCHASE_RETURN", "Purchase Return"
    SALES = "SALES_RETURN", "Sales Return"


class InventoryReturn(models.Model):
    """Immutable return business record linked to one source movement.

    This is traceability/business identity only; StockMovement remains the
    canonical stock truth. Purchase/Sales invoice models are not present in
    this repository, so the source invoice/receipt identity is the immutable
    source movement reference supplied by the future document domain.
    """

    return_type = models.CharField(max_length=20, choices=InventoryReturnType.choices)
    source_movement = models.ForeignKey(
        StockMovement, on_delete=models.PROTECT, related_name="returns"
    )
    return_movement = models.OneToOneField(
        StockMovement, on_delete=models.PROTECT, related_name="return_record"
    )
    party = models.ForeignKey(
        "parties.Party", on_delete=models.PROTECT, related_name="inventory_returns"
    )
    product = models.ForeignKey(
        "products.Product", on_delete=models.PROTECT, related_name="inventory_returns"
    )
    warehouse = models.ForeignKey(
        "warehouses.Warehouse", on_delete=models.PROTECT, related_name="inventory_returns"
    )
    source_document = models.CharField(max_length=200)
    quantity = models.IntegerField()
    description = models.CharField(max_length=500)
    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="inv_return_qty_gt0"),
            models.CheckConstraint(condition=~models.Q(source_document=""), name="inv_return_source_nonblank"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Posted inventory returns are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Posted inventory returns cannot be deleted")
