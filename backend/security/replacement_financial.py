"""Local read-only financial report for an unpublished replacement database.

Not a posting engine, source snapshot, proof of physical custody, or permission
to publish. Existing AVCO and party reconciliation contracts remain authoritative.
"""
from collections import defaultdict
from decimal import Decimal, localcontext
from types import SimpleNamespace

from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Sum

from accounting.balances import EFFECTIVE_STATUSES, normal_balance_of
from accounting.models import JournalLine
from core.money import line_total
from inventory.models import StockMovement
from inventory.stock import avco_for
from party_ledger.ledger import reconcile_party_ledger
from party_ledger.models import PARTY_LEDGER_ACCOUNTS
from security.audit_chain import assert_audit_trigger_schema, has_verified_replacement_preparation
from security.emergency_owner_key_service import get_current_gm_for_local_operation
from security.mfa_models import SecurityLoginSession
from security.recovery_readiness import RecoveryReconciliationError
from security.replacement_identity import _require_staging


def _money(value):
    if not isinstance(value, Decimal) or not value.is_finite():
        raise RecoveryReconciliationError("non-decimal financial report value")
    return format(value, ".2f")


def _totals(debit, credit, normal):
    return {"debit": _money(debit), "credit": _money(credit),
            "balance": _money(debit - credit if normal == "DEBIT" else credit - debit)}


def collect_replacement_financial_report(*, source_isolated, expected_report=None):
    """Read prepared staging data; optionally compare an independent report.

    The expected report, if supplied, must be the full same-schema business
    report independently retained at the selected recovery point. Comparing
    a newly computed report to itself is NOT independent evidence.
    """
    _require_staging(source_isolated)
    with transaction.atomic(), localcontext() as ctx:
        ctx.prec = 60
        gm = get_current_gm_for_local_operation().user
        assert_audit_trigger_schema()
        if not has_verified_replacement_preparation(gm):
            raise RecoveryReconciliationError("replacement identity preparation is not verified")
        if SecurityLoginSession.objects.filter(revoked_at__isnull=True).exists() or Session.objects.exists():
            raise RecoveryReconciliationError("replacement report requires no historical or live sessions")

        accounts = defaultdict(lambda: [Decimal("0"), Decimal("0"), 0])
        parties = defaultdict(lambda: [Decimal("0"), Decimal("0"), 0])
        currency_totals = defaultdict(lambda: [Decimal("0"), Decimal("0")])
        unknown = unattributed = 0
        lines = JournalLine.objects.filter(entry__status__in=EFFECTIVE_STATUSES).order_by("pk").values_list(
            "entry__currency__code", "account__code", "account__account_type",
            "debit", "credit", "party_ledger_attribution__party_id",
        )
        for currency, code, kind, debit, credit, party_id in lines.iterator(chunk_size=1000):
            if currency is None:
                unknown += 1
            totals = accounts[currency, code, kind]
            totals[0] += debit
            totals[1] += credit
            totals[2] += 1
            currency_totals[currency][0] += debit
            currency_totals[currency][1] += credit
            if code in PARTY_LEDGER_ACCOUNTS:
                if party_id is None:
                    unattributed += 1
                else:
                    totals = parties[currency, code, kind, party_id]
                    totals[0] += debit
                    totals[1] += credit
                    totals[2] += 1
            elif party_id is not None:
                raise RecoveryReconciliationError("unexpected party attribution account")

        def order(key):
            return (key[0] is None, key[0] or "", *key[1:])

        trial = []
        for currency in sorted(currency_totals, key=lambda c: (c is None, c or "")):
            debit, credit = currency_totals[currency]
            if debit != credit:
                raise RecoveryReconciliationError("currency-separated trial balance is not balanced")
            trial.append({"currency": currency, "debit": _money(debit), "credit": _money(credit)})
        account_rows = []
        for (currency, code, kind), (debit, credit, count) in sorted(accounts.items(), key=lambda item: order(item[0])):
            normal = normal_balance_of(SimpleNamespace(code=code, account_type=kind))
            account_rows.append({"currency": currency, "account_code": code, "normal_balance": normal,
                                 **_totals(debit, credit, normal), "line_count": count})
        party_rows = []
        for (currency, code, kind, party_id), (debit, credit, count) in sorted(parties.items(), key=lambda item: order(item[0])):
            normal = normal_balance_of(SimpleNamespace(code=code, account_type=kind))
            party_rows.append({"currency": currency, "party_id": party_id,
                               "balance_type": str(PARTY_LEDGER_ACCOUNTS[code]),
                               **_totals(debit, credit, normal), "line_count": count})
        controls = []
        for currency in sorted(c for c in currency_totals if c is not None):
            canonical = reconcile_party_ledger(currency=currency)
            controls.append({"currency": currency, "reconciled": canonical["reconciled"],
                             "accounts": [{k: _money(v) if isinstance(v, Decimal) else v
                                           for k, v in row.items()} for row in canonical["accounts"]]})

        stock_rows = []
        stock = StockMovement.objects.values("product_id", "warehouse_id").annotate(
            quantity=Sum("quantity")
        ).order_by("product_id", "warehouse_id")
        for row in stock:
            quantity = int(row["quantity"])
            average = avco_for(row["product_id"], row["warehouse_id"])
            if quantity > 0 and average is None or quantity <= 0 and average is not None:
                raise RecoveryReconciliationError("stock quantity and canonical AVCO are inconsistent")
            stock_rows.append({"product_id": row["product_id"], "warehouse_id": row["warehouse_id"],
                               "quantity": quantity,
                               "avco_afn": None if average is None else format(average, ".4f"),
                               # This is an extension of rounded AVCO, not the
                               # exact accounting carrying basis or GL tie-out.
                               "rounded_avco_extension_afn": None if average is None else _money(line_total(quantity, average))})

        report = {"schema": "hesabdari.replacement-financial.v1",
                  "trial_by_currency": trial, "account_balances": account_rows,
                  "party_balances": party_rows, "party_control_totals": controls,
                  "stock_and_avco": stock_rows,
                  "unknown_currency_lines": unknown, "unattributed_party_lines": unattributed}
        if expected_report is not None and expected_report != report:
            raise RecoveryReconciliationError("replacement financial report differs from independent report")
        return report
