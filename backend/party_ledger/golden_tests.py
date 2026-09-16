"""Phase 5 — golden party-ledger scenarios G51-01..12 (printed).

Each scenario drives the REAL services and prints the ledger trail. Run
with ``-s`` to capture the trail.

Because payment/invoice/allocation engines are OUT OF PHASE 5, the
future-flow goldens below post REPRESENTATIVE journals plus attribution
(the Phase-5 boundary) and clearly mark the real engines as future
scope. No future entity is invented.
"""

from datetime import date
from decimal import Decimal
from itertools import count

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounting.coa import seed_chart_of_accounts
from accounting.models import Account
from accounting.services import post_journal, reverse_journal
from currencies.models import Currency
from parties.services import create_party

from . import ledger as ledger_module
from . import services as ledger_services
from .ledger import (
    net_position,
    party_balance,
    party_statement,
    reconcile_party_ledger,
)
from .services import attribute_journal_line, open_party_balance


class GoldenFixture:
    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(
            code="AFN", name="Afghani", is_base=True)
        cls.usd = Currency.objects.create(code="USD", name="US Dollar")

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "g51user", password="x")
        self.customer = create_party(
            name="Karimi Store", is_customer=True, user=self.user)
        self.supplier = create_party(
            name="Hari Dunya", is_supplier=True, user=self.user)
        self._numbers = count(1)

    def _show(self, tag, obj):
        print(f"  [{tag}] {obj}")

    def _number(self, tag="G51"):
        return f"{tag}-{next(self._numbers):04d}"

    def _account(self, code):
        return Account.objects.get(code=code)

    def _post(self, currency, debit_code, credit_code, amount, day,
              source, rate=None):
        """Representative journal (future engines will own real flows)."""
        kwargs = {}
        if not currency.is_base:
            kwargs = {"rate": rate or Decimal("70"),
                      "rate_date": date(2026, 1, day)}
        entry = post_journal(
            number=self._number(), posting_date=date(2026, 1, day),
            description=f"golden {source}", source_type=source,
            source_id=self._number("SIM"),
            lines=[{"account": self._account(debit_code), "debit": amount},
                   {"account": self._account(credit_code),
                    "credit": amount}],
            currency=currency, created_by=self.user, **kwargs)
        return entry

    def _attribute(self, entry, code, party):
        return attribute_journal_line(
            entry.lines.get(account__code=code), party=party,
            user=self.user)

    def _balance(self, party, currency, balance_type):
        return party_balance(
            party, currency=currency,
            balance_type=balance_type)["balance"]


