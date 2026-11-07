"""W0-2A / R1 RBAC policy core, extended by the W0-2B/R2 operation entry point.

The legacy key-only `resolve()` remains a compatibility wrapper with its
R1 evaluation order. Mounted R2 API views call `resolve_operation()` through
`HasErpOperation`; the operation-aware path binds a server-declared view
method and typed target while reusing the same policy core.

Binding contract: W0-2A_RBAC_OFFLINE_SECURITY_DESIGN_DRAFT.md §16.1 (the
ten-step evaluation sequence), §16.2 (pseudocode), §9A Item 2, as approved
at commit e0d7db4505b7c04b1093c07e953aa4b1a3944f1d.

Historical R1 boundary and current R2 wiring:
- In W0-2A/R1, the key-only resolver was dormant and no first-party view
  imported it directly. The R1 regression test continues to pin that direct
  import boundary and the frozen DRF authentication defaults.
- W0-2B/R2 now wires only explicitly declared API methods through
  HasErpOperation, OperationSpec, and resolve_operation(). The operation
  registry imports the typed TargetReference; view modules do not call the
  legacy resolve() entry point.
- Both entry points use the same _resolve() policy core. The legacy
  key-only resolve() retains its R1 evaluation behavior; the operation
  entry point supplies a method-specific server-owned resource binding.
- ERP_RBAC_ENFORCEMENT currently defaults to False in base settings. The
  Production startup guard is not implemented in this branch yet, so this
  draft must not be merged or deployed.

Evaluation order (§16.1 — never reordered, never short-circuited into an
allow path):

1. Authentication           -> DENY UNAUTHENTICATED (nothing persisted;
                               frozen Batch 3 no-persist pin preserved)
2. Account state            -> DENY INACTIVE_ACCOUNT / ACCOUNT_LOCKED
3. Session validity         -> DENY NO_ACTIVE_SESSION / MFA_REQUIRED
4. Permission-key resolution-> DENY UNKNOWN_PERMISSION (first catalog touch;
                               unauthenticated callers learn nothing)
5. Protected GM authority   -> ALLOW GM_PROTECTED (overrides never
                               consulted for GM; domain invariants still
                               apply downstream of the resolver).
                               W0-2B owner decision: GM is recognized ONLY
                               through the singleton GMRoleSlot row's linked
                               assignment; an unlinked GM assignment grants
                               no GM authority (identity, role, and ACTIVE
                               predicate of the LINKED row are all required).
6. Explicit user DENY       -> DENY USER_DENY (deny wins over everything
                               below)
7. Explicit user ALLOW      -> candidate USER_ALLOW (never returned before
                               the scope gate)
8. Role-derived grants      -> candidate ROLE_GRANT (union of all active
                               role grants)
9. One mandatory resource-binding + scope gate for every candidate
   -> DENY SCOPE_DENIED on missing target, mismatch, or missing scope
10. Default deny            -> DENY NO_GRANT

Fail-closed: the whole resolver sits inside one exception boundary.
Expected denials keep their reason; any unexpected database/cache/resolver
error returns DENY FAIL_CLOSED and is logged. No exception can escape as
an ALLOW, and there is no default-allow path anywhere.

Known R1 limitations (documented, fail-closed, tested):
- ``account_locked`` is a no-op until the W0-2D lockout store exists; the
  ACCOUNT_LOCKED branch and its position BEFORE the GM step are pinned by
  tests using that seam.
- ``AuthContext.requires_mfa`` is False for every caller in R1 because MFA
  does not exist yet (W0-2C). The MFA_REQUIRED branch is implemented now
  and pinned by tests, so BasicAuthentication can never satisfy an
  MFA-protected operation later (§6, R27).
- Per-operation resource binding is SERVER-OWNED operation metadata,
  independent of the permission's scope_policy (§16.1 step 9, §16.2).
  The legacy R1 key-only entry point uses the shipped binding registry and
  its register_operation_binding seam. The R2 API entry point obtains
  immutable per-method declarations from security.operation_registry:
  OperationSpec states COLLECTION or OBJECT, permission key, target kind,
  and server-owned target source. resolve_operation() converts that
  declaration into the shared resolver's binding override; this allows
  collection and object methods to share a permission key without sharing
  a target rule.
  The shipped R1 registry still declares the ten WAREHOUSE_REQUIRED keys
  and two OBJECT_REQUIRED self-user keys. scope_policy=NONE means no
  warehouse/object authorization restriction — it NEVER waives target
  resolution or validation for a target-bound operation (§15A). Missing
  operation declarations fail closed; a collection exists only when
  explicitly declared as COLLECTION.
- Target resolution always re-resolves from persisted rows (fresh fetch
  by pk plus any declared required parents): unsaved instances,
  fabricated pks, deleted rows, wrong types, and unresolvable required
  parents are denied. Client-supplied identifiers/booleans are never
  authority (§16.1 step 9).
- Scope ``allows`` evaluation reads the M6 registry for WAREHOUSE_REQUIRED
  and self-scope equality for OBJECT_REQUIRED. Broader ScopeContext
  machinery arrives with W0-2B+ (§14.9).
"""
import logging

