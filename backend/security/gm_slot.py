"""W0-2B — singleton GM slot domain logic (owner decision: at most ONE active GM).

The owner decision for this batch is binding and additive: **at most ONE
user may hold the active General Manager role in the entire ERP at any
time.** Zero active GM holders are permitted during initial setup or a
controlled recovery interval; two active GM holders are never permitted.
A Django superuser or staff account never receives GM authority merely by
being one, and historical ``UserRoleAssignment`` rows are never silently
reconciled by choosing an account.

This module owns the three singleton-slot primitives shared by the
resolver, the system check, the operator preflight command, and future
W0-2B grant services:

- ``load_singleton_slot()`` — the authoritative read of the single
  ``GMRoleSlot`` row (fail-closed to "no GM" on absence/corruption).
- ``gm_holder_assignment()`` — the persisted assignment currently holding
  the slot, or ``None`` for the valid empty state.
- ``claim_gm_slot()`` — the ONLY writer. An atomic compare-and-set claim
  for an already-created GM assignment: exactly one competing claim may
  succeed, a repeated claim by the same assignment is idempotent, and an
  existing holder is never overwritten, cleared, or transferred.
- ``inspect_slot_consistency()`` — read-only findings used verbatim by the
  ``security.E004`` system check and the ``gm_slot_preflight`` command.

Fail-closed rules: a missing or malformed slot, a missing/wrong linked
assignment, a wrong or inactive role, and a revoked/expired/not-yet-effective
link all read as "not GM" — never as GM. Unexpected database errors
propagate to the caller (the resolver boundary converts them into
``FAIL_CLOSED``). No function here reads or returns password, token, TOTP,
recovery, or other secret material.

The design is engine-neutral: the claim's compare-and-set is a single
conditional ``UPDATE ... WHERE assignment IS NULL`` statement, which is
atomic under SQLite's database-level write serialization and under
PostgreSQL row locking with READ COMMITTED re-evaluation.
``select_for_update()`` alone is deliberately NOT relied upon.
"""
from django.db import transaction
from django.utils import timezone

GM_SLOT_CODE = "GM"

# Stable finding codes shared by the system check (security.E004) and the
# operator preflight command. Messages carry identifiers and counts only.
FINDING_SLOT_MISSING = "GM_SLOT_MISSING"
FINDING_SLOT_DUPLICATE = "GM_SLOT_DUPLICATE"
FINDING_SLOT_INVALID_IDENTITY = "GM_SLOT_INVALID_IDENTITY"
FINDING_LINK_NOT_GM_ROLE = "GM_SLOT_LINK_NOT_GM_ROLE"
FINDING_LINK_REVOKED = "GM_SLOT_LINK_REVOKED"
FINDING_LINK_NOT_ACTIVE = "GM_SLOT_LINK_NOT_ACTIVE"
FINDING_LINK_USER_INACTIVE = "GM_SLOT_USER_INACTIVE"
FINDING_UNLINKED_GM_ASSIGNMENT = "GM_ASSIGNMENT_UNLINKED"


class GMSlotClaimError(Exception):
    """Domain error raised when the singleton GM slot cannot be claimed.

    Safe by construction: the message carries no account identifiers or
    secret material. The helper's nested ``transaction.atomic()`` rolls
    back its own savepoint on failure. It cannot force an enclosing
    transaction to roll back if the caller catches this exception inside
    that outer block. Callers that create an assignment and require the
    creation to roll back on claim failure must let this exception escape
    the outer transaction (or explicitly roll back there).
    """


def load_singleton_slot(using=None):
    """Return the single GMRoleSlot row, or None when absent or corrupt.

    A missing row (migration 0005 not applied) and an impossible duplicate
    both fail closed to "no GM authority available"; the system check
    reports them separately. Database errors propagate to the caller.
    """
    from security.models import GMRoleSlot

    queryset = GMRoleSlot.objects.select_related("assignment", "assignment__role")
    if using:
        queryset = queryset.using(using)
    try:
        return queryset.get(code=GM_SLOT_CODE)
    except GMRoleSlot.DoesNotExist:
        return None
    except GMRoleSlot.MultipleObjectsReturned:
        # Unreachable while the unique+check constraints hold; fail closed
        # if the database state is tampered with.
        return None


