from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import monotonic
from types import SimpleNamespace
from copy import copy
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, localcontext
from unittest.mock import patch
from uuid import UUID, uuid4

from django.core.management import call_command
from django.db import DatabaseError, OperationalError, connection, connections, transaction
from unittest import skipUnless

from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from categories.models import Category
from security.audit_chain import (
    AuditChainError,
    AuditChainVerificationError,
    calculate_event_hash,
    canonical_json_bytes,
    immutable_event_payload,
    verify_audit_chain,
    verify_audit_chain_records,
)
from security.models import AuditAction, AuditChainHead, AuditEvent
from security.services import record_audit_event
from security.test_support import AuditTriggerAwareTransactionTestCase


class AuditChainTests(TestCase):
    def _append(self, *, action=AuditAction.CREATE, entity_id="1", **kwargs):
        return record_audit_event(
            action=action,
            entity="AuditChainTest",
            entity_id=entity_id,
            **kwargs,
        )

    def test_canonical_json_is_recursive_sorted_compact_and_utf8(self):
        left = {"z": [2, {"b": "ب", "a": 1}], "a": None}
        right = {"a": None, "z": [2, {"a": 1, "b": "ب"}]}
        self.assertEqual(canonical_json_bytes(left), canonical_json_bytes(right))
        self.assertIn("ب".encode("utf-8"), canonical_json_bytes(left))

    def test_canonical_json_rejects_non_finite_or_unsupported_values(self):
        with self.assertRaises(TypeError):
            canonical_json_bytes({"not_finite": float("nan")})
        with self.assertRaises(TypeError):
            canonical_json_bytes({"binary": b"must-not-be-stored"})

    def test_hash_commits_to_previous_link_and_payload(self):
        payload = {"schema": "test", "value": 1}
        first = calculate_event_hash("0" * 64, payload)
        second = calculate_event_hash("1" * 64, payload)
        changed = calculate_event_hash("0" * 64, {"schema": "test", "value": 2})
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, changed)

    def test_appends_linear_chain_and_updates_singleton_head(self):
        first = self._append(entity_id="first", new_state={"value": 1})
        second = self._append(
            action=AuditAction.UPDATE,
            entity_id="second",
            previous_state={"value": 1},
            new_state={"value": 2},
        )

        self.assertEqual(first.prev_event_hash, "0" * 64)
        self.assertEqual(second.prev_event_hash, first.event_hash)
        self.assertEqual(AuditChainHead.objects.get(pk=1).head_hash, second.event_hash)
        self.assertEqual(AuditChainHead.objects.get(pk=1).last_event_id, second.pk)
        self.assertEqual(verify_audit_chain()["event_count"], 2)

    def test_sensitive_snapshot_fields_are_redacted_before_hashing(self):
        event = self._append(
            new_state={
                "password": "must-not-persist",
                "nested": {"totp_code": "123456", "safe_value": "visible"},
                "message": "reset password=Secret123; TOTP code=654321; Bearer abc.def.ghi",
                "setup_uri": "otpauth://totp/Hesabdari?secret=ABCDEF123&issuer=ERP",
            }
        )
        self.assertEqual(event.new_state["password"], "[REDACTED]")
        self.assertEqual(event.new_state["nested"]["totp_code"], "[REDACTED]")
        self.assertEqual(event.new_state["nested"]["safe_value"], "visible")
        self.assertNotIn(b"must-not-persist", canonical_json_bytes(event.new_state))
        self.assertNotIn(b"Secret123", canonical_json_bytes(event.new_state))
        self.assertNotIn(b"654321", canonical_json_bytes(event.new_state))
        self.assertNotIn(b"abc.def.ghi", canonical_json_bytes(event.new_state))
        self.assertNotIn(b"ABCDEF123", canonical_json_bytes(event.new_state))
        self.assertTrue(verify_audit_chain()["valid"])

    def test_jsonfield_values_are_canonical_before_persisting_and_verify_after_reload(self):
        moment = timezone.now().replace(microsecond=123456)
        identifier = uuid4()
        event = self._append(
            new_state={
                "amount": Decimal("10.5000"),
                "moment": moment,
                "identifier": identifier,
            }
        )
        event.refresh_from_db()
        expected_moment = (
            moment.astimezone(dt_timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        self.assertEqual(event.new_state["amount"], "10.5")
        self.assertEqual(event.new_state["moment"], expected_moment)
        self.assertEqual(event.new_state["identifier"], str(identifier).lower())
        self.assertTrue(verify_audit_chain()["valid"])

    def test_audit_rows_reject_orm_and_raw_update_delete(self):
        event = self._append(new_state={"original": True})

        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                AuditEvent.objects.filter(pk=event.pk).update(reason="tampered")
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                AuditEvent.objects.filter(pk=event.pk).delete()

        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE security_auditevent SET reason = %s WHERE id = %s",
                        ["raw tamper", event.pk],
                    )
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM security_auditevent WHERE id = %s",
                        [event.pk],
                    )
        self.assertTrue(verify_audit_chain()["valid"])

    def _drop_update_trigger(self):
        with connection.cursor() as cursor:
            if connection.vendor == "sqlite":
                cursor.execute("DROP TRIGGER security_auditevent_no_update")
            elif connection.vendor == "postgresql":
                cursor.execute(
                    "DROP TRIGGER security_auditevent_no_update_delete ON security_auditevent"
                )
            else:
                self.fail(f"unsupported test database: {connection.vendor}")

    def _restore_update_trigger(self):
        with connection.cursor() as cursor:
            if connection.vendor == "sqlite":
                cursor.execute(
                    "CREATE TRIGGER security_auditevent_no_update "
                    "BEFORE UPDATE ON security_auditevent "
                    "BEGIN SELECT RAISE(ABORT, 'security_auditevent is append-only'); END"
                )
            elif connection.vendor == "postgresql":
                cursor.execute(
                    "CREATE TRIGGER security_auditevent_no_update_delete "
                    "BEFORE UPDATE OR DELETE ON security_auditevent "
                    "FOR EACH ROW EXECUTE FUNCTION security_reject_audit_mutation()"
                )
            else:
                self.fail(f"unsupported test database: {connection.vendor}")

    def test_verifier_detects_payload_tampering_when_test_temporarily_drops_trigger(self):
        event = self._append(new_state={"expected": "original"})
        self._drop_update_trigger()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE security_auditevent SET reason = %s WHERE id = %s",
                    ["tampered outside the application", event.pk],
                )
        finally:
            self._restore_update_trigger()

        with self.assertRaises(AuditChainVerificationError):
            verify_audit_chain()

    def test_verifier_detects_deleted_middle_link_when_test_drops_delete_trigger(self):
        first = self._append(entity_id="first")
        middle = self._append(action=AuditAction.UPDATE, entity_id="middle")
        self._append(action=AuditAction.UPDATE, entity_id="last")
        with connection.cursor() as cursor:
            if connection.vendor == "sqlite":
                cursor.execute("DROP TRIGGER security_auditevent_no_delete")
            elif connection.vendor == "postgresql":
                cursor.execute(
                    "DROP TRIGGER security_auditevent_no_update_delete ON security_auditevent"
                )
            else:
                self.fail(f"unsupported test database: {connection.vendor}")
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM security_auditevent WHERE id = %s", [middle.pk]
                )
        finally:
            with connection.cursor() as cursor:
                if connection.vendor == "sqlite":
                    cursor.execute(
                        "CREATE TRIGGER security_auditevent_no_delete "
                        "BEFORE DELETE ON security_auditevent "
                        "BEGIN SELECT RAISE(ABORT, 'security_auditevent is append-only'); END"
                    )
                else:
                    cursor.execute(
                        "CREATE TRIGGER security_auditevent_no_update_delete "
                        "BEFORE UPDATE OR DELETE ON security_auditevent "
                        "FOR EACH ROW EXECUTE FUNCTION security_reject_audit_mutation()"
                    )

        self.assertNotEqual(first.event_hash, "0" * 64)
        with self.assertRaises(AuditChainVerificationError):
            verify_audit_chain()

    def test_previous_hash_has_database_unique_constraint(self):
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor, AuditEvent._meta.db_table
            )
        self.assertTrue(any(
            item.get("unique") and item.get("columns") == ["prev_event_hash"]
            for item in constraints.values()
        ))

    def test_action_inventory_respects_w0_2a_width_and_naming_contract(self):
        actions = [value for value, _label in AuditAction.choices]
        self.assertEqual(len(actions), len(set(actions)))
        self.assertIn("LOGIN", actions)
        self.assertIn("LOGOUT", actions)
        self.assertIn("ACCOUNT_EMERGENCY_RECOVERY", actions)
        for action in actions:
            self.assertLessEqual(len(action), 40)
            self.assertRegex(action, re.compile(r"^[A-Z]+(?:_[A-Z]+){0,2}$"))
            self.assertLessEqual(len(action.split("_")), 3)

    def test_event_insert_and_head_update_roll_back_with_business_mutation(self):
        original_count = AuditEvent.objects.count()
        with self.assertRaisesRegex(RuntimeError, "injected head update failure"):
            with transaction.atomic():
                Category.objects.create(name="must roll back with audit")
                with patch.object(
                    AuditChainHead,
                    "save",
                    side_effect=RuntimeError("injected head update failure"),
                ):
                    self._append(new_state={"transactional": True})
        self.assertFalse(Category.objects.filter(name="must roll back with audit").exists())
        self.assertEqual(AuditEvent.objects.count(), original_count)
        self.assertTrue(verify_audit_chain()["valid"])


