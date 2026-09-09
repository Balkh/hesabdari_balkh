"""Stage 2.1 — Canonical Chart of Accounts tests (handoff §§8–14, §18).

The EXPECTED_* tables below are an INDEPENDENT oracle transcribed from the
authoritative Phase 2 handoff — they are deliberately NOT imported from
``coa.py``. Agreement between the oracle and the seeded database proves the
implementation matches the specification; any transcription error on either
side fails loudly here.

Conventions:
- FA names are proposed canonical labels; final authority is user review.
- Posting tests exercise the real ``post_journal`` path (Stage 2.2 contract).
- The universal test counter-account is 3900 (handoff §19, test use only).
"""

from decimal import Decimal
from unittest import mock

from django.test import TestCase
from currencies.models import Currency

from . import coa as coa_module
from .coa import COASeedError, seed_chart_of_accounts
from .models import Account, JournalEntry, JournalStatus
from .services import JournalValidationError, post_journal

# Independent oracle: (code, name_en, name_fa, type, parent_code, is_posting, is_active)
EXPECTED_COA = (
    ("1000", "Assets", "دارایی‌ها", "ASSET", None, False, True),
    ("1100", "Cash & Bank", "نقد و بانک", "ASSET", "1000", False, True),
    ("1110", "Cash in Hand", "نقد در صندوق", "ASSET", "1100", True, True),
    ("1120", "Bank Accounts", "حسابات بانکی", "ASSET", "1100", True, True),
    ("1200", "Exchange House Accounts", "حسابات صرافی", "ASSET", "1000", False, True),
    ("1210", "Exchange House A", "صرافی الف", "ASSET", "1200", True, True),
    ("1220", "Exchange House B", "صرافی ب", "ASSET", "1200", True, True),
    ("1300", "Accounts Receivable", "حسابات دریافتنی", "ASSET", "1000", False, True),
    ("1310", "Trade Receivables", "دریافتنی‌های تجاری", "ASSET", "1300", True, True),
    ("1400", "Inventory", "موجودی کالا", "ASSET", "1000", False, True),
    ("1410", "Main Warehouse", "گدام اصلی", "ASSET", "1400", True, True),
    ("1420", "Secondary Warehouse", "گدام فرعی", "ASSET", "1400", True, True),
    ("1500", "Supplier Advances", "پیش‌پرداخت به تأمین‌کنندگان", "ASSET", "1000", True, True),
    ("1900", "Other Assets", "سایر دارایی‌ها", "ASSET", "1000", True, True),
    ("2000", "Liabilities", "بدهی‌ها", "LIABILITY", None, False, True),
    ("2100", "Accounts Payable", "حسابات پرداختنی", "LIABILITY", "2000", False, True),
    ("2110", "Trade Payables", "پرداختنی‌های تجاری", "LIABILITY", "2100", True, True),
    ("2200", "Customer Advances / Credits", "پیش‌پرداخت و اعتبار مشتریان", "LIABILITY", "2000", True, True),
    ("2400", "Tax Payable", "مالیات پرداختنی", "LIABILITY", "2000", False, False),
    ("2900", "Other Liabilities", "سایر بدهی‌ها", "LIABILITY", "2000", True, True),
    ("3000", "Equity", "حقوق مالک", "EQUITY", None, False, True),
    ("3100", "Owner Capital", "سرمایه مالک", "EQUITY", "3000", True, True),
    ("3900", "Opening Balance Equity", "حساب توازن افتتاحیه", "EQUITY", "3000", True, True),
    ("3950", "Retained Earnings", "سود انباشته", "EQUITY", "3000", True, True),
    ("4000", "Revenue", "عواید", "REVENUE", None, False, True),
    ("4100", "Sales Revenue", "عواید فروش", "REVENUE", "4000", False, True),
    ("4110", "Wholesale Sales", "فروش عمده", "REVENUE", "4100", True, True),
    ("4120", "Retail Sales", "فروش پرچون", "REVENUE", "4100", True, True),
    ("4200", "Sales Returns", "برگشتی فروش", "REVENUE", "4000", True, True),
    ("5000", "Cost of Goods Sold", "بهای تمام‌شده فروش", "EXPENSE", None, False, True),
    ("5100", "COGS", "بهای تمام‌شده کالای فروش‌رفته", "EXPENSE", "5000", True, True),
    ("5200", "Purchase Returns", "برگشتی خرید", "EXPENSE", "5000", True, True),
    ("6000", "Expenses", "مصارف", "EXPENSE", None, False, True),
    ("6100", "Operating Expenses", "مصارف عملیاتی", "EXPENSE", "6000", True, True),
    ("6200", "Freight & Transport", "کرایه و حمل‌ونقل", "EXPENSE", "6000", True, True),
    ("6300", "Salaries", "معاشات", "EXPENSE", "6000", True, True),
    ("8100", "Foreign Exchange Gain", "عاید تبادله ارز", "REVENUE", None, True, True),
    ("8200", "Foreign Exchange Loss", "ضرر تبادله ارز", "EXPENSE", None, True, True),
)

