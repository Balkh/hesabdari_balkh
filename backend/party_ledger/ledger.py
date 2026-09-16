"""Party Ledger derivation (Phase 5 — read-only, OD-5-04 A).

Every balance derives from POSTED/REVERSED journal lines plus immutable
attribution. NOTHING here mutates, stores, or caches a financial
balance. Ordering reuses ``CHRONOLOGY_ORDER`` (posting date → journal
number → entry id, §2.8); signs reuse ``normal_balance_of``; the
(P, C, T) identity is enforced by requiring currency + type on every
balance call (§6/§26 — merging is refused, never silent).
"""

from decimal import Decimal

from accounting.balances import (
    CHRONOLOGY_ORDER,
    EFFECTIVE_STATUSES,
    normal_balance_of,
)
from accounting.models import Account, JournalLine
from accounting.services import _as_date

from .models import PARTY_LEDGER_ACCOUNTS, BalanceType
from .services import PartyLedgerValidationError, resolve_currency
from .services import resolve_party as _resolve_party_ledger


def _coerce_type(value):
    if isinstance(value, BalanceType):
        return str(value)
    if isinstance(value, str) and value in BalanceType.values:
        return value
    raise PartyLedgerValidationError(
        "Balance type must be one of RECEIVABLE, PAYABLE, "
        "CUSTOMER_CREDIT, SUPPLIER_ADVANCE."
    )


def _account_for_type(type_value):
    code = next(
        c for c, kind in PARTY_LEDGER_ACCOUNTS.items() if kind == type_value
    )
    try:
        return Account.objects.get(code=code)
    except Account.DoesNotExist as exc:
        raise PartyLedgerValidationError(
            f"Account {code} does not exist; seed the canonical COA."
        ) from exc


def _signed_for(normal, debit, credit):
    if normal == "DEBIT":
        return debit - credit
    return credit - debit


def _attributed_lines(party, currency, type_value, date_from=None,
                      date_to=None):
    account_code = next(
        c for c, kind in PARTY_LEDGER_ACCOUNTS.items() if kind == type_value
    )
    lines = (
        JournalLine.objects.filter(
            entry__status__in=EFFECTIVE_STATUSES,
            account__code=account_code,
            entry__currency=currency,
            party_ledger_attribution__party=party,
        )
        .select_related("entry", "entry__currency", "account")
    )
    if date_from is not None:
        lines = lines.filter(entry__posting_date__gte=date_from)
    if date_to is not None:
        lines = lines.filter(entry__posting_date__lte=date_to)
    return lines.order_by(
        "entry__posting_date", "entry__number", "entry__id", "id"
    )


def party_balance(party, *, currency, balance_type, date_to=None):
    """Signed balance for one (Party, Currency, Balance Type) identity.

    Currency and type are REQUIRED — merging is refused, never silent.
    """
    resolved_party = _resolve_party_ledger(party)
    resolved_currency = resolve_currency(currency)
    type_value = _coerce_type(balance_type)
    end = _as_date(date_to, "date_to") if date_to is not None else None
    account = _account_for_type(type_value)
    normal = normal_balance_of(account)
    lines = list(_attributed_lines(
        resolved_party, resolved_currency, type_value, date_to=end
    ))
    debit = sum((line.debit for line in lines), Decimal("0"))
    credit = sum((line.credit for line in lines), Decimal("0"))
    return {
        "party_id": resolved_party.pk,
        "party_name": resolved_party.name,
        "currency": resolved_currency.code,
        "balance_type": type_value,
        "account_code": account.code,
        "normal_balance": normal,
        "total_debit": debit,
        "total_credit": credit,
        "balance": _signed_for(normal, debit, credit),
        "lines_count": len(lines),
        "date_to": end,
    }