from dataclasses import dataclass, field
from typing import Optional

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from security.gm_slot import GM_SLOT_CODE, load_singleton_slot
from security.models import (
    OverrideEffect,
    Permission,
    RolePermission,
    UserPermissionOverride,
    UserRoleAssignment,
    UserWarehouseScope,
)
from security.permissions_catalog import CATALOG_BY_KEY

logger = logging.getLogger("security.authorization")

GM_ROLE_CODE = "GM"

# Allow reasons (§16.2)
ALLOW_GM_PROTECTED = "GM_PROTECTED"
ALLOW_USER_ALLOW = "USER_ALLOW"
ALLOW_ROLE_GRANT = "ROLE_GRANT"

# Deny reasons (§16.2)
DENY_UNAUTHENTICATED = "UNAUTHENTICATED"
DENY_INACTIVE_ACCOUNT = "INACTIVE_ACCOUNT"
DENY_ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
DENY_NO_ACTIVE_SESSION = "NO_ACTIVE_SESSION"
DENY_MFA_REQUIRED = "MFA_REQUIRED"
DENY_UNKNOWN_PERMISSION = "UNKNOWN_PERMISSION"
DENY_USER_DENY = "USER_DENY"
DENY_NO_GRANT = "NO_GRANT"
DENY_SCOPE_DENIED = "SCOPE_DENIED"
DENY_FAIL_CLOSED = "FAIL_CLOSED"

# Target kinds for the R1 resource-binding registry (§16.1 step 9).
BINDING_TARGET_WAREHOUSE = "WAREHOUSE"
BINDING_TARGET_SELF_USER = "SELF_USER"
BINDING_TARGET_FISCAL_PERIOD = "FISCAL_PERIOD"
BINDING_TARGET_LANDED_COST_DOCUMENT = "LANDED_COST_DOCUMENT"

# Binding status vocabulary (server-owned operation metadata).
BINDING_STATUS_DECLARED = "DECLARED"
BINDING_STATUS_UNDECLARED = "UNDECLARED_W0_2B"  # owning API batch must declare


@dataclass(frozen=True)
class TargetReference:
    """Server-created reference to a persisted object; never built from client model metadata."""

    target_kind: str
    pk: object


@dataclass(frozen=True)
class PermissionDecision:
    """Explicit, explainable resolver result (§9A Item 2 diagnostic trace)."""

    allowed: bool
    reason: str
    source: Optional[str] = None
    trace: tuple = field(default_factory=tuple)

    def __str__(self):
        return f"{'ALLOW' if self.allowed else 'DENY'}:{self.reason}"


@dataclass(frozen=True)
class AuthContext:
    """Trusted server-side authentication/session evidence (§16.1 step 3).

    Constructed ONLY from server-side evidence — never from
    caller-supplied booleans or request fields. ``from_request`` builds it
    from a Django/DRF request using the server session store and DRF's
    successful authenticator.

    Session validity semantics in R1:
    - A trusted server-side Django session bound to the user is valid until
      its expiry (binding/revocation validation arrives with W0-2D).
    - A BasicAuthentication-only context carries NO session evidence. Under
      the frozen Batch 2/3 authentication contract, Basic remains a valid
      authentication path until W0-2C introduces MFA; the fail-closed
      MFA gate (``is_basic_only and requires_mfa``) is what will deny
      Basic-only access to MFA-protected operations (R27). It must never
      be set to True by callers in R1.
    - Any context with neither session evidence nor a recognized
      mechanism fails closed (NO_ACTIVE_SESSION).
    """

    is_basic_only: bool = False
    requires_mfa: bool = False
    mfa_verified: bool = False
    session_user_id: Optional[int] = None
    session_expiry: Optional[object] = None

    def is_valid_for(self, user, at) -> bool:
        if self.session_user_id is not None:
            if self.session_user_id != user.pk:
                return False
            if self.session_expiry is not None and self.session_expiry <= at:
                return False
            return True
        if self.is_basic_only:
            return True
        return False

    @classmethod
    def from_request(cls, request) -> "AuthContext":
        """Derive context only from authenticated server-side evidence.

        Django session cookies are insufficient by themselves: a live,
        user-bound W0-2C registry row is required. BasicAuthentication remains
        a temporary compatibility path for non-GM operations, but can never
        satisfy the mandatory GM MFA gate.
        """
        from rest_framework.authentication import BasicAuthentication

        user = getattr(request, "user", None)
        session = getattr(request, "session", None)
        authenticated = bool(user is not None and getattr(user, "is_authenticated", False))
        at = timezone.now()
        is_basic_only = isinstance(
            getattr(request, "successful_authenticator", None), BasicAuthentication
        )

        requires_mfa = False
        mfa_verified = False
        session_user_id = None
        session_expiry = None

        if authenticated:
            # Only the active assignment linked to the singleton GM slot is
            # treated as the GM identity. Staff/superuser flags and unlinked
            # GM assignments cannot activate this requirement.
            assignment_id = _singleton_gm_assignment_id(user)
            requires_mfa = bool(
                assignment_id is not None
                and _linked_gm_assignment_is_active(user, assignment_id, at)
            )

            if session is not None:
                raw_id = session.get("_auth_user_id")
                session_key = getattr(session, "session_key", None)
                if raw_id is not None and str(raw_id) == str(user.pk) and session_key:
                    from security.session_service import touch_login_session

                    record = touch_login_session(user, session_key, at=at)
                    if record is not None:
                        session_user_id = user.pk
                        session_expiry = min(
                            record.idle_expires_at, record.absolute_expires_at
                        )
                        mfa_verified = record.mfa_verified_at is not None

        return cls(
            is_basic_only=is_basic_only,
            requires_mfa=requires_mfa,
            mfa_verified=mfa_verified,
            session_user_id=session_user_id,
            session_expiry=session_expiry,
        )


