"""Party Ledger services (Phase 5): attribution + controlled opening.

Two operations only (§12/§13/§15):

- ``attribute_journal_line``: annotate one posted party-account line.
- ``open_party_balance``: post one controlled opening journal through the
  frozen pipeline (period gate + validation + POST audit + idempotency)
  and attribute its party leg — atomically (§14).

Everything else is reused, never duplicated: posting, reversal,
currency, FX, audit, idempotency, period gate, numbering, sign
conventions (§4/§40).
"""

from datetime import date as date_class
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction

from accounting.balances import EFFECTIVE_STATUSES, normal_balance_of
from accounting.models import Account, JournalEntry, JournalLine
from accounting.services import _as_date, post_journal
from core.dates import gregorian_to_jalali
from core.money import quantize_half_up
from currencies.models import Currency
from documents.services import next_document_number
from parties.services import PartyValidationError
from parties.services import resolve_party as _resolve_party_frozen
from security.models import AuditAction
from security.services import record_audit_event

from .models import (
    OPENING_EQUITY_ACCOUNT,
    OPENING_SOURCE_TYPE,
    PARTY_LEDGER_ACCOUNTS,
    BalanceType,
    PartyLedgerAttribution,
)


class PartyLedgerValidationError(ValueError):
    """Deterministic party-ledger rejection (service-error convention)."""


def _require_actor(user, action):
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        raise PartyLedgerValidationError(
            f"Authorization required to {action}: user must be a user."
        )
    return user


def resolve_party(ref):
    """Resolve via the frozen Party resolver; translate the domain error."""
    try:
        return _resolve_party_frozen(ref)
    except PartyValidationError as exc:
        raise PartyLedgerValidationError(str(exc)) from exc


def resolve_currency(ref):
    """Accept a Currency instance or exact code; deterministic miss error.

    No currency resolver exists in the repository, so this minimal
    resolver is new-but-necessary (§40: no equivalent to reuse).
    """
    if isinstance(ref, Currency):
        if ref.pk is None:
            raise PartyLedgerValidationError("Currency does not exist.")
        return ref
    if isinstance(ref, str) and ref:
        found = Currency.objects.filter(code=ref).first()
        if found is not None:
            return found
    raise PartyLedgerValidationError("Currency does not exist.")


def _require_usable_account(code):
    try:
        account = Account.objects.get(code=code)
    except Account.DoesNotExist as exc:
        raise PartyLedgerValidationError(
            f"Account {code} does not exist; seed the canonical COA."
        ) from exc
    if not account.is_active or not account.is_posting:
        raise PartyLedgerValidationError(
            f"Account {code} is not usable for posting."
        )
    return account


def _snapshot(attribution):
    line = attribution.journal_line
    entry = line.entry
    return {
        "id": attribution.id,
        "journal_line_id": line.pk,
        "journal_entry_id": entry.pk,
        "journal_number": entry.number,
        "account_code": line.account.code,
        "balance_type": PARTY_LEDGER_ACCOUNTS[line.account.code],
        "party_id": attribution.party.pk,
        "party_name": attribution.party.name,
        "currency": entry.currency.code if entry.currency else None,
    }


def attribute_journal_line(line, *, party, user=None):
    """Annotate one posted party-account line with its Party (§13).

    Eligibility (§11): the line must belong to a POSTED/REVERSED journal
    and hit one of 1310/2110/2200/1500. DRAFT lines are rejected loudly:
    attribution annotates financial truth, and DRAFT has none.
    """
    actor = _require_actor(user, "attribute journal line")
    if not isinstance(line, JournalLine) or line.pk is None:
        raise PartyLedgerValidationError(
            "A persisted journal line is required."
        )
    if line.entry.status not in EFFECTIVE_STATUSES:
        raise PartyLedgerValidationError(
            "Only lines of POSTED or REVERSED journals can be attributed."
        )
    if line.account.code not in PARTY_LEDGER_ACCOUNTS:
        raise PartyLedgerValidationError(
            f"Account {line.account.code} is not a party-ledger account."
        )
    resolved = resolve_party(party)
    try:
        with transaction.atomic():
            attribution = PartyLedgerAttribution.objects.create(
                journal_line=line, party=resolved
            )
            record_audit_event(
                user=actor, action=AuditAction.CREATE,
                entity="PartyLedgerAttribution",
                entity_id=attribution.id, reference=resolved.name,
                previous_state=None, new_state=_snapshot(attribution),
                reason="",
            )
    except IntegrityError as exc:
        raise PartyLedgerValidationError(
            "This journal line is already attributed to a party."
        ) from exc
    return attribution


