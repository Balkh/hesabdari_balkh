"""Batch B: real legacy upgrades and append-only migration persistence.

These tests operate only on Django's disposable database. Historical rows
are created through the actual pre-chain migration state, never by mutating
an installed audit ledger. The isolated fixture discards the test database.
"""
from datetime import datetime, timezone as dt_timezone
from importlib import import_module
from io import StringIO
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from security.audit_chain import (
    AuditChainVerificationError,
    GENESIS_HASH,
    assert_audit_trigger_schema,
    verify_audit_chain,
)
from security.models import AuditAction, AuditChainHead, AuditEvent
from security.services import record_audit_event
from security.test_support import AuditTriggerAwareTransactionTestCase

PRE_CHAIN = ("security", "0015_login_attempt_account_time_index")
BACKFILL = ("security", "0016_audit_chain_backfill")
GUARDED = ("security", "0018_audit_extended_guards")
LEGACY_FIELDS = (
    "id", "user_id", "action", "entity", "entity_id", "reference",
    "previous_state", "new_state", "reason", "created_at",
)


class AuditBatchBMigrationTests(AuditTriggerAwareTransactionTestCase):
    def _migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate([target])
        return MigrationExecutor(connection).loader.project_state([target]).apps

    def _legacy_fixture(self):
        self.assertEqual(AuditEvent.objects.count(), 0)
        apps = self._migrate(PRE_CHAIN)
        event = apps.get_model("security", "AuditEvent")
        user = get_user_model().objects.create_user(username="batch-b-legacy-user")
        early = datetime(2026, 1, 1, 8, 30, 0, 123456, tzinfo=dt_timezone.utc)
        late = datetime(2026, 1, 2, 9, 45, 0, 654321, tzinfo=dt_timezone.utc)
        # Deliberately insert the late event first; same-timestamp ties are
        # resolved by primary key, not default model ordering.
        rows = [
            event.objects.create(
                user_id=user.pk, action="LOGIN", entity="Authentication",
                entity_id=str(user.pk), reference="legacy-login",
                new_state={"locale": "fa-AF"}, reason="historical login",
            ),
            event.objects.create(
                user_id=None, action="POST", entity="JournalEntry",
                entity_id="legacy-1", reference="JE-1404-00001",
                new_state={"debit": "125.50", "credit": "125.50", "label": "بلخ"},
            ),
            event.objects.create(
                user_id=user.pk, action="UPDATE", entity="JournalEntry",
                entity_id="legacy-1", reference="JE-1404-00001",
                previous_state={"description": "old"}, new_state={"description": "new"},
                reason="historical description",
            ),
        ]
        event.objects.filter(pk=rows[0].pk).update(created_at=late)
        event.objects.filter(pk__in=[rows[1].pk, rows[2].pk]).update(created_at=early)
        original = list(event.objects.order_by("created_at", "pk").values(*LEGACY_FIELDS))
        return event, original

    def _assert_guarded(self, event):
        assert_audit_trigger_schema()
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                AuditEvent.objects.filter(pk=event.pk).update(reason="forbidden")
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM security_auditevent WHERE id = %s", [event.pk])
        self.assertTrue(verify_audit_chain()["valid"])

    def test_fresh_genesis_and_empty_downgrade_reapply_preserve_guards(self):
        self.assertEqual(verify_audit_chain(), {
            "valid": True, "event_count": 0, "head_hash": GENESIS_HASH, "last_event_id": None,
        })
        assert_audit_trigger_schema()
        self._migrate(PRE_CHAIN)
        self.assertNotIn("security_auditchainhead", connection.introspection.table_names())
        self._migrate(BACKFILL)
        self.assertEqual(AuditChainHead.objects.get(pk=1).head_hash, GENESIS_HASH)
        # Chain integrity alone is insufficient before guard installation.
        with self.assertRaises(AuditChainVerificationError):
            assert_audit_trigger_schema()
        with self.assertRaises(CommandError):
            call_command("verify_audit_chain", stdout=StringIO())
        self._migrate(GUARDED)
        assert_audit_trigger_schema()
        with transaction.atomic():
            event = record_audit_event(action=AuditAction.CREATE, entity="BatchB", entity_id="fresh")
        self.assertEqual(event.prev_event_hash, GENESIS_HASH)
        self._assert_guarded(event)
        output = StringIO()
        call_command("verify_audit_chain", stdout=output)
        self.assertIn("AUDIT CHAIN VERIFIED: 1 events", output.getvalue())

    def test_populated_legacy_upgrade_preserves_fields_order_uuid_and_head(self):
        _, original = self._legacy_fixture()
        self._migrate(GUARDED)
        actual = list(AuditEvent.objects.order_by("created_at", "pk").values(*LEGACY_FIELDS))
        self.assertEqual(actual, original)
        previous = GENESIS_HASH
        for before in original:
            event = AuditEvent.objects.get(pk=before["id"])
            expected_uuid = uuid5(NAMESPACE_URL,
                f"hesabdari-audit-legacy-v1:{event.pk}:{before['created_at'].isoformat()}")
            self.assertEqual(event.event_uuid, expected_uuid)
            self.assertEqual(event.prev_event_hash, previous)
            self.assertEqual(event.actor_snapshot["actor_type"], "LEGACY")
            self.assertEqual(event.actor_snapshot["user_id"],
                str(before["user_id"]) if before["user_id"] is not None else None)
            self.assertEqual(event.actor_snapshot["roles"], [])
            self.assertEqual(event.actor_snapshot["historical_context"], "NOT_RECORDED_AT_ORIGIN")
            self.assertEqual(event.authorization_context["capture"], "LEGACY_UNAVAILABLE")
            self.assertEqual(event.source_fingerprint, "")
            previous = event.event_hash
        initial = verify_audit_chain()
        self.assertEqual(initial["event_count"], len(original))
        self.assertEqual(initial["head_hash"], previous)
        self.assertEqual(initial["last_event_id"], original[-1]["id"])
        # Reconnect to prove guards are persistent schema objects, not
        # connection-local settings or an in-memory assertion.
        connection.close()
        self._assert_guarded(AuditEvent.objects.get(pk=original[0]["id"]))
        self.assertEqual(verify_audit_chain(), initial)
        with transaction.atomic():
            new = record_audit_event(action=AuditAction.CREATE, entity="BatchB", entity_id="new")
        self.assertEqual(new.prev_event_hash, initial["head_hash"])
        self.assertEqual(verify_audit_chain()["event_count"], len(original) + 1)
        self.assertEqual(list(AuditEvent.objects.filter(pk__in=[row["id"] for row in original])
            .order_by("created_at", "pk").values(*LEGACY_FIELDS)), original)
        print(f"BATCH B LEGACY UPGRADE [{connection.vendor}]: {len(original)} preserved, 1 appended")

    def test_failed_backfill_rolls_back_schema_and_all_legacy_rows_then_retries(self):
        legacy, original = self._legacy_fixture()
        module = import_module("security.migrations.0016_audit_chain_backfill")
        normalize = module._normalize
        seen = []

        def reject_second(payload):
            if isinstance(payload, dict) and payload.get("schema") == module.SCHEMA:
                seen.append(payload["action"])
                if len(seen) == 2:
                    raise TypeError("private synthetic invalid payload")
            return normalize(payload)

        # Inject one failure inside the real atomic migration, after the first
        # row has already been written. No test flag changes the migration.
        with patch.object(module, "_normalize", side_effect=reject_second):
            with self.assertRaisesMessage(RuntimeError,
                f"cannot canonicalize legacy audit row id={original[1]['id']}") as failure:
                self._migrate(BACKFILL)
        self.assertNotIn("private synthetic invalid payload", str(failure.exception))
        self.assertEqual(len(seen), 2)
        self.assertNotIn(BACKFILL, MigrationRecorder(connection).applied_migrations())
        self.assertNotIn("security_auditchainhead", connection.introspection.table_names())
        with connection.cursor() as cursor:
            columns = {field.name for field in connection.introspection.get_table_description(
                cursor, "security_auditevent")}
        self.assertNotIn("event_uuid", columns)
        self.assertEqual(list(legacy.objects.order_by("created_at", "pk").values(*LEGACY_FIELDS)), original)
        self._migrate(GUARDED)
        self.assertEqual(verify_audit_chain()["event_count"], len(original))
        self.assertEqual(list(AuditEvent.objects.order_by("created_at", "pk").values(*LEGACY_FIELDS)), original)
        self._assert_guarded(AuditEvent.objects.get(pk=original[0]["id"]))

    def test_backfill_downgrade_refuses_history_before_removing_metadata(self):
        _, original = self._legacy_fixture()
        self._migrate(BACKFILL)
        initial = verify_audit_chain()
        with self.assertRaisesMessage(RuntimeError, "cannot be reversed while any audit event exists"):
            self._migrate(PRE_CHAIN)
        self.assertIn(BACKFILL, MigrationRecorder(connection).applied_migrations())
        self.assertEqual(verify_audit_chain(), initial)
        self.assertEqual(list(AuditEvent.objects.order_by("created_at", "pk").values(*LEGACY_FIELDS)), original)
        self._migrate(GUARDED)
        self._assert_guarded(AuditEvent.objects.get(pk=original[0]["id"]))
