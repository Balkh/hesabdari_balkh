from decimal import Decimal

from django.conf import settings
from django.db import models

from accounting.models import PostedImmutabilityError


class PurchaseStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    POSTED = "POSTED", "Posted"


class PurchaseDeliveryMode(models.TextChoices):
    IMMEDIATE = "IMMEDIATE", "Immediate warehouse receipt"
    IN_TRANSIT = "IN_TRANSIT", "Owned in transit"


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
    delivery_mode = models.CharField(max_length=12, choices=PurchaseDeliveryMode.choices, default=PurchaseDeliveryMode.IMMEDIATE)
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
    measured_weight_kg = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    freight_allocated = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))

    objects = PurchaseLineQuerySet.as_manager()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="purchase_line_qty_gt0"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="purchase_line_price_gte0"),
            models.CheckConstraint(condition=models.Q(line_total__gte=0), name="purchase_line_total_gte0"),
            models.CheckConstraint(condition=models.Q(discount_allocated__gte=0), name="purchase_line_discount_gte0"),
            models.CheckConstraint(condition=models.Q(net_total__gte=0), name="purchase_line_net_gte0"),
            models.CheckConstraint(condition=models.Q(measured_weight_kg__isnull=True) | models.Q(measured_weight_kg__gt=0), name="purchase_line_weight_kg_gt0"),
            models.CheckConstraint(condition=models.Q(freight_allocated__gte=0), name="purchase_line_freight_allocated_gte0"),
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


class PurchaseReturnStatus(models.TextChoices):
    POSTED = "POSTED", "Posted"
    REVERSED = "REVERSED", "Reversed"


class PurchaseReturnQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if self.filter(status=PurchaseReturnStatus.POSTED).exists() or "status" in kwargs:
            raise PostedImmutabilityError("Posted purchase returns are immutable")
        return super().update(**kwargs)

    def delete(self):
        if self.filter(status=PurchaseReturnStatus.POSTED).exists():
            raise PostedImmutabilityError("Posted purchase returns cannot be deleted")
        return super().delete()


class PurchaseReturn(models.Model):
    """Financial document for one immutable inventory purchase return.

    InventoryReturn remains the stock truth. This document adds the supplier
    claim/payable effect: Dr 2110 / Cr warehouse inventory at original cost.
    """

    document_number = models.CharField(max_length=30, unique=True)
    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT, related_name="purchase_returns")
    inventory_return = models.OneToOneField("inventory.InventoryReturn", null=True, blank=True, on_delete=models.PROTECT, related_name="purchase_financial_return")
    transit_lot = models.ForeignKey("goods_in_transit.GoodsInTransitLot", null=True, blank=True, on_delete=models.PROTECT, related_name="purchase_returns")
    supplier = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="purchase_returns")
    warehouse = models.ForeignKey("warehouses.Warehouse", on_delete=models.PROTECT, related_name="purchase_returns")
    currency = models.ForeignKey("currencies.Currency", on_delete=models.PROTECT, related_name="purchase_returns")
    return_date = models.DateField()
    quantity = models.IntegerField()
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    journal_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, related_name="purchase_return_document")
    status = models.CharField(max_length=10, choices=PurchaseReturnStatus.choices, default=PurchaseReturnStatus.POSTED)
    reason = models.CharField(max_length=500)
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_returns_created")
    posted_at = models.DateTimeField(auto_now_add=True)

    objects = PurchaseReturnQuerySet.as_manager()

    class Meta:
        ordering = ["return_date", "document_number"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="purchase_return_qty_gt0"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="purchase_return_amount_gt0"),
        ]

    def save(self, *args, **kwargs):
        allow_reversal = kwargs.pop("allow_reversal", False)
        if self.pk is not None:
            current = type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if current == PurchaseReturnStatus.POSTED:
                if not (
                    allow_reversal
                    and self.status == PurchaseReturnStatus.REVERSED
                    and kwargs.get("update_fields") is not None
                    and set(kwargs["update_fields"]) == {"status"}
                ):
                    raise PostedImmutabilityError("Posted purchase returns are immutable; correct through reversal")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk is not None and type(self).objects.filter(pk=self.pk, status=PurchaseReturnStatus.POSTED).exists():
            raise PostedImmutabilityError("Posted purchase returns cannot be deleted")
        return super().delete(*args, **kwargs)


class SupplierRefundStatus(models.TextChoices):
    POSTED = "POSTED", "Posted"
    REVERSED = "REVERSED", "Reversed"


