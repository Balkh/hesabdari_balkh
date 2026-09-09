"""Stage 2.4 — balances, trial balance & source traceability goldens (G1–G22).

Read-only layer over posted journals: posted-only inclusion, normal-balance
signs (incl. 4200/5200 contra overrides with frozen COA types), posting-date
filtering, trial-balance equation with loud failure, source round-trips,
failure behavior and reconciliation. Mixed-currency activity is REFUSED
(Phase 0 §16.6-5: never merge currencies numerically).
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from currencies.models import Currency
from security.models import AuditEvent

from .balances import TrialBalanceError, account_balance, journals_by_source, trace_source, trial_balance
from .coa import seed_chart_of_accounts
from .models import Account, JournalEntry, JournalLine, JournalStatus
from .services import JournalValidationError, post_journal, reverse_journal


class BalanceHelpers:
    def _post(self, number, debit_code, credit_code, amount, posting_date="2026-09-09",
              currency=None, **kwargs):
        params = dict(
            number=number, posting_date=posting_date, description="balance probe",
            lines=[
                {"account": Account.objects.get(code=debit_code), "debit": amount},
                {"account": Account.objects.get(code=credit_code), "credit": amount},
            ],
            currency=currency or self.afn,
        )
        params.update(kwargs)
        return post_journal(**params)

    def _bal(self, code, **kwargs):
        return account_balance(Account.objects.get(code=code), **kwargs)


class GoldenBalanceTests(BalanceHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")

    def test_g1_empty_ledger(self):
        result = self._bal("1110")
        self.assertEqual(result["total_debit"], Decimal("0"))
        self.assertEqual(result["total_credit"], Decimal("0"))
        self.assertEqual(result["balance"], Decimal("0"))
        self.assertEqual(result["lines_count"], 0)
        tb = trial_balance()
        self.assertEqual(tb["rows"], [])
        self.assertEqual(tb["total_debit"], Decimal("0"))
        self.assertEqual(tb["total_credit"], Decimal("0"))
        self.assertTrue(tb["balanced"])

    def test_g2_one_balanced_journal(self):
        self._post("JE-G2", "1110", "4110", "1000")
        cash = self._bal("1110")
        self.assertEqual(cash["balance"], Decimal("1000"))
        self.assertEqual(cash["normal_balance"], "DEBIT")
        revenue = self._bal("4110")
        self.assertEqual(revenue["balance"], Decimal("1000"))
        self.assertEqual(revenue["normal_balance"], "CREDIT")

    def test_g3_multiple_journals_aggregate(self):
        self._post("JE-G3A", "1110", "4110", "100")
        self._post("JE-G3B", "1110", "4110", "250")
        self.assertEqual(self._bal("1110")["balance"], Decimal("350"))
        self.assertEqual(self._bal("4110")["balance"], Decimal("350"))

    def test_g4_asset_debit_balance(self):
        self._post("JE-G4", "1110", "4110", "500")
        result = self._bal("1110")
        self.assertEqual((result["total_debit"], result["total_credit"]), (Decimal("500"), Decimal("0")))
        self.assertEqual(result["balance"], Decimal("500"))

    def test_g5_asset_credit_reduction(self):
        self._post("JE-G5A", "1110", "4110", "500")
        self._post("JE-G5B", "4110", "1110", "200")
        self.assertEqual(self._bal("1110")["balance"], Decimal("300"))

    def test_g6_liability_credit_balance(self):
        self._post("JE-G6", "1410", "2110", "1000")
        result = self._bal("2110")
        self.assertEqual(result["normal_balance"], "CREDIT")
        self.assertEqual(result["balance"], Decimal("1000"))

    def test_g7_expense_debit_balance(self):
        self._post("JE-G7", "6100", "1110", "400")
        result = self._bal("6100")
        self.assertEqual(result["normal_balance"], "DEBIT")
        self.assertEqual(result["balance"], Decimal("400"))

    def test_g8_revenue_credit_balance(self):
        self._post("JE-G8", "1110", "4120", "700")
        self.assertEqual(self._bal("4120")["balance"], Decimal("700"))

    def test_equity_credit_balance(self):
        self._post("JE-GEQ", "1110", "3100", "500")
        result = self._bal("3100")
        self.assertEqual(result["normal_balance"], "CREDIT")
        self.assertEqual(result["balance"], Decimal("500"))

    def test_g9_sales_returns_debit_normal(self):
        self._post("JE-G9", "4200", "1110", "100")
        result = self._bal("4200")
        self.assertEqual(result["account_type"], "REVENUE")  # frozen COA type intact
        self.assertTrue(result["is_contra"])
        self.assertEqual(result["normal_balance"], "DEBIT")
        self.assertEqual(result["balance"], Decimal("100"))

    def test_g10_purchase_returns_credit_normal(self):
        self._post("JE-G10", "2110", "5200", "100")
        result = self._bal("5200")
        self.assertEqual(result["account_type"], "EXPENSE")  # frozen COA type intact
        self.assertTrue(result["is_contra"])
        self.assertEqual(result["normal_balance"], "CREDIT")
        self.assertEqual(result["balance"], Decimal("100"))


class StatusAndDateTests(BalanceHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")

    def test_g11_draft_excluded_then_posted(self):
        draft = JournalEntry.objects.create(number="JE-G11", posting_date="2026-09-09", description="d")
        cash = Account.objects.get(code="1110")
        revenue = Account.objects.get(code="4110")
        JournalLine.objects.create(entry=draft, account=cash, debit=Decimal("100.00"))
        JournalLine.objects.create(entry=draft, account=revenue, credit=Decimal("100.00"))
        self.assertEqual(self._bal("1110")["balance"], Decimal("0"))
        self.assertEqual(trial_balance()["rows"], [])
        draft.status = JournalStatus.POSTED
        draft.save()
        self.assertEqual(self._bal("1110")["balance"], Decimal("100.00"))
        self.assertEqual(trial_balance()["total_debit"], Decimal("100.00"))

    def test_g12_reversal_nets_zero_history_preserved(self):
        original = self._post("JE-G12", "1110", "4110", "1000")
        reversal = reverse_journal(original, "golden", None)
        self.assertEqual(self._bal("1110")["balance"], Decimal("0"))
        self.assertEqual(self._bal("4110")["balance"], Decimal("0"))
        self.assertEqual(JournalEntry.objects.count(), 2)
        self.assertEqual(JournalEntry.objects.get(pk=original.pk).status, JournalStatus.REVERSED)
        self.assertEqual(JournalEntry.objects.get(pk=reversal.pk).status, JournalStatus.POSTED)

    def test_cancelled_status_excluded(self):
        entry = JournalEntry.objects.create(number="JE-CX", posting_date="2026-09-09", description="x")
        cash = Account.objects.get(code="1110")
        revenue = Account.objects.get(code="4110")
        JournalLine.objects.create(entry=entry, account=cash, debit=Decimal("50.00"))
        JournalLine.objects.create(entry=entry, account=revenue, credit=Decimal("50.00"))
        entry.status = "CANCELLED"
        entry.save()
        self.assertEqual(self._bal("1110")["balance"], Decimal("0"))
        self.assertEqual(trial_balance()["rows"], [])

    def test_g13_date_filtering(self):
        self._post("JE-D1", "1110", "4110", "10", posting_date="2026-01-10")
        self._post("JE-D2", "1110", "4110", "20", posting_date="2026-01-20")
        self._post("JE-D3", "1110", "4110", "30", posting_date="2026-01-30")
        self.assertEqual(self._bal("1110")["balance"], Decimal("60"))
        self.assertEqual(self._bal("1110", date_from="2026-01-20")["balance"], Decimal("50"))
        self.assertEqual(self._bal("1110", date_to="2026-01-20")["balance"], Decimal("30"))
        exact = self._bal("1110", date_from="2026-01-20", date_to="2026-01-20")
        self.assertEqual(exact["balance"], Decimal("20"))  # inclusive bounds
        self.assertEqual(exact["date_from"], date(2026, 1, 20))

    def test_g14_chronology_follows_posting_date(self):
        self._post("JE-B", "1110", "4110", "20", posting_date="2026-01-20")  # created 1st
        self._post("JE-A", "1110", "4110", "10", posting_date="2026-01-10")  # created 2nd
        self._post("JE-0", "1110", "4110", "5", posting_date="2026-01-10")  # tie-break by number
        ordered = list(JournalEntry.objects.order_by("posting_date", "number", "id")
                       .values_list("number", flat=True))
        self.assertEqual(ordered, ["JE-0", "JE-A", "JE-B"])
        self.assertEqual(self._bal("1110", date_to="2026-01-15")["balance"], Decimal("15"))


class TrialBalanceTests(BalanceHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")

    def test_g15_trial_balance_multi_account(self):
        self._post("JE-T1", "1110", "4110", "1000")
        self._post("JE-T2", "6100", "1110", "400")
        tb = trial_balance()
        self.assertEqual([r["account_code"] for r in tb["rows"]], ["1110", "4110", "6100"])
        by_code = {r["account_code"]: r for r in tb["rows"]}
        self.assertEqual(by_code["1110"]["debit"], Decimal("1000"))
        self.assertEqual(by_code["1110"]["credit"], Decimal("400"))
        self.assertEqual(by_code["1110"]["balance"], Decimal("600"))
        self.assertEqual(tb["total_debit"], Decimal("1400"))
        self.assertEqual(tb["total_credit"], Decimal("1400"))
        self.assertEqual(tb["difference"], Decimal("0"))
        self.assertTrue(tb["balanced"])
        self.assertEqual(tb["accounts_count"], 3)

    def test_g16_trial_balance_after_reversal(self):
        original = self._post("JE-T3", "1110", "4110", "1000")
        reverse_journal(original, "golden", None)
        tb = trial_balance()
        self.assertTrue(tb["balanced"])
        by_code = {r["account_code"]: r for r in tb["rows"]}
        self.assertEqual(set(by_code), {"1110", "4110"})  # activity rows kept, not hidden
        self.assertEqual(by_code["1110"]["debit"], Decimal("1000"))
        self.assertEqual(by_code["1110"]["credit"], Decimal("1000"))
        self.assertEqual(by_code["1110"]["balance"], Decimal("0"))

    def test_trial_balance_respects_date_to(self):
        self._post("JE-T4", "1110", "4110", "100", posting_date="2026-01-10")
        self._post("JE-T5", "1110", "4110", "200", posting_date="2026-03-10")
        tb = trial_balance("2026-02-01")
        self.assertEqual(tb["total_debit"], Decimal("100"))
        self.assertEqual(tb["date_to"], date(2026, 2, 1))

    def test_imbalance_fails_loudly_with_diagnosis(self):
        entry = self._post("JE-T6", "1110", "4110", "100")
        JournalLine.objects.filter(entry_id=entry.pk, debit__gt=0).update(debit=Decimal("101.00"))
        honest = self._bal("1110")  # reporting stays truthful, nothing hidden
        self.assertEqual(honest["total_debit"], Decimal("101.00"))
        with self.assertRaises(TrialBalanceError) as ctx:
            trial_balance()
        self.assertIn("out of balance", str(ctx.exception))
        self.assertEqual(ctx.exception.result["total_debit"], Decimal("101.00"))
        self.assertEqual(ctx.exception.result["total_credit"], Decimal("100.00"))
        self.assertEqual(ctx.exception.result["difference"], Decimal("1.00"))
        self.assertFalse(ctx.exception.result["balanced"])
        self.assertEqual(len(ctx.exception.result["rows"]), 2)


class SourceTraceTests(BalanceHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")

    def test_g17_source_round_trip(self):
        entry = self._post("JE-S1", "1110", "4110", "100", source_type="TEST", source_id="DOC-1")
        found = journals_by_source("TEST", "DOC-1")
        self.assertEqual([e.pk for e in found], [entry.pk])
        self.assertEqual(found[0].lines.count(), 2)
        ref = trace_source(entry)
        self.assertEqual((ref["source_type"], ref["source_id"]), ("TEST", "DOC-1"))
        self.assertEqual(ref["entry_number"], "JE-S1")

    def test_g18_missing_source_safe(self):
        self.assertEqual(journals_by_source("NOPE", "X"), [])
        entry = self._post("JE-S2", "1110", "4110", "100")
        ref = trace_source(entry)
        self.assertFalse(ref["resolved"])
        self.assertIsNone(ref["document"])
        intact = JournalEntry.objects.get(pk=entry.pk)
        self.assertEqual(intact.status, JournalStatus.POSTED)
        self.assertEqual(intact.lines.count(), 2)

    def test_g19_multiple_journals_one_source_chronological(self):
        self._post("JE-S3B", "1110", "4110", "20", posting_date="2026-02-01",
                   source_type="DOC", source_id="9")
        self._post("JE-S3A", "1110", "4110", "10", posting_date="2026-01-01",
                   source_type="DOC", source_id="9")
        found = journals_by_source("DOC", "9")
        self.assertEqual([e.number for e in found], ["JE-S3A", "JE-S3B"])

    def test_g20_no_source_no_fabrication(self):
        entry = self._post("JE-S4", "1110", "4110", "100")
        ref = trace_source(entry)
        self.assertEqual(set(ref), {"entry_id", "entry_number", "entry_status", "source_type",
                                   "source_id", "resolved", "document"})
        self.assertEqual((ref["source_type"], ref["source_id"]), ("", ""))
        self.assertFalse(ref["resolved"])
        self.assertIsNone(ref["document"])


class ReadIntegrityTests(BalanceHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")

    def _snapshot(self):
        entry_fields = [f.name for f in JournalEntry._meta.concrete_fields]
        line_fields = [f.name for f in JournalLine._meta.concrete_fields]
        account_fields = [f.name for f in Account._meta.concrete_fields]
        return (
            list(JournalEntry.objects.order_by("id").values_list(*entry_fields)),
            list(JournalLine.objects.order_by("id").values_list(*line_fields)),
            list(Account.objects.order_by("id").values_list(*account_fields)),
            AuditEvent.objects.count(),
        )

    def test_g21_read_layer_never_mutates(self):
        self._post("JE-R1", "1110", "4110", "100")
        before = self._snapshot()
        account_balance(Account.objects.get(code="1110"))
        account_balance(Account.objects.get(code="4110"), date_from="2026-01-01", date_to="2026-12-31")
        trial_balance()
        trial_balance("2026-06-01")
        trace_source(JournalEntry.objects.get(number="JE-R1"))
        journals_by_source("X", "Y")
        self.assertEqual(self._snapshot(), before)

    def test_g22_decimal_precision(self):
        self._post("JE-P1", "1110", "4110", "0.10")
        self._post("JE-P2", "1110", "4110", "0.20")
        self._post("JE-P3", "4110", "1110", "0.30")
        result = self._bal("1110")
        self.assertEqual(result["balance"], Decimal("0.00"))  # exact, no float drift
        self.assertIsInstance(result["balance"], Decimal)
        self.assertIsInstance(result["total_debit"], Decimal)
        self.assertEqual(trial_balance()["difference"], Decimal("0"))

    def test_mixed_currencies_refused(self):
        self._post("JE-M1", "1110", "4110", "100")
        self._post("JE-M2", "1110", "4110", "10", currency=self.usd, rate="70", rate_date="2026-09-09")
        with self.assertRaises(JournalValidationError):
            self._bal("1110")
        with self.assertRaises(JournalValidationError):
            trial_balance()
        self.assertEqual(JournalEntry.objects.count(), 2)  # nothing hidden or removed


class FailureTests(BalanceHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")

    def test_nonexistent_account_rejected(self):
        for bad in (None, "1110", Account()):
            with self.subTest(account=repr(bad)[:20]):
                with self.assertRaises(JournalValidationError):
                    account_balance(bad)

    def test_invalid_range_rejected(self):
        account = Account.objects.get(code="1110")
        with self.assertRaises(JournalValidationError):
            account_balance(account, date_from="not-a-date")
        with self.assertRaises(JournalValidationError):
            account_balance(account, date_from="2026-02-01", date_to="2026-01-01")
        with self.assertRaises(JournalValidationError):
            trial_balance("not-a-date")

    def test_trace_argument_validation(self):
        for bad in (None, "JE-1", JournalEntry()):
            with self.subTest(entry=repr(bad)[:20]):
                with self.assertRaises(JournalValidationError):
                    trace_source(bad)


class ReconciliationTests(BalanceHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")

    def test_lines_to_balances_to_trial_balance(self):
        self._post("JE-C1", "1110", "4110", "1000", posting_date="2026-01-05")
        self._post("JE-C2", "6100", "1110", "400", posting_date="2026-02-05")
        doomed = self._post("JE-C3", "1410", "2110", "250", posting_date="2026-03-05")
        reverse_journal(doomed, "reconcile", None)
        draft = JournalEntry.objects.create(number="JE-C4", posting_date="2026-04-05", description="d")
        JournalLine.objects.create(entry=draft, account=Account.objects.get(code="1110"),
                                   debit=Decimal("9999.00"))

        posted_lines = JournalLine.objects.filter(entry__status__in=("POSTED", "REVERSED"))
        journal_debit = sum((l.debit for l in posted_lines), Decimal("0"))
        journal_credit = sum((l.credit for l in posted_lines), Decimal("0"))

        account_debit = Decimal("0")
        account_credit = Decimal("0")
        for account in Account.objects.all():
            result = account_balance(account)
            account_debit += result["total_debit"]
            account_credit += result["total_credit"]
        self.assertEqual(account_debit, journal_debit)
        self.assertEqual(account_credit, journal_credit)

        tb = trial_balance()
        self.assertEqual(tb["total_debit"], journal_debit)
        self.assertEqual(tb["total_credit"], journal_credit)
        self.assertEqual(tb["total_debit"], tb["total_credit"])

    def test_source_linked_data_matches_persisted(self):
        entry = self._post("JE-C5", "1310", "4110", "300", source_type="TEST", source_id="R-1")
        (found,) = journals_by_source("TEST", "R-1")
        self.assertEqual(found.pk, entry.pk)
        direct = [(l.account.code, l.debit, l.credit) for l in
                  JournalLine.objects.filter(entry_id=entry.pk).order_by("id")]
        traced = [(l.account.code, l.debit, l.credit) for l in found.lines.all().order_by("id")]
        self.assertEqual(traced, direct)
