from django.db import models

from accounting.models import JournalEntry
from currencies.models import Currency
from parties.models import Party


class PaymentPurpose(models.TextChoices):
    RECEIVABLE = "RECEIVABLE", "Customer Receivable"
    CUSTOMER_CREDIT = "CUSTOMER_CREDIT", "Customer Credit / Advance"


class Payment(models.Model):
    """Immutable customer cash-receipt document; allocation is a later phase."""

    document_number = models.CharField(max_length=30, unique=True)
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="payments")
    payment_date = models.DateField()
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    purpose = models.CharField(max_length=20, choices=PaymentPurpose.choices)
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, related_name="payment_document")
    description = models.CharField(max_length=500, blank=True, default="")
    reference = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["payment_date", "document_number"]

    def __str__(self):
        return self.document_number