def account_locked(user, at) -> bool:
    """Account-lockout predicate — NO-OP until W0-2D ships its store.

    The ACCOUNT_LOCKED deny reason and its position BEFORE the protected-GM
    step are binding (§16.1 steps 2 and 5; test R14). W0-2D implements the
    real store and keeps this seam.
    """
    return False


@dataclass(frozen=True)
class _ResourceBinding:
    """Server-owned per-operation resource-binding metadata (§16.1 step 9).

    Defined per OPERATION, independently of the permission's
    ``scope_policy``: a NONE-policy operation may be target-bound (the
    gate then validates the target), and a target-bound declaration never
    implies any warehouse/object authorization restriction — scope is
    applied only according to the registered scope policy.
    """

    is_target_bound: bool
    target_kind: Optional[str] = None
    binding_status: str = BINDING_STATUS_DECLARED
    required_parent_paths: tuple = ()


# ----------------------------------------------------------------------
# Server-owned operation resource-binding registry (§16.1 step 9).
#
# Shipped R1 entries: exactly the architecture-unambiguous bindings.
# The WAREHOUSE_REQUIRED inventory keys operate on a specific persisted
# ``warehouses.Warehouse`` (scope basis: the M6 registry, §15A), and the
# two OBJECT_REQUIRED self-scope keys operate on the persisted target
# user. ``warehouses.Warehouse`` is a flat master with no FK relations
# (verified §15A), so no required parent paths apply to it.
#
# Every NONE key is deliberately NOT declared here: the approved §15A
# ``resolver_context`` column defers each NONE operation's executable
# target binding to the owning API batch (W0-2B). Undeclared is NOT
# "collection": it is an explicit UNDECLARED status, and the owning
# batch MUST declare target-bound operations through
# ``register_operation_binding`` before wiring them. The resolver gate
# fully supports target-bound NONE declarations (pinned by the resource
# binding contract tests).
# ----------------------------------------------------------------------
_OPERATION_RESOURCE_BINDINGS = {
    "inventory.adjustment.create": _ResourceBinding(
        is_target_bound=True, target_kind=BINDING_TARGET_WAREHOUSE
    ),
    "inventory.adjustment.export": _ResourceBinding(
        is_target_bound=True, target_kind=BINDING_TARGET_WAREHOUSE
    ),
    "inventory.adjustment.post": _ResourceBinding(
        is_target_bound=True, target_kind=BINDING_TARGET_WAREHOUSE
    ),
    "inventory.adjustment.view": _ResourceBinding(
        is_target_bound=True, target_kind=BINDING_TARGET_WAREHOUSE
    ),
    "inventory.count.create": _ResourceBinding(
        is_target_bound=True, target_kind=BINDING_TARGET_WAREHOUSE
    ),
    "inventory.count.export": _ResourceBinding(
        is_target_bound=True, target_kind=BINDING_TARGET_WAREHOUSE
    ),
    "inventory.count.view": _ResourceBinding(
        is_target_bound=True, target_kind=BINDING_TARGET_WAREHOUSE
    ),
    "inventory.movement.create": _ResourceBinding(
        is_target_bound=True, target_kind=BINDING_TARGET_WAREHOUSE
    ),
    "inventory.movement.export": _ResourceBinding(
        is_target_bound=True, target_kind=BINDING_TARGET_WAREHOUSE
    ),
    "inventory.movement.view": _ResourceBinding(
        is_target_bound=True, target_kind=BINDING_TARGET_WAREHOUSE
    ),
    "security.account.view_own": _ResourceBinding(
        is_target_bound=True, target_kind=BINDING_TARGET_SELF_USER
    ),
    "security.mfa.enroll_own": _ResourceBinding(
        is_target_bound=True, target_kind=BINDING_TARGET_SELF_USER
    ),
}