class AuditChainReversalGuardTests(AuditTriggerAwareTransactionTestCase):
    """Migration 0017 must refuse downgrades that would remove append-only
    triggers while any audit history exists.

    This runs on ``AuditTriggerAwareTransactionTestCase`` (no wrapping
    ``TestCase`` atomic block) for two reasons:

    1. The expected migration failure raises inside the migration
       executor's own atomic block; running it under ``TestCase`` would
       poison the outer transaction (``needs_rollback``) and the follow-up
       assertions could not execute at all.
    2. The trigger-rejection assertion below needs the *real* installed
       trigger to reject the UPDATE after the refused rollback.
    """

    def _append(self, **kwargs):
        return record_audit_event(
            action=AuditAction.CREATE,
            entity="AuditChainTest",
            entity_id="reversal-guard",
            **kwargs,
        )

    def test_reverse_trigger_migration_refuses_when_audit_history_exists(self):
        # TransactionTestCase runs in autocommit mode; the append service
        # requires the caller's business transaction, so commit the history
        # event explicitly before attempting the refused downgrade.
        with transaction.atomic():
            event = self._append(new_state={"migration_rollback": "must-be-blocked"})
        with self.assertRaisesMessage(
            RuntimeError, "cannot be removed while audit history exists"
        ):
            call_command("migrate", "security", "0016", verbosity=0, interactive=False)

        # The refused downgrade must not have lost a single audit row.
        self.assertTrue(AuditEvent.objects.filter(pk=event.pk).exists())
        # Trigger removal never happened, so the append-only guard must
        # still reject mutation attempts on the ledger.
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                AuditEvent.objects.filter(pk=event.pk).update(reason="rollback-bypass")
        self.assertTrue(verify_audit_chain()["valid"])


