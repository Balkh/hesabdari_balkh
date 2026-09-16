"""Phase 5 — Party Ledger tests (§35.1-40).

Attribution, derivation, dual-role, net position, opening, immutability,
traceability, reconciliation. No future engines are simulated beyond
representative journals; payment/invoice/allocation engines stay out.
Frozen suites untouched.
"""

from datetime import date
from decimal import Decimal
from itertools import count
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounting.balances import account_balance, journals_by_source
from accounting.coa import seed_chart_of_accounts
from accounting.models import (
    Account,
    JournalEntry,
    JournalLine,
    JournalStatus,
    PostedImmutabilityError,
)
from accounting.services import post_journal, reverse_journal
from currencies.models import Currency
from documents.services import next_document_number
from parties.services import create_party
from security.models import AuditAction, AuditEvent

from .ledger import (
    net_position,
    party_balance,
    party_statement,
    reconcile_party_ledger,
)
from .models import BalanceType, PartyLedgerAttribution
from .services import (
    PartyLedgerValidationError,
    attribute_journal_line,
    open_party_balance,
)


class LedgerFixture:
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(
            code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")
        cls.user = get_user_model().objects.create_user(
            "pl5user", password="x")

    def setUp(self):
        self._numbers = count(1)
        self.customer = create_party(
            name="Karimi Store", is_customer=True, user=self.user)
        self.supplier = create_party(
            name="Hari Dunya", is_supplier=True, user=self.user)
        self.both = create_party(
            name="ABC Trading", is_customer=True, is_supplier=True,
            user=self.user)

    def _number(self, tag="T5"):
        return f"{tag}-{next(self._numbers):04d}"

    def _post(self, currency, lines, posting_date=None, source_type="",
              source_id="", rate=None, tag="T5"):
        kwargs = {}
        if not currency.is_base:
            kwargs = {"rate": rate if rate is not None else Decimal("70"),
                      "rate_date": posting_date or date(2026, 1, 1)}
        return post_journal(
            number=self._number(tag),
            posting_date=posting_date or date(2026, 1, 1),
            description="test journal", lines=lines,
            source_type=source_type, source_id=source_id,
            currency=currency, created_by=self.user, **kwargs)

    def _account(self, code):
        return Account.objects.get(code=code)

    def _sale_effect(self, party, amount, currency=None, day=1):
        currency = currency or self.afn
        entry = self._post(
            currency,
            [{"account": self._account("1310"), "debit": amount},
             {"account": self._account("4110"), "credit": amount}],
            posting_date=date(2026, 1, day),
            source_type="SIMULATED_SALE", source_id=self._number("SIM"))
        line = entry.lines.get(account__code="1310")
        attribute_journal_line(line, party=party, user=self.user)
        return entry

    def _payment_effect(self, party, amount, currency=None, day=2):
        currency = currency or self.afn
        entry = self._post(
            currency,
            [{"account": self._account("1110"), "debit": amount},
             {"account": self._account("1310"), "credit": amount}],
            posting_date=date(2026, 1, day),
            source_type="SIMULATED_PAYMENT", source_id=self._number("SIM"))
        line = entry.lines.get(account__code="1310")
        attribute_journal_line(line, party=party, user=self.user)
        return entry


class AttributionTests(LedgerFixture, TestCase):
    def test_01_valid_attribution(self):
        entry = self._sale_effect(self.customer, Decimal("5000"))
        attribution = PartyLedgerAttribution.objects.get(
            journal_line__entry=entry)
        self.assertEqual(attribution.party, self.customer)
        self.assertIsNotNone(attribution.created_at)
        event = AuditEvent.objects.get(
            action=AuditAction.CREATE, entity="PartyLedgerAttribution")
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.new_state["party_name"], "Karimi Store")
        self.assertEqual(event.new_state["balance_type"], "RECEIVABLE")

    def test_02_non_party_account_rejected(self):
        entry = self._post(
            self.afn,
            [{"account": self._account("1310"), "debit": Decimal("100")},
             {"account": self._account("4110"), "credit": Decimal("100")}])
        revenue_line = entry.lines.get(account__code="4110")
        with self.assertRaises(PartyLedgerValidationError):
            attribute_journal_line(
                revenue_line, party=self.customer, user=self.user)
        self.assertEqual(PartyLedgerAttribution.objects.count(), 0)

    def test_03_unsupported_account_rejected(self):
        entry = self._post(
            self.afn,
            [{"account": self._account("1110"), "debit": Decimal("100")},
             {"account": self._account("3100"), "credit": Decimal("100")}])
        for code in ("1110", "3100"):
            with self.assertRaises(PartyLedgerValidationError):
                attribute_journal_line(
                    entry.lines.get(account__code=code),
                    party=self.customer, user=self.user)
        opening = open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("100"),
            posting_date=date(2026, 1, 1), user=self.user)
        equity_line = opening.lines.get(account__code="3900")
        with self.assertRaises(PartyLedgerValidationError):
            attribute_journal_line(
                equity_line, party=self.customer, user=self.user)
        self.assertEqual(PartyLedgerAttribution.objects.count(), 1)

    def test_04_duplicate_attribution_rejected(self):
        entry = self._sale_effect(self.customer, Decimal("5000"))
        line = entry.lines.get(account__code="1310")
        with self.assertRaises(PartyLedgerValidationError):
            attribute_journal_line(
                line, party=self.supplier, user=self.user)
        with self.assertRaises(PartyLedgerValidationError):
            attribute_journal_line(
                line, party=self.customer, user=self.user)
        self.assertEqual(PartyLedgerAttribution.objects.count(), 1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PartyLedgerAttribution.objects.create(
                    journal_line=line, party=self.supplier)

    def test_05_invalid_party_rejected(self):
        entry = self._post(
            self.afn,
            [{"account": self._account("1310"), "debit": Decimal("100")},
             {"account": self._account("4110"), "credit": Decimal("100")}])
        line = entry.lines.get(account__code="1310")
        with self.assertRaises(PartyLedgerValidationError):
            attribute_journal_line(line, party=424242, user=self.user)
        with self.assertRaises(PartyLedgerValidationError):
            attribute_journal_line(line, party="not-a-party",
                                   user=self.user)
        self.assertEqual(PartyLedgerAttribution.objects.count(), 0)

    def test_06_attribution_immutable(self):
        entry = self._sale_effect(self.customer, Decimal("5000"))
        attribution = PartyLedgerAttribution.objects.get(
            journal_line__entry=entry)
        attribution.party = self.supplier
        with self.assertRaises(PostedImmutabilityError):
            attribution.save()
        with self.assertRaises(PostedImmutabilityError):
            attribution.delete()
        attribution.refresh_from_db()
        self.assertEqual(attribution.party, self.customer)

    def test_07_audit_and_actor_rules(self):
        entry = self._post(
            self.afn,
            [{"account": self._account("2110"), "credit": Decimal("100")},
             {"account": self._account("6100"), "debit": Decimal("100")}])
        line = entry.lines.get(account__code="2110")
        with self.assertRaises(PartyLedgerValidationError):
            attribute_journal_line(
                line, party=self.supplier, user=AnonymousUser())
        attribute_journal_line(line, party=self.supplier)
        event = AuditEvent.objects.get(entity="PartyLedgerAttribution")
        self.assertIsNone(event.user)
        self.assertEqual(event.new_state["account_code"], "2110")
        self.assertEqual(event.new_state["balance_type"], "PAYABLE")


class DerivationTests(LedgerFixture, TestCase):
    def test_08_receivable_derivation(self):
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("10000"),
            posting_date=date(2026, 1, 1), user=self.user)
        result = party_balance(
            self.customer, currency=self.afn, balance_type="RECEIVABLE")
        self.assertEqual(result["balance"], Decimal("10000"))
        self.assertEqual(result["total_debit"], Decimal("10000"))
        self.assertEqual(result["normal_balance"], "DEBIT")

    def test_09_payable_derivation(self):
        open_party_balance(
            party=self.supplier, currency=self.afn,
            balance_type="PAYABLE", amount=Decimal("7000"),
            posting_date=date(2026, 1, 1), user=self.user)
        result = party_balance(
            self.supplier, currency=self.afn, balance_type="PAYABLE")
        self.assertEqual(result["balance"], Decimal("7000"))
        self.assertEqual(result["total_credit"], Decimal("7000"))
        self.assertEqual(result["normal_balance"], "CREDIT")

    def test_10_customer_credit_derivation(self):
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="CUSTOMER_CREDIT", amount=Decimal("2000"),
            posting_date=date(2026, 1, 1), user=self.user)
        result = party_balance(
            self.customer, currency=self.afn,
            balance_type="CUSTOMER_CREDIT")
        self.assertEqual(result["balance"], Decimal("2000"))

    def test_11_supplier_advance_derivation(self):
        open_party_balance(
            party=self.supplier, currency=self.usd,
            balance_type="SUPPLIER_ADVANCE", amount=Decimal("3000"),
            posting_date=date(2026, 1, 1), rate=Decimal("70"),
            rate_date=date(2026, 1, 1), user=self.user)
        result = party_balance(
            self.supplier, currency=self.usd,
            balance_type="SUPPLIER_ADVANCE")
        self.assertEqual(result["balance"], Decimal("3000"))
        self.assertEqual(result["currency"], "USD")

    def test_12_currency_separation(self):
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("10000"),
            posting_date=date(2026, 1, 1), user=self.user)
        open_party_balance(
            party=self.customer, currency=self.usd,
            balance_type="RECEIVABLE", amount=Decimal("500"),
            posting_date=date(2026, 1, 1), rate=Decimal("70"),
            rate_date=date(2026, 1, 1), user=self.user)
        afn = party_balance(
            self.customer, currency=self.afn, balance_type="RECEIVABLE")
        usd = party_balance(
            self.customer, currency=self.usd, balance_type="RECEIVABLE")
        self.assertEqual((afn["balance"], usd["balance"]),
                         (Decimal("10000"), Decimal("500")))
        with self.assertRaises(PartyLedgerValidationError):
            party_balance(self.customer, currency="EUR",
                          balance_type="RECEIVABLE")

    def test_13_draft_has_no_effect(self):
        entry = JournalEntry.objects.create(
            number=self._number("DRAFT"), posting_date=date(2026, 1, 1),
            description="draft", status=JournalStatus.DRAFT,
            currency=self.afn)
        line = JournalLine.objects.create(
            entry=entry, account=self._account("1310"),
            debit=Decimal("9999"))
        with self.assertRaises(PartyLedgerValidationError):
            attribute_journal_line(
                line, party=self.customer, user=self.user)
        result = party_balance(
            self.customer, currency=self.afn, balance_type="RECEIVABLE")
        self.assertEqual(result["balance"], Decimal("0"))
        self.assertEqual(result["lines_count"], 0)

    def test_14_reversal_effect(self):
        opening = open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("10000"),
            posting_date=date(2026, 1, 1), user=self.user)
        reversal = reverse_journal(opening, "wrong amount", self.user)
        attribute_journal_line(
            reversal.lines.get(account__code="1310"),
            party=self.customer, user=self.user)
        result = party_balance(
            self.customer, currency=self.afn, balance_type="RECEIVABLE")
        self.assertEqual(result["balance"], Decimal("0"))
        self.assertEqual(result["lines_count"], 2)

    def test_15_chronology(self):
        for day in (10, 1, 5):
            self._sale_effect(self.customer, Decimal("100"), day=day)
        statement = party_statement(
            self.customer, currency=self.afn, balance_type="RECEIVABLE")
        dates = [row["posting_date"] for row in statement["lines"]]
        self.assertEqual(
            dates, [date(2026, 1, 1), date(2026, 1, 5), date(2026, 1, 10)])

    def test_16_running_balance(self):
        self._sale_effect(self.customer, Decimal("10000"), day=1)
        self._payment_effect(self.customer, Decimal("3000"), day=10)
        self._sale_effect(self.customer, Decimal("2000"), day=20)
        statement = party_statement(
            self.customer, currency=self.afn, balance_type="RECEIVABLE")
        runnings = [row["running_balance"] for row in statement["lines"]]
        self.assertEqual(
            runnings, [Decimal("10000"), Decimal("7000"), Decimal("9000")])
        self.assertEqual(statement["closing_balance"], Decimal("9000"))

    def test_17_identity_separation(self):
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("1000"),
            posting_date=date(2026, 1, 1), user=self.user)
        open_party_balance(
            party=self.customer, currency=self.usd,
            balance_type="RECEIVABLE", amount=Decimal("200"),
            posting_date=date(2026, 1, 1), rate=Decimal("70"),
            rate_date=date(2026, 1, 1), user=self.user)
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="CUSTOMER_CREDIT", amount=Decimal("300"),
            posting_date=date(2026, 1, 1), user=self.user)
        open_party_balance(
            party=self.supplier, currency=self.afn,
            balance_type="PAYABLE", amount=Decimal("400"),
            posting_date=date(2026, 1, 1), user=self.user)
        self.assertEqual(party_balance(
            self.customer, currency=self.afn,
            balance_type="RECEIVABLE")["balance"], Decimal("1000"))
        self.assertEqual(party_balance(
            self.customer, currency=self.usd,
            balance_type="RECEIVABLE")["balance"], Decimal("200"))
        self.assertEqual(party_balance(
            self.customer, currency=self.afn,
            balance_type="CUSTOMER_CREDIT")["balance"], Decimal("300"))
        self.assertEqual(party_balance(
            self.supplier, currency=self.afn,
            balance_type="PAYABLE")["balance"], Decimal("400"))
        self.assertEqual(party_balance(
            self.supplier, currency=self.afn,
            balance_type="RECEIVABLE")["balance"], Decimal("0"))


