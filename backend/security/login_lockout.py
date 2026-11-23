"""W0-2D persistent account lockout and privacy-preserving login history."""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connections, transaction
from django.utils import timezone

from security.mfa_models import (
    SecurityAccountLockout,
    SecurityLoginAttempt,
    SecurityLoginAttemptOutcome,
    SecurityLoginSession,
)
from security.models import AuditAction, AuditEvent
from security.request_context import get_current_request

PASSWORD_FAILURE_LIMIT = 5
PASSWORD_COUNTER_RESET = timedelta(minutes=15)
ACCOUNT_LOCK_DURATION = timedelta(minutes=15)
SQLITE_LOCK_RETRIES = 5


class AccountCurrentlyLocked(RuntimeError):
    """Raised when a successful authentication races with an active lock."""


def _fingerprint(purpose: str, value: str) -> str:
    secret = str(settings.SECRET_KEY).encode("utf-8")
    payload = (purpose + "\x00" + value).encode("utf-8", errors="replace")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def username_fingerprint(username) -> str:
    value = username.strip() if isinstance(username, str) else ""
    return _fingerprint("username", value)


def request_source_fingerprint(request) -> str:
    """Fingerprint the socket peer; never trust caller-controlled forwarded headers."""
    if request is None:
        request = get_current_request()
    meta = getattr(request, "META", {}) if request is not None else {}
    remote = str(meta.get("REMOTE_ADDR") or "unknown")[:128]
    return _fingerprint("source", remote)


def find_user_for_login(username):
    """Resolve the configured natural key without exposing lookup results to callers."""
    if not isinstance(username, str) or not username:
        return None
    User = get_user_model()
    try:
        return User._default_manager.get_by_natural_key(username)
    except User.DoesNotExist:
        return None


def is_account_locked(user, *, at=None) -> bool:
    if user is None or getattr(user, "pk", None) is None:
        return False
    now = at or timezone.now()
    return SecurityAccountLockout.objects.filter(
        user_id=user.pk, locked_until__gt=now
    ).exists()


def login_failure_rate():
    """Reuse the existing security_login DRF rate; no new numeric policy is invented."""
    configured = getattr(settings, "REST_FRAMEWORK", {}).get("DEFAULT_THROTTLE_RATES", {})
    rate = configured.get("security_login")
    if not isinstance(rate, str) or "/" not in rate:
        raise RuntimeError("REST_FRAMEWORK.DEFAULT_THROTTLE_RATES.security_login is required")
    count_text, period_text = rate.split("/", 1)
    try:
        count = int(count_text.strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError("security_login rate must start with a positive integer") from exc
    period = period_text.strip().lower()
    duration = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }.get(period[:1])
    if count < 1 or duration is None:
        raise RuntimeError("security_login rate must be a positive bounded DRF rate")
    return count, timedelta(seconds=duration)


def is_login_rate_limited(username, request, *, at=None) -> bool:
    """Enforce the existing login-failure budget independently per account and source."""
    now = at or timezone.now()
    limit, window = login_failure_rate()
    cutoff = now - window
    name_digest = username_fingerprint(username)
    source_digest = request_source_fingerprint(request)
    recent = SecurityLoginAttempt.objects.filter(
        occurred_at__gte=cutoff,
        outcome__in=(
            SecurityLoginAttemptOutcome.PASSWORD_FAILED,
            SecurityLoginAttemptOutcome.LOCKED,
        ),
    )
    return (
        recent.filter(username_digest=name_digest).count() >= limit
        or recent.filter(source_digest=source_digest).count() >= limit
    )


def _retry_sqlite_lock(operation):
    connection = connections["default"]
    attempts = SQLITE_LOCK_RETRIES if connection.vendor == "sqlite" else 1
    for number in range(attempts):
        try:
            return operation()
        except DatabaseError as exc:
            message = str(exc).lower()
            retryable = connection.vendor == "sqlite" and (
                "locked" in message or "busy" in message
            )
            if not retryable or number + 1 >= attempts:
                raise
            time.sleep(0.025 * (number + 1))
    raise RuntimeError("unreachable SQLite lock retry state")