class AuditChainSnapshotTests(AuditTriggerAwareTransactionTestCase):
    def _append(self, entity_id):
        with transaction.atomic():
            return record_audit_event(
                action=AuditAction.CREATE,
                entity="AuditSnapshotTest",
                entity_id=entity_id,
            )

    def test_verifier_acquires_snapshot_boundary_before_loading_events(self):
        self._append("first")
        self.assertFalse(connection.in_atomic_block)
        with CaptureQueriesContext(connection) as queries:
            verified = verify_audit_chain()
        statements = [query["sql"].upper() for query in queries.captured_queries]
        head_index = next(i for i, sql in enumerate(statements) if "SECURITY_AUDITCHAINHEAD" in sql)
        events_index = next(i for i, sql in enumerate(statements) if "SECURITY_AUDITEVENT" in sql)
        self.assertLess(head_index, events_index)
        if connection.vendor == "postgresql":
            self.assertIn("FOR UPDATE", statements[head_index])
        elif connection.vendor == "sqlite":
            self.assertTrue(any("BEGIN IMMEDIATE" in sql for sql in statements[:head_index]))
        self.assertEqual(verified["event_count"], 1)
        self.assertFalse(connection.in_atomic_block)

    def test_concurrent_append_cannot_commit_during_verification(self):
        from security.audit_chain import verify_audit_chain_records

        self._append("first")
        allow_writer = Event()
        writer_attempted = Event()
        writer_committed = Event()

        def observe_write(execute, sql, params, many, context):
            upper = sql.upper()
            if ("BEGIN IMMEDIATE" in upper or
                    ("UPDATE" in upper and "SECURITY_AUDITCHAINHEAD" in upper)):
                writer_attempted.set()
            return execute(sql, params, many, context)

        def writer():
            try:
                if not allow_writer.wait(10):
                    raise AssertionError("verifier did not reach the snapshot")
                with connection.execute_wrapper(observe_write):
                    self._append("second")
                writer_committed.set()
            finally:
                connection.close()

        def verify_while_writer_attempts(events, **kwargs):
            self.assertTrue(connection.in_atomic_block)
            allow_writer.set()
            self.assertTrue(writer_attempted.wait(10), "writer did not attempt the lock")
            self.assertFalse(writer_committed.wait(0.2), "writer committed inside verification")
            return verify_audit_chain_records(events, **kwargs)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(writer)
            try:
                with patch("security.audit_chain.verify_audit_chain_records",
                           side_effect=verify_while_writer_attempts):
                    verified = verify_audit_chain()
            finally:
                allow_writer.set()
            future.result(timeout=25)
        self.assertEqual(verified["event_count"], 1)
        self.assertTrue(writer_committed.is_set())
        self.assertEqual(verify_audit_chain()["event_count"], 2)

    def test_review_materializes_page_inside_same_verification_transaction(self):
        from security.audit_views import _build_audit_events_payload

        self._append("first")
        verified_inside_transaction = []

        def check_transaction():
            verified_inside_transaction.append(connection.in_atomic_block)
            return verify_audit_chain()

        with CaptureQueriesContext(connection) as queries:
            with patch("security.audit_views.verify_audit_chain", side_effect=check_transaction):
                payload, error = _build_audit_events_payload(SimpleNamespace(query_params={}))
        self.assertIsNone(error)
        self.assertEqual(verified_inside_transaction, [True])
        self.assertEqual(payload["integrity"]["event_count"], 1)
        self.assertEqual(len(payload["events"]), 1)
        self.assertEqual(payload["events"][0]["event_hash"], payload["integrity"]["head_hash"])
        statements = [q["sql"].upper() for q in queries.captured_queries]
        commit_index = next(i for i, sql in enumerate(statements) if sql == "COMMIT")
        event_reads = [i for i, sql in enumerate(statements) if
                       "SELECT" in sql and "SECURITY_AUDITEVENT" in sql]
        self.assertGreaterEqual(len(event_reads), 2)
        self.assertTrue(all(i < commit_index for i in event_reads))
        self.assertFalse(connection.in_atomic_block)


