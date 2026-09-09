"""Account balances, trial balance and source traceability (Stage 2.4).

READ-ONLY layer over posted journals (Phase 0 §1.2/§1.4/§1.8/§1.9):

- Only POSTED and REVERSED entries participate (positive inclusion — DRAFT and
  any other status are excluded; reversed originals remain, their POSTED
  reversals offset them).
- Date filtering uses journal POSTING DATE, inclusive bounds.
- Signed balances follow normal-balance semantics; 4200/5200 use the explicit
  contra overrides below WITHOUT changing canonical COA types.
- Different transaction currencies are NEVER merged numerically (§16.6-5):
  mixed-currency activity raises instead of summing. Currency-separated
  balances arrive with the later ledger phases, which will extend this module.
- All money math is Decimal, aggregated in the database (no float, no N+1).
- trial_balance() FAILS LOUDLY on imbalance — it never repairs or hides.
- Nothing in this module mutates accounting truth.
"""

from decimal import Decimal

from django.db.models import Count, Sum

from .models import Account, AccountType, JournalEntry, JournalLine, JournalStatus
from .services import JournalValidationError, _as_date  # shared date coercion — do not fork


class TrialBalanceError(JournalValidationError):
    """Trial Balance debits != credits. Carries the computed ``result`` for diagnosis."""

    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result


# Statuses that carry financial effect. Everything else (DRAFT, ...) is excluded.
EFFECTIVE_STATUSES = (JournalStatus.POSTED, JournalStatus.REVERSED)

# Canonical accounting chronology: posting date → document sequence → entry id.
# "Document sequence" is the unique journal number.
CHRONOLOGY_ORDER = ("posting_date", "number", "id")

# Effective normal balances. Types first, then explicit contra overrides.
# 4200 keeps COA type REVENUE and 5200 keeps COA type EXPENSE (frozen);
# only the balance SIGN convention is overridden here per Stage 2.4 RULE 5.
DEBIT_NORMAL_TYPES = frozenset({AccountType.ASSET, AccountType.EXPENSE})
CONTRA_NORMAL_BALANCE = {"4200": "DEBIT", "5200": "CREDIT"}


def normal_balance_of(account):
    """Effective normal balance ('DEBIT' or 'CREDIT') for an account."""
    if account.code in CONTRA_NORMAL_BALANCE:
        return CONTRA_NORMAL_BALANCE[account.code]
    if account.account_type in DEBIT_NORMAL_TYPES:
        return "DEBIT"
    return "CREDIT"


def _coerce_account(account):
    if not isinstance(account, Account) or account.pk is None:
        raise JournalValidationError("A persisted Account is required")


def _coerce_range(date_from, date_to):
    start = _as_date(date_from, "date_from") if date_from is not None else None
    end = _as_date(date_to, "date_to") if date_to is not None else None
    if start is not None and end is not None and start > end:
        raise JournalValidationError("date_from cannot be after date_to")
    return start, end


def _signed(debit, credit, normal_balance):
    if normal_balance == "DEBIT":
        return debit - credit
    return credit - debit


def _reject_mixed_currencies(lines):
    """Refuse to sum lines spanning more than one transaction currency.

    NULL (legacy unknown) counts as its own bucket: unknown amounts are never
    silently merged with known-currency amounts either.
    """
    mix = lines.aggregate(currencies=Count("entry__currency", distinct=True),
                          with_currency=Count("entry__currency"), total=Count("id"))
    distinct = mix["currencies"] + (1 if mix["total"] != mix["with_currency"] else 0)
    if distinct > 1:
        codes = sorted({c or "UNKNOWN" for c in lines.values_list("entry__currency__code", flat=True)})
        raise JournalValidationError(
            f"Cannot merge transaction currencies {codes} into one balance; "
            "post or filter a single currency"
        )


