"""Stage 2.5 realized-FX tests (§1.10–§1.12, §5–§15 of the Stage 2.5 brief).

Covers the mandatory FX vectors (§12 A–H), the four gain/loss directions, the
zero-FX case, partial settlement, currency safety, every invalid-input class
(§14), historical-rate preservation (§10), reversal compatibility (§15),
idempotency (§24) and a genuine transaction-level rollback (§23).

The rollback tests use TransactionTestCase: TestCase wraps the whole test in a
transaction, so only a real transaction proves application-level atomicity.
"""

from datetime import date
from decimal import Decimal
from unittest import mock

from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase

from core.idempotency import DuplicateOperationError, IdempotencyRecord
from core.money import fx_equivalent, normalize_rate
from currencies.models import Currency, ExchangeRate
from documents.models import NumberSequence
from security.models import AuditAction, AuditEvent

from .balances import account_balance, journals_by_source, trace_source
from .coa import seed_chart_of_accounts
from .fx import (
    FX_CONVERSION,
    FX_GAIN,
    FX_LOSS,
    FX_NONE,
    compute_realized_fx,
    post_fx_conversion,
    post_realized_fx_settlement,
)
from .models import Account, AccountType, FXSettlement, JournalEntry, JournalLine, JournalStatus
from .services import JournalValidationError, reverse_journal, verify_entry_totals

ZERO = Decimal("0.00")


class FXFixture:
    """Shared fixture: canonical COA + AFN (base) / USD / EUR."""

    @classmethod
    def _seed(cls):
        seed_chart_of_accounts()
        afn, _ = Currency.objects.get_or_create(code="AFN", defaults={"name": "Afghani", "is_base": True})
        usd, _ = Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar"})
        eur, _ = Currency.objects.get_or_create(code="EUR", defaults={"name": "Euro"})
        return afn, usd, eur

    @classmethod
    def _accounts(cls):
        # 4100 (Sales Revenue) is a NON-POSTING group account in the frozen
        # Stage 2.1 COA, so revenue postings use its posting child 4110.
        return {code: Account.objects.get(code=code) for code in
                ("1110", "1210", "1310", "1410", "2110", "2400", "4100", "4110",
                 "4200", "5100", "8100", "8200")}

    def _plan(self, **overrides):
        params = dict(
            obligation_kind="RECEIVABLE",
            obligation_account=self.acc["1310"],
            obligation_amount="100.00",
            obligation_currency=self.usd,
            historical_rate="70",
            settlement_account=self.acc["1110"],
            settlement_amount="100.00",
            settlement_currency=self.usd,
            settlement_rate="72",
        )
        params.update(overrides)
        return compute_realized_fx(**params)

    def _settle(self, number="JE-FX-1", **overrides):
        params = dict(
            obligation_kind="RECEIVABLE",
            obligation_account=self.acc["1310"],
            obligation_amount="100.00",
            obligation_currency=self.usd,
            historical_rate="70",
            settlement_account=self.acc["1110"],
            settlement_amount="100.00",
            settlement_currency=self.usd,
            settlement_rate="72",
        )
        params.update(overrides)
        return post_realized_fx_settlement(
            number=number, posting_date="2026-03-01", description="realized fx test",
            source_type="FX", source_id="OBL-1", **params,
        )

    def _state(self):
        return {
            "entries": JournalEntry.objects.count(),
            "lines": JournalLine.objects.count(),
            "audits": AuditEvent.objects.count(),
            "idempotency": IdempotencyRecord.objects.count(),
            "sequences": NumberSequence.objects.count(),
        }


# ---------------------------------------------------------------------------
# §12 — mandatory FX vectors
# ---------------------------------------------------------------------------