class AuditWriterTransactionBoundaryTests(AuditTriggerAwareTransactionTestCase):
    def _append(self, **kwargs):
        return record_audit_event(
            action=AuditAction.CREATE,
            entity="AuditBoundaryTest",
            entity_id="boundary",
            **kwargs,
        )

    def test_append_requires_caller_transaction(self):
        self.assertFalse(connection.in_atomic_block)
        with self.assertRaisesMessage(AuditChainError, "caller"):
            self._append()
        self.assertEqual(AuditEvent.objects.count(), 0)
        self.assertTrue(verify_audit_chain()["valid"])

    def test_caught_serialization_failure_marks_business_block_rollback_only(self):
        initial = verify_audit_chain()
        with transaction.atomic():
            Category.objects.create(name="rollback invalid audit payload")
            with self.assertRaises(TypeError):
                self._append(new_state={"unsupported": float("nan")})
            self.assertTrue(transaction.get_rollback())
        self.assertFalse(Category.objects.filter(name="rollback invalid audit payload").exists())
        self.assertEqual(verify_audit_chain(), initial)

    def test_caught_head_save_failure_rolls_back_insert_and_business_mutation(self):
        initial = verify_audit_chain()
        with transaction.atomic():
            Category.objects.create(name="rollback failed audit head")
            with patch.object(AuditChainHead, "save",
                              side_effect=RuntimeError("injected head save failure")):
                with self.assertRaisesMessage(RuntimeError, "injected head save failure"):
                    self._append(new_state={"transactional": True})
            self.assertTrue(transaction.get_rollback())
        self.assertFalse(Category.objects.filter(name="rollback failed audit head").exists())
        self.assertEqual(AuditEvent.objects.count(), initial["event_count"])
        self.assertEqual(verify_audit_chain(), initial)

    def test_caught_invalid_action_marks_business_block_rollback_only(self):
        initial = verify_audit_chain()
        with transaction.atomic():
            Category.objects.create(name="rollback invalid audit action")
            with self.assertRaisesMessage(ValueError, "Unknown audit action"):
                record_audit_event(action="NOT_AN_AUDIT_ACTION", entity="AuditBoundaryTest")
            self.assertTrue(transaction.get_rollback())
        self.assertFalse(Category.objects.filter(name="rollback invalid audit action").exists())
        self.assertEqual(verify_audit_chain(), initial)

    @skipUnless(connection.vendor == "sqlite", "SQLite-specific transaction mode")
    def test_live_deferred_transaction_rejected_even_when_settings_say_immediate(self):
        initial = verify_audit_chain()
        db = connections["default"]
        self.assertEqual(db.settings_dict["OPTIONS"]["transaction_mode"], "IMMEDIATE")
        with patch.object(db, "transaction_mode", "DEFERRED"):
            with CaptureQueriesContext(db) as queries:
                with transaction.atomic():
                    # Deliberately read before the attempted append on the
                    # unsupported transaction; do not allow a late upgrade.
                    self.assertEqual(AuditEvent.objects.count(), initial["event_count"])
                    with self.assertRaisesMessage(AuditChainError, "outermost IMMEDIATE"):
                        self._append()
                    self.assertTrue(transaction.get_rollback())
            sql = [q["sql"].upper() for q in queries.captured_queries]
            self.assertTrue(any("BEGIN DEFERRED" in statement for statement in sql))
            self.assertFalse(any("UPDATE" in statement and "SECURITY_AUDITCHAINHEAD" in statement
                                 for statement in sql))
        self.assertEqual(verify_audit_chain(), initial)

    @skipUnless(connection.vendor == "sqlite", "SQLite-specific transaction mode")
    def test_manual_autocommit_off_boundary_rejected(self):
        initial = verify_audit_chain()
        transaction.set_autocommit(False)
        try:
            with transaction.atomic():
                with self.assertRaisesMessage(AuditChainError, "outermost IMMEDIATE"):
                    self._append()
                self.assertTrue(transaction.get_rollback())
        finally:
            connection.rollback()
            transaction.set_autocommit(True)
        self.assertEqual(verify_audit_chain(), initial)


