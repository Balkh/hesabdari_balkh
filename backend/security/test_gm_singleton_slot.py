"""W0-2B — singleton GM slot: authorization, cardinality, migration, checks.

Pins the owner decision implemented in this batch: **at most ONE user may
hold the active General Manager role in the entire ERP at any time.** Zero
active GM holders are permitted (initial setup / controlled recovery
interval); two are never permitted; a Django superuser or staff account
never receives GM merely by being one; and an ordinary unlinked
``UserRoleAssignment(role=GM)`` grants neither protected GM capability nor
GM permission keys.

Covers:
- model constraints (singleton identity, OneToOne reuse backstop, PROTECT);
- resolver authorization through the slot (linked/unlinked, temporal
  states, corrupt states, non-GM roles unchanged, fail-closed);
- atomic claim semantics (first/second/idempotent/conflict rollback and a
  real threaded concurrency test — on PostgreSQL this runs with two
  independent connections; SQLite is NOT a substitute for that evidence);
- migration 0005 behavior (zero/one/multiple candidates, reverse
  preserving history, idempotent re-application);
- the ``security.E004`` system check (including the valid EMPTY slot on a
  fresh database) and the read-only ``gm_slot_preflight`` command.
"""
import io
import threading
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from security import authorization
from security.authorization import resolve
from security.checks import check_gm_singleton_slot_for_alias
from security.gm_slot import (
    GM_SLOT_CODE,
    GMSlotClaimError,
    claim_gm_slot,
    load_singleton_slot,
)
from security.models import GMRoleSlot, Role, UserRoleAssignment
from security.test_authorization_resolver import (
    ResolverTestBase,
    grant_role,
    link,
)

User = get_user_model()

GM_KEY = "audit.report.view"  # NONE-policy key inside the GM capability set


def _gm_role():
    return Role.objects.get(code="GM")


def _unlinked_gm_assignment(user):
    """Create an ordinary (never slot-linked) GM assignment."""
    return UserRoleAssignment.objects.create(user=user, role=_gm_role())


def _reseed_rbac_catalog():
    """Restore the canonical 0003 RBAC reference rows and the slot row.

    ``TransactionTestCase`` flushes every table between tests (the same
    pattern the existing goods_in_transit / purchases concurrency tests
    handle by re-seeding in ``setUp``); the RBAC seed is a RunPython data
    migration and is not re-run by flush's post_migrate signal. The
    singleton slot ROW is likewise migration-created DATA — flush empties
    it while ``django_migrations`` still records 0005 applied — so it is
    recreated here with no holder (the valid empty state).
    """
    from security.models import Permission, RolePermission
    from security.seed import seed_rbac_catalog

    seed_rbac_catalog(
        role_model=Role,
        permission_model=Permission,
        role_permission_model=RolePermission,
    )
    GMRoleSlot.objects.get_or_create(code=GM_SLOT_CODE)


# ---------------------------------------------------------------------------
# Model constraints
# ---------------------------------------------------------------------------
class SingletonSlotModelTests(TestCase):
    def test_singleton_row_exists_after_migrations(self):
        self.assertEqual(GMRoleSlot.objects.count(), 1)
        slot = GMRoleSlot.objects.get()
        self.assertEqual(slot.code, GM_SLOT_CODE)
        self.assertIsNone(slot.assignment)

    def test_second_slot_row_is_rejected(self):
        with self.assertRaises(Exception) as ctx:
            with transaction.atomic():
                GMRoleSlot.objects.create(code=GM_SLOT_CODE)
        self.assertIsInstance(
            ctx.exception, (Exception,)
        )  # unique violation — engine-specific subclass
        self.assertEqual(GMRoleSlot.objects.count(), 1)

    def test_slot_identity_code_is_constrained_to_gm(self):
        with self.assertRaises(Exception):
            with transaction.atomic():
                GMRoleSlot.objects.create(code="NOT_GM")
        self.assertEqual(GMRoleSlot.objects.count(), 1)
        self.assertEqual(GMRoleSlot.objects.get().code, GM_SLOT_CODE)

    def test_linked_assignment_is_protected_against_deletion(self):
        user = User.objects.create_user(username="protected-holder")
        assignment = _unlinked_gm_assignment(user)
        claim_gm_slot(assignment)
        from django.db.models import ProtectedError

        with self.assertRaises(ProtectedError):
            assignment.delete()
        self.assertEqual(GMRoleSlot.objects.get().assignment_id, assignment.pk)


