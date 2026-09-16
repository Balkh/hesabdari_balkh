"""Phase 3.1 — fiscal period unit + integration tests.

Covers: period creation/validation, no-overlap, the single posting-date
gate (via the REAL post_journal/reverse_journal path), lifecycle
transitions, reopen/unlock authorization + audit, atomic close with
integrity validation, idempotent repeats, backdating, and posted
immutability after reopen. Printed golden scenarios live in
period_golden_tests.py; frozen Phase 2 tests are untouched.
"""

from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from accounting.balances import account_balance, trial_balance
from accounting.coa import seed_chart_of_accounts
from accounting.models import (
    Account,
    JournalEntry,
    JournalLine,
    JournalStatus,
    PostedImmutabilityError,
)
from accounting.services import post_journal, reverse_journal
from core.dates import gregorian_to_jalali
from currencies.models import Currency
from security.models import AuditAction, AuditEvent

from .models import FiscalPeriod, PeriodStatus
from .services import (
    PeriodValidationError,
    assert_posting_date_open,
    close_period,
    create_period,
    find_period_for_date,
    lock_period,
    reopen_period,
    unlock_period,
)


class PeriodFixture:
    def setUp(self):
        seed_chart_of_accounts()
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        self.user = get_user_model().objects.create_user("p3user", password="x")
        self.n = 0

    def _number(self, prefix="JE-P3"):
        self.n += 1
        return f"{prefix}-{self.n:05d}"

    def _post(self, posting_date, number=None, **kwargs):
        params = dict(
            number=number or self._number(),
            posting_date=posting_date,
            description="period probe",
            lines=[
                {"account": Account.objects.get(code="1110"), "debit": "100.00"},
                {"account": Account.objects.get(code="4110"), "credit": "100.00"},
            ],
            currency=self.afn,
        )
        params.update(kwargs)
        return post_journal(**params)

    def _period(self, name="FY 2026", start="2026-01-01", end="2026-12-31", **kwargs):
        return create_period(name=name, start_date=start, end_date=end, **kwargs)


