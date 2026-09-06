from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db import models


class AccountType(models.TextChoices):
    ASSET = "ASSET", "Asset"
    LIABILITY = "LIABILITY", "Liability"
    EQUITY = "EQUITY", "Equity"
    REVENUE = "REVENUE", "Revenue"
    EXPENSE = "EXPENSE", "Expense"


class JournalStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    POSTED = "POSTED", "Posted"
    REVERSED = "REVERSED", "Reversed"


class Account(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    is_posting = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class JournalEntry(models.Model):
    number = models.CharField(max_length=30, unique=True)
    posting_date = models.DateField()
    description = models.CharField(max_length=500)
    source_type = models.CharField(max_length=80, blank=True)
    source_id = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=12, choices=JournalStatus.choices, default=JournalStatus.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["posting_date", "number"]


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="journal_lines")
    debit = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0"))])
    credit = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0"))])
    description = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(models.Q(debit__gt=0) & models.Q(credit=0)) | (models.Q(credit__gt=0) & models.Q(debit=0)), name="journal_line_one_sided_positive"),
        ]