EXPECTED_CODES = tuple(row[0] for row in EXPECTED_COA)

# Handoff §9 — exact group list (12).
GROUP_CODES = (
    "1000", "1100", "1200", "1300", "1400", "2000",
    "2100", "3000", "4000", "4100", "5000", "6000",
)

# Handoff §10 — exact posting list (25).
POSTING_CODES = (
    "1110", "1120", "1210", "1220", "1310", "1410", "1420", "1500", "1900",
    "2110", "2200", "2900", "3100", "3900", "3950", "4110", "4120", "4200",
    "5100", "5200", "6100", "6200", "6300", "8100", "8200",
)

POSTING_DATE = "2026-09-09"
AMOUNT = Decimal("100.00")


def _db_snapshot():
    """Full ordered state of canonical accounts in the database."""
    rows = []
    for account in Account.objects.filter(code__in=EXPECTED_CODES).order_by("code"):
        rows.append((
            account.code, account.name, account.name_fa, str(account.account_type),
            account.parent.code if account.parent else None,
            account.is_posting, account.is_active,
        ))
    return rows


class SeedIdempotencyTests(TestCase):
    """Handoff TEST 1 — seed twice, prove identical database state."""

    def test_seed_twice_produces_identical_state(self):
        first = seed_chart_of_accounts()
        snapshot_before = _db_snapshot()
        second = seed_chart_of_accounts()
        snapshot_after = _db_snapshot()

        self.assertEqual(first, {"created": 38, "updated": 0, "total_canonical": 38})
        self.assertEqual(second, {"created": 0, "updated": 0, "total_canonical": 38})
        self.assertEqual(len(snapshot_before), 38)
        self.assertEqual(snapshot_before, snapshot_after)
        codes = [row[0] for row in snapshot_after]
        self.assertEqual(len(codes), len(set(codes)))  # no duplicate codes

    def test_seed_converges_stale_canonical_row(self):
        Account.objects.create(code="1100", name="Cash", account_type="ASSET")
        result = seed_chart_of_accounts()
        self.assertEqual(result, {"created": 37, "updated": 1, "total_canonical": 38})
        account = Account.objects.get(code="1100")
        self.assertEqual(account.name, "Cash & Bank")
        self.assertEqual(account.name_fa, "نقد و بانک")
        self.assertEqual(account.parent.code, "1000")
        self.assertFalse(account.is_posting)

    def test_seed_is_non_destructive_to_unknown_accounts(self):
        custom = Account.objects.create(
            code="9999", name="Custom", name_fa="سفارشی",
            account_type="ASSET", is_posting=True, is_active=True,
        )
        seed_chart_of_accounts()
        custom.refresh_from_db()
        self.assertEqual(custom.name, "Custom")
        self.assertEqual(custom.name_fa, "سفارشی")
        self.assertTrue(custom.is_posting)
        self.assertTrue(custom.is_active)
        self.assertEqual(Account.objects.filter(code__in=EXPECTED_CODES).count(), 38)


class COAContractTests(TestCase):
    """Handoff TESTS 2–6 — every canonical account matches the contract."""

    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()

    def test_canonical_count_is_38(self):
        self.assertEqual(len(EXPECTED_COA), 38)
        self.assertEqual(Account.objects.filter(code__in=EXPECTED_CODES).count(), 38)

    def test_every_account_matches_contract(self):
        for code, name_en, name_fa, type_, parent_code, is_posting, is_active in EXPECTED_COA:
            with self.subTest(code=code):
                account = Account.objects.get(code=code)
                self.assertEqual(account.name, name_en)
                self.assertEqual(account.name_fa, name_fa)
                self.assertEqual(str(account.account_type), type_)
                self.assertEqual(account.parent.code if account.parent else None, parent_code)
                self.assertEqual(account.is_posting, is_posting)
                self.assertEqual(account.is_active, is_active)

    def test_names_are_bilingual_and_separate(self):
        for account in Account.objects.filter(code__in=EXPECTED_CODES):
            with self.subTest(code=account.code):
                self.assertTrue(account.name)
                self.assertTrue(account.name_fa)
                self.assertNotEqual(account.name, account.name_fa)
                self.assertTrue(account.name.isascii())  # English only in `name`
                self.assertFalse(account.name_fa.isascii())  # Persian script in `name_fa`

    def test_group_posting_and_active_flags_match_handoff(self):
        for code in GROUP_CODES:
            with self.subTest(code=code):
                account = Account.objects.get(code=code)
                self.assertFalse(account.is_posting)
                self.assertTrue(account.is_active)
        for code in POSTING_CODES:
            with self.subTest(code=code):
                account = Account.objects.get(code=code)
                self.assertTrue(account.is_posting)
                self.assertTrue(account.is_active)

    def test_top_level_accounts_have_no_parent_and_no_8000_exists(self):
        for code in ("1000", "2000", "3000", "4000", "5000", "6000", "8100", "8200"):
            with self.subTest(code=code):
                self.assertIsNone(Account.objects.get(code=code).parent)
        self.assertFalse(Account.objects.filter(code="8000").exists())


