from django.conf import settings
from django.db import models

from accounting.models import JournalEntry, PostedImmutabilityError


class SupplierAdvanceQuerySet(models.QuerySet):
    def _contains_posted(self):
        return self.filter(status=SupplierAdvanceStatus.POSTED).exists()

    def update(self, **kwargs):
        if self._contains_posted() or "status" in kwargs:
            raise PostedImmutabilityError("Posted supplier advances cannot be changed through bulk ORM updates")
        return super().update(**kwargs)

    def delete(self):
        if self._contains_posted():
            raise PostedImmutabilityError("Posted supplier advances cannot be deleted through bulk ORM deletion")
        return super().delete()


class SupplierAdvanceAllocationQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if self.exists():
            raise PostedImmutabilityError("Supplier advance allocations are immutable")
        return super().update(**kwargs)

    def delete(self):
        if self.exists():
            raise PostedImmutabilityError("Supplier advance allocations cannot be deleted")
        return super().delete()


class SupplierAdvanceAllocationReversalQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if self.exists():
            raise PostedImmutabilityError("Supplier advance allocation reversals are immutable")
        return super().update(**kwargs)

    def delete(self):
        if self.exists():
            raise PostedImmutabilityError("Supplier advance allocation reversals cannot be deleted")
        return super().delete()


class SupplierAdvanceStatus(models.TextChoices):
    POSTED = "POSTED", "Posted"
    REVERSED = "REVERSED", "Reversed"


class SupplierAdvance(models.Model):
    """Immutable supplier prepayment document.

    A SupplierAdvance is independent of Purchase and Payable. Its financial
    truth is the linked journal: Dr 1500 / Cr 1110. Foreign-currency advances
    intentionally may be unvalued at invoice/advance time; the journal keeps
    currency truth without inventing a historical FX rate.
    """

    document_number = models.CharField(max_length=30, unique=True)
    supplier = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="supplier_advances")
    advance_date = models.DateField()
    currency = models.ForeignKey("currencies.Currency", on_delete=models.PROTECT, related_name="supplier_advances")
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, related_name="supplier_advance_document")
    status = models.CharField(max_length=10, choices=SupplierAdvanceStatus.choices, default=SupplierAdvanceStatus.POSTED)
    description = models.CharField(max_length=500, blank=True, default="")
    reference = models.CharField(max_length=200, blank=True, default="")
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="supplier_advances_created")
    posted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["advance_date", "document_number"]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="supplier_advance_amount_gt0")]

    objects = SupplierAdvanceQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if self.pk is not None:
            current = type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if current is not None:
                raise PostedImmutabilityError("Posted supplier advances are immutable; correct through reversal")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Supplier advances cannot be deleted; correct through reversal")


class SupplierAdvanceAllocation(models.Model):
    """Immutable application of a supplier advance to one posted Purchase."""

    advance = models.ForeignKey(SupplierAdvance, on_delete=models.PROTECT, related_name="allocations")
    purchase = models.ForeignKey("purchases.Purchase", on_delete=models.PROTECT, related_name="supplier_advance_allocations")
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    journal_entry = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="supplier_advance_allocation")
    idempotency_key = models.CharField(max_length=128, unique=True)
    allocated_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="supplier_advance_allocations_created")

    class Meta:
        ordering = ["id"]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="supplier_advance_alloc_amount_gt0")]

    objects = SupplierAdvanceAllocationQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Supplier advance allocations are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Supplier advance allocations cannot be deleted")


class SupplierAdvanceAllocationReversal(models.Model):
    """Immutable append-only reversal of one SupplierAdvanceAllocation."""

    allocation = models.OneToOneField(SupplierAdvanceAllocation, on_delete=models.PROTECT, related_name="reversal")
    journal_entry = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="supplier_advance_allocation_reversal")
    reason = models.CharField(max_length=500)
    idempotency_key = models.CharField(max_length=128, unique=True)
    reversed_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="supplier_advance_allocation_reversals_created")

    class Meta:
        ordering = ["id"]

    objects = SupplierAdvanceAllocationReversalQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("Supplier advance allocation reversals are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("Supplier advance allocation reversals cannot be deleted")
