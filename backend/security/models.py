from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditAction(models.TextChoices):
    LOGIN = "LOGIN", "Login"
    LOGOUT = "LOGOUT", "Logout"
    CREATE = "CREATE", "Create"
    UPDATE = "UPDATE", "Update"
    POST = "POST", "Post"
    REVERSE = "REVERSE", "Reverse"
    APPROVE = "APPROVE", "Approve"


class AuditEvent(models.Model):
    """Immutable audit foundation for future financial operations."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=20, choices=AuditAction.choices)
    entity = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=100, blank=True)
    reference = models.CharField(max_length=200, blank=True)
    previous_state = models.JSONField(null=True, blank=True)
    new_state = models.JSONField(null=True, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


# ---------------------------------------------------------------------------
# W0-2A / R1 — RBAC foundation models (M1–M6).
#
# Contract: docs/architecture/W0-2A_RBAC_OFFLINE_SECURITY_DESIGN_DRAFT.md
# §14 (temporal semantics, uniqueness, deletion policies) as approved at
# commit e0d7db4505b7c04b1093c07e953aa4b1a3944f1d.
#
# These models are SCHEMA-ONLY in R1 (§24.2): nothing in the production
# request path reads or writes them in R1. The dormant resolver
# (security/authorization.py) is the only reader, and no view imports it.
# Django Groups/auth.Permission are NOT used as an authorization source of
# truth (§4.3); the default Django User model is referenced, never replaced.
# ---------------------------------------------------------------------------


class RevocationKind(models.TextChoices):
    """Closure cause for temporal grant rows (§14.1, defect A fix)."""

    MANUAL = "MANUAL", "Manual revocation"
    EXPIRED = "EXPIRED", "Expired (settled)"
    SUPERSEDED = "SUPERSEDED", "Superseded by a replacement grant"


class OverrideEffect(models.TextChoices):
    """Explicit per-user override effect (M5, §14.9)."""

    ALLOW = "ALLOW", "Allow"
    DENY = "DENY", "Deny"


class Role(models.Model):
    """M1 — stable role identity and active state (§14.9).

    `code` is unique and case-sensitive under the default collation of both
    supported engines. `is_system=True` marks the three canonical seeds
    (GM/ACCOUNTANT/WAREHOUSE_KEEPER); deletion of a system role is
    service-guarded in a later batch (§14.8) — R1 adds no such service.
    """

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    name_fa = models.CharField(max_length=100, blank=True, default="")
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class Permission(models.Model):
    """M2 — RBAC permission catalog row (§14.9).

    The single source of truth for catalog content is
    ``SECURITY_PERMISSION_CATALOG`` in ``security/permissions_catalog.py``
    (§15.1); rows here are seeded from it and asserted equal by a database
    system check. This model is distinct from
    ``django.contrib.auth.models.Permission`` and must never be confused
    with it. Catalog rows are deactivated (``is_active=False``), never
    deleted (§14.8).
    """

    key = models.CharField(max_length=100, unique=True)
    domain = models.CharField(max_length=50)
    resource = models.CharField(max_length=50)
    action = models.CharField(max_length=50)
    description = models.CharField(max_length=500, blank=True, default="")
    is_sensitive = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["domain", "key"]

    def __str__(self):
        return self.key


class RolePermission(models.Model):
    """M3 — permission granted to a role (§14.9).

    Deleting a (non-system) role cascades only its structural grant rows;
    catalog rows and authorization history are PROTECTed (§14.8).
    """

    role = models.ForeignKey(
        Role, on_delete=models.CASCADE, related_name="permission_grants"
    )
    permission = models.ForeignKey(
        Permission, on_delete=models.PROTECT, related_name="role_grants"
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="role_permission_grants",
    )
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["role", "permission"],
                name="security_rp_role_permission_unique",
            ),
        ]

    def __str__(self):
        return f"{self.role_id}:{self.permission_id}"


class UserRoleAssignment(models.Model):
    """M4 — user-to-role assignment (§14.1 temporal grant-row shape).

    At most one non-closed row per (user, role) — the partial unique is the
    race backstop; temporal correctness comes from settlement-before-insert
    in the future W0-2B grant services (§14.4–§14.6, CONTRACT-ONLY for R1).
    SCHEDULED/EXPIRED/REVOKED rows never grant; only the ACTIVE predicate
    of §14.2 grants.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    role = models.ForeignKey(
        Role, on_delete=models.PROTECT, related_name="user_assignments"
    )
    start_at = models.DateTimeField(default=timezone.now)
    end_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=500, blank=True, default="")
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="role_assignments_granted",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="role_assignments_revoked",
    )
    revocation_kind = models.CharField(
        max_length=20,
        choices=RevocationKind.choices,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role"],
                condition=models.Q(revoked_at__isnull=True),
                name="security_ura_live_slot_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(end_at__isnull=True)
                | models.Q(end_at__gt=models.F("start_at")),
                name="security_ura_window_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "role", "revoked_at"],
                name="security_ura_slot_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.role_id}"


class UserPermissionOverride(models.Model):
    """M5 — explicit per-user ALLOW/DENY override (§14.1, §14.9).

    Effect-independent uniqueness: one live row per (user, permission)
    across both effects, so an ambiguous simultaneously-live ALLOW+DENY
    pair is impossible at the database level (§14.4, revised). The resolver
    still applies deny-wins defensively (§16, R15).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="permission_overrides",
    )
    permission = models.ForeignKey(
        Permission, on_delete=models.PROTECT, related_name="user_overrides"
    )
    effect = models.CharField(max_length=10, choices=OverrideEffect.choices)
    start_at = models.DateTimeField(default=timezone.now)
    end_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=500, blank=True, default="")
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="permission_overrides_granted",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="permission_overrides_revoked",
    )
    revocation_kind = models.CharField(
        max_length=20,
        choices=RevocationKind.choices,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "permission"],
                condition=models.Q(revoked_at__isnull=True),
                name="security_upo_live_slot_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(end_at__isnull=True)
                | models.Q(end_at__gt=models.F("start_at")),
                name="security_upo_window_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "permission", "revoked_at"],
                name="security_upo_slot_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.permission_id}:{self.effect}"


class UserWarehouseScope(models.Model):
    """M6 — per-user warehouse assignment registry (§14.1, §14.9).

    Schema-only in W0-2A; enforcement is provided through the dormant
    resolver's scope evaluation and wired by a later batch via the
    ScopeContext contract (§14.9, §24.2).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="warehouse_scopes",
    )
    warehouse = models.ForeignKey(
        "warehouses.Warehouse",
        on_delete=models.PROTECT,
        related_name="user_scopes",
    )
    start_at = models.DateTimeField(default=timezone.now)
    end_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=500, blank=True, default="")
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="warehouse_scopes_granted",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="warehouse_scopes_revoked",
    )
    revocation_kind = models.CharField(
        max_length=20,
        choices=RevocationKind.choices,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "warehouse"],
                condition=models.Q(revoked_at__isnull=True),
                name="security_uws_live_slot_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(end_at__isnull=True)
                | models.Q(end_at__gt=models.F("start_at")),
                name="security_uws_window_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "warehouse", "revoked_at"],
                name="security_uws_slot_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.warehouse_id}"


