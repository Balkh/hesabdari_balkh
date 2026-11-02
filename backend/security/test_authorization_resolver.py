"""W0-2A / R1 — dormant resolver tests (Checkpoint C).

Pins the §16.1 binding sequence, §16.3/§16.4 cases R14–R27 (R26 deferred to
the W0-2C AdminSite gate — R1 must NOT implement Admin enforcement), and
the Item 2 owner-approved semantics (deny precedence, candidate discovery
before one shared scope gate, protected GM, union across roles, fail-closed
error handling, zero catalog queries for anonymous callers).
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from security import authorization
from security.authorization import (
    AuthContext,
    PermissionDecision,
    resolve,
)
from security.models import (
    OverrideEffect,
    Permission,
    Role,
    RolePermission,
    UserPermissionOverride,
    UserRoleAssignment,
    UserWarehouseScope,
)
from warehouses.models import Warehouse

User = get_user_model()


def grant_role(user, code):
    role, _ = Role.objects.get_or_create(code=code, defaults={"name": code})
    return UserRoleAssignment.objects.create(user=user, role=role)


def link(role_code, key):
    role = Role.objects.get(code=role_code)
    permission = Permission.objects.get(key=key)
    # get_or_create: the migrated test DB already carries the canonical
    # 0003 seed links; tests only ensure the link exists.
    obj, _created = RolePermission.objects.get_or_create(
        role=role, permission=permission
    )
    return obj


def allow_override(user, key, **overrides):
    fields = {
        "user": user,
        "permission": Permission.objects.get(key=key),
        "effect": OverrideEffect.ALLOW,
    }
    fields.update(overrides)
    return UserPermissionOverride.objects.create(**fields)


def deny_override(user, key, **overrides):
    fields = {
        "user": user,
        "permission": Permission.objects.get(key=key),
        "effect": OverrideEffect.DENY,
    }
    fields.update(overrides)
    return UserPermissionOverride.objects.create(**fields)


class _FakeOverrideRows:
    """Minimal list surface emulating the resolver's override queries."""

    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, **kwargs):
        effect = kwargs.get("effect")
        return _FakeOverrideRows(
            [r for r in self.rows if effect is None or r.effect == effect]
        )

    def exists(self):
        return bool(self.rows)


class ResolverTestBase(TestCase):
    def setUp(self):
        self.now = timezone.now()  # reference point for window offsets only
        self.session_ctx = AuthContext(session_user_id=None, is_basic_only=False)
        self.basic_ctx = AuthContext(is_basic_only=True)
        self.user = None

    def ctx_for(self, user, basic=False, requires_mfa=False):
        return AuthContext(
            is_basic_only=basic,
            requires_mfa=requires_mfa,
            session_user_id=None if basic else user.pk,
            session_expiry=None,
        )

    def resolve(self, user, key, resource=None, ctx=None, at=None):
        # at=None lets resolve() use timezone.now(); window fixtures below
        # are always expressed as offsets from timezone.now() so row
        # defaults (start_at=now) are covered by the ACTIVE predicate.
        return resolve(
            user,
            key,
            auth_context=ctx if ctx is not None else self.ctx_for(user),
            resource=resource,
            at=at,
        )