class DualRoleTests(LedgerFixture, TestCase):
    def test_18_customer_only(self):
        self._sale_effect(self.customer, Decimal("5000"))
        self.assertEqual(party_balance(
            self.customer, currency=self.afn,
            balance_type="RECEIVABLE")["balance"], Decimal("5000"))
        self.assertEqual(party_balance(
            self.customer, currency=self.afn,
            balance_type="PAYABLE")["balance"], Decimal("0"))

    def test_19_supplier_only(self):
        entry = self._post(
            self.afn,
            [{"account": self._account("6100"), "debit": Decimal("7000")},
             {"account": self._account("2110"), "credit": Decimal("7000")}],
            source_type="SIMULATED_PURCHASE")
        attribute_journal_line(
            entry.lines.get(account__code="2110"),
            party=self.supplier, user=self.user)
        self.assertEqual(party_balance(
            self.supplier, currency=self.afn,
            balance_type="PAYABLE")["balance"], Decimal("7000"))

    def test_20_dual_role_simultaneous(self):
        self._sale_effect(self.both, Decimal("5000"))
        entry = self._post(
            self.afn,
            [{"account": self._account("6100"), "debit": Decimal("7000")},
             {"account": self._account("2110"), "credit": Decimal("7000")}])
        attribute_journal_line(
            entry.lines.get(account__code="2110"),
            party=self.both, user=self.user)
        open_party_balance(
            party=self.both, currency=self.afn,
            balance_type="CUSTOMER_CREDIT", amount=Decimal("1000"),
            posting_date=date(2026, 1, 1), user=self.user)
        open_party_balance(
            party=self.both, currency=self.afn,
            balance_type="SUPPLIER_ADVANCE", amount=Decimal("2000"),
            posting_date=date(2026, 1, 1), user=self.user)
        self.assertEqual(party_balance(
            self.both, currency=self.afn,
            balance_type="RECEIVABLE")["balance"], Decimal("5000"))
        self.assertEqual(party_balance(
            self.both, currency=self.afn,
            balance_type="PAYABLE")["balance"], Decimal("7000"))
        self.assertEqual(party_balance(
            self.both, currency=self.afn,
            balance_type="CUSTOMER_CREDIT")["balance"], Decimal("1000"))
        self.assertEqual(party_balance(
            self.both, currency=self.afn,
            balance_type="SUPPLIER_ADVANCE")["balance"], Decimal("2000"))