_BINDING_STATUS_UNDECLARED = _ResourceBinding(
    is_target_bound=False,
    target_kind=None,
    binding_status=BINDING_STATUS_UNDECLARED,
)

_BINDING_TARGET_MODELS = {
    BINDING_TARGET_WAREHOUSE: "warehouses.models.Warehouse",
    BINDING_TARGET_SELF_USER: "django.contrib.auth User",
}


def _binding_target_model(kind):
    """Resolve a declared target kind to its persisted model class.

    The two shipped kinds resolve lazily (import-cycle safety, app
    registry readiness); seam-registered kinds store their model class
    directly.
    """
    if kind == BINDING_TARGET_WAREHOUSE:
        from warehouses.models import Warehouse

        return Warehouse
    if kind == BINDING_TARGET_SELF_USER:
        from django.contrib.auth import get_user_model

        return get_user_model()
    if kind == BINDING_TARGET_FISCAL_PERIOD:
        from fiscal_periods.models import FiscalPeriod

        return FiscalPeriod
    if kind == BINDING_TARGET_LANDED_COST_DOCUMENT:
        from purchases.models import LandedCostDocument

        return LandedCostDocument
    model = _BINDING_TARGET_MODELS.get(kind)
    if model is None:
        raise LookupError(kind)
    return model


def register_binding_target_kind(kind, model):
    """Server-owned extension seam: declare a persisted target kind.

    The owning API batch (W0-2B) registers its document/pk kinds here
    before declaring target-bound operations that use them. ``model`` is
    the persisted model class the kind resolves to.
    """
    if kind in _BINDING_TARGET_MODELS:
        raise ValueError(f"binding target kind already declared: {kind}")
    _BINDING_TARGET_MODELS[kind] = model


def unregister_binding_target_kind(kind):
    """Remove a seam-registered target kind (test isolation / rewiring)."""
    if kind in (BINDING_TARGET_WAREHOUSE, BINDING_TARGET_SELF_USER):
        raise ValueError("shipped target kinds cannot be unregistered")
    _BINDING_TARGET_MODELS.pop(kind, None)


def register_operation_binding(permission_key, binding):
    """Server-owned extension seam (§16.1 step 9, §16.2).

    The owning API batch declares each wired operation's resource binding
    here — explicitly, per operation, never inferred from scope_policy.
    Unknown catalog keys are rejected (fail loud at declaration time).
    """
    if permission_key not in CATALOG_BY_KEY:
        raise ValueError(f"operation not in approved catalog: {permission_key}")
    if not isinstance(binding, _ResourceBinding):
        raise TypeError("binding must be a _ResourceBinding")
    if binding.is_target_bound and binding.target_kind not in _BINDING_TARGET_MODELS:
        raise ValueError(f"undeclared binding target kind: {binding.target_kind}")
    _OPERATION_RESOURCE_BINDINGS[permission_key] = binding


def unregister_operation_binding(permission_key):
    """Remove a seam-registered operation binding (test isolation)."""
    _OPERATION_RESOURCE_BINDINGS.pop(permission_key, None)


def _validate_operation_bindings_against_catalog():
    """Fail loud on drift between the binding registry and the catalog.

    Two directions: every shipped binding must reference an existing
    catalog key whose registered scope policy matches the binding's
    implied policy, and EVERY WAREHOUSE_REQUIRED / OBJECT_REQUIRED
    catalog key must carry a declared target binding (their binding is
    architecture-unambiguous, §15A classification framework).
    """
    for key, binding in _OPERATION_RESOURCE_BINDINGS.items():
        entry = CATALOG_BY_KEY.get(key)
        if entry is None:
            raise RuntimeError(
                f"operation binding references unknown catalog key: {key}"
            )
        policy = entry["scope_policy"]
        if binding.target_kind == BINDING_TARGET_WAREHOUSE and policy != "WAREHOUSE_REQUIRED":
            raise RuntimeError(f"binding/policy drift for {key}: {policy}")
        if binding.target_kind == BINDING_TARGET_SELF_USER and policy != "OBJECT_REQUIRED":
            raise RuntimeError(f"binding/policy drift for {key}: {policy}")
    for key, entry in CATALOG_BY_KEY.items():
        policy = entry["scope_policy"]
        if policy in ("WAREHOUSE_REQUIRED", "OBJECT_REQUIRED"):
            binding = _OPERATION_RESOURCE_BINDINGS.get(key)
            if binding is None or not binding.is_target_bound:
                raise RuntimeError(
                    f"missing required target binding for {policy} key: {key}"
                )


