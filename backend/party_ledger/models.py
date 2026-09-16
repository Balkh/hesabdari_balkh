"""Party Ledger attribution model (Phase 5 — derived subsidiary layer).

OD-5-01/OD-5-02 (Option A): a NEW link row maps one posted journal LINE
to one Party. The financial amount stays on JournalLine, the account
stays on JournalLine, the currency stays authoritative on JournalEntry —
the Party relation is the only new dimension. Balance TYPE is derived
from the line's account via the single authoritative mapping below (§7);
it is never stored and never user-selectable.

Frozen models are untouched: no field is added to JournalEntry,
JournalLine, Party, Account, or Currency. Attribution rows are immutable
(§9): creation annotates posted truth; updates and deletes are refused
with the reused ``PostedImmutabilityError``. Correction happens through
accounting reversal plus a new attribution.
"""

from django.db import models

from accounting.models import PostedImmutabilityError


class BalanceType(models.TextChoices):
    """Phase-5 balance types (§7). Derived from account, never stored."""

    RECEIVABLE = "RECEIVABLE", "Receivable"
    PAYABLE = "PAYABLE", "Payable"
    CUSTOMER_CREDIT = "CUSTOMER_CREDIT", "Customer Credit"
    SUPPLIER_ADVANCE = "SUPPLIER_ADVANCE", "Supplier Advance"


# THE authoritative account → balance-type mapping (§7). Import this;
# do not duplicate it in services, derivation, or tests.
PARTY_LEDGER_ACCOUNTS = {
    "1310": BalanceType.RECEIVABLE,
    "2110": BalanceType.PAYABLE,
    "2200": BalanceType.CUSTOMER_CREDIT,
    "1500": BalanceType.SUPPLIER_ADVANCE,
}

OPENING_EQUITY_ACCOUNT = "3900"
OPENING_SOURCE_TYPE = "OPENING_BALANCE"


class PartyLedgerAttribution(models.Model):
    """One immutable link: posted JournalLine → Party (OD-5-01 A).

    OneToOne enforces "one attribution per journal line" at the database
    (§10/§31). There is deliberately NO unique(party, currency, type):
    that identity is a QUERY identity (§6), not a stored row (OD-5-04 A).
    """

    journal_line = models.OneToOneField(
        "accounting.JournalLine",
        on_delete=models.PROTECT,
        related_name="party_ledger_attribution",
    )
    party = models.ForeignKey(
        "parties.Party",
        on_delete=models.PROTECT,
        related_name="party_ledger_attributions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PostedImmutabilityError(
                "Party attribution is immutable; correct through reversal"
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PostedImmutabilityError(
            "Party attribution cannot be deleted; correct through reversal"
        )
