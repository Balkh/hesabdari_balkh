from decimal import Decimal

from django.conf import settings
from django.db import models

from accounting.models import PostedImmutabilityError


class SalesChannel(models.TextChoices):
    WHOLESALE = "WHOLESALE", "Wholesale"
    RETAIL = "RETAIL", "Retail"


class PaymentMode(models.TextChoices):
    CASH = "CASH", "Cash"
    CREDIT = "CREDIT", "Credit"


class SaleType(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Available"
    FUTURE = "FUTURE", "Future"


class SaleStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    FINALIZED = "FINALIZED", "Finalized"


class CheckStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    FINALIZED = "FINALIZED", "Finalized"


class Sale(models.Model):
    document_number = models.CharField(max_length=30, unique=True)
    customer = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="sales")
    sale_date = models.DateField()
    currency = models.ForeignKey("currencies.Currency", on_delete=models.PROTECT, related_name="sales")
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=4)
    rate_date = models.DateField()
    sale_type = models.CharField(max_length=10, choices=SaleType.choices, default=SaleType.AVAILABLE)
    channel = models.CharField(max_length=10, choices=SalesChannel.choices)
    payment_mode = models.CharField(max_length=8, choices=PaymentMode.choices)
    subtotal = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    total_discount = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=10, choices=SaleStatus.choices, default=SaleStatus.DRAFT)
    journal_entry = models.ForeignKey("accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="sales")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="sales_created")
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sale_date", "document_number"]

    def save(self, *args, **kwargs):
        if self.pk is not None and Sale.objects.filter(pk=self.pk, status=SaleStatus.FINALIZED).exists():
            raise PostedImmutabilityError("Finalized sales are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk is not None and Sale.objects.filter(pk=self.pk, status=SaleStatus.FINALIZED).exists():
            raise PostedImmutabilityError("Finalized sales cannot be deleted")
        return super().delete(*args, **kwargs)


class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT, related_name="sale_lines")
    unit = models.ForeignKey("uom.UnitOfMeasure", on_delete=models.PROTECT, related_name="sale_lines")
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=20, decimal_places=4)
    discount = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=20, decimal_places=2)
    net_total = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        ordering = ["id"]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sale_line_qty_gt0")]

    def save(self, *args, **kwargs):
        if self.sale_id and Sale.objects.filter(pk=self.sale_id, status=SaleStatus.FINALIZED).exists():
            raise PostedImmutabilityError("Finalized sale lines are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.sale_id and Sale.objects.filter(pk=self.sale_id, status=SaleStatus.FINALIZED).exists():
            raise PostedImmutabilityError("Finalized sale lines cannot be deleted")
        return super().delete(*args, **kwargs)


class WarehouseCheck(models.Model):
    number = models.CharField(max_length=30, unique=True)
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="warehouse_checks")
    sale_line = models.ForeignKey(SaleLine, on_delete=models.PROTECT, related_name="warehouse_checks")
    warehouse = models.ForeignKey("warehouses.Warehouse", on_delete=models.PROTECT, related_name="warehouse_checks")
    quantity = models.IntegerField()
    status = models.CharField(max_length=10, choices=CheckStatus.choices, default=CheckStatus.DRAFT)
    stock_movement = models.ForeignKey("inventory.StockMovement", null=True, blank=True, on_delete=models.PROTECT, related_name="warehouse_checks")
    cogs_journal = models.ForeignKey("accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="warehouse_check_cogs")
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["number"]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="warehouse_check_qty_gt0")]

    def save(self, *args, **kwargs):
        if self.pk is not None and WarehouseCheck.objects.filter(pk=self.pk, status=CheckStatus.FINALIZED).exists():
            raise PostedImmutabilityError("Finalized Warehouse Checks are immutable")
        return super().save(*args, **kwargs)


class OwnershipEvent(models.Model):
    warehouse_check = models.OneToOneField(WarehouseCheck, on_delete=models.PROTECT, related_name="ownership_event")
    sale_line = models.ForeignKey(SaleLine, on_delete=models.PROTECT, related_name="ownership_events")
    customer = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="ownership_events")
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT, related_name="ownership_events")
    warehouse = models.ForeignKey("warehouses.Warehouse", on_delete=models.PROTECT, related_name="ownership_events")
    quantity = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


class NegativeCOGSObligation(models.Model):
    movement = models.OneToOneField("inventory.StockMovement", on_delete=models.PROTECT, related_name="negative_cogs_obligation")
    warehouse_check = models.OneToOneField(WarehouseCheck, on_delete=models.PROTECT, related_name="negative_cogs_obligation")
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT, related_name="negative_cogs_obligations")
    warehouse = models.ForeignKey("warehouses.Warehouse", on_delete=models.PROTECT, related_name="negative_cogs_obligations")
    original_quantity = models.PositiveIntegerField()
    resolved_quantity = models.PositiveIntegerField(default=0)
    temporary_unit_cost_afn = models.DecimalField(max_digits=20, decimal_places=4)
    movement_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["movement_date", "id"]


class COGSAdjustment(models.Model):
    obligation = models.ForeignKey(NegativeCOGSObligation, on_delete=models.PROTECT, related_name="adjustments")
    receipt_movement = models.ForeignKey("inventory.StockMovement", on_delete=models.PROTECT, related_name="cogs_adjustments")
    quantity = models.PositiveIntegerField()
    actual_unit_cost_afn = models.DecimalField(max_digits=20, decimal_places=4)
    temporary_unit_cost_afn = models.DecimalField(max_digits=20, decimal_places=4)
    difference = models.DecimalField(max_digits=20, decimal_places=2)
    journal_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, related_name="cogs_adjustment")
    created_at = models.DateTimeField(auto_now_add=True)