class AuditMultiWriterTests(AuditTriggerAwareTransactionTestCase):
    """Use real independent database connections and committed transactions."""

    def _write(self, marker):
        with transaction.atomic():
            category = Category.objects.create(name=marker)
            event = record_audit_event(
                action=AuditAction.CREATE,
                entity="Category",
                entity_id=str(category.pk),
                reference=marker,
                new_state={"category_id": category.pk, "name": marker},
            )
        return category.pk, event.pk

    def test_four_independent_writers_commit_one_linear_chain(self):
        workers, operations = 4, 8
        start = Barrier(workers, timeout=15)
        initial = verify_audit_chain()

        def write_batch(worker):
            db = connections["default"]
            try:
                db.ensure_connection()
                identity = id(db.connection)
                if db.vendor == "postgresql":
                    with db.cursor() as cursor:
                        cursor.execute("SHOW transaction_isolation")
                        self.assertEqual(cursor.fetchone()[0], "read committed")
                start.wait()
                pairs = [
                    self._write(f"audit-multiwriter-{worker}-{number}")
                    for number in range(operations)
                ]
                return identity, pairs
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(write_batch, worker) for worker in range(workers)]
            results = [future.result(timeout=90) for future in futures]

        self.assertEqual(len({identity for identity, _ in results}), workers)
        pairs = [pair for _, batch in results for pair in batch]
        self.assertEqual(len(pairs), workers * operations)
        category_ids = {category_id for category_id, _ in pairs}
        event_ids = {event_id for _, event_id in pairs}
        self.assertEqual(len(category_ids), workers * operations)
        self.assertEqual(len(event_ids), workers * operations)
        categories = dict(Category.objects.filter(pk__in=category_ids).values_list("pk", "name"))
        self.assertEqual(len(categories), workers * operations)
        events = list(AuditEvent.objects.filter(pk__in=event_ids))
        self.assertEqual(len(events), workers * operations)
        for event in events:
            self.assertEqual(event.entity, "Category")
            category_id = int(event.entity_id)
            self.assertIn(category_id, categories)
            self.assertEqual(event.new_state, {"category_id": category_id, "name": categories[category_id]})
            self.assertEqual(event.reference, categories[category_id])
        self.assertEqual({int(event.entity_id) for event in events}, category_ids)

        # Follow the actual hashes, not insertion timestamps or primary-key order.
        by_previous = {event.prev_event_hash: event for event in events}
        self.assertEqual(len(by_previous), workers * operations)
        current = initial["head_hash"]
        visited = set()
        last = None
        for _ in range(workers * operations):
            self.assertIn(current, by_previous)
            last = by_previous[current]
            self.assertNotIn(last.pk, visited)
            visited.add(last.pk)
            current = last.event_hash
        self.assertEqual(visited, event_ids)
        verified = verify_audit_chain()
        self.assertTrue(verified["valid"])
        self.assertEqual(verified["event_count"], initial["event_count"] + workers * operations)
        self.assertEqual(verified["head_hash"], current)
        self.assertEqual(verified["last_event_id"], last.pk)

    @skipUnless(connection.vendor == "sqlite", "SQLite-specific busy timeout")
    def test_sqlite_busy_timeout_rejects_entire_contended_operation(self):
        initial = verify_audit_chain()
        ready = Event()
        attempt = Event()

        def contended_writer():
            db = connections["default"]
            try:
                db.ensure_connection()
                with db.cursor() as cursor:
                    cursor.execute("PRAGMA busy_timeout")
                    configured = cursor.fetchone()[0]
                    # Shorten only this disposable test connection's timeout;
                    # the production configuration remains unchanged.
                    cursor.execute("PRAGMA busy_timeout = 150")
                ready.set()
                if not attempt.wait(10):
                    raise AssertionError("lock holder did not start the contention test")
                started = monotonic()
                with CaptureQueriesContext(db) as queries:
                    with self.assertRaises(OperationalError) as failure:
                        self._write("audit-timeout-must-not-commit")
                return configured, monotonic() - started, str(failure.exception), [
                    query["sql"].upper() for query in queries.captured_queries
                ]
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(contended_writer)
            try:
                self.assertTrue(ready.wait(10), "writer connection did not initialize")
                with transaction.atomic():
                    # BEGIN IMMEDIATE owns the write reservation before any
                    # business statement, so the contender must fail at BEGIN.
                    attempt.set()
                    configured, elapsed, message, statements = future.result(timeout=10)
                    self.assertEqual(configured, 20000)
                    self.assertGreaterEqual(elapsed, 0.10)
                    self.assertIn("locked", message.lower())
                    self.assertTrue(any("BEGIN IMMEDIATE" in sql for sql in statements))
                    self.assertFalse(any("INSERT" in sql or "UPDATE" in sql for sql in statements))
            finally:
                attempt.set()

        self.assertFalse(Category.objects.filter(name="audit-timeout-must-not-commit").exists())
        self.assertEqual(verify_audit_chain(), initial)
        # Prove a subsequent independent operation can commit after release.
        self._write("audit-after-timeout")
        self.assertEqual(verify_audit_chain()["event_count"], initial["event_count"] + 1)