_validate_operation_bindings_against_catalog()


def _server_defined_resource_binding(permission_key):
    """Server-owned per-operation binding contract (§16.1 step 9, §16.2).

    A function of the operation's key ONLY — never of scope_policy.
    Undeclared keys return the UNDECLARED sentinel. The resolver must
    reject that status; non-target-bound means collection ONLY when an
    operation was explicitly registered as such.
    """
    return _OPERATION_RESOURCE_BINDINGS.get(permission_key, _BINDING_STATUS_UNDECLARED)


@dataclass(frozen=True)
class _TrustedScope:
    kind: str
    warehouse: Optional[object] = None
    user: Optional[object] = None

    def is_consistent_with(self, resource) -> bool:
        """Consistency check for scope_policy=NONE operations (defensive)."""
        return True


def _resolve_persisted_target(binding, resource):
    """Resolve and validate the target from PERSISTED rows (§16.1 step 9).

    The passed ``resource`` is only a server-side seam carrying the target
    identity: the resolver re-fetches the row (and any declared required
    parents) fresh from the database, so unsaved instances, fabricated
    pks, deleted rows, wrong types, and unresolvable required parents are
    all invalid. Client-supplied identifiers/booleans are never authority.
    Returns the persisted instance, or None when the target chain does
    not resolve (the gate then denies with SCOPE_DENIED).
    """
    if resource is None:
        return None
    try:
        model = _binding_target_model(binding.target_kind)
    except LookupError:
        return None
    if not isinstance(resource, model) or resource.pk is None:
        return None
    manager = model._default_manager
    if binding.required_parent_paths:
        manager = manager.select_related(*binding.required_parent_paths)
    try:
        persisted = manager.get(pk=resource.pk)
    except ObjectDoesNotExist:
        # A genuinely missing target is an expected binding denial.
        return None
    for parent_path in binding.required_parent_paths:
        attr = persisted
        try:
            for part in parent_path.split("__"):
                attr = getattr(attr, part)
                if attr is None:
                    return None
        except ObjectDoesNotExist:
            # A declared required relation exists in the model contract but
            # has no persisted related row.
            return None
    return persisted


def _derive_trusted_scope(resolved_target, scope_policy):
    """Derive trusted scope ONLY from persisted server-side facts."""
    if resolved_target is None:
        return None
    if scope_policy == "WAREHOUSE_REQUIRED":
        return _TrustedScope(kind="warehouse", warehouse=resolved_target)
    if scope_policy == "OBJECT_REQUIRED":
        return _TrustedScope(kind="self", user=resolved_target)
    return None


def _scope_allows(user, trusted_scope, at) -> bool:
    """Evaluate the trusted scope against persisted assignment registries."""
    if trusted_scope.kind == "warehouse":
        return UserWarehouseScope.objects.filter(
            user=user,
            warehouse=trusted_scope.warehouse,
            revoked_at__isnull=True,
            start_at__lte=at,
        ).filter(
            _active_window_q(UserWarehouseScope, at)
        ).exists()
    if trusted_scope.kind == "self":
        return trusted_scope.user.pk == user.pk
    return False


def _active_window_q(model, at):
    from django.db.models import Q

    return Q(end_at__isnull=True) | Q(end_at__gt=at)


def _singleton_gm_assignment_id(user) -> Optional[int]:
    """Identity of the single GM holder's assignment, when it is this user's.

    W0-2B owner decision (additive): at most ONE user may hold the active
    GM role in the entire ERP at any time. The singleton ``GMRoleSlot`` row
    is the authoritative identity of that one holder; the resolver
    recognizes GM ONLY through it.

    Fail-closed to ``None`` (not GM) for: a missing or malformed slot row,
    the valid empty slot (no GM provisioned yet), a slot held by another
    user, and a slot linking a missing/wrong/inactive-role assignment.
    Database errors propagate to the resolver's fail-closed boundary —
    they can never read as "not GM silently": the outer except converts
    them into DENY FAIL_CLOSED.
    """
    slot = load_singleton_slot()
    if slot is None:
        logger.error(
            "GM singleton slot row is missing or unreadable; GM authority "
            "is disabled"
        )
        return None
    assignment = slot.assignment
    if assignment is None:
        # Valid pre-provisioning / controlled-recovery state: no GM exists.
        return None
    if assignment.user_id != user.pk:
        return None
    role = getattr(assignment, "role", None)
    if role is None or role.code != GM_ROLE_CODE or not role.is_active:
        logger.error(
            "GM singleton slot links a malformed or non-GM assignment; "
            "GM authority is denied"
        )
        return None
    return assignment.pk


