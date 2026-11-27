"""Isolated TransactionTestCase database reset for append-only audit history.

The audit triggers remain installed for the entire test body. Django's default
TransactionTestCase cleanup uses DELETE/flush, which must be rejected by the
append-only database guard. These tests therefore discard the disposable test
database itself and recreate it by running all migrations. No audit row is
mutated, no trigger is disabled, and the reconstructed database has the same
schema guards as a fresh installation.
"""

from django.conf import settings
from django.db import connections
from django.test import TransactionTestCase


def reset_ephemeral_test_database(*, aliases):
    """Discard and recreate disposable test DBs without issuing SQL DELETE."""
    original_names = getattr(settings, "ERP_TEST_ORIGINAL_DATABASE_NAMES", {})
    for alias in aliases:
        connection = connections[alias]
        if connection.in_atomic_block:
            raise AssertionError(
                "Audit test database cannot be discarded while a transaction is active"
            )
        if alias not in original_names:
            raise AssertionError(
                f"ERP_TEST_ORIGINAL_DATABASE_NAMES must define database alias {alias!r}"
            )

        creation = connection.creation
        creation.destroy_test_db(
            old_database_name=original_names[alias],
            verbosity=0,
            keepdb=False,
        )
        creation.create_test_db(
            verbosity=0,
            autoclobber=True,
            serialize=False,
            keepdb=False,
        )


class AuditTriggerAwareTransactionTestCase(TransactionTestCase):
    """Reset by discarding the ephemeral database, never by flushing rows."""

    def reset_test_database(self):
        aliases = self._databases_names(include_mirrors=False)
        reset_ephemeral_test_database(aliases=aliases)

    def _fixture_teardown(self):
        # Drop the disposable database itself; never use Django's normal
        # TransactionTestCase flush, whose DELETE statements must be rejected.
        self.reset_test_database()
