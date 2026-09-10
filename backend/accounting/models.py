from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class PostedImmutabilityError(ValueError):
    """Raised when code attempts to mutate or delete a POSTED/REVERSED journal row."""

    pass


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


IMMUTABLE_JOURNAL_STATUSES = (JournalStatus.POSTED, JournalStatus.REVERSED)


class Account(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    name_fa = models.CharField(max_length=200, blank=True, default="")
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
    # Stage 2.2 — journal currency contract (§1.8). NULL/empty snapshot fields
    # mean "legacy pre-2.2 row, original context unknown" — never fabricated.
    currency = models.ForeignKey("currencies.Currency", null=True, blank=True, on_delete=models.PROTECT, related_name="journal_entries")
    total_debit = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    total_credit = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    afn_total = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    rate = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    rate_date = models.DateField(null=True, blank=True)
    rate_direction = models.CharField(max_length=20, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # Stage 2.3 — posting integrity (§1.9). NULL = posted without an idempotency
    # key (legacy rows and non-idempotent posts); unique where present.
    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)
    reverses = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversals")
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["posting_date", "number"]
        indexes = [
            models.Index(fields=["source_type", "source_id"], name="je_src_type_id_idx"),
        ]

    def save(self, *args, **kwargs):
        bypass = kwargs.pop("allow_protected_update", False)
        if self.pk is not None:
            old_status = JournalEntry.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if old_status in IMMUTABLE_JOURNAL_STATUSES and not (
                bypass
                and old_status == JournalStatus.POSTED
                and self.status == JournalStatus.REVERSED
                and kwargs.get("update_fields") is not None
                and set(kwargs["update_fields"]) == {"status"}
            ):
                raise PostedImmutabilityError("POSTED/REVERSED journal entries are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk is not None:
            current = JournalEntry.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if current in IMMUTABLE_JOURNAL_STATUSES:
                raise PostedImmutabilityError("POSTED/REVERSED journal entries cannot be deleted")
        return super().delete(*args, **kwargs)


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="journal_lines")
    debit = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0"))])
    credit = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0"))])
    description = models.CharField(max_length=500, blank=True)
    reference = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(models.Q(debit__gt=0) & models.Q(credit=0)) | (models.Q(credit__gt=0) & models.Q(debit=0)), name="journal_line_one_sided_positive"),
        ]

    def save(self, *args, **kwargs):
        bypass = kwargs.pop("allow_protected_update", False)
        if self.pk is None:
            if self.entry_id is not None:
                status = JournalEntry.objects.filter(pk=self.entry_id).values_list("status", flat=True).first()
                if status in IMMUTABLE_JOURNAL_STATUSES and not bypass:
                    raise PostedImmutabilityError("Cannot add lines to a POSTED/REVERSED journal entry")
        else:
            original = JournalLine.objects.filter(pk=self.pk).values("entry__status").first()
            original_status = original["entry__status"] if original else None
            current_status = None
            if self.entry_id is not None:
                current_status = JournalEntry.objects.filter(pk=self.entry_id).values_list("status", flat=True).first()
            if original_status in IMMUTABLE_JOURNAL_STATUSES or current_status in IMMUTABLE_JOURNAL_STATUSES:
                raise PostedImmutabilityError("POSTED/REVERSED journal lines are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk is not None:
            original = JournalLine.objects.filter(pk=self.pk).values("entry__status").first()
            if original and original["entry__status"] in IMMUTABLE_JOURNAL_STATUSES:
                raise PostedImmutabilityError("POSTED/REVERSED journal lines cannot be deleted")
        return super().delete(*args, **kwargs)


class FXSettlement(models.Model):
    """Structured, immutable snapshot of one manual-rate FX transaction.

    Stage 2.5, user ruling L1: the settlement rate is TRANSACTION DATA. It is
    entered by the user at settlement/conversion time, snapshotted here at 4
    decimals, and is never derived from — nor updated by — any later
    ``ExchangeRate`` row (§1.12). A later global rate of 75 or 80 leaves this
    row exactly as it was entered.

    ``JournalEntry.rate`` deliberately keeps the journal's own accounting
    currency snapshot (``1.0000`` / ``AFN->AFN`` for AFN book-value journals);
    it is NOT repurposed as the settlement rate, because doing so would
    misrepresent that journal's currency context and its AFN equivalent.

    Every field is structured, so the settlement can be queried, filtered,
    audited and reported without parsing any free text. ``description`` /
    ``reference`` remain available for the user's own explanation, but they are
    never the only storage location for the rate.

    Immutable (§1.9): updates and deletes are refused, exactly like posted
    journals. Correction happens through reversal of the linked journal.
    """

    class Result(models.TextChoices):
        GAIN = "GAIN", "Gain"
        LOSS = "LOSS", "Loss"
        NONE = "NONE", "No FX result"

    CONVERSION = "CONVERSION"
    RECEIVABLE = "RECEIVABLE"
    PAYABLE = "PAYABLE"

    entry = models.OneToOneField("JournalEntry", on_delete=models.PROTECT, related_name="fx_settlement")
    transaction_date = models.DateField()
    kind = models.CharField(max_length=12, default=CONVERSION)
    source_currency = models.ForeignKey("currencies.Currency", on_delete=models.PROTECT,
                                        related_name="fx_settlement_sources")
    source_amount = models.DecimalField(max_digits=20, decimal_places=2)
    target_currency = models.ForeignKey("currencies.Currency", on_delete=models.PROTECT,
                                        related_name="fx_settlement_targets")
    target_amount = models.DecimalField(max_digits=20, decimal_places=2)
    settlement_rate = models.DecimalField(max_digits=20, decimal_places=4)
    rate_direction = models.CharField(max_length=20)
    historical_rate = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    obligation_account = models.ForeignKey("Account", on_delete=models.PROTECT,
                                           related_name="fx_settlement_obligations")
    settlement_account = models.ForeignKey("Account", on_delete=models.PROTECT,
                                           related_name="fx_settlement_destinations")
    fx_account = models.ForeignKey("Account", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="fx_settlement_results")
    carrying_value = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    settlement_value = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    difference = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal("0.00"))
    direction = models.CharField(max_length=8, choices=Result.choices, default=Result.NONE)
    description = models.CharField(max_length=500, blank=True, default="")
    reference = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["transaction_date"], name="fx_settle_date_idx"),
        ]

    def __str__(self):
        return (
            f"{self.source_amount} {self.source_currency} -> {self.target_amount} "
            f"{self.target_currency} @ {self.settlement_rate}"
        )

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError("FX settlement records are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError("FX settlement records cannot be deleted")
