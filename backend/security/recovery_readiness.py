"""Read-only recovery rehearsal checks; no ORM, credentials, or activation.

Run against the already authenticated disposable restore only. No queries in
normal transaction paths and no alternate accounting posting formulas.
"""
from decimal import Decimal, InvalidOperation, localcontext

from accounting.models import IMMUTABLE_JOURNAL_STATUSES
from inventory.models import IN_MOVEMENT_TYPES, OUT_MOVEMENT_TYPES
from party_ledger.models import PARTY_LEDGER_ACCOUNTS
from security.backup_service import BackupError


class RecoveryReconciliationError(BackupError):
    """Restored business data does not satisfy a checked invariant."""


def _money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
            raise ValueError
        return amount
    except (InvalidOperation, TypeError, ValueError):
        raise RecoveryReconciliationError("invalid stored journal amount") from None


def inspect_disposable_recovery(cursor):
    """Reconcile posted journals and stock snapshots; report remaining security work.

    Currency totals are not combined. No names, individual balances, password
    hashes, MFA secrets, session keys, or recovery-code material are returned.
    """
    posted = set(IMMUTABLE_JOURNAL_STATUSES)
    cursor.execute(
        "SELECT e.id, e.status, e.total_debit, e.total_credit, l.id, "
        "l.debit, l.credit FROM accounting_journalentry e "
        "LEFT JOIN accounting_journalline l ON l.entry_id=e.id "
        "ORDER BY e.id,l.id"
    )
    checked_entries = checked_lines = 0
    current = None
    with localcontext() as ctx:
        ctx.prec = 60
        def check_entry(header, debit, credit, count):
            if header is None:
                return
            if count < 2 or debit <= 0 or debit != credit or (debit, credit) != header:
                raise RecoveryReconciliationError("posted journal totals do not match balanced lines")
        for entry_id, status, header_debit, header_credit, line_id, d, c in cursor:
            if status not in posted:
                continue
            if entry_id != current:
                if current is not None:
                    check_entry(header, debit, credit, count)
                current = entry_id
                header = (_money(header_debit), _money(header_credit))
                debit = credit = Decimal("0")
                count = 0
                checked_entries += 1
            if line_id is not None:
                d, c = _money(d), _money(c)
                if not ((d > 0 and c == 0) or (c > 0 and d == 0)):
                    raise RecoveryReconciliationError("posted journal line is not one-sided positive")
                debit += d
                credit += c
                count += 1
                checked_lines += 1
        if current is not None:
            check_entry(header, debit, credit, count)

    cursor.execute(
        "SELECT product_id, warehouse_id, movement_type, quantity, qty_before, qty_after "
        "FROM inventory_stockmovement ORDER BY product_id,warehouse_id,id"
    )
    stock_groups = stock_rows = 0
    previous_group = None
    balance = 0
    for product, warehouse, kind, quantity, before, after in cursor:
        group = (product, warehouse)
        if group != previous_group:
            stock_groups += 1
            previous_group = group
            balance = 0
        if (kind not in IN_MOVEMENT_TYPES and kind not in OUT_MOVEMENT_TYPES
                or kind in IN_MOVEMENT_TYPES and quantity <= 0
                or kind in OUT_MOVEMENT_TYPES and quantity >= 0
                or before != balance or after != before + quantity):
            raise RecoveryReconciliationError("stock movement direction or running quantity is inconsistent")
        balance = after
        stock_rows += 1

    cursor.execute(
        "SELECT e.status,a.code FROM party_ledger_partyledgerattribution p "
        "JOIN accounting_journalline l ON l.id=p.journal_line_id "
        "JOIN accounting_journalentry e ON e.id=l.entry_id "
        "JOIN accounting_account a ON a.id=l.account_id"
    )
    attributions = 0
    for status, code in cursor:
        if status not in posted or code not in PARTY_LEDGER_ACCOUNTS:
            raise RecoveryReconciliationError("party ledger attribution references an invalid journal line")
        attributions += 1

    # Counts expose work still required without releasing credentials or PII.
    counts = {}
    for name, sql in (
        ("historical_registry_sessions", "SELECT COUNT(*) FROM security_securityloginsession WHERE revoked_at IS NULL"),
        ("django_session_rows", "SELECT COUNT(*) FROM django_session"),
        ("active_mfa_devices", "SELECT COUNT(*) FROM security_securitymfadevice WHERE status='ACTIVE'"),
        ("pending_mfa_devices", "SELECT COUNT(*) FROM security_securitymfadevice WHERE status='PENDING'"),
        ("required_employee_mfa_policies", "SELECT COUNT(*) FROM security_securitymfarequirement WHERE is_required"),
        ("unretired_recovery_codes", "SELECT COUNT(*) FROM security_securityrecoverycode WHERE used_at IS NULL"),
        ("live_owner_key_rows", "SELECT COUNT(*) FROM security_securityemergencyownerkey WHERE consumed_at IS NULL AND revoked_at IS NULL"),
        ("cash_account_masters", "SELECT COUNT(*) FROM cash_accounts_cashaccount"),
        ("idempotency_records", "SELECT COUNT(*) FROM core_idempotencyrecord"),
    ):
        cursor.execute(sql)
        counts[name] = cursor.fetchone()[0]
    return {
        "posted_or_reversed_journals": checked_entries,
        "checked_journal_lines": checked_lines,
        "checked_stock_movements": stock_rows,
        "stock_product_warehouse_groups": stock_groups,
        "checked_party_attributions": attributions,
        **counts,
    }