class GMRoleSlot(models.Model):
    """W0-2B — authoritative singleton identity of the single GM holder.

    Owner decision (additive, W0-2B/R2): **at most ONE user may hold the
    active General Manager role in the entire ERP at any time.** Zero active
    GM users are permitted during initial setup or a controlled recovery
    interval; two active GM users are never permitted. The policy is global
    — never per department, warehouse, device, or organization unit — and a
    Django superuser or staff user never receives GM merely by being one.

    The slot is a fixed-identity database singleton:

    - ``code`` is unique and constrained to exactly ``"GM"``, so at most one
      slot row can exist (unique + check constraint).
    - ``assignment`` is a nullable OneToOne to the single GM
      ``UserRoleAssignment``. NULL is a VALID state on a fresh system before
      first-GM provisioning and during a controlled recovery interval.
    - ``on_delete=PROTECT`` and the absence of any transfer/revoke service
      in this batch mean the slot never silently overwrites, clears, or
      transfers a holder. A second user must never be linked while the slot
      is held; claiming is exclusively the atomic CAS helper
      (``security.gm_slot.claim_gm_slot``).
    - The OneToOne unique constraint prevents one assignment from being
      linked more than once.

    The resolver (``security/authorization.py``) recognizes GM ONLY through
    this row's linked assignment; an ordinary unlinked
    ``UserRoleAssignment(role=GM)`` grants no protected GM capability and no
    GM permission keys. Historical ``UserRoleAssignment`` rows are never
    rewritten, merged, or silently revoked by migration 0005.
    """

    code = models.CharField(max_length=20, unique=True)
    assignment = models.OneToOneField(
        UserRoleAssignment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="gm_slot",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code="GM"),
                name="security_gm_slot_code_gm_only",
            ),
        ]

    def __str__(self):
        return f"{self.code}:{self.assignment_id or '-'}"


# W0-2C durable MFA and server-side session records.
# Kept in a focused module; importing here registers the models with Django.
from security.mfa_models import (  # noqa: E402,F401
    MFADeviceStatus,
    SecurityLoginSession,
    SecurityMFADevice,
    SecurityRecoveryCode,
    SecurityMFARequirement,
    SecurityBootstrapToken,
    SecurityEmergencyOwnerKey,
)
