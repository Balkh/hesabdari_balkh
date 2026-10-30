from io import StringIO

from django.core.management import call_command, CommandError
from django.test import TestCase

from accounting.coa import CANONICAL_COA
from accounting.models import Account
from currencies.models import Currency
from security.models import AuditEvent


class FreshDatabaseBootstrapTests(TestCase):
    def test_fresh_database_creates_canonical_coa_currencies_and_audit(self):
        output = StringIO()

        call_command("bootstrap_fresh_database", stdout=output)

        self.assertEqual(Account.objects.count(), len(CANONICAL_COA))
        self.assertEqual(set(Currency.objects.values_list("code", flat=True)), {"AFN", "USD"})
        afn = Currency.objects.get(code="AFN")
        usd = Currency.objects.get(code="USD")
        self.assertTrue(afn.is_base)
        self.assertEqual(afn.decimal_places, 2)
        self.assertFalse(usd.is_base)
        self.assertEqual(usd.decimal_places, 2)
        self.assertEqual(AuditEvent.objects.filter(entity="SystemBootstrap").count(), 1)
        self.assertIn("Bootstrap completed", output.getvalue())

    def test_repeat_run_is_noop_and_does_not_duplicate_audit(self):
        call_command("bootstrap_fresh_database")
        account_count = Account.objects.count()
        currency_count = Currency.objects.count()
        audit_count = AuditEvent.objects.count()

        output = StringIO()
        call_command("bootstrap_fresh_database", stdout=output)

        self.assertEqual(Account.objects.count(), account_count)
        self.assertEqual(Currency.objects.count(), currency_count)
        self.assertEqual(AuditEvent.objects.count(), audit_count)
        self.assertIn("no data changed", output.getvalue())

    def test_partial_database_is_refused_without_mutation(self):
        Account.objects.create(
            code="1000",
            name="Assets",
            account_type="ASSET",
            is_posting=False,
        )

        with self.assertRaises(CommandError):
            call_command("bootstrap_fresh_database")

        self.assertEqual(Account.objects.count(), 1)
        self.assertEqual(Currency.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_existing_accountant_edit_is_never_overwritten(self):
        call_command("bootstrap_fresh_database")
        account = Account.objects.get(code="1110")
        account.name = "Accountant-approved cash name"
        account.save(update_fields=["name"])

        with self.assertRaises(CommandError):
            call_command("bootstrap_fresh_database")

        account.refresh_from_db()
        self.assertEqual(account.name, "Accountant-approved cash name")