def _linked_gm_assignment_is_active(user, assignment_id, at) -> bool:
    """ACTIVE predicate (§14.2) evaluated on the SLOT-LINKED row only.

    Deliberately pinned to the linked assignment's pk: another live GM
    assignment of the same user (an unlinked row) must never satisfy the
    predicate, and the (user, role) live-slot uniqueness makes the linked
    row the user's only possible live GM assignment anyway.
    """
    return UserRoleAssignment.objects.filter(
        pk=assignment_id,
        user=user,
        role__code=GM_ROLE_CODE,
        role__is_active=True,
        revoked_at__isnull=True,
        start_at__lte=at,
    ).filter(
        _active_window_q(UserRoleAssignment, at)
    ).exists()


def _live_overrides(user, permission, at):
    """Non-closed override rows for the slot, DENY rows first (R15)."""
    base = UserPermissionOverride.objects.filter(
        user=user,
        permission=permission,
        revoked_at__isnull=True,
        start_at__lte=at,
    ).filter(_active_window_q(UserPermissionOverride, at))
    return base


def _union_of_active_role_permission_keys(user, at, *, include_gm=False):
    """Union of permission keys across all ACTIVE role grants (§14.5).

    W0-2B singleton-GM: the GM role's keys are granted ONLY through the
    singleton slot. The GM role is therefore excluded from the ordinary
    assignment join (an unlinked ``UserRoleAssignment(role=GM)`` grants no
    GM permission keys) and ``_gm_capability_keys()`` is unioned only when
    the caller proved the caller user holds the slot-linked ACTIVE GM
    assignment. Non-GM role evaluation is unchanged.
    """
    from django.db.models import Q

    keys = set(
        RolePermission.objects.filter(
            role__is_active=True,
            permission__is_active=True,
            role__user_assignments__user=user,
            role__user_assignments__revoked_at__isnull=True,
            role__user_assignments__start_at__lte=at,
        ).filter(
            Q(role__user_assignments__end_at__isnull=True)
            | Q(role__user_assignments__end_at__gt=at)
        ).exclude(role__code=GM_SLOT_CODE)
        .values_list("permission__key", flat=True)
    )
    if include_gm:
        keys |= _gm_capability_keys()
    return keys


def _gm_capability_keys():
    """The protected GM capability set: keys granted to the GM role (§15.1).

    Read from the database (seeded by 0003 to exactly the
    ENDPOINT/SERVICE/MATRIX set and asserted by the drift check), never
    hardcoded, so catalog administration remains single-sourced.
    """
    return set(
        RolePermission.objects.filter(
            role__code=GM_ROLE_CODE,
            role__is_active=True,
            permission__is_active=True,
        ).values_list("permission__key", flat=True)
    )


def resolve(user, permission_key, *, auth_context, resource=None, at=None) -> PermissionDecision:
    """Legacy R1 key-only resolver. Its protected-GM sequence is intentionally unchanged."""
    return _resolve(
        user, permission_key, auth_context=auth_context,
        resource=resource, at=at,
    )


def resolve_operation(user, operation, *, auth_context, target_reference=None, at=None) -> PermissionDecision:
    """Resolve an R2 view+method operation through the shared R1 policy core.

    Operation metadata is server-owned. R2 binds the permission decision to
    the declared target kind and validates target existence/type before a
    protected-GM allow. The legacy key-only R1 entry point is unchanged.
    """
    binding_kind = getattr(operation, "binding_kind", None)
    if binding_kind not in ("COLLECTION", "OBJECT"):
        return PermissionDecision(False, DENY_SCOPE_DENIED, None, ("operation:invalid-binding",))
    target_kind = getattr(operation, "target_kind", None)
    if binding_kind == "OBJECT" and not target_kind:
        return PermissionDecision(False, DENY_SCOPE_DENIED, None, ("operation:missing-target-kind",))
    if binding_kind == "COLLECTION" and target_kind is not None:
        return PermissionDecision(False, DENY_SCOPE_DENIED, None, ("operation:collection-target-kind",))
    binding = _ResourceBinding(
        is_target_bound=(binding_kind == "OBJECT"),
        target_kind=target_kind,
    )
    return _resolve(
        user,
        getattr(operation, "permission_key", None),
        auth_context=auth_context,
        at=at,
        binding_override=binding,
        target_reference=target_reference,
        operation_aware=True,
    )


