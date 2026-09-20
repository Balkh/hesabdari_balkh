from decimal import Decimal

from django.conf import settings
from django.db import models

from accounting.models import PostedImmutabilityError


class PurchaseStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    POSTED = "POSTED", "Posted"


class PurchaseQuerySet(models.QuerySet):
    def _contains_posted(self):
        return self.filter(status=PurchaseStatus.POSTED).exists()

    def update(self, **kwargs):
        if self._contains_posted() or "status" in kwargs:
            raise PostedImmutabilityError(
                "Posted purchases cannot be changed through bulk ORM updates"
            )
        return super().update(**kwargs)

    def delete(self):
        if self._contains_posted():
            raise PostedImmutabilityError(
                "Posted purchases cannot be deleted through bulk ORM deletion"
            )
        return super().delete()


class PurchaseLineQuerySet(models.QuerySet):
    def _contains_posted_parent(self):
        return self.filter(purchase__status=PurchaseStatus.POSTED).exists()

    def _targets_posted_parent(self, kwargs):
        target = kwargs.get("purchase_id", kwargs.get("purchase"))
        if target is None:
            return False
        target_id = getattr(target, "pk", target)
        return Purchase.objects.filter(
            pk=target_id, status=PurchaseStatus.POSTED
        ).exists()

    def update(self, **kwargs):
        if self._contains_posted_parent() or self._targets_posted_parent(kwargs):
            raise PostedImmutabilityError(
                "Lines belonging to posted purchases cannot be changed "
                "through bulk ORM updates"
            )
        return super().update(**kwargs)

    def delete(self):
        if self._contains_posted_parent():
            raise PostedImmutabilityError(
                "Lines belonging to posted purchases cannot be deleted "
                "through bulk ORM deletion"
            )
        return super().delete()


class Purchase(models.Model):
    document_number = models.CharField(max_length=30, unique=True)
    supplier = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="purchases")
    purchase_date = models.DateField()
    currency = models.ForeignKey("currencies.Currency", on_delete=models.PROTECT, related_name="purchases")
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=4)
    rate_date = models.DateField()
    warehouse = models.ForeignKey("warehouses.Warehouse", on_delete=models.PROTECT, related_name="purchases")
    description = models.CharField(max_length=500, blank=True, default="")
    subtotal = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    discount = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    freight = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=10, choices=PurchaseStatus.choices, default=PurchaseStatus.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchases_created")
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PurchaseQuerySet.as_manager()

    class Meta:
        ordering = ["purchase_date", "document_number"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            previous = Purchase.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if previous == PurchaseStatus.POSTED:
                raise PostedImmutabilityError("Posted purchases are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk is not None and Purchase.objects.filter(pk=self.pk, status=PurchaseStatus.POSTED).exists():
            raise PostedImmutabilityError("Posted purchases cannot be deleted")
        return super().delete(*args, **kwargs)


class PurchaseLine(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT, related_name="purchase_lines")
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=20, decimal_places=4)
    line_total = models.DecimalField(max_digits=20, decimal_places=2)
    discount_allocated = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    net_total = models.DecimalField(max_digits=20, decimal_places=2)

    objects = PurchaseLineQuerySet.as_manager()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="purchase_line_qty_gt0"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="purchase_line_price_gte0"),
            models.CheckConstraint(condition=models.Q(line_total__gte=0), name="purchase_line_total_gte0"),
            models.CheckConstraint(condition=models.Q(discount_allocated__gte=0), name="purchase_line_discount_gte0"),
            models.CheckConstraint(condition=models.Q(net_total__gte=0), name="purchase_line_net_gte0"),
        ]

    def save(self, *args, **kwargs):
        if self.purchase_id is not None:
            status = Purchase.objects.filter(pk=self.purchase_id).values_list("status", flat=True).first()
            if status == PurchaseStatus.POSTED:
                raise PostedImmutabilityError("Posted purchase lines are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.purchase_id and Purchase.objects.filter(pk=self.purchase_id, status=PurchaseStatus.POSTED).exists():
            raise PostedImmutabilityError("Posted purchase lines cannot be deleted")
        return super().delete(*args, **kwargs)