class NetPositionTests(LedgerFixture, TestCase):
    def test_21_customer_net(self):
        self._sale_effect(self.customer, Decimal("10000"))
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="CUSTOMER_CREDIT", amount=Decimal("2000"),
            posting_date=date(2026, 1, 1), user=self.user)
        position = net_position(
            self.customer, currency=self.afn, side="CUSTOMER")
        self.assertEqual(
            (position["gross"], position["contra"], position["net"]),
            (Decimal("10000"), Decimal("2000"), Decimal("8000")))

    def test_22_supplier_net(self):
        open_party_balance(
            party=self.supplier, currency=self.afn,
            balance_type="PAYABLE", amount=Decimal("7000"),
            posting_date=date(2026, 1, 1), user=self.user)
        open_party_balance(
            party=self.supplier, currency=self.afn,
            balance_type="SUPPLIER_ADVANCE", amount=Decimal("3000"),
            posting_date=date(2026, 1, 1), user=self.user)
        position = net_position(
            self.supplier, currency=self.afn, side="SUPPLIER")
        self.assertEqual(
            (position["gross"], position["contra"], position["net"]),
            (Decimal("7000"), Decimal("3000"), Decimal("4000")))

    def test_23_debtor(self):
        self._sale_effect(self.customer, Decimal("10000"))
        position = net_position(
            self.customer, currency=self.afn, side="CUSTOMER")
        self.assertEqual(position["status"], "DEBTOR")

    def test_24_creditor(self):
        self._sale_effect(self.customer, Decimal("10000"))
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="CUSTOMER_CREDIT", amount=Decimal("12000"),
            posting_date=date(2026, 1, 1), user=self.user)
        position = net_position(
            self.customer, currency=self.afn, side="CUSTOMER")
        self.assertEqual(position["status"], "CREDITOR")
        self.assertEqual(position["net"], Decimal("-2000"))

    def test_25_zero(self):
        self._sale_effect(self.customer, Decimal("5000"))
        self._payment_effect(self.customer, Decimal("5000"))
        position = net_position(
            self.customer, currency=self.afn, side="CUSTOMER")
        self.assertEqual(position["status"], "ZERO")
        self.assertEqual(position["net"], Decimal("0"))
        with self.assertRaises(PartyLedgerValidationError):
            net_position(self.customer, currency=self.afn, side="BOTH")