def _coerce_balance_type(value):
    if isinstance(value, BalanceType):
        return str(value)
    if isinstance(value, str) and value in BalanceType.values:
        return value
    raise PartyLedgerValidationError(
        "Balance type must be one of RECEIVABLE, PAYABLE, "
        "CUSTOMER_CREDIT, SUPPLIER_ADVANCE."
    )


def _coerce_amount(value):
    try:
        amount = quantize_half_up(Decimal(str(value)), 2)
    except (InvalidOperation, ValueError, TypeError, ArithmeticError) as exc:
        raise PartyLedgerValidationError(
            "Opening amount must be a positive number."
        ) from exc
    if amount <= 0:
        raise PartyLedgerValidationError(
            "Opening amount must be a positive number."
        )
    return amount


def _jalali_year(value):
    return int(gregorian_to_jalali(value).split("/")[0])


def open_party_balance(*, party, currency, balance_type, amount,
                       posting_date, description="", reference="",
                       rate=None, rate_date=None, user=None,
                       number=None, idempotency_key=None):
    """Post one controlled opening journal + attribute it, atomically.

    Uses ``post_journal`` (period gate + validation + POST audit +
    idempotency all automatic) with the "JE" system-number precedent and
    source OPENING_BALANCE. The party leg follows the account's frozen
    normal-balance semantics; the other leg is 3900 (§15/§16). No
    one-shot restriction is invented (OD-5-03 A). Returns the entry.
    """
    actor = _require_actor(user, "open party balance")
    resolved_party = resolve_party(party)
    resolved_currency = resolve_currency(currency)
    if not resolved_currency.is_active:
        raise PartyLedgerValidationError("Currency is not active.")
    type_value = _coerce_balance_type(balance_type)
    clean_amount = _coerce_amount(amount)
    if not isinstance(description, str) or not isinstance(reference, str):
        raise PartyLedgerValidationError(
            "Opening description and reference must be text."
        )
    account_code = next(
        code for code, kind in PARTY_LEDGER_ACCOUNTS.items()
        if kind == type_value
    )
    account = _require_usable_account(account_code)
    equity = _require_usable_account(OPENING_EQUITY_ACCOUNT)
    posting_day = (
        posting_date
        if isinstance(posting_date, date_class)
        else _as_date(posting_date, "posting_date")
    )
    if number is None:
        number = next_document_number("JE", _jalali_year(posting_day))
    elif not isinstance(number, str) or not number.strip():
        raise PartyLedgerValidationError("Journal number must be text.")
    else:
        number = number.strip()
    label = f"Opening {type_value}: {resolved_party.name}"
    line_description = description.strip() or label
    party_leg = {
        "account": account, "description": line_description,
        "reference": reference.strip(),
    }
    equity_leg = {
        "account": equity, "description": line_description,
        "reference": reference.strip(),
    }
    if normal_balance_of(account) == "DEBIT":
        party_leg["debit"] = clean_amount
        equity_leg["credit"] = clean_amount
    else:
        equity_leg["debit"] = clean_amount
        party_leg["credit"] = clean_amount
    with transaction.atomic():
        entry = post_journal(
            number=number, posting_date=posting_day,
            description=line_description,
            lines=[party_leg, equity_leg],
            source_type=OPENING_SOURCE_TYPE, source_id=number,
            currency=resolved_currency, rate=rate, rate_date=rate_date,
            created_by=actor, idempotency_key=idempotency_key,
        )
        party_line = entry.lines.get(account__code=account_code)
        try:
            attribute_journal_line(
                party_line, party=resolved_party, user=actor)
        except PartyLedgerValidationError:
            # Idempotent retry: post_journal returned the ORIGINAL entry,
            # so its line is already attributed. Same party → success;
            # anything else → re-raise loudly (never silently merge).
            existing = getattr(
                party_line, "party_ledger_attribution", None)
            if existing is None or existing.party_id != resolved_party.pk:
                raise
    return entry
