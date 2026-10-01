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


class CrossCurrencySettlementStatus(models.TextChoices):
    POSTED = "POSTED", "Posted"
    REVERSED = "REVERSED", "Reversed"


class CrossCurrencySettlement(models.Model):
    """Immutable coordinator for one customer payment settling debt in another currency.

    The linked Payment records the actual cash received. The settlement stores the
    agreed payment-time conversion independently from the invoice and coordinates
    the two single-currency journal legs.
    """

    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="cross_currency_settlement")
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="cross_currency_settlements")
    debt_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="settlements_as_debt_currency")
    debt_amount = models.DecimalField(max_digits=20, decimal_places=2)
    payment_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="settlements_as_payment_currency")
    payment_amount = models.DecimalField(max_digits=20, decimal_places=2)
    agreed_rate = models.DecimalField(max_digits=20, decimal_places=8)
    rate_direction = models.CharField(max_length=80)
    settled_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=CrossCurrencySettlementStatus.choices, default=CrossCurrencySettlementStatus.POSTED)
    idempotency_key = models.CharField(max_length=128, unique=True)
    cash_journal = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, related_name="cross_currency_cash_settlement")
    receivable_journal = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, related_name="cross_currency_receivable_settlement")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(debt_amount__gt=0), name="ccs_debt_amount_gt0"),
            models.CheckConstraint(condition=models.Q(payment_amount__gt=0), name="ccs_payment_amount_gt0"),
            models.CheckConstraint(condition=models.Q(agreed_rate__gt=0), name="ccs_rate_gt0"),
        ]
        indexes = [
            models.Index(fields=["party", "debt_currency"], name="ccs_party_debt_cur_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Cross-currency settlements are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Cross-currency settlements cannot be deleted")