class AuthenticationAndAccountStateTests(ResolverTestBase):
    def _at(self):
        return timezone.now()

    def test_r1_unauthenticated_denied_without_queries(self):
        with self.assertNumQueries(0):
            decision = resolve(
                AnonymousUser(),
                "fiscal.period.view",
                auth_context=self.basic_ctx,
                at=self._at(),
            )
        self.assertEqual(decision.reason, "UNAUTHENTICATED")
        self.assertFalse(decision.allowed)

    def test_none_user_denied_without_queries(self):
        with self.assertNumQueries(0):
            decision = resolve(
                None,
                "fiscal.period.view",
                auth_context=self.basic_ctx,
                at=self._at(),
            )
        self.assertEqual(decision.reason, "UNAUTHENTICATED")

    def test_r18_unknown_key_with_anonymous_never_leaks_catalog(self):
        decision = resolve(
            AnonymousUser(),
            "no.such.key",
            auth_context=self.basic_ctx,
            at=self._at(),
        )
        self.assertEqual(decision.reason, "UNAUTHENTICATED")

    def test_r2_inactive_account_denied(self):
        user = User.objects.create_user(username="inactive")
        user.is_active = False
        user.save(update_fields=["is_active"])
        decision = self.resolve(user, "fiscal.period.view")
        self.assertEqual(decision.reason, "INACTIVE_ACCOUNT")

    def test_r14_locked_account_denied_before_gm_step(self):
        user = User.objects.create_user(username="locked-gm", is_superuser=False)
        grant_role(user, "GM")
        with patch.object(authorization, "account_locked", return_value=True):
            decision = self.resolve(user, "audit.report.view")
        self.assertEqual(decision.reason, "ACCOUNT_LOCKED")
        self.assertFalse(decision.allowed)

    def test_missing_session_evidence_fails_closed(self):
        user = User.objects.create_user(username="no-evidence")
        ctx = AuthContext()  # no session evidence, not basic-only
        decision = self.resolve(user, "fiscal.period.view", ctx=ctx)
        self.assertEqual(decision.reason, "NO_ACTIVE_SESSION")

    def test_session_bound_to_other_user_is_invalid(self):
        user = User.objects.create_user(username="session-user")
        ctx = AuthContext(session_user_id=user.pk + 999)
        decision = self.resolve(user, "fiscal.period.view", ctx=ctx)
        self.assertEqual(decision.reason, "NO_ACTIVE_SESSION")

    def test_expired_session_is_invalid(self):
        user = User.objects.create_user(username="expired-session")
        ctx = AuthContext(
            session_user_id=user.pk,
            session_expiry=self.now - timezone.timedelta(minutes=1),
        )
        decision = self.resolve(user, "fiscal.period.view", ctx=ctx)
        self.assertEqual(decision.reason, "NO_ACTIVE_SESSION")

    def test_valid_server_side_session_passes_step3(self):
        user = User.objects.create_user(username="session-ok")
        ctx = AuthContext(session_user_id=user.pk, session_expiry=None)
        decision = self.resolve(user, "fiscal.period.view", ctx=ctx)
        # No grant exists -> the resolver reaches default deny, which
        # proves steps 1-3 passed.
        self.assertEqual(decision.reason, "NO_GRANT")

    def test_r27_basic_only_on_mfa_protected_operation_denied(self):
        user = User.objects.create_user(username="basic-gm")
        grant_role(user, "GM")
        decision = self.resolve(
            user,
            "audit.report.view",
            ctx=AuthContext(is_basic_only=True, requires_mfa=True),
        )
        self.assertEqual(decision.reason, "MFA_REQUIRED")


class PermissionKeyResolutionTests(ResolverTestBase):
    def test_r18_unknown_key_with_authenticated_user(self):
        user = User.objects.create_user(username="key-user")
        with self.assertLogs("security.authorization", level="WARNING"):
            decision = self.resolve(user, "made.up.key")
        self.assertEqual(decision.reason, "UNKNOWN_PERMISSION")

    def test_inactive_permission_key_is_unknown(self):
        user = User.objects.create_user(username="inactive-key-user")
        permission = Permission.objects.get(key="fiscal.period.view")
        permission.is_active = False
        permission.save(update_fields=["is_active"])
        decision = self.resolve(user, "fiscal.period.view")
        self.assertEqual(decision.reason, "UNKNOWN_PERMISSION")
        # restore not needed: TestCase isolation

    def test_r16_zero_grant_queries_before_session_checks(self):
        """Structural order proof: anonymous callers trigger no queries."""
        # assertNumQueries(0) already proven in
        # AuthenticationAndAccountStateTests; this companion asserts the
        # known-key variant also cannot leak for anonymous callers.
        with self.assertNumQueries(0):
            resolve(
                AnonymousUser(),
                "inventory.movement.view",
                auth_context=self.basic_ctx,
                at=timezone.now(),
            )


class ProtectedGmAuthorityTests(ResolverTestBase):
    def test_gm_capability_key_allowed_without_scope(self):
        user = User.objects.create_user(username="gm-user")
        grant_role(user, "GM")
        decision = self.resolve(user, "inventory.movement.view")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "GM_PROTECTED")

    def test_gm_overrides_never_consulted(self):
        user = User.objects.create_user(username="gm-override")
        grant_role(user, "GM")
        deny_override(user, "audit.report.view")
        decision = self.resolve(user, "audit.report.view")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "GM_PROTECTED")

    def test_gm_key_not_in_capability_set_falls_through(self):
        """A GM without the specific grant (e.g. future RESERVED key) is
        not protected for it: falls through to candidate discovery."""
        user = User.objects.create_user(username="gm-limited")
        grant_role(user, "GM")
        # sales.document.approve is RESERVED -> granted to no one, not in
        # the GM capability set.
        decision = self.resolve(user, "sales.document.approve")
        self.assertEqual(decision.reason, "NO_GRANT")

    def test_inactive_gm_role_assignment_does_not_protect(self):
        user = User.objects.create_user(username="gm-inactive-role")
        assignment = grant_role(user, "GM")
        assignment.revoked_at = self.now
        assignment.revocation_kind = "MANUAL"
        assignment.save(update_fields=["revoked_at", "revocation_kind"])
        decision = self.resolve(user, "audit.report.view")
        self.assertEqual(decision.reason, "NO_GRANT")