def _lock_user_row(user):
    if user is not None and getattr(user, "pk", None) is not None:
        get_user_model()._default_manager.select_for_update().only("pk").get(pk=user.pk)


def _record_attempt(*, user, username, request, outcome, at, failure_count=None, reason=""):
    name_digest = username_fingerprint(username)
    source_digest = request_source_fingerprint(request)
    row = SecurityLoginAttempt.objects.create(
        user=user,
        username_digest=name_digest,
        source_digest=source_digest,
        outcome=outcome,
        occurred_at=at,
    )
    if outcome != SecurityLoginAttemptOutcome.SUCCESS:
        AuditEvent.objects.create(
            user=None,
            action=AuditAction.LOGIN_FAILED,
            entity="AUTHENTICATION",
            entity_id=name_digest,
            reason=reason[:500],
            new_state={
                "attempt_id": row.pk,
                "user_id": user.pk if user is not None else None,
                "source_digest": source_digest,
                "outcome": outcome,
                "failed_password_attempts": failure_count,
            },
        )
    return row


def _record_password_failure_once(*, user, username, request, at):
    with transaction.atomic():
        if user is not None and getattr(user, "pk", None) is not None:
            _lock_user_row(user)

        state = None
        newly_locked = False
        failure_count = None
        outcome = SecurityLoginAttemptOutcome.PASSWORD_FAILED

        if user is not None and getattr(user, "is_active", False):
            state, _ = SecurityAccountLockout.objects.select_for_update().get_or_create(user=user)
            if state.locked_until is not None and state.locked_until > at:
                outcome = SecurityLoginAttemptOutcome.LOCKED
            else:
                expired_window = (
                    state.last_failed_at is None
                    or at - state.last_failed_at >= PASSWORD_COUNTER_RESET
                    or (state.locked_until is not None and state.locked_until <= at)
                )
                if expired_window:
                    state.failed_password_attempts = 0
                    state.locked_until = None

                state.failed_password_attempts = min(
                    PASSWORD_FAILURE_LIMIT, state.failed_password_attempts + 1
                )
                state.last_failed_at = at
                failure_count = state.failed_password_attempts
                if failure_count >= PASSWORD_FAILURE_LIMIT:
                    state.locked_until = at + ACCOUNT_LOCK_DURATION
                    newly_locked = True
                state.save(update_fields=[
                    "failed_password_attempts", "last_failed_at", "locked_until", "updated_at"
                ])

        _record_attempt(
            user=user, username=username, request=request, outcome=outcome, at=at,
            failure_count=failure_count, reason="PASSWORD_AUTHENTICATION_FAILED",
        )
        if newly_locked:
            # Revoke every registered session in the same transaction as
            # the account lock. A timed unlock must never revive a previously
            # admitted (possibly stolen) session.
            revoked_sessions = SecurityLoginSession.objects.filter(
                user=user,
                revoked_at__isnull=True,
            ).update(
                revoked_at=at,
                revoke_reason="ACCOUNT_LOCKED",
            )
            AuditEvent.objects.create(
                user=None,
                action=AuditAction.ACCOUNT_LOCKED,
                entity="ACCOUNT",
                entity_id=str(user.pk),
                reason="Five consecutive failed password attempts",
                new_state={
                    "user_id": user.pk,
                    "failed_password_attempts": PASSWORD_FAILURE_LIMIT,
                    "locked_until": state.locked_until.isoformat(),
                    "revoked_sessions": revoked_sessions,
                },
            )
        return {
            "outcome": outcome,
            "failed_password_attempts": failure_count,
            "locked_until": state.locked_until if state is not None else None,
        }


def record_password_failure(user, username, request, *, at=None):
    """Persist one failed password authentication and apply the approved policy."""
    now = at or timezone.now()
    return _retry_sqlite_lock(
        lambda: _record_password_failure_once(
            user=user, username=username, request=request, at=now
        )
    )