class OpeningTests(LedgerFixture, TestCase):
    def test_26_afn_opening(self):
        entry = open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("10000"),
            posting_date=date(2026, 1, 1), user=self.user)
        self.assertEqual(entry.status, JournalStatus.POSTED)
        self.assertEqual(entry.total_debit, entry.total_credit)
        self.assertEqual(
            party_balance(self.customer, currency=self.afn,
                          balance_type="RECEIVABLE")["balance"],
            Decimal("10000"))

    def test_27_usd_opening(self):
        entry = open_party_balance(
            party=self.customer, currency=self.usd,
            balance_type="RECEIVABLE", amount=Decimal("1000"),
            posting_date=date(2026, 1, 1), rate=Decimal("70"),
            rate_date=date(2026, 1, 1), user=self.user)
        self.assertEqual(entry.currency, self.usd)
        self.assertEqual(entry.afn_total, Decimal("70000.00"))
        self.assertEqual(
            party_balance(self.customer, currency=self.usd,
                          balance_type="RECEIVABLE")["balance"],
            Decimal("1000"))

    def test_28_opening_uses_3900(self):
        entry = open_party_balance(
            party=self.supplier, currency=self.afn,
            balance_type="PAYABLE", amount=Decimal("7000"),
            posting_date=date(2026, 1, 1), user=self.user)
        codes = sorted(
            line.account.code for line in entry.lines.all())
        self.assertEqual(codes, ["2110", "3900"])
        payable_leg = entry.lines.get(account__code="2110")
        self.assertEqual(payable_leg.credit, Decimal("7000"))

    def test_29_pipeline_idempotent_retry(self):
        params = dict(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("1000"),
            posting_date=date(2026, 1, 1), user=self.user,
            number=next_document_number("JE", 1404),
            idempotency_key="open-retry-001")
        first = open_party_balance(**params)
        second = open_party_balance(**params)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(PartyLedgerAttribution.objects.count(), 1)
        self.assertTrue(AuditEvent.objects.filter(
            action=AuditAction.POST, entity="JournalEntry").exists())

    def test_30_attribution_failure_rolls_back(self):
        audits_before = AuditEvent.objects.count()
        with mock.patch(
                "party_ledger.services.attribute_journal_line",
                side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                open_party_balance(
                    party=self.customer, currency=self.afn,
                    balance_type="RECEIVABLE", amount=Decimal("1000"),
                    posting_date=date(2026, 1, 1), user=self.user)
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(PartyLedgerAttribution.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), audits_before)

    def test_31_repeated_opening_allowed(self):
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("1000"),
            posting_date=date(2026, 1, 1), user=self.user)
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("2000"),
            posting_date=date(2026, 2, 1), user=self.user)
        self.assertEqual(
            party_balance(self.customer, currency=self.afn,
                          balance_type="RECEIVABLE")["balance"],
            Decimal("3000"))
        with self.assertRaises(PartyLedgerValidationError):
            open_party_balance(
                party=self.customer, currency=self.afn,
                balance_type="RECEIVABLE", amount=Decimal("0"),
                posting_date=date(2026, 1, 1), user=self.user)


