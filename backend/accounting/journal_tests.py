"""Stage 2.2 — journal contract tests (Phase 0 §1.8).

Covers: currency context, rate snapshot, stored totals, AFN equivalent,
line reference, created_by, mismatch rejection, legacy readability (via the
real 0004 backfill function), and entry-level reconciliation.
"""

import importlib
from datetime import date
from decimal import Decimal

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import TestCase

from core.money import fx_equivalent
from currencies.models import Currency

from .coa import seed_chart_of_accounts
from .models import Account, JournalEntry, JournalStatus
from .services import JournalValidationError, post_journal, verify_entry_totals


class JournalContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")
        cls.cash = Account.objects.get(code="1110")
        cls.revenue = Account.objects.get(code="4110")

    def _lines(self, amount=Decimal("100.00")):
        return [
            {"account": self.cash, "debit": amount},
            {"account": self.revenue, "credit": amount},
        ]

    def test_afn_post_stores_full_snapshot(self):
        entry = post_journal(
            number="JE-2201", posting_date="2026-09-09", description="AFN sale",
            lines=self._lines(), currency=self.afn,
        )
        self.assertEqual(entry.status, JournalStatus.POSTED)
        self.assertEqual(entry.currency, self.afn)
        self.assertEqual(entry.total_debit, Decimal("100.00"))
        self.assertEqual(entry.total_credit, Decimal("100.00"))
        self.assertEqual(entry.afn_total, Decimal("100.00"))
        self.assertEqual(entry.rate, Decimal("1.0000"))
        self.assertEqual(entry.rate_date, date(2026, 9, 9))
        self.assertEqual(entry.rate_direction, "AFN->AFN")
        self.assertIsNone(entry.created_by)
        self.assertEqual([line.reference for line in entry.lines.all()], ["", ""])

    def test_afn_post_accepts_explicit_rate_date(self):
        entry = post_journal(
            number="JE-2202", posting_date="2026-09-09", description="AFN explicit rate date",
            lines=self._lines(Decimal("50.00")), currency=self.afn, rate_date="2026-09-01",
        )
        self.assertEqual(entry.rate_date, date(2026, 9, 1))
        self.assertEqual(entry.rate, Decimal("1.0000"))

    def test_usd_post_computes_afn_half_up(self):
        entry = post_journal(
            number="JE-2203", posting_date="2026-09-09", description="USD sale",
            lines=self._lines(Decimal("1.00")), currency=self.usd,
            rate="70.005", rate_date="2026-09-08",
        )
        entry.refresh_from_db()  # prove DB round-trip, not just in-memory state
        self.assertEqual(entry.total_debit, Decimal("1.00"))
        self.assertEqual(entry.afn_total, Decimal("70.01"))  # HALF_UP, not 70.00
        self.assertEqual(entry.rate, Decimal("70.0050"))
        self.assertEqual(entry.rate_date, date(2026, 9, 8))  # distinct from posting date
        self.assertEqual(entry.posting_date, date(2026, 9, 9))
        self.assertEqual(entry.rate_direction, "USD->AFN")

    def test_rate_quantized_to_4dp(self):
        entry = post_journal(
            number="JE-2204", posting_date="2026-09-09", description="rate precision",
            lines=self._lines(Decimal("10.00")), currency=self.usd,
            rate="70.00005", rate_date="2026-09-09",
        )
        self.assertEqual(entry.rate, Decimal("70.0001"))

    def test_line_reference_optional_and_stored(self):
        entry = post_journal(
            number="JE-2205", posting_date="2026-09-09", description="references",
            lines=[
                {"account": self.cash, "debit": Decimal("5.00"), "reference": "SI-1405-00001:1"},
                {"account": self.revenue, "credit": Decimal("5.00")},
            ],
            currency=self.afn,
        )
        refs = sorted(line.reference for line in entry.lines.all())
        self.assertEqual(refs, ["", "SI-1405-00001:1"])

    def test_created_by_nullable_and_stored(self):
        user = get_user_model().objects.create_user("acc1", password="x")
        entry = post_journal(
            number="JE-2206", posting_date="2026-09-09", description="with user",
            lines=self._lines(Decimal("7.00")), currency=self.afn, created_by=user,
        )
        self.assertEqual(entry.created_by, user)
        with self.assertRaises(JournalValidationError):
            post_journal(
                number="JE-2207", posting_date="2026-09-09", description="bad user",
                lines=self._lines(Decimal("7.00")), currency=self.afn, created_by="not-a-user",
            )

    def test_currency_context_required(self):
        for bad in (None, "USD", 123):
            with self.subTest(currency=bad):
                before = JournalEntry.objects.count()
                with self.assertRaises(JournalValidationError):
                    post_journal(
                        number="JE-2208", posting_date="2026-09-09", description="no currency",
                        lines=self._lines(), currency=bad,
                    )
                self.assertEqual(JournalEntry.objects.count(), before)

    def test_inactive_currency_rejected(self):
        self.usd.is_active = False
        self.usd.save()
        with self.assertRaises(JournalValidationError):
            post_journal(
                number="JE-2209", posting_date="2026-09-09", description="inactive currency",
                lines=self._lines(), currency=self.usd, rate="70", rate_date="2026-09-09",
            )
        self.assertFalse(JournalEntry.objects.filter(number="JE-2209").exists())

    def test_foreign_requires_rate_and_rate_date(self):
        base_kwargs = dict(number="JE-2210", posting_date="2026-09-09",
                           description="x", lines=self._lines(), currency=self.usd)
        with self.assertRaises(JournalValidationError):
            post_journal(**{**base_kwargs, "rate_date": "2026-09-09"})  # no rate
        for bad_rate in ("0", "-5", "abc", 70.5):
            with self.subTest(rate=bad_rate):
                with self.assertRaises(JournalValidationError):
                    post_journal(**{**base_kwargs, "rate": bad_rate, "rate_date": "2026-09-09"})
        with self.assertRaises(JournalValidationError):
            post_journal(**{**base_kwargs, "rate": "70"})  # no rate_date
        self.assertFalse(JournalEntry.objects.filter(number="JE-2210").exists())

    def test_base_rejects_non_one_rate(self):
        with self.assertRaises(JournalValidationError):
            post_journal(
                number="JE-2211", posting_date="2026-09-09", description="bad base rate",
                lines=self._lines(), currency=self.afn, rate="70",
            )
        entry = post_journal(
            number="JE-2212", posting_date="2026-09-09", description="explicit one rate",
            lines=self._lines(), currency=self.afn, rate="1",
        )
        self.assertEqual(entry.rate, Decimal("1.0000"))

    def test_stored_totals_match_and_verify_passes(self):
        entry = post_journal(
            number="JE-2213", posting_date="2026-09-09", description="verify ok",
            lines=self._lines(Decimal("12.50")), currency=self.afn,
        )
        result = verify_entry_totals(JournalEntry.objects.get(number="JE-2213"))
        self.assertEqual(result, {"total_debit": Decimal("12.50"), "total_credit": Decimal("12.50")})

    def test_mismatch_rejected(self):
        entry = post_journal(
            number="JE-2214", posting_date="2026-09-09", description="to corrupt",
            lines=self._lines(Decimal("9.00")), currency=self.afn,
        )
        JournalEntry.objects.filter(pk=entry.pk).update(total_debit=Decimal("1.00"))
        with self.assertRaises(JournalValidationError):
            verify_entry_totals(JournalEntry.objects.get(pk=entry.pk))

    def test_missing_totals_rejected(self):
        ghost = JournalEntry(
            number="JE-GHOST", posting_date="2026-09-09", description="x",
            total_debit=None, total_credit=None,
        )
        with self.assertRaises(JournalValidationError):
            verify_entry_totals(ghost)

    def test_failed_post_leaves_nothing(self):
        before = JournalEntry.objects.count()
        with self.assertRaises(JournalValidationError):
            post_journal(
                number="JE-2215", posting_date="2026-09-09", description="bad currency",
                lines=self._lines(), currency="XXX",
            )
        self.assertEqual(JournalEntry.objects.count(), before)
        self.assertFalse(JournalEntry.objects.filter(number="JE-2215").exists())


class MissingBaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")

    def test_foreign_without_base_configured(self):
        with self.assertRaises(JournalValidationError):
            post_journal(
                number="JE-2216", posting_date="2026-09-09", description="no base",
                lines=[
                    {"account": Account.objects.get(code="1110"), "debit": Decimal("1.00")},
                    {"account": Account.objects.get(code="4110"), "credit": Decimal("1.00")},
                ],
                currency=self.usd, rate="70", rate_date="2026-09-09",
            )
        self.assertFalse(JournalEntry.objects.filter(number="JE-2216").exists())


class LegacyReadabilityTests(TestCase):
    """Pre-2.2-shaped rows stay readable; the REAL 0004 backfill fills totals
    from lines and fabricates nothing (currency stays NULL)."""

    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()

    def test_legacy_journal_readable_and_backfillable(self):
        cash = Account.objects.get(code="1110")
        revenue = Account.objects.get(code="4110")
        legacy = JournalEntry.objects.create(
            number="JE-LEG-1", posting_date="2026-09-01",
            description="legacy", status=JournalStatus.POSTED,
        )
        from .models import JournalLine
        JournalLine.objects.create(entry=legacy, account=cash, debit=Decimal("100.00"))
        JournalLine.objects.create(entry=legacy, account=revenue, credit=Decimal("100.00"))
        draft = JournalEntry.objects.create(
            number="JE-LEG-2", posting_date="2026-09-01", description="legacy draft",
        )

        # Readable before backfill, with honest NULL/empty snapshot fields.
        legacy.refresh_from_db()
        self.assertIsNone(legacy.currency)
        self.assertEqual(legacy.total_debit, Decimal("0.00"))
        self.assertEqual(legacy.lines.count(), 2)

        # Execute the REAL migration function (not a copy of its logic).
        migration = importlib.import_module("accounting.migrations.0004_backfill_journal_totals")
        migration.backfill_totals(django_apps, None)

        legacy.refresh_from_db()
        draft.refresh_from_db()
        self.assertEqual(legacy.total_debit, Decimal("100.00"))
        self.assertEqual(legacy.total_credit, Decimal("100.00"))
        self.assertIsNone(legacy.currency)  # NOT fabricated
        self.assertIsNone(legacy.afn_total)
        self.assertIsNone(legacy.rate)
        self.assertEqual(draft.total_debit, Decimal("0.00"))  # no lines -> 0/0
        self.assertEqual(draft.total_credit, Decimal("0.00"))
        verify_entry_totals(legacy)  # passes after backfill


class EntryReconciliationTests(TestCase):
    """Stage 2.2 reconciliation: every entry's stored totals and AFN figure
    agree with its lines and snapshot."""

    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")

    def test_all_entries_reconcile(self):
        user = get_user_model().objects.create_user("rec1", password="x")
        cash = Account.objects.get(code="1110")
        revenue = Account.objects.get(code="4110")

        def post(number, amount, currency, **kw):
            return post_journal(
                number=number, posting_date="2026-09-09", description="rec",
                lines=[{"account": cash, "debit": amount},
                       {"account": revenue, "credit": amount}],
                currency=currency, **kw,
            )

        post("JE-R1", Decimal("100.00"), self.afn)
        post("JE-R2", Decimal("1.00"), self.usd, rate="70.005", rate_date="2026-09-08")
        post("JE-R3", Decimal("50.00"), self.afn, created_by=user)

        self.assertEqual(JournalEntry.objects.count(), 3)
        for entry in JournalEntry.objects.all():
            verify_entry_totals(entry)
            if entry.currency.is_base:
                self.assertEqual(entry.afn_total, entry.total_debit)
            else:
                self.assertEqual(entry.afn_total, fx_equivalent(entry.total_debit, entry.rate))