class CandidateAndDenyPrecedenceTests(ResolverTestBase):
    def test_role_grant_allows(self):
        user = User.objects.create_user(username="acc-user")
        grant_role(user, "ACCOUNTANT")
        link("ACCOUNTANT", "fiscal.period.view")
        decision = self.resolve(user, "fiscal.period.view")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "ROLE_GRANT")

    def test_explicit_deny_beats_role_grant(self):
        user = User.objects.create_user(username="deny-role")
        grant_role(user, "ACCOUNTANT")
        link("ACCOUNTANT", "fiscal.period.view")
        deny_override(user, "fiscal.period.view")
        decision = self.resolve(user, "fiscal.period.view")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "USER_DENY")

    def test_live_allow_deny_pair_is_schema_impossible(self):
        """A live ALLOW+DENY pair cannot exist: M5 uniqueness is
        effect-independent (§14.4). The resolver's defensive deny-wins for
        a tampered pair is pinned by the R15 seam test below."""
        user = User.objects.create_user(username="pair-blocked")
        deny_override(user, "cash.cashaccount.view")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                allow_override(user, "cash.cashaccount.view")

    def test_r15_tampered_live_allow_deny_pair_denies(self):
        """§14.4 makes a live ALLOW+DENY pair unreachable through the API
        and schema; simulate the tampered state at the resolver seam to pin
        defensive deny-wins (R15)."""
        user = User.objects.create_user(username="tampered")
        allow_override(user, "cash.cashaccount.view")

        fabricated = _FakeOverrideRows([
            SimpleNamespace(effect=OverrideEffect.ALLOW),
            SimpleNamespace(effect=OverrideEffect.DENY),
        ])
        with patch.object(
            authorization, "_live_overrides", return_value=fabricated
        ):
            decision = self.resolve(user, "cash.cashaccount.view")
        self.assertEqual(decision.reason, "USER_DENY")

    def test_user_allow_grants_permission_absent_from_roles(self):
        user = User.objects.create_user(username="allow-only")
        allow_override(user, "cash.cashaccount.view")
        decision = self.resolve(user, "cash.cashaccount.view")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "USER_ALLOW")

    def test_multiple_roles_union(self):
        user = User.objects.create_user(username="union-user")
        grant_role(user, "ACCOUNTANT")
        grant_role(user, "WAREHOUSE_KEEPER")
        link("ACCOUNTANT", "parties.party.create")
        link("WAREHOUSE_KEEPER", "inventory.movement.view")
        assigned = Warehouse.objects.create(name="Union WH")
        UserWarehouseScope.objects.create(user=user, warehouse=assigned)
        decision = self.resolve(user, "parties.party.create")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "ROLE_GRANT")
        second = self.resolve(user, "inventory.movement.view", resource=assigned)
        self.assertTrue(second.allowed)
        self.assertEqual(second.reason, "ROLE_GRANT")

    def test_r17_expired_but_unsettled_assignment_never_grants(self):
        user = User.objects.create_user(username="expired-assignment")
        assignment = grant_role(user, "ACCOUNTANT")
        link("ACCOUNTANT", "fiscal.period.view")
        # Expire the bounded window in one UPDATE that satisfies the
        # end_at > start_at check constraint.
        UserRoleAssignment.objects.filter(pk=assignment.pk).update(
            start_at=self.now - timezone.timedelta(days=2),
            end_at=self.now - timezone.timedelta(days=1),
        )
        decision = self.resolve(user, "fiscal.period.view")
        self.assertEqual(decision.reason, "NO_GRANT")

    def test_r17_after_settlement_regrant_succeeds(self):
        """Simulated settlement (production service = W0-2B, §14.3): close
        the expired row, then a new live row grants again."""
        user = User.objects.create_user(username="settlement-user")
        assignment = grant_role(user, "ACCOUNTANT")
        link("ACCOUNTANT", "fiscal.period.view")
        UserRoleAssignment.objects.filter(pk=assignment.pk).update(
            start_at=self.now - timezone.timedelta(days=2),
            end_at=self.now - timezone.timedelta(days=1),
        )
        # Idempotent settlement (inline test simulation of §14.3): the
        # in-memory instance is stale after the window UPDATE, so re-read
        # the persisted end_at before closing the row.
        assignment.refresh_from_db()
        UserRoleAssignment.objects.filter(pk=assignment.pk).update(
            revoked_at=assignment.end_at, revocation_kind="EXPIRED", revoked_by=None,
        )
        UserRoleAssignment.objects.create(user=user, role=assignment.role)
        decision = self.resolve(user, "fiscal.period.view")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "ROLE_GRANT")

    def test_future_dated_assignment_never_grants(self):
        user = User.objects.create_user(username="future-user")
        assignment = grant_role(user, "ACCOUNTANT")
        link("ACCOUNTANT", "fiscal.period.view")
        assignment.start_at = self.now + timezone.timedelta(days=1)
        assignment.save(update_fields=["start_at"])
        decision = self.resolve(user, "fiscal.period.view")
        self.assertEqual(decision.reason, "NO_GRANT")

    def test_override_window_expiry_disables_allow(self):
        user = User.objects.create_user(username="window-user")
        allow_override(
            user,
            "cash.cashaccount.view",
            start_at=self.now - timezone.timedelta(days=2),
            end_at=self.now - timezone.timedelta(days=1),
        )
        decision = self.resolve(user, "cash.cashaccount.view")
        self.assertEqual(decision.reason, "NO_GRANT")