class ImmutabilityTests(LedgerFixture, TestCase):
    def test_32_posted_journal_immutable(self):
        entry = self._sale_effect(self.customer, Decimal("1000"))
        entry.description = "edited"
        with self.assertRaises(PostedImmutabilityError):
            entry.save()

    def test_33_reversed_history_visible(self):
        opening = open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("10000"),
            posting_date=date(2026, 1, 1), user=self.user)
        reversal = reverse_journal(opening, "fix", self.user)
        attribute_journal_line(
            reversal.lines.get(account__code="1310"),
            party=self.customer, user=self.user)
        statement = party_statement(
            self.customer, currency=self.afn, balance_type="RECEIVABLE")
        self.assertEqual(statement["lines_count"], 2)
        numbers = [row["journal_number"] for row in statement["lines"]]
        self.assertIn(opening.number, numbers)
        self.assertIn(reversal.number, numbers)

    def test_34_reversal_net_correct(self):
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("10000"),
            posting_date=date(2026, 1, 1), user=self.user)
        mistaken = self._sale_effect(self.customer, Decimal("5000"), day=5)
        reversal = reverse_journal(mistaken, "wrong invoice", self.user)
        attribute_journal_line(
            reversal.lines.get(account__code="1310"),
            party=self.customer, user=self.user)
        result = party_balance(
            self.customer, currency=self.afn, balance_type="RECEIVABLE")
        self.assertEqual(result["balance"], Decimal("10000"))
        self.assertEqual(result["lines_count"], 3)

    def test_35_cannot_rewrite_attributed_history(self):
        entry = self._sale_effect(self.customer, Decimal("1000"))
        attribution = PartyLedgerAttribution.objects.get(
            journal_line__entry=entry)
        attribution.party_id = self.supplier.pk
        with self.assertRaises(PostedImmutabilityError):
            attribution.save(update_fields=["party"])
        attribution.refresh_from_db()
        self.assertEqual(attribution.party, self.customer)