def account_balance(account, date_from=None, date_to=None):
    """Signed balance of one account from posted journal lines (read-only).

    Returns a dict with account identity, total_debit, total_credit, signed
    ``balance`` (Decimal, normal-balance convention), normal-balance context,
    line count and the effective date range. Never mutates.
    """
    _coerce_account(account)
    start, end = _coerce_range(date_from, date_to)
    lines = JournalLine.objects.filter(entry__status__in=EFFECTIVE_STATUSES, account=account)
    if start is not None:
        lines = lines.filter(entry__posting_date__gte=start)
    if end is not None:
        lines = lines.filter(entry__posting_date__lte=end)
    _reject_mixed_currencies(lines)
    totals = lines.aggregate(debit=Sum("debit"), credit=Sum("credit"), n=Count("id"))
    debit = totals["debit"] or Decimal("0")
    credit = totals["credit"] or Decimal("0")
    normal = normal_balance_of(account)
    return {
        "account_code": account.code,
        "account_name": account.name,
        "account_type": str(account.account_type),
        "normal_balance": normal,
        "is_contra": account.code in CONTRA_NORMAL_BALANCE,
        "total_debit": debit,
        "total_credit": credit,
        "balance": _signed(debit, credit, normal),
        "lines_count": totals["n"],
        "date_from": start,
        "date_to": end,
    }


def trial_balance(date_to=None):
    """Trial balance over posted lines up to ``date_to`` (None = all history).

    One grouped database query; rows ordered by canonical account code; only
    accounts WITH posted activity appear (zero-net accounts included — activity
    is activity). Raises TrialBalanceError (with ``.result``) when
    Σ debit != Σ credit. Never mutates, never repairs.
    """
    end = _as_date(date_to, "date_to") if date_to is not None else None
    lines = JournalLine.objects.filter(entry__status__in=EFFECTIVE_STATUSES)
    if end is not None:
        lines = lines.filter(entry__posting_date__lte=end)
    _reject_mixed_currencies(lines)
    grouped = (
        lines.values("account__code", "account__name", "account__account_type")
        .annotate(debit=Sum("debit"), credit=Sum("credit"), n=Count("id"))
        .order_by("account__code")
    )
    rows = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for row in grouped:
        debit = row["debit"] or Decimal("0")
        credit = row["credit"] or Decimal("0")
        code = row["account__code"]
        if code in CONTRA_NORMAL_BALANCE:
            normal = CONTRA_NORMAL_BALANCE[code]
        elif row["account__account_type"] in DEBIT_NORMAL_TYPES:
            normal = "DEBIT"
        else:
            normal = "CREDIT"
        total_debit += debit
        total_credit += credit
        rows.append({
            "account_code": code,
            "account_name": row["account__name"],
            "account_type": row["account__account_type"],
            "debit": debit,
            "credit": credit,
            "balance": _signed(debit, credit, normal),
            "normal_balance": normal,
            "lines_count": row["n"],
        })
    difference = total_debit - total_credit
    result = {
        "date_to": end,
        "rows": rows,
        "accounts_count": len(rows),
        "total_debit": total_debit,
        "total_credit": total_credit,
        "difference": difference,
        "balanced": difference == 0,
    }
    if difference != 0:
        raise TrialBalanceError(
            f"Trial balance out of balance: debit {total_debit} != credit {total_credit} "
            f"(difference {difference})",
            result=result,
        )
    return result


def journals_by_source(source_type, source_id):
    """All journal entries for a source, in canonical chronology order.

    Returns a list (possibly empty — never None, never an error for missing
    sources). Read-only.
    """
    return list(
        JournalEntry.objects.filter(source_type=source_type or "", source_id=str(source_id or ""))
        .order_by(*CHRONOLOGY_ORDER)
    )


def trace_source(entry):
    """Journal → source reference (read-only, never fabricates, never rewrites).

    ``resolved`` is False for every source type in Stage 2.4: no business
    modules exist yet, so no source document can be resolved. Future phases may
    add resolvers behind this stable return shape.
    """
    if not isinstance(entry, JournalEntry) or entry.pk is None:
        raise JournalValidationError("A persisted JournalEntry is required")
    return {
        "entry_id": entry.pk,
        "entry_number": entry.number,
        "entry_status": entry.status,
        "source_type": entry.source_type,
        "source_id": entry.source_id,
        "resolved": False,
        "document": None,
    }
