from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.db import connections
from django.test import TestCase

from accounting.coa import CANONICAL_COA
from accounting.models import Account
from categories.models import Category
from currencies.models import Currency
from security.models import AuditAction, AuditEvent


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
        self.assertEqual(
            AuditEvent.objects.filter(
                entity="SystemBootstrap", reference="fresh-database-v1",
                action=AuditAction.CREATE,
            ).count(),
            1,
        )
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

    def test_rerun_refuses_when_bootstrap_audit_event_is_missing(self):
        call_command("bootstrap_fresh_database")
        AuditEvent.objects.filter(
            entity="SystemBootstrap", reference="fresh-database-v1"
        ).delete()

        with self.assertRaisesMessage(CommandError, "expected exactly one bootstrap audit event"):
            call_command("bootstrap_fresh_database")

        self.assertEqual(Account.objects.count(), len(CANONICAL_COA))
        self.assertEqual(set(Currency.objects.values_list("code", flat=True)), {"AFN", "USD"})
        self.assertFalse(AuditEvent.objects.filter(entity="SystemBootstrap").exists())

    def test_rerun_refuses_when_bootstrap_audit_event_is_duplicated(self):
        call_command("bootstrap_fresh_database")
        AuditEvent.objects.create(
            action=AuditAction.CREATE,
            entity="SystemBootstrap",
            reference="fresh-database-v1",
            reason="Duplicate audit fixture",
        )

        with self.assertRaisesMessage(CommandError, "expected exactly one bootstrap audit event"):
            call_command("bootstrap_fresh_database")

        self.assertEqual(
            AuditEvent.objects.filter(
                entity="SystemBootstrap", reference="fresh-database-v1"
            ).count(),
            2,
        )

    def test_fresh_database_refuses_existing_orphaned_bootstrap_audit(self):
        event = AuditEvent.objects.create(
            action=AuditAction.CREATE,
            entity="SystemBootstrap",
            reference="fresh-database-v1",
            reason="Orphaned bootstrap marker fixture",
        )

        with self.assertRaisesMessage(CommandError, "a bootstrap audit event already exists"):
            call_command("bootstrap_fresh_database")

        self.assertEqual(Account.objects.count(), 0)
        self.assertEqual(Currency.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.get(pk=event.pk).reason, "Orphaned bootstrap marker fixture")

    def test_audit_failure_rolls_back_all_bootstrap_rows(self):
        with patch(
            "accounting.management.commands.bootstrap_fresh_database.record_audit_event",
            side_effect=RuntimeError("simulated audit storage failure"),
        ):
            with self.assertRaisesMessage(RuntimeError, "simulated audit storage failure"):
                call_command("bootstrap_fresh_database")

        self.assertEqual(Account.objects.count(), 0)
        self.assertEqual(Currency.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_rerun_refuses_when_bootstrap_audit_action_is_wrong(self):
        call_command("bootstrap_fresh_database")
        event = AuditEvent.objects.get(
            entity="SystemBootstrap", reference="fresh-database-v1"
        )
        event.action = AuditAction.UPDATE
        event.save(update_fields=["action"])

        with self.assertRaisesMessage(CommandError, "unexpected action"):
            call_command("bootstrap_fresh_database")

    def test_rerun_refuses_when_another_base_currency_exists(self):
        call_command("bootstrap_fresh_database")
        # The schema enforces at most one base currency. Move the base flag
        # rather than attempting an impossible second is_base=True insert.
        afn = Currency.objects.get(code="AFN")
        afn.is_base = False
        afn.save(update_fields=["is_base"])
        Currency.objects.create(
            code="EUR",
            name="Euro",
            symbol="€",
            decimal_places=2,
            is_base=True,
            is_active=True,
        )

        with self.assertRaises(CommandError) as raised:
            call_command("bootstrap_fresh_database")

        self.assertIn("a currency other than AFN is marked as base", str(raised.exception))
        afn.refresh_from_db()
        self.assertFalse(afn.is_base)
        self.assertTrue(Currency.objects.get(code="EUR").is_base)

    def test_existing_currency_edit_is_never_overwritten(self):
        call_command("bootstrap_fresh_database")
        currency = Currency.objects.get(code="USD")
        currency.name = "Accountant-approved USD label"
        currency.save(update_fields=["name"])

        with self.assertRaises(CommandError):
            call_command("bootstrap_fresh_database")

        currency.refresh_from_db()
        self.assertEqual(currency.name, "Accountant-approved USD label")

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

    def test_existing_non_accounting_erp_data_blocks_bootstrap(self):
        category = Category.objects.create(name="Pre-existing category")

        with self.assertRaisesMessage(CommandError, "categories.Category"):
            call_command("bootstrap_fresh_database")

        self.assertEqual(Category.objects.get(pk=category.pk).name, "Pre-existing category")
        self.assertEqual(Account.objects.count(), 0)
        self.assertEqual(Currency.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_existing_user_blocks_bootstrap(self):
        user = get_user_model().objects.create_user(username="bootstrap-blocker")

        with self.assertRaisesMessage(CommandError, "auth.User"):
            call_command("bootstrap_fresh_database")

        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
        self.assertEqual(Account.objects.count(), 0)
        self.assertEqual(Currency.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_missing_bootstrap_tables_are_reported_before_any_model_query(self):
        existing_tables = set(connections["default"].introspection.table_names())

        for model in (Account, Currency, AuditEvent):
            with self.subTest(model=model._meta.label):
                table_names = sorted(existing_tables - {model._meta.db_table})
                with patch.object(
                    connections["default"].introspection,
                    "table_names",
                    return_value=table_names,
                ):
                    # If the command reaches an ORM query before the schema
                    # preflight, this assertion error escapes instead.
                    with patch.object(
                        Account.objects,
                        "exists",
                        side_effect=AssertionError("ORM query ran before schema preflight"),
                    ):
                        with self.assertRaisesMessage(
                            CommandError, "database schema is incomplete"
                        ) as raised:
                            call_command("bootstrap_fresh_database")

                self.assertIn(model._meta.label, str(raised.exception))

    def test_missing_automatic_many_to_many_table_is_reported_before_any_model_query(self):
        through_model = get_user_model().groups.through
        existing_tables = set(connections["default"].introspection.table_names())
        self.assertIn(through_model._meta.db_table, existing_tables)

        table_names = sorted(existing_tables - {through_model._meta.db_table})
        with patch.object(
            connections["default"].introspection,
            "table_names",
            return_value=table_names,
        ):
            # The missing intermediary table must be detected before any ORM
            # query, just like a missing concrete application model table.
            with patch.object(
                Account.objects,
                "exists",
                side_effect=AssertionError("ORM query ran before schema preflight"),
            ):
                with self.assertRaisesMessage(
                    CommandError, "database schema is incomplete"
                ) as raised:
                    call_command("bootstrap_fresh_database")

        self.assertIn(through_model._meta.label, str(raised.exception))