class GroupRejectionTests(TestCase):
    """Handoff TEST 7 — every group account rejects posting, nothing persists."""

    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)

    def test_every_group_account_rejects_posting(self):
        counter = Account.objects.get(code="3900")
        for code in GROUP_CODES:
            with self.subTest(code=code):
                number = f"JE-1405-G{code}"
                before = JournalEntry.objects.count()
                with self.assertRaises(JournalValidationError):
                    post_journal(
                        number=number, posting_date=POSTING_DATE,
                        description=f"Stage 2.1 group rejection probe {code}",
                        currency=self.afn,
                        lines=[
                            {"account": Account.objects.get(code=code), "debit": AMOUNT},
                            {"account": counter, "credit": AMOUNT},
                        ],
                    )
                self.assertEqual(JournalEntry.objects.count(), before)
                self.assertFalse(JournalEntry.objects.filter(number=number).exists())


class PostingAcceptanceTests(TestCase):
    """Handoff TEST 8 — every posting account accepts a balanced posting."""

    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)

    def test_every_posting_account_accepts_balanced_posting(self):
        for code in POSTING_CODES:
            with self.subTest(code=code):
                account = Account.objects.get(code=code)
                counter_code = "1110" if code == "3900" else "3900"
                number = f"JE-1405-P{code}"
                entry = post_journal(
                    number=number, posting_date=POSTING_DATE,
                    description=f"Stage 2.1 posting acceptance probe {code}",
                        currency=self.afn,
                    lines=[
                        {"account": account, "debit": AMOUNT},
                        {"account": Account.objects.get(code=counter_code), "credit": AMOUNT},
                    ],
                )
                self.assertEqual(entry.status, JournalStatus.POSTED)
                persisted = JournalEntry.objects.get(number=number)
                debits = sum((line.debit for line in persisted.lines.all()), Decimal("0"))
                credits = sum((line.credit for line in persisted.lines.all()), Decimal("0"))
                self.assertEqual(debits, AMOUNT)
                self.assertEqual(credits, AMOUNT)


class Tax2400Tests(TestCase):
    """Handoff TEST 9 — 2400 is inactive/non-posting and rejects posting."""

    @classmethod
    def setUpTestData(cls):
        seed_chart_of_accounts()
        cls.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)

    def test_2400_is_inactive_and_non_posting(self):
        account = Account.objects.get(code="2400")
        self.assertFalse(account.is_posting)
        self.assertFalse(account.is_active)
        self.assertEqual(account.parent.code, "2000")

    def test_2400_rejects_posting_without_persisting(self):
        number = "JE-1405-G2400"
        before = JournalEntry.objects.count()
        with self.assertRaises(JournalValidationError):
            post_journal(
                number=number, posting_date=POSTING_DATE,
                description="Stage 2.1 2400 rejection probe",
                currency=self.afn,
                lines=[
                    {"account": Account.objects.get(code="2400"), "debit": AMOUNT},
                    {"account": Account.objects.get(code="3900"), "credit": AMOUNT},
                ],
            )
        self.assertEqual(JournalEntry.objects.count(), before)
        self.assertFalse(JournalEntry.objects.filter(number=number).exists())


class SeedFailureRollbackTests(TestCase):
    """Seed failure atomicity: a broken seed persists nothing (G5)."""

    def test_missing_parent_aborts_seed_without_partial_state(self):
        bad_coa = (
            ("1000", "Assets", "دارایی‌ها", "ASSET", None, False, True),
            ("1999", "Broken", "خراب", "ASSET", "9999", True, True),
        )
        with mock.patch.object(coa_module, "CANONICAL_COA", bad_coa):
            with self.assertRaises(COASeedError):
                seed_chart_of_accounts()
        self.assertEqual(Account.objects.count(), 0)