class ScopeGateTests(ResolverTestBase):
    def test_r19_warehouse_required_without_scope_denied(self):
        user = User.objects.create_user(username="wk-noscope")
        grant_role(user, "WAREHOUSE_KEEPER")
        link("WAREHOUSE_KEEPER", "inventory.movement.view")
        decision = self.resolve(user, "inventory.movement.view")
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    def test_r20_outside_assigned_warehouse_denied(self):
        user = User.objects.create_user(username="wk-wrongwh")
        grant_role(user, "WAREHOUSE_KEEPER")
        link("WAREHOUSE_KEEPER", "inventory.movement.view")
        assigned = Warehouse.objects.create(name="Assigned WH")
        other = Warehouse.objects.create(name="Other WH")
        UserWarehouseScope.objects.create(user=user, warehouse=assigned)
        decision = self.resolve(user, "inventory.movement.view", resource=other)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    def test_r21_explicit_allow_cannot_bypass_scope(self):
        user = User.objects.create_user(username="wk-allow-noscope")
        grant_role(user, "WAREHOUSE_KEEPER")
        link("WAREHOUSE_KEEPER", "inventory.movement.view")
        allow_override(user, "inventory.movement.view")
        decision = self.resolve(user, "inventory.movement.view")
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    def test_r22_accountant_warehouse_required_without_scope_denied(self):
        user = User.objects.create_user(username="acc-wr")
        grant_role(user, "ACCOUNTANT")
        link("ACCOUNTANT", "inventory.movement.view")
        decision = self.resolve(user, "inventory.movement.view")
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    def test_r23_assigned_warehouse_grants(self):
        user = User.objects.create_user(username="wk-ok")
        grant_role(user, "WAREHOUSE_KEEPER")
        link("WAREHOUSE_KEEPER", "inventory.movement.view")
        assigned = Warehouse.objects.create(name="Assigned WH 2")
        UserWarehouseScope.objects.create(user=user, warehouse=assigned)
        decision = self.resolve(user, "inventory.movement.view", resource=assigned)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "ROLE_GRANT")

    def test_r24_none_policy_needs_no_scope(self):
        user = User.objects.create_user(username="none-policy")
        grant_role(user, "ACCOUNTANT")
        link("ACCOUNTANT", "fiscal.period.view")
        decision = self.resolve(user, "fiscal.period.view")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "ROLE_GRANT")

    def test_object_required_self_scope_success(self):
        user = User.objects.create_user(username="self-scope")
        allow_override(user, "security.account.view_own")
        decision = self.resolve(user, "security.account.view_own", resource=user)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "USER_ALLOW")

    def test_object_required_other_target_denied(self):
        user = User.objects.create_user(username="self-scope-fail")
        other = User.objects.create_user(username="other-user")
        allow_override(user, "security.account.view_own")
        decision = self.resolve(user, "security.account.view_own", resource=other)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    def test_object_required_role_grant_self_scope(self):
        """security.mfa.enroll_own is the second self-scope key; role
        holders (ACCOUNTANT seeded) pass scope only for themselves."""
        user = User.objects.create_user(username="self-scope-role")
        grant_role(user, "ACCOUNTANT")
        link("ACCOUNTANT", "security.mfa.enroll_own")
        decision = self.resolve(user, "security.mfa.enroll_own", resource=user)
        self.assertTrue(decision.allowed)
        other = User.objects.create_user(username="not-self")
        second = self.resolve(user, "security.mfa.enroll_own", resource=other)
        self.assertEqual(second.reason, "SCOPE_DENIED")

    def test_target_bound_operation_requires_persisted_target_even_via_role(self):
        user = User.objects.create_user(username="target-required")
        grant_role(user, "WAREHOUSE_KEEPER")
        link("WAREHOUSE_KEEPER", "inventory.movement.view")
        UserWarehouseScope.objects.create(
            user=user,
            warehouse=Warehouse.objects.create(name="Assigned WH 3"),
        )
        decision = self.resolve(user, "inventory.movement.view", resource=None)
        self.assertEqual(decision.reason, "SCOPE_DENIED")

    def test_target_bound_rejects_non_persisted_or_wrong_kind(self):
        user = User.objects.create_user(username="wrong-kind")
        grant_role(user, "WAREHOUSE_KEEPER")
        link("WAREHOUSE_KEEPER", "inventory.movement.view")
        UserWarehouseScope.objects.create(
            user=user,
            warehouse=Warehouse.objects.create(name="Assigned WH 4"),
        )
        for bad in (None, "warehouse-pk-as-string", self.user):
            decision = self.resolve(user, "inventory.movement.view", resource=bad)
            self.assertEqual(decision.reason, "SCOPE_DENIED", repr(bad))