# ---------------------------------------------------------------------------
# Authorization through the singleton slot
# ---------------------------------------------------------------------------
class SingletonGmAuthorizationTests(ResolverTestBase):
    def test_linked_active_gm_receives_protected_capability(self):
        user = User.objects.create_user(username="slot-gm")
        grant_role(user, "GM")  # helper claims the slot
        decision = self.resolve(user, GM_KEY)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "GM_PROTECTED")
        self.assertEqual(decision.source, "GM")

    def test_superuser_without_slot_has_no_gm_authority(self):
        grant_role(User.objects.create_user(username="real-gm"), "GM")
        second = User.objects.create_user(
            username="super-not-gm", is_superuser=True
        )
        decision = self.resolve(second, GM_KEY)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "NO_GRANT")
        self.assertNotIn("5:GM_PROTECTED", decision.trace)

    def test_staff_without_slot_has_no_gm_authority(self):
        grant_role(User.objects.create_user(username="real-gm-2"), "GM")
        second = User.objects.create_user(username="staff-not-gm", is_staff=True)
        decision = self.resolve(second, GM_KEY)
        self.assertEqual(decision.reason, "NO_GRANT")

    def test_unlinked_gm_assignment_grants_nothing(self):
        grant_role(User.objects.create_user(username="holder-a"), "GM")
        stranger = User.objects.create_user(username="unlinked-gm")
        _unlinked_gm_assignment(stranger)
        decision = self.resolve(stranger, GM_KEY)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "NO_GRANT")
        self.assertNotIn("5:GM_PROTECTED", decision.trace)

    def test_inactive_gm_user_is_denied(self):
        user = User.objects.create_user(username="inactive-gm")
        grant_role(user, "GM")
        user.is_active = False
        user.save(update_fields=["is_active"])
        decision = self.resolve(user, GM_KEY)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "INACTIVE_ACCOUNT")

    def test_revoked_linked_assignment_grants_nothing(self):
        user = User.objects.create_user(username="revoked-gm")
        assignment = grant_role(user, "GM")
        UserRoleAssignment.objects.filter(pk=assignment.pk).update(
            revoked_at=timezone.now(), revocation_kind="MANUAL"
        )
        decision = self.resolve(user, GM_KEY)
        self.assertEqual(decision.reason, "NO_GRANT")

    def test_expired_linked_assignment_grants_nothing(self):
        user = User.objects.create_user(username="expired-gm")
        assignment = grant_role(user, "GM")
        UserRoleAssignment.objects.filter(pk=assignment.pk).update(
            start_at=self.now - timezone.timedelta(days=2),
            end_at=self.now - timezone.timedelta(days=1),
        )
        decision = self.resolve(user, GM_KEY)
        self.assertEqual(decision.reason, "NO_GRANT")

    def test_future_linked_assignment_grants_nothing(self):
        user = User.objects.create_user(username="future-gm")
        assignment = grant_role(user, "GM")
        UserRoleAssignment.objects.filter(pk=assignment.pk).update(
            start_at=self.now + timezone.timedelta(days=1)
        )
        decision = self.resolve(user, GM_KEY)
        self.assertEqual(decision.reason, "NO_GRANT")

    def test_wrong_role_linked_through_invalid_fixture_fails_closed(self):
        """A deliberately corrupt slot link (role != GM) grants nothing."""
        user = User.objects.create_user(username="corrupt-holder")
        corrupt_role = Role.objects.create(
            code="CORRUPT_SLOT_ROLE", name="Corrupt Fixture Role"
        )
        corrupt_assignment = UserRoleAssignment.objects.create(
            user=user, role=corrupt_role
        )
        GMRoleSlot.objects.update(assignment=corrupt_assignment)
        with self.assertLogs("security.authorization", level="ERROR"):
            decision = self.resolve(user, GM_KEY)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "NO_GRANT")

    def test_missing_slot_row_denies_gm_and_logs(self):
        user = User.objects.create_user(username="no-slot-gm")
        grant_role(user, "GM")
        GMRoleSlot.objects.all().delete()
        with self.assertLogs("security.authorization", level="ERROR"):
            decision = self.resolve(user, GM_KEY)
        self.assertEqual(decision.reason, "NO_GRANT")

    def test_slot_held_by_another_user_denies_the_second_user(self):
        grant_role(User.objects.create_user(username="first-holder"), "GM")
        second = User.objects.create_user(username="second-candidate")
        _unlinked_gm_assignment(second)
        decision = self.resolve(second, GM_KEY)
        self.assertEqual(decision.reason, "NO_GRANT")
        # The real holder is untouched.
        holder_decision = self.resolve(
            User.objects.get(username="first-holder"), GM_KEY
        )
        self.assertTrue(holder_decision.allowed)
        self.assertEqual(holder_decision.reason, "GM_PROTECTED")

    def test_accountant_authorization_unchanged(self):
        self.declare_collection("fiscal.period.view")
        user = User.objects.create_user(username="acc-singleton")
        grant_role(user, "ACCOUNTANT")
        link("ACCOUNTANT", "fiscal.period.view")
        decision = self.resolve(user, "fiscal.period.view")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "ROLE_GRANT")

    def test_warehouse_keeper_authorization_unchanged(self):
        from warehouses.models import Warehouse

        from security.models import UserWarehouseScope

        user = User.objects.create_user(username="wk-singleton")
        grant_role(user, "WAREHOUSE_KEEPER")
        link("WAREHOUSE_KEEPER", "inventory.movement.view")
        assigned = Warehouse.objects.create(name="Singleton WH")
        UserWarehouseScope.objects.create(user=user, warehouse=assigned)
        decision = self.resolve(user, "inventory.movement.view", resource=assigned)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "ROLE_GRANT")


