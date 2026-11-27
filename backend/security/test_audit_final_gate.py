"""Final quality gate: disposable DB controls, domain rollback and measurements."""
from datetime import date
from decimal import Decimal
from time import perf_counter
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from accounting.coa import seed_chart_of_accounts
from accounting.models import JournalEntry, JournalLine
from core.models import IdempotencyRecord
from currencies.models import Currency
from documents.models import NumberSequence
from party_ledger.models import PartyLedgerAttribution
from parties.models import Party
from payments.models import Payment
from payments.services import create_payment
from security.audit_chain import assert_audit_trigger_schema, verify_audit_chain
from security.models import AuditAction, AuditChainHead, AuditEvent
from security.services import record_audit_event
from security.test_support import AuditTriggerAwareTransactionTestCase


class FinalAuditGuardTests(AuditTriggerAwareTransactionTestCase):
    def test_database_rejects_replacement_or_truncate_and_bulk_mutation(self):
        # Commit the fixture before testing destructive SQL. Django TestCase
        # leaves deferred FK trigger events pending in its outer transaction;
        # PostgreSQL would reject TRUNCATE before reaching our security guard.
        # The disposable DB is recreated by the trigger-aware fixture.
        with transaction.atomic():
            first = record_audit_event(action=AuditAction.CREATE, entity="FinalGate", entity_id="1")
            second = record_audit_event(action=AuditAction.CREATE, entity="FinalGate", entity_id="2")
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)
        before = verify_audit_chain()
        assert_audit_trigger_schema()
        with self.assertRaisesMessage(DatabaseError, "is append-only"):
            with transaction.atomic():
                AuditEvent.objects.all().update(reason="forbidden")
        with self.assertRaisesMessage(DatabaseError, "is append-only"):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM security_auditevent")
        if connection.vendor == "sqlite":
            # Test the schema guard even with recursive DELETE triggers off.
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA recursive_triggers")
                old = cursor.fetchone()[0]
                cursor.execute("PRAGMA recursive_triggers=OFF")
            try:
                with self.assertRaisesMessage(DatabaseError, "replacement is forbidden"):
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "INSERT OR REPLACE INTO security_auditevent "
                                "(id,user_id,action,entity,entity_id,reference,previous_state,new_state,"
                                "reason,event_uuid,prev_event_hash,event_hash,actor_snapshot,"
                                "authorization_context,source_fingerprint,created_at) "
                                "SELECT id,user_id,action,entity,entity_id,reference,previous_state,new_state,"
                                "'forbidden',event_uuid,prev_event_hash,event_hash,actor_snapshot,"
                                "authorization_context,source_fingerprint,created_at "
                                "FROM security_auditevent WHERE id=%s", [first.pk])
            finally:
                with connection.cursor() as cursor:
                    cursor.execute(f"PRAGMA recursive_triggers={int(old)}")
        else:
            with self.assertRaisesMessage(DatabaseError, "truncate is forbidden"):
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("TRUNCATE TABLE security_auditevent CASCADE")
        self.assertEqual(verify_audit_chain(), before)
        self.assertEqual(AuditEvent.objects.get(pk=first.pk).reason, first.reason)
        self.assertEqual(AuditEvent.objects.get(pk=second.pk).reason, second.reason)
        with transaction.atomic():
            third = record_audit_event(action=AuditAction.CREATE, entity="FinalGate", entity_id="3")
        self.assertEqual(third.prev_event_hash, before["head_hash"])
        self.assertEqual(verify_audit_chain()["event_count"], before["event_count"] + 1)
        print(f"FINAL GATE GUARDS [{connection.vendor}]: committed history preserved; exact guard rejection; append verified")


class FinalAuditLoadTests(TestCase):
    def test_large_chain_measurement_checks_all_1000_events(self):
        before = verify_audit_chain()
        started = perf_counter()
        with transaction.atomic():
            for i in range(1000):
                record_audit_event(action=AuditAction.CREATE, entity="FinalGateLoad",
                                   entity_id=str(i), new_state={"amount": "125.50", "label": "بلخ", "index": i})
        append_seconds = perf_counter() - started
        with CaptureQueriesContext(connection) as queries:
            started = perf_counter()
            verified = verify_audit_chain()
            verify_seconds = perf_counter() - started
        self.assertEqual(verified["event_count"], before["event_count"] + 1000)
        self.assertTrue(verified["valid"])
        reads = [q["sql"] for q in queries.captured_queries
                 if "SELECT" in q["sql"].upper() and "SECURITY_AUDITEVENT" in q["sql"].upper()]
        # One ledger query/cursor; no per-event ORM queries or sampled checks.
        self.assertEqual(len(reads), 1)
        print(f"FINAL GATE LOAD [{connection.vendor}]: events=1000 append_seconds={append_seconds:.4f} "
              f"verify_seconds={verify_seconds:.4f} ledger_selects={len(reads)}")