class FXVectorTests(FXFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd, cls.eur = cls._seed()
        cls.acc = cls._accounts()

    def test_vector_A_no_difference(self):
        plan = self._plan(historical_rate="70", settlement_rate="70")
        self.assertEqual(plan["carrying_value"], Decimal("7000.00"))
        self.assertEqual(plan["settlement_value"], Decimal("7000.00"))
        self.assertEqual(plan["difference"], Decimal("0.00"))
        self.assertEqual(plan["direction"], FX_NONE)

    def test_vector_B_customer_gain(self):
        plan = self._plan(historical_rate="70", settlement_rate="72")
        self.assertEqual(plan["carrying_value"], Decimal("7000.00"))
        self.assertEqual(plan["settlement_value"], Decimal("7200.00"))
        self.assertEqual(plan["difference"], Decimal("200.00"))
        self.assertEqual(plan["direction"], FX_GAIN)

    def test_vector_C_customer_loss(self):
        plan = self._plan(historical_rate="72", settlement_rate="70")
        self.assertEqual(plan["carrying_value"], Decimal("7200.00"))
        self.assertEqual(plan["settlement_value"], Decimal("7000.00"))
        self.assertEqual(plan["difference"], Decimal("200.00"))
        self.assertEqual(plan["direction"], FX_LOSS)

    def test_vector_D_supplier_loss(self):
        plan = self._plan(obligation_kind="PAYABLE",
                          obligation_account=self.acc["2110"],
                          historical_rate="70", settlement_rate="72")
        self.assertEqual(plan["carrying_value"], Decimal("7000.00"))
        self.assertEqual(plan["settlement_value"], Decimal("7200.00"))
        self.assertEqual(plan["difference"], Decimal("200.00"))
        self.assertEqual(plan["direction"], FX_LOSS)

    def test_vector_E_supplier_gain(self):
        plan = self._plan(obligation_kind="PAYABLE",
                          obligation_account=self.acc["2110"],
                          historical_rate="72", settlement_rate="70")
        self.assertEqual(plan["carrying_value"], Decimal("7200.00"))
        self.assertEqual(plan["settlement_value"], Decimal("7000.00"))
        self.assertEqual(plan["difference"], Decimal("200.00"))
        self.assertEqual(plan["direction"], FX_GAIN)

    def test_vector_F_partial_settlement(self):
        plan = self._plan(obligation_amount="100.00", settlement_amount="40.00",
                          historical_rate="70", settlement_rate="72")
        self.assertEqual(plan["carrying_value"], Decimal("2800.00"))
        self.assertEqual(plan["settlement_value"], Decimal("2880.00"))
        self.assertEqual(plan["difference"], Decimal("80.00"))
        self.assertEqual(plan["unsettled_amount"], Decimal("60.00"))
        self.assertEqual(plan["direction"], FX_GAIN)

    def test_vector_G_rate_precision_4dp(self):
        plan = self._plan(historical_rate="70.1234", settlement_rate="72.1234")
        self.assertEqual(plan["historical_rate"], Decimal("70.1234"))
        self.assertEqual(plan["settlement_rate"], Decimal("72.1234"))
        self.assertEqual(plan["carrying_value"], Decimal("7012.34"))
        self.assertEqual(plan["settlement_value"], Decimal("7212.34"))
        self.assertEqual(plan["difference"], Decimal("200.00"))
        # AFN money stays 2dp; no float drift anywhere in the chain.
        self.assertEqual(fx_equivalent("100.00", "70.1234"), Decimal("7012.34"))

    def test_vector_H_half_up_boundary(self):
        # 2.675 -> 2.68 (Half-Up), not banker's 2.67
        self.assertEqual(fx_equivalent("2.675", "1"), Decimal("2.68"))
        # rate boundary at 4dp: 2.00005 -> 2.0001 (Half-Up)
        self.assertEqual(normalize_rate("2.00005"), Decimal("2.0001"))
        plan = self._plan(obligation_amount="2.675", settlement_amount="2.675",
                          historical_rate="1", settlement_rate="1.0000")
        self.assertEqual(plan["carrying_value"], Decimal("2.68"))
        self.assertEqual(plan["settlement_value"], Decimal("2.68"))
        self.assertEqual(plan["direction"], FX_NONE)

    def test_plan_is_always_balanced(self):
        for hist, settle in (("70", "72"), ("72", "70"), ("70", "70"), ("70.1234", "72.1234")):
            for kind in ("RECEIVABLE", "PAYABLE"):
                plan = self._plan(obligation_kind=kind,
                                  obligation_account=self.acc["1310"] if kind == "RECEIVABLE" else self.acc["2110"],
                                  historical_rate=hist, settlement_rate=settle)
                self.assertTrue(plan["balanced"], f"{kind} {hist}->{settle}")
                self.assertEqual(plan["total_debit"], plan["total_credit"])


# ---------------------------------------------------------------------------
# Direction + exact journal shape (§6, §9)
# ---------------------------------------------------------------------------

class FXDirectionTests(FXFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd, cls.eur = cls._seed()
        cls.acc = cls._accounts()

    def _shape(self, entry):
        return [(line.account.code, line.debit, line.credit) for line in entry.lines.all().order_by("id")]

    def test_customer_gain_shape(self):
        entry = self._settle("JE-FX-GAIN")
        self.assertEqual(entry.currency.code, "AFN")
        self.assertEqual(entry.rate, Decimal("1.0000"))
        self.assertEqual(entry.rate_direction, "AFN->AFN")
        self.assertEqual(entry.afn_total, Decimal("7200.00"))
        self.assertEqual(entry.total_debit, Decimal("7200.00"))
        self.assertEqual(entry.total_credit, Decimal("7200.00"))
        self.assertEqual(
            self._shape(entry),
            [("1110", Decimal("7200.00"), ZERO),
             ("1310", ZERO, Decimal("7000.00")),
             ("8100", ZERO, Decimal("200.00"))],
        )
        self.assertFalse(entry.lines.filter(account__code="8200").exists())

    def test_customer_loss_shape(self):
        entry = self._settle("JE-FX-LOSS", historical_rate="72", settlement_rate="70")
        self.assertEqual(
            self._shape(entry),
            [("1110", Decimal("7000.00"), ZERO),
             ("1310", ZERO, Decimal("7200.00")),
             ("8200", Decimal("200.00"), ZERO)],
        )
        self.assertFalse(entry.lines.filter(account__code="8100").exists())

    def test_supplier_loss_shape(self):
        entry = self._settle("JE-FX-SLOSS", obligation_kind="PAYABLE",
                             obligation_account=self.acc["2110"],
                             historical_rate="70", settlement_rate="72")
        self.assertEqual(
            self._shape(entry),
            [("2110", Decimal("7000.00"), ZERO),
             ("1110", ZERO, Decimal("7200.00")),
             ("8200", Decimal("200.00"), ZERO)],
        )
        self.assertFalse(entry.lines.filter(account__code="8100").exists())

    def test_supplier_gain_shape(self):
        entry = self._settle("JE-FX-SGAIN", obligation_kind="PAYABLE",
                             obligation_account=self.acc["2110"],
                             historical_rate="72", settlement_rate="70")
        self.assertEqual(
            self._shape(entry),
            [("2110", Decimal("7200.00"), ZERO),
             ("1110", ZERO, Decimal("7000.00")),
             ("8100", ZERO, Decimal("200.00"))],
        )
        self.assertFalse(entry.lines.filter(account__code="8200").exists())

    def test_fx_accounts_keep_their_coa_type(self):
        self._settle("JE-FX-TYPES")
        self.assertEqual(Account.objects.get(code="8100").account_type, str(AccountType.REVENUE))
        self.assertEqual(Account.objects.get(code="8200").account_type, str(AccountType.EXPENSE))

    def test_settlement_uses_obligation_and_settlement_accounts(self):
        entry = self._settle("JE-FX-ACCT", settlement_account=self.acc["1210"])
        self.assertEqual(sorted(entry.lines.values_list("account__code", flat=True)),
                         ["1210", "1310", "8100"])


# ---------------------------------------------------------------------------
# §13 — zero FX difference
# ---------------------------------------------------------------------------

class ZeroFXTests(FXFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd, cls.eur = cls._seed()
        cls.acc = cls._accounts()

    def test_zero_fx_has_no_gain_or_loss_line(self):
        entry = self._settle("JE-FX-ZERO", historical_rate="70", settlement_rate="70")
        codes = list(entry.lines.values_list("account__code", flat=True))
        self.assertNotIn("8100", codes)
        self.assertNotIn("8200", codes)
        self.assertEqual(entry.lines.count(), 2)
        self.assertEqual(entry.total_debit, Decimal("7000.00"))
        self.assertEqual(entry.total_credit, Decimal("7000.00"))

    def test_zero_fx_payable_has_no_gain_or_loss_line(self):
        entry = self._settle("JE-FX-ZEROP", obligation_kind="PAYABLE",
                             obligation_account=self.acc["2110"],
                             historical_rate="70", settlement_rate="70")
        self.assertEqual(entry.lines.count(), 2)
        self.assertFalse(entry.lines.filter(account__code__in=["8100", "8200"]).exists())

    def test_base_currency_obligation_never_produces_fx(self):
        entry = self._settle("JE-FX-BASE", obligation_currency=self.afn,
                             settlement_currency=self.afn,
                             historical_rate="1", settlement_rate="1")
        self.assertEqual(entry.lines.count(), 2)
        self.assertFalse(entry.lines.filter(account__code__in=["8100", "8200"]).exists())


# ---------------------------------------------------------------------------
# §7 — partial settlement
# ---------------------------------------------------------------------------

class PartialSettlementTests(FXFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd, cls.eur = cls._seed()
        cls.acc = cls._accounts()

    def test_partial_gain_only_on_settled_portion(self):
        entry = self._settle("JE-FX-PART", settlement_amount="40.00",
                             historical_rate="70", settlement_rate="72")
        self.assertEqual(entry.total_debit, Decimal("2880.00"))
        self.assertEqual(entry.lines.get(account__code="8100").credit, Decimal("80.00"))
        self.assertEqual(entry.lines.get(account__code="1310").credit, Decimal("2800.00"))

    def test_unsettled_remainder_books_nothing(self):
        plan = self._plan(obligation_amount="100.00", settlement_amount="40.00",
                          historical_rate="70", settlement_rate="72")
        self.assertEqual(plan["unsettled_amount"], Decimal("60.00"))
        self.assertEqual(plan["difference"], Decimal("80.00"))
        self.assertNotEqual(plan["difference"], Decimal("200.00"))

    def test_full_settlement_has_no_remainder(self):
        plan = self._plan(obligation_amount="100.00", settlement_amount="100.00")
        self.assertEqual(plan["unsettled_amount"], Decimal("0.00"))


# ---------------------------------------------------------------------------
# §5 — currency safety
# ---------------------------------------------------------------------------

class CurrencySafetyTests(FXFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd, cls.eur = cls._seed()
        cls.acc = cls._accounts()

    def test_cross_currency_settlement_rejected(self):
        before = self._state()
        with self.assertRaises(JournalValidationError) as ctx:
            self._plan(settlement_currency=self.eur)
        self.assertIn("Cross-currency settlement is not supported", str(ctx.exception))
        self.assertEqual(before, self._state())

    def test_cross_currency_posting_rejected(self):
        with self.assertRaises(JournalValidationError):
            self._settle("JE-FX-XCUR", settlement_currency=self.eur)
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_inactive_currency_rejected(self):
        self.usd.is_active = False
        self.usd.save(update_fields=["is_active"])
        with self.assertRaises(JournalValidationError):
            self._plan()
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_base_currency_rate_must_be_one(self):
        with self.assertRaises(JournalValidationError) as ctx:
            self._plan(obligation_currency=self.afn, settlement_currency=self.afn,
                       historical_rate="70", settlement_rate="70")
        self.assertIn("must be 1.0000", str(ctx.exception))


# ---------------------------------------------------------------------------
# §14 — invalid input
# ---------------------------------------------------------------------------

class InvalidInputTests(FXFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd, cls.eur = cls._seed()
        cls.acc = cls._accounts()

    def _rejects(self, **overrides):
        before = self._state()
        with self.assertRaises(JournalValidationError):
            self._plan(**overrides)
        self.assertEqual(before, self._state(), "calculation must not touch the database")

    def test_zero_historical_rate_rejected(self):
        self._rejects(historical_rate="0")

    def test_negative_historical_rate_rejected(self):
        self._rejects(historical_rate="-70")

    def test_zero_settlement_rate_rejected(self):
        self._rejects(settlement_rate="0")

    def test_negative_settlement_rate_rejected(self):
        self._rejects(settlement_rate="-72")

    def test_missing_historical_rate_rejected(self):
        self._rejects(historical_rate=None)

    def test_missing_settlement_rate_rejected(self):
        self._rejects(settlement_rate=None)

    def test_missing_currency_rejected(self):
        with self.assertRaises(JournalValidationError):
            self._plan(obligation_currency=None)

    def test_negative_obligation_amount_rejected(self):
        self._rejects(obligation_amount="-100.00")

    def test_zero_obligation_amount_rejected(self):
        self._rejects(obligation_amount="0.00")

    def test_negative_settlement_amount_rejected(self):
        self._rejects(settlement_amount="-40.00")

    def test_settlement_exceeding_obligation_rejected(self):
        self._rejects(obligation_amount="100.00", settlement_amount="140.00")

    def test_invalid_obligation_kind_rejected(self):
        self._rejects(obligation_kind="EQUITY")

    def test_invalid_gain_account_rejected(self):
        self._rejects(gain_account=self.acc["1110"])

    def test_swapped_gain_loss_accounts_rejected(self):
        self._rejects(gain_account=self.acc["8200"])
        self._rejects(loss_account=self.acc["8100"])

    def test_contra_revenue_is_not_an_fx_gain_account(self):
        self._rejects(gain_account=self.acc["4200"])

    def test_inactive_2400_rejected_as_obligation_account(self):
        self._rejects(obligation_account=self.acc["2400"])

    def test_inactive_2400_rejected_as_settlement_account(self):
        self._rejects(settlement_account=self.acc["2400"])

    def test_inactive_2400_rejected_as_gain_account(self):
        self._rejects(gain_account=self.acc["2400"])

    def test_same_account_on_both_sides_rejected(self):
        self._rejects(obligation_account=self.acc["1310"], settlement_account=self.acc["1310"])

    def test_unpersisted_account_rejected(self):
        self._rejects(obligation_account=Account(code="9999", name="Ghost",
                                                 account_type=str(AccountType.ASSET)))

    def test_non_account_rejected(self):
        self._rejects(settlement_account="1110")

    def test_float_amount_rejected_by_money_contract(self):
        with self.assertRaises(TypeError):
            self._plan(obligation_amount=100.0)

    def test_float_rate_rejected_by_money_contract(self):
        with self.assertRaises(TypeError):
            self._plan(settlement_rate=72.0)

    def test_2400_never_receives_a_posting(self):
        with self.assertRaises(JournalValidationError):
            self._settle("JE-FX-2400", settlement_account=self.acc["2400"])
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(JournalLine.objects.filter(account__code="2400").count(), 0)

    def test_unbalanced_generated_fx_journal_is_rejected(self):
        """If the constructed lines ever fail to balance, nothing is persisted."""
        broken_plan = self._plan()
        broken_plan["lines"][0]["debit"] = Decimal("9999.00")  # corrupt the plan
        with mock.patch("accounting.fx.compute_realized_fx", return_value=broken_plan):
            with self.assertRaises(JournalValidationError) as ctx:
                self._settle("JE-FX-BROKEN")
        self.assertIn("Total debit must equal total credit", str(ctx.exception))
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(JournalLine.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)


# ---------------------------------------------------------------------------
# §9 / §10 — posting contract and rate preservation
# ---------------------------------------------------------------------------

class FXPostingContractTests(FXFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd, cls.eur = cls._seed()
        cls.acc = cls._accounts()

    def test_posting_emits_one_post_audit(self):
        entry = self._settle("JE-FX-AUDIT")
        audits = AuditEvent.objects.filter(entity="JournalEntry", entity_id=str(entry.id))
        self.assertEqual(audits.count(), 1)
        self.assertEqual(audits.first().action, AuditAction.POST)

    def test_stored_totals_match_lines(self):
        entry = self._settle("JE-FX-TOTALS")
        self.assertEqual(verify_entry_totals(entry),
                         {"total_debit": Decimal("7200.00"), "total_credit": Decimal("7200.00")})
        self.assertEqual(entry.status, JournalStatus.POSTED)

    def test_source_metadata_stored(self):
        entry = self._settle("JE-FX-SRC")
        self.assertEqual(entry.source_type, "FX")
        self.assertEqual(entry.source_id, "OBL-1")
        self.assertEqual([e.number for e in journals_by_source("FX", "OBL-1")], [entry.number])
        trace = trace_source(entry)
        self.assertEqual(trace["entry_number"], entry.number)
        self.assertEqual(trace["source_type"], "FX")

    def test_rates_preserved_in_description_and_references(self):
        entry = self._settle("JE-FX-RATES")
        self.assertIn("72.0000", entry.description)
        self.assertIn("70.0000", entry.description)
        references = " ".join(entry.lines.values_list("reference", flat=True))
        self.assertIn("USD@72.0000", references)
        self.assertIn("USD@70.0000", references)

    def test_posted_fx_journal_is_immutable(self):
        entry = self._settle("JE-FX-IMMUT")
        from .models import PostedImmutabilityError
        entry.description = "tampered"
        with self.assertRaises(PostedImmutabilityError):
            entry.save()

    def test_no_business_document_is_fabricated(self):
        """No numbering, no documents: only the caller's journal number is used."""
        before = NumberSequence.objects.count()
        self._settle("JE-FX-NODOC")
        self.assertEqual(NumberSequence.objects.count(), before)


class HistoricalRatePreservationTests(FXFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd, cls.eur = cls._seed()
        cls.acc = cls._accounts()

    def test_obligation_rate_snapshot_survives_later_rate_changes(self):
        from .services import post_journal
        obligation = post_journal(
            number="JE-OBL-1", posting_date="2026-01-01", description="USD sale",
            lines=[{"account": self.acc["1310"], "debit": "100.00"},
                   {"account": self.acc["4110"], "credit": "100.00"}],
            currency=self.usd, rate="70.0000", rate_date="2026-01-01",
            source_type="SALE", source_id="INV-1",
        )
        self.assertEqual(obligation.rate, Decimal("70.0000"))
        self.assertEqual(obligation.afn_total, Decimal("7000.00"))

        # "current" rate moves to 75 — historical row must not move.
        ExchangeRate.objects.create(source_currency=self.usd, target_currency=self.afn,
                                   rate=Decimal("75.0000"), effective_date="2026-02-01")
        obligation.refresh_from_db()
        self.assertEqual(obligation.rate, Decimal("70.0000"))
        self.assertEqual(obligation.total_debit, Decimal("100.00"))
        self.assertEqual(obligation.afn_total, Decimal("7000.00"))
        self.assertEqual(obligation.rate_direction, "USD->AFN")

        settlement = self._settle("JE-SETTLE-1", historical_rate="70.0000", settlement_rate="72.0000")
        self.assertEqual(settlement.afn_total, Decimal("7200.00"))
        self.assertIn("72.0000", settlement.description)

        obligation.refresh_from_db()
        self.assertEqual(obligation.rate, Decimal("70.0000"))
        self.assertEqual(obligation.afn_total, Decimal("7000.00"))
        self.assertEqual(obligation.status, JournalStatus.POSTED)

    def test_fx_difference_uses_historical_vs_settlement_not_current(self):
        ExchangeRate.objects.create(source_currency=self.usd, target_currency=self.afn,
                                   rate=Decimal("99.0000"), effective_date="2026-02-15")
        plan = self._plan(historical_rate="70", settlement_rate="72")
        self.assertEqual(plan["difference"], Decimal("200.00"))

    def test_no_unrealized_restatement_of_open_balances(self):
        from .services import post_journal
        post_journal(number="JE-OPEN-1", posting_date="2026-01-01", description="USD sale",
                     lines=[{"account": self.acc["1310"], "debit": "100.00"},
                            {"account": self.acc["4110"], "credit": "100.00"}],
                     currency=self.usd, rate="70.0000", rate_date="2026-01-01")
        before = account_balance(self.acc["1310"])
        ExchangeRate.objects.create(source_currency=self.usd, target_currency=self.afn,
                                   rate=Decimal("88.0000"), effective_date="2026-03-01")
        after = account_balance(self.acc["1310"])
        self.assertEqual(before, after)
        self.assertEqual(after["total_debit"], Decimal("100.00"))


# ---------------------------------------------------------------------------
# §15 — reversal compatibility
# ---------------------------------------------------------------------------

class FXReversalTests(FXFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd, cls.eur = cls._seed()
        cls.acc = cls._accounts()

    def test_fx_journal_reversal(self):
        entry = self._settle("JE-FX-REV")
        before = {
            "lines": [(l.account.code, str(l.debit), str(l.credit), l.reference)
                      for l in entry.lines.all().order_by("id")],
            "rate": entry.rate, "afn_total": entry.afn_total,
            "rate_direction": entry.rate_direction, "rate_date": entry.rate_date,
        }
        reversal = reverse_journal(entry, "fx test reversal", None)
        entry.refresh_from_db()

        self.assertEqual(entry.status, JournalStatus.REVERSED)
        self.assertEqual(reversal.status, JournalStatus.POSTED)
        self.assertEqual(reversal.reverses_id, entry.pk)
        self.assertEqual(
            [(l.account.code, str(l.debit), str(l.credit), l.reference)
             for l in entry.lines.all().order_by("id")], before["lines"])
        self.assertEqual(entry.rate, before["rate"])
        self.assertEqual(entry.afn_total, before["afn_total"])
        self.assertEqual(entry.rate_direction, before["rate_direction"])
        self.assertEqual(entry.rate_date, before["rate_date"])

        # mirrored and balanced
        self.assertEqual(reversal.total_debit, entry.total_credit)
        self.assertEqual(reversal.total_credit, entry.total_debit)
        self.assertEqual(verify_entry_totals(reversal)["total_debit"], Decimal("7200.00"))
        for original in entry.lines.all():
            mirror = reversal.lines.get(account_id=original.account_id)
            self.assertEqual(mirror.debit, original.credit)
            self.assertEqual(mirror.credit, original.debit)

        # pair nets to zero
        self.assertEqual(account_balance(self.acc["1110"])["balance"], Decimal("0.00"))
        self.assertEqual(account_balance(self.acc["8100"])["balance"], Decimal("0.00"))

        # exactly one REVERSE audit, original POST audit untouched
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.POST,
                                                   entity_id=str(entry.id)).count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.REVERSE,
                                                   entity_id=str(entry.id)).count(), 1)
        # still traceable
        self.assertIn(entry.number, [e.number for e in journals_by_source("FX", "OBL-1")])


# ---------------------------------------------------------------------------
# §24 — idempotency
# ---------------------------------------------------------------------------

class FXIdempotencyTests(FXFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd, cls.eur = cls._seed()
        cls.acc = cls._accounts()

    def test_exact_retry_returns_original(self):
        first = self._settle("JE-FX-IDEM", idempotency_key="fx-key-1")
        second = self._settle("JE-FX-IDEM", idempotency_key="fx-key-1")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(JournalLine.objects.count(), 3)
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.POST).count(), 1)
        self.assertEqual(account_balance(self.acc["8100"])["balance"], Decimal("200.00"))

    def test_changed_request_same_key_rejected(self):
        self._settle("JE-FX-IDEM2", idempotency_key="fx-key-2", settlement_rate="72")
        with self.assertRaises(JournalValidationError) as ctx:
            self._settle("JE-FX-IDEM2", idempotency_key="fx-key-2", settlement_rate="75")
        self.assertIn("already used for a different operation", str(ctx.exception))
        self.assertEqual(JournalEntry.objects.count(), 1)

    def test_failure_releases_the_key(self):
        with mock.patch("accounting.services._audit_post", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self._settle("JE-FX-FAIL", idempotency_key="fx-key-3")
        self.assertEqual(IdempotencyRecord.objects.filter(key="fx-key-3").count(), 0)
        entry = self._settle("JE-FX-FAIL", idempotency_key="fx-key-3")
        self.assertEqual(entry.idempotency_key, "fx-key-3")
        self.assertEqual(JournalEntry.objects.count(), 1)

    def test_duplicate_number_with_fresh_key_raises(self):
        self._settle("JE-FX-DUP", idempotency_key="dup-a")
        with self.assertRaises(IntegrityError):
            self._settle("JE-FX-DUP", idempotency_key="dup-b")
        self.assertEqual(IdempotencyRecord.objects.filter(key="dup-b").count(), 0)
        self._settle("JE-FX-DUP2", idempotency_key="dup-b")
        self.assertEqual(JournalEntry.objects.count(), 2)

    def test_invalid_key_rejected(self):
        with self.assertRaises(JournalValidationError):
            self._settle("JE-FX-BADKEY", idempotency_key="")

    def test_orphaned_reservation_does_not_return_wrong_entry(self):
        first = self._settle("JE-FX-ORPHAN", idempotency_key="fx-orphan")
        # The settlement record protects its journal (see the test below), so the
        # orphan is created the way only a bulk operation could: queryset delete.
        FXSettlement.objects.filter(entry_id=first.pk).delete()
        JournalLine.objects.filter(entry_id=first.pk).delete()
        JournalEntry.objects.filter(pk=first.pk).delete()
        with self.assertRaises(DuplicateOperationError):
            self._settle("JE-FX-ORPHAN", idempotency_key="fx-orphan")

    def test_settlement_record_protects_its_journal(self):
        entry = self._settle("JE-FX-PROTECT")
        self.assertTrue(FXSettlement.objects.filter(entry_id=entry.pk).exists())
        with self.assertRaises(ProtectedError):
            JournalEntry.objects.filter(pk=entry.pk).delete()


# ---------------------------------------------------------------------------
# §23 — genuine transaction-level rollback (TransactionTestCase)
# ---------------------------------------------------------------------------

class FXAtomicRollbackTests(FXFixture, TransactionTestCase):
    def setUp(self):
        self.afn, self.usd, self.eur = self._seed()
        self.acc = self._accounts()

    def test_failure_after_persist_rolls_back_everything(self):
        before = self._state()
        self.assertEqual(before["entries"], 0)

        with mock.patch("accounting.services._audit_post", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                self._settle("JE-FX-ATOMIC", idempotency_key="fx-atomic")

        after = self._state()
        self.assertEqual(before, after, "no partial accounting state may survive")
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(JournalLine.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)
        self.assertEqual(account_balance(self.acc["1110"])["balance"], Decimal("0.00"))
        self.assertEqual(account_balance(self.acc["8100"])["balance"], Decimal("0.00"))

        # the key is reusable and the retry now succeeds cleanly
        entry = self._settle("JE-FX-ATOMIC", idempotency_key="fx-atomic")
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(JournalLine.objects.count(), 3)
        self.assertEqual(entry.afn_total, Decimal("7200.00"))

    def test_failure_before_persist_rolls_back_everything(self):
        before = self._state()
        with mock.patch("accounting.fx.compute_realized_fx", side_effect=RuntimeError("early failure")):
            with self.assertRaises(RuntimeError):
                self._settle("JE-FX-EARLY", idempotency_key="fx-early")
        self.assertEqual(before, self._state())

    def test_no_numbering_side_effects_on_rollback(self):
        before = NumberSequence.objects.count()
        with mock.patch("accounting.services._audit_post", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self._settle("JE-FX-NUM", idempotency_key="fx-num")
        self.assertEqual(NumberSequence.objects.count(), before)


# ---------------------------------------------------------------------------
# User ruling L1 — settlement rate is manual transaction-time structured data
# ---------------------------------------------------------------------------

class ManualSettlementRateTests(FXFixture, TestCase):
    """The settlement rate is entered by the user and persisted structurally."""

    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd, cls.eur = cls._seed()
        cls.acc = cls._accounts()

    def _settle(self, number="JE-MR", **overrides):
        params = dict(
            obligation_kind="RECEIVABLE",
            obligation_account=self.acc["1310"], obligation_amount="100.00",
            obligation_currency=self.usd, historical_rate="70",
            settlement_account=self.acc["1110"], settlement_amount="100.00",
            settlement_currency=self.usd, settlement_rate="72.5000",
        )
        params.update(overrides)
        call = dict(number=number, posting_date="2026-04-01",
                    description="manual rate settlement", source_type="FX", source_id="MR-1")
        for key in ("description", "reference"):
            if key in params:
                call[key] = params.pop(key)
        return post_realized_fx_settlement(**call, **params)

    # (1) accepted --------------------------------------------------------
    def test_manual_settlement_rate_is_accepted(self):
        entry = self._settle("JE-MR-ACC")
        self.assertEqual(entry.status, JournalStatus.POSTED)
        self.assertEqual(entry.lines.get(account__code="8100").credit, Decimal("250.00"))

    # (2) persisted structurally -----------------------------------------
    def test_manual_settlement_rate_is_persisted_structurally(self):
        entry = self._settle("JE-MR-PERSIST")
        record = FXSettlement.objects.get(entry=entry)
        self.assertEqual(record.settlement_rate, Decimal("72.5000"))
        self.assertEqual(record.source_currency.code, "USD")
        self.assertEqual(record.source_amount, Decimal("100.00"))
        self.assertEqual(record.target_currency.code, "AFN")
        self.assertEqual(record.target_amount, Decimal("7250.00"))
        self.assertEqual(record.rate_direction, "USD->AFN")
        self.assertEqual(record.historical_rate, Decimal("70.0000"))
        self.assertEqual(record.transaction_date, date(2026, 4, 1))
        self.assertEqual(record.obligation_account.code, "1310")
        self.assertEqual(record.settlement_account.code, "1110")
        self.assertEqual(record.fx_account.code, "8100")
        self.assertEqual(record.direction, FX_GAIN)
        self.assertEqual(record.carrying_value, Decimal("7000.00"))
        self.assertEqual(record.settlement_value, Decimal("7250.00"))
        self.assertEqual(record.difference, Decimal("250.00"))
        # the journal keeps its OWN accounting-currency snapshot
        entry.refresh_from_db()
        self.assertEqual(entry.rate, Decimal("1.0000"))
        self.assertEqual(entry.rate_direction, "AFN->AFN")
        self.assertEqual(entry.currency.code, "AFN")

    # (3) not only text ----------------------------------------------------
    def test_rate_is_not_stored_only_in_description_or_reference(self):
        entry = self._settle("JE-MR-TEXT", description="", reference="")
        record = FXSettlement.objects.get(entry=entry)
        self.assertEqual(record.description, "")
        self.assertEqual(record.reference, "")
        self.assertEqual(record.settlement_rate, Decimal("72.5000"))
        # queryable/filterable/reportable as structured data
        self.assertEqual(
            [r.entry.number for r in FXSettlement.objects.filter(settlement_rate=Decimal("72.5000"))],
            [entry.number])
        self.assertEqual(
            [r.entry.number for r in FXSettlement.objects.filter(rate_direction="USD->AFN")],
            [entry.number])

    # (4) Example A: 50,000 AFN -> USD @ 70 --------------------------------
    def test_example_a_50000_afn_to_usd_at_70(self):
        entry = post_fx_conversion(
            number="JE-CONV-A", posting_date="2026-04-02",
            source_account=self.acc["1110"], source_amount="50000.00", source_currency=self.afn,
            target_account=self.acc["1210"], target_currency=self.usd, settlement_rate="70",
            description="50,000 AFN converted to USD at rate 70 and received by Exchange X",
            reference="EXCH-X", source_type="EXCHANGE", source_id="CONV-A")
        record = FXSettlement.objects.get(entry=entry)
        self.assertEqual(record.settlement_rate, Decimal("70.0000"))
        self.assertEqual(record.source_currency.code, "AFN")
        self.assertEqual(record.source_amount, Decimal("50000.00"))
        self.assertEqual(record.target_currency.code, "USD")
        self.assertEqual(record.target_amount, Decimal("714.29"))   # 50000 / 70, Half-Up
        self.assertEqual(record.rate_direction, "AFN->USD")
        self.assertEqual(record.kind, FX_CONVERSION)
        self.assertEqual(record.direction, FX_NONE)
        self.assertIsNone(record.fx_account)
        self.assertEqual(record.settlement_account.code, "1210")
        self.assertEqual(record.obligation_account.code, "1110")
        # journal: AFN book values, balanced, its own snapshot untouched
        self.assertEqual(entry.total_debit, Decimal("50000.00"))
        self.assertEqual(entry.total_credit, Decimal("50000.00"))
        self.assertEqual(entry.rate, Decimal("1.0000"))
        self.assertEqual(entry.rate_direction, "AFN->AFN")
        self.assertEqual(entry.lines.get(account__code="1210").debit, Decimal("50000.00"))
        self.assertEqual(entry.lines.get(account__code="1110").credit, Decimal("50000.00"))
        self.assertEqual(entry.lines.count(), 2)   # no 8100/8200 on a conversion
        # the description is preserved AND the structured fields stand alone
        self.assertIn("Exchange X", entry.description)
        self.assertEqual(record.description, "50,000 AFN converted to USD at rate 70 and received by Exchange X")
        self.assertEqual(record.reference, "EXCH-X")

    # (5) Example B: 500 USD -> AFN @ 72 -----------------------------------
    def test_example_b_500_usd_to_afn_at_72(self):
        entry = post_realized_fx_settlement(
            number="JE-CONV-B", posting_date="2026-04-03", description="500 USD converted to AFN",
            obligation_kind="RECEIVABLE", obligation_account=self.acc["1310"],
            obligation_amount="500.00", obligation_currency=self.usd, historical_rate="70",
            settlement_account=self.acc["1110"], settlement_amount="500.00",
            settlement_currency=self.usd, settlement_rate="72",
            source_type="EXCHANGE", source_id="CONV-B")
        record = FXSettlement.objects.get(entry=entry)
        self.assertEqual(record.settlement_rate, Decimal("72.0000"))
        self.assertEqual(record.source_amount, Decimal("500.00"))
        self.assertEqual(record.source_currency.code, "USD")
        self.assertEqual(record.target_amount, Decimal("36000.00"))
        self.assertEqual(record.target_currency.code, "AFN")
        self.assertEqual(record.rate_direction, "USD->AFN")
        self.assertEqual(record.difference, Decimal("1000.00"))
        self.assertEqual(record.direction, FX_GAIN)
        self.assertEqual(entry.lines.get(account__code="8100").credit, Decimal("1000.00"))

    def test_example_b_zero_fx_variant(self):
        """500 USD -> AFN at its own carrying rate: 36,000 AFN, no gain/loss line."""
        entry = post_realized_fx_settlement(
            number="JE-CONV-B0", posting_date="2026-04-03", description="500 USD converted at carrying rate",
            obligation_kind="RECEIVABLE", obligation_account=self.acc["1310"],
            obligation_amount="500.00", obligation_currency=self.usd, historical_rate="72",
            settlement_account=self.acc["1110"], settlement_amount="500.00",
            settlement_currency=self.usd, settlement_rate="72")
        record = FXSettlement.objects.get(entry=entry)
        self.assertEqual(record.settlement_rate, Decimal("72.0000"))
        self.assertEqual(record.target_amount, Decimal("36000.00"))
        self.assertEqual(record.direction, FX_NONE)
        self.assertEqual(entry.lines.count(), 2)

    # (6) direction preserved ----------------------------------------------
    def test_rate_direction_preserved_both_paths(self):
        settle = self._settle("JE-MR-DIR")
        convert = post_fx_conversion(
            number="JE-MR-DIR2", posting_date="2026-04-04",
            source_account=self.acc["1110"], source_amount="1000.00", source_currency=self.afn,
            target_account=self.acc["1210"], target_currency=self.usd, settlement_rate="70")
        self.assertEqual(FXSettlement.objects.get(entry=settle).rate_direction, "USD->AFN")
        self.assertEqual(FXSettlement.objects.get(entry=convert).rate_direction, "AFN->USD")

    # (7) later global rate never rewrites history --------------------------
    def test_later_global_rate_does_not_change_settlement(self):
        entry = self._settle("JE-MR-HIST")
        before = {
            "settlement_rate": FXSettlement.objects.get(entry=entry).settlement_rate,
            "historical_rate": FXSettlement.objects.get(entry=entry).historical_rate,
            "target_amount": FXSettlement.objects.get(entry=entry).target_amount,
            "journal_rate": entry.rate,
            "journal_afn": entry.afn_total,
        }
        ExchangeRate.objects.create(source_currency=self.usd, target_currency=self.afn,
                                   rate=Decimal("75.0000"), effective_date="2026-05-01")
        ExchangeRate.objects.create(source_currency=self.usd, target_currency=self.afn,
                                   rate=Decimal("80.0000"), effective_date="2026-06-01")
        entry.refresh_from_db()
        record = FXSettlement.objects.get(entry=entry)
        self.assertEqual(record.settlement_rate, Decimal("72.5000"))
        self.assertEqual(record.historical_rate, Decimal("70.0000"))
        self.assertEqual(record.target_amount, Decimal("7250.00"))
        self.assertEqual(entry.rate, Decimal("1.0000"))
        self.assertEqual(entry.afn_total, Decimal("7250.00"))
        self.assertEqual(before["settlement_rate"], record.settlement_rate)
        # the settlement rate is NOT taken from the ExchangeRate table
        self.assertEqual(FXSettlement.objects.filter(settlement_rate=Decimal("75.0000")).count(), 0)

    def test_conversion_rate_not_taken_from_exchange_rate_table(self):
        ExchangeRate.objects.create(source_currency=self.usd, target_currency=self.afn,
                                   rate=Decimal("88.0000"), effective_date="2026-04-01")
        entry = post_fx_conversion(
            number="JE-MR-NOTBL", posting_date="2026-04-02",
            source_account=self.acc["1110"], source_amount="70000.00", source_currency=self.afn,
            target_account=self.acc["1210"], target_currency=self.usd, settlement_rate="70")
        self.assertEqual(FXSettlement.objects.get(entry=entry).settlement_rate, Decimal("70.0000"))
        self.assertEqual(FXSettlement.objects.get(entry=entry).target_amount, Decimal("1000.00"))

    # (14) invalid settlement rates ----------------------------------------
    def test_conversion_zero_rate_rejected(self):
        with self.assertRaises(JournalValidationError):
            self._convert(settlement_rate="0")
        self.assertEqual(FXSettlement.objects.count(), 0)

    def test_conversion_negative_rate_rejected(self):
        with self.assertRaises(JournalValidationError):
            self._convert(settlement_rate="-70")

    def test_conversion_missing_rate_rejected(self):
        with self.assertRaises(JournalValidationError):
            self._convert(settlement_rate=None)

    def test_conversion_float_rate_rejected(self):
        with self.assertRaises(TypeError):
            self._convert(settlement_rate=70.0)

    def test_conversion_zero_amount_rejected(self):
        with self.assertRaises(JournalValidationError):
            self._convert(source_amount="0.00")

    def test_conversion_negative_amount_rejected(self):
        with self.assertRaises(JournalValidationError):
            self._convert(source_amount="-100.00")

    def test_conversion_inactive_2400_rejected(self):
        with self.assertRaises(JournalValidationError):
            self._convert(target_account=self.acc["2400"])

    # (15) cross-currency / unsupported shapes ------------------------------
    def test_conversion_cross_currency_rejected(self):
        with self.assertRaises(JournalValidationError):
            self._convert(source_currency=self.usd, target_currency=self.eur)
        self.assertEqual(FXSettlement.objects.count(), 0)

    def test_conversion_same_currency_rejected(self):
        with self.assertRaises(JournalValidationError):
            self._convert(target_currency=self.afn)

    def test_foreign_to_base_must_use_the_realized_path(self):
        with self.assertRaises(JournalValidationError) as ctx:
            self._convert(source_currency=self.usd, target_currency=self.afn)
        self.assertIn("post_realized_fx_settlement", str(ctx.exception))
        self.assertEqual(FXSettlement.objects.count(), 0)

    def test_conversion_same_account_rejected(self):
        with self.assertRaises(JournalValidationError):
            self._convert(target_account=self.acc["1110"])

    def test_conversion_inactive_currency_rejected(self):
        self.usd.is_active = False
        self.usd.save(update_fields=["is_active"])
        with self.assertRaises(JournalValidationError):
            self._convert()

    # (18) reversal preserves the original snapshot -------------------------
    def test_reversal_preserves_settlement_rate_snapshot(self):
        entry = self._settle("JE-MR-REV")
        record = FXSettlement.objects.get(entry=entry)
        snapshot = {
            "settlement_rate": record.settlement_rate,
            "historical_rate": record.historical_rate,
            "source_amount": record.source_amount,
            "target_amount": record.target_amount,
            "rate_direction": record.rate_direction,
            "direction": record.direction,
            "transaction_date": record.transaction_date,
            "created_at": record.created_at,
        }
        reverse_journal(entry, "manual rate reversal", None)
        entry.refresh_from_db()
        record.refresh_from_db()
        self.assertEqual(entry.status, JournalStatus.REVERSED)
        self.assertEqual(entry.rate, Decimal("1.0000"))
        for field, value in snapshot.items():
            self.assertEqual(getattr(record, field), value)
        # the reversal has no settlement record of its own
        reversal = JournalEntry.objects.get(reverses=entry)
        self.assertFalse(FXSettlement.objects.filter(entry=reversal).exists())

    # (19) audit integrity ---------------------------------------------------
    def test_audit_records_remain_correct(self):
        entry = self._settle("JE-MR-AUD", idempotency_key="mr-audit")
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.POST,
                                                   entity_id=str(entry.id)).count(), 1)
        retry = self._settle("JE-MR-AUD", idempotency_key="mr-audit")
        self.assertEqual(retry.pk, entry.pk)
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.POST,
                                                   entity_id=str(entry.id)).count(), 1)
        self.assertEqual(FXSettlement.objects.filter(entry=entry).count(), 1)
        reverse_journal(entry, "audit check", None)
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.REVERSE,
                                                   entity_id=str(entry.id)).count(), 1)

    def test_settlement_record_is_immutable(self):
        entry = self._settle("JE-MR-IMMUT")
        record = FXSettlement.objects.get(entry=entry)
        from .models import PostedImmutabilityError
        record.settlement_rate = Decimal("99.0000")
        with self.assertRaises(PostedImmutabilityError):
            record.save()
        with self.assertRaises(PostedImmutabilityError):
            record.delete()

    # (25) revenue posting account ------------------------------------------
    def test_revenue_uses_4110_not_non_posting_4100(self):
        from .services import post_journal
        self.assertFalse(Account.objects.get(code="4100").is_posting)
        self.assertTrue(Account.objects.get(code="4110").is_posting)
        with self.assertRaises(JournalValidationError):
            post_journal(number="JE-REV-4100", posting_date="2026-04-05", description="revenue on group account",
                         lines=[{"account": self.acc["1310"], "debit": "100.00"},
                                {"account": self.acc["4100"], "credit": "100.00"}],
                         currency=self.usd, rate="70.0000", rate_date="2026-04-05")
        entry = post_journal(number="JE-REV-4110", posting_date="2026-04-05", description="revenue on posting account",
                             lines=[{"account": self.acc["1310"], "debit": "100.00"},
                                    {"account": self.acc["4110"], "credit": "100.00"}],
                             currency=self.usd, rate="70.0000", rate_date="2026-04-05")
        self.assertEqual(entry.status, JournalStatus.POSTED)
        self.assertEqual(account_balance(self.acc["4110"])["balance"], Decimal("100.00"))
        self.assertEqual(account_balance(self.acc["4100"])["lines_count"], 0)

    def _convert(self, **overrides):
        params = dict(
            number="JE-CONV-X", posting_date="2026-04-02",
            source_account=self.acc["1110"], source_amount="1000.00", source_currency=self.afn,
            target_account=self.acc["1210"], target_currency=self.usd, settlement_rate="70",
        )
        params.update(overrides)
        return post_fx_conversion(**params)
