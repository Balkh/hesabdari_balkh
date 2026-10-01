"""Phase 11 sales return/refund aggregates.

Return, financial entitlement, and refund are deliberately separate events.
The existing inventory return service remains the physical stock authority.
"""
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import models
from django.db.models import F

from accounting.models import PostedImmutabilityError


class SalesReturnStatus(models.TextChoices):
    POSTED = "POSTED", "Posted"
    REVERSED = "REVERSED", "Reversed"


class RefundStatus(models.TextChoices):
    POSTED = "POSTED", "Posted"
    REVERSED = "REVERSED", "Reversed"


class SalesReturn(models.Model):
    """One immutable commercial return for one released Warehouse Check."""

    document_number = models.CharField(max_length=30, unique=True)
    sale = models.ForeignKey("sales.Sale", on_delete=models.PROTECT, related_name="sales_returns")
    sale_line = models.ForeignKey("sales.SaleLine", on_delete=models.PROTECT, related_name="sales_returns")
    inventory_return = models.OneToOneField(
        "inventory.InventoryReturn", on_delete=models.PROTECT, related_name="sales_return"
    )
    warehouse = models.ForeignKey("warehouses.Warehouse", on_delete=models.PROTECT, related_name="sales_returns")
    return_date = models.DateField()
    quantity = models.PositiveIntegerField()
    entitlement_currency = models.ForeignKey(
        "currencies.Currency", on_delete=models.PROTECT, related_name="sales_return_entitlements"
    )
    entitlement_amount = models.DecimalField(max_digits=20, decimal_places=2)
    refundable_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    entitlement_journal = models.ForeignKey(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="sales_return_entitlements"
    )
    cogs_journal = models.ForeignKey(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="sales_return_cogs"
    )
    status = models.CharField(max_length=10, choices=SalesReturnStatus.choices, default=SalesReturnStatus.POSTED)
    reason = models.CharField(max_length=500)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="sales_returns_created",
    )
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["return_date", "document_number"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sales_return_qty_gt0"),
            models.CheckConstraint(condition=models.Q(entitlement_amount__gt=0), name="sales_return_entitlement_gt0"),
            models.CheckConstraint(condition=models.Q(refundable_amount__gte=0), name="sales_return_refundable_gte0"),
            models.CheckConstraint(condition=models.Q(refundable_amount__lte=models.F("entitlement_amount")), name="sales_return_refundable_lte_entitlement"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Posted sales returns are immutable; correct through reversal")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Sales returns cannot be deleted")


class Refund(models.Model):
    """One immutable cash refund consuming one SalesReturn entitlement."""

    document_number = models.CharField(max_length=30, unique=True)
    sales_return = models.ForeignKey(SalesReturn, on_delete=models.PROTECT, related_name="refunds")
    refund_date = models.DateField()
    entitlement_currency = models.ForeignKey(
        "currencies.Currency", on_delete=models.PROTECT, related_name="refund_entitlements"
    )
    entitlement_amount = models.DecimalField(max_digits=20, decimal_places=2)
    refund_currency = models.ForeignKey(
        "currencies.Currency", on_delete=models.PROTECT, related_name="refund_payments"
    )
    refund_amount = models.DecimalField(max_digits=20, decimal_places=2)
    agreed_rate = models.DecimalField(max_digits=20, decimal_places=8)
    rate_direction = models.CharField(max_length=80)
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT,
        related_name="refunds",
    )
    status = models.CharField(max_length=10, choices=RefundStatus.choices, default=RefundStatus.POSTED)
    reason = models.CharField(max_length=500)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="refunds_created",
    )
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["refund_date", "document_number"]
        constraints = [
            models.CheckConstraint(condition=models.Q(entitlement_amount__gt=0), name="refund_entitlement_gt0"),
            models.CheckConstraint(condition=models.Q(refund_amount__gt=0), name="refund_amount_gt0"),
            models.CheckConstraint(condition=models.Q(agreed_rate__gt=0), name="refund_rate_gt0"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Posted refunds are immutable; correct through reversal")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Refunds cannot be deleted")


class CrossCurrencyRefundStatus(models.TextChoices):
    POSTED = "POSTED", "Posted"
    REVERSED = "REVERSED", "Reversed"


class CrossCurrencyRefund(models.Model):
    """Aggregate coordinating two single-currency refund journal legs."""

    refund = models.OneToOneField(Refund, on_delete=models.PROTECT, related_name="cross_currency_refund")
    entitlement_currency = models.ForeignKey(
        "currencies.Currency", on_delete=models.PROTECT, related_name="cross_refunds_as_entitlement"
    )
    entitlement_amount = models.DecimalField(max_digits=20, decimal_places=2)
    refund_currency = models.ForeignKey(
        "currencies.Currency", on_delete=models.PROTECT, related_name="cross_refunds_as_payment"
    )
    refund_amount = models.DecimalField(max_digits=20, decimal_places=2)
    agreed_rate = models.DecimalField(max_digits=20, decimal_places=8)
    rate_direction = models.CharField(max_length=80)
    entitlement_journal = models.OneToOneField(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="cross_currency_refund_entitlement"
    )
    cash_journal = models.OneToOneField(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="cross_currency_refund_cash"
    )
    status = models.CharField(max_length=10, choices=CrossCurrencyRefundStatus.choices, default=CrossCurrencyRefundStatus.POSTED)
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(entitlement_amount__gt=0), name="cross_refund_entitlement_gt0"),
            models.CheckConstraint(condition=models.Q(refund_amount__gt=0), name="cross_refund_amount_gt0"),
            models.CheckConstraint(condition=models.Q(agreed_rate__gt=0), name="cross_refund_rate_gt0"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Cross-currency refunds are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Cross-currency refunds cannot be deleted")