def gm_holder_assignment(using=None):
    """The assignment currently holding the slot, or None (valid empty state)."""
    slot = load_singleton_slot(using=using)
    if slot is None:
        return None
    return slot.assignment


def _temporally_active(assignment, at):
    """The §14.2 ACTIVE predicate evaluated on a loaded assignment row."""
    if assignment.revoked_at is not None:
        return False
    if assignment.start_at is None or assignment.start_at > at:
        return False
    if assignment.end_at is not None and assignment.end_at <= at:
        return False
    return True


def claim_gm_slot(assignment):
    """Atomically claim the singleton GM slot for a valid GM assignment.

    Contract (owner decision, W0-2B):

    - Opens its own ``transaction.atomic()`` block. When called inside a
      caller-owned transaction this is a savepoint: a raised error rolls
      back the helper's work, but rolls back the caller's work only when
      the exception is allowed to propagate out of the caller's outer
      atomic block. Do not catch-and-suppress a claim error inside that
      outer block when assignment creation must be atomic with the claim.
    - Verifies the assignment is a persisted, non-closed, temporally ACTIVE
      assignment of the ACTIVE ``GM`` role (fresh re-read, never the
      caller's possibly-stale instance).
    - Requires the singleton slot row to exist (migration 0005 applied).
    - Claims with a database-atomic conditional update
      (``UPDATE ... WHERE code='GM' AND assignment IS NULL``): exactly one
      competing claim succeeds; a repeated claim by the same assignment is
      idempotent.
    - Never overwrites an existing holder, never silently clears or
      transfers the slot, and raises the domain-specific
      ``GMSlotClaimError`` when the slot is already held by another
      assignment.

    This is an internal helper — no public endpoint, Admin action, or
    general revocation/transfer service is provided by this batch.
    """
    from security.models import GMRoleSlot, UserRoleAssignment

    with transaction.atomic():
        if assignment is None or assignment.pk is None:
            raise GMSlotClaimError(
                "GM slot claim requires a persisted role assignment"
            )
        try:
            fresh = (
                UserRoleAssignment.objects.select_related("role")
                .get(pk=assignment.pk)
            )
        except UserRoleAssignment.DoesNotExist:
            raise GMSlotClaimError(
                "GM slot claim requires a persisted role assignment"
            )

        role = fresh.role
        at = timezone.now()
        if role is None or role.code != GM_SLOT_CODE or not role.is_active:
            raise GMSlotClaimError(
                "GM slot can only be claimed by an assignment of the active GM role"
            )
        if not _temporally_active(fresh, at):
            raise GMSlotClaimError(
                "GM slot can only be claimed by a non-closed, temporally "
                "active GM assignment"
            )

        # Compare-and-set: the update touches a row only while the slot is
        # empty. On SQLite the write is serialized database-wide; on
        # PostgreSQL competing updates block on the row lock and re-evaluate
        # the predicate after the winner commits.
        updated = GMRoleSlot.objects.filter(
            code=GM_SLOT_CODE, assignment__isnull=True
        ).update(assignment=fresh)
        if updated:
            return GMRoleSlot.objects.select_related(
                "assignment", "assignment__role"
            ).get(code=GM_SLOT_CODE)

        try:
            current = GMRoleSlot.objects.get(code=GM_SLOT_CODE)
        except GMRoleSlot.DoesNotExist:
            raise GMSlotClaimError(
                "GM singleton slot row is missing; apply migration "
                "security.0005 before provisioning"
            )
        if current.assignment_id == fresh.pk:
            return current  # idempotent re-claim by the same assignment
        raise GMSlotClaimError(
            "GM singleton slot is already held by another assignment; the "
            "owner decision permits at most ONE active GM holder and the "
            "slot is never overwritten or transferred"
        )


