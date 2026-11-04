"""W0-2B — singleton GM slot (owner decision: at most ONE active GM holder).

Additive migration on top of 0004. Migrations 0001–0004 are NOT rewritten.

Owner decision implemented here (binding): at most ONE user may hold the
active General Manager role in the entire ERP at any time. Zero active GM
users are permitted during initial setup or a controlled recovery interval;
two active GM users are never permitted; a second user must never receive
GM merely because they are a Django superuser or staff user; existing GM
role assignments must be reconciled without silently choosing an account.

Schema (additive only):
- ``GMRoleSlot`` — a fixed-identity singleton row. ``code`` is unique and
  check-constrained to exactly ``"GM"`` so at most one row can exist; the
  nullable ``OneToOneField`` to ``security.UserRoleAssignment`` (PROTECT)
  links the one holder and prevents one assignment from being linked more
  than once. NULL is a VALID state (fresh system / controlled recovery
  interval).

Data reconciliation (never chooses an account):
1. The singleton slot row is created with NO assignment.
2. All legacy assignments remain preserved. Only a currently ACTIVE GM
   assignment (active GM role, not revoked, ``start_at <= now``, and
   ``end_at IS NULL OR end_at > now``) is a candidate to occupy the slot.
   Expired and future assignments remain unchanged history and do not
   reserve the current GM slot.
3. Zero candidates  -> the slot stays empty (expected before first-GM
   provisioning).
4. Exactly one candidate -> that candidate is linked through a
   compare-and-set update that only fires while the slot is empty.
5. More than one candidate -> the migration STOPS with an actionable
   error. It never picks the lowest ID, earliest account, first superuser,
   or any other automatic winner. The whole migration is atomic, so the
   failure rolls back every row it wrote.

Historical ``UserRoleAssignment`` rows are never deleted, rewritten,
shortened, merged, or silently revoked. Reverse removes exactly this
migration's own singleton structure/record and preserves every
pre-existing assignment row.

Operators must run the read-only ``manage.py gm_slot_preflight`` command
before deploying when the database may contain multiple legacy GM
assignments; it reports candidate user IDs and safe account status fields
only — never passwords, tokens, TOTP secrets, or recovery material.
"""
from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone
import django.db.models.deletion

GM_SLOT_CODE = "GM"


def seed_slot_and_reconcile(apps, schema_editor):
    GMRoleSlot = apps.get_model("security", "GMRoleSlot")
    UserRoleAssignment = apps.get_model("security", "UserRoleAssignment")
    db_alias = schema_editor.connection.alias

    # RunPython historical models are not automatically pinned to the
    # connection that invoked this migration. Every ORM operation must use
    # schema_editor's database alias to avoid writing to "default" when a
    # non-default database is migrated.
    # 1) The singleton row, with no assignment. Idempotent by identity.
    slot, _created = GMRoleSlot.objects.using(db_alias).get_or_create(
        code=GM_SLOT_CODE
    )
    if slot.assignment_id is not None:
        # Defensive: the slot already holds a holder. Never overwrite,
        # clear, or transfer it.
        return

    # 2) Only a GM assignment that is ACTIVE now can occupy the singleton.
    # Expired/future rows remain unchanged history and do not reserve the slot.
    at = timezone.now()
    candidates = list(
        UserRoleAssignment.objects.using(db_alias).filter(
            role__code=GM_SLOT_CODE,
            role__is_active=True,
            revoked_at__isnull=True,
            start_at__lte=at,
        ).filter(
            Q(end_at__isnull=True) | Q(end_at__gt=at)
        ).order_by("pk")
    )

    # 3) Zero candidates: a fresh system before provisioning — valid state.
    if not candidates:
        return

    # 5) Multiple candidates: the owner decision forbids automatic choice.
    if len(candidates) > 1:
        raise RuntimeError(
            f"security.0005 refused to run: {len(candidates)} currently ACTIVE GM "
            "role assignments exist, but the W0-2B owner decision permits "
            "at most ONE active GM holder and this migration will never "
            "choose an account automatically (not the lowest ID, not the "
            "earliest account, not a superuser). Run `python manage.py "
            "gm_slot_preflight` for the read-only candidate report (user "
            "IDs and safe account status fields only), reconcile only the "
            "currently ACTIVE GM assignments so at most one remains, preserve "
            "expired/future history unchanged, then re-apply this migration. "
            "No rows were changed."
        )

    # 4) Exactly one candidate: link it through a CAS update that fires
    #    only while the slot is empty (never overwrites a holder).
    updated = GMRoleSlot.objects.using(db_alias).filter(
        code=GM_SLOT_CODE, assignment__isnull=True
    ).update(assignment=candidates[0])
    if updated != 1:
        raise RuntimeError(
            "security.0005 refused to link the single GM candidate: the "
            "singleton slot is missing or already held. Run `python "
            "manage.py gm_slot_preflight` and review manually. No rows "
            "were changed."
        )


def remove_singleton_slot(apps, schema_editor):
    """Reverse: remove ONLY this migration's own singleton record.

    Every pre-existing ``security.UserRoleAssignment`` row is preserved.
    (The CreateModel reversal drops the slot table itself; deleting the
    rows here keeps the data operation explicit and order-independent.)
    """
    GMRoleSlot = apps.get_model("security", "GMRoleSlot")
    db_alias = schema_editor.connection.alias
    GMRoleSlot.objects.using(db_alias).all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0004_legacy_superuser_gm_mapping"),
    ]

    operations = [
        migrations.CreateModel(
            name="GMRoleSlot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=20, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assignment", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="gm_slot", to="security.userroleassignment")),
            ],
            options={
                "constraints": [models.CheckConstraint(condition=models.Q(("code", "GM")), name="security_gm_slot_code_gm_only")],
            },
        ),
        migrations.RunPython(
            seed_slot_and_reconcile,
            reverse_code=remove_singleton_slot,
        ),
    ]