class FinalFinancialRollbackTests(TestCase):
    def setUp(self):
        seed_chart_of_accounts()
        self.user = get_user_model().objects.create_user(username="final-gate-financial")
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)
        self.customer = Party.objects.create(name="Final gate customer", is_customer=True)

    def _counts(self):
        return (Payment.objects.count(), JournalEntry.objects.count(), JournalLine.objects.count(),
                PartyLedgerAttribution.objects.count(), IdempotencyRecord.objects.count())

    def test_payment_final_audit_failure_reverts_journal_attribution_sequence_and_idempotency(self):
        before = verify_audit_chain()
        counts = self._counts()
        sequences = list(NumberSequence.objects.order_by("pk").values())
        kwargs = dict(party=self.customer, payment_date=date(2026, 9, 28),
                      currency=self.afn, amount="125.50", user=self.user,
                      document_number="PMT-FINAL-GATE", idempotency_key="final-payment")
        def fail_final(**kw):
            self.assertEqual(kw["entity"], "Payment")
            raise RuntimeError("final payment audit failure")
        with patch("payments.services.record_audit_event", side_effect=fail_final):
            with self.assertRaisesMessage(RuntimeError, "final payment audit failure"):
                create_payment(**kwargs)
        self.assertEqual(self._counts(), counts)
        self.assertEqual(list(NumberSequence.objects.order_by("pk").values()), sequences)
        self.assertEqual(verify_audit_chain(), before)
        payment = create_payment(**kwargs)
        self.assertEqual(create_payment(**kwargs).pk, payment.pk)
        self.assertEqual(payment.amount, Decimal("125.50"))
        self.assertEqual(payment.journal_entry.total_debit, payment.journal_entry.total_credit)
        self.assertEqual(payment.journal_entry.lines.get(account__code="1310").party_ledger_attribution.party_id,
                         self.customer.pk)
        self.assertTrue(verify_audit_chain()["valid"])

    def test_purchase_final_audit_failure_reverts_stock_payable_journal_and_idempotency(self):
        from accounting.models import Account
        from categories.services import create_category
        from inventory.models import StockMovement, WarehouseInventoryAccount
        from inventory.stock import stock_for
        from parties.services import create_party
        from products.services import create_product
        from purchases.models import PurchaseStatus
        from purchases.services import create_purchase, post_purchase
        from uom.services import create_uom
        from warehouses.services import create_warehouse
        category = create_category(name="Final gate category", user=self.user)
        uom = create_uom(name="Final gate unit", user=self.user)
        product = create_product(code="FINAL-GATE-1", name="Final gate product", name_fa="کالا",
                                 category=category, primary_uom=uom, user=self.user)
        supplier = create_party(name="Final gate supplier", is_supplier=True, user=self.user)
        warehouse = create_warehouse(name="Final gate warehouse", user=self.user)
        WarehouseInventoryAccount.objects.create(warehouse=warehouse, account=Account.objects.get(code="1410"))
        purchase = create_purchase(supplier=supplier, purchase_date=date(2026, 9, 28),
                                   currency=self.afn, warehouse=warehouse,
                                   lines=[{"product": product, "quantity": 10, "unit_price": "12.0000"}],
                                   document_number="PI-FINAL-GATE", user=self.user)
        initial = verify_audit_chain()
        counts = self._counts()
        stock_count = StockMovement.objects.count()
        sequences = list(NumberSequence.objects.order_by("pk").values())
        def fail_final(**kw):
            self.assertEqual(kw["entity"], "Purchase")
            self.assertEqual(kw["action"], AuditAction.POST)
            raise RuntimeError("final purchase audit failure")
        kwargs = dict(purchase=purchase, user=self.user, idempotency_key="final-purchase")
        with patch("purchases.services.record_audit_event", side_effect=fail_final):
            with self.assertRaisesMessage(RuntimeError, "final purchase audit failure"):
                post_purchase(**kwargs)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, PurchaseStatus.DRAFT)
        self.assertEqual(self._counts(), counts)
        self.assertEqual(StockMovement.objects.count(), stock_count)
        self.assertEqual(list(NumberSequence.objects.order_by("pk").values()), sequences)
        self.assertEqual(verify_audit_chain(), initial)
        post_purchase(**kwargs)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, PurchaseStatus.POSTED)
        journal = JournalEntry.objects.get(source_type="PURCHASE", source_id=purchase.document_number)
        self.assertEqual(journal.total_debit, Decimal("120.00"))
        self.assertEqual(journal.total_credit, Decimal("120.00"))
        self.assertEqual(journal.lines.get(account__code="2110").party_ledger_attribution.party_id, supplier.pk)
        self.assertEqual(StockMovement.objects.count(), stock_count + 1)
        self.assertTrue(verify_audit_chain()["valid"])


class FinalDenialFailureTests(TestCase):
    @override_settings(ERP_RBAC_ENFORCEMENT=True)
    def test_denial_storage_failure_does_not_authorize_business_mutation(self):
        from rest_framework.test import APIClient
        from fiscal_periods.models import FiscalPeriod
        from security.session_service import register_login_session
        user = get_user_model().objects.create_user(username="final-no-role", password="synthetic-test-password")
        client = APIClient()
        self.assertTrue(client.login(username=user.username, password="synthetic-test-password"))
        register_login_session(user, client.session.session_key)
        before = verify_audit_chain()
        count = FiscalPeriod.objects.count()
        with patch("security.services.record_audit_event", side_effect=RuntimeError("synthetic audit outage")):
            with self.assertLogs("security.operation_permissions", level="ERROR") as captured:
                response = client.post("/api/v1/fiscal-periods/", data={}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(FiscalPeriod.objects.count(), count)
        self.assertEqual(verify_audit_chain(), before)
        self.assertTrue(any("permission denial could not be written" in msg for msg in captured.output))