class PeriodCreationTests(PeriodFixture, TestCase):
    def test_create_valid_period_is_open_by_default(self):
        period = self._period(user=self.user)
        self.assertEqual(period.status, PeriodStatus.OPEN)
        self.assertIsNone(period.closed_at)
        self.assertEqual(period.start_date, date(2026, 1, 1))
        self.assertEqual(period.end_date, date(2026, 12, 31))
        event = AuditEvent.objects.get(action=AuditAction.CREATE, entity="FiscalPeriod")
        self.assertEqual(event.user, self.user)
        self.assertIsNone(event.previous_state)
        self.assertEqual(event.new_state["status"], "OPEN")
        self.assertEqual(event.entity_id, str(period.id))

    def test_create_rejects_start_after_end(self):
        with self.assertRaises(PeriodValidationError):
            self._period(start="2026-12-31", end="2026-01-01")
        self.assertEqual(FiscalPeriod.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_create_rejects_blank_name(self):
        for bad in ("", "   "):
            with self.subTest(name=repr(bad)):
                with self.assertRaises(PeriodValidationError):
                    self._period(name=bad)
        self.assertEqual(FiscalPeriod.objects.count(), 0)

    def test_create_rejects_overlap(self):
        self._period(name="H1", start="2026-01-01", end="2026-06-30")
        clashes = [
            ("same", "2026-01-01", "2026-06-30"),
            ("inner", "2026-02-01", "2026-03-31"),
            ("outer", "2025-01-01", "2026-12-31"),
            ("left", "2025-06-01", "2026-02-01"),
            ("right", "2026-06-01", "2026-09-01"),
            ("single-day-touch", "2026-06-30", "2026-06-30"),
        ]
        for label, start, end in clashes:
            with self.subTest(label):
                with self.assertRaises(PeriodValidationError):
                    self._period(name=label, start=start, end=end)
        self.assertEqual(FiscalPeriod.objects.count(), 1)

    def test_create_allows_adjacent_periods(self):
        first = self._period(name="H1", start="2026-01-01", end="2026-06-30")
        second = self._period(name="H2", start="2026-07-01", end="2026-12-31")
        self.assertEqual(FiscalPeriod.objects.count(), 2)
        self.assertEqual(find_period_for_date("2026-06-30"), first)
        self.assertEqual(find_period_for_date("2026-07-01"), second)

    def test_create_accepts_dates_and_iso_strings(self):
        by_date = self._period(name="D", start=date(2026, 1, 1), end=date(2026, 1, 31))
        by_str = self._period(name="S", start="2026-02-01", end="2026-02-28")
        self.assertEqual((by_date.start_date, by_str.start_date), (date(2026, 1, 1), date(2026, 2, 1)))

    def test_create_rejects_bad_input_types(self):
        with self.assertRaises(PeriodValidationError):
            self._period(start="not-a-date")
        with self.assertRaises(PeriodValidationError):
            create_period(name="X", start_date="2026-01-01", end_date="2026-01-31", user="nobody")
        self.assertEqual(FiscalPeriod.objects.count(), 0)

    def test_db_check_constraint_enforced(self):
        with self.assertRaises(IntegrityError):
            FiscalPeriod.objects.create(
                name="raw", start_date=date(2026, 2, 1), end_date=date(2026, 1, 1)
            )


class PeriodGateTests(PeriodFixture, TestCase):
    def test_bootstrap_no_periods_posting_allowed(self):
        self.assertIsNone(find_period_for_date("2026-05-05"))
        self.assertIsNone(assert_posting_date_open("2026-05-05"))
        entry = self._post("2026-05-05")
        self.assertEqual(entry.status, JournalStatus.POSTED)

    def test_open_period_allows_posting(self):
        period = self._period()
        self.assertEqual(assert_posting_date_open("2026-05-05"), period)
        self.assertEqual(assert_posting_date_open(date(2026, 12, 31)), period)
        entry = self._post("2026-05-05")
        self.assertEqual(entry.status, JournalStatus.POSTED)

    def test_closed_period_rejects_posting(self):
        period = self._period()
        close_period(period, user=self.user, reason="year-end")
        with self.assertRaises(PeriodValidationError) as ctx:
            assert_posting_date_open("2026-05-05")
        self.assertIn("CLOSED", str(ctx.exception))
        with self.assertRaises(PeriodValidationError):
            self._post("2026-05-05")
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_locked_period_rejects_posting(self):
        period = self._period()
        lock_period(period, user=self.user)
        with self.assertRaises(PeriodValidationError) as ctx:
            assert_posting_date_open("2026-05-05")
        self.assertIn("LOCKED", str(ctx.exception))
        with self.assertRaises(PeriodValidationError):
            self._post("2026-05-05")
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_uncovered_date_rejects_once_periods_exist(self):
        self._period(start="2026-01-01", end="2026-06-30")
        with self.assertRaises(PeriodValidationError) as ctx:
            self._post("2026-09-09")
        self.assertIn("No fiscal period covers posting date", str(ctx.exception))
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_ambiguous_resolution_raises_never_guesses(self):
        FiscalPeriod.objects.create(name="A", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        FiscalPeriod.objects.create(name="B", start_date=date(2026, 6, 1), end_date=date(2026, 6, 30))
        with self.assertRaises(PeriodValidationError) as ctx:
            find_period_for_date("2026-06-15")
        self.assertIn("Ambiguous", str(ctx.exception))

    def test_gate_rejects_invalid_date_input(self):
        with self.assertRaises(PeriodValidationError):
            assert_posting_date_open("not-a-date")
        with self.assertRaises(PeriodValidationError):
            find_period_for_date(None)


class PeriodLifecycleTests(PeriodFixture, TestCase):
    def test_open_to_closed_success(self):
        period = self._period()
        self._post("2026-03-03")
        closed = close_period(period, user=self.user, reason="year-end close")
        self.assertEqual(closed.status, PeriodStatus.CLOSED)
        self.assertTrue(timezone.is_aware(closed.closed_at))
        event = AuditEvent.objects.get(action=AuditAction.UPDATE, entity="FiscalPeriod")
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.reason, "year-end close")
        self.assertEqual(event.previous_state["status"], "OPEN")
        self.assertEqual(event.new_state["status"], "CLOSED")
        self.assertEqual(event.new_state["journals_verified"], 1)
        self.assertTrue(timezone.is_aware(event.created_at))

    def test_open_to_locked_success(self):
        period = self._period()
        locked = lock_period(period, user=self.user, reason="freeze")
        self.assertEqual(locked.status, PeriodStatus.LOCKED)
        self.assertIsNone(locked.closed_at)
        event = AuditEvent.objects.get(action=AuditAction.UPDATE)
        self.assertEqual((event.previous_state["status"], event.new_state["status"]), ("OPEN", "LOCKED"))

    def test_closed_to_open_requires_user_and_reason(self):
        period = close_period(self._period(), user=self.user)
        with self.assertRaises(PeriodValidationError):
            reopen_period(period, user=None, reason="fix")
        with self.assertRaises(PeriodValidationError):
            reopen_period(period, user=self.user, reason="  ")
        reopened = reopen_period(period, user=self.user, reason="correction needed")
        self.assertEqual(reopened.status, PeriodStatus.OPEN)
        self.assertIsNone(reopened.closed_at)
        event = AuditEvent.objects.filter(entity="FiscalPeriod").order_by("id").last()
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.reason, "correction needed")
        self.assertEqual((event.previous_state["status"], event.new_state["status"]), ("CLOSED", "OPEN"))

    def test_locked_to_open_requires_user_and_reason(self):
        period = lock_period(self._period(), user=self.user)
        with self.assertRaises(PeriodValidationError):
            unlock_period(period, user=None, reason="fix")
        with self.assertRaises(PeriodValidationError):
            unlock_period(period, user=self.user, reason="")
        unlocked = unlock_period(period, user=self.user, reason="adjust")
        self.assertEqual(unlocked.status, PeriodStatus.OPEN)

    def test_forbidden_transitions_rejected(self):
        locked = lock_period(
            self._period(name="L", start="2026-01-01", end="2026-06-30"), user=self.user)
        with self.assertRaises(PeriodValidationError):
            close_period(locked, user=self.user)
        with self.assertRaises(PeriodValidationError):
            reopen_period(locked, user=self.user, reason="x")
        closed = close_period(
            self._period(name="C", start="2026-07-01", end="2026-12-31"), user=self.user)
        with self.assertRaises(PeriodValidationError):
            lock_period(closed, user=self.user)
        with self.assertRaises(PeriodValidationError):
            unlock_period(closed, user=self.user, reason="x")
        self.assertEqual(FiscalPeriod.objects.get(name="L").status, PeriodStatus.LOCKED)
        self.assertEqual(FiscalPeriod.objects.get(name="C").status, PeriodStatus.CLOSED)

    def test_repeat_transition_is_noop_without_audit(self):
        period = self._period()
        close_period(period, user=self.user)
        audits = AuditEvent.objects.count()
        closed_at = FiscalPeriod.objects.get(pk=period.pk).closed_at
        close_period(period, user=self.user)
        self.assertEqual(AuditEvent.objects.count(), audits)
        self.assertEqual(FiscalPeriod.objects.get(pk=period.pk).closed_at, closed_at)
        reopen_period(period, user=self.user, reason="r")
        audits = AuditEvent.objects.count()
        reopen_period(period, user=self.user, reason="r")
        self.assertEqual(AuditEvent.objects.count(), audits)

    def test_lifecycle_rejects_unknown_and_unpersisted_periods(self):
        ghost = FiscalPeriod(name="ghost", start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        for op in (close_period, lock_period):
            with self.assertRaises(PeriodValidationError):
                op(ghost, user=self.user)
        for op in (reopen_period, unlock_period):
            with self.assertRaises(PeriodValidationError):
                op(ghost, user=self.user, reason="x")
        ghost.pk = 999999
        with self.assertRaises(PeriodValidationError):
            close_period(ghost, user=self.user)

    def test_close_and_lock_require_user(self):
        period = self._period()
        with self.assertRaises(PeriodValidationError):
            close_period(period, user=None)
        with self.assertRaises(PeriodValidationError):
            lock_period(period, user=None)
        self.assertEqual(FiscalPeriod.objects.get(pk=period.pk).status, PeriodStatus.OPEN)


class PeriodIntegrationTests(PeriodFixture, TestCase):
    def test_reversal_rejected_in_closed_period(self):
        period = self._period()
        entry = self._post("2026-04-04")
        close_period(period, user=self.user)
        with self.assertRaises(PeriodValidationError):
            reverse_journal(entry, "late fix", self.user)
        self.assertEqual(JournalEntry.objects.get(pk=entry.pk).status, JournalStatus.POSTED)

    def test_reopen_then_reverse_then_close_flow(self):
        period = self._period()
        entry = self._post("2026-04-04")
        close_period(period, user=self.user)
        reopen_period(period, user=self.user, reason="error found")
        reversal = reverse_journal(entry, "wrong amount", self.user)
        self.assertEqual(reversal.status, JournalStatus.POSTED)
        self.assertEqual(reversal.posting_date, date(2026, 4, 4))
        self.assertEqual(JournalEntry.objects.get(pk=entry.pk).status, JournalStatus.REVERSED)
        close_period(period, user=self.user, reason="done")
        self.assertEqual(FiscalPeriod.objects.get(pk=period.pk).status, PeriodStatus.CLOSED)

    def test_backdated_posting_open_ok_closed_reject(self):
        period = self._period()
        old = self._post("2026-02-02")
        self.assertEqual(old.status, JournalStatus.POSTED)
        close_period(period, user=self.user)
        with self.assertRaises(PeriodValidationError):
            self._post("2026-01-15")
        self.assertEqual(JournalEntry.objects.count(), 1)

    def test_close_rejects_tampered_totals_without_repair(self):
        period = self._period()
        entry = self._post("2026-04-04")
        JournalEntry.objects.filter(pk=entry.pk).update(total_debit=Decimal("1.00"))
        with self.assertRaises(PeriodValidationError) as ctx:
            close_period(period, user=self.user)
        self.assertIn("failed integrity check", str(ctx.exception))
        fresh = FiscalPeriod.objects.get(pk=period.pk)
        self.assertEqual(fresh.status, PeriodStatus.OPEN)
        self.assertIsNone(fresh.closed_at)
        self.assertFalse(AuditEvent.objects.filter(entity="FiscalPeriod", new_state__status="CLOSED").exists())
        still_broken = JournalEntry.objects.get(pk=entry.pk)
        self.assertEqual(still_broken.total_debit, Decimal("1.00"))

    def test_close_rolls_back_when_audit_fails(self):
        period = self._period()
        self._post("2026-04-04")
        with mock.patch(
            "fiscal_periods.services.record_audit_event", side_effect=RuntimeError("audit down")
        ):
            with self.assertRaises(RuntimeError):
                close_period(period, user=self.user)
        self.assertEqual(FiscalPeriod.objects.get(pk=period.pk).status, PeriodStatus.OPEN)

    def test_close_empty_range_succeeds(self):
        period = self._period()
        closed = close_period(period, user=self.user)
        self.assertEqual(closed.status, PeriodStatus.CLOSED)
        event = AuditEvent.objects.get(entity="FiscalPeriod", action=AuditAction.UPDATE)
        self.assertEqual(event.new_state["journals_verified"], 0)

    def test_historical_queries_survive_close(self):
        period = self._period()
        self._post("2026-03-03")
        close_period(period, user=self.user)
        bal = account_balance(Account.objects.get(code="1110"), date_to="2026-12-31")
        self.assertEqual(bal["balance"], Decimal("100.00"))
        result = trial_balance(date_to="2026-12-31")
        self.assertTrue(result["balanced"])
        self.assertEqual(result["difference"], Decimal("0"))

    def test_posted_immutable_after_reopen(self):
        period = self._period()
        entry = self._post("2026-04-04")
        close_period(period, user=self.user)
        reopen_period(period, user=self.user, reason="new business")
        entry.description = "sneaky edit"
        with self.assertRaises(PostedImmutabilityError):
            entry.save()
        with self.assertRaises(PostedImmutabilityError):
            entry.delete()
        self.assertEqual(JournalEntry.objects.get(pk=entry.pk).description, "period probe")
        fresh_post = self._post("2026-05-05")
        self.assertEqual(fresh_post.status, JournalStatus.POSTED)

    def test_period_boundaries_are_inclusive(self):
        period = self._period(start="2026-03-01", end="2026-03-31")
        self.assertEqual(find_period_for_date("2026-03-01"), period)
        self.assertEqual(find_period_for_date("2026-03-31"), period)
        self._post("2026-03-01")
        self._post("2026-03-31")
        self.assertEqual(JournalEntry.objects.count(), 2)

    def test_jalali_presentation_and_leap_day(self):
        period = self._period(name="Q1", start="2025-12-01", end="2026-02-28")
        self.assertEqual(gregorian_to_jalali(period.start_date), "1404/09/10")
        self.assertEqual(gregorian_to_jalali(period.end_date), "1404/12/09")
        leap = self._period(name="LEAP", start="2024-02-01", end="2024-02-29")
        self.assertEqual(find_period_for_date(date(2024, 2, 29)), leap)

    def test_g31_12_unbalanced_lines_block_close(self):
        """G31-12: close must reject journals whose ACTUAL lines are unbalanced.

        Variant 1 (§10 literal): stored (100/100), actual lines (100/90).
        Variant 2 (true §5 gap): stored manipulated to (100/90) to match the
        unbalanced lines — the old stored-only check passes it, so only the
        new actual==actual check rejects. Corruption via QuerySet.update
        (repo tamper convention: bypasses frozen save guards, like real
        low-level corruption would).
        """
        variants = [
            ("spec-numbers", Decimal("100.00"), Decimal("100.00"), "failed integrity check"),
            ("matched-manipulation", Decimal("100.00"), Decimal("90.00"), "unbalanced"),
        ]
        for label, stored_debit, stored_credit, message_bit in variants:
            with self.subTest(label):
                months = (1, 6) if label == "spec-numbers" else (7, 12)
                period = self._period(
                    name=f"G12-{label}",
                    start=f"2026-{months[0]:02d}-01",
                    end=f"2026-{months[1]:02d}-28",
                )
                entry = self._post(f"2026-{months[0]:02d}-15", number=f"JE-G12-{label}")
                JournalLine.objects.filter(entry_id=entry.pk, credit__gt=0).update(
                    credit=Decimal("90.00"))
                JournalEntry.objects.filter(pk=entry.pk).update(
                    total_debit=stored_debit, total_credit=stored_credit)
                with self.assertRaises(PeriodValidationError) as ctx:
                    close_period(period, user=self.user)
                self.assertIn(message_bit, str(ctx.exception))
                fresh = FiscalPeriod.objects.get(pk=period.pk)
                self.assertEqual(fresh.status, PeriodStatus.OPEN)
                self.assertIsNone(fresh.closed_at)
                still = JournalEntry.objects.get(pk=entry.pk)
                self.assertEqual(still.status, JournalStatus.POSTED)
                self.assertEqual(still.total_debit, stored_debit)
                self.assertEqual(still.total_credit, stored_credit)
                lines = list(JournalLine.objects.filter(entry_id=entry.pk).order_by("id"))
                self.assertEqual(sum(line.debit for line in lines), Decimal("100.00"))
                self.assertEqual(sum(line.credit for line in lines), Decimal("90.00"))
                self.assertFalse(
                    AuditEvent.objects.filter(
                        entity="FiscalPeriod", entity_id=str(period.pk),
                        new_state__status="CLOSED",
                    ).exists()
                )
                self.assertEqual(FiscalPeriod.objects.filter(pk=period.pk).count(), 1)