def party_statement(party, *, currency, balance_type, date_from=None,
                    date_to=None):
    """Read-only statement: derived opening + ordered rows + running balance.

    Opening/previous balance is itself derived (§2.7): the signed balance
    of attributed lines strictly before ``date_from``. Running balance is
    calculated, never stored (§21).
    """
    resolved_party = _resolve_party_ledger(party)
    resolved_currency = resolve_currency(currency)
    type_value = _coerce_type(balance_type)
    start = _as_date(date_from, "date_from") if date_from is not None else None
    end = _as_date(date_to, "date_to") if date_to is not None else None
    if start is not None and end is not None and start > end:
        raise PartyLedgerValidationError("date_from cannot be after date_to.")
    account = _account_for_type(type_value)
    normal = normal_balance_of(account)
    opening = Decimal("0")
    if start is not None:
        earlier = _attributed_lines(
            resolved_party, resolved_currency, type_value
        ).filter(entry__posting_date__lt=start)
        for line in earlier:
            opening += _signed_for(normal, line.debit, line.credit)
    rows = []
    running = opening
    for line in _attributed_lines(
        resolved_party, resolved_currency, type_value,
        date_from=start, date_to=end,
    ):
        running += _signed_for(normal, line.debit, line.credit)
        entry = line.entry
        rows.append({
            "posting_date": entry.posting_date,
            "journal_number": entry.number,
            "journal_entry_id": entry.pk,
            "journal_line_id": line.pk,
            "description": line.description or entry.description,
            "reference": line.reference,
            "source_type": entry.source_type,
            "source_id": entry.source_id,
            "account_code": account.code,
            "debit": line.debit,
            "credit": line.credit,
            "running_balance": running,
        })
    return {
        "party_id": resolved_party.pk,
        "party_name": resolved_party.name,
        "currency": resolved_currency.code,
        "balance_type": type_value,
        "account_code": account.code,
        "normal_balance": normal,
        "opening_balance": opening,
        "closing_balance": running,
        "lines": rows,
        "lines_count": len(rows),
        "date_from": start,
        "date_to": end,
        "chronology": list(CHRONOLOGY_ORDER) + ["line_id"],
    }


def net_position(party, *, currency, side):
    """Contract net position (§2.3/§2.4): gross − contra, same currency.

    CUSTOMER: Receivable − Customer Credit (>0 → customer owes → DEBTOR).
    SUPPLIER: Payable − Supplier Advance (>0 → we owe → CREDITOR).
    No cross-category netting exists (§25).
    """
    if side == "CUSTOMER":
        gross_type, contra_type = (
            BalanceType.RECEIVABLE, BalanceType.CUSTOMER_CREDIT)
        debtor_when_positive = True
    elif side == "SUPPLIER":
        gross_type, contra_type = (
            BalanceType.PAYABLE, BalanceType.SUPPLIER_ADVANCE)
        debtor_when_positive = False
    else:
        raise PartyLedgerValidationError("Side must be CUSTOMER or SUPPLIER.")
    gross = party_balance(
        party, currency=currency, balance_type=gross_type)["balance"]
    contra = party_balance(
        party, currency=currency, balance_type=contra_type)["balance"]
    net = gross - contra
    if net == 0:
        status = "ZERO"
    elif (net > 0) == debtor_when_positive:
        status = "DEBTOR"
    else:
        status = "CREDITOR"
    resolved_currency = resolve_currency(currency)
    resolved_party = _resolve_party_ledger(party)
    return {
        "party_id": resolved_party.pk,
        "party_name": resolved_party.name,
        "currency": resolved_currency.code,
        "side": side,
        "gross": gross,
        "contra": contra,
        "net": net,
        "status": status,
    }


def reconcile_party_ledger(*, currency):
    """Party derivation ↔ GL control accounts, per currency (§37).

    For each of 1310/2110/2200/1500: GL sums over ALL effective lines vs
    sums over ATTRIBUTED lines. Legacy unattributed lines are reported
    explicitly (§43) — never assigned, never hidden. ``reconciled`` is
    true only when nothing is unattributed.
    """
    resolved_currency = resolve_currency(currency)
    accounts = []
    for code in sorted(PARTY_LEDGER_ACCOUNTS):
        gl_lines = JournalLine.objects.filter(
            entry__status__in=EFFECTIVE_STATUSES,
            account__code=code, entry__currency=resolved_currency,
        )
        attributed = gl_lines.filter(
            party_ledger_attribution__isnull=False)
        gl_debit = sum((d for d in
                        gl_lines.values_list("debit", flat=True)),
                       Decimal("0"))
        gl_credit = sum((c for c in
                         gl_lines.values_list("credit", flat=True)),
                        Decimal("0"))
        attr_debit = sum((d for d in
                          attributed.values_list("debit", flat=True)),
                         Decimal("0"))
        attr_credit = sum((c for c in
                           attributed.values_list("credit", flat=True)),
                          Decimal("0"))
        unattributed_count = gl_lines.filter(
            party_ledger_attribution__isnull=True).count()
        accounts.append({
            "account_code": code,
            "balance_type": PARTY_LEDGER_ACCOUNTS[code],
            "gl_debit": gl_debit,
            "gl_credit": gl_credit,
            "attributed_debit": attr_debit,
            "attributed_credit": attr_credit,
            "unattributed_debit": gl_debit - attr_debit,
            "unattributed_credit": gl_credit - attr_credit,
            "unattributed_lines": unattributed_count,
        })
    reconciled = all(
        row["unattributed_debit"] == 0
        and row["unattributed_credit"] == 0
        for row in accounts
    )
    return {
        "currency": resolved_currency.code,
        "accounts": accounts,
        "reconciled": reconciled,
    }