class FailClosedTests(ResolverTestBase):
    def test_r25_db_failure_denies_and_logs(self):
        user = User.objects.create_user(username="db-failure")
        grant_role(user, "ACCOUNTANT")
        link("ACCOUNTANT", "fiscal.period.view")

        class ExplodingManager:
            def filter(self, *a, **k):
                raise RuntimeError("simulated database failure")

        with patch.object(authorization, "Permission") as fake:
            fake.objects = ExplodingManager()
            with self.assertLogs("security.authorization", level="ERROR"):
                decision = self.resolve(user, "fiscal.period.view")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "FAIL_CLOSED")

    def test_scope_lookup_failure_denies(self):
        user = User.objects.create_user(username="scope-failure")
        grant_role(user, "WAREHOUSE_KEEPER")
        link("WAREHOUSE_KEEPER", "inventory.movement.view")
        assigned = Warehouse.objects.create(name="Assigned WH 5")
        UserWarehouseScope.objects.create(user=user, warehouse=assigned)
        with patch.object(
            authorization.UserWarehouseScope.objects, "filter",
            side_effect=RuntimeError("simulated scope lookup failure"),
        ):
            with self.assertLogs("security.authorization", level="ERROR"):
                decision = self.resolve(
                    user, "inventory.movement.view", resource=assigned
                )
        self.assertEqual(decision.reason, "FAIL_CLOSED")

    def test_no_exception_escapes_the_resolver(self):
        user = User.objects.create_user(username="exp-escape")
        with patch.object(
            authorization, "_has_active_role",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertLogs("security.authorization", level="ERROR"):
                decision = self.resolve(user, "fiscal.period.view")
        self.assertEqual(decision.reason, "FAIL_CLOSED")


class AuthContextFromRequestTests(TestCase):
    def _raw_request(self, *, user=None, session=None, basic_auth=False):
        """A raw Django request bearing only server-side facts.

        AuthContext.from_request reads request.user, request.session and
        request.successful_authenticator; DRF's Request wrapping is part of
        W0-2B wiring, so the evidence-derivation logic is proven here on
        the raw request objects it actually reads.
        """
        from django.test import RequestFactory
        from rest_framework.authentication import BasicAuthentication

        request = RequestFactory().get("/api/v1/security/me/")
        if session is not None:
            request.session = session
        if user is not None:
            request.user = user
        if basic_auth:
            request.successful_authenticator = BasicAuthentication()
        return request

    def test_session_authenticated_request_derives_trusted_session(self):
        from importlib import import_module

        from django.conf import settings as dj_settings
        from django.test import Client

        User.objects.create_user(
            username="ctx-session", password="Strong-test-password-123"
        )
        client = Client()
        self.assertTrue(
            client.login(username="ctx-session", password="Strong-test-password-123")
        )
        user = User.objects.get(username="ctx-session")

        engine = import_module(dj_settings.SESSION_ENGINE)
        session = engine.SessionStore(
            session_key=client.cookies["sessionid"].value
        )
        self.assertEqual(session.get("_auth_user_id"), str(user.pk))

        request = self._raw_request(user=user, session=session)
        ctx = AuthContext.from_request(request)
        self.assertIsNotNone(ctx.session_user_id)
        self.assertFalse(ctx.is_basic_only)
        self.assertTrue(ctx.is_valid_for(user, timezone.now()))

    def test_basic_only_request_has_no_session_evidence(self):
        user = User.objects.create_user(username="ctx-basic")
        request = self._raw_request(user=user, basic_auth=True)
        ctx = AuthContext.from_request(request)
        self.assertTrue(ctx.is_basic_only)
        self.assertIsNone(ctx.session_user_id)
        self.assertFalse(ctx.requires_mfa)

    def test_request_without_session_engine_support_fails_closed(self):
        """No session attribute at all: no evidence, fail closed."""
        user = User.objects.create_user(username="ctx-bare")
        request = SimpleNamespace(user=user, successful_authenticator=None)
        ctx = AuthContext.from_request(request)
        self.assertIsNone(ctx.session_user_id)
        self.assertFalse(ctx.is_basic_only)
        self.assertFalse(ctx.is_valid_for(user, timezone.now()))


class DormancyStructuralTests(TestCase):
    """§24.2: resolver is dormant — zero view wiring, zero settings change."""

    VIEW_IMPORT_PATTERN = (
        r"(^|\n)\s*(from\s+security(\.[a-z_]+)*\s+import[^\n]*\bauthorization\b"
        r"|from\s+security\.authorization\s+import"
        r"|import\s+security\.authorization)"
    )

    def _iter_view_modules(self):
        import inspect
        import os

        from django.apps import apps

        view_sources = []
        for config in apps.get_app_configs():
            module_dir = os.path.dirname(inspect.getfile(config.module))
            views_py = os.path.join(module_dir, "views.py")
            views_pkg = os.path.join(module_dir, "views")
            if os.path.isfile(views_py):
                view_sources.append((config.name, views_py))
            elif os.path.isdir(views_pkg):
                for entry in sorted(os.listdir(views_pkg)):
                    if entry.endswith(".py"):
                        view_sources.append(
                            (config.name, os.path.join(views_pkg, entry))
                        )
        return view_sources

    def test_no_installed_app_view_module_imports_authorization(self):
        import re

        view_sources = self._iter_view_modules()
        self.assertTrue(view_sources)  # the scan itself must be meaningful
        pattern = re.compile(self.VIEW_IMPORT_PATTERN)
        for app_name, path in view_sources:
            with open(path, encoding="utf-8", errors="replace") as fh:
                source = fh.read()
            self.assertIsNone(
                pattern.search(source),
                f"{app_name} views module must not import the dormant resolver ({path})",
            )

    def test_drf_settings_untouched(self):
        from django.conf import settings

        self.assertEqual(
            list(settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]),
            [
                "rest_framework.authentication.SessionAuthentication",
                "rest_framework.authentication.BasicAuthentication",
            ],
        )
        self.assertEqual(
            list(settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]),
            ["security.permissions.IsAuthenticatedForERP"],
        )

    def test_resolver_module_contains_no_view_wiring(self):
        """The lazy BasicAuthentication isinstance check inside
        AuthContext.from_request is authentication-evidence classification,
        not view wiring; DRF view machinery must be absent entirely."""
        import inspect

        source = inspect.getsource(authorization)
        for forbidden in (
            "APIView", "api_view", "viewsets", "ViewSet",
            "permission_classes", "authentication_classes",
            "DEFAULT_PERMISSION", "@permission",
        ):
            self.assertNotIn(forbidden, source)

    def test_decision_type_is_explicit(self):
        decision = PermissionDecision(allowed=False, reason="X")
        self.assertFalse(decision.allowed)
        self.assertEqual(str(decision), "DENY:X")