class AuditBatchAIntegrityTests(TestCase):
    """Deterministic cross-engine vectors and failure/rollback controls."""

    def _append(self, entity_id="a", **kwargs):
        return record_audit_event(
            action=AuditAction.CREATE, entity="BatchA", entity_id=entity_id, **kwargs
        )

    def test_decimal_canonicalization_is_exact_at_different_context_precisions(self):
        amount = Decimal("123456789012345678901234567890.1234500")
        expected = b'{"amount":"123456789012345678901234567890.12345"}'
        for precision in (6, 28, 80):
            with self.subTest(precision=precision), localcontext() as context:
                context.prec = precision
                self.assertEqual(canonical_json_bytes({"amount": amount}), expected)
        self.assertEqual(canonical_json_bytes({"value": Decimal("1000")}), b'{"value":"1000"}')

    def test_non_string_keys_rejected_before_redaction_can_collapse_them(self):
        initial = verify_audit_chain()
        with self.assertRaisesMessage(TypeError, "keys must be strings"):
            with transaction.atomic():
                self._append(new_state={1: "first", "1": "second"})
        self.assertEqual(verify_audit_chain(), initial)

    def test_fixed_vector_persists_identical_v1_digest_on_both_engines(self):
        initial = verify_audit_chain()
        self.assertEqual(initial["event_count"], 0)
        moment = datetime(2026, 11, 23, 12, 34, 56, 123456, tzinfo=dt_timezone.utc)
        identifier = UUID("12345678-1234-5678-1234-567812345678")
        with (
            patch("security.audit_chain.uuid4", return_value=identifier),
            patch("security.audit_chain.timezone.now", return_value=moment),
            patch("security.audit_chain._request_context", return_value=None),
            localcontext() as context,
        ):
            context.prec = 6
            event = record_audit_event(
                action=AuditAction.CREATE, entity="GoldenAuditVector",
                entity_id="vector-1", reference="AFN",
                new_state={
                    "amount": Decimal("123456789012345678901234567890.1234500"),
                    "moment": moment,
                    "identifier": UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                    "label": "بلخ", "integral": 1e20, "zero": -0.0, "fraction": 1.25,
                },
                authorization_context={"operation_id": "golden.vector"},
            )
        event.refresh_from_db()
        self.assertEqual(event.new_state["amount"], "123456789012345678901234567890.12345")
        self.assertIs(type(event.new_state["integral"]), int)
        self.assertEqual(event.new_state["integral"], 100000000000000000000)
        self.assertIs(type(event.new_state["zero"]), int)
        self.assertEqual(event.new_state["zero"], 0)
        self.assertEqual(event.new_state["fraction"], 1.25)
        # Independent fixed fixture: SHA256(domain + 32 zero bytes + canonical
        # UTF-8 JSON). Do not derive expected digest using the code under test.
        expected = "f5ee217e5676b266a7f4d2af275a320d99938e2b3e7ebb86e9600130d0811d90"
        self.assertEqual(event.event_hash, expected)
        self.assertEqual(calculate_event_hash(event.prev_event_hash, immutable_event_payload(event)), expected)
        self.assertEqual(verify_audit_chain()["head_hash"], expected)
        print(f"BATCH A GOLDEN DIGEST [{connection.vendor}]: {expected}")

    def test_legacy_v1_float_bytes_are_not_rewritten_by_new_write_normalization(self):
        self.assertEqual(canonical_json_bytes({"n": 1e20, "z": -0.0}), b'{"n":1e+20,"z":-0.0}')

    def test_verifier_rejects_tampered_hash_link_fork_duplicate_uuid_and_head(self):
        first = self._append("first")
        second = self._append("second")
        third = self._append("third")
        original = verify_audit_chain()
        # Use detached in-memory copies: no trigger removal or persistent
        # mutation is needed to exercise these negative verifier paths.
        for name in ("hash", "link", "fork", "uuid", "head", "head_locator", "tail"):
            with self.subTest(name=name):
                rows = [copy(first), copy(second), copy(third)]
                head_hash = original["head_hash"]
                last_id = original["last_event_id"]
                if name == "hash":
                    rows[1].event_hash = "f" * 64
                elif name == "link":
                    rows[1].prev_event_hash = "e" * 64
                elif name == "fork":
                    rows[2].prev_event_hash = rows[1].prev_event_hash
                elif name == "uuid":
                    rows[1].event_uuid = rows[0].event_uuid
                    rows[1].event_hash = calculate_event_hash(rows[1].prev_event_hash, immutable_event_payload(rows[1]))
                elif name == "head":
                    head_hash = "0" * 64
                elif name == "head_locator":
                    last_id = first.pk
                elif name == "tail":
                    rows.pop()
                with self.assertRaises(AuditChainVerificationError):
                    verify_audit_chain_records(rows, head_hash=head_hash, last_event_id=last_id)
        self.assertEqual(verify_audit_chain(), original)

    def test_nested_business_failure_propagates_and_rolls_back_earlier_work(self):
        initial = verify_audit_chain()
        with self.assertRaisesMessage(RuntimeError, "nested audit failure"):
            with transaction.atomic():
                Category.objects.create(name="batch-a-outer")
                self._append("outer")
                with transaction.atomic():
                    Category.objects.create(name="batch-a-inner")
                    with patch.object(AuditChainHead, "save", side_effect=RuntimeError("nested audit failure")):
                        self._append("inner")
        self.assertFalse(Category.objects.filter(name__startswith="batch-a-").exists())
        self.assertEqual(verify_audit_chain(), initial)