# ---------------------------------------------------------------------------
# Atomic claim semantics (deterministic)
# ---------------------------------------------------------------------------
class SlotClaimCardinalityTests(TestCase):
    def _candidate(self, username):
        user = User.objects.create_user(username=username)
        return _unlinked_gm_assignment(user)

    def test_first_claim_succeeds(self):
        assignment = self._candidate("first-claim")
        slot = claim_gm_slot(assignment)
        self.assertEqual(slot.assignment_id, assignment.pk)
        self.assertEqual(GMRoleSlot.objects.get().assignment_id, assignment.pk)

    def test_second_different_assignment_claim_fails(self):
        first = self._candidate("claim-winner")
        second = self._candidate("claim-loser")
        claim_gm_slot(first)
        with self.assertRaises(GMSlotClaimError):
            claim_gm_slot(second)
        self.assertEqual(GMRoleSlot.objects.get().assignment_id, first.pk)
        # The losing assignment row itself is untouched by the claim helper.
        self.assertTrue(UserRoleAssignment.objects.filter(pk=second.pk).exists())

    def test_repeated_claim_by_same_assignment_is_idempotent(self):
        assignment = self._candidate("idempotent-claim")
        first = claim_gm_slot(assignment)
        second = claim_gm_slot(assignment)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(GMRoleSlot.objects.get().assignment_id, assignment.pk)

    def test_claim_rejects_non_gm_role_assignment(self):
        user = User.objects.create_user(username="acc-claim")
        role = Role.objects.get(code="ACCOUNTANT")
        assignment = UserRoleAssignment.objects.create(user=user, role=role)
        with self.assertRaises(GMSlotClaimError):
            claim_gm_slot(assignment)
        self.assertIsNone(GMRoleSlot.objects.get().assignment_id)

    def test_claim_rejects_inactive_user_account(self):
        user = User.objects.create_user(
            username="inactive-claim", is_active=False
        )
        assignment = _unlinked_gm_assignment(user)

        with self.assertRaisesMessage(
            GMSlotClaimError, "active User account"
        ):
            claim_gm_slot(assignment)

        self.assertIsNone(GMRoleSlot.objects.get().assignment_id)
        self.assertTrue(UserRoleAssignment.objects.filter(pk=assignment.pk).exists())

    def test_claim_rejects_revoked_assignment(self):
        assignment = self._candidate("revoked-claim")
        UserRoleAssignment.objects.filter(pk=assignment.pk).update(
            revoked_at=timezone.now(), revocation_kind="MANUAL"
        )
        with self.assertRaises(GMSlotClaimError):
            claim_gm_slot(assignment)
        self.assertIsNone(GMRoleSlot.objects.get().assignment_id)

    def test_conflicting_claim_rolls_back_the_newly_created_assignment(self):
        first = self._candidate("rollback-winner")
        claim_gm_slot(first)
        other = User.objects.create_user(username="rollback-loser")
        with self.assertRaises(GMSlotClaimError):
            with transaction.atomic():
                stray = UserRoleAssignment.objects.create(
                    user=other, role=_gm_role()
                )
                claim_gm_slot(stray)
        self.assertFalse(
            UserRoleAssignment.objects.filter(pk=stray.pk).exists()
        )
        self.assertEqual(GMRoleSlot.objects.get().assignment_id, first.pk)

    def test_caught_claim_error_only_rolls_back_helper_savepoint(self):
        first = self._candidate("savepoint-winner")
        claim_gm_slot(first)
        other = User.objects.create_user(username="savepoint-loser")

        with transaction.atomic():
            stray = UserRoleAssignment.objects.create(user=other, role=_gm_role())
            try:
                claim_gm_slot(stray)
            except GMSlotClaimError:
                # Catching inside the outer atomic block deliberately allows
                # work created before the helper's nested savepoint to commit.
                pass

        self.assertTrue(UserRoleAssignment.objects.filter(pk=stray.pk).exists())
        self.assertEqual(GMRoleSlot.objects.get().assignment_id, first.pk)