class SupplierRefund(models.Model):
    """Settlement of a supplier claim created by a Purchase Return."""
    document_number = models.CharField(max_length=30, unique=True)
    purchase_return = models.ForeignKey(PurchaseReturn, on_delete=models.PROTECT, related_name="refunds")
    refund_date = models.DateField()
    claim_amount = models.DecimalField(max_digits=20, decimal_places=2)
    refund_amount = models.DecimalField(max_digits=20, decimal_places=2)
    claim_currency = models.ForeignKey("currencies.Currency", on_delete=models.PROTECT, related_name="supplier_refund_claims")
    refund_currency = models.ForeignKey("currencies.Currency", on_delete=models.PROTECT, related_name="supplier_refund_cash")
    agreed_rate = models.DecimalField(max_digits=20, decimal_places=8)
    rate_direction = models.CharField(max_length=80)
    status = models.CharField(max_length=10, choices=SupplierRefundStatus.choices, default=SupplierRefundStatus.POSTED)
    reason = models.CharField(max_length=500)
    idempotency_key = models.CharField(max_length=128, unique=True)
    journal_entry = models.ForeignKey("accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="supplier_refunds")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="supplier_refunds_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["refund_date", "document_number"]
        constraints = [
            models.CheckConstraint(condition=models.Q(claim_amount__gt=0), name="supplier_refund_claim_amount_gt0"),
            models.CheckConstraint(condition=models.Q(refund_amount__gt=0), name="supplier_refund_amount_gt0"),
            models.CheckConstraint(condition=models.Q(agreed_rate__gt=0), name="supplier_refund_rate_gt0"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Supplier refunds are immutable; correct through reversal")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Supplier refunds cannot be deleted; correct through reversal")


class CrossCurrencySupplierRefundStatus(models.TextChoices):
    POSTED = "POSTED", "Posted"
    REVERSED = "REVERSED", "Reversed"


class CrossCurrencySupplierRefund(models.Model):
    """Coordinator for a supplier claim settled in a different currency."""
    refund = models.OneToOneField(SupplierRefund, on_delete=models.PROTECT, related_name="cross_currency_refund")
    claim_currency = models.ForeignKey("currencies.Currency", on_delete=models.PROTECT, related_name="cross_supplier_refunds_as_claim")
    claim_amount = models.DecimalField(max_digits=20, decimal_places=2)
    refund_currency = models.ForeignKey("currencies.Currency", on_delete=models.PROTECT, related_name="cross_supplier_refunds_as_cash")
    refund_amount = models.DecimalField(max_digits=20, decimal_places=2)
    agreed_rate = models.DecimalField(max_digits=20, decimal_places=8)
    rate_direction = models.CharField(max_length=80)
    claim_journal = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, related_name="cross_currency_supplier_refund_claim")
    cash_journal = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, related_name="cross_currency_supplier_refund_cash")
    status = models.CharField(max_length=10, choices=CrossCurrencySupplierRefundStatus.choices, default=CrossCurrencySupplierRefundStatus.POSTED)
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(claim_amount__gt=0), name="cross_supplier_refund_claim_gt0"),
            models.CheckConstraint(condition=models.Q(refund_amount__gt=0), name="cross_supplier_refund_amount_gt0"),
            models.CheckConstraint(condition=models.Q(agreed_rate__gt=0), name="cross_supplier_refund_rate_gt0"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Cross-currency supplier refunds are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Cross-currency supplier refunds cannot be deleted")


class SupplierRefundReversal(models.Model):
    refund = models.OneToOneField(SupplierRefund, on_delete=models.PROTECT, related_name="reversal")
    journal_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, related_name="supplier_refund_reversal")
    cross_currency = models.OneToOneField(CrossCurrencySupplierRefund, null=True, blank=True, on_delete=models.PROTECT, related_name="reversal")
    reason = models.CharField(max_length=500)
    idempotency_key = models.CharField(max_length=128, unique=True)
    reversed_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="supplier_refund_reversals_created")

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Supplier refund reversals are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Supplier refund reversals cannot be deleted")


class PurchaseReturnReversal(models.Model):
    purchase_return = models.OneToOneField(PurchaseReturn, on_delete=models.PROTECT, related_name="reversal")
    journal_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, related_name="purchase_return_reversal")
    stock_movement = models.OneToOneField("inventory.StockMovement", null=True, blank=True, on_delete=models.PROTECT, related_name="purchase_return_reversal")
    reason = models.CharField(max_length=500)
    idempotency_key = models.CharField(max_length=128, unique=True)
    reversed_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_return_reversals_created")

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Purchase return reversals are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Purchase return reversals cannot be deleted")



class LandedCostStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    POSTED = "POSTED", "Posted"


class LandedCostAllocationMethod(models.TextChoices):
    DIRECT = "DIRECT", "Direct to purchase line"
    WEIGHT = "WEIGHT", "Measured-weight allocation"


class LandedCostDocumentQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if self.filter(status=LandedCostStatus.POSTED).exists() or "status" in kwargs:
            raise PostedImmutabilityError("Posted landed-cost documents are immutable")
        return super().update(**kwargs)

    def delete(self):
        if self.filter(status=LandedCostStatus.POSTED).exists():
            raise PostedImmutabilityError("Posted landed-cost documents cannot be deleted")
        return super().delete()


