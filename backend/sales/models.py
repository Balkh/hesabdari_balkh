from decimal import Decimal

from django.conf import settings
from django.db import models

from accounting.models import PostedImmutabilityError


class SaleType(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Available"
    FUTURE = "FUTURE", "Future"


class SaleStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    FINALIZED = "FINALIZED", "Finalized"


class SaleQuerySet(models.QuerySet):
    def _contains_finalized(self):
        return self.filter(status=SaleStatus.FINALIZED).exists()

    def update(self, **kwargs):
        if self._contains_finalized() or "status" in kwargs:
            raise PostedImmutabilityError(
                "Finalized sales cannot be changed through bulk ORM updates"
            )
        return super().update(**kwargs)

    def delete(self):
        if self._contains_finalized():
            raise PostedImmutabilityError("Finalized sales cannot be deleted")
        return super().delete()


class SaleLineQuerySet(models.QuerySet):
    def _contains_finalized_parent(self):
        return self.filter(sale__status=SaleStatus.FINALIZED).exists()

    def _targets_finalized_parent(self, kwargs):
        target = kwargs.get("sale_id", kwargs.get("sale"))
        if target is None:
            return False
        target_id = getattr(target, "pk", target)
        return Sale.objects.filter(pk=target_id, status=SaleStatus.FINALIZED).exists()

    def update(self, **kwargs):
        if self._contains_finalized_parent() or self._targets_finalized_parent(kwargs):
            raise PostedImmutabilityError(
                "Lines belonging to finalized sales cannot be changed through bulk ORM updates"
            )
        return super().update(**kwargs)

    def delete(self):
        if self._contains_finalized_parent():
            raise PostedImmutabilityError("Lines belonging to finalized sales cannot be deleted")
        return super().delete()


class Sale(models.Model):
    document_number = models.CharField(max_length=30, unique=True)
    customer = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="sales")
    sale_date = models.DateField()
    currency = models.ForeignKey("currencies.Currency", on_delete=models.PROTECT, related_name="sales")
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=4)
    rate_date = models.DateField()
    sale_type = models.CharField(max_length=10, choices=SaleType.choices)
    subtotal = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    total_discount = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=10, choices=SaleStatus.choices, default=SaleStatus.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="sales_created")
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SaleQuerySet.as_manager()

    class Meta:
        ordering = ["sale_date", "document_number"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            previous = Sale.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if previous == SaleStatus.FINALIZED:
                raise PostedImmutabilityError("Finalized sales are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk is not None and Sale.objects.filter(pk=self.pk, status=SaleStatus.FINALIZED).exists():
            raise PostedImmutabilityError("Finalized sales cannot be deleted")
        return super().delete(*args, **kwargs)


class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT, related_name="sale_lines")
    warehouse = models.ForeignKey("warehouses.Warehouse", on_delete=models.PROTECT, related_name="sale_lines")
    unit = models.ForeignKey("uom.UnitOfMeasure", on_delete=models.PROTECT, related_name="sale_lines")
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=20, decimal_places=4)
    discount = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=20, decimal_places=2)
    net_total = models.DecimalField(max_digits=20, decimal_places=2)

    objects = SaleLineQuerySet.as_manager()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sale_line_qty_gt0"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="sale_line_price_gte0"),
            models.CheckConstraint(condition=models.Q(discount__gte=0), name="sale_line_discount_gte0"),
            models.CheckConstraint(condition=models.Q(line_total__gte=0), name="sale_line_total_gte0"),
            models.CheckConstraint(condition=models.Q(net_total__gte=0), name="sale_line_net_gte0"),
        ]

    def save(self, *args, **kwargs):
        if self.sale_id is not None:
            status = Sale.objects.filter(pk=self.sale_id).values_list("status", flat=True).first()
            if status == SaleStatus.FINALIZED:
                raise PostedImmutabilityError("Finalized sale lines are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.sale_id and Sale.objects.filter(pk=self.sale_id, status=SaleStatus.FINALIZED).exists():
            raise PostedImmutabilityError("Finalized sale lines cannot be deleted")
        return super().delete(*args, **kwargs)
