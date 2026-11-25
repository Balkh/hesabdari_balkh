from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from categories.models import Category
from security.audit_chain import (
    AuditChainError,
    AuditChainVerificationError,
    calculate_event_hash,
    canonical_json_bytes,
    verify_audit_chain,
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
