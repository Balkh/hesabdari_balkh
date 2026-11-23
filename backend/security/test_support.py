"""Test-only TransactionTestCase base for append-only audit database triggers."""

from django.db import connections
from django.test import TransactionTestCase

GENESIS_HASH = "0" * 64


class AuditTriggerAwareTransactionTestCase(TransactionTestCase):
    """Keep production triggers active during tests, but permit Django test flush.

    Django's TransactionTestCase flushes tables with DELETE, which correctly
    conflicts with the production append-only triggers. We drop only the two
    triggers immediately around the framework-owned test flush, then restore
    them in a finally block. Test bodies still execute against the real guards.
    """

    def _fixture_teardown(self):
        aliases = self._databases_names(include_mirrors=False)
        for alias in aliases:
            self._drop_triggers(alias)
        try:
            super()._fixture_teardown()
        finally:
            for alias in aliases:
                self._install_triggers(alias)

    @staticmethod
    def _drop_triggers(alias):
        connection = connections[alias]
        tables = set(connection.introspection.table_names())
        if "security_auditevent" not in tables:
            return
        with connection.cursor() as cursor:
            if connection.vendor == "sqlite":
                cursor.execute("DROP TRIGGER IF EXISTS security_auditevent_no_update")
                cursor.execute("DROP TRIGGER IF EXISTS security_auditevent_no_delete")
            elif connection.vendor == "postgresql":
                cursor.execute(
                    "DROP TRIGGER IF EXISTS security_auditevent_no_update_delete "
                    "ON security_auditevent"
                )

    @staticmethod
    def _install_triggers(alias):
        connection = connections[alias]
        tables = set(connection.introspection.table_names())
        if "security_auditevent" not in tables:
            return
        with connection.cursor() as cursor:
            if connection.vendor == "sqlite":
                cursor.execute(
                    "CREATE TRIGGER IF NOT EXISTS security_auditevent_no_update "
                    "BEFORE UPDATE ON security_auditevent "
                    "BEGIN SELECT RAISE(ABORT, 'security_auditevent is append-only'); END"
                )
                cursor.execute(
                    "CREATE TRIGGER IF NOT EXISTS security_auditevent_no_delete "
                    "BEFORE DELETE ON security_auditevent "
                    "BEGIN SELECT RAISE(ABORT, 'security_auditevent is append-only'); END"
                )
            elif connection.vendor == "postgresql":
                cursor.execute(
                    "CREATE OR REPLACE FUNCTION security_reject_audit_mutation() "
                    "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                    "RAISE EXCEPTION 'security_auditevent is append-only'; END; $$"
                )
                cursor.execute(
                    "CREATE TRIGGER security_auditevent_no_update_delete "
                    "BEFORE UPDATE OR DELETE ON security_auditevent "
                    "FOR EACH ROW EXECUTE FUNCTION security_reject_audit_mutation()"
                )