def inspect_slot_consistency(using=None):
    """Read-only consistency inspection of the singleton GM slot state.

    Returns a list of ``(finding_code, message)`` pairs describing every
    inconsistent state that could make GM resolution ambiguous. A valid
    EMPTY slot on a database with no GM provisioned is NOT a finding: the
    system must start safely before first-GM provisioning. Messages carry
    row identifiers and counts only — never passwords, tokens, TOTP
    secrets, recovery material, or usernames.

    A database whose slot structure does not exist yet (migration
    ``security.0005`` not applied) reports exactly the
    ``GM_SLOT_MISSING`` finding instead of a database error, so the
    preflight command also works against a pre-migration database.
    """
    from django.db import connections
    from security.models import GMRoleSlot, UserRoleAssignment

    alias = using or "default"
    if GMRoleSlot._meta.db_table not in set(
        connections[alias].introspection.table_names()
    ):
        return [
            (
                FINDING_SLOT_MISSING,
                "the GMRoleSlot structure is missing (migration "
                "security.0005 not applied)",
            )
        ]

    findings = []
    queryset = GMRoleSlot.objects.select_related(
        "assignment", "assignment__role", "assignment__user"
    )
    if using:
        queryset = queryset.using(using)
    rows = list(queryset.order_by("pk"))

    if not rows:
        return [
            (
                FINDING_SLOT_MISSING,
                "the GMRoleSlot singleton row is missing; apply migration "
                "security.0005",
            )
        ]
    if len(rows) > 1:
        findings.append(
            (
                FINDING_SLOT_DUPLICATE,
                f"{len(rows)} GM slot rows exist; exactly one is permitted "
                f"(slot pks={sorted(row.pk for row in rows)})",
            )
        )

    slot = rows[0]
    if slot.code != GM_SLOT_CODE:
        findings.append(
            (
                FINDING_SLOT_INVALID_IDENTITY,
                f"GM slot identity code is invalid (slot pk={slot.pk}); the "
                f"singleton identity must be exactly {GM_SLOT_CODE!r}",
            )
        )

    assignment = slot.assignment
    if assignment is not None:
        if not assignment.user.is_active:
            findings.append(
                (
                    FINDING_LINK_USER_INACTIVE,
                    f"GM slot (pk={slot.pk}) links assignment pk="
                    f"{assignment.pk} for inactive User account "
                    f"(user id={assignment.user_id})",
                )
            )
        role = getattr(assignment, "role", None)
        if role is None or role.code != GM_SLOT_CODE or not role.is_active:
            findings.append(
                (
                    FINDING_LINK_NOT_GM_ROLE,
                    f"GM slot (pk={slot.pk}) links assignment pk="
                    f"{assignment.pk} whose role is not the active GM role",
                )
            )
        if assignment.revoked_at is not None:
            findings.append(
                (
                    FINDING_LINK_REVOKED,
                    f"GM slot (pk={slot.pk}) links a revoked assignment "
                    f"(assignment pk={assignment.pk})",
                )
            )
        elif not _temporally_active(assignment, timezone.now()):
            findings.append(
                (
                    FINDING_LINK_NOT_ACTIVE,
                    f"GM slot (pk={slot.pk}) links an assignment outside "
                    f"its temporal ACTIVE window (assignment pk={assignment.pk})",
                )
            )

    # Any non-closed GM assignment not represented by the slot makes GM
    # resolution ambiguous, even though the resolver itself fails closed.
    linked_ids = {row.assignment_id for row in rows if row.assignment_id}
    from django.db.models import Q

    at = timezone.now()
    unlinked = UserRoleAssignment.objects.filter(
        role__code=GM_SLOT_CODE,
        role__is_active=True,
        revoked_at__isnull=True,
        start_at__lte=at,
    ).filter(
        Q(end_at__isnull=True) | Q(end_at__gt=at)
    ).exclude(pk__in=linked_ids)
    if using:
        unlinked = unlinked.using(using)
    unlinked_ids = list(unlinked.order_by("pk").values_list("pk", flat=True)[:20])
    if unlinked_ids:
        findings.append(
            (
                FINDING_UNLINKED_GM_ASSIGNMENT,
                f"{len(unlinked_ids)} currently ACTIVE GM role assignment(s) are "
                "not represented by the singleton GM slot (assignment pks="
                f"{unlinked_ids}); the resolver grants them no GM authority",
            )
        )
    return findings
