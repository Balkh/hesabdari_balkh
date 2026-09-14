"""Product master identity (Phase 4.1).

Master identity/configuration ONLY, per contract §4.1 + §4.2 and the
interpretation record (R-2..R-8, U-4): unique user-assigned code, bilingual
names, category, primary/secondary UOM with a STORED (never applied)
conversion factor, optional barcode/brand, reference prices (suggestions,
never transactions), stored stock thresholds (no behavior), active flag.

No stock, no valuation, no AVCO/COGS, no movements, no postings.
"""

from decimal import Decimal

from django.db import models


class Product(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=200)
    name_fa = models.CharField(max_length=200)
    category = models.ForeignKey(
        "categories.Category", on_delete=models.PROTECT, related_name="products"
    )
    primary_uom = models.ForeignKey(
        "uom.UnitOfMeasure", on_delete=models.PROTECT, related_name="primary_products"
    )
    secondary_uom = models.ForeignKey(
        "uom.UnitOfMeasure", on_delete=models.PROTECT, null=True, blank=True,
        related_name="secondary_products",
    )
    conversion_factor = models.DecimalField(
        max_digits=20, decimal_places=4, default=Decimal("1")
    )
    barcode = models.CharField(max_length=100, blank=True, default="")
    brand = models.CharField(max_length=200, blank=True, default="")
    ref_purchase_price = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )
    ref_sales_price = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )
    min_stock = models.DecimalField(
        max_digits=20, decimal_places=3, default=Decimal("0")
    )
    max_stock = models.DecimalField(
        max_digits=20, decimal_places=3, null=True, blank=True
    )
    reorder_point = models.DecimalField(
        max_digits=20, decimal_places=3, null=True, blank=True
    )
    is_active = models.BooleanField(default=True)
    description = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(code=""), name="prod_code_nonblank"
            ),
            models.CheckConstraint(
                condition=~models.Q(name=""), name="prod_name_nonblank"
            ),
            models.CheckConstraint(
                condition=~models.Q(name_fa=""), name="prod_namefa_nonblank"
            ),
            models.CheckConstraint(
                condition=models.Q(conversion_factor__gt=0),
                name="prod_factor_gt0",
            ),
            models.CheckConstraint(
                condition=models.Q(min_stock__gte=0), name="prod_min_gte0"
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"
