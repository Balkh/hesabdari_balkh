from decimal import Decimal
from django.db import IntegrityError
from django.test import TestCase
from currencies.models import Currency
from .models import Account, AccountType, JournalStatus
from .services import JournalValidationError, post_journal


class AccountingFoundationTests(TestCase):
    def setUp(self):
        self.cash = Account.objects.create(code="1100", name="Cash", account_type=AccountType.ASSET)
        self.revenue = Account.objects.create(code="4100", name="Sales Revenue", account_type=AccountType.REVENUE)
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)

    def test_balanced_entry_posts(self):
        entry = post_journal(
            number="JE-1405-00001", posting_date="2026-09-06", description="Foundation test",
            lines=[{"account": self.cash, "debit": "100.00"}, {"account": self.revenue, "credit": "100.00"}],
            currency=self.afn,
        )
        self.assertEqual(entry.status, JournalStatus.POSTED)
        self.assertEqual(entry.lines.count(), 2)
        self.assertEqual(sum(x.debit for x in entry.lines.all()), Decimal("100.00"))
        self.assertEqual(sum(x.credit for x in entry.lines.all()), Decimal("100.00"))

    def test_unbalanced_entry_is_rejected_without_entry(self):
        with self.assertRaises(JournalValidationError):
            post_journal(number="JE-1405-00002", posting_date="2026-09-06", description="Invalid", lines=[{"account": self.cash, "debit": 100}, {"account": self.revenue, "credit": 99}], currency=self.afn)
        from .models import JournalEntry
        self.assertFalse(JournalEntry.objects.filter(number="JE-1405-00002").exists())

    def test_duplicate_number_is_rejected(self):
        post_journal(number="JE-1405-00003", posting_date="2026-09-06", description="First", lines=[{"account": self.cash, "debit": 10}, {"account": self.revenue, "credit": 10}], currency=self.afn)
        with self.assertRaises(IntegrityError):
            post_journal(number="JE-1405-00003", posting_date="2026-09-06", description="Duplicate", lines=[{"account": self.cash, "debit": 10}, {"account": self.revenue, "credit": 10}], currency=self.afn)

    def test_parent_account_cannot_receive_posting(self):
        parent = Account.objects.create(code="1000", name="Assets", account_type=AccountType.ASSET, is_posting=False)
        with self.assertRaises(JournalValidationError):
            post_journal(number="JE-1405-00004", posting_date="2026-09-06", description="Invalid parent", lines=[{"account": parent, "debit": 10}, {"account": self.revenue, "credit": 10}], currency=self.afn)
