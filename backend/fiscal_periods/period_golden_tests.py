"""Phase 3.1 — §12.9 fiscal period golden scenarios (G31-01..G31-10).

Every scenario prints its own evidence block (period rows, journals,
trial balance, audit trail, PASS/FAIL) and then asserts the same facts
it printed. Run with ``-s`` (or under ``manage.py test``) to see them.

Presentation helpers below are LOCAL and test-only (period rows differ
from journal rows); no business logic is duplicated from frozen modules.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounting.balances import account_balance, trial_balance
from accounting.coa import seed_chart_of_accounts
from accounting.models import (
    Account,
    JournalEntry,
    JournalStatus,
    PostedImmutabilityError,
)
from accounting.services import post_journal, reverse_journal
from currencies.models import Currency
from security.models import AuditAction, AuditEvent

from .models import FiscalPeriod, PeriodStatus
from .services import (
    PeriodValidationError,
    close_period,
    create_period,
    lock_period,
    reopen_period,
    unlock_period,
)

WIDTH = 66


def _fmt(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)


def golden_report(number, name, sections):
    out = ["=" * WIDTH, f"GOLDEN {number} — {name}", "=" * WIDTH]
    for heading, rows in sections:
        out.append("")
        out.append(heading)
        for label, value in rows:
            out.append(f"  {label:<30}{_fmt(value)}")
    text = "\n".join(out)
    print("\n" + text + "\n")
    return text


def period_rows(period, title="PERIOD"):
    return [
        (f"{title} Name", period.name),
        ("Range", f"{period.start_date} .. {period.end_date}"),
        ("Status", period.status),
        ("Closed At", period.closed_at or "-"),
    ]


def audit_rows(title="AUDIT TRAIL"):
    rows = [(title, "")]
    events = AuditEvent.objects.filter(entity="FiscalPeriod").order_by("id")
    for event in events:
        prev = (event.previous_state or {}).get("status", "-")
        new = (event.new_state or {}).get("status", "-")
        rows.append((
            f"#{event.id} {event.action} {prev}->{new}",
            f"user={event.user} reason={event.reason or '-'}",
        ))
    if not events:
        rows.append(("(no events)", ""))
    return rows


class PeriodGoldenFixture:
    def setUp(self):
        seed_chart_of_accounts()
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        self.user = get_user_model().objects.create_user("gold", password="x")
        self.n = 0

    def _post(self, posting_date, debit="100.00", credit="100.00", prefix="JE-G31"):
        self.n += 1
        return post_journal(
            number=f"{prefix}-{self.n:05d}", posting_date=posting_date,
            description="golden probe",
            lines=[
                {"account": Account.objects.get(code="1110"), "debit": debit},
                {"account": Account.objects.get(code="4110"), "credit": credit},
            ],
            currency=self.afn,
        )


class PeriodGoldenTests(PeriodGoldenFixture, TestCase):
    def test_g31_01_period_creation(self):
        period = create_period(
            name="FY 2026", start_date="2026-01-01", end_date="2026-12-31",
            user=self.user,
        )
        golden_report("G31-01", "Period creation", [
            ("INPUT", [("Name", "FY 2026"), ("Range", "2026-01-01 .. 2026-12-31")]),
            ("RESULT", period_rows(period) + [("Verdict", "PASS")]),
        ])
        self.assertEqual(period.status, PeriodStatus.OPEN)
        self.assertIsNone(period.closed_at)

    def test_g31_02_invalid_range_rejected(self):
        try:
            create_period(name="BAD", start_date="2026-12-31", end_date="2026-01-01")
            verdict = "FAIL: created"
        except PeriodValidationError as exc:
            verdict = f"PASS: rejected ({exc})"
        golden_report("G31-02", "Invalid range rejection", [
            ("INPUT", [("Range", "2026-12-31 .. 2026-01-01 (start > end)")]),
            ("RESULT", [("Periods in DB", FiscalPeriod.objects.count()), ("Verdict", verdict)]),
        ])
        self.assertEqual(FiscalPeriod.objects.count(), 0)
        self.assertTrue(verdict.startswith("PASS"))

    def test_g31_03_open_posting_allowed(self):
        period = create_period(
            name="FY 2026", start_date="2026-01-01", end_date="2026-12-31")
        entry = self._post("2026-05-05")
        result = trial_balance(date_to="2026-12-31")
        golden_report("G31-03", "OPEN posting allowed", [
            ("PERIOD", [(k, v) for k, v in period_rows(period)]),
            ("JOURNAL", [
                ("Number", entry.number), ("Posting Date", entry.posting_date),
                ("Status", entry.status),
                ("TOTAL DEBIT", entry.total_debit), ("TOTAL CREDIT", entry.total_credit),
            ]),
            ("TRIAL BALANCE", [
                ("Total Debit", result["total_debit"]), ("Total Credit", result["total_credit"]),
                ("Difference", result["difference"]), ("Balanced", result["balanced"]),
            ]),
            ("RESULT", [("Verdict", "PASS")]),
        ])
        self.assertEqual(entry.status, JournalStatus.POSTED)
        self.assertTrue(result["balanced"])

    def test_g31_04_closed_rejection(self):
        period = create_period(
            name="FY 2026", start_date="2026-01-01", end_date="2026-12-31")
        close_period(period, user=self.user, reason="year-end")
        before = JournalEntry.objects.count()
        try:
            self._post("2026-05-05")
            verdict = "FAIL: posted into CLOSED"
        except PeriodValidationError as exc:
            verdict = f"PASS: rejected ({exc})"
        after = JournalEntry.objects.count()
        golden_report("G31-04", "CLOSED rejection", [
            ("PERIOD", period_rows(FiscalPeriod.objects.get(pk=period.pk))),
            ("ATTEMPT", [("Posting Date", "2026-05-05")]),
            ("RESULT", [
                ("Entries Before/After", f"{before}/{after}"),
                ("Verdict", verdict if after == before else "FAIL: row leaked"),
            ]),
        ])
        self.assertEqual(after, before)
        self.assertTrue(verdict.startswith("PASS"))

    def test_g31_05_locked_rejection(self):
        period = create_period(
            name="FY 2026", start_date="2026-01-01", end_date="2026-12-31")
        lock_period(period, user=self.user, reason="freeze")
        try:
            self._post("2026-05-05")
            verdict = "FAIL: posted into LOCKED"
        except PeriodValidationError as exc:
            verdict = f"PASS: rejected ({exc})"
        golden_report("G31-05", "LOCKED rejection", [
            ("PERIOD", period_rows(FiscalPeriod.objects.get(pk=period.pk))),
            ("RESULT", [("Entries in DB", JournalEntry.objects.count()), ("Verdict", verdict)]),
        ])
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertTrue(verdict.startswith("PASS"))

    def test_g31_06_full_lifecycle_with_audit(self):
        period = create_period(
            name="FY 2026", start_date="2026-01-01", end_date="2026-12-31",
            user=self.user)
        close_period(period, user=self.user, reason="year-end")
        reopen_period(period, user=self.user, reason="correction")
        lock_period(period, user=self.user, reason="freeze")
        unlock_period(period, user=self.user, reason="adjust")
        final = FiscalPeriod.objects.get(pk=period.pk)
        golden_report("G31-06", "Full lifecycle with audit", [
            ("FINAL", period_rows(final)),
            ("TRAIL", audit_rows()),
            ("RESULT", [("Verdict", "PASS")]),
        ])
        self.assertEqual(final.status, PeriodStatus.OPEN)
        actions = list(
            AuditEvent.objects.filter(entity="FiscalPeriod").order_by("id")
            .values_list("action", flat=True)
        )
        self.assertEqual(actions, [AuditAction.CREATE] + [AuditAction.UPDATE] * 4)

    def test_g31_07_reopen_preserves_immutability(self):
        period = create_period(
            name="FY 2026", start_date="2026-01-01", end_date="2026-12-31")
        entry = self._post("2026-04-04")
        close_period(period, user=self.user)
        reopen_period(period, user=self.user, reason="new business")
        entry.description = "sneaky edit"
        try:
            entry.save()
            verdict = "FAIL: posted edit allowed"
        except PostedImmutabilityError as exc:
            verdict = f"PASS: rejected ({exc})"
        golden_report("G31-07", "Reopen preserves immutability", [
            ("PERIOD", period_rows(FiscalPeriod.objects.get(pk=period.pk))),
            ("ATTEMPT", [("Action", "edit POSTED journal after reopen")]),
            ("RESULT", [
                ("Stored Description", JournalEntry.objects.get(pk=entry.pk).description),
                ("Verdict", verdict),
            ]),
        ])
        self.assertTrue(verdict.startswith("PASS"))

    def test_g31_08_backdated_posting(self):
        create_period(name="FY 2026", start_date="2026-01-01", end_date="2026-12-31")
        entry = self._post("2026-02-02")
        bal = account_balance(Account.objects.get(code="1110"), date_to="2026-12-31")
        golden_report("G31-08", "Backdated posting into OPEN", [
            ("JOURNAL", [
                ("Number", entry.number), ("Posting Date", entry.posting_date),
                ("Status", entry.status),
            ]),
            ("BALANCE 1110 AS OF 2026-12-31", [
                ("Total Debit", bal["total_debit"]), ("Total Credit", bal["total_credit"]),
                ("Balance", bal["balance"]),
            ]),
            ("RESULT", [("Verdict", "PASS")]),
        ])
        self.assertEqual(entry.status, JournalStatus.POSTED)
        self.assertEqual(bal["balance"], Decimal("100.00"))

    def test_g31_09_close_failure_on_tampered_totals(self):
        period = create_period(
            name="FY 2026", start_date="2026-01-01", end_date="2026-12-31")
        entry = self._post("2026-04-04")
        JournalEntry.objects.filter(pk=entry.pk).update(total_debit=Decimal("1.00"))
        try:
            close_period(period, user=self.user)
            verdict = "FAIL: closed over corruption"
        except PeriodValidationError as exc:
            verdict = f"PASS: rejected ({exc})"
        fresh = FiscalPeriod.objects.get(pk=period.pk)
        golden_report("G31-09", "Close failure (detect→report→reject)", [
            ("TAMPER", [("Journal", entry.number), ("Stored Debit Now", "1.00 (was 100.00)")]),
            ("CLOSE ATTEMPT", [("Verdict", verdict)]),
            ("STATE AFTER", period_rows(fresh) + [
                ("Stored Debit Still", JournalEntry.objects.get(pk=entry.pk).total_debit),
            ]),
            ("RESULT", [("Verdict", verdict if fresh.status == "OPEN" else "FAIL: mutated")]),
        ])
        self.assertEqual(fresh.status, PeriodStatus.OPEN)
        self.assertTrue(verdict.startswith("PASS"))

    def test_g31_10_historical_balance_as_of_date(self):
        create_period(name="FY 2026", start_date="2026-01-01", end_date="2026-12-31")
        self._post("2026-03-03")
        early = account_balance(Account.objects.get(code="1110"), date_to="2026-02-01")
        later = account_balance(Account.objects.get(code="1110"), date_to="2026-12-31")
        golden_report("G31-10", "Historical balance as-of-date", [
            ("JOURNAL", [("Posting Date", "2026-03-03"), ("Amount", "100.00")]),
            ("BALANCE AS OF 2026-02-01", [("Balance", early["balance"]), ("Lines", early["lines_count"])]),
            ("BALANCE AS OF 2026-12-31", [("Balance", later["balance"]), ("Lines", later["lines_count"])]),
            ("RESULT", [("Verdict", "PASS")]),
        ])
        self.assertEqual(early["balance"], Decimal("0"))
        self.assertEqual(later["balance"], Decimal("100.00"))

    def test_g31_11_reopen_then_reverse_correction_flow(self):
        period = create_period(
            name="FY 2026", start_date="2026-01-01", end_date="2026-12-31")
        entry = self._post("2026-04-04")
        close_period(period, user=self.user)
        try:
            reverse_journal(entry, "too early", self.user)
            direct = "FAIL: reversed into CLOSED"
        except PeriodValidationError:
            direct = "PASS: direct reversal rejected"
        reopen_period(period, user=self.user, reason="error found")
        reversal = reverse_journal(entry, "wrong amount", self.user)
        golden_report("G31-11", "Reopen→reverse correction flow", [
            ("DIRECT REVERSAL INTO CLOSED", [("Verdict", direct)]),
            ("AFTER REOPEN", [
                ("Reversal Number", reversal.number),
                ("Reversal Date", reversal.posting_date),
                ("Original Status", JournalEntry.objects.get(pk=entry.pk).status),
            ]),
            ("RESULT", [("Verdict", "PASS" if direct.startswith("PASS") else "FAIL")]),
        ])
        self.assertTrue(direct.startswith("PASS"))
        self.assertEqual(reversal.status, JournalStatus.POSTED)