def _record_non_password_attempt_once(*, user, username, request, outcome, at, reason):
    with transaction.atomic():
        return _record_attempt(
            user=user, username=username, request=request, outcome=outcome,
            at=at, reason=reason,
        )


def record_locked_login(user, username, request, *, at=None):
    now = at or timezone.now()
    return _retry_sqlite_lock(
        lambda: _record_non_password_attempt_once(
            user=user, username=username, request=request,
            outcome=SecurityLoginAttemptOutcome.LOCKED, at=now,
            reason="LOGIN_BLOCKED_BY_ACTIVE_ACCOUNT_LOCK",
        )
    )


def record_mfa_failure(user, username, request, *, at=None):
    now = at or timezone.now()
    return _retry_sqlite_lock(
        lambda: _record_non_password_attempt_once(
            user=user, username=username, request=request,
            outcome=SecurityLoginAttemptOutcome.MFA_FAILED, at=now,
            reason="MFA_AUTHENTICATION_FAILED",
        )
    )


def _clear_failures_once(user, *, at, require_unlocked):
    with transaction.atomic():
        _lock_user_row(user)
        state = SecurityAccountLockout.objects.select_for_update().filter(user=user).first()
        if state is None:
            return True
        if require_unlocked and state.locked_until is not None and state.locked_until > at:
            return False
        if state.failed_password_attempts or state.last_failed_at is not None or state.locked_until is not None:
            state.failed_password_attempts = 0
            state.last_failed_at = None
            state.locked_until = None
            state.save(update_fields=[
                "failed_password_attempts", "last_failed_at", "locked_until", "updated_at"
            ])
        return True


def clear_failures_after_basic_auth(user, *, at=None) -> bool:
    """A valid non-MFA Basic request resets failures only when no active lock exists."""
    now = at or timezone.now()
    return _retry_sqlite_lock(
        lambda: _clear_failures_once(user, at=now, require_unlocked=True)
    )


def record_login_success(user, username, request, *, at=None):
    """Reset consecutive password failures after successful session admission."""
    now = at or timezone.now()

    def operation():
        with transaction.atomic():
            _lock_user_row(user)
            state = SecurityAccountLockout.objects.select_for_update().filter(user=user).first()
            if state is not None and state.locked_until is not None and state.locked_until > now:
                raise AccountCurrentlyLocked()
            if state is not None:
                state.failed_password_attempts = 0
                state.last_failed_at = None
                state.locked_until = None
                state.save(update_fields=[
                    "failed_password_attempts", "last_failed_at", "locked_until", "updated_at"
                ])
            _record_attempt(
                user=user, username=username, request=request,
                outcome=SecurityLoginAttemptOutcome.SUCCESS, at=now,
            )
            return True

    return _retry_sqlite_lock(operation)


def unlock_account(user, actor, *, reason, at=None):
    """GM-authorized early unlock with a mandatory auditable reason."""
    now = at or timezone.now()
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("an unlock reason is required")
    reason = reason.strip()[:500]

    with transaction.atomic():
        _lock_user_row(user)
        state = SecurityAccountLockout.objects.select_for_update().filter(user=user).first()
        if state is None or state.locked_until is None or state.locked_until <= now:
            return None
        previous = {
            "failed_password_attempts": state.failed_password_attempts,
            "locked_until": state.locked_until.isoformat(),
        }
        state.failed_password_attempts = 0
        state.last_failed_at = None
        state.locked_until = None
        state.save(update_fields=[
            "failed_password_attempts", "last_failed_at", "locked_until", "updated_at"
        ])
        AuditEvent.objects.create(
            user=actor,
            action=AuditAction.ACCOUNT_UNLOCKED,
            entity="ACCOUNT",
            entity_id=str(user.pk),
            reason=reason,
            previous_state=previous,
            new_state={
                "user_id": user.pk,
                "failed_password_attempts": 0,
                "locked_until": None,
            },
        )
        return state