# ---------------------------------------------------------------------------
# Concurrency — two real competing claims (separate connections/threads)
# ---------------------------------------------------------------------------
class ConcurrentSlotClaimTests(TransactionTestCase):
    def setUp(self):
        _reseed_rbac_catalog()

    def _candidate(self, username):
        user = User.objects.create_user(username=username)
        return _unlinked_gm_assignment(user)

    def test_two_concurrent_claims_never_produce_two_gm_holders(self):
        first = self._candidate("concurrent-a")
        second = self._candidate("concurrent-b")

        barrier = threading.Barrier(2)
        results = {}

        def attempt(name, assignment_pk):
            outcome = "unknown"
            try:
                barrier.wait(timeout=15)
                claim_gm_slot(UserRoleAssignment.objects.get(pk=assignment_pk))
                outcome = "claimed"
            except GMSlotClaimError:
                outcome = "conflict"
            except Exception as exc:
                # Engine-level lock contention (e.g. SQLite busy/table lock)
                # is a DENIAL, never a second holder. PostgreSQL evidence for
                # the clean CAS conflict comes from the postgresql CI job.
                outcome = f"denied:{type(exc).__name__}"
            finally:
                results[name] = outcome
                connection.close()

        threads = [
            threading.Thread(target=attempt, args=("a", first.pk)),
            threading.Thread(target=attempt, args=("b", second.pk)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertTrue(all(not t.is_alive() for t in threads), results)

        outcomes = list(results.values())
        self.assertEqual(
            outcomes.count("claimed"), 1, f"exactly one winner required: {results}"
        )
        denials = outcomes.count("conflict") + sum(
            1 for o in outcomes if o.startswith("denied:")
        )
        self.assertEqual(denials, 1, f"exactly one denial required: {results}")

        holders = GMRoleSlot.objects.filter(assignment__isnull=False)
        self.assertEqual(holders.count(), 1, "never two GM holders")
        self.assertIn(holders.get().assignment_id, {first.pk, second.pk})
        # The database still holds both candidate rows (nothing deleted).
        self.assertEqual(
            UserRoleAssignment.objects.filter(
                role__code=GM_SLOT_CODE, revoked_at__isnull=True
            ).count(),
            2,
        )


@skipUnless(
    connection.vendor == "postgresql",
    "Row-lock CAS conflict evidence is verified on PostgreSQL 17.11 "
    "(repo concurrency-test convention); SQLite cannot provide it",
)
class PostgreSQLConcurrentSlotClaimTests(TransactionTestCase):
    """Strict PostgreSQL evidence: two independent connections race the
    compare-and-set claim. On PostgreSQL the loser MUST receive the clean
    domain conflict (the winner's row lock blocks the loser's CAS UPDATE,
    which then re-evaluates ``assignment IS NULL`` against committed state)
    — engine-level lock errors are not acceptable outcomes here."""

    def setUp(self):
        _reseed_rbac_catalog()

    def _candidate(self, username):
        user = User.objects.create_user(username=username)
        return _unlinked_gm_assignment(user)

    def test_competing_claims_produce_one_holder_and_one_domain_conflict(self):
        first = self._candidate("pg-concurrent-a")
        second = self._candidate("pg-concurrent-b")

        barrier = threading.Barrier(2)
        results = {}

        def attempt(name, assignment_pk):
            outcome = "unknown"
            try:
                barrier.wait(timeout=15)
                claim_gm_slot(
                    UserRoleAssignment.objects.get(pk=assignment_pk)
                )
                outcome = "claimed"
            except GMSlotClaimError:
                outcome = "conflict"
            finally:
                results[name] = outcome
                connection.close()

        threads = [
            threading.Thread(target=attempt, args=("a", first.pk)),
            threading.Thread(target=attempt, args=("b", second.pk)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertTrue(all(not t.is_alive() for t in threads), results)

        self.assertEqual(
            sorted(results.values()), ["claimed", "conflict"], results
        )
        holders = GMRoleSlot.objects.filter(assignment__isnull=False)
        self.assertEqual(holders.count(), 1)
        self.assertIn(holders.get().assignment_id, {first.pk, second.pk})


# ---------------------------------------------------------------------------
# Migration 0005 behavior
# ---------------------------------------------------------------------------
class SingletonSlotMigrationTests(TransactionTestCase):
    """Migration 0005 behavior against the real migration runner.

    ``TransactionTestCase`` is required: reversing/applying migrations
    performs DDL, which SQLite's schema editor refuses inside a TestCase
    transaction. The flush between tests wipes the migration-seeded RBAC
    reference rows, so ``setUp`` re-seeds them (same pattern as the
    existing repo concurrency tests).
    """

    def setUp(self):
        _reseed_rbac_catalog()

    def _reverse_to_0004(self):
        call_command("migrate", "security", "0004", verbosity=0, interactive=False)

    def _apply_all(self):
        call_command("migrate", "security", verbosity=0, interactive=False)

    def _slot_table_exists(self):
        return GMRoleSlot._meta.db_table in set(
            connection.introspection.table_names()
        )

    def test_zero_candidates_keeps_slot_empty(self):
        self._reverse_to_0004()
        self.assertFalse(self._slot_table_exists())
        self._apply_all()
        self.assertTrue(self._slot_table_exists())
        self.assertEqual(GMRoleSlot.objects.count(), 1)
        self.assertIsNone(GMRoleSlot.objects.get().assignment)

    def test_exactly_one_candidate_is_linked_automatically(self):
        self._reverse_to_0004()
        user = User.objects.create_user(username="legacy-super", is_superuser=True)
        assignment = _unlinked_gm_assignment(user)
        # Pre-migration state is unmigrated state, not an inconsistency:
        # E004 must not pre-block the migration that owns the linking.
        self.assertEqual(check_gm_singleton_slot_for_alias("default"), [])
        self._apply_all()
        slot = GMRoleSlot.objects.get()
        self.assertEqual(slot.assignment_id, assignment.pk)
        # The historical row is preserved untouched.
        self.assertTrue(
            UserRoleAssignment.objects.filter(
                pk=assignment.pk, user=user, revoked_at__isnull=True
            ).exists()
        )

    def test_expired_legacy_assignment_is_preserved_but_not_linked(self):
        self._reverse_to_0004()
        user = User.objects.create_user(username="legacy-expired-gm")
        assignment = _unlinked_gm_assignment(user)
        UserRoleAssignment.objects.filter(pk=assignment.pk).update(
            start_at=timezone.now() - timezone.timedelta(days=2),
            end_at=timezone.now() - timezone.timedelta(days=1),
        )

        preflight_output = io.StringIO()
        call_command("gm_slot_preflight", stdout=preflight_output)
        self.assertIn("Currently ACTIVE GM assignments found: 0", preflight_output.getvalue())
        self.assertIn("can proceed automatically: YES", preflight_output.getvalue())

        self._apply_all()

        self.assertIsNone(GMRoleSlot.objects.get().assignment_id)
        self.assertTrue(
            UserRoleAssignment.objects.filter(
                pk=assignment.pk, revoked_at__isnull=True
            ).exists()
        )
        self.assertEqual(check_gm_singleton_slot_for_alias("default"), [])

    def test_temporally_active_assignment_for_inactive_user_blocks_migration(self):
        self._reverse_to_0004()
        user = User.objects.create_user(
            username="legacy-inactive-gm", is_active=False
        )
        assignment = _unlinked_gm_assignment(user)

        preflight_output, preflight_error = io.StringIO(), None
        try:
            call_command("gm_slot_preflight", stdout=preflight_output)
        except CommandError as exc:
            preflight_error = exc
        self.assertIn(
            "Currently ACTIVE assignments belonging to inactive User accounts: 1",
            preflight_output.getvalue(),
        )
        self.assertIn("can proceed automatically: NO", preflight_output.getvalue())
        self.assertIsNotNone(preflight_error)
        self.assertIn("inactive User account", str(preflight_error))

        # The migration itself must independently enforce the same rule.
        with self.assertRaisesRegex(RuntimeError, "inactive User account"):
            self._apply_all()

        # Atomic migration failure preserves both the absent slot structure
        # and the historical assignment; it does not silently revoke/delete.
        self.assertFalse(self._slot_table_exists())
        self.assertTrue(UserRoleAssignment.objects.filter(pk=assignment.pk).exists())
        user.refresh_from_db()
        self.assertFalse(user.is_active)

        # Only an explicit operator reconciliation makes the legacy account
        # eligible; the migration then links the same preserved assignment.
        user.is_active = True
        user.save(update_fields=["is_active"])
        self._apply_all()
        self.assertEqual(GMRoleSlot.objects.get().assignment_id, assignment.pk)

    def test_multiple_candidates_fail_closed_without_choosing(self):
        self._reverse_to_0004()
        u1 = User.objects.create_user(username="candidate-a", is_superuser=True)
        u2 = User.objects.create_user(username="candidate-b", is_superuser=True)
        a1 = _unlinked_gm_assignment(u1)
        a2 = _unlinked_gm_assignment(u2)
        # E004 must not pre-block the migration: the refusal must come from
        # the migration itself with its actionable message.
        self.assertEqual(check_gm_singleton_slot_for_alias("default"), [])
        with self.assertRaises(RuntimeError):
            self._apply_all()
        # The migration is atomic: nothing was created, nothing was chosen,
        # and both historical rows survive.
        self.assertFalse(self._slot_table_exists())
        self.assertTrue(UserRoleAssignment.objects.filter(pk=a1.pk).exists())
        self.assertTrue(UserRoleAssignment.objects.filter(pk=a2.pk).exists())
        self.assertEqual(
            UserRoleAssignment.objects.filter(
                role__code=GM_SLOT_CODE, revoked_at__isnull=True
            ).count(),
            2,
        )
        # Restore the head migration state for later tests: manual
        # reconciliation (never automatic) closes one candidate with a
        # revocation UPDATE — deliberately NOT a DELETE, which would touch
        # the PROTECTed slot relation while the slot table is absent —
        # then the migration proceeds with the single remaining holder.
        UserRoleAssignment.objects.filter(pk=a2.pk).update(
            revoked_at=timezone.now(), revocation_kind="MANUAL"
        )
        self._apply_all()
        self.assertEqual(GMRoleSlot.objects.get().assignment_id, a1.pk)

    def test_reverse_preserves_assignment_history_and_reapplies(self):
        user = User.objects.create_user(username="reverse-holder", is_superuser=True)
        assignment = _unlinked_gm_assignment(user)
        claim_gm_slot(assignment)
        self.assertEqual(GMRoleSlot.objects.get().assignment_id, assignment.pk)

        self._reverse_to_0004()
        self.assertFalse(self._slot_table_exists())
        # Every pre-existing UserRoleAssignment row is preserved exactly.
        self.assertTrue(
            UserRoleAssignment.objects.filter(
                pk=assignment.pk,
                user=user,
                role=_gm_role(),
                revoked_at__isnull=True,
            ).exists()
        )
        self.assertEqual(UserRoleAssignment.objects.count(), 1)

        # Re-application reconciles the same single candidate again.
        self._apply_all()
        self.assertEqual(GMRoleSlot.objects.get().assignment_id, assignment.pk)

    def test_pre_migration_state_reports_missing_structure(self):
        self._reverse_to_0004()
        user = User.objects.create_user(username="premig-holder", is_superuser=True)
        _unlinked_gm_assignment(user)
        out, error = io.StringIO(), None
        try:
            call_command("gm_slot_preflight", stdout=out)
        except CommandError as exc:
            error = exc
        output = out.getvalue()
        self.assertIn("MISSING", output)
        self.assertIn("Non-closed GM assignments found: 1", output)
        self.assertIn("can proceed automatically: YES", output)
        self.assertIsNone(error)
        # Restore the head migration state.
        self._apply_all()
        self.assertEqual(GMRoleSlot.objects.count(), 1)

    def test_makemigrations_detects_no_pending_model_changes(self):
        out, err = io.StringIO(), io.StringIO()
        try:
            call_command(
                "makemigrations", "security", "--check", "--dry-run",
                stdout=out, stderr=err, verbosity=1,
            )
        except SystemExit as exc:
            self.fail(
                "makemigrations --check failed; generated migration diff follows. "
                f"exit={exc.code}; stdout={out.getvalue()!r}; stderr={err.getvalue()!r}"
            )
        self.assertIn(
            "No changes detected in app 'security'",
            out.getvalue(),
            f"makemigrations --check did not confirm a clean migration state: "
            f"stdout={out.getvalue()!r}; stderr={err.getvalue()!r}",
        )
        self.assertEqual(
            err.getvalue().strip(), "",
            f"unexpected makemigrations stderr: {err.getvalue()!r}",
        )


# ---------------------------------------------------------------------------
# Fail-closed behavior of the slot seam
# ---------------------------------------------------------------------------
class SingletonSlotSystemCheckTests(TestCase):
    def _errors(self):
        return check_gm_singleton_slot_for_alias("default")

    def test_valid_empty_slot_is_not_an_error_on_a_fresh_database(self):
        self.assertIsNone(GMRoleSlot.objects.get().assignment)
        self.assertEqual(self._errors(), [])

    def test_missing_slot_row_is_reported(self):
        GMRoleSlot.objects.all().delete()
        errors = self._errors()
        self.assertEqual([e.id for e in errors], ["security.E004"])
        self.assertIn("GM_SLOT_MISSING", errors[0].msg)

    def test_missing_slot_table_after_migration_is_reported(self):
        table_names = set(connection.introspection.table_names())
        self.assertIn("django_migrations", table_names)
        self.assertIn(GMRoleSlot._meta.db_table, table_names)
        table_names.remove(GMRoleSlot._meta.db_table)

        # Simulate a dropped slot table while preserving the real applied
        # migration record. E004 must not mistake this for pre-migration.
        with patch.object(
            connection.introspection,
            "table_names",
            return_value=sorted(table_names),
        ):
            errors = self._errors()

        self.assertEqual([e.id for e in errors], ["security.E004"])
        self.assertIn("GM_SLOT_MISSING", errors[0].msg)

    def test_slot_linking_non_gm_role_is_reported(self):
        corrupt_role = Role.objects.create(code="NOTGM_ROLE", name="Not GM")
        user = User.objects.create_user(username="check-corrupt")
        corrupt_assignment = UserRoleAssignment.objects.create(
            user=user, role=corrupt_role
        )
        GMRoleSlot.objects.update(assignment=corrupt_assignment)
        errors = self._errors()
        self.assertTrue(
            any("GM_SLOT_LINK_NOT_GM_ROLE" in e.msg for e in errors),
            [e.msg for e in errors],
        )

    def test_slot_linking_revoked_assignment_is_reported(self):
        user = User.objects.create_user(username="check-revoked")
        assignment = _unlinked_gm_assignment(user)
        claim_gm_slot(assignment)
        UserRoleAssignment.objects.filter(pk=assignment.pk).update(
            revoked_at=timezone.now(), revocation_kind="MANUAL"
        )
        errors = self._errors()
        self.assertTrue(
            any("GM_SLOT_LINK_REVOKED" in e.msg for e in errors),
            [e.msg for e in errors],
        )

    def test_slot_linking_inactive_user_account_is_reported(self):
        user = User.objects.create_user(username="check-inactive-user")
        assignment = _unlinked_gm_assignment(user)
        claim_gm_slot(assignment)
        user.is_active = False
        user.save(update_fields=["is_active"])

        errors = self._errors()

        self.assertTrue(
            any("GM_SLOT_USER_INACTIVE" in error.msg for error in errors),
            [error.msg for error in errors],
        )

    def test_slot_linking_expired_or_future_assignment_is_reported(self):
        windows = (
            (
                "check-expired-window",
                {
                    "start_at": timezone.now() - timezone.timedelta(days=2),
                    "end_at": timezone.now() - timezone.timedelta(days=1),
                },
            ),
            (
                "check-future-window",
                {"start_at": timezone.now() + timezone.timedelta(days=1)},
            ),
        )
        for username, window in windows:
            with self.subTest(username=username):
                user = User.objects.create_user(username=username)
                assignment = _unlinked_gm_assignment(user)
                UserRoleAssignment.objects.filter(pk=assignment.pk).update(**window)
                GMRoleSlot.objects.update(assignment=assignment)

                errors = self._errors()

                self.assertTrue(
                    any("GM_SLOT_LINK_NOT_ACTIVE" in e.msg for e in errors),
                    [e.msg for e in errors],
                )
                GMRoleSlot.objects.update(assignment=None)

    def test_unlinked_gm_assignment_is_reported_and_cleared_by_claim(self):
        user = User.objects.create_user(username="check-unlinked")
        assignment = _unlinked_gm_assignment(user)
        errors = self._errors()
        self.assertTrue(
            any("GM_ASSIGNMENT_UNLINKED" in e.msg for e in errors),
            [e.msg for e in errors],
        )
        claim_gm_slot(assignment)
        self.assertEqual(self._errors(), [])

    def test_check_messages_never_carry_usernames(self):
        user = User.objects.create_user(username="cannot-see-this-name")
        _unlinked_gm_assignment(user)
        text = " ".join(e.msg for e in self._errors())
        self.assertNotIn("cannot-see-this-name", text)


# ---------------------------------------------------------------------------
# gm_slot_preflight — read-only operator command
# ---------------------------------------------------------------------------
class PreflightCommandTests(TestCase):
    def _run(self):
        out, error = io.StringIO(), None
        try:
            call_command("gm_slot_preflight", stdout=out)
        except CommandError as exc:
            error = exc
        return out.getvalue(), error

    def test_zero_candidates_reports_automatic_proceed(self):
        output, error = self._run()
        self.assertIn("Non-closed GM assignments found: 0", output)
        self.assertIn("can proceed automatically: YES", output)
        self.assertIsNone(error)
        self.assertIn("no rows were changed", output.lower())

    def test_single_candidate_reports_ids_and_status_without_usernames(self):
        user = User.objects.create_user(
            username="preflight-hidden-name",
            is_superuser=True,
            is_staff=True,
        )
        assignment = _unlinked_gm_assignment(user)
        claim_gm_slot(assignment)
        output, error = self._run()
        self.assertIn("Non-closed GM assignments found: 1", output)
        self.assertIn(f"user id={user.pk}", output)
        self.assertIn("is_superuser=True", output)
        self.assertIn("is_staff=True", output)
        self.assertNotIn("preflight-hidden-name", output)
        self.assertIsNone(error)

    def test_post_migration_unlinked_assignment_is_nonzero(self):
        user = User.objects.create_user(username="preflight-orphan")
        _unlinked_gm_assignment(user)
        output, error = self._run()
        self.assertIn("CONSISTENCY FINDING GM_ASSIGNMENT_UNLINKED", output)
        self.assertIsNotNone(error)
        self.assertIn("inconsistent after migration", str(error).lower())

    def test_post_migration_missing_slot_row_is_nonzero(self):
        GMRoleSlot.objects.all().delete()
        output, error = self._run()
        self.assertIn("CONSISTENCY FINDING GM_SLOT_MISSING", output)
        self.assertIsNotNone(error)
        self.assertIn("inconsistent after migration", str(error).lower())

    def test_post_migration_temporally_inactive_link_is_nonzero(self):
        user = User.objects.create_user(username="preflight-expired-holder")
        assignment = _unlinked_gm_assignment(user)
        UserRoleAssignment.objects.filter(pk=assignment.pk).update(
            start_at=timezone.now() - timezone.timedelta(days=2),
            end_at=timezone.now() - timezone.timedelta(days=1),
        )
        GMRoleSlot.objects.update(assignment=assignment)

        output, error = self._run()

        self.assertIn("CONSISTENCY FINDING GM_SLOT_LINK_NOT_ACTIVE", output)
        self.assertIsNotNone(error)
        self.assertIn("inconsistent after migration", str(error).lower())

    def test_post_migration_inactive_user_slot_holder_is_nonzero(self):
        user = User.objects.create_user(username="preflight-inactive-holder")
        assignment = _unlinked_gm_assignment(user)
        claim_gm_slot(assignment)
        user.is_active = False
        user.save(update_fields=["is_active"])

        output, error = self._run()

        self.assertIn(
            "Currently ACTIVE assignments belonging to inactive User accounts: 1",
            output,
        )
        self.assertIn(
            "INACTIVE-USER GM candidates (assignment/user ids):",
            output,
        )
        self.assertIn(f"[({assignment.pk}, {user.pk})]", output)
        self.assertIsNotNone(error)
        self.assertIn("inactive User account", str(error))
        self.assertIn(str(user.pk), output)
        self.assertIn(str(assignment.pk), output)

    def test_multiple_candidates_report_manual_reconciliation(self):
        for index in range(2):
            user = User.objects.create_user(
                username=f"multi-candidate-{index}", is_superuser=True
            )
            _unlinked_gm_assignment(user)
        output, error = self._run()
        self.assertIn("Non-closed GM assignments found: 2", output)
        self.assertIn("can proceed automatically: NO", output)
        self.assertIsNotNone(error)


# ---------------------------------------------------------------------------
# Fail-closed behavior of the slot seam
# ---------------------------------------------------------------------------
class GmSlotFailClosedTests(ResolverTestBase):
    def test_slot_lookup_failure_fails_closed(self):
        user = User.objects.create_user(username="slot-db-failure")
        grant_role(user, "ACCOUNTANT")
        with patch.object(
            authorization, "load_singleton_slot",
            side_effect=RuntimeError("simulated database failure"),
        ):
            with self.assertLogs("security.authorization", level="ERROR"):
                decision = self.resolve(user, "fiscal.period.view")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "FAIL_CLOSED")

    def test_missing_slot_disables_gm_but_not_other_paths(self):
        self.declare_collection("fiscal.period.view")
        user = User.objects.create_user(username="acc-slot-gone")
        grant_role(user, "ACCOUNTANT")
        link("ACCOUNTANT", "fiscal.period.view")
        grant_role(User.objects.create_user(username="gm-slot-gone"), "GM")
        GMRoleSlot.objects.all().delete()

        with self.assertLogs("security.authorization", level="ERROR"):
            decision = self.resolve(user, "fiscal.period.view")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "ROLE_GRANT")