class PartyLedgerGoldenTests(GoldenFixture, TestCase):
    def test_g51_01_customer_debtor(self):
        print("G51-01 customer debtor via opening balance:")
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("10000"),
            posting_date=date(2026, 1, 1), user=self.user)
        position = net_position(
            self.customer, currency=self.afn, side="CUSTOMER")
        self._show("net", f"{position['net']} AFN status={position['status']}")
        self.assertEqual(position["status"], "DEBTOR")
        print("PASS G51-01")

    def test_g51_02_full_payment_effect(self):
        print("G51-02 sale then FULL payment effect (engine is future):")
        sale = self._post(self.afn, "1310", "4110", Decimal("5000"), 5,
                          "SIMULATED_SALE")
        self._attribute(sale, "1310", self.customer)
        payment = self._post(self.afn, "1110", "1310", Decimal("5000"), 10,
                             "SIMULATED_PAYMENT")
        self._attribute(payment, "1310", self.customer)
        balance = self._balance(self.customer, self.afn, "RECEIVABLE")
        self._show("balance", f"{balance} AFN (payment engine: future)")
        self.assertEqual(balance, Decimal("0"))
        print("PASS G51-02")

    def test_g51_03_partial_payment_effect(self):
        print("G51-03 sale then PARTIAL payment effect (engine is future):")
        sale = self._post(self.afn, "1310", "4110", Decimal("5000"), 5,
                          "SIMULATED_SALE")
        self._attribute(sale, "1310", self.customer)
        payment = self._post(self.afn, "1110", "1310", Decimal("2000"), 10,
                             "SIMULATED_PAYMENT")
        self._attribute(payment, "1310", self.customer)
        balance = self._balance(self.customer, self.afn, "RECEIVABLE")
        self._show("balance", f"{balance} AFN (payment engine: future)")
        self.assertEqual(balance, Decimal("3000"))
        print("PASS G51-03")

    def test_g51_04_customer_credit(self):
        print("G51-04 customer credit from overpayment pattern (§7.7):")
        entry = post_journal(
            number=self._number(), posting_date=date(2026, 1, 10),
            description="golden overpayment", source_type="SIMULATED_PAYMENT",
            source_id=self._number("SIM"),
            lines=[{"account": self._account("1110"),
                    "debit": Decimal("6000")},
                   {"account": self._account("1310"),
                    "credit": Decimal("5000")},
                   {"account": self._account("2200"),
                    "credit": Decimal("1000")}],
            currency=self.afn, created_by=self.user)
        self._attribute(entry, "1310", self.customer)
        self._attribute(entry, "2200", self.customer)
        credit = self._balance(self.customer, self.afn, "CUSTOMER_CREDIT")
        self._show("credit", f"{credit} AFN on 2200 (one journal, two types)")
        self.assertEqual(credit, Decimal("1000"))
        print("PASS G51-04")

    def test_g51_05_customer_overpayment(self):
        print("G51-05 overpayment creates credit, net goes creditor-side:")
        sale = self._post(self.afn, "1310", "4110", Decimal("5000"), 5,
                          "SIMULATED_SALE")
        self._attribute(sale, "1310", self.customer)
        entry = post_journal(
            number=self._number(), posting_date=date(2026, 1, 10),
            description="golden overpayment", source_type="SIMULATED_PAYMENT",
            source_id=self._number("SIM"),
            lines=[{"account": self._account("1110"),
                    "debit": Decimal("7000")},
                   {"account": self._account("1310"),
                    "credit": Decimal("5000")},
                   {"account": self._account("2200"),
                    "credit": Decimal("2000")}],
            currency=self.afn, created_by=self.user)
        self._attribute(entry, "1310", self.customer)
        self._attribute(entry, "2200", self.customer)
        position = net_position(
            self.customer, currency=self.afn, side="CUSTOMER")
        self._show("net", f"{position['net']} AFN status={position['status']}")
        self.assertEqual(
            (position["net"], position["status"]),
            (Decimal("-2000"), "CREDITOR"))
        print("PASS G51-05")

    def test_g51_06_supplier_payable(self):
        print("G51-06 supplier payable via purchase pattern:")
        entry = self._post(self.afn, "6100", "2110", Decimal("7000"), 5,
                           "SIMULATED_PURCHASE")
        self._attribute(entry, "2110", self.supplier)
        balance = self._balance(self.supplier, self.afn, "PAYABLE")
        self._show("payable", f"{balance} AFN")
        self.assertEqual(balance, Decimal("7000"))
        print("PASS G51-06")

    def test_g51_07_supplier_advance(self):
        print("G51-07 supplier advance reduces supplier net:")
        entry = self._post(self.afn, "6100", "2110", Decimal("7000"), 5,
                           "SIMULATED_PURCHASE")
        self._attribute(entry, "2110", self.supplier)
        open_party_balance(
            party=self.supplier, currency=self.afn,
            balance_type="SUPPLIER_ADVANCE", amount=Decimal("3000"),
            posting_date=date(2026, 1, 1), user=self.user)
        position = net_position(
            self.supplier, currency=self.afn, side="SUPPLIER")
        self._show("net",
                   f"{position['gross']}-{position['contra']}="
                   f"{position['net']} AFN status={position['status']}")
        self.assertEqual(
            (position["net"], position["status"]),
            (Decimal("4000"), "CREDITOR"))
        print("PASS G51-07")

    def test_g51_08_multi_currency_separation(self):
        print("G51-08 AFN and USD receivable never merge:")
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("300000"),
            posting_date=date(2026, 1, 1), user=self.user)
        open_party_balance(
            party=self.customer, currency=self.usd,
            balance_type="RECEIVABLE", amount=Decimal("5000"),
            posting_date=date(2026, 1, 1), rate=Decimal("70"),
            rate_date=date(2026, 1, 1), user=self.user)
        afn = self._balance(self.customer, self.afn, "RECEIVABLE")
        usd = self._balance(self.customer, self.usd, "RECEIVABLE")
        self._show("balances", f"AFN {afn} + USD {usd} (two balances)")
        self.assertEqual((afn, usd), (Decimal("300000"), Decimal("5000")))
        print("PASS G51-08")

    def test_g51_09_historical_balance(self):
        print("G51-09 history in chronology with running balance:")
        sale = self._post(self.afn, "1310", "4110", Decimal("10000"), 1,
                          "SIMULATED_SALE")
        self._attribute(sale, "1310", self.customer)
        payment = self._post(self.afn, "1110", "1310", Decimal("3000"), 10,
                             "SIMULATED_PAYMENT")
        self._attribute(payment, "1310", self.customer)
        statement = party_statement(
            self.customer, currency=self.afn, balance_type="RECEIVABLE")
        trail = [(str(row["posting_date"]), row["debit"], row["credit"],
                  row["running_balance"]) for row in statement["lines"]]
        self._show("trail", trail)
        self.assertEqual(statement["closing_balance"], Decimal("7000"))
        print("PASS G51-09")

    def test_g51_10_opening_balance(self):
        print("G51-10 USD opening posts via pipeline with 3900:")
        entry = open_party_balance(
            party=self.customer, currency=self.usd,
            balance_type="RECEIVABLE", amount=Decimal("1000"),
            posting_date=date(2026, 1, 1), rate=Decimal("70"),
            rate_date=date(2026, 1, 1), user=self.user)
        legs = sorted((line.account.code, str(line.debit), str(line.credit))
                      for line in entry.lines.all())
        self._show("legs", legs)
        self._show("afn_total", f"{entry.afn_total} (supplemental)")
        self.assertEqual(
            self._balance(self.customer, self.usd, "RECEIVABLE"),
            Decimal("1000"))
        print("PASS G51-10")

    def test_g51_11_allocation_boundary(self):
        print("G51-11 allocation engine absent; boundary pinned:")
        for module in (ledger_services, ledger_module):
            for name in ("allocate", "payment", "invoice", "settle",
                         "PaymentAllocation", "InvoiceAllocation"):
                self.assertFalse(hasattr(module, name), name)
        self._show("api", "no allocate/payment/invoice/settle in Phase 5")
        print("PASS G51-11")

    def test_g51_12_party_gl_reconciliation(self):
        print("G51-12 party derivation equals GL control effects:")
        open_party_balance(
            party=self.customer, currency=self.afn,
            balance_type="RECEIVABLE", amount=Decimal("10000"),
            posting_date=date(2026, 1, 1), user=self.user)
        sale = self._post(self.afn, "1310", "4110", Decimal("5000"), 5,
                          "SIMULATED_SALE")
        self._attribute(sale, "1310", self.customer)
        mistaken = self._post(self.afn, "1310", "4110", Decimal("1000"), 6,
                              "SIMULATED_SALE")
        self._attribute(mistaken, "1310", self.customer)
        reversal = reverse_journal(mistaken, "golden fix", self.user)
        self._attribute(reversal, "1310", self.customer)
        report = reconcile_party_ledger(currency=self.afn)
        row = next(item for item in report["accounts"]
                   if item["account_code"] == "1310")
        self._show("1310", f"GL Dr {row['gl_debit']} Cr {row['gl_credit']} = "
                           f"attributed Dr {row['attributed_debit']} Cr "
                           f"{row['attributed_credit']}")
        self.assertTrue(report["reconciled"])
        print("PASS G51-12")
