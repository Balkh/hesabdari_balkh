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
    """The complete V1 movement family (§10). No other types invented."""

    PURCHASE_RECEIPT = "PURCHASE_RECEIPT", "Purchase Receipt"
    SALES_ISSUE = "SALES_ISSUE", "Sales Issue"
    SALES_RETURN = "SALES_RETURN", "Sales Return"
    PURCHASE_RETURN = "PURCHASE_RETURN", "Purchase Return"
    TRANSFER_IN = "TRANSFER_IN", "Transfer In"
    TRANSFER_OUT = "TRANSFER_OUT", "Transfer Out"
    ADJUSTMENT_IN = "ADJUSTMENT_IN", "Adjustment In"
    ADJUSTMENT_OUT = "ADJUSTMENT_OUT", "Adjustment Out"
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
})

# Canonical COA identities (G2 stable codes, cf. accounting/coa.py).
INVENTORY_ROOT_CODE = "1400"
OPENING_EQUITY_ACCOUNT = "3900"
OPENING_SOURCE_TYPE = "OPENING_STOCK"
INVENTORY_MOVEMENT_OPERATION = "inventory.movement"


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