class LandedCostAllocationQuerySet(models.QuerySet):
    def _contains_posted_parent(self):
        return self.filter(cost_document__status=LandedCostStatus.POSTED).exists()

    def update(self, **kwargs):
        target = kwargs.get("cost_document_id", kwargs.get("cost_document"))
        target_id = getattr(target, "pk", target)
        if self._contains_posted_parent() or (
            target_id is not None
            and LandedCostDocument.objects.filter(
                pk=target_id, status=LandedCostStatus.POSTED
            ).exists()
        ):
            raise PostedImmutabilityError("Allocations of posted landed costs are immutable")
        return super().update(**kwargs)

    def delete(self):
        if self._contains_posted_parent():
            raise PostedImmutabilityError("Allocations of posted landed costs cannot be deleted")
        return super().delete()


class LandedCostDocument(models.Model):
    """Immutable later direct-cost source; valuation effects are separate adjustments.

    Amount/rate fields preserve the cost document's own historical transaction
    context. They must never overwrite the source Purchase or its posted journal.
    """

    document_number = models.CharField(max_length=30, unique=True)
    payee = models.ForeignKey(
        "parties.Party", on_delete=models.PROTECT, related_name="landed_cost_documents"
    )
    cost_date = models.DateField()
    currency = models.ForeignKey(
        "currencies.Currency", on_delete=models.PROTECT, related_name="landed_cost_documents"
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=4)
    rate_date = models.DateField()
    afn_amount = models.DecimalField(max_digits=20, decimal_places=2)
    category = models.CharField(max_length=40)
    description = models.CharField(max_length=500, blank=True, default="")
    status = models.CharField(max_length=10, choices=LandedCostStatus.choices, default=LandedCostStatus.DRAFT)
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT,
        related_name="landed_cost_documents",
    )
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="landed_cost_documents_created",
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = LandedCostDocumentQuerySet.as_manager()

    class Meta:
        ordering = ["cost_date", "document_number"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="landed_cost_amount_gt0"),
            models.CheckConstraint(condition=models.Q(exchange_rate__gt=0), name="landed_cost_rate_gt0"),
            models.CheckConstraint(condition=models.Q(afn_amount__gt=0), name="landed_cost_afn_gt0"),
            models.CheckConstraint(condition=~models.Q(document_number=""), name="landed_cost_doc_nonblank"),
            models.CheckConstraint(condition=~models.Q(category=""), name="landed_cost_category_nonblank"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            current = type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if current == LandedCostStatus.POSTED:
                raise PostedImmutabilityError(
                    "Posted landed-cost documents are immutable; correct through traceable adjustment/reversal"
                )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk is not None and type(self).objects.filter(pk=self.pk, status=LandedCostStatus.POSTED).exists():
            raise PostedImmutabilityError("Posted landed-cost documents cannot be deleted")
        return super().delete(*args, **kwargs)


class LandedCostAllocation(models.Model):
    """Immutable allocation snapshot for one source purchase line."""

    cost_document = models.ForeignKey(
        LandedCostDocument, on_delete=models.PROTECT, related_name="allocations"
    )
    purchase_line = models.ForeignKey(
        PurchaseLine, on_delete=models.PROTECT, related_name="landed_cost_allocations"
    )
    method = models.CharField(max_length=10, choices=LandedCostAllocationMethod.choices)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    afn_amount = models.DecimalField(max_digits=20, decimal_places=2)
    measured_weight_kg = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = LandedCostAllocationQuerySet.as_manager()

    class Meta:
        ordering = ["cost_document_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["cost_document", "purchase_line"], name="uniq_lc_doc_purchase_line"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="landed_cost_alloc_amount_gt0"),
            models.CheckConstraint(condition=models.Q(afn_amount__gt=0), name="landed_cost_alloc_afn_gt0"),
            models.CheckConstraint(
                condition=models.Q(measured_weight_kg__isnull=True) | models.Q(measured_weight_kg__gt=0),
                name="landed_cost_alloc_weight_gt0",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            original_document_id = type(self).objects.filter(pk=self.pk).values_list(
                "cost_document_id", flat=True
            ).first()
            if original_document_id and LandedCostDocument.objects.filter(
                pk=original_document_id, status=LandedCostStatus.POSTED
            ).exists():
                raise PostedImmutabilityError("Allocations of posted landed-cost documents are immutable")
        if self.cost_document_id and LandedCostDocument.objects.filter(
            pk=self.cost_document_id, status=LandedCostStatus.POSTED
        ).exists():
            raise PostedImmutabilityError("Cannot add or move allocations into a posted landed-cost document")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk is not None and type(self).objects.filter(
            pk=self.pk, cost_document__status=LandedCostStatus.POSTED
        ).exists():
            raise PostedImmutabilityError("Allocations of posted landed-cost documents cannot be deleted")
        return super().delete(*args, **kwargs)