class AuditBatchAFinancialRollbackTests(TestCase):
    def setUp(self):
        from accounting.models import Account, AccountType
        from currencies.models import Currency
        self.cash = Account.objects.create(code="1100", name="Cash", account_type=AccountType.ASSET)
        self.revenue = Account.objects.create(code="4100", name="Revenue", account_type=AccountType.REVENUE)
        self.afn = Currency.objects.create(code="AFN", name="Afghani", is_base=True)

    def _post(self, key):
        from accounting.services import post_journal
        return post_journal(
            number="JE-1405-90001", posting_date="2026-09-06",
            description="Batch A audited balanced journal", currency=self.afn,
            lines=[{"account": self.cash, "debit": "125.50"},
                   {"account": self.revenue, "credit": "125.50"}],
            idempotency_key=key,
        )

    def test_post_failure_rolls_back_lines_idempotency_and_chain_then_retry_is_exact(self):
        from accounting.models import JournalEntry, JournalLine
        from accounting.services import verify_entry_totals
        from core.idempotency import IdempotencyRecord

        initial = verify_audit_chain()
        key = "batch-a-journal-post"
        before_entries, before_lines = JournalEntry.objects.count(), JournalLine.objects.count()
        with patch.object(AuditChainHead, "save", side_effect=RuntimeError("financial audit failure")):
            with self.assertRaisesMessage(RuntimeError, "financial audit failure"):
                self._post(key)
        self.assertEqual(JournalEntry.objects.count(), before_entries)
        self.assertEqual(JournalLine.objects.count(), before_lines)
        self.assertFalse(IdempotencyRecord.objects.filter(key=key).exists())
        self.assertEqual(verify_audit_chain(), initial)
        posted = self._post(key)
        self.assertEqual(self._post(key).pk, posted.pk)
        self.assertEqual(JournalEntry.objects.count(), before_entries + 1)
        self.assertEqual(JournalLine.objects.count(), before_lines + 2)
        self.assertEqual(verify_entry_totals(posted)["total_debit"], Decimal("125.50"))
        self.assertEqual(posted.total_debit, posted.total_credit)
        self.assertEqual(verify_audit_chain()["event_count"], initial["event_count"] + 1)

    def test_reversal_failure_preserves_original_lines_status_sequence_and_chain(self):
        from accounting.models import JournalEntry, JournalLine, JournalStatus
        from accounting.services import reverse_journal, verify_entry_totals
        from documents.models import NumberSequence

        entry = self._post("batch-a-reverse-post")
        initial = verify_audit_chain()
        original_lines = list(entry.lines.order_by("pk").values("pk", "account_id", "debit", "credit"))
        before_entries, before_lines = JournalEntry.objects.count(), JournalLine.objects.count()
        sequences = list(NumberSequence.objects.order_by("pk").values())
        with patch.object(AuditChainHead, "save", side_effect=RuntimeError("reversal audit failure")):
            with self.assertRaisesMessage(RuntimeError, "reversal audit failure"):
                reverse_journal(entry, "Batch A correction", None)
        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalStatus.POSTED)
        self.assertEqual(list(entry.lines.order_by("pk").values("pk", "account_id", "debit", "credit")), original_lines)
        self.assertEqual(JournalEntry.objects.count(), before_entries)
        self.assertEqual(JournalLine.objects.count(), before_lines)
        self.assertEqual(list(NumberSequence.objects.order_by("pk").values()), sequences)
        self.assertEqual(verify_audit_chain(), initial)
        reversal = reverse_journal(entry, "Batch A correction", None)
        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalStatus.REVERSED)
        self.assertEqual(reversal.reverses_id, entry.pk)
        self.assertEqual(verify_entry_totals(reversal)["total_debit"], Decimal("125.50"))
        self.assertEqual(reversal.total_debit, reversal.total_credit)
        self.assertEqual(list(reversal.lines.order_by("pk").values_list("account_id", "debit", "credit")),
                         [(line["account_id"], line["credit"], line["debit"]) for line in original_lines])
        self.assertEqual(verify_audit_chain()["event_count"], initial["event_count"] + 1)
