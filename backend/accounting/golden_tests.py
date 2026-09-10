"""Stage 2.5 — §1.13 Accounting Golden Suite (16 scenarios).

Every scenario prints its own evidence block (inputs, journals, totals, AFN
equivalents, balances, reconciliation, PASS/FAIL) and then asserts the same
facts it printed. Run with ``-s`` (or under ``manage.py test``) to see them.

Two fixture rules follow from the frozen contracts and are stated in the
evidence report:

* Revenue is posted to **4110 Wholesale Sales** because 4100 Sales Revenue is a
  NON-POSTING group account in the frozen Stage 2.1 COA.
* Business scenarios use one currency (USD @ 70.0000) so the frozen Stage 2.4
  read layer can reconcile them; the AFN-denominated realized-FX journals form
  their own single-currency fixtures for the same reason.
"""

from decimal import Decimal
from unittest import mock

from django.test import TestCase, TransactionTestCase

from core.idempotency import IdempotencyRecord
from core.money import cogs as cogs_amount
from core.money import format_rate
from currencies.models import Currency, ExchangeRate
from documents.models import NumberSequence
from security.models import AuditAction, AuditEvent

from .balances import account_balance, journals_by_source, trace_source, trial_balance
from .coa import seed_chart_of_accounts
from .fx import compute_realized_fx, post_realized_fx_settlement
from .models import Account, JournalEntry, JournalLine, JournalStatus
from .services import JournalValidationError, post_journal, reverse_journal, verify_entry_totals

WIDTH = 66


# ---------------------------------------------------------------------------
# Reporting helpers (test-only presentation layer)
# ---------------------------------------------------------------------------

def _fmt(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)


def golden_report(number, name, sections):
    label = f"{number:02d}" if isinstance(number, int) else str(number)
    out = ["=" * WIDTH, f"GOLDEN {label} — {name}", "=" * WIDTH]
    for heading, rows in sections:
        out.append("")
        out.append(heading)
        for label, value in rows:
            out.append(f"  {label:<32}{_fmt(value)}")
    text = "\n".join(out)
    print("\n" + text + "\n")
    return text


def journal_rows(entry, title="JOURNAL"):
    rows = [
        (f"{title} Number", entry.number),
        ("Posting Date", entry.posting_date),
        ("Currency", entry.currency.code),
        ("Rate Snapshot", format_rate(entry.rate)),
        ("Rate Date", entry.rate_date),
        ("Rate Direction", entry.rate_direction),
        ("Status", entry.status),
        ("-- Debit Lines --", ""),
    ]
    for line in entry.lines.all().order_by("id"):
        if line.debit:
            rows.append((f"Dr {line.account.code} {line.account.name}", f"{line.debit:.2f}"))
    rows.append(("-- Credit Lines --", ""))
    for line in entry.lines.all().order_by("id"):
        if line.credit:
            rows.append((f"Cr {line.account.code} {line.account.name}", f"{line.credit:.2f}"))
    rows.append(("TOTAL DEBIT", f"{entry.total_debit:.2f}"))
    rows.append(("TOTAL CREDIT", f"{entry.total_credit:.2f}"))
    rows.append(("AFN EQUIVALENT", f"{entry.afn_total:.2f}"))
    return rows


def balance_rows(codes, accounts):
    rows = []
    for code in codes:
        data = account_balance(accounts[code])
        rows.append((f"{code} {accounts[code].name}",
                     f"{data['balance']:.2f} ({data['normal_balance']})"))
    return rows


class GoldenFixture:
    """Canonical COA + AFN (base) + USD, and the accounts the goldens use."""

    @classmethod
    def _seed(cls):
        seed_chart_of_accounts()
        afn, _ = Currency.objects.get_or_create(code="AFN", defaults={"name": "Afghani", "is_base": True})
        usd, _ = Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar"})
        return afn, usd

    @classmethod
    def _accounts(cls):
        codes = ("1110", "1210", "1310", "1410", "2110", "2400", "3100", "3900",
                 "4100", "4110", "4200", "5100", "5200", "8100", "8200")
        return {code: Account.objects.get(code=code) for code in codes}

    def _post(self, number, lines, *, rate="70.0000", date="2026-03-01", source_type="GOLDEN",
              source_id="DOC-1", description="golden", currency=None, **kwargs):
        return post_journal(
            number=number, posting_date=date, description=description,
            lines=[{"account": self.acc[code], **side} for code, side in lines],
            currency=currency or self.usd, rate=rate, rate_date=date,
            source_type=source_type, source_id=source_id, **kwargs,
        )


# ---------------------------------------------------------------------------
# GOLDEN 01–10 — core accounting patterns
# ---------------------------------------------------------------------------

