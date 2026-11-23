from __future__ import annotations

import re
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.db import DatabaseError, connection, transaction
from django.test import TestCase
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

    def test_reverse_trigger_migration_refuses_when_audit_history_exists(self):
        event = self._append(new_state={"migration_rollback": "must-be-blocked"})
        with self.assertRaisesMessage(RuntimeError, "cannot be removed while audit history exists"):
            call_command("migrate", "security", "0016", verbosity=0, interactive=False)

        self.assertTrue(AuditEvent.objects.filter(pk=event.pk).exists())
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                AuditEvent.objects.filter(pk=event.pk).update(reason="rollback-bypass")
        self.assertTrue(verify_audit_chain()["valid"])

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