def _resolve_persisted_target_reference(binding, target_reference):
    """Resolve a typed R2 target using only the operation's server-declared model kind."""
    if not isinstance(target_reference, TargetReference):
        return None
    if target_reference.target_kind != binding.target_kind or target_reference.pk is None:
        return None
    if isinstance(target_reference.pk, bool) or not isinstance(target_reference.pk, (int, str)):
        return None
    if isinstance(target_reference.pk, str) and not target_reference.pk.strip():
        return None
    try:
        model = _binding_target_model(binding.target_kind)
    except LookupError:
        return None
    try:
        persisted = model._default_manager.get(pk=target_reference.pk)
    except ObjectDoesNotExist:
        return None
    for parent_path in binding.required_parent_paths:
        attr = persisted
        try:
            for part in parent_path.split("__"):
                attr = getattr(attr, part)
                if attr is None:
                    return None
        except ObjectDoesNotExist:
            return None
    return persisted


def _resolve(
    user,
    permission_key,
    *,
    auth_context,
    resource=None,
    at=None,
    binding_override=None,
    target_reference=None,
    operation_aware=False,
) -> PermissionDecision:
    """Shared authorization policy core for legacy R1 and operation-aware R2."""
    at = at or timezone.now()
    trace = []
    try:
        # Step 1 — authentication. Nothing is persisted for anonymous
        # callers (frozen Batch 3 no-persist pin) and no permission-grant
        # lookup has happened yet (R16 order proof).
        if user is None or not getattr(user, "is_authenticated", False):
            trace.append("1:UNAUTHENTICATED")
            return PermissionDecision(False, DENY_UNAUTHENTICATED, None, tuple(trace))

        # Step 2 — account state.
        if not user.is_active:
            trace.append("2:INACTIVE_ACCOUNT")
            return PermissionDecision(False, DENY_INACTIVE_ACCOUNT, None, tuple(trace))
        if account_locked(user, at):
            trace.append("2:ACCOUNT_LOCKED")
            return PermissionDecision(False, DENY_ACCOUNT_LOCKED, None, tuple(trace))

        # Step 3 — trusted server-side session validity.
        if auth_context is None or not auth_context.is_valid_for(user, at):
            trace.append("3:NO_ACTIVE_SESSION")
            return PermissionDecision(False, DENY_NO_ACTIVE_SESSION, None, tuple(trace))
        if getattr(auth_context, "requires_mfa", False) and not getattr(
            auth_context, "mfa_verified", False
        ):
            trace.append("3:MFA_REQUIRED")
            return PermissionDecision(False, DENY_MFA_REQUIRED, None, tuple(trace))

        # Step 4 — permission-key resolution (first catalog touch).
        permission = Permission.objects.filter(
            key=permission_key, is_active=True
        ).first()
        if permission is None:
            trace.append("4:UNKNOWN_PERMISSION")
            logger.warning(
                "resolver denied unknown/inactive permission key",
                extra={"permission_key": str(permission_key)},
            )
            return PermissionDecision(False, DENY_UNKNOWN_PERMISSION, None, tuple(trace))

        # Step 5 — protected GM authority (overrides never consulted).
        # W0-2B singleton: identity comes from the GMRoleSlot row; the
        # ACTIVE predicate is evaluated on the slot-LINKED assignment only.
        gm_slot_assignment_id = _singleton_gm_assignment_id(user)
        gm_is_linked_and_active = (
            gm_slot_assignment_id is not None
            and _linked_gm_assignment_is_active(user, gm_slot_assignment_id, at)
        )
        if gm_is_linked_and_active and permission.key in _gm_capability_keys():
            if operation_aware:
                # R2 API operations validate server-declared target identity
                # before GM authority. This is deliberately not applied to
                # the frozen legacy R1 key-only resolver.
                if binding_override is None:
                    trace.append("5:SCOPE_DENIED:operation-binding-missing")
                    return PermissionDecision(False, DENY_SCOPE_DENIED, None, tuple(trace))
                if binding_override.is_target_bound:
                    gm_target = _resolve_persisted_target_reference(
                        binding_override, target_reference
                    )
                    if gm_target is None:
                        trace.append("5:SCOPE_DENIED:target-resolution")
                        return PermissionDecision(False, DENY_SCOPE_DENIED, None, tuple(trace))
                elif target_reference is not None:
                    trace.append("5:SCOPE_DENIED:collection-has-target")
                    return PermissionDecision(False, DENY_SCOPE_DENIED, None, tuple(trace))
            trace.append("5:GM_PROTECTED")
            return PermissionDecision(True, ALLOW_GM_PROTECTED, "GM", tuple(trace))

        # Step 6 — explicit user DENY wins over every candidate below
        # (defensive deny-wins: a live DENY is checked before any ALLOW so
        # a tampered ALLOW+DENY pair still denies, test R15).
        active_overrides = _live_overrides(user, permission, at)
        if active_overrides.filter(effect=OverrideEffect.DENY).exists():
            trace.append("6:USER_DENY")
            return PermissionDecision(False, DENY_USER_DENY, None, tuple(trace))

        # Steps 7/8 — discover BOTH candidate sources before the shared
        # scope gate. Neither becomes an ALLOW result here.
        user_allow = active_overrides.filter(effect=OverrideEffect.ALLOW).exists()
        role_grant_keys = _union_of_active_role_permission_keys(
            user, at, include_gm=gm_is_linked_and_active
        )
        role_grant = permission.key in role_grant_keys
        if not (user_allow or role_grant):
            trace.append("10:NO_GRANT")
            return PermissionDecision(False, DENY_NO_GRANT, None, tuple(trace))
        trace.append("7/8:candidates:" + ("USER_ALLOW" if user_allow else "") + (
            "+ROLE_GRANT" if role_grant and user_allow else ("ROLE_GRANT" if role_grant else "")
        ))

        # Step 9 — ONE mandatory resource-binding + scope gate for every
        # candidate grant. Registry metadata is server-owned; missing or
        # unknown metadata fails closed.
        entry = CATALOG_BY_KEY.get(permission.key)
        scope_policy = entry["scope_policy"] if entry else None
        if scope_policy not in ("NONE", "WAREHOUSE_REQUIRED", "OBJECT_REQUIRED"):
            trace.append("9:SCOPE_DENIED:no-registry-metadata")
            return PermissionDecision(False, DENY_SCOPE_DENIED, None, tuple(trace))

        binding = (
            binding_override
            if operation_aware
            else _server_defined_resource_binding(permission.key)
        )
        if binding is None or binding.binding_status != BINDING_STATUS_DECLARED:
            # UNDECLARED is a contract/configuration failure, NOT a
            # collection declaration. Fail closed for every candidate
            # grant, including explicit user ALLOW.
            trace.append("9:SCOPE_DENIED:binding-undeclared")
            return PermissionDecision(False, DENY_SCOPE_DENIED, None, tuple(trace))

        if binding.is_target_bound:
            # Target validation runs REGARDLESS of the key's scope_policy.
            # R2 resolves typed references through the operation's model kind;
            # R1 continues to pass a server-side model instance.
            resolved_target = (
                _resolve_persisted_target_reference(binding, target_reference)
                if operation_aware
                else _resolve_persisted_target(binding, resource)
            )
            if resolved_target is None:
                trace.append("9:SCOPE_DENIED:target-resolution")
                return PermissionDecision(False, DENY_SCOPE_DENIED, None, tuple(trace))
        else:
            # A collection binding is explicit; it cannot be supplied a target.
            if operation_aware and target_reference is not None:
                trace.append("9:SCOPE_DENIED:collection-has-target")
                return PermissionDecision(False, DENY_SCOPE_DENIED, None, tuple(trace))
            resolved_target = None

        trusted_scope = _derive_trusted_scope(resolved_target, scope_policy)
        if scope_policy != "NONE":
            if trusted_scope is None or not _scope_allows(user, trusted_scope, at):
                trace.append("9:SCOPE_DENIED:scope-evaluation")
                return PermissionDecision(False, DENY_SCOPE_DENIED, None, tuple(trace))
        elif trusted_scope is not None and not trusted_scope.is_consistent_with(
            resolved_target
        ):
            trace.append("9:SCOPE_DENIED:consistency")
            return PermissionDecision(False, DENY_SCOPE_DENIED, None, tuple(trace))

        # Step 10 — grants after the gate; explicit ALLOW selected over a
        # role grant when both exist.
        if user_allow:
            trace.append("10:USER_ALLOW")
            return PermissionDecision(True, ALLOW_USER_ALLOW, "USER", tuple(trace))
        trace.append("10:ROLE_GRANT")
        return PermissionDecision(True, ALLOW_ROLE_GRANT, "ROLE", tuple(trace))

    except Exception:
        # Fail-closed boundary (§16.1 step 4): expected denials keep their
        # reasons above; everything unexpected lands here with a logged
        # diagnostic and a deny. Never an ALLOW, never a raised exception.
        logger.error(
            "authorization resolver failed closed",
            exc_info=True,
            extra={
                "permission_key": str(permission_key),
                "user_id": getattr(user, "pk", None),
            },
        )
        trace.append("exception:FAIL_CLOSED")
        return PermissionDecision(False, DENY_FAIL_CLOSED, None, tuple(trace))