class TraceabilityTests(LedgerFixture, TestCase):
    def test_36_source_preserved(self):
        entry = open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("1000"),
            posting_date=date(2026, 1, 1), reference="OB-2026",
            user=self.user)
        self.assertEqual(entry.source_type, "OPENING_BALANCE")
        statement = party_statement(
            self.customer, currency=self.afn, balance_type="RECEIVABLE")
        row = statement["lines"][0]
        self.assertEqual(row["source_type"], "OPENING_BALANCE")
        self.assertEqual(row["source_id"], entry.number)
        self.assertEqual(row["reference"], "OB-2026")

    def test_37_journals_by_source_compatible(self):
        entry = open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("1000"),
            posting_date=date(2026, 1, 1), user=self.user)
        found = journals_by_source("OPENING_BALANCE", entry.number)
        self.assertEqual([item.pk for item in found], [entry.pk])

    def test_38_statement_exposes_source(self):
        self._sale_effect(self.customer, Decimal("1000"))
        row = party_statement(
            self.customer, currency=self.afn,
            balance_type="RECEIVABLE")["lines"][0]
        for key in ("source_type", "source_id", "journal_number",
                    "journal_entry_id", "journal_line_id", "description",
                    "reference", "account_code"):
            self.assertIn(key, row)
        self.assertEqual(row["source_type"], "SIMULATED_SALE")


