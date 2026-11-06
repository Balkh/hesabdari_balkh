"""W0-2B — read-only singleton GM slot preflight for operators.

Reports, without modifying anything:
- whether the ``GMRoleSlot`` singleton structure exists (migration
  ``security.0005`` applied or not);
- the current slot holder, if any (assignment pk and user id only);
- every non-closed GM role assignment (``role__code="GM"``,
  ``revoked_at IS NULL``) with user IDs and safe account status fields;
- the separate count of currently ACTIVE candidates (active GM role,
  not revoked, start time reached, and end time absent or in the future),
  including a separate blocker count for candidates whose User account is
  inactive; an inactive User candidate blocks migration rather than being
  linked or silently ignored;
- whether migration ``security.0005`` can proceed automatically (zero or
  one currently ACTIVE candidate attached to an active User account, with
  no inactive-account candidate) or will refuse to run. Multiple ACTIVE
  candidates or any ACTIVE assignment for an inactive User require manual
  owner-authorized reconciliation; no account is chosen or altered here.

The command never modifies accounts or grants and never prints passwords,
tokens, TOTP secrets, recovery codes, or other personal secrets — user
names and e-mails are deliberately excluded; only numeric IDs and status
flags are reported.

Exit codes: 0 when migration can proceed automatically (or the slot state
is already consistent), 1 when manual reconciliation is required or the
report could not be produced.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from security.gm_slot import (
    GM_SLOT_CODE,
    _temporally_active,
    inspect_slot_consistency,
)


def _table_exists(alias, model):
    connection = connections[alias]
    return model._meta.db_table in set(connection.introspection.table_names())


class Command(BaseCommand):
    help = (
        "Read-only singleton GM slot preflight: reports GM slot state and "
        "non-closed GM assignments plus the currently ACTIVE candidate count. "
        "Modifies nothing; prints no secret material."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default="default",
            help="Database alias to inspect (default: default).",
        )

    def handle(self, *args, **options):
        from security.models import GMRoleSlot, UserRoleAssignment

        alias = options["database"]
        if alias not in connections:
            raise CommandError(f"unknown database alias: {alias!r}")

        migration_applied = (
            ("security", "0005_gmroleslot")
            in MigrationRecorder(connections[alias]).applied_migrations()
        )
        slot_table_exists = _table_exists(alias, GMRoleSlot)

        out = self.stdout
        out.write(f"GM singleton slot preflight (database: {alias!r})")
        out.write(
            "Owner decision: at most ONE user may hold the active GM role "
            "in the entire ERP at any time; the migration never chooses an "
            "account automatically."
        )

        out.write(
            "- security.0005 migration: "
            + ("applied" if migration_applied else "not applied (pre-migration)")
        )
        if not slot_table_exists:
            out.write(
                "- GMRoleSlot table: MISSING. This is expected only before "
                "security.0005; after an applied migration it is an error."
            )
        else:
            out.write("- GMRoleSlot table: present")

        # Slot state (only meaningful once the table exists).
        if slot_table_exists:
            slot_qs = GMRoleSlot.objects.using(alias).order_by("pk")
            slot_rows = list(slot_qs)
            if not slot_rows:
                out.write("- GM slot row: MISSING (run migration security.0005)")
            else:
                slot = slot_rows[0]
                if slot.assignment_id is None:
                    out.write(
                        "- GM slot row: present, EMPTY (valid state before "
                        "first-GM provisioning / during a controlled "
                        "recovery interval)"
                    )
                else:
                    holder = slot.assignment
                    out.write(
                        f"- GM slot row: present, HELD by assignment pk="
                        f"{holder.pk} (user id={holder.user_id})"
                    )
                if len(slot_rows) > 1:
                    out.write(
                        f"- WARNING: {len(slot_rows)} slot rows exist; "
                        "exactly one is permitted."
                    )

        # Candidates: non-closed GM assignments (pre- and post-migration).
        if not _table_exists(alias, UserRoleAssignment):
            raise CommandError(
                "security.UserRoleAssignment table does not exist on this "
                "alias; apply migrations first. No rows were changed."
            )

        now = timezone.now()
        candidates = list(
            UserRoleAssignment.objects.using(alias)
            .filter(role__code=GM_SLOT_CODE, revoked_at__isnull=True)
            .select_related("user", "role")
            .order_by("pk")
        )
        active_candidates = [
            assignment
            for assignment in candidates
            if assignment.role.is_active and _temporally_active(assignment, now)
        ]
        inactive_user_candidates = [
            assignment for assignment in active_candidates
            if not assignment.user.is_active
        ]
        eligible_candidates = [
            assignment for assignment in active_candidates
            if assignment.user.is_active
        ]
        out.write(f"- Non-closed GM assignments found: {len(candidates)}")
        out.write(
            f"- Currently ACTIVE GM assignments found: {len(active_candidates)}"
        )
        out.write(
            f"- Currently ACTIVE assignments belonging to inactive User accounts: "
            f"{len(inactive_user_candidates)}"
        )
        out.write(
            f"- Eligible GM candidates (active User accounts): {len(eligible_candidates)}"
        )
        if inactive_user_candidates:
            details = [
                (assignment.pk, assignment.user_id)
                for assignment in inactive_user_candidates
            ]
            out.write(
                f"- INACTIVE-USER GM candidates (assignment/user ids): {details}"
            )
        for assignment in candidates:
            user = assignment.user
            window = (
                f"start_at={assignment.start_at.isoformat() if assignment.start_at else None}, "
                f"end_at={assignment.end_at.isoformat() if assignment.end_at else None}"
            )
            out.write(
                f"  * assignment pk={assignment.pk} user id={user.pk} "
                f"role pk={assignment.role_id} is_active={user.is_active} "
                f"is_staff={user.is_staff} is_superuser={user.is_superuser} "
                f"{window} reason={assignment.reason!r} "
                f"temporally_active_now={bool(
                    assignment.revoked_at is None
                    and assignment.start_at is not None
                    and assignment.start_at <= now
                    and (assignment.end_at is None or assignment.end_at > now)
                )}"
            )
            out.write(
                f"    (account status fields only; usernames and e-mails "
                f"are intentionally not printed)"
            )

        can_proceed = (
            len(active_candidates) <= 1 and not inactive_user_candidates
        )
        out.write(
            "- Migration security.0005 can proceed automatically: "
            + ("YES" if can_proceed else "NO")
        )

        if inactive_user_candidates:
            details = [
                (assignment.pk, assignment.user_id)
                for assignment in inactive_user_candidates
            ]
            raise CommandError(
                f"{len(inactive_user_candidates)} currently ACTIVE GM "
                "assignment(s) belong to inactive User account(s) "
                f"(assignment/user ids={details}). Migration is blocked: "
                "the slot must not be linked to an unusable account. Obtain "
                "the owner's reconciliation decision and use the authorized "
                "account/assignment procedure. This command never activates, "
                "revokes, deletes, or transfers an account or GM assignment. "
                "No rows were changed."
            )
        if len(active_candidates) > 1:
            raise CommandError(
                f"{len(active_candidates)} currently ACTIVE GM assignments "
                "exist; the singleton GM policy permits at most ONE. "
                "Reconcile manually (close/revoke all but the approved holder's "
                "assignment), then re-run this preflight. No rows were "
                "changed by this command."
            )

        if migration_applied:
            # After 0005, an orphan assignment, missing slot row/table, or
            # any other consistency finding is a blocking error. Do not
            # report success merely because the candidate count is <= 1.
            findings = inspect_slot_consistency(using=alias)
            for code, message in findings:
                out.write(f"- CONSISTENCY FINDING {code}: {message}")
            if findings:
                raise CommandError(
                    "Singleton GM slot is inconsistent after migration "
                    "security.0005. Reconcile the reported findings and "
                    "re-run this read-only preflight. No rows were changed."
                )
        elif slot_table_exists:
            # A table without its migration record is not a clean
            # pre-migration state; stop for manual inspection.
            raise CommandError(
                "GMRoleSlot table exists but migration security.0005 is "
                "not recorded. Treat this as a partial migration state and "
                "inspect it manually before proceeding. No rows were changed."
            )

        out.write(
            "Preflight complete: no rows were changed and no secret "
            "material was read or printed."
        )
