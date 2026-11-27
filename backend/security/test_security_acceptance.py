"""Engineering acceptance benchmark using committed disposable history."""
from time import perf_counter

from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from security.audit_chain import assert_audit_trigger_schema, verify_audit_chain
from security.models import AuditAction
from security.services import record_audit_event
from security.test_support import AuditTriggerAwareTransactionTestCase


class CommittedAuditCapacityTests(AuditTriggerAwareTransactionTestCase):
    def test_committed_10000_event_chain_full_verification(self):
        initial = verify_audit_chain()
        start = perf_counter()
        # Commit every 100 events; measure a larger ledger without asserting
        # an arbitrary performance SLA on shared CI hardware.
        for batch in range(100):
            with transaction.atomic():
                for offset in range(100):
                    index = batch * 100 + offset
                    record_audit_event(
                        action=AuditAction.CREATE, entity="AcceptanceLoad",
                        entity_id=str(index), new_state={"amount": "125.50",
                        "description": "سند آزمایشی حسابداری بلخ", "index": index})
        append_seconds = perf_counter() - start
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)
        connection.close()
        assert_audit_trigger_schema()
        with CaptureQueriesContext(connection) as queries:
            start = perf_counter()
            verified = verify_audit_chain()
            verify_seconds = perf_counter() - start
        self.assertTrue(verified["valid"])
        self.assertEqual(verified["event_count"], initial["event_count"] + 10000)
        reads = [q["sql"] for q in queries.captured_queries
                 if "SELECT" in q["sql"].upper() and "SECURITY_AUDITEVENT" in q["sql"].upper()]
        self.assertEqual(len(reads), 1)
        with transaction.atomic():
            last = record_audit_event(action=AuditAction.CREATE, entity="AcceptanceLoad", entity_id="after")
        self.assertEqual(last.prev_event_hash, verified["head_hash"])
        after = verify_audit_chain()
        self.assertEqual(after["event_count"], verified["event_count"] + 1)
        self.assertEqual(after["last_event_id"], last.pk)
        print(f"ACCEPTANCE LOAD [{connection.vendor}]: committed=10000 transactions=100 "
              f"append_seconds={append_seconds:.4f} verify_seconds={verify_seconds:.4f} "
              f"ledger_selects={len(reads)} reconnect_and_append=verified")