class ReconciliationTests(LedgerFixture, TestCase):
    def test_39_reconciles_to_gl(self):
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("10000"),
            posting_date=date(2026, 1, 1), user=self.user)
        open_party_balance(
            party=self.supplier, currency=self.afn,
            balance_type="PAYABLE", amount=Decimal("7000"),
            posting_date=date(2026, 1, 1), user=self.user)
        self._sale_effect(self.customer, Decimal("5000"), day=5)
        mistaken = self._sale_effect(self.customer, Decimal("1000"), day=6)
        reversal = reverse_journal(mistaken, "fix", self.user)
        attribute_journal_line(
            reversal.lines.get(account__code="1310"),
            party=self.customer, user=self.user)
        report = reconcile_party_ledger(currency=self.afn)
        self.assertTrue(report["reconciled"])
        by_account = {row["account_code"]: row
                      for row in report["accounts"]}
        gl_1310 = account_balance(self._account("1310"))
        self.assertEqual(by_account["1310"]["attributed_debit"],
                         gl_1310["total_debit"])
        self.assertEqual(by_account["1310"]["attributed_credit"],
                         gl_1310["total_credit"])
        self.assertEqual(
            by_account["2110"]["attributed_credit"], Decimal("7000"))

    def test_40_no_independent_effect(self):
        self._post(
            self.afn,
            [{"account": self._account("1310"), "debit": Decimal("5000")},
             {"account": self._account("4110"), "credit": Decimal("5000")}])
        result = party_balance(
            self.customer, currency=self.afn, balance_type="RECEIVABLE")
        self.assertEqual(result["balance"], Decimal("0"))
        report = reconcile_party_ledger(currency=self.afn)
        self.assertFalse(report["reconciled"])
        row_1310 = next(row for row in report["accounts"]
                        if row["account_code"] == "1310")
        self.assertEqual(row_1310["unattributed_lines"], 1)
        self.assertEqual(row_1310["unattributed_debit"], Decimal("5000"))