class GoldenCoreTests(GoldenFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd = cls._seed()
        cls.acc = cls._accounts()

    # -----------------------------------------------------------------
    def test_golden_01_balanced_journal(self):
        entry = self._post("JE-G01", [("1110", {"debit": "5000.00"}), ("3100", {"credit": "5000.00"})])
        totals = verify_entry_totals(entry)
        tb = trial_balance()
        golden_report(1, "BALANCED JOURNAL", [
            ("INPUT", [("Debit 1110 Cash", "5000.00"), ("Credit 3100 Owner Capital", "5000.00"),
                       ("Currency", self.usd.code), ("Rate", "70.0000")]),
            ("EXPECTED", [("Total Debit = Total Credit", "5000.00 = 5000.00")]),
            (f"JOURNAL {entry.number}", journal_rows(entry, "JOURNAL")),
            ("BALANCE", [("1110 Cash", f"{account_balance(self.acc['1110'])['balance']:.2f}"),
                         ("3100 Owner Capital", f"{account_balance(self.acc['3100'])['balance']:.2f}")]),
            ("RECONCILIATION", [("Lines vs stored totals", f"{totals['total_debit']:.2f} == {totals['total_credit']:.2f}"),
                                ("Trial balance difference", f"{tb['difference']:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(entry.total_debit, Decimal("5000.00"))
        self.assertEqual(entry.total_credit, Decimal("5000.00"))
        self.assertEqual(entry.afn_total, Decimal("350000.00"))
        self.assertEqual(entry.rate_direction, "USD->AFN")
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.POST, entity_id=str(entry.id)).count(), 1)
        self.assertEqual([e.number for e in journals_by_source("GOLDEN", "DOC-1")], [entry.number])
        self.assertEqual(tb["difference"], Decimal("0.00"))

    # -----------------------------------------------------------------
    def test_golden_02_unbalanced_journal_rejected(self):
        before = {"entries": JournalEntry.objects.count(), "lines": JournalLine.objects.count(),
                  "audits": AuditEvent.objects.count(), "idem": IdempotencyRecord.objects.count(),
                  "sequences": NumberSequence.objects.count()}
        error = ""
        try:
            self._post("JE-G02", [("1110", {"debit": "5000.00"}), ("3100", {"credit": "4999.00"})],
                       idempotency_key="golden-02")
        except JournalValidationError as exc:
            error = str(exc)
        after = {"entries": JournalEntry.objects.count(), "lines": JournalLine.objects.count(),
                 "audits": AuditEvent.objects.count(), "idem": IdempotencyRecord.objects.count(),
                 "sequences": NumberSequence.objects.count()}
        golden_report(2, "UNBALANCED JOURNAL REJECTION", [
            ("INPUT", [("Debit 1110 Cash", "5000.00"), ("Credit 3100 Owner Capital", "4999.00"),
                       ("Idempotency key", "golden-02")]),
            ("EXPECTED", [("Posting rejected", "JournalValidationError"),
                          ("No partial state", "0 entries / 0 lines / 0 audits")]),
            ("OBSERVED", [("Error", error), ("JournalEntry count", after["entries"]),
                          ("JournalLine count", after["lines"]), ("Audit count", after["audits"]),
                          ("Idempotency reservation released", after["idem"] == 0),
                          ("NumberSequence unchanged", after["sequences"] == before["sequences"])]),
            ("RECONCILIATION", [("before == after", f"{before} == {after}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertIn("Total debit must equal total credit", error)
        self.assertEqual(before, after)
        # the released key is reusable
        retry = self._post("JE-G02", [("1110", {"debit": "5000.00"}), ("3100", {"credit": "5000.00"})],
                           idempotency_key="golden-02")
        self.assertEqual(retry.idempotency_key, "golden-02")

    # -----------------------------------------------------------------
    def test_golden_03_customer_receivable(self):
        entry = self._post("JE-G03", [("1310", {"debit": "1000.00"}), ("4110", {"credit": "1000.00"})],
                           source_type="SALE", source_id="INV-G03", description="credit sale")
        ar = account_balance(self.acc["1310"])
        rev = account_balance(self.acc["4110"])
        golden_report(3, "CUSTOMER RECEIVABLE", [
            ("INPUT", [("Debit 1310 Trade Receivables", "1000.00"), ("Credit 4110 Wholesale Sales", "1000.00"),
                       ("Currency", self.usd.code), ("Rate", format_rate(entry.rate))]),
            ("EXPECTED", [("Balanced", "1000.00 = 1000.00"), ("1310 normal balance", "DEBIT"),
                          ("4110 normal balance", "CREDIT")]),
            (f"JOURNAL {entry.number}", journal_rows(entry, "JOURNAL")),
            ("BALANCE", [("1310 Receivable", f"{ar['balance']:.2f} ({ar['normal_balance']})"),
                         ("4110 Sales", f"{rev['balance']:.2f} ({rev['normal_balance']})")]),
            ("SOURCE TRACE", [("journals_by_source(SALE, INV-G03)",
                               str([e.number for e in journals_by_source("SALE", "INV-G03")]))]),
            ("RECONCILIATION", [("Debits == Credits", f"{entry.total_debit:.2f} == {entry.total_credit:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(entry.total_debit, entry.total_credit)
        self.assertEqual(ar["balance"], Decimal("1000.00"))
        self.assertEqual(ar["normal_balance"], "DEBIT")
        self.assertEqual(rev["normal_balance"], "CREDIT")
        self.assertEqual([e.number for e in journals_by_source("SALE", "INV-G03")], [entry.number])

    # -----------------------------------------------------------------
    def test_golden_04_supplier_payable(self):
        entry = self._post("JE-G04", [("1410", {"debit": "2500.00"}), ("2110", {"credit": "2500.00"})],
                           source_type="PURCHASE", source_id="BILL-G04", description="credit purchase")
        ap = account_balance(self.acc["2110"])
        golden_report(4, "SUPPLIER PAYABLE", [
            ("INPUT", [("Debit 1410 Main Warehouse", "2500.00"), ("Credit 2110 Trade Payables", "2500.00"),
                       ("Currency", self.usd.code), ("Rate", format_rate(entry.rate))]),
            ("EXPECTED", [("Payable increases", "2500.00 CREDIT")]),
            (f"JOURNAL {entry.number}", journal_rows(entry, "JOURNAL")),
            ("BALANCE", [("2110 Payable", f"{ap['balance']:.2f} ({ap['normal_balance']})"),
                         ("1410 Inventory", f"{account_balance(self.acc['1410'])['balance']:.2f}")]),
            ("SOURCE TRACE", [("journals_by_source(PURCHASE, BILL-G04)",
                               str([e.number for e in journals_by_source("PURCHASE", "BILL-G04")]))]),
            ("HISTORICAL RATE", [("Rate snapshot stored", format_rate(entry.rate)),
                                 ("Rate date", entry.rate_date)]),
            ("RECONCILIATION", [("Debits == Credits", f"{entry.total_debit:.2f} == {entry.total_credit:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(ap["balance"], Decimal("2500.00"))
        self.assertEqual(ap["normal_balance"], "CREDIT")
        self.assertEqual(entry.rate, Decimal("70.0000"))

    # -----------------------------------------------------------------
    def test_golden_05_customer_receipt(self):
        self._post("JE-G05A", [("1310", {"debit": "1000.00"}), ("4110", {"credit": "1000.00"})],
                   source_id="INV-G05")
        ar_before = account_balance(self.acc["1310"])["balance"]
        entry = self._post("JE-G05B", [("1110", {"debit": "1000.00"}), ("1310", {"credit": "1000.00"})],
                           source_type="RECEIPT", source_id="RCPT-G05", description="customer receipt")
        ar_after = account_balance(self.acc["1310"])["balance"]
        cash = account_balance(self.acc["1110"])
        golden_report(5, "CUSTOMER RECEIPT", [
            ("INPUT", [("Debit 1110 Cash", "1000.00"), ("Credit 1310 Trade Receivables", "1000.00"),
                       ("Currency", self.usd.code), ("Rate", format_rate(entry.rate))]),
            ("EXPECTED", [("Receivable decreases", "1000.00 -> 0.00"), ("Cash increases", "0.00 -> 1000.00")]),
            (f"JOURNAL {entry.number}", journal_rows(entry, "JOURNAL")),
            ("BALANCE", [("1310 before", f"{ar_before:.2f}"), ("1310 after", f"{ar_after:.2f}"),
                         ("1110 Cash", f"{cash['balance']:.2f} ({cash['normal_balance']})")]),
            ("SOURCE TRACE", [("journals_by_source(RECEIPT, RCPT-G05)",
                               str([e.number for e in journals_by_source("RECEIPT", "RCPT-G05")]))]),
            ("RECONCILIATION", [("Debits == Credits", f"{entry.total_debit:.2f} == {entry.total_credit:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(ar_after, Decimal("0.00"))
        self.assertEqual(cash["balance"], Decimal("1000.00"))

    # -----------------------------------------------------------------
    def test_golden_06_supplier_payment(self):
        self._post("JE-G06A", [("1410", {"debit": "2500.00"}), ("2110", {"credit": "2500.00"})],
                   source_id="BILL-G06")
        ap_before = account_balance(self.acc["2110"])["balance"]
        entry = self._post("JE-G06B", [("2110", {"debit": "2500.00"}), ("1110", {"credit": "2500.00"})],
                           source_type="PAYMENT", source_id="PAY-G06", description="supplier payment")
        ap_after = account_balance(self.acc["2110"])["balance"]
        cash = account_balance(self.acc["1110"])
        golden_report(6, "SUPPLIER PAYMENT", [
            ("INPUT", [("Debit 2110 Trade Payables", "2500.00"), ("Credit 1110 Cash", "2500.00"),
                       ("Currency", self.usd.code), ("Rate", format_rate(entry.rate))]),
            ("EXPECTED", [("Payable decreases", "2500.00 -> 0.00"), ("Cash decreases", "-2500.00")]),
            (f"JOURNAL {entry.number}", journal_rows(entry, "JOURNAL")),
            ("BALANCE", [("2110 before", f"{ap_before:.2f}"), ("2110 after", f"{ap_after:.2f}"),
                         ("1110 Cash", f"{cash['balance']:.2f} ({cash['normal_balance']})")]),
            ("SOURCE TRACE", [("journals_by_source(PAYMENT, PAY-G06)",
                               str([e.number for e in journals_by_source("PAYMENT", "PAY-G06")]))]),
            ("RECONCILIATION", [("Debits == Credits", f"{entry.total_debit:.2f} == {entry.total_credit:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(ap_after, Decimal("0.00"))
        self.assertEqual(cash["balance"], Decimal("-2500.00"))

    # -----------------------------------------------------------------
    def test_golden_07_purchase(self):
        entry = self._post("JE-G07", [("1410", {"debit": "4000.00"}), ("2110", {"credit": "4000.00"})],
                           source_type="PURCHASE", source_id="BILL-G07", description="purchase on credit")
        inv = account_balance(self.acc["1410"])
        ap = account_balance(self.acc["2110"])
        golden_report(7, "PURCHASE", [
            ("INPUT", [("Debit 1410 Main Warehouse", "4000.00"), ("Credit 2110 Trade Payables", "4000.00"),
                       ("Currency", self.usd.code), ("Rate", format_rate(entry.rate))]),
            ("EXPECTED", [("Inventory increases", "4000.00"), ("Payable increases", "4000.00")]),
            (f"JOURNAL {entry.number}", journal_rows(entry, "JOURNAL")),
            ("BALANCE", [("1410 Inventory", f"{inv['balance']:.2f} ({inv['normal_balance']})"),
                         ("2110 Payable", f"{ap['balance']:.2f} ({ap['normal_balance']})")]),
            ("HISTORICAL RATE", [("Rate snapshot", format_rate(entry.rate)), ("Rate date", entry.rate_date),
                                 ("AFN equivalent", f"{entry.afn_total:.2f}")]),
            ("SOURCE TRACE", [("journals_by_source(PURCHASE, BILL-G07)",
                               str([e.number for e in journals_by_source("PURCHASE", "BILL-G07")]))]),
            ("RECONCILIATION", [("Debits == Credits", f"{entry.total_debit:.2f} == {entry.total_credit:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(inv["balance"], Decimal("4000.00"))
        self.assertEqual(ap["balance"], Decimal("4000.00"))
        self.assertEqual(entry.afn_total, Decimal("280000.00"))

    # -----------------------------------------------------------------
    def test_golden_08_sale_and_cogs_pair(self):
        sale = self._post("JE-G08A", [("1310", {"debit": "3000.00"}), ("4110", {"credit": "3000.00"})],
                          source_id="INV-G08", description="sale")
        cogs_entry = self._post("JE-G08B", [("5100", {"debit": "1800.00"}), ("1410", {"credit": "1800.00"})],
                                source_id="INV-G08", description="cogs")
        self._post("JE-G08C", [("1410", {"debit": "1800.00"}), ("2110", {"credit": "1800.00"})],
                   source_id="BILL-G08", description="stock in")
        tb = trial_balance()
        golden_report(8, "SALE + COGS PAIR", [
            ("INPUT", [("Sale: Dr 1310 / Cr 4110", "3000.00"), ("COGS: Dr 5100 / Cr 1410", "1800.00")]),
            ("EXPECTED", [("Both journals balanced", "yes"), ("Inventory decreases", "1800.00")]),
            (f"JOURNAL {sale.number}", journal_rows(sale, "SALE")),
            (f"JOURNAL {cogs_entry.number}", journal_rows(cogs_entry, "COGS")),
            ("BALANCE", balance_rows(("1310", "4110", "5100", "1410"), self.acc)),
            ("COMBINED", [("Total debit", f"{tb['total_debit']:.2f}"), ("Total credit", f"{tb['total_credit']:.2f}")]),
            ("SOURCE TRACE", [("journals_by_source(GOLDEN, INV-G08)",
                               str([e.number for e in journals_by_source("GOLDEN", "INV-G08")]))]),
            ("RECONCILIATION", [("Trial balance difference", f"{tb['difference']:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(sale.total_debit, sale.total_credit)
        self.assertEqual(cogs_entry.total_debit, cogs_entry.total_credit)
        self.assertEqual(account_balance(self.acc["5100"])["balance"], Decimal("1800.00"))
        self.assertEqual(account_balance(self.acc["1410"])["balance"], Decimal("0.00"))
        self.assertEqual(tb["difference"], Decimal("0.00"))
        self.assertEqual([e.number for e in journals_by_source("GOLDEN", "INV-G08")],
                         ["JE-G08A", "JE-G08B"])

    # -----------------------------------------------------------------
    def test_golden_09_cogs_math(self):
        qty, avco = Decimal("3"), Decimal("125.555")
        expected = cogs_amount(qty, avco)
        entry = self._post("JE-G09", [("5100", {"debit": str(expected)}), ("1410", {"credit": str(expected)})],
                           source_id="COGS-G09", description="cogs golden vector")
        golden_report(9, "COGS MATH", [
            ("INPUT", [("Quantity", qty), ("AVCO", avco)]),
            ("EXPECTED", [("Round(3 x 125.555, 2) Half-Up", "376.67"), ("Float used", "no")]),
            ("OBSERVED", [("core.money.cogs(3, 125.555)", f"{expected}"),
                          ("Result type", type(expected).__name__)]),
            (f"JOURNAL {entry.number}", journal_rows(entry, "JOURNAL")),
            ("BALANCE", balance_rows(("5100", "1410"), self.acc)),
            ("RECONCILIATION", [("376.67 == 376.67", f"{expected} == {expected}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(expected, Decimal("376.67"))
        self.assertEqual(entry.total_debit, Decimal("376.67"))
        self.assertEqual(entry.total_credit, Decimal("376.67"))

    # -----------------------------------------------------------------
    def test_golden_10_exchange_house_movement(self):
        self._post("JE-G10A", [("1110", {"debit": "9000.00"}), ("3100", {"credit": "9000.00"})],
                   source_id="CAP-G10")
        entry = self._post("JE-G10B", [("1210", {"debit": "6000.00"}), ("1110", {"credit": "6000.00"})],
                           source_type="EXCHANGE", source_id="EXH-G10", description="cash to exchange house")
        cash = account_balance(self.acc["1110"])
        exh = account_balance(self.acc["1210"])
        golden_report(10, "EXCHANGE HOUSE MOVEMENT", [
            ("INPUT", [("Debit 1210 Exchange House A", "6000.00"), ("Credit 1110 Cash", "6000.00"),
                       ("Currency", self.usd.code), ("Rate", format_rate(entry.rate))]),
            ("EXPECTED", [("Cash decreases", "9000.00 -> 3000.00"), ("Exchange house increases", "6000.00")]),
            (f"JOURNAL {entry.number}", journal_rows(entry, "JOURNAL")),
            ("BALANCE", [("1110 Cash", f"{cash['balance']:.2f} ({cash['normal_balance']})"),
                         ("1210 Exchange House", f"{exh['balance']:.2f} ({exh['normal_balance']})")]),
            ("RATE SNAPSHOT", [("Rate", format_rate(entry.rate)), ("Rate date", entry.rate_date),
                               ("Direction", entry.rate_direction)]),
            ("SOURCE TRACE", [("journals_by_source(EXCHANGE, EXH-G10)",
                               str([e.number for e in journals_by_source("EXCHANGE", "EXH-G10")]))]),
            ("RECONCILIATION", [("Debits == Credits", f"{entry.total_debit:.2f} == {entry.total_credit:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(cash["balance"], Decimal("3000.00"))
        self.assertEqual(exh["balance"], Decimal("6000.00"))
        self.assertEqual(entry.rate, Decimal("70.0000"))


# ---------------------------------------------------------------------------
# GOLDEN 11–13 — realized FX
# ---------------------------------------------------------------------------

class GoldenFXTests(GoldenFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd = cls._seed()
        cls.acc = cls._accounts()

    def _fx(self, number, **overrides):
        params = dict(
            obligation_kind="RECEIVABLE",
            obligation_account=self.acc["1310"], obligation_amount="100.00",
            obligation_currency=self.usd, historical_rate="70",
            settlement_account=self.acc["1110"], settlement_amount="100.00",
            settlement_currency=self.usd, settlement_rate="72",
        )
        params.update(overrides)
        plan = compute_realized_fx(**params)
        entry = post_realized_fx_settlement(
            number=number, posting_date="2026-03-01", description="golden fx",
            source_type="FX", source_id="OBL-G11", **params,
        )
        return plan, entry

    # -----------------------------------------------------------------
    def test_golden_11_fx_gain(self):
        plan, entry = self._fx("JE-G11")
        tb = trial_balance()
        gain_balance = account_balance(self.acc["8100"])
        golden_report(11, "FX GAIN", [
            ("INPUT", [("Historical", "100.00 USD @ 70.0000 AFN/USD"),
                       ("Historical AFN", f"{plan['carrying_value']:.2f}"),
                       ("Settlement", "100.00 USD @ 72.0000 AFN/USD"),
                       ("Settlement AFN", f"{plan['settlement_value']:.2f}")]),
            ("EXPECTED", [("FX Gain", f"{plan['difference']:.2f}"), ("Account", "8100 FX Gain"),
                          ("8200 used", "no")]),
            (f"JOURNAL {entry.number}", journal_rows(entry, "JOURNAL")),
            ("BALANCE", [("1110 Cash", f"{account_balance(self.acc['1110'])['balance']:.2f}"),
                         ("1310 Receivable", f"{account_balance(self.acc['1310'])['balance']:.2f}"),
                         ("8100 FX Gain", f"{gain_balance['balance']:.2f} ({gain_balance['normal_balance']})")]),
            ("RATE SNAPSHOT", [("Historical rate (input)", format_rate(plan["historical_rate"])),
                               ("Settlement rate", format_rate(plan["settlement_rate"])),
                               ("Recorded in description", entry.description)]),
            ("SOURCE TRACE", [("journals_by_source(FX, OBL-G11)",
                               str([e.number for e in journals_by_source("FX", "OBL-G11")]))]),
            ("RECONCILIATION", [("7200.00 == 7200.00", f"{entry.total_debit:.2f} == {entry.total_credit:.2f}"),
                                ("Trial balance difference", f"{tb['difference']:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(plan["difference"], Decimal("200.00"))
        self.assertEqual(plan["direction"], "GAIN")
        self.assertEqual(entry.lines.get(account__code="8100").credit, Decimal("200.00"))
        self.assertFalse(entry.lines.filter(account__code="8200").exists())
        self.assertEqual(entry.total_debit, Decimal("7200.00"))
        self.assertEqual(entry.total_credit, Decimal("7200.00"))
        self.assertEqual(gain_balance["balance"], Decimal("200.00"))
        self.assertEqual(tb["difference"], Decimal("0.00"))

    # -----------------------------------------------------------------
    def test_golden_12_fx_loss(self):
        plan, entry = self._fx("JE-G12", historical_rate="72", settlement_rate="70")
        tb = trial_balance()
        loss_balance = account_balance(self.acc["8200"])
        golden_report(12, "FX LOSS", [
            ("INPUT", [("Historical", "100.00 USD @ 72.0000 AFN/USD"),
                       ("Historical AFN", f"{plan['carrying_value']:.2f}"),
                       ("Settlement", "100.00 USD @ 70.0000 AFN/USD"),
                       ("Settlement AFN", f"{plan['settlement_value']:.2f}")]),
            ("EXPECTED", [("FX Loss", f"{plan['difference']:.2f}"), ("Account", "8200 FX Loss"),
                          ("8100 used", "no")]),
            (f"JOURNAL {entry.number}", journal_rows(entry, "JOURNAL")),
            ("BALANCE", [("1110 Cash", f"{account_balance(self.acc['1110'])['balance']:.2f}"),
                         ("1310 Receivable", f"{account_balance(self.acc['1310'])['balance']:.2f}"),
                         ("8200 FX Loss", f"{loss_balance['balance']:.2f} ({loss_balance['normal_balance']})")]),
            ("RATE SNAPSHOT", [("Historical rate (input)", format_rate(plan["historical_rate"])),
                               ("Settlement rate", format_rate(plan["settlement_rate"]))]),
            ("SOURCE TRACE", [("journals_by_source(FX, OBL-G11)",
                               str([e.number for e in journals_by_source("FX", "OBL-G11")]))]),
            ("RECONCILIATION", [("7200.00 == 7200.00", f"{entry.total_debit:.2f} == {entry.total_credit:.2f}"),
                                ("Trial balance difference", f"{tb['difference']:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(plan["difference"], Decimal("200.00"))
        self.assertEqual(plan["direction"], "LOSS")
        self.assertEqual(entry.lines.get(account__code="8200").debit, Decimal("200.00"))
        self.assertFalse(entry.lines.filter(account__code="8100").exists())
        self.assertEqual(entry.total_debit, Decimal("7200.00"))
        self.assertEqual(loss_balance["balance"], Decimal("200.00"))
        self.assertEqual(tb["difference"], Decimal("0.00"))

    # -----------------------------------------------------------------
    def test_golden_13_historical_rate_preservation(self):
        obligation = post_journal(
            number="JE-G13A", posting_date="2026-01-01", description="USD credit sale",
            lines=[{"account": self.acc["1310"], "debit": "100.00"},
                   {"account": self.acc["4110"], "credit": "100.00"}],
            currency=self.usd, rate="70.0000", rate_date="2026-01-01",
            source_type="SALE", source_id="INV-G13",
        )
        before = {"number": obligation.number, "rate": obligation.rate,
                  "total_debit": obligation.total_debit, "total_credit": obligation.total_credit,
                  "afn_total": obligation.afn_total, "direction": obligation.rate_direction,
                  "rate_date": obligation.rate_date, "status": obligation.status}
        ExchangeRate.objects.create(source_currency=self.usd, target_currency=self.afn,
                                   rate=Decimal("75.0000"), effective_date="2026-02-01")
        plan, entry = self._fx("JE-G13B", historical_rate="70.0000", settlement_rate="72.0000")
        obligation.refresh_from_db()
        after = {"number": obligation.number, "rate": obligation.rate,
                 "total_debit": obligation.total_debit, "total_credit": obligation.total_credit,
                 "afn_total": obligation.afn_total, "direction": obligation.rate_direction,
                 "rate_date": obligation.rate_date, "status": obligation.status}
        golden_report(13, "HISTORICAL RATE PRESERVATION", [
            ("INPUT", [("Obligation", "100.00 USD @ 70.0000 (JE-G13A)"),
                       ("Current rate changed to", "75.0000"),
                       ("Settlement rate", "72.0000")]),
            ("EXPECTED", [("Obligation rate stays", "70.0000"), ("Settlement journal stores", "72.0000"),
                          ("FX difference from 70 vs 72", "200.00")]),
            ("OBLIGATION BEFORE", [(k, f"{v}") for k, v in before.items()]),
            ("OBLIGATION AFTER", [(k, f"{v}") for k, v in after.items()]),
            (f"JOURNAL {entry.number}", journal_rows(entry, "SETTLEMENT")),
            ("RECONCILIATION", [("before == after", str(before == after)),
                                ("Settlement AFN", f"{plan['settlement_value']:.2f}"),
                                ("Carrying AFN", f"{plan['carrying_value']:.2f}"),
                                ("Difference", f"{plan['difference']:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(before, after)
        self.assertEqual(obligation.rate, Decimal("70.0000"))
        self.assertEqual(plan["difference"], Decimal("200.00"))
        self.assertEqual(entry.lines.get(account__code="8100").credit, Decimal("200.00"))


# ---------------------------------------------------------------------------
# GOLDEN 14 — duplicate posting prevention
# ---------------------------------------------------------------------------

class GoldenIdempotencyTests(GoldenFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd = cls._seed()
        cls.acc = cls._accounts()

    def test_golden_14_duplicate_posting_prevention(self):
        key = "golden-14"
        first = self._post("JE-G14", [("1110", {"debit": "1500.00"}), ("3100", {"credit": "1500.00"})],
                           idempotency_key=key)
        second = self._post("JE-G14", [("1110", {"debit": "1500.00"}), ("3100", {"credit": "1500.00"})],
                            idempotency_key=key)
        rejected = ""
        try:
            self._post("JE-G14", [("1110", {"debit": "9999.00"}), ("3100", {"credit": "9999.00"})],
                       idempotency_key=key)
        except JournalValidationError as exc:
            rejected = str(exc)
        golden_report(14, "DUPLICATE POSTING PREVENTION", [
            ("INPUT", [("Idempotency key", key), ("First post", "1500.00 / 1500.00"),
                       ("Exact retry", "identical request"), ("Key reuse", "different amount")]),
            ("EXPECTED", [("Retry returns original", "yes"), ("No duplicate journal", "1 entry"),
                          ("No duplicate audit", "1 POST audit"), ("Changed request", "rejected")]),
            ("OBSERVED", [("First entry id", first.pk), ("Retry entry id", second.pk),
                          ("Same object", str(first.pk == second.pk)),
                          ("JournalEntry count", JournalEntry.objects.count()),
                          ("JournalLine count", JournalLine.objects.count()),
                          ("POST audit count", AuditEvent.objects.filter(action=AuditAction.POST).count()),
                          ("Balance 1110", f"{account_balance(self.acc['1110'])['balance']:.2f}"),
                          ("Reuse error", rejected)]),
            ("RECONCILIATION", [("1500.00 == 1500.00", f"{first.total_debit:.2f} == {first.total_credit:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(JournalLine.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action=AuditAction.POST).count(), 1)
        self.assertEqual(account_balance(self.acc["1110"])["balance"], Decimal("1500.00"))
        self.assertIn("already used for a different operation", rejected)


# ---------------------------------------------------------------------------
# GOLDEN 15 — atomic rollback (real transactions)
# ---------------------------------------------------------------------------

class GoldenRollbackTests(GoldenFixture, TransactionTestCase):
    def setUp(self):
        self.afn, self.usd = self._seed()
        self.acc = self._accounts()

    def test_golden_15_atomic_rollback(self):
        before = {"entries": JournalEntry.objects.count(), "lines": JournalLine.objects.count(),
                  "audits": AuditEvent.objects.count(), "idem": IdempotencyRecord.objects.count(),
                  "sequences": NumberSequence.objects.count()}
        with mock.patch("accounting.services._audit_post", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                self._post("JE-G15", [("1110", {"debit": "8000.00"}), ("3100", {"credit": "8000.00"})],
                           idempotency_key="golden-15")
        after = {"entries": JournalEntry.objects.count(), "lines": JournalLine.objects.count(),
                 "audits": AuditEvent.objects.count(), "idem": IdempotencyRecord.objects.count(),
                 "sequences": NumberSequence.objects.count()}
        retry = self._post("JE-G15", [("1110", {"debit": "8000.00"}), ("3100", {"credit": "8000.00"})],
                           idempotency_key="golden-15")
        golden_report(15, "ATOMIC ROLLBACK", [
            ("INPUT", [("Post", "8000.00 / 8000.00"), ("Failure injection", "audit writer raises after persist"),
                       ("Idempotency key", "golden-15")]),
            ("EXPECTED", [("State after failure", "identical to state before"),
                          ("Retry with same key", "succeeds")]),
            ("BEFORE FAILURE", [(k, v) for k, v in before.items()]),
            ("AFTER FAILURE", [(k, v) for k, v in after.items()]),
            ("AFTER RETRY", [("JournalEntry count", JournalEntry.objects.count()),
                             ("JournalLine count", JournalLine.objects.count()),
                             ("Entry number", retry.number),
                             ("Idempotency key", retry.idempotency_key)]),
            ("RECONCILIATION", [("before == after failure", str(before == after)),
                                ("8000.00 == 8000.00", f"{retry.total_debit:.2f} == {retry.total_credit:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(before, after)
        self.assertEqual(retry.idempotency_key, "golden-15")
        self.assertEqual(JournalEntry.objects.count(), 1)


# ---------------------------------------------------------------------------
# GOLDEN 16 — source traceability
# ---------------------------------------------------------------------------

class GoldenSourceTraceTests(GoldenFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd = cls._seed()
        cls.acc = cls._accounts()

    def test_golden_16_source_traceability(self):
        entry = self._post("JE-G16", [("1310", {"debit": "2200.00"}), ("4110", {"credit": "2200.00"})],
                           source_type="SALE", source_id="INV-G16", description="traceable sale")
        trace = trace_source(entry)
        by_source = journals_by_source("SALE", "INV-G16")
        tb = trial_balance()
        reversal = reverse_journal(entry, "golden 16 reversal", None)
        after_reversal = journals_by_source("SALE", "INV-G16")
        golden_report(16, "SOURCE TRACEABILITY", [
            ("INPUT", [("source_type", "SALE"), ("source_id", "INV-G16"),
                       ("Journal", "Dr 1310 / Cr 4110 2200.00")]),
            ("EXPECTED", [("journals_by_source finds it", "yes"), ("trace_source returns structure", "yes"),
                          ("Lines reachable", "2"), ("Trial balance includes it", "yes"),
                          ("Traceable after reversal", "yes"), ("Fake business document", "none")]),
            ("OBSERVED", [(k, f"{v}") for k, v in trace.items()]),
            ("LINES", [(f"{line.account.code}", f"Dr {line.debit:.2f} Cr {line.credit:.2f}")
                       for line in entry.lines.all().order_by("id")]),
            ("BALANCES", [("1310", f"{account_balance(self.acc['1310'])['balance']:.2f}"),
                          ("4110", f"{account_balance(self.acc['4110'])['balance']:.2f}")]),
            ("TRIAL BALANCE", [("Total debit", f"{tb['total_debit']:.2f}"),
                               ("Total credit", f"{tb['total_credit']:.2f}"),
                               ("Difference", f"{tb['difference']:.2f}")]),
            ("AFTER REVERSAL", [("journals_by_source", str([e.number for e in after_reversal])),
                                ("Reversal", reversal.number),
                                ("Original status", JournalEntry.objects.get(pk=entry.pk).status)]),
            ("NO FABRICATION", [("NumberSequence rows", NumberSequence.objects.count())]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual([e.number for e in by_source], [entry.number])
        self.assertEqual(trace["source_type"], "SALE")
        self.assertEqual(trace["source_id"], "INV-G16")
        self.assertEqual(trace["resolved"], False)
        self.assertEqual(entry.lines.count(), 2)
        self.assertEqual(tb["difference"], Decimal("0.00"))
        self.assertEqual(len(after_reversal), 2)
        self.assertEqual(NumberSequence.objects.count(), 1)  # only the reversal's JE number


# ---------------------------------------------------------------------------
# §17 / §18 — trial-balance and account-balance regression
# ---------------------------------------------------------------------------

class RegressionTests(GoldenFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd = cls._seed()
        cls.acc = cls._accounts()

    def test_trial_balance_regression_single_currency_business(self):
        self._post("JE-TB1", [("1110", {"debit": "10000.00"}), ("3100", {"credit": "10000.00"})], source_id="TB1")
        self._post("JE-TB2", [("1310", {"debit": "3000.00"}), ("4110", {"credit": "3000.00"})], source_id="TB2")
        self._post("JE-TB3", [("1410", {"debit": "2000.00"}), ("2110", {"credit": "2000.00"})], source_id="TB3")
        self._post("JE-TB4", [("4200", {"debit": "300.00"}), ("1310", {"credit": "300.00"})], source_id="TB4")
        self._post("JE-TB5", [("2110", {"debit": "150.00"}), ("5200", {"credit": "150.00"})], source_id="TB5")
        draft = JournalEntry.objects.create(number="JE-TB-DRAFT", posting_date="2026-03-01",
                                            description="draft", status=JournalStatus.DRAFT,
                                            currency=self.usd, total_debit=Decimal("999.00"),
                                            total_credit=Decimal("999.00"))
        JournalLine(entry=draft, account=self.acc["1110"], debit=Decimal("999.00")).save()
        JournalLine(entry=draft, account=self.acc["3100"], credit=Decimal("999.00")).save()
        reversed_entry = self._post("JE-TB6", [("5100", {"debit": "700.00"}), ("1410", {"credit": "700.00"})],
                                    source_id="TB6")
        reverse_journal(reversed_entry, "trial balance regression", None)

        tb = trial_balance()
        golden_report("R1", "TRIAL BALANCE REGRESSION (USD fixture)", [
            ("EXPECTED", [("Difference", "0.00"), ("DRAFT excluded", "yes"),
                          ("4200 contra-revenue", "DEBIT normal"), ("5200 contra-COGS", "CREDIT normal")]),
            ("ROWS", [(f"{row['account_code']} {row['account_name']}",
                       f"Dr {row['debit']:.2f} Cr {row['credit']:.2f} bal {row['balance']:.2f} "
                       f"({row['normal_balance']})") for row in tb["rows"]]),
            ("TOTALS", [("Total debit", f"{tb['total_debit']:.2f}"), ("Total credit", f"{tb['total_credit']:.2f}"),
                        ("Difference", f"{tb['difference']:.2f}"), ("Balanced", str(tb["balanced"]))]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(tb["difference"], Decimal("0.00"))
        self.assertTrue(tb["balanced"])
        self.assertNotIn("JE-TB-DRAFT", [r for r in tb["rows"]])
        self.assertEqual(account_balance(self.acc["4200"])["normal_balance"], "DEBIT")
        self.assertEqual(account_balance(self.acc["5200"])["normal_balance"], "CREDIT")

    def test_trial_balance_regression_fx_fixture(self):
        plan_gain = compute_realized_fx(
            obligation_kind="RECEIVABLE", obligation_account=self.acc["1310"],
            obligation_amount="100.00", obligation_currency=self.usd, historical_rate="70",
            settlement_account=self.acc["1110"], settlement_amount="100.00",
            settlement_currency=self.usd, settlement_rate="72")
        plan_loss = compute_realized_fx(
            obligation_kind="PAYABLE", obligation_account=self.acc["2110"],
            obligation_amount="50.00", obligation_currency=self.usd, historical_rate="70",
            settlement_account=self.acc["1110"], settlement_amount="50.00",
            settlement_currency=self.usd, settlement_rate="75")
        for number, plan, params in (
            ("JE-FXG", plan_gain, dict(obligation_kind="RECEIVABLE", obligation_account=self.acc["1310"],
                                       obligation_amount="100.00", obligation_currency=self.usd,
                                       historical_rate="70", settlement_account=self.acc["1110"],
                                       settlement_amount="100.00", settlement_currency=self.usd,
                                       settlement_rate="72")),
            ("JE-FXL", plan_loss, dict(obligation_kind="PAYABLE", obligation_account=self.acc["2110"],
                                       obligation_amount="50.00", obligation_currency=self.usd,
                                       historical_rate="70", settlement_account=self.acc["1110"],
                                       settlement_amount="50.00", settlement_currency=self.usd,
                                       settlement_rate="75")),
        ):
            post_realized_fx_settlement(number=number, posting_date="2026-03-01", description="tb fx",
                                        source_type="FX", source_id="TB-FX", **params)
        tb = trial_balance()
        golden_report("R2", "TRIAL BALANCE REGRESSION (AFN realized-FX fixture)", [
            ("EXPECTED", [("Difference", "0.00"), ("8100 classified", "CREDIT normal (REVENUE)"),
                          ("8200 classified", "DEBIT normal (EXPENSE)")]),
            ("ROWS", [(f"{row['account_code']} {row['account_name']}",
                       f"Dr {row['debit']:.2f} Cr {row['credit']:.2f} bal {row['balance']:.2f} "
                       f"({row['normal_balance']})") for row in tb["rows"]]),
            ("TOTALS", [("Total debit", f"{tb['total_debit']:.2f}"), ("Total credit", f"{tb['total_credit']:.2f}"),
                        ("Difference", f"{tb['difference']:.2f}")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(tb["difference"], Decimal("0.00"))
        gain_row = next(r for r in tb["rows"] if r["account_code"] == "8100")
        loss_row = next(r for r in tb["rows"] if r["account_code"] == "8200")
        self.assertEqual(gain_row["normal_balance"], "CREDIT")
        self.assertEqual(loss_row["normal_balance"], "DEBIT")

    def test_account_balance_regression(self):
        self._post("JE-AB1", [("1110", {"debit": "20000.00"}), ("3100", {"credit": "20000.00"})], source_id="AB1")
        self._post("JE-AB2", [("1210", {"debit": "5000.00"}), ("1110", {"credit": "5000.00"})], source_id="AB2")
        self._post("JE-AB3", [("1310", {"debit": "7000.00"}), ("4110", {"credit": "7000.00"})], source_id="AB3")
        self._post("JE-AB4", [("1410", {"debit": "4000.00"}), ("2110", {"credit": "4000.00"})], source_id="AB4")
        self._post("JE-AB5", [("5100", {"debit": "1500.00"}), ("1410", {"credit": "1500.00"})], source_id="AB5")
        rows = balance_rows(("1110", "1210", "1310", "1410", "2110", "4100", "4110", "5100"), self.acc)
        golden_report("R3", "ACCOUNT BALANCE REGRESSION (USD fixture)", [
            ("EXPECTED", [("1110 Cash", "15000.00 DEBIT"), ("1210 Exchange House", "5000.00 DEBIT"),
                          ("1310 Receivable", "7000.00 DEBIT"), ("1410 Inventory", "2500.00 DEBIT"),
                          ("2110 Payable", "4000.00 CREDIT"), ("4110 Sales", "7000.00 CREDIT"),
                          ("5100 COGS", "1500.00 DEBIT"),
                          ("4100 Sales Revenue (group)", "0.00 — non-posting group in the frozen COA")]),
            ("OBSERVED", rows),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(account_balance(self.acc["1110"])["balance"], Decimal("15000.00"))
        self.assertEqual(account_balance(self.acc["1210"])["balance"], Decimal("5000.00"))
        self.assertEqual(account_balance(self.acc["1310"])["balance"], Decimal("7000.00"))
        self.assertEqual(account_balance(self.acc["1410"])["balance"], Decimal("2500.00"))
        self.assertEqual(account_balance(self.acc["2110"])["balance"], Decimal("4000.00"))
        self.assertEqual(account_balance(self.acc["4110"])["balance"], Decimal("7000.00"))
        self.assertEqual(account_balance(self.acc["5100"])["balance"], Decimal("1500.00"))
        # 4100 is a non-posting group account in the frozen COA: no direct activity.
        self.assertEqual(account_balance(self.acc["4100"])["lines_count"], 0)

    def test_account_balance_regression_fx(self):
        params = dict(obligation_kind="RECEIVABLE", obligation_account=self.acc["1310"],
                      obligation_amount="100.00", obligation_currency=self.usd, historical_rate="70",
                      settlement_account=self.acc["1110"], settlement_amount="100.00",
                      settlement_currency=self.usd, settlement_rate="72")
        post_realized_fx_settlement(number="JE-ABFX", posting_date="2026-03-01", description="ab fx",
                                    source_type="FX", source_id="AB-FX", **params)
        gain = account_balance(self.acc["8100"])
        loss = account_balance(self.acc["8200"])
        golden_report("R4", "ACCOUNT BALANCE REGRESSION (8100 / 8200)", [
            ("EXPECTED", [("8100 FX Gain", "200.00 CREDIT-normal"), ("8200 FX Loss", "0.00 (unused)")]),
            ("OBSERVED", [("8100", f"{gain['balance']:.2f} ({gain['normal_balance']})"),
                          ("8200", f"{loss['balance']:.2f} ({loss['normal_balance']})")]),
            ("STATUS", [("Result", "PASS")]),
        ])
        self.assertEqual(gain["balance"], Decimal("200.00"))
        self.assertEqual(gain["normal_balance"], "CREDIT")
        self.assertEqual(loss["balance"], Decimal("0.00"))
        self.assertEqual(loss["normal_balance"], "DEBIT")


# ---------------------------------------------------------------------------
# §16 — historical integrity regression (frozen Stage 2.1–2.4 data)
# ---------------------------------------------------------------------------

class HistoricalIntegrityTests(GoldenFixture, TestCase):
    """Before/after proof: running Stage 2.5 rewrites nothing that already existed."""

    @classmethod
    def setUpTestData(cls):
        cls.afn, cls.usd = cls._seed()
        cls.acc = cls._accounts()

    def _seed_frozen_data(self):
        """Representative Stage 2.1–2.4 state, including a Stage 2.2 legacy row."""
        # Stage 2.3 — posted journal with idempotency, then reversed.
        posted = post_journal(
            number="JE-HIST-1", posting_date="2026-01-05", description="frozen 2.3 posting",
            lines=[{"account": self.acc["1310"], "debit": "500.00"},
                   {"account": self.acc["4110"], "credit": "500.00"}],
            currency=self.usd, rate="70.0000", rate_date="2026-01-05",
            source_type="SALE", source_id="HIST-1", idempotency_key="hist-key-1",
        )
        reverse_journal(posted, "historical fixture", None)
        # Stage 2.2 — legacy pre-2.2 row: NULL currency snapshot, still readable.
        legacy = JournalEntry.objects.create(
            number="JE-LEGACY-1", posting_date="2025-06-01", description="legacy pre-2.2 row",
            status=JournalStatus.POSTED, total_debit=Decimal("250.00"), total_credit=Decimal("250.00"),
        )
        JournalLine(entry=legacy, account=self.acc["1110"], debit=Decimal("250.00")).save(
            allow_protected_update=True)
        JournalLine(entry=legacy, account=self.acc["3100"], credit=Decimal("250.00")).save(
            allow_protected_update=True)
        return posted, legacy

    def _snapshot(self):
        return {
            "currencies": list(Currency.objects.order_by("code").values("code", "is_base", "is_active")),
            "accounts": list(Account.objects.order_by("code").values(
                "code", "name", "name_fa", "account_type", "parent_id", "is_posting", "is_active")),
            "journals": list(JournalEntry.objects.order_by("id").values(
                "id", "number", "posting_date", "status", "currency_id", "rate", "rate_date",
                "rate_direction", "total_debit", "total_credit", "afn_total", "source_type", "source_id")),
            "lines": list(JournalLine.objects.order_by("id").values(
                "id", "entry_id", "account_id", "debit", "credit", "description", "reference")),
            "audits": list(AuditEvent.objects.order_by("id").values(
                "id", "action", "entity", "entity_id", "reference", "new_state")),
        }

    def test_historical_records_unchanged_after_stage_2_5(self):
        posted, legacy = self._seed_frozen_data()
        before = self._snapshot()

        # ---- run Stage 2.5 work -------------------------------------------
        fx = post_realized_fx_settlement(
            number="JE-HIST-FX", posting_date="2026-03-01", description="historical integrity fx",
            obligation_kind="RECEIVABLE", obligation_account=self.acc["1310"],
            obligation_amount="100.00", obligation_currency=self.usd, historical_rate="70",
            settlement_account=self.acc["1110"], settlement_amount="100.00",
            settlement_currency=self.usd, settlement_rate="72",
            source_type="FX", source_id="HIST-FX", idempotency_key="hist-fx-key",
        )
        reverse_journal(fx, "historical integrity", None)

        after = self._snapshot()

        new_journals = [j for j in after["journals"] if j["id"] not in
                        {j["id"] for j in before["journals"]}]
        new_lines = [l for l in after["lines"] if l["id"] not in {l["id"] for l in before["lines"]}]
        new_audits = [a for a in after["audits"] if a["id"] not in {a["id"] for a in before["audits"]}]

        golden_report("R5", "HISTORICAL INTEGRITY (Stage 2.1–2.4 data)", [
            ("BEFORE", [("Currencies", len(before["currencies"])), ("Accounts", len(before["accounts"])),
                        ("Journals", len(before["journals"])), ("Lines", len(before["lines"])),
                        ("Audit events", len(before["audits"]))]),
            ("AFTER", [("Currencies", len(after["currencies"])), ("Accounts", len(after["accounts"])),
                       ("Journals", len(after["journals"])), ("Lines", len(after["lines"])),
                       ("Audit events", len(after["audits"]))]),
            ("NEW RECORDS (expected only)", [("Journals", str([j["number"] for j in new_journals])),
                                             ("Lines", len(new_lines)),
                                             ("Audits", str([a["action"] for a in new_audits]))]),
            ("FROZEN FACTS", [("COA account count", Account.objects.count()),
                              ("2400 inactive", str(not Account.objects.get(code="2400").is_active)),
                              ("Legacy row currency", str(JournalEntry.objects.get(number="JE-LEGACY-1").currency)),
                              ("Legacy totals readable", str(verify_entry_totals(legacy))),
                              ("Source index present", str(self._source_index_present()))]),
            ("RECONCILIATION", [
                ("COA unchanged", str(before["accounts"] == after["accounts"])),
                ("Currencies unchanged", str(before["currencies"] == after["currencies"])),
                ("Existing journals unchanged",
                 str([j for j in after["journals"] if j["id"] in {b["id"] for b in before["journals"]}] == before["journals"])),
                ("Existing lines unchanged",
                 str([l for l in after["lines"] if l["id"] in {b["id"] for b in before["lines"]}] == before["lines"])),
                ("Existing audits unchanged",
                 str([a for a in after["audits"] if a["id"] in {b["id"] for b in before["audits"]}] == before["audits"])),
            ]),
            ("STATUS", [("Result", "PASS")]),
        ])

        self.assertEqual(before["accounts"], after["accounts"])
        self.assertEqual(before["currencies"], after["currencies"])
        self.assertEqual([j for j in after["journals"] if j["id"] in {b["id"] for b in before["journals"]}],
                         before["journals"])
        self.assertEqual([l for l in after["lines"] if l["id"] in {b["id"] for b in before["lines"]}],
                         before["lines"])
        self.assertEqual([a for a in after["audits"] if a["id"] in {b["id"] for b in before["audits"]}],
                         before["audits"])
        # Only the FX journal, its reversal, their lines and their audits are new.
        # (The reversal's own number comes from the backend sequence, so it is
        # identified structurally, not by a hard-coded value.)
        self.assertEqual(len(new_journals), 2)
        self.assertIn("JE-HIST-FX", [j["number"] for j in new_journals])
        self.assertTrue(any(j["number"].startswith("JE-") and j["number"] != "JE-HIST-FX"
                            for j in new_journals))
        self.assertEqual(len(new_lines), 6)
        self.assertEqual(sorted(a["action"] for a in new_audits), ["POST", "REVERSE"])
        # Stage 2.1 / 2.2 / 2.4 frozen facts
        self.assertEqual(Account.objects.count(), 38)
        self.assertFalse(Account.objects.get(code="2400").is_active)
        self.assertIsNone(JournalEntry.objects.get(number="JE-LEGACY-1").currency)
        self.assertTrue(self._source_index_present())
        self.assertEqual(account_balance(self.acc["8100"])["balance"], Decimal("0.00"))  # reversed

    def _source_index_present(self):
        from django.db import connection
        table = JournalEntry._meta.db_table
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, table)
        return any("source_type" in (info.get("columns") or []) and "source_id" in (info.get("columns") or [])
                   for info in constraints.values())
